"""S24 등 Android Chrome을 위한 서버 음성 전사 폴백.

브라우저 Web Speech API가 결과 없이 종료되는 기기에서는 MediaRecorder 음성을
짧게 받아 WAV로 정규화한 뒤 Gemini에 전사를 요청한다. 원본 음성은 저장하지
않으며 요청 처리 후 메모리에서 버린다.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid

import imageio_ffmpeg

MAX_AUDIO_BYTES = 5 * 1024 * 1024
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2")
STT_TIMEOUT_SECONDS = max(5.0, float(os.getenv("STT_TIMEOUT_SECONDS", "25")))


class TranscriptionUnavailable(RuntimeError):
    """전사 서비스 또는 오디오 변환을 사용할 수 없음."""


def _as_wav(audio: bytes, mime_type: str) -> bytes:
    if not audio:
        raise ValueError("빈 음성입니다")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("음성이 너무 깁니다")
    if mime_type.split(";", 1)[0].strip().lower() in {"audio/wav", "audio/x-wav"}:
        return audio

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        "pipe:1",
    ]
    completed = subprocess.run(
        command,
        input=audio,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or len(completed.stdout) < 44:
        detail = completed.stderr.decode("utf-8", errors="replace")[-300:]
        raise TranscriptionUnavailable(f"음성 변환 실패: {detail}")
    return completed.stdout


def _multipart_audio(wav: bytes, language_code: str) -> tuple[str, bytes]:
    """Build the small multipart request without adding another HTTP client."""
    boundary = f"----memory-call-stt-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_text(name: str, value: str) -> None:
        chunks.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}\r\n'.encode("utf-8")
        )

    add_text("model_id", STT_MODEL)
    add_text("language_code", language_code)
    add_text("tag_audio_events", "false")
    add_text("timestamps_granularity", "none")
    chunks.append(
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="file"; filename="utterance.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'.encode("utf-8")
    )
    chunks.append(wav)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return boundary, b"".join(chunks)


def transcribe(audio: bytes, mime_type: str, *, lang: str = "ko-KR") -> dict:
    """Transcribe the short fallback recording with ElevenLabs Scribe v2."""
    wav = _as_wav(audio, mime_type)
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise TranscriptionUnavailable("ELEVENLABS_API_KEY is not configured")
    language_code = (lang or "ko").split("-", 1)[0].lower()
    boundary, body = _multipart_audio(wav, language_code)
    request = urllib.request.Request(
        STT_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "xi-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=STT_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-500:]
        raise TranscriptionUnavailable(
            f"ElevenLabs batch STT {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TranscriptionUnavailable("ElevenLabs batch STT connection failed") from exc

    text = " ".join(str(result.get("text") or "").split())[:500]
    has_speech = bool(text)
    return {"text": text if has_speech else "", "has_speech": has_speech}
