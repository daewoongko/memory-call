"""ElevenLabs Scribe v2 Realtime browser authentication.

The permanent API key stays on the server. A browser receives only a
single-use token that expires after 15 minutes and is consumed on connection.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"
REALTIME_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
MODEL_ID = "scribe_v2_realtime"
REQUEST_TIMEOUT_SECONDS = max(
    3.0, float(os.getenv("ELEVENLABS_STT_TOKEN_TIMEOUT_SECONDS", "10"))
)


class ElevenLabsSTTNotConfigured(RuntimeError):
    """The server has no ElevenLabs credential."""


class ElevenLabsSTTUnavailable(RuntimeError):
    """ElevenLabs did not issue a realtime token."""


def create_realtime_token() -> dict:
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise ElevenLabsSTTNotConfigured("ELEVENLABS_API_KEY is not configured")

    request = urllib.request.Request(
        TOKEN_URL,
        headers={"xi-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-300:]
        raise ElevenLabsSTTUnavailable(
            f"ElevenLabs realtime token {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ElevenLabsSTTUnavailable(
            "ElevenLabs realtime token request failed"
        ) from exc

    token = str(payload.get("token") or "").strip()
    if not token:
        raise ElevenLabsSTTUnavailable("ElevenLabs returned an empty token")
    return {
        "token": token,
        "websocket_url": REALTIME_URL,
        "model_id": MODEL_ID,
        "audio_format": "pcm_16000",
        "expires_in_seconds": 900,
    }
