"""로컬 Chatterbox TTS 서비스와 통화 API 사이의 작은 프록시."""

from __future__ import annotations

import json
import os
from urllib import error, request


SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")


class TTSUnavailable(RuntimeError):
    """로컬 TTS 서비스에 연결할 수 없거나 합성에 실패했다."""


def _call(path: str, payload: dict | None = None, timeout: float = 120) -> bytes:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = request.Request(
        f"{SERVICE_URL}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        raise TTSUnavailable(detail or f"TTS 서비스 오류 ({exc.code})") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise TTSUnavailable(f"TTS 서비스에 연결할 수 없습니다: {exc}") from exc


def health() -> dict:
    return json.loads(_call("/health", timeout=2).decode("utf-8"))


def synthesize(text: str, rate: float) -> bytes:
    return _call("/synthesize", {"text": text, "rate": rate})
