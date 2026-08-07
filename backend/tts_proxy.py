"""Proxy requests to a fixed TTS service or an authenticated dynamic bridge."""

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


SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")
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
_ALLOWED_MEDIA_TYPES = frozenset({"audio/wav", "video/mp4"})
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


def _safe_tts_model(value: object) -> str | None:
    candidate = str(value).strip().lower() if value is not None else ""
    if candidate == "chatterbox-multilingual-v3":
        return candidate
    return None


def _safe_media_type(value: object) -> str | None:
    """Accept only the two response types in the public TTS contract."""
    candidate = str(value).split(";", 1)[0].strip().lower() if value else ""
    return candidate if candidate in _ALLOWED_MEDIA_TYPES else None


def _safe_lipsync_fallback(value: object) -> str | None:
    candidate = str(value).strip().lower() if value is not None else ""
    return "audio" if candidate == "audio" else None


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


def _duration_seconds_header(value: float) -> str:
    return f"{value:.3f}"


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
    """The selected TTS service could not be reached or failed to synthesize."""


class TTSBridgeError(ValueError):
    """A dynamic TTS bridge registration is invalid."""


class TTSBridgeUnauthorized(PermissionError):
    """The bridge registration Bearer token is missing or invalid."""


class TTSBridgeNotConfigured(RuntimeError):
    """Dynamic bridge registration is disabled until a token is configured."""


@dataclass(frozen=True)
class ProxyCallResult:
    """A buffered upstream response plus sanitized latency metadata."""

    body: bytes
    # urllib returns only after response headers. Because the local service
    # creates those headers after synthesis, this is upstream wait/TTFB rather
    # than a pure TCP/TLS connect measurement.
    upstream_wait_seconds: float
    proxy_read_seconds: float
    proxy_total_seconds: float
    media_type: str = "audio/wav"
    generation_seconds: float | None = None
    audio_duration_seconds: float | None = None
    local_request_id: str | None = None
    tts_request_seconds: float | None = None
    tts_queue_seconds: float | None = None
    tts_model_seconds: float | None = None
    tts_time_stretch_seconds: float | None = None
    tts_wav_encode_seconds: float | None = None
    tts_model: str | None = None
    lipsync_seconds: float | None = None
    lipsync_fallback: str | None = None

    def public_headers(self, *, request_id: str | None = None) -> dict[str, str]:
        """Build a small allowlisted header set safe for a public response."""
        headers: dict[str, str] = {}
        effective_request_id = _safe_request_id(request_id) or self.local_request_id
        if effective_request_id is not None:
            headers["X-Request-ID"] = effective_request_id
        if self.audio_duration_seconds is not None:
            headers["X-Audio-Duration"] = _duration_seconds_header(
                self.audio_duration_seconds
            )
        if self.generation_seconds is not None:
            headers["X-Generation-Seconds"] = _duration_seconds_header(
                self.generation_seconds
            )
        detailed_headers = (
            ("X-TTS-Request-Seconds", self.tts_request_seconds),
            ("X-TTS-Queue-Seconds", self.tts_queue_seconds),
            ("X-TTS-Generation-Seconds", self.tts_model_seconds),
            ("X-TTS-Time-Stretch-Seconds", self.tts_time_stretch_seconds),
            ("X-TTS-Wav-Encode-Seconds", self.tts_wav_encode_seconds),
        )
        for name, value in detailed_headers:
            if value is not None:
                headers[name] = _duration_seconds_header(value)
        if self.tts_model is not None:
            headers["X-TTS-Model"] = self.tts_model
        if self.lipsync_seconds is not None:
            headers["X-Lipsync-Seconds"] = _duration_seconds_header(
                self.lipsync_seconds
            )
        if self.lipsync_fallback is not None:
            headers["X-Lipsync-Fallback"] = self.lipsync_fallback

        metrics: list[str] = []
        if self.generation_seconds is not None:
            metrics.append(
                f"tts_total;dur={_duration_ms_metric(self.generation_seconds)}"
            )
        detailed_metrics = (
            ("tts_request", self.tts_request_seconds),
            ("tts_queue", self.tts_queue_seconds),
            ("tts_model", self.tts_model_seconds),
            ("tts_stretch", self.tts_time_stretch_seconds),
            ("tts_wav", self.tts_wav_encode_seconds),
        )
        for name, value in detailed_metrics:
            if value is not None:
                metrics.append(f"{name};dur={_duration_ms_metric(value)}")
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


