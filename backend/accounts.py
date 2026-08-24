"""로그인 세션, 역할별 최초 설정 진행 상태, 동의 이력.

SMS 발송 공급자는 아직 연결하지 않는다. 번호와 간편번호로 계정을 보호하고,
나중에 SMS 확인을 붙일 수 있도록 ``phone_verified_at``을 별도 필드로 둔다.
클라이언트에는 원본 세션 토큰을 한 번만 반환하고 DB에는 SHA-256 해시만 저장한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import uuid

import db


ROLES = {"elder", "child", "care"}
CONSENT_TYPES = {
    "basic_profile", "call_recording", "sensitive_care", "care_sharing",
    "overseas_processing", "retention_deletion",
}
SESSION_DAYS = 30
PIN_ITERATIONS = 210_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("82") and len(digits) in {11, 12}:
        digits = "0" + digits[2:]
    if not re.fullmatch(r"01\d{8,9}", digits):
        raise ValueError("휴대전화 번호를 확인해 주세요.")
    return digits


def _pin_digest(pin: str, salt: str) -> str:
    if not re.fullmatch(r"\d{6}", pin or ""):
        raise ValueError("간편번호는 숫자 6자리로 입력해 주세요.")
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), bytes.fromhex(salt), PIN_ITERATIONS
    ).hex()


def _public_user(row) -> dict:
    return {
        "user_id": row["user_id"],
        "phone": row["phone"],
        "display_name": row["display_name"],
        "phone_verified": bool(row["phone_verified_at"]),
    }


def _issue_session(conn, user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = _stamp(_now() + timedelta(days=SESSION_DAYS))
    conn.execute(
        "INSERT INTO app_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (token_hash, user_id, expires_at),
    )
    return token, expires_at


def register(phone: str, display_name: str, pin: str) -> dict:
    normalized = normalize_phone(phone)
    name = (display_name or "").strip()
    if not 1 <= len(name) <= 30:
        raise ValueError("이름을 입력해 주세요.")
    salt = secrets.token_hex(16)
    digest = _pin_digest(pin, salt)
    with db.connect() as conn:
        if conn.execute(
            "SELECT 1 FROM app_users WHERE phone = ?", (normalized,)
        ).fetchone():
            raise ValueError("이미 가입한 번호예요. 로그인으로 들어가 주세요.")
        user_id = f"user_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO app_users "
            "(user_id, phone, display_name, pin_salt, pin_hash) VALUES (?, ?, ?, ?, ?)",
            (user_id, normalized, name, salt, digest),
        )
        token, expires_at = _issue_session(conn, user_id)
        row = conn.execute(
            "SELECT * FROM app_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.commit()
    return {"token": token, "expires_at": expires_at, "user": _public_user(row)}


def login(phone: str, pin: str) -> dict:
    normalized = normalize_phone(phone)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM app_users WHERE phone = ?", (normalized,)
        ).fetchone()
        if row is None:
            raise ValueError("가입된 번호를 찾지 못했어요.")
        supplied = _pin_digest(pin, row["pin_salt"])
        if not hmac.compare_digest(supplied, row["pin_hash"]):
            raise ValueError("간편번호가 맞지 않아요.")
        token, expires_at = _issue_session(conn, row["user_id"])
        conn.commit()
    return {"token": token, "expires_at": expires_at, "user": _public_user(row)}


def authenticate(token: str | None) -> dict:
    if not token:
        raise ValueError("로그인이 필요합니다.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _stamp()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.* FROM app_sessions s JOIN app_users u ON u.user_id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash, now),
        ).fetchone()
    if row is None:
        raise ValueError("로그인이 만료됐어요. 다시 로그인해 주세요.")
    return _public_user(row)


def logout(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.connect() as conn:
        conn.execute("DELETE FROM app_sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()


def onboarding(user_id: str, role: str) -> dict:
    if role not in ROLES:
        raise ValueError("올바르지 않은 역할입니다.")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_role_onboarding WHERE user_id = ? AND role = ?",
            (user_id, role),
        ).fetchone()
    if row is None:
        return {"role": role, "current_step": "intro", "data": {}, "complete": False}
    try:
        data = json.loads(row["progress_data"] or "{}")
    except json.JSONDecodeError:
        data = {}
    return {
        "role": role,
        "current_step": row["current_step"],
        "data": data,
        "complete": bool(row["completed_at"]),
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def save_onboarding(user_id: str, role: str, current_step: str,
                    data: dict, complete: bool = False) -> dict:
    if role not in ROLES:
        raise ValueError("올바르지 않은 역할입니다.")
    step = (current_step or "intro").strip()[:50]
    existing = onboarding(user_id, role)
    merged = {**existing.get("data", {}), **(data or {})}
    serialized = json.dumps(merged, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > 64 * 1024:
        raise ValueError("최초 설정 내용이 너무 큽니다.")
    completed_at = _stamp() if complete else existing.get("completed_at")
    now = _stamp()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO user_role_onboarding "
            "(user_id, role, current_step, progress_data, completed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, role) DO UPDATE SET "
            "current_step=excluded.current_step, progress_data=excluded.progress_data, "
            "completed_at=excluded.completed_at, updated_at=excluded.updated_at",
            (user_id, role, step, serialized, completed_at, now),
        )
        conn.commit()
    return onboarding(user_id, role)


def record_consents(user_id: str, role: str, consent_types: list[str],
                    version: str, mode: str, elder_id: str | None = None) -> list[dict]:
    if role not in ROLES:
        raise ValueError("올바르지 않은 역할입니다.")
    if mode not in {"self", "with_guardian", "legal_representative", "staff"}:
        raise ValueError("동의 확인 방식을 선택해 주세요.")
    types = sorted({item.strip() for item in consent_types if item.strip()})
    if not types:
        raise ValueError("동의 항목을 확인해 주세요.")
    if not set(types).issubset(CONSENT_TYPES):
        raise ValueError("알 수 없는 동의 항목이 포함되어 있습니다.")
    accepted_at = _stamp()
    with db.connect() as conn:
        for consent_type in types:
            conn.execute(
                "UPDATE consent_records SET revoked_at = ? "
                "WHERE user_id = ? AND role = ? AND consent_type = ? AND revoked_at IS NULL",
                (accepted_at, user_id, role, consent_type),
            )
            conn.execute(
                "INSERT INTO consent_records "
                "(consent_id, user_id, role, elder_id, consent_type, consent_version, "
                "consent_mode, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"consent_{uuid.uuid4().hex[:16]}", user_id, role, elder_id,
                 consent_type, version, mode, accepted_at),
            )
        conn.commit()
    return consents(user_id, role)


def consents(user_id: str, role: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT consent_type, consent_version, consent_mode, elder_id, accepted_at "
            "FROM consent_records WHERE user_id = ? AND role = ? AND revoked_at IS NULL "
            "ORDER BY accepted_at, consent_type",
            (user_id, role),
        ).fetchall()
    return [dict(row) for row in rows]
