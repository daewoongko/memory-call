"""가족별 ElevenLabs 복제 음성 등록과 점진적 PVC 표본 관리.

IVC는 1분 안팎의 두 녹음을 즉시 등록한다. 이후 녹음은 같은 가족의 비공개
폴더에 누적하고 30분/60분 진행도만 계산한다. PVC 생성·본인 인증·학습은
사용자 확인이 필요한 별도 단계이므로 이 모듈이 임의로 시작하지 않는다.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib import error, request

import db
import elevenlabs_tts
from storage import persona_voice_storage


IVC_API_URL = "https://api.elevenlabs.io/v1/voices/add"
VOICE_API_URL = "https://api.elevenlabs.io/v1/voices"
MAX_SAMPLE_BYTES = 25 * 1024 * 1024
IVC_PROMPTS = {"general", "care"}
ALLOWED_MIME_TYPES = {
    "audio/webm", "audio/mp4", "audio/mpeg", "audio/mp3", "audio/wav",
    "audio/x-wav", "audio/ogg",
}
EXTENSIONS = {
    "audio/webm": ".webm", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
}


class VoiceProfileError(ValueError):
    pass


class VoiceProviderUnavailable(RuntimeError):
    pass


def _persona(persona_id: str, elder_id: str | None = None) -> dict:
    with db.connect() as conn:
        if elder_id:
            row = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ? AND elder_id = ?",
                (persona_id, elder_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ?", (persona_id,),
            ).fetchone()
    if row is None:
        raise VoiceProfileError("가족 프로필을 찾을 수 없습니다.")
    return db._row(row)


def _ensure_profile(conn, persona_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO persona_voice_profiles(persona_id) VALUES (?)",
        (persona_id,),
    )


def _quality(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sample_rows(conn, persona_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT sample_id, phase, prompt_id, duration_seconds, quality, usable, "
        "created_at FROM persona_voice_samples WHERE persona_id = ? "
        "ORDER BY created_at", (persona_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["quality"] = _quality(item.get("quality"))
        item["usable"] = bool(item.get("usable"))
        result.append(item)
    return result


def _totals(samples: list[dict]) -> tuple[float, float]:
    ivc = sum(float(s["duration_seconds"]) for s in samples
              if s["usable"] and s["phase"] == "ivc")
    all_audio = sum(float(s["duration_seconds"]) for s in samples if s["usable"])
    return ivc, all_audio


def public_profile(persona_id: str, elder_id: str | None = None) -> dict:
    persona = _persona(persona_id, elder_id)
    with db.connect() as conn:
        _ensure_profile(conn, persona_id)
        row = conn.execute(
            "SELECT * FROM persona_voice_profiles WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()
        samples = _sample_rows(conn, persona_id)
        conn.commit()
    ivc_seconds, total_seconds = _totals(samples)
    available_prompts = {
        sample["prompt_id"] for sample in samples
        if sample["phase"] == "ivc" and sample["usable"]
    }
    status = dict(row)
    # 공급자 voice_id는 브라우저로 내보내지 않는다.
    for secret in ("ivc_voice_id", "pvc_voice_id", "active_voice_id"):
        status.pop(secret, None)
    return {
        "persona_id": persona_id,
        "display_name": persona.get("display_name"),
        **status,
        "consented": bool(status.get("consent_at")),
        "ivc_seconds": round(ivc_seconds, 1),
        "recorded_seconds": round(total_seconds, 1),
        "ivc_prompts_ready": sorted(available_prompts),
        "ivc_can_create": IVC_PROMPTS.issubset(available_prompts)
            and ivc_seconds >= 80,
        "pvc_eligible": total_seconds >= 30 * 60,
        "pvc_recommended": total_seconds >= 60 * 60,
        "samples": samples,
    }


def record_consent(persona_id: str, elder_id: str, accepted: bool) -> dict:
    _persona(persona_id, elder_id)
    with db.connect() as conn:
        _ensure_profile(conn, persona_id)
        conn.execute(
            "UPDATE persona_voice_profiles SET consent_at = "
            "CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, "
            "voice_status = CASE WHEN ? THEN 'ivc_recording' ELSE 'unregistered' END, "
            "updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
            (int(accepted), int(accepted), persona_id),
        )
        conn.commit()
    return public_profile(persona_id, elder_id)


def save_sample(
    persona_id: str,
    elder_id: str,
    *,
    phase: str,
    prompt_id: str,
    original_name: str,
    mime_type: str,
    payload: bytes,
    duration_seconds: float,
    quality: dict,
) -> dict:
    _persona(persona_id, elder_id)
    if phase not in {"ivc", "pvc"}:
        raise VoiceProfileError("지원하지 않는 녹음 단계입니다.")
    if phase == "ivc" and prompt_id not in IVC_PROMPTS:
        raise VoiceProfileError("올바르지 않은 안내 문장입니다.")
    mime_type = mime_type.lower().split(";", 1)[0]
    if mime_type not in ALLOWED_MIME_TYPES:
        raise VoiceProfileError("지원하지 않는 음성 형식입니다.")
    if not payload or len(payload) > MAX_SAMPLE_BYTES:
        raise VoiceProfileError("녹음 파일 크기를 확인해 주세요.")
    minimum = 40 if phase == "ivc" else 10
    maximum = 100 if phase == "ivc" else 360
    if not minimum <= duration_seconds <= maximum:
        raise VoiceProfileError(
            f"{minimum}초 이상 {maximum}초 이하로 녹음해 주세요."
        )
    if quality.get("passed") is not True:
        raise VoiceProfileError("음질 확인을 통과한 녹음만 저장할 수 있습니다.")

    folder = persona_voice_storage(persona_id)
    sample_id = f"voice_{uuid.uuid4().hex[:16]}"
    path = folder / f"{sample_id}{EXTENSIONS[mime_type]}"
    path.write_bytes(payload)
    old_paths: list[str] = []
    try:
        with db.connect() as conn:
            _ensure_profile(conn, persona_id)
            # IVC 안내문은 다시 녹음하면 최신 한 건으로 교체한다.
            if phase == "ivc":
                old_paths = [
                    row["file_path"] for row in conn.execute(
                        "SELECT file_path FROM persona_voice_samples "
                        "WHERE persona_id = ? AND phase = 'ivc' AND prompt_id = ?",
                        (persona_id, prompt_id),
                    ).fetchall()
                ]
                conn.execute(
                    "DELETE FROM persona_voice_samples WHERE persona_id = ? "
                    "AND phase = 'ivc' AND prompt_id = ?", (persona_id, prompt_id),
                )
            conn.execute(
                "INSERT INTO persona_voice_samples(sample_id, persona_id, phase, "
                "prompt_id, file_path, original_name, mime_type, duration_seconds, "
                "quality, usable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (sample_id, persona_id, phase, prompt_id, str(path), original_name,
                 mime_type, duration_seconds, json.dumps(quality, ensure_ascii=False)),
            )
            samples = _sample_rows(conn, persona_id)
            _, total_seconds = _totals(samples)
            next_status = "ivc_recording" if phase == "ivc" else "pvc_collecting"
            conn.execute(
                "UPDATE persona_voice_profiles SET voice_status = ?, "
                "recorded_seconds = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE persona_id = ?", (next_status, total_seconds, persona_id),
            )
            conn.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    for old in old_paths:
        Path(old).unlink(missing_ok=True)
    return public_profile(persona_id, elder_id)


def _multipart(files: list[Path], fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"memorycall{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode("utf-8"), b"\r\n",
        ])
    for path in files:
        content_type = mimetypes.guess_type(path.name)[0] or "audio/webm"
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="files"; '
             f'filename="{path.name}"\r\nContent-Type: {content_type}\r\n\r\n').encode(),
            path.read_bytes(), b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _create_ivc_remote(persona_name: str, files: list[Path]) -> dict:
    api_key = elevenlabs_tts._require_api_key()
    body, content_type = _multipart(files, {
        "name": f"다소니 {persona_name}",
        "description": "본인이 동의하고 직접 녹음한 다소니 가족 통화 음성",
        "remove_background_noise": "false",
    })
    req = request.Request(
        IVC_API_URL, data=body, method="POST",
        headers={"xi-api-key": api_key, "Content-Type": content_type},
    )
    try:
        with request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise VoiceProviderUnavailable(
            f"ElevenLabs 목소리 등록 실패 ({exc.code}): {detail}"
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise VoiceProviderUnavailable("ElevenLabs에 잠시 연결하지 못했습니다.") from exc


def _delete_remote_voice(voice_id: str) -> None:
    """ElevenLabs에 만들어진 복제 음성을 영구 삭제한다."""
    api_key = elevenlabs_tts._require_api_key()
    req = request.Request(
        f"{VOICE_API_URL}/{voice_id}", method="DELETE",
        headers={"xi-api-key": api_key},
    )
    try:
        with request.urlopen(req, timeout=30):
            return
    except error.HTTPError as exc:
        if exc.code == 404:
            return
        detail = exc.read().decode("utf-8", "replace")
        raise VoiceProviderUnavailable(
            f"ElevenLabs 목소리 삭제 실패 ({exc.code}): {detail}"
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise VoiceProviderUnavailable(
            "ElevenLabs에 연결하지 못해 목소리를 삭제하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
        ) from exc


def create_ivc(persona_id: str, elder_id: str) -> dict:
    persona = _persona(persona_id, elder_id)
    with db.connect() as conn:
        _ensure_profile(conn, persona_id)
        profile_row = conn.execute(
            "SELECT * FROM persona_voice_profiles WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()
        if not profile_row["consent_at"]:
            raise VoiceProfileError("본인 음성 사용 동의가 필요합니다.")
        rows = conn.execute(
            "SELECT prompt_id, file_path, duration_seconds FROM persona_voice_samples "
            "WHERE persona_id = ? AND phase = 'ivc' AND usable = 1",
            (persona_id,),
        ).fetchall()
    by_prompt = {row["prompt_id"]: row for row in rows}
    if not IVC_PROMPTS.issubset(by_prompt) or sum(
        float(by_prompt[p]["duration_seconds"]) for p in IVC_PROMPTS
    ) < 80:
        raise VoiceProfileError("1분 녹음 두 개를 먼저 완료해 주세요.")
    result = _create_ivc_remote(
        persona.get("display_name") or "가족",
        [Path(by_prompt[p]["file_path"]) for p in sorted(IVC_PROMPTS)],
    )
    voice_id = str(result.get("voice_id") or "").strip()
    if not voice_id:
        raise VoiceProviderUnavailable("목소리 ID를 받지 못했습니다.")
    with db.connect() as conn:
        conn.execute(
            "UPDATE persona_voice_profiles SET ivc_voice_id = ?, "
            "voice_status = 'ivc_ready', verification_status = ?, last_error = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
            (voice_id, "required" if result.get("requires_verification") else "not_required",
             persona_id),
        )
        conn.commit()
    return public_profile(persona_id, elder_id)


def candidate_voice_id(persona_id: str, elder_id: str) -> str:
    _persona(persona_id, elder_id)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ivc_voice_id FROM persona_voice_profiles WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()
    if not row or not row["ivc_voice_id"]:
        raise VoiceProfileError("미리 들을 목소리가 아직 없습니다.")
    return row["ivc_voice_id"]


def approve_ivc(persona_id: str, elder_id: str) -> dict:
    voice_id = candidate_voice_id(persona_id, elder_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE persona_voice_profiles SET active_voice_type = 'ivc', "
            "active_voice_id = ?, voice_status = 'pvc_collecting', "
            "approved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE persona_id = ?", (voice_id, persona_id),
        )
        conn.commit()
    return public_profile(persona_id, elder_id)


def delete_profile(persona_id: str, elder_id: str) -> dict:
    """제공자 음성, 비공개 녹음과 연결 정보를 모두 삭제한다."""
    _persona(persona_id, elder_id)
    with db.connect() as conn:
        profile = conn.execute(
            "SELECT ivc_voice_id, pvc_voice_id FROM persona_voice_profiles "
            "WHERE persona_id = ?", (persona_id,),
        ).fetchone()
        sample_paths = [
            Path(row["file_path"]) for row in conn.execute(
                "SELECT file_path FROM persona_voice_samples WHERE persona_id = ?",
                (persona_id,),
            ).fetchall()
        ]

    voice_ids = {
        str(profile[key]).strip()
        for key in ("ivc_voice_id", "pvc_voice_id")
        if profile and profile[key]
    }
    # 제공자 삭제가 실패했는데 로컬 기록만 지우면 사용자가 원격 음성이
    # 사라졌다고 오해한다. 원격 삭제를 먼저 확인한 뒤 로컬을 정리한다.
    for voice_id in voice_ids:
        _delete_remote_voice(voice_id)

    with db.connect() as conn:
        conn.execute(
            "DELETE FROM persona_voice_samples WHERE persona_id = ?", (persona_id,),
        )
        conn.execute(
            "DELETE FROM persona_voice_profiles WHERE persona_id = ?", (persona_id,),
        )
        conn.commit()
    for path in sample_paths:
        path.unlink(missing_ok=True)
    return public_profile(persona_id, elder_id)


def active_voice_id(persona_id: str | None) -> str | None:
    if not persona_id:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT active_voice_id FROM persona_voice_profiles WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()
    return row["active_voice_id"] if row and row["active_voice_id"] else None
