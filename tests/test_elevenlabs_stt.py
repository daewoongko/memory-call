"""ElevenLabs realtime Scribe token tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import elevenlabs_stt  # noqa: E402


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class ElevenLabsRealtimeTokenTests(unittest.TestCase):
    def test_permanent_key_stays_in_server_request(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("Xi-api-key")
            captured["timeout"] = timeout
            return _Response({"token": "sutkn_test"})

        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "secret-server-key"}),
            patch.object(elevenlabs_stt.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = elevenlabs_stt.create_realtime_token()

        self.assertEqual(captured["key"], "secret-server-key")
        self.assertTrue(captured["url"].endswith("/realtime_scribe"))
        self.assertEqual(result["token"], "sutkn_test")
        self.assertEqual(result["model_id"], "scribe_v2_realtime")
        self.assertNotIn("secret-server-key", result.values())

    def test_missing_key_is_explicit(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            with self.assertRaises(elevenlabs_stt.ElevenLabsSTTNotConfigured):
                elevenlabs_stt.create_realtime_token()

    def test_empty_token_is_rejected(self):
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "server-key"}),
            patch.object(
                elevenlabs_stt.urllib.request,
                "urlopen",
                return_value=_Response({"token": ""}),
            ),
        ):
            with self.assertRaises(elevenlabs_stt.ElevenLabsSTTUnavailable):
                elevenlabs_stt.create_realtime_token()


if __name__ == "__main__":
    unittest.main()
