"""Proxy lip-sync render calls to the local MuseTalk bridge (or its Quick Tunnel).

TTS synthesis itself no longer goes through this module — ``backend/api.py``
calls ``elevenlabs_tts`` directly for audio, since ElevenLabs is a hosted API
with no local GPU or tunnel dependency. This module now only forwards
already-synthesized WAV audio to the local MuseTalk worker for lip-sync
rendering, plus the bridge registration/health machinery that makes that
worker reachable from a deployed backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import math
import os
import re
import threading
import time
from urllib import error, request
from urllib.parse import urlsplit


SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")
BRIDGE_TOKEN = os.getenv("TTS_BRIDGE_TOKEN", "").strip()
TOKEN_PLACEHOLDER = "replace-with-a-long-random-token"


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


BRIDGE_TTL_SECONDS = _positive_float_env("TTS_BRIDGE_TTL_SECONDS", 120.0)
BRIDGE_ALLOWED_HOSTS = tuple(
    host.strip().lower().lstrip("*.")
    for host in os.getenv(
        "TTS_BRIDGE_ALLOWED_HOSTS", "trycloudflare.com"
    ).split(",")
    if host.strip().lstrip("*.")
)

_MAX_LOCAL_TIMING_SECONDS = 60.0 * 60.0
_MAX_UPSTREAM_BODY_BYTES = 64 * 1024 * 1024
_REQUEST_ID_PATTERN = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


class _NoRedirectHandler(request.HTTPRedirectHandler):
    """Fail closed instead of forwarding the bridge Bearer token on redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = request.build_opener(_NoRedirectHandler())


def _open_no_redirect(req: request.Request, timeout: float):
    return _NO_REDIRECT_OPENER.open(req, timeout=timeout)


def _safe_seconds(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(parsed)
        or parsed < 0
        or parsed > _MAX_LOCAL_TIMING_SECONDS
    ):
        return None
    return parsed


def _safe_request_id(value: object) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    return candidate.lower() if _REQUEST_ID_PATTERN.fullmatch(candidate) else None


def _header_value(headers: object, name: str) -> object | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is not None:
        value = getter(name)
        if value is not None:
            return value
    items = getattr(headers, "items", None)
    if items is not None:
        for key, value in items():
            if str(key).lower() == name.lower():
                return value
    return None


def _duration_ms_metric(value: float) -> str:
    return f"{max(0.0, value) * 1000.0:.1f}"


def _read_bounded(response: object) -> bytes:
    reader = getattr(response, "read")
    try:
        body = reader(_MAX_UPSTREAM_BODY_BYTES + 1)
    except TypeError:
        # Tiny unit-test doubles and a few alternate urllib-compatible clients
        # expose read() without a size argument. The post-read bound still
        # prevents such a response from reaching a public API response.
        body = reader()
    if len(body) > _MAX_UPSTREAM_BODY_BYTES:
        raise TTSUnavailable("TTS service response is too large")
    return body


class TTSUnavailable(RuntimeError):
    """The local MuseTalk lip-sync worker could not be reached or failed to render."""


class TTSBridgeError(ValueError):
    """A dynamic TTS bridge registration is invalid."""


class TTSBridgeUnauthorized(PermissionError):
    """The bridge registration Bearer token is missing or invalid."""


class TTSBridgeNotConfigured(RuntimeError):
    """Dynamic bridge registration is disabled until a token is configured."""


@dataclass(frozen=True)
class ProxyCallResult:
    """A buffered MuseTalk render response plus sanitized latency metadata."""

    body: bytes
    # urllib returns only after response headers. Because the local service
    # creates those headers after rendering, this is upstream wait/TTFB rather
    # than a pure TCP/TLS connect measurement.
    upstream_wait_seconds: float
    proxy_read_seconds: float
    proxy_total_seconds: float
    media_type: str = "video/mp4"
    local_request_id: str | None = None
    lipsync_seconds: float | None = None

    def public_headers(self, *, request_id: str | None = None) -> dict[str, str]:
        """Build a small allowlisted header set safe for a public response."""
        headers: dict[str, str] = {}
        effective_request_id = _safe_request_id(request_id) or self.local_request_id
        if effective_request_id is not None:
            headers["X-Request-ID"] = effective_request_id
        if self.lipsync_seconds is not None:
            headers["X-Lipsync-Seconds"] = f"{self.lipsync_seconds:.3f}"

        metrics: list[str] = []
        if self.lipsync_seconds is not None:
            metrics.append(
                f"lipsync;dur={_duration_ms_metric(self.lipsync_seconds)}"
            )
        metrics.extend(
            (
                f"upstream_wait;dur={_duration_ms_metric(self.upstream_wait_seconds)}",
                f"proxy_read;dur={_duration_ms_metric(self.proxy_read_seconds)}",
                f"proxy_total;dur={_duration_ms_metric(self.proxy_total_seconds)}",
            )
        )
        headers["Server-Timing"] = ", ".join(metrics)
        return headers


@dataclass(frozen=True)
class _BridgeRegistration:
    service_url: str
    expires_at: float


_bridge_lock = threading.RLock()
_bridge_registration: _BridgeRegistration | None = None


def verify_bridge_bearer(authorization: str | None) -> None:
    """Verify the shared secret used for bridge registration and proxy calls."""
    if (
        len(BRIDGE_TOKEN) < 32
        or any(character.isspace() for character in BRIDGE_TOKEN)
        or BRIDGE_TOKEN == TOKEN_PLACEHOLDER
    ):
        raise TTSBridgeNotConfigured(
            "TTS_BRIDGE_TOKEN must be a non-placeholder secret of at least "
            "32 characters with no whitespace"
        )

    scheme, separator, supplied = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(
            supplied.strip().encode("utf-8"),
            BRIDGE_TOKEN.encode("utf-8"),
        )
    ):
        raise TTSBridgeUnauthorized("invalid TTS bridge Bearer token")


