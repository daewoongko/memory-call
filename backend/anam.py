"""Server-only Anam session-token exchange.

The permanent API key and avatar id never leave this process. Browsers receive
only Anam's short-lived session token for the active persona.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib import error, request


API_URL = "https://api.anam.ai/v1/auth/session-token"
AVATAR_API_URL = "https://api.anam.ai/v1/avatars"
DEFAULT_AVATAR_MODEL = "cara-4"
DEFAULT_TIMEOUT_SECONDS = 12.0


class AnamNotConfigured(RuntimeError):
    pass


class AnamUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.getenv("ANAM_API_KEY", "").strip())


def _timeout_seconds() -> float:
    try:
        value = float(os.getenv("ANAM_REQUEST_TIMEOUT_SECONDS", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _api_key() -> str:
    api_key = os.getenv("ANAM_API_KEY", "").strip()
    if not api_key:
        raise AnamNotConfigured("ANAM_API_KEY is not configured")
    return api_key


def create_session_token(
    *, avatar_id: str, persona_name: str | None = None,
    avatar_model: str | None = None,
) -> dict[str, str]:
    api_key = _api_key()
    avatar_id = avatar_id.strip()
    if not avatar_id:
        raise AnamNotConfigured("The selected family member has no ready Anam avatar")
    persona_config = {
        "name": (persona_name or "memory-call-family")[:80],
        "avatarId": avatar_id,
        "avatarModel": (
            (avatar_model or "").strip()
            or os.getenv("ANAM_AVATAR_MODEL", "").strip()
            or DEFAULT_AVATAR_MODEL
        ),
        "enableAudioPassthrough": True,
    }
    req = request.Request(
        API_URL,
        data=json.dumps({"personaConfig": persona_config}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        # Do not proxy provider payloads: they can contain account details.
        raise AnamUnavailable(f"Anam session request failed ({exc.code})") from exc
    except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AnamUnavailable("Anam session service is unavailable") from exc

    token = payload.get("sessionToken") or payload.get("session_token")
    if not isinstance(token, str) or not token:
        raise AnamUnavailable("Anam returned no session token")
    return {
        "session_token": token,
        "avatar_id": avatar_id,
        "avatar_model": persona_config["avatarModel"],
    }


def create_avatar(
    *, display_name: str, image: bytes, filename: str = "avatar.jpg",
    content_type: str | None = None, avatar_model: str | None = None,
) -> dict[str, str]:
    """Create an Anam custom avatar from a server-side prepared image."""
    api_key = _api_key()
    boundary = f"----memory-call-{uuid.uuid4().hex}"
    mime = content_type or mimetypes.guess_type(filename)[0] or "image/jpeg"
    model = (avatar_model or os.getenv("ANAM_AVATAR_MODEL", "").strip()
             or DEFAULT_AVATAR_MODEL)
    fields = {
        "displayName": display_name[:80],
        "avatarModel": model,
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode("utf-8"), b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="imageFile"; '
            f'filename="{Path(filename).name}"\r\n'
        ).encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(), image, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    req = request.Request(
        AVATAR_API_URL,
        data=b"".join(chunks),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise AnamUnavailable(f"Anam avatar creation failed ({exc.code})") from exc
    except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AnamUnavailable("Anam avatar service is unavailable") from exc
    avatar_id = payload.get("id") or payload.get("avatarId") or payload.get("avatar_id")
    if not isinstance(avatar_id, str) or not avatar_id:
        raise AnamUnavailable("Anam returned no avatar id")
    return {"avatar_id": avatar_id, "avatar_model": model}
