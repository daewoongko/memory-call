"""Server-only Anam session-token exchange.

The permanent API key and avatar id never leave this process. Browsers receive
only Anam's short-lived session token for the active persona.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from functools import lru_cache
from pathlib import Path
from urllib import error, request
from urllib.parse import urlencode


API_URL = "https://api.anam.ai/v1/auth/session-token"
AVATAR_API_URL = "https://api.anam.ai/v1/avatars"
# Use the active model of an existing avatar whenever possible. cara-4 is the
# model currently attached to the deployment's approved custom avatar.
DEFAULT_AVATAR_MODEL = "cara-4"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_DIRECTOR_STYLE = (
    "Keep steady eye contact and remain calm, gentle, and attentive. "
    "Use restrained head movement and subtle facial expressions. "
    "Avoid broad smiles, surprise, laughter, emphatic nodding, and exaggerated emotion. "
    "Behave like a family member speaking softly with an elderly grandfather on a video call."
)
DEFAULT_EXPRESSIVITY = 0.05


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


def _director_notes(expressivity: float | None = None) -> dict[str, str | float]:
    style = os.getenv("ANAM_DIRECTOR_STYLE", "").strip() or DEFAULT_DIRECTOR_STYLE
    if expressivity is None:
        try:
            expressivity = float(os.getenv("ANAM_EXPRESSIVITY", ""))
        except ValueError:
            expressivity = DEFAULT_EXPRESSIVITY
    if not 0.0 <= expressivity <= 1.0:
        expressivity = DEFAULT_EXPRESSIVITY
    return {
        "customStylePrompt": style,
        "expressivity": expressivity,
    }


@lru_cache(maxsize=8)
def _find_avatar_by_name_cached(display_name: str) -> tuple[str, str] | None:
    """Find an existing account avatar without exposing provider metadata.

    Render's ephemeral database cannot retain the avatar id across deploys.
    Looking it up by a non-secret display name lets the server recover the id
    while keeping that id and the provider response out of the browser.
    """
    api_key = _api_key()
    page = 1
    while page <= 20:
        url = f"{AVATAR_API_URL}?{urlencode({'page': page, 'perPage': 100})}"
        req = request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=_timeout_seconds()) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise AnamUnavailable(f"Anam avatar lookup failed ({exc.code})") from exc
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AnamUnavailable("Anam avatar lookup is unavailable") from exc

        avatars = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(avatars, list):
            raise AnamUnavailable("Anam returned an invalid avatar list")
        for avatar in avatars:
            if not isinstance(avatar, dict):
                continue
            candidate_name = avatar.get("displayName") or avatar.get("display_name")
            avatar_id = avatar.get("id") or avatar.get("avatarId")
            if (
                isinstance(candidate_name, str)
                and candidate_name.strip().casefold() == display_name.casefold()
                and isinstance(avatar_id, str)
                and avatar_id.strip()
            ):
                model = avatar.get("activeVersion") or avatar.get("avatarModel")
                return avatar_id.strip(), (
                    model.strip() if isinstance(model, str) and model.strip()
                    else DEFAULT_AVATAR_MODEL
                )

        meta = payload.get("meta") if isinstance(payload, dict) else None
        next_page = meta.get("next") if isinstance(meta, dict) else None
        if not next_page:
            return None
        try:
            page = int(next_page)
        except (TypeError, ValueError):
            return None
    return None


def find_avatar_by_name(display_name: str) -> dict[str, str] | None:
    normalized = display_name.strip()
    if not normalized:
        return None
    selected = _find_avatar_by_name_cached(normalized)
    if not selected:
        return None
    avatar_id, avatar_model = selected
    return {"avatar_id": avatar_id, "avatar_model": avatar_model}


def create_session_token(
    *, avatar_id: str, persona_name: str | None = None,
    avatar_model: str | None = None, expressivity: float | None = None,
) -> dict[str, str]:
    api_key = _api_key()
    avatar_id = avatar_id.strip()
    if not avatar_id:
        raise AnamNotConfigured("The selected family member has no ready Anam avatar")
    model = (
        (avatar_model or "").strip()
        or os.getenv("ANAM_AVATAR_MODEL", "").strip()
        or DEFAULT_AVATAR_MODEL
    )
    persona_config = {
        "name": (persona_name or "memory-call-family")[:80],
        "avatarId": avatar_id,
        "avatarModel": model,
        "enableAudioPassthrough": True,
    }
    if model in {"cara-4", "cara-4-latest"}:
        persona_config["directorNotes"] = _director_notes(expressivity)
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
