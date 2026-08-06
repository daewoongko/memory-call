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
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

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


class VoiceEngine:
    def __init__(self, reference: Path):
        self.reference = reference
        self.model: ChatterboxMultilingualTTS | None = None
        self.lock = threading.Lock()
        self.loaded_seconds = 0.0

    def load(self) -> None:
        if not self.reference.is_file():
            raise FileNotFoundError(f"참조 음성을 찾을 수 없습니다: {self.reference}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU를 사용할 수 없습니다.")

        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"참조 음성: {self.reference}")
        print("Chatterbox Multilingual V3를 GPU에 올리는 중...")
        started = time.perf_counter()
        self.model = ChatterboxMultilingualTTS.from_pretrained(
            device="cuda",
            t3_model="v3",
        )
        self.loaded_seconds = time.perf_counter() - started
        print(f"TTS 준비 완료 ({self.loaded_seconds:.1f}초)")

    def synthesize(self, text: str, rate: float) -> tuple[bytes, float, float]:
        if self.model is None:
            raise RuntimeError("TTS 모델이 아직 준비되지 않았습니다.")

        with self.lock, torch.inference_mode():
            started = time.perf_counter()
            wav = self.model.generate(
                text.strip(),
                language_id="ko",
                audio_prompt_path=str(self.reference),
                exaggeration=0.5,
                cfg_weight=0.5,
            )
            samples = wav.detach().float().cpu().numpy().squeeze()

            # librosa의 time_stretch는 음높이를 유지하면서 길이만 조절한다.
            if abs(rate - 1.0) >= 0.005:
                samples = librosa.effects.time_stretch(samples, rate=rate)

            samples = np.clip(samples, -1.0, 1.0)
            buffer = io.BytesIO()
            sf.write(
                buffer,
                samples,
                self.model.sr,
                format="WAV",
                subtype="PCM_16",
            )
            elapsed = time.perf_counter() - started
            duration = len(samples) / self.model.sr
            return buffer.getvalue(), duration, elapsed


def create_app(engine: VoiceEngine, bridge_token: str | None = None) -> FastAPI:
    require_bearer = make_bearer_guard(require_bridge_token(bridge_token))

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
        }

    @app.post("/synthesize", dependencies=[Depends(require_bearer)])
    def synthesize(req: SynthesisRequest):
        try:
            audio, duration, elapsed = engine.synthesize(req.text, req.rate)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"음성 합성 실패: {exc}") from exc
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store",
                "X-Audio-Duration": f"{duration:.2f}",
                "X-Generation-Seconds": f"{elapsed:.2f}",
                "X-TTS-Model": "chatterbox-multilingual-v3",
            },
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
    app = create_app(VoiceEngine(reference))
    print(f"\n  TTS 상태  http://{args.host}:{args.port}/health")
    print("  종료      Ctrl + C\n")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