def _call_with_metadata(
    path: str,
    payload: dict | None = None,
    timeout: float = 120,
    *,
    request_id: str | None = None,
    allowed_media_types: frozenset[str] = frozenset({"audio/wav"}),
    default_media_type: str | None = "audio/wav",
    validate_media_body: bool = False,
) -> ProxyCallResult:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    service_url, _is_dynamic_bridge = _target()
    if BRIDGE_TOKEN:
        headers["Authorization"] = f"Bearer {BRIDGE_TOKEN}"
    safe_request_id = _safe_request_id(request_id)
    if safe_request_id is not None:
        headers["X-Request-ID"] = safe_request_id
    req = request.Request(
        f"{service_url}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
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

    media_type = _safe_media_type(
        _header_value(response_headers, "Content-Type")
    ) or _safe_media_type(default_media_type)
    if media_type is None or media_type not in allowed_media_types:
        raise TTSUnavailable("TTS service returned an unsupported media type")

    generation_seconds = _safe_seconds(
        _header_value(response_headers, "X-Generation-Seconds")
    )
    audio_duration_seconds = _safe_seconds(
        _header_value(response_headers, "X-Audio-Duration")
    )
    local_request_id = _safe_request_id(
        _header_value(response_headers, "X-Request-ID")
    )
    tts_request_seconds = _safe_seconds(
        _header_value(response_headers, "X-TTS-Request-Seconds")
    )
    tts_queue_seconds = _safe_seconds(
        _header_value(response_headers, "X-TTS-Queue-Seconds")
    )
    tts_model_seconds = _safe_seconds(
        _header_value(response_headers, "X-TTS-Generation-Seconds")
    )
    tts_time_stretch_seconds = _safe_seconds(
        _header_value(response_headers, "X-TTS-Time-Stretch-Seconds")
    )
    tts_wav_encode_seconds = _safe_seconds(
        _header_value(response_headers, "X-TTS-Wav-Encode-Seconds")
    )
    tts_model = _safe_tts_model(_header_value(response_headers, "X-TTS-Model"))
    lipsync_seconds = _safe_seconds(
        _header_value(response_headers, "X-Lipsync-Seconds")
    )
    lipsync_fallback = _safe_lipsync_fallback(
        _header_value(response_headers, "X-Lipsync-Fallback")
    )
    if validate_media_body:
        if media_type == "video/mp4":
            if (
                len(response_body) < 12
                or response_body[4:8] != b"ftyp"
                or lipsync_fallback is not None
            ):
                raise TTSUnavailable("TTS service returned an invalid MP4 response")
        elif (
            len(response_body) < 44
            or response_body[:4] != b"RIFF"
            or response_body[8:12] != b"WAVE"
            or lipsync_fallback != "audio"
        ):
            raise TTSUnavailable("TTS service returned an invalid audio fallback")
    return ProxyCallResult(
        body=response_body,
        upstream_wait_seconds=max(0.0, connected - started),
        proxy_read_seconds=max(0.0, finished - connected),
        proxy_total_seconds=max(0.0, finished - started),
        media_type=media_type,
        generation_seconds=generation_seconds,
        audio_duration_seconds=audio_duration_seconds,
        local_request_id=local_request_id,
        tts_request_seconds=tts_request_seconds,
        tts_queue_seconds=tts_queue_seconds,
        tts_model_seconds=tts_model_seconds,
        tts_time_stretch_seconds=tts_time_stretch_seconds,
        tts_wav_encode_seconds=tts_wav_encode_seconds,
        tts_model=tts_model,
        lipsync_seconds=lipsync_seconds,
        lipsync_fallback=lipsync_fallback,
    )


def _call(path: str, payload: dict | None = None, timeout: float = 120) -> bytes:
    """Backward-compatible buffered call used by health and older callers."""
    return _call_with_metadata(path, payload, timeout).body


def health() -> dict:
    try:
        result = json.loads(_call("/health", timeout=2).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSUnavailable("TTS service returned an invalid health response") from exc
    if not isinstance(result, dict):
        raise TTSUnavailable("TTS service returned an invalid health response")
    return {**result, "proxy": bridge_status(include_service_url=False)}


def synthesize(text: str, rate: float) -> bytes:
    """Return WAV bytes for backward compatibility."""
    return synthesize_with_metadata(text, rate).body


def synthesize_with_metadata(
    text: str,
    rate: float,
    *,
    request_id: str | None = None,
) -> ProxyCallResult:
    return _call_with_metadata(
        "/synthesize",
        {"text": text, "rate": rate},
        request_id=request_id,
    )


def synthesize_video_with_metadata(
    text: str,
    rate: float,
    *,
    request_id: str | None = None,
) -> ProxyCallResult:
    """Return a MuseTalk MP4 or the local server's byte-identical WAV fallback."""
    return _call_with_metadata(
        "/synthesize-video",
        {"text": text, "rate": rate},
        timeout=180,
        request_id=request_id,
        allowed_media_types=_ALLOWED_MEDIA_TYPES,
        # This endpoint has two valid representations, so a missing/invalid
        # Content-Type must fail closed instead of being guessed.
        default_media_type=None,
        validate_media_body=True,
    )
