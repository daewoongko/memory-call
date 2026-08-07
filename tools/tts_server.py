r"""GPU에 Chatterbox Multilingual V3를 계속 올려두는 로컬 TTS 서버.

실행:
    .\.venv-tts\Scripts\python.exe tools\tts_server.py

통화 API는 기본적으로 http://127.0.0.1:8001 에 있는 이 서버를 사용한다.
생성 음성은 메모리에서 바로 반환하며 디스크에 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import hmac
import io
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import NamedTuple
from urllib import error, request

import librosa
import numpy as np
import soundfile as sf
import torch
import uvicorn
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience for direct runs
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "data" / "voice" / "reference.wav"
TOKEN_ENV = "TTS_BRIDGE_TOKEN"
TOKEN_PLACEHOLDER = "replace-with-a-long-random-token"
GENERATION_SEED_ENV = "TTS_GENERATION_SEED"
DEFAULT_GENERATION_SEED = 20260806
DEFAULT_MUSETALK_URL = "http://127.0.0.1:8002"
MAX_LIPSYNC_VIDEO_BYTES = 64 * 1024 * 1024
# A short, fixed phrase exercises the Korean tokenizer and both GPU inference
# stages without putting user content into startup logs or caches.
WARMUP_TEXT = "안녕."


class MuseTalkUnavailable(RuntimeError):
    """The optional loopback lip-sync worker could not render this request."""


class _NoRedirectHandler(request.HTTPRedirectHandler):
    """Never forward the shared Bearer token through an HTTP redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LOOPBACK_OPENER = request.build_opener(
    request.ProxyHandler({}),
    _NoRedirectHandler(),
)


class MuseTalkRender(NamedTuple):
    video: bytes
    elapsed_seconds: float


