"""ElevenLabs TTS 단일 창구.

Chatterbox(로컬 GPU)를 대체한다. 음성 클론은 ElevenLabs 계정에 한 번 등록해둔
voice_id를 쓸 뿐, 이 모듈은 텍스트를 보내고 오디오를 받는 순수 API 호출만
한다. 다른 파일에서 직접 ElevenLabs를 호출하지 말 것 (backend/llm.py와 같은
원칙).

24kHz mono PCM16으로 요청하는 이유는 MuseTalk의 ``/render``가 그 형식만
받기 때문이다 (``tools/musetalk_server.py``의 ``validate_wav``). WAV
컨테이너로 감싸는 것도 이 모듈의 책임이라 호출자는 항상 완성된 WAV 바이트를
받는다.
"""

from __future__ import annotations

import io
import json
import math
import os
import time
import wave
from dataclasses import dataclass
from urllib import error, request


API_BASE = "https://api.elevenlabs.io"
SAMPLE_RATE = 24000
MAX_PCM_BYTES = 25 * 1024 * 1024  # MuseTalk의 WAV 상한과 맞춘다.

# Flash는 다국어(한국어 포함)를 지원하면서 지연이 가장 짧은 모델이다.
# 품질이 아쉬우면 eleven_multilingual_v2로 바꾸되 지연이 늘어난다.
DEFAULT_MODEL_ID = "eleven_flash_v2_5"
DEFAULT_TIMEOUT_SECONDS = 20.0
# ElevenLabs voice_settings.speed의 문서화된 범위. 프로젝트의 TTSRequest.rate
# (0.75~1.15)는 이미 이 안에 들어오지만, 방어적으로 한 번 더 clamp한다.
MIN_SPEED = 0.7
MAX_SPEED = 1.2


class ElevenLabsUnavailable(RuntimeError):
    """ElevenLabs 호출이 실패했거나 응답을 신뢰할 수 없다."""


class ElevenLabsNotConfigured(RuntimeError):
    """API 키 또는 voice_id가 설정되지 않았다."""


def _model_id() -> str:
    return os.getenv("ELEVENLABS_MODEL_ID", "").strip() or DEFAULT_MODEL_ID


def _timeout_seconds() -> float:
    try:
        value = float(os.getenv("ELEVENLABS_REQUEST_TIMEOUT_SECONDS", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _require_api_key() -> str:
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise ElevenLabsNotConfigured(
            "ELEVENLABS_API_KEY가 설정되지 않았습니다. .env에 발급받은 키를 넣으세요."
        )
    if not key.startswith("sk_"):
        raise ElevenLabsNotConfigured(
            "ELEVENLABS_API_KEY에는 API key ID가 아니라 sk_로 시작하는 "
            "실제 API 키를 넣어야 합니다. ElevenLabs에서 새 키를 발급받으세요."
        )
    return key


def _require_voice_id(voice_id: str | None = None) -> str:
    selected = (voice_id or os.getenv("ELEVENLABS_VOICE_ID", "")).strip()
    if not selected:
        raise ElevenLabsNotConfigured(
            "ELEVENLABS_VOICE_ID가 설정되지 않았습니다. "
            "tools/elevenlabs_clone_voice.py로 먼저 클론 음성을 등록하세요."
        )
    return selected


def _clamp_speed(rate: float) -> float:
    return max(MIN_SPEED, min(MAX_SPEED, rate))


def _wrap_pcm16_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def _safe_seconds(value: float) -> float:
    return value if math.isfinite(value) and value >= 0 else 0.0


@dataclass(frozen=True)
class SpeechResult:
    """WAV 오디오와 지연 메타데이터. tts_proxy.ProxyCallResult와 같은 결의 계약."""

    body: bytes  # mono PCM16 24kHz WAV
    audio_duration_seconds: float
    generation_seconds: float
    local_request_id: str | None = None

    def public_headers(self, *, request_id: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        effective_request_id = request_id or self.local_request_id
        if effective_request_id is not None:
            headers["X-Request-ID"] = effective_request_id
        headers["X-Audio-Duration"] = f"{self.audio_duration_seconds:.3f}"
        headers["X-Generation-Seconds"] = f"{self.generation_seconds:.3f}"
        headers["X-TTS-Model"] = _model_id()
        headers["Server-Timing"] = (
            f"tts_total;dur={self.generation_seconds * 1000:.1f}"
        )
        return headers


def synthesize_with_metadata(
    text: str,
    rate: float,
    *,
    request_id: str | None = None,
    voice_id: str | None = None,
) -> SpeechResult:
    """ElevenLabs로 24kHz mono PCM16 WAV를 합성한다."""
    api_key = _require_api_key()
    voice_id = _require_voice_id(voice_id)

    payload = json.dumps(
        {
            "text": text,
            "model_id": _model_id(),
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "speed": _clamp_speed(rate),
            },
        }
    ).encode("utf-8")
    url = f"{API_BASE}/v1/text-to-speech/{voice_id}?output_format=pcm_24000"
    req = request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        },
    )

    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=_timeout_seconds()) as response:
            pcm = response.read(MAX_PCM_BYTES + 1)
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("detail", {}).get("message") or str(detail)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            message = None
        raise ElevenLabsUnavailable(
            message or f"ElevenLabs API error ({exc.code})"
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise ElevenLabsUnavailable(f"ElevenLabs에 연결할 수 없습니다: {exc}") from exc

    generation_seconds = _safe_seconds(time.perf_counter() - started)

    if len(pcm) > MAX_PCM_BYTES:
        raise ElevenLabsUnavailable("ElevenLabs 응답이 너무 큽니다")
    if len(pcm) < 2 or len(pcm) % 2 != 0:
        raise ElevenLabsUnavailable("ElevenLabs가 유효하지 않은 오디오를 반환했습니다")

    duration_seconds = (len(pcm) // 2) / SAMPLE_RATE
    wav_bytes = _wrap_pcm16_wav(pcm, sample_rate=SAMPLE_RATE)

    return SpeechResult(
        body=wav_bytes,
        audio_duration_seconds=duration_seconds,
        generation_seconds=generation_seconds,
        local_request_id=request_id,
    )
