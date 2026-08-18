from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import anam  # noqa: E402
import api  # noqa: E402
import elevenlabs_tts  # noqa: E402


class _Response:
    def __init__(self, body: bytes):
        self.body = body
        self.offset = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            self.offset = len(self.body)
            return self.body
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class AnamConfigTests(unittest.TestCase):
    def test_configuration_requires_only_provider_key(self):
        with patch.dict("os.environ", {"ANAM_API_KEY": "secret"}, clear=True):
            self.assertTrue(anam.configured())

    def test_session_request_keeps_permanent_key_on_server(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["authorization"] = req.get_header("Authorization")
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response(b'{"sessionToken":"temporary-token"}')

        with (
            patch.dict(
                "os.environ",
                {
                    "ANAM_API_KEY": "permanent-secret",
                },
                clear=True,
            ),
            patch.object(anam.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = anam.create_session_token(
                avatar_id="avatar-family", persona_name="정훈"
            )

        self.assertEqual(captured["authorization"], "Bearer permanent-secret")
        self.assertTrue(
            captured["payload"]["personaConfig"]["enableAudioPassthrough"]
        )
        self.assertEqual(result["session_token"], "temporary-token")
        self.assertNotIn("permanent-secret", json.dumps(result))

    def test_custom_avatar_upload_returns_provider_id(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["authorization"] = req.get_header("Authorization")
            captured["content_type"] = req.get_header("Content-type")
            captured["body"] = req.data
            return _Response(b'{"id":"avatar-created"}')

        with (
            patch.dict("os.environ", {"ANAM_API_KEY": "permanent-secret"}, clear=True),
            patch.object(anam.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = anam.create_avatar(
                display_name="정훈", image=b"jpeg-bytes", filename="avatar.jpg"
            )

        self.assertEqual(result["avatar_id"], "avatar-created")
        self.assertEqual(captured["authorization"], "Bearer permanent-secret")
        self.assertIn("multipart/form-data", captured["content_type"])
        self.assertIn(b'filename="avatar.jpg"', captured["body"])


class AnamApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.call_id = "call_12345678"
        api.SESSIONS[self.call_id] = SimpleNamespace(
            persona_id="persona_jeonghun",
            ctx={"persona": {"display_name": "정훈"}},
        )
        with api._tts_rate_lock:
            api._tts_rate_events.clear()
            api._tts_global_rate_events.clear()
            api._tts_rate_last_cleanup = 0.0
        api._tts_capacity = threading.BoundedSemaphore(api.TTS_MAX_CONCURRENT)

    def tearDown(self):
        api.SESSIONS.pop(self.call_id, None)

    def test_session_token_requires_matching_active_call(self):
        with (
            patch.object(
                api.avatar_mod,
                "active_avatar",
                return_value={"avatar_id": "avatar-family", "avatar_model": "cara-4"},
            ),
            patch.object(
                api.anam_mod,
                "create_session_token",
                return_value={
                    "session_token": "short-lived",
                    "avatar_id": "avatar-family",
                    "avatar_model": "cara-4",
                },
            ) as create,
        ):
            response = self.client.post(
                "/api/anam/session-token",
                json={
                    "call_id": self.call_id,
                    "persona_id": "persona_jeonghun",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_token"], "short-lived")
        self.assertNotIn("avatar_id", response.json())
        create.assert_called_once_with(
            avatar_id="avatar-family", avatar_model="cara-4", persona_name="정훈"
        )
        mismatch = self.client.post(
            "/api/anam/session-token",
            json={
                "call_id": self.call_id,
                "persona_id": "persona_miyoung",
            },
        )
        self.assertEqual(mismatch.status_code, 409)

    def test_pcm_endpoint_streams_family_voice_without_buffering(self):
        upstream = _Response(b"\x01\x02\x03\x04")
        stream = elevenlabs_tts.PCMStreamResult(
            response=upstream,
            generation_seconds=0.12,
            local_request_id="local-request",
        )
        with (
            patch.object(api.voice_mod, "active_voice_id", return_value="voice-family"),
            patch.object(
                api.elevenlabs_tts, "open_pcm_stream", return_value=stream
            ) as open_stream,
        ):
            response = self.client.post(
                "/api/tts/pcm-stream",
                json={
                    "text": "안심하세요.",
                    "persona_id": "persona_jeonghun",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\x01\x02\x03\x04")
        self.assertEqual(response.headers["x-audio-sample-rate"], "16000")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(upstream.closed)
        open_stream.assert_called_once_with(
            "안심하세요.", 0.92,
            request_id=ANY,
            voice_id="voice-family",
        )


if __name__ == "__main__":
    unittest.main()