class MuseTalkClient:
    """Fixed loopback-only client for the persistent MuseTalk worker."""

    def __init__(
        self,
        token: str,
        *,
        service_url: str = DEFAULT_MUSETALK_URL,
        timeout: float = 120.0,
    ):
        if service_url.rstrip("/") != DEFAULT_MUSETALK_URL:
            raise ValueError("MuseTalk service must use http://127.0.0.1:8002")
        self.token = token
        self.service_url = DEFAULT_MUSETALK_URL
        self.timeout = timeout

    def render(self, audio: bytes) -> MuseTalkRender:
        req = request.Request(
            f"{self.service_url}/render",
            data=audio,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "audio/wav",
            },
        )
        started = time.perf_counter()
        try:
            with _LOOPBACK_OPENER.open(req, timeout=self.timeout) as response:
                content_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type != "video/mp4":
                    raise MuseTalkUnavailable(
                        "MuseTalk returned an unsupported media type"
                    )
                video = response.read(MAX_LIPSYNC_VIDEO_BYTES + 1)
        except error.HTTPError as exc:
            raise MuseTalkUnavailable(
                f"MuseTalk service returned HTTP {exc.code}"
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise MuseTalkUnavailable("MuseTalk service is unavailable") from exc
        if (
            len(video) < 12
            or len(video) > MAX_LIPSYNC_VIDEO_BYTES
            or video[4:8] != b"ftyp"
        ):
            raise MuseTalkUnavailable("MuseTalk returned an invalid video")
        return MuseTalkRender(
            video=video,
            elapsed_seconds=time.perf_counter() - started,
        )


def load_local_env() -> None:
    """Load the repository .env without overwriting an explicit environment."""
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env", override=False)


def require_bridge_token(value: str | None = None) -> str:
    token = (value if value is not None else os.getenv(TOKEN_ENV, "")).strip()
    if (
        len(token) >= 32
        and not any(character.isspace() for character in token)
        and token != TOKEN_PLACEHOLDER
    ):
        return token
    raise RuntimeError(
        "TTS_BRIDGE_TOKEN must be a non-placeholder secret of at least 32 "
        "characters with no whitespace. Set the same secret locally and in "
        "Render. PowerShell generation example (the value is assigned without "
        "being printed):\n"
        "$env:TTS_BRIDGE_TOKEN = (& python -c \"import secrets; "
        "print(secrets.token_urlsafe(48))\")"
    )


def make_bearer_guard(expected_token: str):
    """Return a FastAPI dependency that checks a Bearer token in constant time."""

    def require_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        scheme, separator, supplied_token = (authorization or "").partition(" ")
        valid = (
            bool(separator)
            and scheme.lower() == "bearer"
            and bool(supplied_token)
            and hmac.compare_digest(supplied_token, expected_token)
        )
        if not valid:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_bearer


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    # 1.0이 원래 속도이고 0.92는 약 8% 느리다.
    rate: float = Field(default=0.92, ge=0.75, le=1.15)


class SynthesisTimings(NamedTuple):
    """Non-sensitive phase durations for the most recent request thread."""

    queue_seconds: float
    pipeline_seconds: float
    model_seconds: float
    time_stretch_seconds: float
    wav_encode_seconds: float


def _safe_seconds(value: float) -> float:
    """Keep timing headers finite and non-negative even for test doubles."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) and result >= 0 else 0.0


def _timing_headers(
    request_seconds: float,
    generation_seconds: float,
    timings: SynthesisTimings | None,
) -> dict[str, str]:
    """Format numeric-only timing headers and the standard Server-Timing value."""
    request_seconds = _safe_seconds(request_seconds)
    generation_seconds = _safe_seconds(generation_seconds)
    queue_seconds = _safe_seconds(timings.queue_seconds if timings else 0.0)
    model_seconds = _safe_seconds(
        timings.model_seconds if timings else generation_seconds
    )
    stretch_seconds = _safe_seconds(
        timings.time_stretch_seconds if timings else 0.0
    )
    wav_seconds = _safe_seconds(timings.wav_encode_seconds if timings else 0.0)

    server_timing = ", ".join(
        (
            f"tts-request;dur={request_seconds * 1000:.2f}",
            f"tts-queue;dur={queue_seconds * 1000:.2f}",
            f"tts-generate;dur={model_seconds * 1000:.2f}",
            f"tts-stretch;dur={stretch_seconds * 1000:.2f}",
            f"tts-wav;dur={wav_seconds * 1000:.2f}",
        )
    )
    return {
        # Preserve the original aggregate header for existing callers.
        "X-Generation-Seconds": f"{generation_seconds:.3f}",
        "X-TTS-Request-Seconds": f"{request_seconds:.3f}",
        "X-TTS-Queue-Seconds": f"{queue_seconds:.3f}",
        "X-TTS-Generation-Seconds": f"{model_seconds:.3f}",
        "X-TTS-Time-Stretch-Seconds": f"{stretch_seconds:.3f}",
        "X-TTS-Wav-Encode-Seconds": f"{wav_seconds:.3f}",
        "Server-Timing": server_timing,
    }


class VoiceEngine:
    def __init__(self, reference: Path, generation_seed: int | None = None):
        self.reference = reference
        if generation_seed is None:
            raw_seed = os.getenv(GENERATION_SEED_ENV, str(DEFAULT_GENERATION_SEED))
            try:
                generation_seed = int(raw_seed)
            except ValueError as exc:
                raise RuntimeError(
                    f"{GENERATION_SEED_ENV} must be an integer."
                ) from exc
        self.generation_seed = generation_seed
        self.model: ChatterboxMultilingualTTS | None = None
        self.lock = threading.Lock()
        self._request_state = threading.local()
        self.loaded_seconds = 0.0
        self.model_load_seconds = 0.0
        self.conditionals_seconds = 0.0
        self.warmup_seconds = 0.0

    def _reset_generation_seed(self) -> None:
        """Make identical text reproducible instead of randomly truncating."""
        torch.manual_seed(self.generation_seed)

    def load(self) -> None:
        if not self.reference.is_file():
            raise FileNotFoundError(f"참조 음성을 찾을 수 없습니다: {self.reference}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU를 사용할 수 없습니다.")

        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"참조 음성: {self.reference}")
        print("Chatterbox Multilingual V3를 GPU에 올리는 중...")
        ready_started = time.perf_counter()
        model_started = time.perf_counter()
        model = ChatterboxMultilingualTTS.from_pretrained(
            device="cuda",
            t3_model="v3",
        )
        self.model_load_seconds = time.perf_counter() - model_started

        # This reference never changes while the process is alive. Chatterbox's
        # generate(audio_prompt_path=...) otherwise decodes, resamples and embeds
        # the same WAV on every request.
        conditionals_started = time.perf_counter()
        with torch.inference_mode():
            model.prepare_conditionals(str(self.reference), exaggeration=0.5)
        self.conditionals_seconds = time.perf_counter() - conditionals_started

        # Finish one bounded Korean inference before publishing a healthy app.
        # This moves lazy CUDA/kernel initialization out of the first real call.
        warmup_started = time.perf_counter()
        with torch.inference_mode():
            self._reset_generation_seed()
            warmup_audio = model.generate(
                WARMUP_TEXT,
                language_id="ko",
                exaggeration=0.5,
                cfg_weight=0.5,
            )
        del warmup_audio
        self.warmup_seconds = time.perf_counter() - warmup_started

        # Health is true only after conditionals and warmup both succeed.
        self.model = model
        self.loaded_seconds = time.perf_counter() - ready_started
        print(f"TTS 준비 완료 ({self.loaded_seconds:.1f}초)")

    def synthesize(self, text: str, rate: float) -> tuple[bytes, float, float]:
        if self.model is None:
            raise RuntimeError("TTS 모델이 아직 준비되지 않았습니다.")

        request_started = time.perf_counter()
        with self.lock, torch.inference_mode():
            lock_acquired = time.perf_counter()
            pipeline_started = lock_acquired

            generation_started = time.perf_counter()
            self._reset_generation_seed()
            wav = self.model.generate(
                text.strip(),
                language_id="ko",
                exaggeration=0.5,
                cfg_weight=0.5,
            )
            samples = wav.detach().float().cpu().numpy().squeeze()
            model_seconds = time.perf_counter() - generation_started

            # librosa의 time_stretch는 음높이를 유지하면서 길이만 조절한다.
            stretch_seconds = 0.0
            if abs(rate - 1.0) >= 0.005:
                stretch_started = time.perf_counter()
                samples = librosa.effects.time_stretch(samples, rate=rate)
                stretch_seconds = time.perf_counter() - stretch_started

            wav_started = time.perf_counter()
            samples = np.clip(samples, -1.0, 1.0)
            buffer = io.BytesIO()
            sf.write(
                buffer,
                samples,
                self.model.sr,
                format="WAV",
                subtype="PCM_16",
            )
            wav_seconds = time.perf_counter() - wav_started
            elapsed = time.perf_counter() - pipeline_started
            duration = len(samples) / self.model.sr
            self._request_state.timings = SynthesisTimings(
                queue_seconds=lock_acquired - request_started,
                pipeline_seconds=elapsed,
                model_seconds=model_seconds,
                time_stretch_seconds=stretch_seconds,
                wav_encode_seconds=wav_seconds,
            )
            return buffer.getvalue(), duration, elapsed

    def last_timings(self) -> SynthesisTimings | None:
        """Return timings belonging to the current request worker thread."""
        return getattr(self._request_state, "timings", None)


def create_app(
    engine: VoiceEngine,
    bridge_token: str | None = None,
    *,
    musetalk: MuseTalkClient | None = None,
) -> FastAPI:
    validated_token = require_bridge_token(bridge_token)
    require_bearer = make_bearer_guard(validated_token)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine.load()
        yield

    app = FastAPI(
        title="Memory Call Local Chatterbox TTS",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", dependencies=[Depends(require_bearer)])
    def health():
        return {
            "ok": engine.model is not None,
            "model": "chatterbox-multilingual-v3",
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "reference": engine.reference.name,
            "load_seconds": round(engine.loaded_seconds, 2),
            "model_load_seconds": round(
                getattr(engine, "model_load_seconds", engine.loaded_seconds), 2
            ),
            "conditionals_seconds": round(
                getattr(engine, "conditionals_seconds", 0.0), 2
            ),
            "warmup_seconds": round(getattr(engine, "warmup_seconds", 0.0), 2),
            "lipsync_configured": musetalk is not None,
        }

    @app.post("/synthesize", dependencies=[Depends(require_bearer)])
    def synthesize(req: SynthesisRequest):
        request_started = time.perf_counter()
        try:
            audio, duration, elapsed = engine.synthesize(req.text, req.rate)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"음성 합성 실패: {exc}") from exc
        request_seconds = time.perf_counter() - request_started
        timing_reader = getattr(engine, "last_timings", None)
        timings = timing_reader() if callable(timing_reader) else None
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store",
                "X-Audio-Duration": f"{duration:.2f}",
                "X-TTS-Model": "chatterbox-multilingual-v3",
                **_timing_headers(request_seconds, elapsed, timings),
            },
        )

    @app.post("/synthesize-video", dependencies=[Depends(require_bearer)])
    def synthesize_video(req: SynthesisRequest):
        """Synthesize once, then render MP4 or return that exact WAV as fallback."""
        tts_started = time.perf_counter()
        try:
            audio, duration, elapsed = engine.synthesize(req.text, req.rate)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"음성 합성 실패: {exc}") from exc
        tts_request_seconds = time.perf_counter() - tts_started
        timing_reader = getattr(engine, "last_timings", None)
        timings = timing_reader() if callable(timing_reader) else None
        headers = {
            "Cache-Control": "no-store",
            "X-Audio-Duration": f"{duration:.2f}",
            "X-TTS-Model": "chatterbox-multilingual-v3",
            **_timing_headers(tts_request_seconds, elapsed, timings),
        }

        if musetalk is not None:
            try:
                rendered = musetalk.render(audio)
            except Exception:  # noqa: BLE001 - lip-sync is optional
                print(
                    "MuseTalk unavailable; returning the generated WAV.",
                    flush=True,
                )
            else:
                lipsync_seconds = _safe_seconds(rendered.elapsed_seconds)
                headers["X-Lipsync-Seconds"] = f"{lipsync_seconds:.3f}"
                headers["Server-Timing"] += (
                    f", lipsync;dur={lipsync_seconds * 1000:.2f}"
                )
                return Response(
                    content=rendered.video,
                    media_type="video/mp4",
                    headers=headers,
                )

        headers["X-Lipsync-Fallback"] = "audio"
        return Response(
            content=audio,
            media_type="audio/wav",
            headers=headers,
        )

    return app


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args()

    reference = args.reference.resolve()
    token = require_bridge_token()
    musetalk_enabled = os.getenv("MUSE_TALK_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    musetalk = MuseTalkClient(token) if musetalk_enabled else None
    app = create_app(VoiceEngine(reference), token, musetalk=musetalk)
    print(f"\n  TTS 상태  http://{args.host}:{args.port}/health")
    print("  종료      Ctrl + C\n")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
