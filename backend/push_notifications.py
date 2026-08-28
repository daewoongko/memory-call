"""Web Push delivery for guardian call and safety alerts.

Subscriptions are browser-issued and safe to persist.  The VAPID private key
never leaves the server.  Delivery is deliberately best-effort: an outage in
the push provider must not delay or break the elder's AI conversation.
"""

from __future__ import annotations

import json
import logging
import os
import base64
from datetime import datetime
from functools import lru_cache

import db
from storage import STORAGE_DIR, ensure_directories

try:  # Deployments without push keys keep the existing foreground polling.
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
except ImportError:  # pragma: no cover - exercised by configuration tests
    WebPushException = Exception
    webpush = None
    Vapid = None
    serialization = None


LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@lru_cache(maxsize=1)
def _generated_material():
    if Vapid is None or serialization is None:
        return None
    ensure_directories()
    key_path = STORAGE_DIR / "web_push_vapid_private.pem"
    vapid = Vapid.from_file(str(key_path))
    raw_public = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    browser_key = base64.urlsafe_b64encode(raw_public).rstrip(b"=").decode("ascii")
    return vapid, browser_key


def public_key() -> str:
    configured_key = os.getenv("WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
    if configured_key:
        return configured_key
    material = _generated_material()
    return material[1] if material else ""


def _private_key():
    configured_key = os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
    if configured_key:
        return configured_key
    material = _generated_material()
    return material[0] if material else ""


def _contact() -> str:
    return (
        os.getenv("WEB_PUSH_CONTACT", "").strip()
        or os.getenv("MEMORY_CALL_RENDER_URL", "").strip()
        or "https://memory-call.onrender.com"
    )


def configured() -> bool:
    contact = _contact()
    return bool(
        webpush and public_key() and _private_key()
        and (contact.startswith("mailto:") or contact.startswith("https://"))
    )


def save(device_id: str, endpoint: str, p256dh: str, auth: str) -> dict:
    if not endpoint.startswith("https://"):
        raise ValueError("유효한 Web Push 구독 주소가 아닙니다.")
    if not p256dh or not auth:
        raise ValueError("Web Push 암호화 키가 없습니다.")
    now = _now()
    with db.connect() as conn:
        device = conn.execute(
            "SELECT role FROM devices WHERE device_id = ?", (device_id,),
        ).fetchone()
        if device is None or device["role"] != "guardian":
            raise ValueError("등록된 보호자 기기만 알림을 받을 수 있습니다.")
        conn.execute(
            "INSERT INTO push_subscriptions "
            "(endpoint, device_id, p256dh, auth, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET "
            "device_id = excluded.device_id, p256dh = excluded.p256dh, "
            "auth = excluded.auth, updated_at = excluded.updated_at",
            (endpoint, device_id, p256dh, auth, now, now),
        )
        conn.commit()
    return {"ok": True, "device_id": device_id, "enabled": True}


def remove_device(device_id: str) -> dict:
    with db.connect() as conn:
        removed = conn.execute(
            "DELETE FROM push_subscriptions WHERE device_id = ?", (device_id,),
        ).rowcount
        conn.commit()
    return {"ok": True, "removed": removed}


def _subscriptions(persona_id: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ps.endpoint, ps.p256dh, ps.auth "
            "FROM push_subscriptions ps JOIN devices d ON d.device_id = ps.device_id "
            "WHERE d.role = 'guardian' AND d.persona_id = ?",
            (persona_id,),
        ).fetchall()
    return [db._row(row) for row in rows]


def _delete_endpoint(endpoint: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()


def send(persona_id: str, payload: dict, *, ttl: int = 120) -> dict:
    if not configured():
        return {"configured": False, "sent": 0, "failed": 0}
    sent = 0
    failed = 0
    contact = _contact()
    for subscription in _subscriptions(persona_id):
        info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh"],
                "auth": subscription["auth"],
            },
        }
        try:
            webpush(
                subscription_info=info,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=_private_key(),
                vapid_claims={"sub": contact},
                ttl=ttl,
                timeout=5,
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                _delete_endpoint(subscription["endpoint"])
            LOGGER.warning("guardian web push failed (status=%s)", status)
        except Exception:  # noqa: BLE001 - notification failure is non-fatal
            failed += 1
            LOGGER.exception("guardian web push failed")
    return {"configured": True, "sent": sent, "failed": failed}


def send_invite(invite: dict, elder_name: str = "고길동") -> dict:
    persona_id = invite.get("persona_id")
    if not persona_id:
        return {"configured": configured(), "sent": 0, "failed": 0}
    risk = invite.get("purpose") == "risk"
    payload = {
        "kind": "risk" if risk else "call",
        "title": "다소니 긴급 확인" if risk else "다소니 가족 통화",
        "body": (
            invite.get("alert_evidence") or f"{elder_name} 어르신의 현재 상태를 확인해 주세요."
        ) if risk else f"{elder_name} 어르신이 가족과 통화를 기다리고 있어요.",
        "tag": f"dasoni-{invite.get('invite_id')}",
        "invite_id": invite.get("invite_id"),
        "url": "/#guardian",
        "urgent": risk,
    }
    return send(persona_id, payload, ttl=300 if risk else 90)


def send_test(device_id: str) -> dict:
    with db.connect() as conn:
        device = conn.execute(
            "SELECT persona_id FROM devices WHERE device_id = ? AND role = 'guardian'",
            (device_id,),
        ).fetchone()
    if device is None or not device["persona_id"]:
        raise ValueError("등록된 보호자 기기를 찾지 못했습니다.")
    return send(device["persona_id"], {
        "kind": "test",
        "title": "다소니 알림 준비 완료",
        "body": "휴대폰이 잠겨 있어도 중요한 소식을 알려드릴게요.",
        "tag": "dasoni-push-test",
        "url": "/#guardian",
        "urgent": False,
    }, ttl=60)
