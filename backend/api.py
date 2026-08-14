"""
통화 API 서버.

chat.py 가 파이썬으로 직접 부르던 것을 HTTP로 노출한다.
React 화면(D5-B)이 이 API만 보고 동작하도록 응답 형태를 고정한다.

    python tools/serve.py
    http://localhost:8000/docs  ← 브라우저에서 바로 테스트 가능
"""

from collections import Counter, defaultdict, deque
from datetime import date, datetime, timedelta
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import admin as admin_mod
import age_timeline
import db
import elevenlabs_stt
import elevenlabs_tts
import invites as inv_mod
import linking as link_mod
import llm
import medication as med_mod
import memories as mem_mod
import nettest as nettest_mod
import persona_voice as voice_mod
import report as report_mod
import schedules as sched_mod
import signaling
import stt as stt_mod
import tts_proxy
from analysis.observation_catalog import SIGNALS
from conversation import Session
from storage import (
    ALIGNED_FACES_DIR,
    AGE_CANDIDATES_DIR,
    FACES_ROOT,
    FINAL_AGE_PATH_DIR,
    FRONTEND_DIST,
    LOOPS_DIR,
    MORPH_PATH,
    MEMORY_PHOTOS_ROOT,
    PERSONAS_ROOT,
    ROOT,
    SOURCE_FACES_DIR,
    ensure_directories,
    ensure_persona_face_directories,
)

FACES_DIR = ALIGNED_FACES_DIR
MEDIA_DIR = FACES_ROOT
MORPH = MORPH_PATH

app = FastAPI(title="기억이음 Call API", version="0.1.0")

