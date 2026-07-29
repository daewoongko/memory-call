"""
통화 API 서버.

chat.py 가 파이썬으로 직접 부르던 것을 HTTP로 노출한다.
React 화면(D5-B)이 이 API만 보고 동작하도록 응답 형태를 고정한다.

    python tools/serve.py
    http://localhost:8000/docs  ← 브라우저에서 바로 테스트 가능
"""

import base64
import binascii
import hashlib
import hmac
import html
import os
import uuid
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import admin as admin_mod
import db
import linking as link_mod
import llm
import medication as med_mod
import memories as mem_mod
import report as report_mod
import schedules as sched_mod
from conversation import Session
from storage import (
    ALIGNED_FACES_DIR,
    FACES_ROOT,
    FRONTEND_DIST,
    LOOPS_DIR,
    MORPH_PATH,
    ensure_directories,
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
app.mount("/faces", StaticFiles(directory=FACES_DIR), name="faces")
# 모핑 영상(morph.mp4)을 내보낸다. 브라우저가 구간 요청을 하므로
# StaticFiles 가 Range 헤더를 처리해 준다.
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


DEMO_COOKIE = "memory_call_demo_session"


def _demo_token(username: str, password: str) -> str:
    """환경 변수 비밀번호를 노출하지 않는 고정 길이 세션 토큰을 만든다."""
    return hmac.new(
        password.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _safe_next_path(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _login_page(next_path: str = "/", error: str = "") -> HTMLResponse:
    safe_next = html.escape(_safe_next_path(next_path), quote=True)
    error_html = (
        f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>기억이음 데모 로그인</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      padding: 24px; background: #f5f0e8; color: #24211d;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(100%, 420px); padding: 36px; border-radius: 24px;
      background: white; box-shadow: 0 18px 50px rgba(55, 43, 28, .12);
    }}
    .eyebrow {{ margin: 0 0 10px; color: #b85c38; font-weight: 700; }}
    h1 {{ margin: 0 0 10px; font-size: 30px; }}
    .description {{ margin: 0 0 28px; color: #696158; line-height: 1.55; }}
    label {{ display: block; margin: 18px 0 8px; font-weight: 700; }}
    input {{
      width: 100%; padding: 14px 15px; border: 1px solid #d8d0c6;
      border-radius: 12px; font: inherit;
    }}
    input:focus {{ outline: 3px solid #f1c7aa; border-color: #b85c38; }}
    button {{
      width: 100%; margin-top: 24px; padding: 14px; border: 0;
      border-radius: 12px; background: #b85c38; color: white;
      font: inherit; font-weight: 800; cursor: pointer;
    }}
    .error {{
      margin: 0 0 16px; padding: 12px; border-radius: 10px;
      background: #fff0ef; color: #9b2c26;
    }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">MEMORY CALL</p>
    <h1>기억이음 데모</h1>
    <p class="description">공개 데모 보호를 위해 설정한 계정으로 로그인해 주세요.</p>
    {error_html}
    <form method="post" action="/demo-login">
      <input type="hidden" name="next" value="{safe_next}">
      <label for="username">아이디</label>
      <input id="username" name="username" value="demo" autocomplete="username" required>
      <label for="password">비밀번호</label>
      <input id="password" name="password" type="password"
             autocomplete="current-password" required autofocus>
      <button type="submit">데모 시작하기</button>
    </form>
  </main>
</body>
</html>"""
    )


@app.get("/demo-login", response_class=HTMLResponse)
async def demo_login_page(next: str = "/"):
    return _login_page(next)


@app.post("/demo-login")
async def demo_login(request: Request):
    form = await request.form()
    username = str(form.get("username", ""))
    supplied_password = str(form.get("password", ""))
    next_path = _safe_next_path(str(form.get("next", "/")))
    expected_username = os.getenv("DEMO_USERNAME", "demo")
    expected_password = os.getenv("DEMO_PASSWORD", "")

    valid = bool(expected_password) and hmac.compare_digest(
        username, expected_username
    ) and hmac.compare_digest(supplied_password, expected_password)
    if not valid:
        response = _login_page(next_path, "아이디 또는 비밀번호가 맞지 않습니다.")
        response.status_code = 401
        return response

    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        DEMO_COOKIE,
        _demo_token(expected_username, expected_password),
        max_age=60 * 60 * 8,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.get("/demo-logout")
async def demo_logout():
    response = RedirectResponse("/demo-login", status_code=303)
    response.delete_cookie(DEMO_COOKIE)
    return response


@app.middleware("http")
async def protect_demo(request: Request, call_next):
    """정식 인증 전 공개 데모를 로그인 쿠키로 보호한다."""
    password = os.getenv("DEMO_PASSWORD", "")
    public_paths = {"/api/health", "/demo-login"}
    if password and request.url.path not in public_paths:
        username = os.getenv("DEMO_USERNAME", "demo")
        expected_token = _demo_token(username, password)
        authorized = hmac.compare_digest(
            request.cookies.get(DEMO_COOKIE, ""),
            expected_token,
        )

        # 자동화 점검과 기존 클라이언트를 위해 Basic 헤더도 계속 허용한다.
        header = request.headers.get("Authorization", "")
        if not authorized and header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
                supplied_user, supplied_password = decoded.split(":", 1)
                authorized = (
                    hmac.compare_digest(supplied_user, username)
                    and hmac.compare_digest(supplied_password, password)
                )
            except (ValueError, UnicodeDecodeError, binascii.Error):
                authorized = False
        if not authorized:
            next_path = quote(
                request.url.path
                + (f"?{request.url.query}" if request.url.query else ""),
                safe="",
            )
            return RedirectResponse(f"/demo-login?next={next_path}", status_code=303)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(self)"
    return response

# 진행 중인 통화. MVP는 단일 프로세스라 메모리에 둔다.
SESSIONS: dict[str, Session] = {}


# ------------------------------------------------------------------ 스키마

class StartCallRequest(BaseModel):
    elder_id: str = "elder_001"
    # 통화 상대. 비우면 등록이 끝난 첫 사람과 연결한다.
    persona_id: str | None = None


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class EndCallRequest(BaseModel):
    reason: str = "user_ended"


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
    tone: str | None = Field(default=None, max_length=200)
    frequent_phrases: list[str] | None = None
    forbidden_phrases: list[str] | None = None
    sensitive_policy: str | None = Field(default=None, max_length=300)


class ElderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    preferred_call_name: str | None = Field(default=None, max_length=30)
    speech_wait_time_ms: int | None = Field(default=None, ge=500, le=8000)
    hearing_support: bool | None = None
    vision_support: bool | None = None
    anxiety_triggers: list[str] | None = None
    calming_phrases: list[str] | None = None
    frequent_questions: list[str] | None = None


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


class RecallReview(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    title: str | None = None
    description: str | None = None
    date_text: str | None = None
    location: str | None = None
    status: str = Field(default="verified", pattern="^(verified|partial)$")
    note: str | None = None


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


class MedicationRequest(BaseModel):
    medication_name: str = Field(min_length=1, max_length=60)
    dosage_text: str = Field(default="1정", max_length=40)
    scheduled_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    meal_relation: str = Field(default="none", pattern="^(before|after|none)$")
    days_of_week: list[str] = Field(
        default=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])


# ------------------------------------------------------------------ 헬퍼

def _get(call_id: str) -> Session:
    session = SESSIONS.get(call_id)
    if session is None:
        raise HTTPException(404, f"통화 {call_id} 를 찾을 수 없습니다. 이미 종료되었을 수 있습니다.")
    return session


def _morph_url() -> str | None:
    """페르소나 등록 시 미리 만들어 둔 모핑 영상. 없으면 이미지 전환으로 대체된다."""
    return f"/media/{MORPH.name}" if MORPH.exists() else None


def _loop_urls() -> dict[str, str]:
    """표정 루프. 모핑이 끝난 뒤 상황에 맞는 것을 반복 재생한다.

    폴더에 있는 파일을 그대로 알려주고, 어떤 것을 언제 틀지는 화면이 정한다.
    루프를 나중에 추가하거나 빼도 서버는 손대지 않아도 된다.
    """
    if not LOOPS_DIR.exists():
        return {}
    return {p.stem: f"/media/loops/{p.name}" for p in sorted(LOOPS_DIR.glob("*.mp4"))}


def _face_urls() -> list[dict]:
    """모핑에 쓸 얼굴 단계 목록. 파일명 앞 숫자가 순서다."""
    if not FACES_DIR.exists():
        return []
    stages = []
    for path in sorted(FACES_DIR.glob("*.png")):
        if path.name.startswith("_"):
            continue
        stage = path.stem.split("_", 1)[-1]
        stages.append({"stage": stage, "url": f"/faces/{path.name}"})
    return stages


# ------------------------------------------------------------------ 엔드포인트

@app.get("/api/health")
def health():
    return {"ok": True, "model": llm.MODEL, "active_calls": len(SESSIONS)}


@app.get("/api/personas")
def call_targets(elder_id: str = "elder_001"):
    """통화 대상 목록.

    등록이 끝난 사람만 실제로 걸 수 있다.
    나머지는 얼굴 사진과 영상이 아직 없어 대기 상태로 보여준다.
    """
    return {
        "elder_id": elder_id,
        "personas": [
            {
                "persona_id": p["persona_id"],
                "display_name": p["display_name"],
                "relationship": p["relationship_type"],
                "ready": bool(p.get("active")),
                "face": _face_urls()[-1]["url"] if p.get("active") and _face_urls() else None,
            }
            for p in db.personas(elder_id)
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
        "faces": _face_urls(),
        "morph_url": _morph_url(),
        "loops": _loop_urls(),
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
def get_persona(elder_id: str = "elder_001"):
    """페르소나 등록 화면에 필요한 전체 정보."""
    try:
        return dict(admin_mod.profile(elder_id), faces=admin_mod.faces())
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.patch("/api/elders/{elder_id}/persona")
def patch_persona(elder_id: str, req: PersonaPatch):
    try:
        return admin_mod.update_persona(elder_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.patch("/api/elders/{elder_id}/profile")
def patch_elder(elder_id: str, req: ElderPatch):
    try:
        return admin_mod.update_elder(elder_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/faces")
def list_faces():
    return admin_mod.faces()


@app.post("/api/faces")
async def upload_faces(files: list[UploadFile] = File(...)):
    """얼굴 사진 업로드.

    파일명 순서가 나이 순서가 되므로 01_, 02_ 처럼 앞에 번호를 붙여 올린다.
    """
    saved, errors = [], []
    for f in files:
        try:
            saved.append(admin_mod.save_face(f.filename, await f.read()))
        except ValueError as e:
            errors.append({"file": f.filename, "error": str(e)})
    return {"saved": saved, "errors": errors, "faces": admin_mod.faces()}


@app.delete("/api/faces/{name}")
def delete_face(name: str):
    admin_mod.delete_face(name)
    return {"ok": True, "faces": admin_mod.faces()}


@app.post("/api/faces/prepare")
def prepare_faces():
    """올린 사진을 3:4 세로로 자르고 눈높이를 맞춘다."""
    return admin_mod.prepare_faces()


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
def list_medications(elder_id: str = "elder_001"):
    """보호자가 등록한 복약 일정과 오늘 현황."""
    return {"elder_id": elder_id, "today": med_mod.today_status(elder_id)}


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
            "active": 1,
        })
        conn.commit()
    return {"schedule_id": schedule_id, "today": med_mod.today_status(elder_id)}


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


@app.post("/api/calls")
def start_call(req: StartCallRequest):
    """AI 대리통화를 연다."""
    session = Session(elder_id=req.elder_id, persona_id=req.persona_id)
    SESSIONS[session.call_id] = session
    persona_name = session.ctx["persona"].get("display_name", "가족")
    return {
        "call_id": session.call_id,
        "persona_name": persona_name,
        # 복약 시간대면 대웅이가 먼저 건넬 말이 들어온다. 없으면 빈 문자열.
        "opening": session.opening(),
        # 명세 13.1 — 연결 전 1회만 고지한다. 통화 중에는 반복하지 않는다.
        "announcement": f"{persona_name}이가 준비한 AI 기억통화가 연결됩니다.",
        "faces": _face_urls(),
        "morph_url": _morph_url(),
        "loops": _loop_urls(),
    }


@app.post("/api/calls/{call_id}/turn")
def turn(call_id: str, req: TurnRequest):
    """할아버지 발화 하나를 보내고 AI 응답을 받는다."""
    session = _get(call_id)
    try:
        result = session.turn(req.text.strip())
    except llm.QuotaExceeded as e:
        raise HTTPException(429, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"모델 호출 실패: {e}") from e

    return {
        "reply": result.get("reply", ""),
        "intent": result.get("intent"),
        "certainty": result.get("certainty"),
        "used_memory_ids": result.get("used_memory_ids") or [],
        "used_schedule_ids": result.get("used_schedule_ids") or [],
        "risk": result.get("risk"),
        "medication_status": result.get("medication_status"),
        "unverified_recall": result.get("unverified_recall"),
        "grounding": result.get("grounding"),
        "safety_flags": result.get("_safety_flags") or [],
        "rewritten": bool(result.get("_rewritten")),
        "latency_ms": result.get("_latency_ms", 0),
    }


@app.get("/api/calls/{call_id}/log")
def call_log(call_id: str):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT seq, speaker, transcript, intent, certainty, "
            "safety_flags, was_rewritten, latency_ms "
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
                   narrative: bool = True):
    """며칠치를 모아 본다. 통화 하나로는 변화가 보이지 않는다."""
    return report_mod.period(elder_id, days=days, narrative=narrative)


@app.post("/api/risk-events/{event_id}/acknowledge")
def ack_risk(event_id: int):
    """보호자가 위험 알림을 확인했음을 기록한다 (명세 FR-10)."""
    return report_mod.acknowledge(event_id)


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
