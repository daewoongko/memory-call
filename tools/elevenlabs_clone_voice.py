"""ElevenLabs에 참조 음성을 등록해 클론 voice_id를 발급받는 1회성 스크립트.

data/voice/reference.wav를 Instant Voice Cloning API에 올리고 돌려받은
voice_id를 출력한다. 그 값을 .env의 ELEVENLABS_VOICE_ID에 붙여넣으면
backend/elevenlabs_tts.py가 그 목소리로 합성한다.

사용:
    python tools/elevenlabs_clone_voice.py --name "할아버지 목소리"
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib import error, request

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience for direct runs
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "data" / "voice" / "reference.wav"
API_URL = "https://api.elevenlabs.io/v1/voices/add"


def load_local_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env", override=False)


def _build_multipart(
    fields: dict[str, str], file_field: str, file_path: Path
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        )
        parts.append(f"{value}\r\n".encode())

    content_type = mimetypes.guess_type(file_path.name)[0] or "audio/wav"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def clone_voice(reference: Path, name: str, api_key: str) -> dict:
    if not reference.is_file():
        raise FileNotFoundError(f"참조 음성을 찾을 수 없습니다: {reference}")
    body, content_type = _build_multipart({"name": name}, "files", reference)
    req = request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": content_type},
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"ElevenLabs voice 등록 실패 ({exc.code}): {detail}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--name", default="Memory Call Family Voice")
    return parser.parse_args()


def main() -> None:
    load_local_env()
    args = parse_args()
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY가 .env에 없습니다. 먼저 설정하세요.")

    result = clone_voice(args.reference.resolve(), args.name, api_key)
    voice_id = result.get("voice_id")
    if not voice_id:
        raise SystemExit(f"voice_id를 받지 못했습니다: {result}")

    print(f"등록 완료: voice_id = {voice_id}")
    print("이 값을 .env의 ELEVENLABS_VOICE_ID에 넣으세요:")
    print(f"ELEVENLABS_VOICE_ID={voice_id}")


if __name__ == "__main__":
    main()