# 개발 중 Vite 서버만 다른 출처다. 배포에서는 React와 API가 같은 출처다.
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
cors_origins.extend(
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_directories()
# 로컬·배포 모두 기존 통화 DB를 지우지 않고 새 컬럼만 보강한다. 배포 시작점은
# DB가 이미 있으면 init_db.py를 건너뛰므로 API 자체가 마이그레이션을 맡아야 한다.
with db.connect() as schema_conn:
    db.init_schema(schema_conn)
app.mount("/faces", StaticFiles(directory=FACES_DIR), name="faces")
app.mount(
    "/identity-faces",
    StaticFiles(directory=SOURCE_FACES_DIR),
    name="identity-faces",
)
app.mount(
    "/age-candidates",
    StaticFiles(directory=AGE_CANDIDATES_DIR),
    name="age-candidates",
)
# 모핑 영상(morph.mp4)을 내보낸다. 브라우저가 구간 요청을 하므로
# StaticFiles 가 Range 헤더를 처리해 준다.
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount(
    "/persona-assets",
    StaticFiles(directory=PERSONAS_ROOT),
    name="persona-assets",
)
app.mount(
    "/memory-photos",
    StaticFiles(directory=MEMORY_PHOTOS_ROOT),
    name="memory-photos",
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(self)"
    return response

# 진행 중인 통화. MVP는 단일 프로세스라 메모리에 둔다.
SESSIONS: dict[str, Session] = {}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


TTS_RATE_LIMIT_PER_MINUTE = _positive_int_env(
    "TTS_RATE_LIMIT_PER_MINUTE", 6
)
TTS_GLOBAL_RATE_LIMIT_PER_MINUTE = _positive_int_env(
    "TTS_GLOBAL_RATE_LIMIT_PER_MINUTE", 12
)
TTS_MAX_CONCURRENT = _positive_int_env("TTS_MAX_CONCURRENT", 1)
_TTS_RATE_WINDOW_SECONDS = 60.0
_tts_rate_lock = threading.Lock()
_tts_rate_events: dict[str, deque[float]] = defaultdict(deque)
_tts_global_rate_events: deque[float] = deque()
_tts_rate_last_cleanup = 0.0
_tts_capacity = threading.BoundedSemaphore(TTS_MAX_CONCURRENT)


# ------------------------------------------------------------------ 스키마

class StartCallRequest(BaseModel):
    elder_id: str = "elder_001"
    # 통화 상대. 비우면 등록이 끝난 첫 사람과 연결한다.
    persona_id: str | None = None


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class DeviceRegistration(BaseModel):
    """통화를 걸거나 받을 기기. device_id 는 클라이언트가 만들어 보관한다."""

    device_id: str = Field(min_length=8, max_length=64)
    elder_id: str = "elder_001"
    role: Literal["elder", "guardian"]
    # 보호자 기기는 자기가 어느 가족인지 밝혀야 어르신이 고른 사람에게 벨이 간다.
    persona_id: str | None = None
    label: str | None = Field(default=None, max_length=40)


class InviteRequest(BaseModel):
    elder_id: str = "elder_001"
    persona_id: str | None = None
    from_device: str | None = Field(default=None, max_length=64)


class InviteDeviceAction(BaseModel):
    device_id: str | None = Field(default=None, max_length=64)
    reason: Literal["media_permission_denied"] | None = None


class TakeOverRequest(BaseModel):
    """벨이 울리는 중에 넘길 때만 사유를 받는다.

    거절·무응답은 서버가 이미 알고 있으므로 덮어쓰지 않는다.
    """

    reason: Literal["transport_failed", "media_permission_denied"] | None = None


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    rate: float = Field(default=0.92, ge=0.75, le=1.15)
    persona_id: str | None = Field(default=None, pattern=r"^persona_[a-z0-9_]+$")


class VoiceConsentRequest(BaseModel):
    elder_id: str = "elder_001"
    accepted: bool


class VoicePreviewRequest(BaseModel):
    elder_id: str = "elder_001"
    text: str = Field(min_length=1, max_length=180)
    rate: float = Field(default=0.92, ge=0.75, le=1.15)


class VoiceApproveRequest(BaseModel):
    elder_id: str = "elder_001"


class TTSBridgeRegistration(BaseModel):
    service_url: str = Field(min_length=1, max_length=2048)


class EndCallRequest(BaseModel):
    reason: str = "user_ended"


@app.post("/api/stt")
async def transcribe_speech(
    audio: UploadFile = File(...),
    lang: str = Query(default="ko-KR", max_length=16),
):
    """Android Chrome의 불안정한 Web Speech를 보완하는 짧은 음성 전사."""
    mime_type = (audio.content_type or "application/octet-stream").lower()
    if not mime_type.startswith("audio/") and mime_type != "video/webm":
        raise HTTPException(415, "지원하지 않는 음성 형식입니다")
    payload = await audio.read(stt_mod.MAX_AUDIO_BYTES + 1)
    if len(payload) > stt_mod.MAX_AUDIO_BYTES:
        raise HTTPException(413, "음성이 너무 깁니다")
    try:
        return stt_mod.transcribe(payload, mime_type, lang=lang)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except stt_mod.TranscriptionUnavailable as exc:
        raise HTTPException(503, "음성 인식에 잠시 연결하지 못했습니다") from exc


@app.post("/api/stt/realtime-token")
def create_realtime_stt_token():
    """Issue a short-lived Scribe token without exposing the permanent key."""
    try:
        return elevenlabs_stt.create_realtime_token()
    except elevenlabs_stt.ElevenLabsSTTNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except elevenlabs_stt.ElevenLabsSTTUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


class NewElder(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    preferred_call_name: str = Field(default="할아버지", max_length=30)
    persona_name: str = Field(default="가족", max_length=30)
    relationship: str = Field(default="손자", max_length=20)


class LinkVerify(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class PersonaPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=30)
    relationship_type: str | None = Field(default=None, max_length=20)
    elder_calls_family: str | None = Field(default=None, max_length=30)
    family_calls_elder: str | None = Field(default=None, max_length=30)
    tone: str | None = Field(default=None, max_length=500)
    frequent_phrases: list[str] | None = None
    forbidden_phrases: list[str] | None = None
    sensitive_policy: str | None = Field(default=None, max_length=300)
    call_style_code: str | None = Field(default=None, pattern=r"^[CB][EP][MO][LG]$")
    call_style_name: str | None = Field(default=None, max_length=40)
    call_style_scores: dict | None = None
    call_style_answers: dict[str, str] | None = None


class ElderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    preferred_call_name: str | None = Field(default=None, max_length=30)
    speech_wait_time_ms: int | None = Field(default=None, ge=500, le=8000)
    hearing_support: bool | None = None
    vision_support: bool | None = None
    anxiety_triggers: list[str] | None = None
    calming_phrases: list[str] | None = None
    frequent_questions: list[str] | None = None


class AgePlanRequest(BaseModel):
    current_age: int | None = Field(default=None, ge=18, le=100)
    current_photo: str = Field(min_length=1, max_length=180)
    birth_date: str | None = Field(default=None, max_length=10)
    current_photo_date: str | None = Field(default=None, max_length=10)
    biological_sex: Literal["unspecified", "female", "male"] = "unspecified"
    population_group: Literal[
        "unspecified", "korean", "east_asian", "other"
    ] = "unspecified"


class AgeCandidateSelection(BaseModel):
    age: int = Field(ge=1, le=100)
    filename: str = Field(min_length=1, max_length=180)


class AgePathRefinementRequest(BaseModel):
    older_age: int = Field(ge=2, le=100)
    younger_age: int = Field(ge=1, le=99)


class MemoryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    date_text: str = Field(default="", max_length=60)
    location: str = Field(default="", max_length=60)
    participants: list[str] = Field(default_factory=list)
    status: str = Field(default="verified",
                        pattern="^(verified|partial|unverified|prohibited)$")
    conversation_allowed: bool = True
    note: str | None = None
    photo_url: str | None = None
    happened_year: int | None = Field(default=None, ge=1800, le=2100)


class MemoryPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    date_text: str | None = None
    location: str | None = None
    participants: list[str] | None = None
    status: str | None = Field(
        default=None, pattern="^(verified|partial|unverified|prohibited)$")
    conversation_allowed: bool | None = None
    note: str | None = None
    photo_url: str | None = None
    happened_year: int | None = Field(default=None, ge=1800, le=2100)


class RecallReview(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    title: str | None = None
    description: str | None = None
    date_text: str | None = None
    location: str | None = None
    status: str = Field(default="verified", pattern="^(verified|partial)$")
    note: str | None = None
    happened_year: int | None = Field(default=None, ge=1800, le=2100)


class ScheduleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    note: str = Field(default="", max_length=200)
    confirmed: bool = True


class SchedulePatch(BaseModel):
    title: str | None = Field(default=None, max_length=60)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    note: str | None = Field(default=None, max_length=200)
    confirmed: bool | None = None


class MedicationSignalLinkRequest(BaseModel):
    signal: str = Field(min_length=1, max_length=80)
    link_level: str = Field(default="monitoring", pattern="^(monitoring|escalation)$")
    criterion_text: str = Field(min_length=1, max_length=300)


class MedicationRequest(BaseModel):
    medication_name: str = Field(min_length=1, max_length=60)
    dosage_text: str = Field(default="1정", max_length=40)
    scheduled_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    meal_relation: str = Field(default="none", pattern="^(before|after|none)$")
    days_of_week: list[str] = Field(
        default=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])
    indication: str = Field(default="", max_length=120)
    monitoring_points: list[str] = Field(default=[])
    review_interval_days: int = Field(default=14, ge=1, le=180)
    escalation_criteria: str = Field(default="", max_length=300)
    signal_links: list[MedicationSignalLinkRequest] = Field(default=[])


class MedicationReviewRequest(BaseModel):
    review_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    severity: int = Field(ge=0, le=3)
    observed_flags: list[str | dict[str, str]] = Field(default=[])
    note: str = Field(default="", max_length=500)


class HandoverRequest(BaseModel):
    shift: str = Field(pattern="^(day|evening|night)$")
    note: str = Field(default="", max_length=1000)


class CareTaskCompleteRequest(BaseModel):
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class CareTaskDoseStatusRequest(CareTaskCompleteRequest):
    status: Literal[
        "USER_CONFIRMED", "UNCLEAR", "REFUSED", "DUPLICATE_SUSPECTED",
    ]


# ------------------------------------------------------------------ 헬퍼

def _get(call_id: str) -> Session:
    session = SESSIONS.get(call_id)
    if session is None:
        raise HTTPException(404, f"통화 {call_id} 를 찾을 수 없습니다. 이미 종료되었을 수 있습니다.")
    return session


def _enforce_tts_rate_limit(request: Request, now: float | None = None) -> None:
    """Apply a process-local sliding-window limit using Request.client.host."""
    current = time.monotonic() if now is None else now
    client = request.client.host if request.client is not None else "unknown"
    cutoff = current - _TTS_RATE_WINDOW_SECONDS

    global _tts_rate_last_cleanup
    with _tts_rate_lock:
        if current - _tts_rate_last_cleanup >= _TTS_RATE_WINDOW_SECONDS:
            for key, events in list(_tts_rate_events.items()):
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    _tts_rate_events.pop(key, None)
            _tts_rate_last_cleanup = current

        while _tts_global_rate_events and _tts_global_rate_events[0] <= cutoff:
            _tts_global_rate_events.popleft()
        if len(_tts_global_rate_events) >= TTS_GLOBAL_RATE_LIMIT_PER_MINUTE:
            retry_after = max(
                1,
                math.ceil(
                    _TTS_RATE_WINDOW_SECONDS
                    - (current - _tts_global_rate_events[0])
                ),
            )
            raise HTTPException(
                status_code=429,
                detail="Global TTS request rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        events = _tts_rate_events[client]
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= TTS_RATE_LIMIT_PER_MINUTE:
            retry_after = max(
                1,
                math.ceil(_TTS_RATE_WINDOW_SECONDS - (current - events[0])),
            )
            raise HTTPException(
                status_code=429,
                detail="TTS request rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        events.append(current)
        _tts_global_rate_events.append(current)


def _acquire_tts_capacity() -> None:
    if not _tts_capacity.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="TTS synthesizer is busy",
            headers={"Retry-After": "3"},
        )


def _morph_url(persona_id: str | None = None) -> str | None:
    """페르소나 등록 시 미리 만들어 둔 모핑 영상. 없으면 이미지 전환으로 대체된다."""
    paths = ensure_persona_face_directories(persona_id)
    if not paths.morph.exists():
        return None
    prefix = "/media" if paths.legacy else f"/persona-assets/{paths.persona_id}"
    return f"{prefix}/{paths.morph.name}?v={paths.morph.stat().st_mtime_ns}"


def _loop_urls(persona_id: str | None = None) -> dict[str, str]:
    """표정 루프. 모핑이 끝난 뒤 상황에 맞는 것을 반복 재생한다.

    폴더에 있는 파일을 그대로 알려주고, 어떤 것을 언제 틀지는 화면이 정한다.
    루프를 나중에 추가하거나 빼도 서버는 손대지 않아도 된다.
    """
    paths = ensure_persona_face_directories(persona_id)
    if not paths.loops.exists():
        return {}
    prefix = "/media/loops" if paths.legacy else (
        f"/persona-assets/{paths.persona_id}/loops"
    )
    return {p.stem: f"{prefix}/{p.name}" for p in sorted(paths.loops.glob("*.mp4"))}


def _face_urls(persona_id: str | None = None) -> list[dict]:
    """모핑에 쓸 얼굴 단계 목록. 파일명 앞 숫자가 순서다."""
    if persona_id is None:
        aligned_dir = FACES_DIR
        final_dir = FINAL_AGE_PATH_DIR
        legacy = True
        selected_persona_id = "persona_minjun"
    else:
        face_paths = ensure_persona_face_directories(persona_id)
        aligned_dir = face_paths.aligned
        final_dir = face_paths.final_age_path
        legacy = face_paths.legacy
        selected_persona_id = face_paths.persona_id
    if not aligned_dir.exists():
        return []
    final_paths = []
    if final_dir.exists():
        final_paths = [
            path
            for path in sorted(final_dir.glob("*.png"))
            if not path.name.startswith("_")
            and path.stem.split("_", 1)[0].isdigit()
            and "_age" in path.stem.lower()
        ]

    # 새 가족은 전체 모핑 경로가 완성되기 전에도 보호자가 확정한
    # 연령 후보를 미리 볼 수 있어야 한다. 현재 사진(99_*)만 있는 동안은
    # age_plan의 선택값을 직접 반환하고, 최종 키프레임이 만들어지면
    # 기존 final_age_path가 다시 단일 기준이 된다.
    current_only = (
        not legacy
        and len(final_paths) == 1
        and final_paths[0].name.startswith("99_")
    )
    if not legacy and (not final_paths or current_only):
        try:
            plan = age_timeline.get_plan(selected_persona_id)
        except (OSError, ValueError):
            plan = {}
        preview = []
        persona_paths = ensure_persona_face_directories(selected_persona_id)
        for stage_data in plan.get("stages", []):
            selected = stage_data.get("selected")
            if not selected:
                continue
            folder = "source" if stage_data.get("kind") == "current" else "age_candidates"
            candidate = persona_paths.root / folder / selected
            if not candidate.is_file():
                continue
            preview.append({
                "stage": f"age{int(stage_data['age']):02d}",
                "url": (
                    f"/persona-assets/{selected_persona_id}/"
                    f"{folder}/{selected}"
                ),
            })
        if len(preview) > len(final_paths):
            return preview

    paths = final_paths or [
        path for path in sorted(aligned_dir.glob("*.png"))
        if not path.name.startswith("_")
    ]
    if legacy:
        url_prefix = "/faces/age_path_final" if final_paths else "/faces"
    else:
        folder = "aligned/age_path_final" if final_paths else "aligned"
        url_prefix = f"/persona-assets/{selected_persona_id}/{folder}"
    stages = []
    for path in paths:
        stage = path.stem.split("_", 1)[-1]
        stages.append({"stage": stage, "url": f"{url_prefix}/{path.name}"})
    return stages


def _persona_face_url(persona_id: str) -> str | None:
    """가족별 대표 얼굴. 준비되지 않은 가족에게 다른 사람 얼굴을 빌려주지 않는다."""
    if persona_id == "persona_minjun":
        legacy = _face_urls(persona_id)
        return legacy[-1]["url"] if legacy else None
    paths = ensure_persona_face_directories(persona_id)
    manifest = paths.root / "profile.json"
    try:
        profile_data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        profile_data = {}
    relative = Path(str(profile_data.get("representative_photo") or "")).as_posix()
    candidate = paths.root / relative
    try:
        candidate.resolve().relative_to(paths.root.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return (
            f"/persona-assets/{persona_id}/{relative}"
            f"?v={candidate.stat().st_mtime_ns}"
        )
    return None


# ------------------------------------------------------------------ 엔드포인트

@app.get("/api/health")
def health():
    return {"ok": True, "model": llm.MODEL, "active_calls": len(SESSIONS)}


@app.get("/api/tts/health")
def tts_health():
    """ElevenLabs 설정과 선택형 MuseTalk 립싱크 워커 상태를 확인한다."""
    tts_status = {
        "engine": "elevenlabs",
        "configured": bool(
            os.getenv("ELEVENLABS_API_KEY", "").strip()
            and os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        ),
        "model": os.getenv(
            "ELEVENLABS_MODEL_ID", elevenlabs_tts.DEFAULT_MODEL_ID,
        ),
    }
    try:
        return {"tts": tts_status, "lipsync": tts_proxy.health()}
    except tts_proxy.TTSUnavailable as exc:
        # 립싱크 워커가 꺼져 있어도 순수 ElevenLabs 음성 통화는 정상 경로다.
        return {"tts": tts_status, "lipsync": {"available": False, "detail": str(exc)}}


@app.post("/api/tts/bridge/register")
def register_tts_bridge(req: TTSBridgeRegistration, request: Request):
    """Register or heartbeat an authenticated HTTPS tunnel to the TTS service."""
    try:
        tts_proxy.verify_bridge_bearer(request.headers.get("Authorization"))
        status = tts_proxy.register_bridge(req.service_url)
    except tts_proxy.TTSBridgeNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except tts_proxy.TTSBridgeUnauthorized as exc:
        raise HTTPException(
            401,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except tts_proxy.TTSBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **status}


@app.post("/api/tts")
def synthesize_speech(req: TTSRequest, request: Request):
    """ElevenLabs가 만든 WAV를 브라우저에 그대로 전달한다."""
    _enforce_tts_rate_limit(request)
    _acquire_tts_capacity()
    request_id = uuid.uuid4().hex
    try:
        try:
            voice_id = voice_mod.active_voice_id(req.persona_id)
            kwargs = {"request_id": request_id}
            if voice_id:
                kwargs["voice_id"] = voice_id
            result = elevenlabs_tts.synthesize_with_metadata(
                req.text.strip(), req.rate, **kwargs,
            )
        except (
            elevenlabs_tts.ElevenLabsNotConfigured,
            elevenlabs_tts.ElevenLabsUnavailable,
        ) as exc:
            raise HTTPException(503, str(exc)) from exc
    finally:
        _tts_capacity.release()
    response_headers = {
        "Cache-Control": "no-store",
        "X-TTS-Engine": "elevenlabs",
        **result.public_headers(request_id=request_id),
    }
    return Response(
        content=result.body,
        media_type="audio/wav",
        headers=response_headers,
    )


@app.post("/api/tts/video")
def synthesize_lipsync_video(req: TTSRequest, request: Request):
    """ElevenLabs로 오디오를 만들고 로컬 MuseTalk으로 립싱크 MP4를 씌운다.

    MuseTalk이 없거나 바쁘거나 실패하면 이미 만든 ElevenLabs WAV를 그대로
    반환한다 (X-Lipsync-Fallback: audio). 오디오 자체가 실패했을 때만 503.
    """
    _enforce_tts_rate_limit(request)
    _acquire_tts_capacity()
    request_id = uuid.uuid4().hex
    try:
        try:
            voice_id = voice_mod.active_voice_id(req.persona_id)
            kwargs = {"request_id": request_id}
            if voice_id:
                kwargs["voice_id"] = voice_id
            audio_result = elevenlabs_tts.synthesize_with_metadata(
                req.text.strip(), req.rate, **kwargs,
            )
        except (
            elevenlabs_tts.ElevenLabsNotConfigured,
            elevenlabs_tts.ElevenLabsUnavailable,
        ) as exc:
            raise HTTPException(503, str(exc)) from exc

        try:
            video_result = tts_proxy.render_lipsync_with_metadata(
                audio_result.body,
                request_id=request_id,
            )
        except tts_proxy.TTSUnavailable:
            response_headers = {
                "Cache-Control": "no-store",
                "X-TTS-Engine": "elevenlabs",
                "X-Lipsync-Fallback": "audio",
                **audio_result.public_headers(request_id=request_id),
            }
            return Response(
                content=audio_result.body,
                media_type="audio/wav",
                headers=response_headers,
            )
    finally:
        _tts_capacity.release()

    response_headers = {
        "Cache-Control": "no-store",
        "X-TTS-Engine": "elevenlabs",
        "X-Audio-Duration": f"{audio_result.audio_duration_seconds:.3f}",
        "X-Generation-Seconds": f"{audio_result.generation_seconds:.3f}",
        **video_result.public_headers(request_id=request_id),
    }
    return Response(
        content=video_result.body,
        media_type=video_result.media_type,
        headers=response_headers,
    )


@app.get("/api/personas")
def call_targets(elder_id: str = "elder_001"):
    """통화 대상 목록.

    등록이 끝난 사람만 실제로 걸 수 있다.
    나머지는 얼굴 사진과 영상이 아직 없어 대기 상태로 보여준다.
    """
    family_order = {
        "persona_jeonghun": 0,
        "persona_miyeong": 1,
        "persona_minjun": 2,
        "persona_yujin": 3,
    }
    personas = sorted(
        db.personas(elder_id),
        key=lambda item: (family_order.get(item["persona_id"], 99), item["display_name"]),
    )
    return {
        "elder_id": elder_id,
        "personas": [
            {
                "persona_id": p["persona_id"],
                "display_name": p["display_name"],
                "relationship": p["relationship_type"],
                "call_style_code": p.get("call_style_code"),
                "call_style_name": p.get("call_style_name"),
                "ready": bool(p.get("active") and _persona_face_url(p["persona_id"])),
                "face": _persona_face_url(p["persona_id"]) if p.get("active") else None,
            }
            for p in personas
        ],
    }


@app.get("/api/profile")
def profile(elder_id: str = "elder_001", persona_id: str | None = None):
    """통화 시작 전 화면에 필요한 정보."""
    ctx = db.load_context(elder_id, persona_id)
    return {
        "elder": {
            "name": ctx["elder"]["name"],
            "call_name": ctx["persona"].get("family_calls_elder", "할아버지"),
            # 발화가 끝났다고 판단하기까지 기다리는 시간 (명세 NFR-03)
            "speech_wait_time_ms": ctx["elder"].get("speech_wait_time_ms") or 2000,
            "hearing_support": bool(ctx["elder"].get("hearing_support")),
            "vision_support": bool(ctx["elder"].get("vision_support")),
        },
        "persona": {
            "persona_id": ctx["persona"].get("persona_id"),
            "display_name": ctx["persona"].get("display_name"),
            "relationship": ctx["persona"].get("relationship_type"),
        },
        "faces": _face_urls(persona_id),
        "morph_url": _morph_url(persona_id),
        "loops": _loop_urls(persona_id),
        "counts": {
            "memories": len(ctx["memories"]),
            "schedules": len(ctx["schedules"]),
            "medications": len(ctx["medications"]),
        },
    }


@app.get("/api/elders")
def list_elders():
    """보호자가 돌보는 어르신 목록."""
    return {"elders": admin_mod.elders()}


@app.post("/api/elders")
def add_elder(req: NewElder):
    """어르신을 새로 등록한다. 기본 페르소나도 함께 만든다."""
    return admin_mod.create_elder(
        req.name, req.preferred_call_name, req.persona_name, req.relationship
    )


@app.post("/api/link/code")
def issue_link_code(elder_id: str = "elder_001"):
    """보호자 기기에서 연결 코드를 만든다."""
    return link_mod.issue(elder_id)


@app.post("/api/link/verify")
def verify_link_code(req: LinkVerify):
    """어르신 기기에서 코드를 입력해 연결한다."""
    try:
        return link_mod.verify(req.code)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/elders/{elder_id}/persona")
def get_persona(elder_id: str = "elder_001", persona_id: str | None = None):
    """페르소나 등록 화면에 필요한 전체 정보."""
    try:
        return dict(
            admin_mod.profile(elder_id, persona_id),
            faces=admin_mod.faces(persona_id),
            identity_photos=admin_mod.identity_photos(persona_id),
            age_plan=age_timeline.get_plan(persona_id),
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.patch("/api/elders/{elder_id}/persona")
def patch_persona(elder_id: str, req: PersonaPatch,
                  persona_id: str | None = None):
    try:
        return admin_mod.update_persona(
            elder_id, req.model_dump(exclude_none=True), persona_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.patch("/api/elders/{elder_id}/profile")
def patch_elder(elder_id: str, req: ElderPatch):
    try:
        return admin_mod.update_elder(elder_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/faces")
def list_faces(persona_id: str | None = None):
    return admin_mod.faces(persona_id)


@app.get("/api/identity-photos")
def list_identity_photos(persona_id: str | None = None):
    return admin_mod.identity_photos(persona_id)


@app.post("/api/identity-photos")
async def upload_identity_photos(files: list[UploadFile] = File(...),
                                 persona_id: str | None = None):
    """나이 변환의 신원 기준이 될 현재 얼굴 사진을 최대 6장 받는다."""
    saved, errors = [], []
    for file in files:
        try:
            saved.append(
                admin_mod.save_identity_photo(
                    file.filename or "photo", await file.read(), persona_id
                )
            )
        except ValueError as exc:
            errors.append({"file": file.filename, "error": str(exc)})
    return {
        "saved": saved,
        "errors": errors,
        "identity_photos": admin_mod.identity_photos(persona_id),
    }


@app.delete("/api/identity-photos/{name}")
def delete_identity_photo(name: str, persona_id: str | None = None):
    admin_mod.delete_identity_photo(name, persona_id)
    return {"ok": True, "identity_photos": admin_mod.identity_photos(persona_id)}


@app.get("/api/age-plan")
def get_age_plan(persona_id: str | None = None):
    """현재 나이를 마지막 지점으로 삼는 과거 얼굴 생성 계획."""
    return age_timeline.get_plan(persona_id)


@app.put("/api/age-plan")
def put_age_plan(req: AgePlanRequest, persona_id: str | None = None):
    try:
        return age_timeline.save_plan(
            req.current_age,
            req.current_photo,
            birth_date=req.birth_date,
            current_photo_date=req.current_photo_date,
            biological_sex=req.biological_sex,
            population_group=req.population_group,
            persona_id=persona_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/personas/{persona_id}/voice-profile")
def get_voice_profile(persona_id: str, elder_id: str = "elder_001"):
    try:
        return voice_mod.public_profile(persona_id, elder_id)
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/personas/{persona_id}/voice-profile")
def delete_voice_profile(persona_id: str, elder_id: str = "elder_001"):
    try:
        return voice_mod.delete_profile(persona_id, elder_id)
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(404, str(exc)) from exc
    except elevenlabs_tts.ElevenLabsNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except voice_mod.VoiceProviderUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/personas/{persona_id}/voice-consent")
def save_voice_consent(persona_id: str, req: VoiceConsentRequest):
    try:
        return voice_mod.record_consent(persona_id, req.elder_id, req.accepted)
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/personas/{persona_id}/voice-samples")
async def upload_voice_sample(
    persona_id: str,
    audio: UploadFile = File(...),
    elder_id: str = Form(default="elder_001"),
    phase: Literal["ivc", "pvc"] = Form(...),
    prompt_id: str = Form(..., max_length=80),
    duration_seconds: float = Form(..., ge=1, le=360),
    quality: str = Form(default="{}", max_length=2000),
):
    try:
        quality_data = json.loads(quality)
        if not isinstance(quality_data, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(400, "음질 측정값이 올바르지 않습니다.") from exc
    payload = await audio.read(voice_mod.MAX_SAMPLE_BYTES + 1)
    try:
        return voice_mod.save_sample(
            persona_id, elder_id, phase=phase, prompt_id=prompt_id,
            original_name=audio.filename or "recording",
            mime_type=audio.content_type or "application/octet-stream",
            payload=payload, duration_seconds=duration_seconds,
            quality=quality_data,
        )
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/personas/{persona_id}/voice/ivc")
def create_persona_ivc(persona_id: str, req: VoiceApproveRequest):
    try:
        return voice_mod.create_ivc(persona_id, req.elder_id)
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except elevenlabs_tts.ElevenLabsNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except voice_mod.VoiceProviderUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/personas/{persona_id}/voice/preview")
def preview_persona_voice(
    persona_id: str, req: VoicePreviewRequest, request: Request,
):
    _enforce_tts_rate_limit(request)
    _acquire_tts_capacity()
    try:
        voice_id = voice_mod.candidate_voice_id(persona_id, req.elder_id)
        result = elevenlabs_tts.synthesize_with_metadata(
            req.text.strip(), req.rate, request_id=uuid.uuid4().hex,
            voice_id=voice_id,
        )
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (
        elevenlabs_tts.ElevenLabsNotConfigured,
        elevenlabs_tts.ElevenLabsUnavailable,
    ) as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        _tts_capacity.release()
    return Response(
        content=result.body, media_type="audio/wav",
        headers={"Cache-Control": "no-store", **result.public_headers()},
    )


@app.post("/api/personas/{persona_id}/voice/approve")
def approve_persona_voice(persona_id: str, req: VoiceApproveRequest):
    try:
        return voice_mod.approve_ivc(persona_id, req.elder_id)
    except voice_mod.VoiceProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/age-plan/selection")
def put_age_candidate_selection(req: AgeCandidateSelection,
                                persona_id: str | None = None):
    try:
        return age_timeline.select_candidate(req.age, req.filename, persona_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/age-plan/refine")
def post_age_path_refinement(req: AgePathRefinementRequest,
                             persona_id: str | None = None):
    """Split a failed adjacent age segment without weakening quality gates."""
    try:
        return age_timeline.refine_failed_segment(
            req.older_age, req.younger_age, persona_id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/faces")
async def upload_faces(files: list[UploadFile] = File(...),
                       persona_id: str | None = None):
    """얼굴 사진 업로드.

    파일명 순서가 나이 순서가 되므로 01_, 02_ 처럼 앞에 번호를 붙여 올린다.
    """
    saved, errors = [], []
    for f in files:
        try:
            saved.append(admin_mod.save_face(f.filename, await f.read(), persona_id))
        except ValueError as e:
            errors.append({"file": f.filename, "error": str(e)})
    return {"saved": saved, "errors": errors, "faces": admin_mod.faces(persona_id)}


@app.delete("/api/faces/{name}")
def delete_face(name: str, persona_id: str | None = None):
    admin_mod.delete_face(name, persona_id)
    return {"ok": True, "faces": admin_mod.faces(persona_id)}


@app.post("/api/faces/prepare")
def prepare_faces(persona_id: str | None = None):
    """올린 사진을 3:4 세로로 자르고 눈높이를 맞춘다."""
    return admin_mod.prepare_faces(persona_id)


@app.get("/api/elders/{elder_id}/memories")
def list_memories(elder_id: str = "elder_001", status: str | None = None):
    return {
        "elder_id": elder_id,
        "memories": mem_mod.listing(elder_id, status),
        "pending_recalls": mem_mod.pending_recalls(elder_id),
    }


@app.post("/api/elders/{elder_id}/memories")
def create_memory(elder_id: str, req: MemoryRequest):
    return mem_mod.create(elder_id, req.model_dump())


@app.post("/api/elders/{elder_id}/memories/{memory_id}/photo")
async def upload_memory_photo(elder_id: str, memory_id: str,
                              file: UploadFile = File(...)):
    try:
        result = mem_mod.save_photo(
            elder_id, memory_id, file.filename or "memory.jpg", await file.read()
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.patch("/api/memories/{memory_id}")
def patch_memory(memory_id: str, req: MemoryPatch):
    try:
        return mem_mod.update(memory_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str):
    """삭제 요청된 기억은 보관하지 않는다 (명세 21장)."""
    mem_mod.delete(memory_id)
    return {"ok": True}


@app.post("/api/recalls/{utterance_id}/review")
def review_recall(utterance_id: int, req: RecallReview,
                  elder_id: str = "elder_001"):
    """통화에서 나온 미확인 회상을 보호자가 판단한다.

    승인해야만 다음 통화부터 AI 가 사실로 쓴다 (명세 FR-05).
    """
    payload = req.model_dump(exclude_none=True)
    decision = payload.pop("decision")
    note = payload.pop("note", None)
    try:
        return mem_mod.review(utterance_id, decision, elder_id, payload, note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/elders/{elder_id}/schedules")
def list_schedules(elder_id: str = "elder_001"):
    """다가오는 일정과 최근 지난 일정.

    used_in_call 이 참인 것만 AI 가 이야기한다.
    """
    return {"elder_id": elder_id, **sched_mod.listing(elder_id)}


@app.post("/api/elders/{elder_id}/schedules")
def add_schedule(elder_id: str, req: ScheduleRequest):
    sched_mod.create(elder_id, req.model_dump())
    return sched_mod.listing(elder_id)


@app.patch("/api/schedules/{schedule_id}")
def patch_schedule(schedule_id: str, req: SchedulePatch):
    try:
        return sched_mod.update(schedule_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: str):
    sched_mod.delete(schedule_id)
    return {"ok": True}


@app.get("/api/elders/{elder_id}/medications")
def list_medications(elder_id: str = "elder_001", as_of: str | None = None):
    """등록 복약, 관찰 주기, AI 근거를 한 번에 반환한다.

    연결은 담당자가 ``medication_signal_links``에 등록한 항목만 사용한다.
    약 이름이나 발화만 보고 원인 관계를 추론하지 않는다.
    """
    try:
        selected_day = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError as exc:
        raise HTTPException(400, "as_of는 YYYY-MM-DD 형식이어야 합니다.") from exc
    with db.connect() as conn:
        reviews = conn.execute(
            "SELECT * FROM medication_reviews WHERE elder_id = ? "
            "ORDER BY review_date DESC, review_id DESC", (elder_id,),
        ).fetchall()
        links = conn.execute(
            "SELECT l.* FROM medication_signal_links l JOIN medications m "
            "ON m.schedule_id = l.schedule_id WHERE m.elder_id = ? "
            "ORDER BY l.schedule_id, l.link_level, l.signal", (elder_id,),
        ).fetchall()
        calendar_start = (selected_day - timedelta(days=45)).isoformat()
        calendar_end = (selected_day + timedelta(days=45)).isoformat()
        reports = conn.execute(
            "SELECT r.call_id, r.care_summary, c.started_at FROM reports r "
            "JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND substr(c.started_at, 1, 10) BETWEEN ? AND ? "
            "ORDER BY c.started_at",
            (elder_id, calendar_start, calendar_end),
        ).fetchall()

    medications = med_mod.listing(elder_id)
    review_rows = [db._row(row) for row in reviews]
    link_rows = [db._row(row) for row in links]
    latest_by_schedule = {}
    for review in review_rows:
        latest_by_schedule.setdefault(review["schedule_id"], review)

    linked_signals = {row["signal"] for row in link_rows}
    evidence_by_signal: dict[str, list[dict]] = defaultdict(list)
    signal_dates: Counter = Counter()
    for raw_report in reports:
        report = db._row(raw_report)
        report_day = str(report.get("started_at") or "")[:10]
        for domain, observations in (report.get("care_summary") or {}).items():
            if domain == "meaningful_moments":
                continue
            for observation in observations or []:
                signal = observation.get("signal")
                if signal in linked_signals and report_day:
                    signal_dates[report_day] += 1
                if signal and report_day == selected_day.isoformat():
                    evidence_by_signal[signal].append({
                        "call_id": report["call_id"],
                        "at": observation.get("at") or report.get("started_at"),
                        "evidence": observation.get("evidence"),
                        "utterance_id": observation.get("utterance_id"),
                    })

    review_status = []
    for medication in medications:
        latest = latest_by_schedule.get(medication["schedule_id"])
        interval = int(medication.get("review_interval_days") or 14)
        latest_day = date.fromisoformat(latest["review_date"]) if latest else None
        due_on = latest_day + timedelta(days=interval) if latest_day else selected_day
        review_status.append({
            "schedule_id": medication["schedule_id"],
            "latest_review": latest,
            "review_due_on": due_on.isoformat(),
            "days_until_due": (due_on - selected_day).days,
            "review_due": due_on <= selected_day,
        })

    signal_options = []
    for signal in sorted({row["signal"] for row in link_rows}):
        spec = SIGNALS.get(signal)
        signal_options.append({
            "signal": signal,
            "label": spec.label if spec else signal,
            "evidence": evidence_by_signal.get(signal, []),
        })
    return {
        "elder_id": elder_id,
        "as_of": selected_day.isoformat(),
        "today": med_mod.status_on(elder_id, selected_day),
        "medications": medications,
        "reviews": review_rows,
        "review_status": review_status,
        "signal_links": link_rows,
        "signal_options": signal_options,
        "signal_dates": [
            {"date": day, "count": count}
            for day, count in sorted(signal_dates.items())
        ],
        "safety_notice": "시스템은 등록된 관찰 기준과 발화만 대조합니다. 원인 판단과 처방 조정은 의료진의 몫입니다.",
    }


@app.post("/api/elders/{elder_id}/medications")
def add_medication(elder_id: str, req: MedicationRequest):
    schedule_id = f"med_{uuid.uuid4().hex[:8]}"
    with db.connect() as conn:
        db.insert(conn, "medications", {
            "schedule_id": schedule_id,
            "elder_id": elder_id,
            "medication_name": req.medication_name,
            "dosage_text": req.dosage_text,
            "scheduled_time": req.scheduled_time,
            "meal_relation": req.meal_relation,
            "days_of_week": req.days_of_week,
            "indication": req.indication,
            "monitoring_points": req.monitoring_points,
            "review_interval_days": req.review_interval_days,
            "escalation_criteria": req.escalation_criteria,
            "active": 1,
        })
        for link in req.signal_links:
            if link.signal not in SIGNALS:
                continue
            db.insert(conn, "medication_signal_links", {
                "schedule_id": schedule_id,
                "signal": link.signal,
                "link_level": link.link_level,
                "criterion_text": link.criterion_text,
            })
        conn.commit()
    return {"schedule_id": schedule_id, "today": med_mod.today_status(elder_id)}


@app.post("/api/elders/{elder_id}/medications/{schedule_id}/reviews")
def add_medication_review(elder_id: str, schedule_id: str,
                          req: MedicationReviewRequest):
    with db.connect() as conn:
        medication = conn.execute(
            "SELECT schedule_id FROM medications WHERE schedule_id = ? AND elder_id = ?",
            (schedule_id, elder_id),
        ).fetchone()
        if medication is None:
            raise HTTPException(404, "해당 환자의 복약 일정을 찾을 수 없습니다.")
        review_id = db.insert(conn, "medication_reviews", {
            "elder_id": elder_id,
            "schedule_id": schedule_id,
            "review_date": req.review_date,
            "severity": req.severity,
            "observed_flags": req.observed_flags,
            "note": req.note,
        })
        conn.commit()
    return {"review_id": review_id, "ok": True}


@app.delete("/api/medications/{schedule_id}")
def remove_medication(schedule_id: str):
    with db.connect() as conn:
        conn.execute("UPDATE medications SET active = 0 WHERE schedule_id = ?",
                     (schedule_id,))
        conn.commit()
    return {"ok": True}


@app.get("/api/elders/{elder_id}/pending-call")
def pending_call(elder_id: str = "elder_001"):
    """AI 가 먼저 전화를 걸어야 하는 상황인지 알려준다.

    노인용 화면이 주기적으로 물어보고, 조건이 맞으면 전화가 걸려온다.
    치매 노인이 약 시간을 스스로 기억하기 어렵기 때문이다 (명세 FR-08).
    """
    meds = med_mod.due(elder_id)
    return {
        "due": bool(meds),
        "reason": "medication" if meds else None,
        "medications": [
            {"name": m["medication_name"], "scheduled_time": m["scheduled_time"],
             "minutes_late": m["minutes_late"]}
            for m in meds
        ],
    }


def _open_ai_session(elder_id: str, persona_id: str | None) -> dict:
    """AI 통화 하나를 연다.

    직접 거는 경우와 보호자가 받지 않아 인계되는 경우가 똑같은 응답을 써야
    한다. 어르신 화면이 두 경로를 구분하지 않는 것이 이 서비스의 요점이라,
    응답 형태가 갈리면 화면에 분기가 생기고 그 분기가 곧 어긋난다.
    """
    session = Session(elder_id=elder_id, persona_id=persona_id)
    SESSIONS[session.call_id] = session
    selected_persona_id = session.ctx["persona"].get("persona_id")
    persona_name = session.ctx["persona"].get("display_name", "가족")
    return {
        "call_id": session.call_id,
        "persona_id": selected_persona_id,
        "persona_name": persona_name,
        # 복약 시간대면 민준이가 먼저 건넬 말이 들어온다. 없으면 빈 문자열.
        "opening": session.opening(),
        # 명세 13.1 — 연결 전 1회만 고지한다. 통화 중에는 반복하지 않는다.
        "announcement": f"{persona_name}이가 준비한 AI 기억통화가 연결됩니다.",
        "faces": _face_urls(selected_persona_id),
        "morph_url": _morph_url(selected_persona_id),
        "loops": _loop_urls(selected_persona_id),
    }


@app.post("/api/calls")
def start_call(req: StartCallRequest):
    """AI 인지·정서 케어 통화를 연다."""
    return _open_ai_session(req.elder_id, req.persona_id)


# ---------------------------------------------------------------- 기기와 호출
#
# 여기부터가 사람↔사람 통화 구간이다. 지금까지 "전화를 건다"는 어르신 기기
# 안의 15초 타이머였고 보호자 기기에는 아무 신호도 가지 않았다. 그래서 받지
# 않았다는 판정 자체가 불가능했고 AI 대리통화는 대리가 아니었다.
#
# 미디어(WebRTC)는 다음 단계다. 이 층은 호출 상태만 다룬다.
# 근거와 뒤집는 조건은 docs/call_transport_decision.md.


@app.post("/api/devices")
def register_device(req: DeviceRegistration):
    try:
        return inv_mod.register_device(
            device_id=req.device_id, elder_id=req.elder_id, role=req.role,
            persona_id=req.persona_id, label=req.label,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------------------ P2P 진단
#
# 사람↔사람 통화를 WebRTC P2P 로 붙이기로 했는데, 그 결정은 아직 실측이 아니라
# 추론이다 (docs/call_transport_decision.md §8). 붙지 않는 망이면 TURN 을
# 더하거나 관리형 SFU 로 갈아타야 하고, 발표 전에 알아야 갈아탈 시간이 있다.


class SignalMessage(BaseModel):
    sender: str = Field(min_length=1, max_length=64)
    kind: Literal["offer", "answer", "ice"]
    payload: dict


class CallSignalMessage(BaseModel):
    sender: Literal["caller", "answerer"]
    kind: Literal["offer", "answer", "ice"]
    payload: dict


class NetTestResult(BaseModel):
    room: str | None = None
    label: str | None = Field(default=None, max_length=60)
    connected: bool
    route: Literal["host", "srflx", "prflx", "relay"] | None = None
    symmetric: bool | None = None
    stun_ok: bool | None = None
    elapsed_ms: int | None = None
    round_trip_ms: int | None = None
    user_agent: str | None = Field(default=None, max_length=120)


@app.post("/api/nettest/room")
def nettest_room():
    return {"room": nettest_mod.new_room()}


@app.post("/api/nettest/{room}/signal")
def nettest_send(room: str, req: SignalMessage):
    """SDP 와 ICE 후보를 상대에게 전달한다. 서버는 내용을 보지 않는다."""
    try:
        return nettest_mod.send(room, req.sender, req.kind, req.payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/nettest/{room}/signal")
def nettest_poll(room: str, sender: str, since: int = 0):
    return nettest_mod.poll(room, sender, since)


@app.post("/api/nettest/results")
def nettest_record(req: NetTestResult):
    return nettest_mod.record(req.model_dump())


@app.get("/api/nettest/results")
def nettest_results(limit: int = 50):
    return {"results": nettest_mod.results(limit)}


@app.get("/api/devices")
def list_devices(elder_id: str = "elder_001"):
    """지금 어느 기기가 벨을 받을 수 있는지. 폰에서 확인할 곳이 필요하다."""
    rows = inv_mod.devices(elder_id)
    return {
        "elder_id": elder_id,
        "devices": rows,
        "alive_within_sec": inv_mod.DEVICE_ALIVE_SEC,
        "listening": sum(1 for row in rows if row["listening"]),
    }


@app.post("/api/call-invites")
def create_invite(req: InviteRequest):
    """어르신이 가족에게 전화를 건다."""
    return inv_mod.create(req.elder_id, req.persona_id, req.from_device)


@app.get("/api/call-invites/recent")
def recent_invites(elder_id: str = "elder_001",
                   limit: int = Query(default=20, ge=1, le=100)):
    """방금 통화가 왜 끝났는지 폰 주소창에서도 확인하는 진단 경로."""
    return {"invites": inv_mod.recent(elder_id, limit)}


@app.get("/api/call-invites/{invite_id}")
def read_invite(invite_id: str):
    """어르신 기기의 폴링. 벨이 울리는 동안 남은 시간도 함께 준다."""
    try:
        return inv_mod.get(invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/call-invites")
def incoming_invite(device_id: str):
    """보호자 기기의 수신 폴링.

    이 호출이 heartbeat 를 겸한다. 보호자가 화면을 열어 두고 있다는 사실이
    여기서 갱신되고, 그 값으로 "받을 기기가 있는가"를 판정한다.
    """
    try:
        return {"invite": inv_mod.incoming_for(device_id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/call-invites/{invite_id}/signal")
def call_invite_signal(invite_id: str, req: CallSignalMessage):
    """실제 통화의 SDP·ICE를 전달한다. room은 invite_id와 같다."""
    try:
        inv_mod.get(invite_id)
        return signaling.send(invite_id, req.sender, req.kind, req.payload)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/call-invites/{invite_id}/signal")
def poll_call_invite_signal(invite_id: str,
                            sender: Literal["caller", "answerer"],
                            since: int = 0):
    try:
        inv_mod.get(invite_id)
        return signaling.poll(invite_id, sender, since)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/call-invites/{invite_id}/answer")
def answer_invite(invite_id: str, req: InviteDeviceAction):
    try:
        return inv_mod.answer(invite_id, req.device_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/call-invites/{invite_id}/decline")
def decline_invite(invite_id: str, req: InviteDeviceAction):
    """거절은 실패가 아니다. 곧바로 AI 가 대신 받을 수 있는 상태로 간다."""
    try:
        return inv_mod.decline(invite_id, req.device_id, req.reason)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/call-invites/{invite_id}/cancel")
def cancel_invite(invite_id: str):
    """어르신이 먼저 끊었다. AI 로 넘기지 않는다."""
    try:
        return inv_mod.cancel(invite_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/call-invites/{invite_id}/ai-takeover")
def take_over_invite(invite_id: str, req: TakeOverRequest):
    """AI 가 대신 받는다. 응답은 POST /api/calls 와 같은 형태다."""
    try:
        invite = inv_mod.get(invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not inv_mod.can_take_over(invite["state"], req.reason):
        raise HTTPException(409, f"'{invite['state']}' 상태에서는 넘길 수 없습니다.")

    call = _open_ai_session(invite["elder_id"], invite["persona_id"])
    try:
        invite = inv_mod.take_over(invite_id, call["call_id"], req.reason)
    except ValueError as exc:
        SESSIONS.pop(call["call_id"], None)
        raise HTTPException(409, str(exc)) from exc
    return {**call, "invite": invite}


@app.post("/api/call-invites/{invite_id}/end")
def end_invite(invite_id: str):
    try:
        return inv_mod.end(invite_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/calls/{call_id}/turn")
def turn(call_id: str, req: TurnRequest, background_tasks: BackgroundTasks):
    """할아버지 발화 하나를 보내고 AI 응답을 받는다."""
    session = _get(call_id)
    try:
        result = session.turn(req.text.strip())
    except llm.QuotaExceeded as e:
        raise HTTPException(429, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"모델 호출 실패: {e}") from e

    background_tasks.add_task(session.finish_turn_metadata, result)

    return {
        "reply": result.get("reply", ""),
        # 아래 리포트용 필드는 백그라운드에서 채워진다. 응답 키는 기존
        # 프론트 계약을 깨지 않기 위해 유지한다.
        "intent": None,
        "certainty": result.get("certainty"),
        "used_memory_ids": result.get("used_memory_ids") or [],
        "used_schedule_ids": result.get("used_schedule_ids") or [],
        "risk": result.get("risk"),
        "medication_status": None,
        "unverified_recall": result.get("unverified_recall"),
        "care": None,
        "grounding": None,
        "safety_flags": result.get("_safety_flags") or [],
        "rewritten": bool(result.get("_rewritten")),
        "latency_ms": result.get("_latency_ms", 0),
        "llm_first_token_ms": result.get("_llm_first_token_ms"),
    }


@app.get("/api/calls/{call_id}/log")
def call_log(call_id: str):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT utterance_id, seq, speaker, transcript, intent, certainty, "
            "care_data, safety_flags, was_rewritten, latency_ms "
            "FROM utterances WHERE call_id = ? ORDER BY seq",
            (call_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(404, "기록이 없습니다.")
    return {"call_id": call_id, "utterances": [db._row(r) for r in rows]}


@app.get("/api/calls/{call_id}/report")
def call_report(call_id: str, regenerate: bool = False):
    """통화 리포트. 처음 요청할 때 만들고 이후에는 저장된 것을 준다.

    통화 종료를 기다리게 하지 않으려고 끊는 시점이 아니라
    보호자가 열어볼 때 생성한다.
    """
    try:
        return report_mod.build(call_id, regenerate=regenerate)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/elders/{elder_id}/summary")
def period_summary(elder_id: str = "elder_001", days: int = 7,
                   narrative: bool = True, start: str | None = None,
                   end: str | None = None):
    """며칠치를 모아 본다. 통화 하나로는 변화가 보이지 않는다."""
    try:
        return report_mod.period(
            elder_id, days=days, narrative=narrative,
            start_date=start, end_date=end,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/risk-events/{event_id}/acknowledge")
def ack_risk(event_id: int):
    """보호자가 위험 알림을 확인했음을 기록한다 (명세 FR-10)."""
    return report_mod.acknowledge(event_id)


def _shift_label(value: str) -> str:
    return {"day": "주간", "evening": "저녁", "night": "야간"}.get(value, value)


_MEDICATION_RISK_TYPES = {"overdose", "duplicate_dose", "duplicate_medication"}


def _remove_represented_medication_risks(
    risk_tasks: list[dict], dose_tasks: list[dict], logs: list[dict],
) -> list[dict]:
    """복약 행에서 처리 가능한 동일 통화의 위험 신호를 즉시 확인에서 제외한다.

    연결된 복약 기록이 없으면 안전한 기본값으로 위험 신호를 그대로 남긴다.
    """
    visible_doses = {
        (row.get("task_date"), row.get("schedule_id"))
        for row in dose_tasks
        if row.get("kind") == "dose"
    }
    represented_calls = {
        (row.get("taken_date"), row.get("call_id"))
        for row in logs
        if row.get("call_id")
        and row.get("status") == "DUPLICATE_SUSPECTED"
        and (row.get("taken_date"), row.get("schedule_id")) in visible_doses
    }
    return [
        row for row in risk_tasks
        if not (
            row.get("risk_type") in _MEDICATION_RISK_TYPES
            and (row.get("task_date"), row.get("call_id")) in represented_calls
        )
    ]


@app.get("/api/care-tasks")
def care_tasks(as_of: str | None = None):
    """안전·복약·관찰 원천을 별도 tasks 테이블 없이 실행 목록으로 합친다."""
    try:
        selected_day = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError as exc:
        raise HTTPException(400, "as_of는 YYYY-MM-DD 형식이어야 합니다.") from exc
    day_text = selected_day.isoformat()
    previous_day = selected_day - timedelta(days=1)
    previous_text = previous_day.isoformat()
    weekday = med_mod.WEEKDAY[selected_day.weekday()]
    previous_weekday = med_mod.WEEKDAY[previous_day.weekday()]
    now_text = time.strftime("%H:%M") if selected_day == date.today() else "23:59"
    with db.connect() as conn:
        elders = [db._row(row) for row in conn.execute(
            "SELECT elder_id, name, preferred_call_name FROM elder_profiles ORDER BY name"
        ).fetchall()]
        meds = [db._row(row) for row in conn.execute(
            "SELECT * FROM medications WHERE active = 1 ORDER BY scheduled_time, medication_name"
        ).fetchall()]
        logs = [db._row(row) for row in conn.execute(
            "SELECT * FROM medication_logs WHERE taken_date IN (?, ?) ORDER BY log_id",
            (previous_text, day_text),
        ).fetchall()]
        reviews = [db._row(row) for row in conn.execute(
            "SELECT * FROM medication_reviews WHERE review_date <= ? ORDER BY review_date DESC, review_id DESC", (day_text,)
        ).fetchall()]
        risks = [db._row(row) for row in conn.execute(
            "SELECT e.*, c.elder_id, c.started_at, u.transcript AS evidence "
            "FROM call_events e JOIN calls c ON c.call_id=e.call_id "
            "LEFT JOIN utterances u ON u.utterance_id=e.utterance_id "
            "WHERE e.event_type='risk' AND substr(c.started_at,1,10) IN (?, ?) "
            "ORDER BY c.started_at DESC", (previous_text, day_text),
        ).fetchall()]
        latest_handover = conn.execute(
            "SELECT * FROM handovers ORDER BY closed_at DESC, handover_id DESC LIMIT 1"
        ).fetchone()

    elder_names = {row["elder_id"]: row["name"] for row in elders}
    log_by_day_schedule = defaultdict(list)
    for row in logs:
        log_by_day_schedule[(row["taken_date"], row["schedule_id"])].append(row)
    review_by_schedule = {}
    for row in reviews:
        review_by_schedule.setdefault(row["schedule_id"], row)

    risk_labels = {
        "fall": "낙상 신호", "lost": "길 잃음 신호", "intrusion": "침입 불안 신호",
        "fire": "화재 신호", "gas_leak": "가스 신호", "chest_pain": "흉통 신호",
        "breathing": "호흡 곤란 신호", "overdose": "중복 복용 신호",
    }

    def risk_task(row: dict, carryover: bool = False) -> dict:
        risk_type = (row.get("payload") or {}).get("type") or (row.get("payload") or {}).get("risk_type")
        return {
            "id": f"risk-{row['event_id']}", "kind": "risk", "event_id": row["event_id"],
            "call_id": row.get("call_id"), "risk_type": risk_type,
            "elder_id": row["elder_id"], "elder_name": elder_names.get(row["elder_id"], row["elder_id"]),
            "title": risk_labels.get(risk_type, "안전 신호 상태 확인"),
            "time": str(row.get("started_at") or "")[11:16],
            "task_date": str(row.get("started_at") or "")[:10],
            "evidence": row.get("evidence") or (row.get("payload") or {}).get("evidence"),
            "completed": bool(row.get("acknowledged")), "completed_at": row.get("acknowledged_at"),
            "status": "completed" if row.get("acknowledged") else ("missed" if carryover else "waiting"),
            "carryover": carryover,
        }

    immediate = [{
        **risk_task(row)
    } for row in risks if str(row.get("started_at") or "")[:10] == day_text]

    def dose_task(med: dict, task_day: str, task_weekday: str, carryover: bool = False) -> dict | None:
        if task_weekday not in (med.get("days_of_week") or med_mod.WEEKDAY):
            return None
        entries = log_by_day_schedule.get((task_day, med["schedule_id"]), [])
        manual_entries = [
            row for row in entries
            if row.get("call_id") is None
            and str(row.get("evidence_text") or "").startswith("담당자 체크:")
        ]
        manual = manual_entries[-1] if manual_entries else None
        observed = [row for row in entries if row not in manual_entries]
        latest = manual or (entries[-1] if entries else None)
        scheduled_time = med.get("scheduled_time") or "23:59"
        # 통화에서 복용이 명확히 확인됐거나 담당자가 네 상태 중 하나를
        # 기록하면 이 슬롯의 기록 업무는 끝난다. 불확실·거부·중복 의심은
        # 값 자체를 보존해 후속 판단에서 USER_CONFIRMED와 섞이지 않는다.
        completed = bool(manual or (latest and latest.get("status") == "USER_CONFIRMED"))
        status = "completed" if completed else (
            "missed" if carryover or (task_day == day_text and scheduled_time < now_text) else "waiting"
        )
        return {
            "id": f"dose-{task_day}-{med['schedule_id']}", "kind": "dose", "schedule_id": med["schedule_id"],
            "elder_id": med["elder_id"], "elder_name": elder_names.get(med["elder_id"], med["elder_id"]),
            "title": med["medication_name"], "time": scheduled_time, "task_date": task_day,
            "dosage_text": med.get("dosage_text"), "indication": med.get("indication"),
            "dose_status": latest.get("status") if latest else None,
            "observed_status": observed[-1].get("status") if observed else None,
            "ai_observation_count": len(observed),
            "evidence": next((row.get("evidence_text") for row in reversed(observed) if row.get("evidence_text")), None),
            "completed": completed, "completed_at": latest.get("created_at") if latest and completed else None,
            "status": status, "carryover": carryover,
        }

    timed = []
    all_day = []
    carryover = []
    for med in meds:
        current_dose = dose_task(med, day_text, weekday)
        if current_dose:
            timed.append(current_dose)
        prior_dose = dose_task(med, previous_text, previous_weekday, carryover=True)
        if prior_dose and not prior_dose["completed"]:
            carryover.append(prior_dose)
        interval = int(med.get("review_interval_days") or 14)
        latest = review_by_schedule.get(med["schedule_id"])
        due_on = (date.fromisoformat(latest["review_date"]) + timedelta(days=interval)) if latest else selected_day
        if due_on <= selected_day:
            review_task = {
                "id": f"review-{med['schedule_id']}", "kind": "review", "schedule_id": med["schedule_id"],
                "elder_id": med["elder_id"], "elder_name": elder_names.get(med["elder_id"], med["elder_id"]),
                "title": f"{med['medication_name']} {interval}일 관찰 주기", "time": None,
                "task_date": due_on.isoformat(), "monitoring_points": med.get("monitoring_points") or [],
                "escalation_criteria": med.get("escalation_criteria"),
                "evidence": None, "completed": bool(latest and latest["review_date"] == day_text),
                "completed_at": latest.get("created_at") if latest and latest["review_date"] == day_text else None,
                "status": "completed" if latest and latest["review_date"] == day_text else "waiting",
            }
            if due_on < selected_day and not review_task["completed"]:
                review_task["carryover"] = True
                review_task["status"] = "missed"
                carryover.append(review_task)
            else:
                all_day.append(review_task)
    carryover.extend(
        risk_task(row, carryover=True) for row in risks
        if str(row.get("started_at") or "")[:10] == previous_text and not row.get("acknowledged")
    )
    dose_tasks = timed + [row for row in carryover if row.get("kind") == "dose"]
    immediate = _remove_represented_medication_risks(immediate, dose_tasks, logs)
    carryover_risks = [row for row in carryover if row.get("kind") == "risk"]
    visible_carryover_risks = _remove_represented_medication_risks(carryover_risks, dose_tasks, logs)
    carryover = [row for row in carryover if row.get("kind") != "risk"] + visible_carryover_risks
    all_tasks = immediate + timed + all_day + carryover
    total = len(all_tasks)
    completed = sum(1 for row in all_tasks if row["completed"])
    return {
        "as_of": day_text, "elders": elders, "immediate": immediate,
        "timed": timed, "all_day": all_day, "carryover": carryover,
        "completed": completed, "total": total, "current_time": now_text,
        "latest_handover": db._row(latest_handover) if latest_handover else None,
    }


@app.get("/api/handovers")
def list_handovers(limit: int = 10):
    with db.connect() as conn:
        rows = [db._row(row) for row in conn.execute(
            "SELECT * FROM handovers ORDER BY closed_at DESC, handover_id DESC LIMIT ?", (max(1, min(limit, 50)),)
        ).fetchall()]
    for row in rows:
        row["shift_label"] = _shift_label(row["shift"])
    return {"handovers": rows}


def _record_care_dose_status(schedule_id: str, as_of: str, status: str) -> dict:
    status_labels = {
        "USER_CONFIRMED": "복용 확인", "UNCLEAR": "불확실",
        "REFUSED": "거부", "DUPLICATE_SUSPECTED": "중복 의심",
    }
    with db.connect() as conn:
        medication = conn.execute("SELECT elder_id FROM medications WHERE schedule_id=? AND active=1", (schedule_id,)).fetchone()
        if medication is None:
            raise HTTPException(404, "복약 일정을 찾을 수 없습니다.")
        existing = conn.execute(
            "SELECT log_id FROM medication_logs WHERE schedule_id=? AND taken_date=? "
            "AND call_id IS NULL AND evidence_text LIKE '담당자 체크:%' "
            "ORDER BY log_id DESC LIMIT 1",
            (schedule_id, as_of),
        ).fetchone()
        evidence_text = f"담당자 체크: {status_labels[status]}"
        if existing:
            conn.execute(
                "UPDATE medication_logs SET status=?, evidence_text=?, created_at=CURRENT_TIMESTAMP WHERE log_id=?",
                (status, evidence_text, existing["log_id"]),
            )
        else:
            db.insert(conn, "medication_logs", {
                "elder_id": medication["elder_id"], "schedule_id": schedule_id,
                "taken_date": as_of, "status": status, "evidence_text": evidence_text,
            })
        conn.commit()
    return {"ok": True, "schedule_id": schedule_id, "as_of": as_of, "status": status}


@app.post("/api/care-tasks/dose/{schedule_id}/status")
def set_dose_task_status(schedule_id: str, req: CareTaskDoseStatusRequest):
    return _record_care_dose_status(schedule_id, req.as_of, req.status)


@app.post("/api/care-tasks/dose/{schedule_id}/complete")
def complete_dose_task(schedule_id: str, req: CareTaskCompleteRequest):
    """이전 프론트와의 호환용. 신규 화면은 /status로 네 상태를 분리 저장한다."""
    return _record_care_dose_status(schedule_id, req.as_of, "USER_CONFIRMED")


@app.post("/api/handovers")
def close_handover(req: HandoverRequest):
    closed_at = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        handover_id = db.insert(conn, "handovers", {"shift": req.shift, "closed_at": closed_at, "note": req.note})
        conn.commit()
    return {"handover_id": handover_id, "shift": req.shift, "closed_at": closed_at, "note": req.note}


@app.get("/api/elders/{elder_id}/reports")
def elder_reports(elder_id: str = "elder_001", limit: int = 20):
    return {"elder_id": elder_id, "calls": report_mod.recent(elder_id, limit)}


@app.post("/api/calls/{call_id}/end")
def end_call(call_id: str, req: EndCallRequest):
    session = _get(call_id)
    summary = session.end(req.reason)
    SESSIONS.pop(call_id, None)
    return summary


# API와 미디어 라우트 뒤에 마운트해야 /api 요청을 React가 가로채지 않는다.
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
