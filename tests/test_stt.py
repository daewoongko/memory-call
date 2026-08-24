"""Android Chrome 서버 음성 전사 단위 테스트."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import stt  # noqa: E402


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class ServerTranscriptionTests(unittest.TestCase):
    def test_wav_is_not_reencoded(self):
        audio = b"RIFF" + b"\x00" * 64
        self.assertEqual(stt._as_wav(audio, "audio/wav"), audio)

    def test_empty_audio_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "빈 음성"):
            stt._as_wav(b"", "audio/webm")

    def test_elevenlabs_batch_audio_result_is_parsed(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("Xi-api-key")
            captured["content_type"] = request.get_header("Content-type")
            captured["body"] = request.data
            captured["timeout"] = timeout
            return _Response({"text": "정훈아, 내 말 들리니?", "words": []})

        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "server-stt-key"}),
            patch.object(stt, "_as_wav", return_value=b"RIFF-wav"),
            patch.object(stt.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = stt.transcribe(b"webm", "audio/webm")

        self.assertEqual(result, {
            "text": "정훈아, 내 말 들리니?",
            "has_speech": True,
        })
        self.assertEqual(captured["url"], stt.STT_URL)
        self.assertEqual(captured["key"], "server-stt-key")
        self.assertIn("multipart/form-data; boundary=", captured["content_type"])
        self.assertIn(b'name="model_id"', captured["body"])
        self.assertIn(b"scribe_v2", captured["body"])
        self.assertIn(b'name="language_code"', captured["body"])
        self.assertIn(b"RIFF-wav", captured["body"])

    def test_no_speech_returns_empty_text(self):
        response = {"text": "", "words": []}
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "server-stt-key"}),
            patch.object(stt, "_as_wav", return_value=b"RIFF-wav"),
            patch.object(stt.urllib.request, "urlopen", return_value=_Response(response)),
        ):
            self.assertEqual(
                stt.transcribe(b"webm", "audio/webm"),
                {"text": "", "has_speech": False},
            )

    def test_missing_elevenlabs_key_fails_closed(self):
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}),
            patch.object(stt, "_as_wav", return_value=b"RIFF-wav"),
        ):
            with self.assertRaises(stt.TranscriptionUnavailable):
                stt.transcribe(b"webm", "audio/webm")


if __name__ == "__main__":
    unittest.main()
