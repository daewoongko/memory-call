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
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")

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

    def test_gemini_inline_audio_result_is_parsed(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("X-goog-api-key")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response({
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": json.dumps(
                                {"text": "정훈아, 내 말 들리니?", "has_speech": True},
                                ensure_ascii=False,
                            )
                        }]
                    }
                }]
            })

        with (
            patch.object(stt, "_as_wav", return_value=b"RIFF-wav"),
            patch.object(stt.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = stt.transcribe(b"webm", "audio/webm")

        self.assertEqual(result, {
            "text": "정훈아, 내 말 들리니?",
            "has_speech": True,
        })
        self.assertIn(":generateContent", captured["url"])
        self.assertEqual(captured["key"], stt.llm.API_KEY)
        inline = captured["body"]["contents"][0]["parts"][1]["inline_data"]
        self.assertEqual(inline["mime_type"], "audio/wav")
        self.assertTrue(inline["data"])

    def test_no_speech_returns_empty_text(self):
        response = {
            "candidates": [{
                "content": {"parts": [{"text": '{"text":"잡음","has_speech":false}'}]}
            }]
        }
        with (
            patch.object(stt, "_as_wav", return_value=b"RIFF-wav"),
            patch.object(stt.urllib.request, "urlopen", return_value=_Response(response)),
        ):
            self.assertEqual(
                stt.transcribe(b"webm", "audio/webm"),
                {"text": "", "has_speech": False},
            )


if __name__ == "__main__":
    unittest.main()
