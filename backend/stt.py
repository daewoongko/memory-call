"""S24 등 Android Chrome을 위한 서버 음성 전사 폴백.

브라우저 Web Speech API가 결과 없이 종료되는 기기에서는 MediaRecorder 음성을
짧게 받아 WAV로 정규화한 뒤 Gemini에 전사를 요청한다. 원본 음성은 저장하지
않으며 요청 처리 후 메모리에서 버린다.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request

import imageio_ffmpeg

import llm


MAX_AUDIO_BYTES = 5 * 1024 * 1024
STT_MODEL = os.getenv("STT_MODEL", llm.MODEL)
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


def _response_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "".join(str(part.get("text") or "") for part in parts).strip()


def transcribe(audio: bytes, mime_type: str, *, lang: str = "ko-KR") -> dict:
    """음성을 저장하지 않고 Gemini inline audio로 전사한다."""
    wav = _as_wav(audio, mime_type)
    model = STT_MODEL.removeprefix("models/")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    prompt = (
        "이 음성에서 사람이 직접 말한 내용을 한국어로 정확히 받아쓰세요. "
        "주변 소리나 무음뿐이면 has_speech를 false로 하세요. "
        "들리지 않은 말을 추측하거나 보충하지 마세요."
    )
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav).decode("ascii"),
                }},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "has_speech": {"type": "BOOLEAN"},
                },
                "required": ["text", "has_speech"],
            },
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": llm.API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=STT_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-500:]
        raise TranscriptionUnavailable(f"Gemini STT {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TranscriptionUnavailable("Gemini STT 연결 실패") from exc

    raw_text = _response_text(result)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = {"text": raw_text, "has_speech": bool(raw_text)}
    text = " ".join(str(parsed.get("text") or "").split())[:500]
    has_speech = bool(parsed.get("has_speech")) and bool(text)
    return {"text": text if has_speech else "", "has_speech": has_speech}
