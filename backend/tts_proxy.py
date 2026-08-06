"""Proxy requests to a fixed TTS service or an authenticated dynamic bridge."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
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


class TTSUnavailable(RuntimeError):
    """The selected TTS service could not be reached or failed to synthesize."""


class TTSBridgeError(ValueError):
    """A dynamic TTS bridge registration is invalid."""


class TTSBridgeUnauthorized(PermissionError):
    """The bridge registration Bearer token is missing or invalid."""


class TTSBridgeNotConfigured(RuntimeError):
    """Dynamic bridge registration is disabled until a token is configured."""


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


def _call(path: str, payload: dict | None = None, timeout: float = 120) -> bytes:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    service_url, _is_dynamic_bridge = _target()
    if BRIDGE_TOKEN:
        headers["Authorization"] = f"Bearer {BRIDGE_TOKEN}"
    req = request.Request(
        f"{service_url}{path}",
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
        raise TTSUnavailable(detail or f"TTS service error ({exc.code})") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise TTSUnavailable(f"Unable to connect to TTS service: {exc}") from exc


def health() -> dict:
    try:
        result = json.loads(_call("/health", timeout=2).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSUnavailable("TTS service returned an invalid health response") from exc
    if not isinstance(result, dict):
        raise TTSUnavailable("TTS service returned an invalid health response")
    return {**result, "proxy": bridge_status(include_service_url=False)}


def synthesize(text: str, rate: float) -> bytes:
    return _call("/synthesize", {"text": text, "rate": rate})
