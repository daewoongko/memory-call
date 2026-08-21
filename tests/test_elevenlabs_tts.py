"""backend/elevenlabs_tts.py 단위 테스트."""

from __future__ import annotations

import json
import sys
import unittest
import wave
from io import BytesIO
from pathlib import Path
from urllib import error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import elevenlabs_tts  # noqa: E402


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args) -> bytes:
        return self.body


def _pcm(seconds: float) -> bytes:
    sample_count = int(elevenlabs_tts.SAMPLE_RATE * seconds)
    return b"\x00\x01" * sample_count  # 16-bit little-endian samples


class ElevenLabsConfigTests(unittest.TestCase):
    def test_missing_api_key_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(elevenlabs_tts.ElevenLabsNotConfigured):
                elevenlabs_tts.synthesize_with_metadata("안녕하세요", 1.0)

    def test_missing_voice_id_fails_closed(self):
        with patch.dict(
            "os.environ", {"ELEVENLABS_API_KEY": "sk_key-value"}, clear=True
        ):
            with self.assertRaises(elevenlabs_tts.ElevenLabsNotConfigured):
                elevenlabs_tts.synthesize_with_metadata("안녕하세요", 1.0)

    def test_api_key_id_is_rejected_before_remote_call(self):
        with patch.dict(
            "os.environ",
            {
                "ELEVENLABS_API_KEY": "00fdd4-key-id",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(
                elevenlabs_tts.ElevenLabsNotConfigured, "API key ID",
            ):
                elevenlabs_tts.synthesize_with_metadata("안녕하세요", 1.0, voice_id="voice-123")


class ElevenLabsSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            "os.environ",
            {
                "ELEVENLABS_API_KEY": "sk_test-key",
            },
            clear=True,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_wraps_pcm_into_a_valid_mono_24k_wav(self):
        pcm = _pcm(1.0)
        with patch.object(
            elevenlabs_tts.request, "urlopen", return_value=_Response(pcm)
        ):
            result = elevenlabs_tts.synthesize_with_metadata("안녕하세요", 1.0, voice_id="voice-123")

        with wave.open(BytesIO(result.body), "rb") as reader:
            self.assertEqual(reader.getnchannels(), 1)
            self.assertEqual(reader.getsampwidth(), 2)
            self.assertEqual(reader.getframerate(), elevenlabs_tts.SAMPLE_RATE)
            self.assertEqual(reader.readframes(reader.getnframes()), pcm)
        self.assertAlmostEqual(result.audio_duration_seconds, 1.0, places=3)
        self.assertGreaterEqual(result.generation_seconds, 0.0)

    def test_sends_voice_id_model_and_clamped_speed(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["api_key"] = req.get_header("Xi-api-key")
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response(_pcm(0.1))

        with patch.object(elevenlabs_tts.request, "urlopen", side_effect=fake_urlopen):
            elevenlabs_tts.synthesize_with_metadata("빠르게 말해줘", 5.0, voice_id="voice-123")

        self.assertIn("/v1/text-to-speech/voice-123", captured["url"])
        self.assertIn("output_format=pcm_24000", captured["url"])
        self.assertEqual(captured["api_key"], "sk_test-key")
        self.assertEqual(captured["payload"]["text"], "빠르게 말해줘")
        self.assertEqual(
            captured["payload"]["model_id"], elevenlabs_tts.DEFAULT_MODEL_ID
        )
        # rate=5.0은 문서화된 speed 상한(1.2)으로 clamp되어야 한다.
        self.assertEqual(
            captured["payload"]["voice_settings"]["speed"], elevenlabs_tts.MAX_SPEED
        )

    def test_explicit_persona_voice_overrides_global_voice(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            return _Response(_pcm(0.1))

        with patch.object(elevenlabs_tts.request, "urlopen", side_effect=fake_urlopen):
            elevenlabs_tts.synthesize_with_metadata(
                "개인 목소리", 1.0, voice_id="voice-persona",
            )

        self.assertIn("/v1/text-to-speech/voice-persona", captured["url"])

    def test_http_error_raises_unavailable(self):
        def fake_urlopen(req, timeout):
            raise error.HTTPError(
                req.full_url,
                401,
                "Unauthorized",
                {},
                BytesIO(b'{"detail": {"message": "invalid api key"}}'),
            )

        with patch.object(elevenlabs_tts.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(elevenlabs_tts.ElevenLabsUnavailable) as raised:
                elevenlabs_tts.synthesize_with_metadata("hello", 1.0, voice_id="voice-123")
        self.assertIn("invalid api key", str(raised.exception))

    def test_odd_length_pcm_is_rejected(self):
        with patch.object(
            elevenlabs_tts.request, "urlopen", return_value=_Response(b"\x01\x02\x03")
        ):
            with self.assertRaises(elevenlabs_tts.ElevenLabsUnavailable):
                elevenlabs_tts.synthesize_with_metadata("hello", 1.0, voice_id="voice-123")

    def test_empty_pcm_is_rejected(self):
        with patch.object(
            elevenlabs_tts.request, "urlopen", return_value=_Response(b"")
        ):
            with self.assertRaises(elevenlabs_tts.ElevenLabsUnavailable):
                elevenlabs_tts.synthesize_with_metadata("hello", 1.0, voice_id="voice-123")

    def test_public_headers_include_request_id_and_model(self):
        with patch.object(
            elevenlabs_tts.request, "urlopen", return_value=_Response(_pcm(0.5))
        ):
            result = elevenlabs_tts.synthesize_with_metadata(
                "hello", 1.0, request_id="a" * 32, voice_id="voice-123"
            )
        headers = result.public_headers()
        self.assertEqual(headers["X-Request-ID"], "a" * 32)
        self.assertEqual(headers["X-TTS-Model"], elevenlabs_tts.DEFAULT_MODEL_ID)
        self.assertIn("X-Audio-Duration", headers)
        self.assertIn("Server-Timing", headers)


if __name__ == "__main__":
    unittest.main()
