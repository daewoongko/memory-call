"""Keep the local GPU TTS server reachable through a Cloudflare Quick Tunnel.

The bridge owns two child processes:

* ``tts_server.py`` running only on 127.0.0.1
* ``musetalk_server.py`` running only on 127.0.0.1 (optional/fail-open)
* ``cloudflared tunnel --url ...`` exposing that loopback server

It registers each newly-created Quick Tunnel URL with the deployed Memory Call
API and repeats the same request as a heartbeat.  The shared Bearer token is
never passed on a command line or written to logs.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib import error, parse, request

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENDER_URL = "https://memory-call.onrender.com"
REGISTER_PATH = "/api/tts/bridge/register"
TOKEN_ENV = "TTS_BRIDGE_TOKEN"
RENDER_URL_ENV = "MEMORY_CALL_RENDER_URL"
TUNNEL_URL_PATTERN = re.compile(
    r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com(?![a-z0-9.-])",
    re.IGNORECASE,
)
_LOOPBACK_OPENER = request.build_opener(request.ProxyHandler({}))
TOKEN_PLACEHOLDER = "replace-with-a-long-random-token"


class BridgeError(RuntimeError):
    """Base error for bridge configuration and runtime failures."""


class ProcessExited(BridgeError):
    """A managed child process exited before completing its current stage."""


class RegistrationError(BridgeError):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class BridgeConfig:
    render_url: str
    token: str
    tts_python: Path
    cloudflared: Path
    reference: Path
    port: int = 8001
    heartbeat_seconds: float = 45.0
    tts_startup_timeout: float = 600.0
    tunnel_url_timeout: float = 90.0
    restart_delay: float = 5.0
    musetalk_enabled: bool = True
    musetalk_python: Path | None = None
    musetalk_dir: Path | None = None
    musetalk_source_video: Path | None = None
    musetalk_port: int = 8002
    musetalk_batch_size: int = 32
    musetalk_fallback_batch_size: int = 20


def load_local_env() -> None:
    """Load .env when python-dotenv is available, preserving explicit values."""
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env", override=False)


def require_bridge_token(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    token = env.get(TOKEN_ENV, "").strip()
    if (
        len(token) >= 32
        and not any(character.isspace() for character in token)
        and token != TOKEN_PLACEHOLDER
    ):
        return token
    raise BridgeError(
        "TTS_BRIDGE_TOKEN must be a non-placeholder secret of at least 32 "
        "characters with no whitespace. Configure the same secret locally and "
        "as a Render secret. PowerShell generation example (assignment does not "
        "print the value):\n"
        "$env:TTS_BRIDGE_TOKEN = (& python -c \"import secrets; "
        "print(secrets.token_urlsafe(48))\")"
    )


def normalize_render_url(value: str) -> str:
    """Return a safe origin URL for bridge registration."""
    candidate = value.strip().rstrip("/")
    try:
        parts = parse.urlsplit(candidate)
        _ = parts.port
    except ValueError as exc:
        raise BridgeError(f"Invalid Render URL: {value!r}") from exc

    host = (parts.hostname or "").lower()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if parts.scheme not in ({"http", "https"} if loopback else {"https"}):
        raise BridgeError("Render URL must use HTTPS (HTTP is allowed only for loopback).")
    if not host or parts.username or parts.password:
        raise BridgeError("Render URL must be an origin without credentials.")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise BridgeError("Render URL must not contain a path, query, or fragment.")
    return parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def parse_trycloudflare_url(text: str) -> str | None:
    """Extract and strictly validate a Cloudflare Quick Tunnel URL."""
    for match in TUNNEL_URL_PATTERN.finditer(text):
        parts = parse.urlsplit(match.group(0))
        host = (parts.hostname or "").lower()
        label = host.removesuffix(".trycloudflare.com")
        if (
            parts.scheme.lower() == "https"
            and host.endswith(".trycloudflare.com")
            and bool(label)
            and len(label) <= 63
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            and parts.port is None
        ):
            return f"https://{host}"
    return None


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _python_runs(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def find_tts_python(
    root: Path = ROOT,
    environ: dict[str, str] | None = None,
    *,
    probe: Callable[[Path], bool] = _python_runs,
) -> Path:
    """Locate a working TTS virtual-environment interpreter."""
    env = os.environ if environ is None else environ
    configured = (env.get("TTS_PYTHON_PATH") or env.get("TTS_PYTHON") or "").strip()
    if configured:
        path = _expand_path(configured)
        if not path.is_file() or not probe(path):
            raise BridgeError(f"Configured TTS Python is not runnable: {path}")
        return path

    relative = (
        (".venv-tts/Scripts/python.exe", ".venv-tts-recovered/Scripts/python.exe")
        if os.name == "nt"
        else (".venv-tts/bin/python", ".venv-tts-recovered/bin/python")
    )
    broken: list[Path] = []
    for item in relative:
        path = (root / item).resolve()
        if path.is_file() and probe(path):
            return path
        if path.is_file():
            broken.append(path)

    detail = f" Existing but broken: {', '.join(map(str, broken))}." if broken else ""
    raise BridgeError(
        "No runnable TTS Python was found. Run tools/setup_tts_runtime.ps1, then "
        "set TTS_PYTHON_PATH to the Python path it reports." + detail
    )


def find_musetalk_python(
    root: Path = ROOT,
    environ: dict[str, str] | None = None,
    *,
    probe: Callable[[Path], bool] = _python_runs,
) -> Path:
    """Locate the isolated Python 3.10 runtime prepared for MuseTalk."""
    env = os.environ if environ is None else environ
    configured = env.get("MUSETALK_PYTHON_PATH", "").strip()
    if configured:
        path = _expand_path(configured)
        if not path.is_file() or not probe(path):
            raise BridgeError(f"Configured MuseTalk Python is not runnable: {path}")
        return path

    candidates = (
        root / ".tools" / "python310" / "bin" / "python.exe",
        root / ".venv-musetalk" / "Scripts" / "python.exe",
    ) if os.name == "nt" else (
        root / ".tools" / "python310" / "bin" / "python",
        root / ".venv-musetalk" / "bin" / "python",
    )
    for path in candidates:
        resolved = path.resolve()
        if resolved.is_file() and probe(resolved):
            return resolved
    raise BridgeError(
        "No runnable MuseTalk Python was found. Run "
        "tools/setup_musetalk_runtime.ps1 or set MUSETALK_PYTHON_PATH."
    )


def find_cloudflared(
    root: Path = ROOT,
    environ: dict[str, str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> Path:
    """Find cloudflared by explicit path, repository tool, then PATH."""
    env = os.environ if environ is None else environ
    configured = env.get("CLOUDFLARED_PATH", "").strip()
    if configured:
        path = _expand_path(configured)
        if not path.is_file():
            raise BridgeError(f"CLOUDFLARED_PATH does not point to a file: {path}")
        return path

    filename = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    repository_copy = (root / ".tools" / filename).resolve()
    if repository_copy.is_file():
        return repository_copy

    found = which("cloudflared") or which(filename)
    if found:
        return Path(found).resolve()
    raise BridgeError(
        "cloudflared was not found. Run tools/setup_cloudflared.ps1 or set "
        "CLOUDFLARED_PATH."
    )


def _validate_service_url(value: str) -> str:
    exact = parse_trycloudflare_url(value)
    if exact != value.lower().rstrip("/"):
        raise BridgeError("Only a bare HTTPS *.trycloudflare.com URL may be registered.")
    return exact


def register_bridge(
    render_url: str,
    service_url: str,
    token: str,
    *,
    timeout: float = 15.0,
    opener: Callable[..., object] = request.urlopen,
) -> object:
    """Register/heartbeat the current tunnel using the fixed backend contract."""
    origin = normalize_render_url(render_url)
    public_url = _validate_service_url(service_url)
    payload = json.dumps(
        {"service_url": public_url}, separators=(",", ":")
    ).encode("utf-8")
    req = request.Request(
        f"{origin}{REGISTER_PATH}",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "memory-call-tts-bridge/1.0",
        },
    )
    try:
        with opener(req, timeout=timeout) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except error.HTTPError as exc:
        retryable = exc.code in {408, 425, 429} or exc.code >= 500
        raise RegistrationError(
            f"Render bridge registration returned HTTP {exc.code}.",
            retryable=retryable,
            status=exc.code,
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RegistrationError(
            "Render bridge registration could not reach the server.", retryable=True
        ) from exc

    if not 200 <= status < 300:
        retryable = status in {408, 425, 429} or status >= 500
        raise RegistrationError(
            f"Render bridge registration returned HTTP {status}.",
            retryable=retryable,
            status=status,
        )
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": status}


def _authorized_health_request(port: int, token: str, timeout: float) -> bool:
    req = request.Request(
        f"http://127.0.0.1:{port}/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        # Never allow OS/user proxy settings to receive the local Bearer token.
        with _LOOPBACK_OPENER.open(req, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("ok") is True
    except (
        error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return False


def wait_for_tts(
    process: subprocess.Popen,
    port: int,
    token: str,
    stop_event: threading.Event,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while not stop_event.is_set():
        code = process.poll()
        if code is not None:
            raise ProcessExited(f"TTS server exited during startup (code {code}).")
        if _authorized_health_request(port, token, timeout=3.0):
            return
        if time.monotonic() >= deadline:
            raise BridgeError(f"TTS server did not become healthy within {timeout:g}s.")
        stop_event.wait(1.0)
    raise BridgeError("Bridge shutdown requested.")


def start_tts(config: BridgeConfig) -> subprocess.Popen:
    env = os.environ.copy()
    env[TOKEN_ENV] = config.token
    env["MUSE_TALK_ENABLED"] = "true" if config.musetalk_enabled else "false"
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        str(config.tts_python),
        "-u",
        str(ROOT / "tools" / "tts_server.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(config.port),
        "--reference",
        str(config.reference),
    ]
    try:
        return subprocess.Popen(command, cwd=ROOT, env=env)
    except OSError as exc:
        raise BridgeError(f"Unable to start the TTS Python process: {exc}") from exc


def start_musetalk(config: BridgeConfig) -> subprocess.Popen:
    """Start the optional MuseTalk worker without exposing a second tunnel."""
    if (
        not config.musetalk_enabled
        or config.musetalk_python is None
        or config.musetalk_dir is None
        or config.musetalk_source_video is None
    ):
        raise BridgeError("MuseTalk is not configured")
    env = os.environ.copy()
    env[TOKEN_ENV] = config.token
    env["PYTHONUNBUFFERED"] = "1"
    # All model files have already been downloaded by the setup command. Keep
    # service startup deterministic and prevent a model hub request from
    # delaying the existing audio bridge.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    command = [
        str(config.musetalk_python),
        "-u",
        str(ROOT / "tools" / "musetalk_server.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(config.musetalk_port),
        "--musetalk-dir",
        str(config.musetalk_dir),
        "--source-video",
        str(config.musetalk_source_video),
        "--batch-size",
        str(config.musetalk_batch_size),
        "--fallback-batch-size",
        str(config.musetalk_fallback_batch_size),
    ]
    try:
        return subprocess.Popen(command, cwd=config.musetalk_dir, env=env)
    except OSError as exc:
        raise BridgeError(f"Unable to start the MuseTalk process: {exc}") from exc


def _read_tunnel_output(
    process: subprocess.Popen,
    urls: queue.Queue[str],
) -> None:
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in stream:
            clean = line.rstrip()
            if clean:
                print(f"[cloudflared] {clean}", flush=True)
            public_url = parse_trycloudflare_url(line)
            if public_url and urls.empty():
                urls.put(public_url)
    finally:
        stream.close()


def start_tunnel(config: BridgeConfig) -> tuple[subprocess.Popen, queue.Queue[str]]:
    command = [
        str(config.cloudflared),
        "tunnel",
        "--url",
        f"http://127.0.0.1:{config.port}",
        "--no-autoupdate",
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise BridgeError(f"Unable to start cloudflared: {exc}") from exc
    urls: queue.Queue[str] = queue.Queue(maxsize=1)
    threading.Thread(
        target=_read_tunnel_output,
        args=(process, urls),
        name="cloudflared-output",
        daemon=True,
    ).start()
    return process, urls


def wait_for_tunnel_url(
    process: subprocess.Popen,
    urls: queue.Queue[str],
    stop_event: threading.Event,
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    while not stop_event.is_set():
        try:
            return urls.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            code = process.poll()
            if code is not None:
                raise ProcessExited(f"cloudflared exited before publishing a URL (code {code}).")
            if time.monotonic() >= deadline:
                raise BridgeError(f"cloudflared did not publish a URL within {timeout:g}s.")
    raise BridgeError("Bridge shutdown requested.")


def terminate_process(process: subprocess.Popen | None, timeout: float = 10.0) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            # Best effort during shutdown; do not hide the triggering failure.
            return


def _register_until_success(
    config: BridgeConfig,
    service_url: str,
    tts: subprocess.Popen,
    tunnel: subprocess.Popen,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        if tts.poll() is not None:
            raise ProcessExited("TTS server exited before bridge registration.")
        if tunnel.poll() is not None:
            raise ProcessExited("cloudflared exited before bridge registration.")
        try:
            register_bridge(config.render_url, service_url, config.token)
            print(f"Bridge registered: {service_url}", flush=True)
            return
        except RegistrationError as exc:
            if not exc.retryable:
                raise
            print(f"Registration retry: {exc}", file=sys.stderr, flush=True)
            stop_event.wait(config.restart_delay)
    raise BridgeError("Bridge shutdown requested.")


def supervise(config: BridgeConfig, stop_event: threading.Event) -> None:
    """Supervise TTS and tunnel lifetimes until shutdown is requested."""
    tts: subprocess.Popen | None = None
    musetalk: subprocess.Popen | None = None
    musetalk_ready = False
    next_musetalk_restart = 0.0
    tunnel: subprocess.Popen | None = None
    try:
        while not stop_event.is_set():
            if tts is None:
                try:
                    print("Starting local GPU TTS server...", flush=True)
                    tts = start_tts(config)
                    wait_for_tts(
                        tts,
                        config.port,
                        config.token,
                        stop_event,
                        config.tts_startup_timeout,
                    )
                    print("Local GPU TTS server is healthy.", flush=True)
                except BridgeError as exc:
                    terminate_process(tts)
                    tts = None
                    if stop_event.is_set():
                        break
                    print(f"TTS restart required: {exc}", file=sys.stderr, flush=True)
                    stop_event.wait(config.restart_delay)
                    continue

            # MuseTalk is optional: launch it in parallel with tunnel setup and
            # let /synthesize-video return the already-generated WAV until the
            # worker becomes healthy. A model/OOM failure must never take down
            # the primary Chatterbox bridge.
            if (
                config.musetalk_enabled
                and musetalk is None
                and time.monotonic() >= next_musetalk_restart
            ):
                try:
                    print("Starting local MuseTalk worker...", flush=True)
                    musetalk = start_musetalk(config)
                    musetalk_ready = False
                except BridgeError:
                    print(
                        "MuseTalk could not start; audio fallback remains active.",
                        file=sys.stderr,
                        flush=True,
                    )
                    musetalk = None
                    next_musetalk_restart = time.monotonic() + config.restart_delay

            try:
                print("Starting Cloudflare Quick Tunnel...", flush=True)
                tunnel, urls = start_tunnel(config)
                service_url = wait_for_tunnel_url(
                    tunnel, urls, stop_event, config.tunnel_url_timeout
                )
                _register_until_success(config, service_url, tts, tunnel, stop_event)
                next_heartbeat = time.monotonic() + config.heartbeat_seconds

                while not stop_event.is_set():
                    if tts.poll() is not None:
                        raise ProcessExited("Local TTS server stopped.")
                    if tunnel.poll() is not None:
                        raise ProcessExited("Cloudflare Quick Tunnel stopped.")

                    if musetalk is not None and musetalk.poll() is not None:
                        print(
                            "MuseTalk stopped; audio fallback remains active.",
                            file=sys.stderr,
                            flush=True,
                        )
                        terminate_process(musetalk)
                        musetalk = None
                        musetalk_ready = False
                        next_musetalk_restart = (
                            time.monotonic() + config.restart_delay
                        )
                    if (
                        musetalk is None
                        and config.musetalk_enabled
                        and time.monotonic() >= next_musetalk_restart
                    ):
                        try:
                            musetalk = start_musetalk(config)
                            musetalk_ready = False
                            print("Restarting local MuseTalk worker...", flush=True)
                        except BridgeError:
                            next_musetalk_restart = (
                                time.monotonic() + config.restart_delay
                            )
                    if (
                        musetalk is not None
                        and not musetalk_ready
                        and _authorized_health_request(
                            config.musetalk_port,
                            config.token,
                            timeout=0.25,
                        )
                    ):
                        musetalk_ready = True
                        print("Local MuseTalk worker is healthy.", flush=True)

                    now = time.monotonic()
                    if now >= next_heartbeat:
                        try:
                            register_bridge(config.render_url, service_url, config.token)
                            print("Bridge heartbeat accepted.", flush=True)
                            next_heartbeat = now + config.heartbeat_seconds
                        except RegistrationError as exc:
                            if not exc.retryable:
                                raise
                            print(f"Heartbeat retry: {exc}", file=sys.stderr, flush=True)
                            next_heartbeat = now + min(
                                config.restart_delay, config.heartbeat_seconds
                            )
                    stop_event.wait(min(1.0, max(0.05, next_heartbeat - now)))
            except RegistrationError:
                # Authentication and other permanent 4xx errors need operator action.
                raise
            except BridgeError as exc:
                tts_alive = tts is not None and tts.poll() is None
                print(f"Bridge process restart: {exc}", file=sys.stderr, flush=True)
                terminate_process(tunnel)
                tunnel = None
                if not tts_alive:
                    terminate_process(tts)
                    tts = None
                if not stop_event.is_set():
                    stop_event.wait(config.restart_delay)
    finally:
        terminate_process(tunnel)
        terminate_process(musetalk)
        terminate_process(tts)


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _enabled_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Expose local GPU TTS and keep its Render registration alive."
    )
    parser.add_argument("--render-url", default=None)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--reference", type=Path, default=ROOT / "data" / "voice" / "reference.wav"
    )
    parser.add_argument("--heartbeat-seconds", type=_positive_float, default=45.0)
    parser.add_argument("--tts-startup-timeout", type=_positive_float, default=600.0)
    parser.add_argument("--tunnel-url-timeout", type=_positive_float, default=90.0)
    parser.add_argument("--restart-delay", type=_positive_float, default=5.0)
    parser.add_argument(
        "--musetalk",
        action=argparse.BooleanOptionalAction,
        default=_enabled_env("MUSE_TALK_ENABLED", True),
        help="run the optional loopback MuseTalk worker (default: enabled)",
    )
    parser.add_argument(
        "--musetalk-port", type=int, default=_int_env("MUSE_TALK_PORT", 8002)
    )
    parser.add_argument("--musetalk-python", type=Path, default=None)
    parser.add_argument("--musetalk-dir", type=Path, default=None)
    parser.add_argument("--musetalk-source-video", type=Path, default=None)
    parser.add_argument("--musetalk-batch-size", type=int, default=32)
    parser.add_argument("--musetalk-fallback-batch-size", type=int, default=20)
    return parser


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def request_stop(signum, _frame) -> None:
        print(f"Shutdown requested (signal {signum}).", flush=True)
        stop_event.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    args = build_parser().parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise BridgeError("Port must be between 1 and 65535.")
        if args.musetalk_port != 8002 or args.musetalk_port == args.port:
            raise BridgeError("MuseTalk must use its fixed loopback port 8002.")
        token = require_bridge_token()
        render_url = normalize_render_url(
            args.render_url
            or os.getenv(RENDER_URL_ENV, "").strip()
            or DEFAULT_RENDER_URL
        )
        reference = args.reference
        if not reference.is_absolute():
            reference = ROOT / reference
        reference = reference.resolve()
        if not reference.is_file():
            raise BridgeError(f"TTS reference audio was not found: {reference}")

        musetalk_enabled = bool(args.musetalk)
        musetalk_python: Path | None = None
        musetalk_dir: Path | None = None
        musetalk_source_video: Path | None = None
        if musetalk_enabled:
            try:
                musetalk_python = (
                    args.musetalk_python.resolve()
                    if args.musetalk_python is not None
                    else find_musetalk_python()
                )
                musetalk_dir = (
                    args.musetalk_dir
                    or Path(
                        os.getenv("MEMORY_CALL_MUSETALK_DIR", "").strip()
                        or ROOT.parent / "Models" / "MuseTalk"
                    )
                ).resolve()
                musetalk_source_video = (
                    args.musetalk_source_video
                    or Path(
                        os.getenv("MUSE_TALK_SOURCE_VIDEO", "").strip()
                        or ROOT / "data" / "faces" / "loops" / "idle.mp4"
                    )
                ).resolve()
                if not (musetalk_dir / "scripts" / "realtime_inference.py").is_file():
                    raise BridgeError("MuseTalk source checkout was not found")
                if not musetalk_source_video.is_file():
                    raise BridgeError("MuseTalk source video was not found")
                if args.musetalk_batch_size <= 0 or args.musetalk_fallback_batch_size <= 0:
                    raise BridgeError("MuseTalk batch sizes must be greater than zero.")
            except (BridgeError, OSError) as exc:
                print(
                    f"MuseTalk disabled for this run: {exc}. "
                    "Audio fallback remains available.",
                    file=sys.stderr,
                )
                musetalk_enabled = False
                musetalk_python = None
                musetalk_dir = None
                musetalk_source_video = None
        config = BridgeConfig(
            render_url=render_url,
            token=token,
            tts_python=find_tts_python(),
            cloudflared=find_cloudflared(),
            reference=reference,
            port=args.port,
            heartbeat_seconds=args.heartbeat_seconds,
            tts_startup_timeout=args.tts_startup_timeout,
            tunnel_url_timeout=args.tunnel_url_timeout,
            restart_delay=args.restart_delay,
            musetalk_enabled=musetalk_enabled,
            musetalk_python=musetalk_python,
            musetalk_dir=musetalk_dir,
            musetalk_source_video=musetalk_source_video,
            musetalk_port=args.musetalk_port,
            musetalk_batch_size=args.musetalk_batch_size,
            musetalk_fallback_batch_size=args.musetalk_fallback_batch_size,
        )
    except BridgeError as exc:
        print(f"TTS bridge configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"Render API: {config.render_url}")
    print(f"Local TTS:  http://127.0.0.1:{config.port}")
    print(f"TTS Python: {config.tts_python}")
    if config.musetalk_enabled:
        print(f"Local MuseTalk: http://127.0.0.1:{config.musetalk_port}")
        print(f"MuseTalk Python: {config.musetalk_python}")
    else:
        print("Local MuseTalk: disabled; audio fallback active")
    print(f"cloudflared: {config.cloudflared}")
    print("TTS_BRIDGE_TOKEN: configured (value hidden)")

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    try:
        supervise(config, stop_event)
    except RegistrationError as exc:
        if exc.status in {401, 403}:
            message = "Render rejected TTS_BRIDGE_TOKEN; local and Render secrets must match."
        else:
            message = str(exc)
        print(f"TTS bridge stopped: {message}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        stop_event.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