def _host_is_allowed(hostname: str) -> bool:
    return any(
        hostname == allowed or hostname.endswith(f".{allowed}")
        for allowed in BRIDGE_ALLOWED_HOSTS
    )


def _normalize_bridge_url(service_url: str) -> str:
    value = service_url.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TTSBridgeError("invalid TTS bridge URL") from exc

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https":
        raise TTSBridgeError("TTS bridge URL must use https")
    if not hostname or not _host_is_allowed(hostname):
        raise TTSBridgeError("TTS bridge host is not allowed")
    if parsed.username or parsed.password:
        raise TTSBridgeError("TTS bridge URL must not contain credentials")
    if port not in (None, 443):
        raise TTSBridgeError("TTS bridge URL must use the default HTTPS port")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise TTSBridgeError("TTS bridge URL must be an origin without a path")

    return f"https://{hostname}"


def _bridge_state(now: float | None = None) -> tuple[_BridgeRegistration | None, float]:
    """Return an active registration and remaining TTL, clearing expired state."""
    current = time.monotonic() if now is None else now
    global _bridge_registration
    with _bridge_lock:
        registration = _bridge_registration
        if registration is None:
            return None, 0.0
        remaining = registration.expires_at - current
        if remaining <= 0:
            _bridge_registration = None
            return None, 0.0
        return registration, remaining


def bridge_status(
    now: float | None = None, *, include_service_url: bool = True
) -> dict:
    """Describe the routing decision without exposing the shared token."""
    registration, remaining = _bridge_state(now)
    if registration is not None:
        status = {
            "active": True,
            "source": "dynamic_bridge",
            "expires_in_seconds": round(remaining, 3),
            "ttl_seconds": BRIDGE_TTL_SECONDS,
        }
        if include_service_url:
            status["service_url"] = registration.service_url
        return status
    status = {
        "active": False,
        "source": "fixed_service",
        "expires_in_seconds": 0.0,
        "ttl_seconds": BRIDGE_TTL_SECONDS,
    }
    if include_service_url:
        status["service_url"] = SERVICE_URL
    return status


def register_bridge(service_url: str, now: float | None = None) -> dict:
    """Register or heartbeat a bridge. Authentication is enforced by the API."""
    normalized = _normalize_bridge_url(service_url)
    current = time.monotonic() if now is None else now
    registration = _BridgeRegistration(
        service_url=normalized,
        expires_at=current + BRIDGE_TTL_SECONDS,
    )
    global _bridge_registration
    with _bridge_lock:
        _bridge_registration = registration
        return bridge_status(now=current)


def _target() -> tuple[str, bool]:
    registration, _remaining = _bridge_state()
    if registration is not None:
        return registration.service_url, True
    return SERVICE_URL, False


def _request_metadata(
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120,
    request_id: str | None = None,
) -> tuple[bytes, object, float, float, float]:
    """Low-level authenticated call. Returns (body, headers, wait, read, total)."""
    headers: dict[str, str] = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    service_url, _is_dynamic_bridge = _target()
    if BRIDGE_TOKEN:
        headers["Authorization"] = f"Bearer {BRIDGE_TOKEN}"
    safe_request_id = _safe_request_id(request_id)
    if safe_request_id is not None:
        headers["X-Request-ID"] = safe_request_id
    req = request.Request(
        f"{service_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with _open_no_redirect(req, timeout=timeout) as response:
            connected = time.perf_counter()
            response_body = _read_bounded(response)
            finished = time.perf_counter()
            response_headers = getattr(response, "headers", None)
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        raise TTSUnavailable(detail or f"TTS service error ({exc.code})") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise TTSUnavailable(f"Unable to connect to TTS service: {exc}") from exc

    return (
        response_body,
        response_headers,
        max(0.0, connected - started),
        max(0.0, finished - connected),
        max(0.0, finished - started),
    )


def health() -> dict:
    body, _headers, _wait, _read, _total = _request_metadata("/health", timeout=5)
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSUnavailable("TTS service returned an invalid health response") from exc
    if not isinstance(result, dict):
        raise TTSUnavailable("TTS service returned an invalid health response")
    return {**result, "proxy": bridge_status(include_service_url=False)}


def render_lipsync_with_metadata(
    audio: bytes,
    *,
    request_id: str | None = None,
) -> ProxyCallResult:
    """Forward already-synthesized WAV audio to the local MuseTalk worker."""
    body, headers, upstream_wait, proxy_read, proxy_total = _request_metadata(
        "/render",
        method="POST",
        data=audio,
        content_type="audio/wav",
        timeout=180,
        request_id=request_id,
    )

    content_type = str(_header_value(headers, "Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != "video/mp4" or len(body) < 12 or body[4:8] != b"ftyp":
        raise TTSUnavailable("MuseTalk service returned an unsupported response")

    lipsync_seconds = _safe_seconds(_header_value(headers, "X-Lipsync-Seconds"))
    local_request_id = _safe_request_id(_header_value(headers, "X-Request-ID"))

    return ProxyCallResult(
        body=body,
        upstream_wait_seconds=upstream_wait,
        proxy_read_seconds=proxy_read,
        proxy_total_seconds=proxy_total,
        media_type="video/mp4",
        local_request_id=local_request_id,
        lipsync_seconds=lipsync_seconds,
    )
