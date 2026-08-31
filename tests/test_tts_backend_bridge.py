"""Backend routing, authentication, and public TTS rate-limit tests."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import elevenlabs_tts  # noqa: E402
import tts_proxy  # noqa: E402

VALID_TOKEN = "test-secret-" + "x" * 40
API_TOKEN = "api-secret-" + "y" * 40


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


def _proxy_result(body: bytes = b"\x00\x00\x00\x18ftypisom-video") -> tts_proxy.ProxyCallResult:
    return tts_proxy.ProxyCallResult(
        body=body,
        upstream_wait_seconds=0.01,
        proxy_read_seconds=0.02,
        proxy_total_seconds=0.03,
        media_type="video/mp4",
    )


def _speech_result(body: bytes = b"RIFF-wave") -> elevenlabs_tts.SpeechResult:
    return elevenlabs_tts.SpeechResult(
        body=body,
        audio_duration_seconds=1.5,
        generation_seconds=0.4,
    )


class TTSRateDefaultsTests(unittest.TestCase):
    def test_public_tts_requests_default_to_natural_slowdown(self):
        self.assertEqual(api.TTSRequest(text="안녕하세요").rate, 0.93)
        self.assertEqual(
            api.VoicePreviewRequest(text="안녕하세요").rate,
            0.93,
        )


class TTSProxyBridgeTests(unittest.TestCase):
    def setUp(self):
        self.config = (
            patch.object(tts_proxy, "BRIDGE_TOKEN", VALID_TOKEN),
            patch.object(tts_proxy, "BRIDGE_TTL_SECONDS", 30.0),
            patch.object(
                tts_proxy,
                "BRIDGE_ALLOWED_HOSTS",
                ("trycloudflare.com",),
            ),
            patch.object(tts_proxy, "SERVICE_URL", "http://127.0.0.1:8002"),
        )
        for item in self.config:
            item.start()
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None

    def tearDown(self):
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None
        for item in reversed(self.config):
            item.stop()

    def test_bearer_token_is_required_and_compared(self):
        for header in (None, "", f"Basic {VALID_TOKEN}", "Bearer wrong"):
            with self.subTest(header=header):
                with self.assertRaises(tts_proxy.TTSBridgeUnauthorized):
                    tts_proxy.verify_bridge_bearer(header)

        tts_proxy.verify_bridge_bearer(f"Bearer {VALID_TOKEN}")
        tts_proxy.verify_bridge_bearer(f"bearer {VALID_TOKEN}")

    def test_registration_is_disabled_without_configured_token(self):
        for token in ("", "short", "replace-with-a-long-random-token"):
            with self.subTest(token=token), patch.object(
                tts_proxy, "BRIDGE_TOKEN", token
            ):
                with self.assertRaises(tts_proxy.TTSBridgeNotConfigured):
                    tts_proxy.verify_bridge_bearer("Bearer anything")

    def test_registration_requires_https_allowed_origin(self):
        invalid_urls = (
            "http://voice.trycloudflare.com",
            "https://trycloudflare.com.evil.example",
            "https://voice.trycloudflare.com:8443",
            "https://user@voice.trycloudflare.com",
            "https://voice.trycloudflare.com/prefix",
            "https://voice.trycloudflare.com?query=yes",
        )
        for service_url in invalid_urls:
            with self.subTest(service_url=service_url):
                with self.assertRaises(tts_proxy.TTSBridgeError):
                    tts_proxy.register_bridge(service_url, now=100.0)

        status = tts_proxy.register_bridge(
            "https://Voice-123.TryCloudflare.Com/", now=100.0
        )
        self.assertTrue(status["active"])
        self.assertEqual(
            status["service_url"],
            "https://voice-123.trycloudflare.com",
        )

    def test_heartbeat_refreshes_ttl_then_expires_to_fixed_service(self):
        tts_proxy.register_bridge(
            "https://voice.trycloudflare.com", now=100.0
        )
        self.assertEqual(
            tts_proxy.bridge_status(now=110.0)["expires_in_seconds"],
            20.0,
        )

        refreshed = tts_proxy.register_bridge(
            "https://voice.trycloudflare.com", now=115.0
        )
        self.assertEqual(refreshed["expires_in_seconds"], 30.0)
        self.assertTrue(tts_proxy.bridge_status(now=144.0)["active"])

        expired = tts_proxy.bridge_status(now=146.0)
        self.assertFalse(expired["active"])
        self.assertEqual(expired["source"], "fixed_service")
        self.assertEqual(expired["service_url"], "http://127.0.0.1:8002")

    def test_concurrent_heartbeats_leave_a_valid_registration(self):
        urls = (
            "https://one.trycloudflare.com",
            "https://two.trycloudflare.com",
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(
                executor.map(
                    lambda index: tts_proxy.register_bridge(
                        urls[index % 2], now=100.0 + index
                    ),
                    range(40),
                )
            )

        self.assertTrue(all(status["active"] for status in statuses))
        for index, status in enumerate(statuses):
            self.assertEqual(status["service_url"], urls[index % 2])
        self.assertIn(
            tts_proxy.bridge_status(now=139.0)["service_url"],
            urls,
        )

    def test_render_uses_bridge_and_forwards_bearer(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            captured["content_type"] = req.get_header("Content-type")
            captured["data"] = req.data
            captured["timeout"] = timeout
            return _Response(
                b"\x00\x00\x00\x18ftypisom-video",
                {"Content-Type": "video/mp4", "X-Lipsync-Seconds": "0.9"},
            )

        with (
            patch.object(tts_proxy.time, "monotonic", return_value=100.0),
            patch.object(tts_proxy, "_open_no_redirect", side_effect=fake_urlopen),
        ):
            tts_proxy.register_bridge("https://voice.trycloudflare.com")
            result = tts_proxy.render_lipsync_with_metadata(b"RIFF-input-wave")

        self.assertEqual(result.body, b"\x00\x00\x00\x18ftypisom-video")
        self.assertEqual(
            captured["url"],
            "https://voice.trycloudflare.com/render",
        )
        self.assertEqual(captured["authorization"], f"Bearer {VALID_TOKEN}")
        self.assertEqual(captured["content_type"], "audio/wav")
        self.assertEqual(captured["data"], b"RIFF-input-wave")
        self.assertEqual(captured["timeout"], 180)
        self.assertEqual(result.lipsync_seconds, 0.9)

    def test_render_rejects_a_non_mp4_response(self):
        with patch.object(
            tts_proxy,
            "_open_no_redirect",
            return_value=_Response(b"not-a-video", {"Content-Type": "text/plain"}),
        ):
            with self.assertRaises(tts_proxy.TTSUnavailable):
                tts_proxy.render_lipsync_with_metadata(b"RIFF-wave")

    def test_render_exposes_only_sanitized_timing_headers(self):
        request_id = "a" * 32
        captured = {}

        def fake_urlopen(req, timeout):
            captured["request_id"] = req.get_header("X-request-id")
            return _Response(
                b"\x00\x00\x00\x18ftypisom-video",
                {
                    "Content-Type": "video/mp4",
                    "X-Lipsync-Seconds": "1.25",
                    "X-Request-ID": request_id,
                    "Server-Timing": f'secret;desc="{VALID_TOKEN}"',
                    "X-Internal-Path": r"C:\\private\\reference.wav",
                    "Authorization": f"Bearer {VALID_TOKEN}",
                },
            )

        with patch.object(tts_proxy, "_open_no_redirect", side_effect=fake_urlopen):
            result = tts_proxy.render_lipsync_with_metadata(
                b"RIFF-wave", request_id=request_id
            )

        headers = result.public_headers(request_id=request_id)
        self.assertEqual(captured["request_id"], request_id)
        self.assertEqual(
            set(headers), {"X-Request-ID", "X-Lipsync-Seconds", "Server-Timing"}
        )
        self.assertEqual(headers["X-Request-ID"], request_id)
        self.assertEqual(headers["X-Lipsync-Seconds"], "1.250")
        self.assertNotIn(VALID_TOKEN, str(headers))
        self.assertNotIn("private", str(headers))

    def test_invalid_local_metadata_is_dropped(self):
        with patch.object(
            tts_proxy,
            "_open_no_redirect",
            return_value=_Response(
                b"\x00\x00\x00\x18ftypisom-video",
                {
                    "Content-Type": "video/mp4",
                    "X-Lipsync-Seconds": "not-a-number",
                    "X-Request-ID": "not-a-safe-request-id",
                },
            ),
        ):
            result = tts_proxy.render_lipsync_with_metadata(b"RIFF-wave")

        headers = result.public_headers()
        self.assertIsNone(result.lipsync_seconds)
        self.assertIsNone(result.local_request_id)
        self.assertEqual(set(headers), {"Server-Timing"})

    def test_bridge_http_redirects_are_not_followed(self):
        handler = tts_proxy._NoRedirectHandler()
        redirected = handler.redirect_request(
            tts_proxy.request.Request("https://voice.trycloudflare.com/render"),
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )
        self.assertIsNone(redirected)

    def test_public_health_status_does_not_expose_tunnel_origin(self):
        tts_proxy.register_bridge("https://voice.trycloudflare.com", now=100.0)
        with (
            patch.object(tts_proxy.time, "monotonic", return_value=110.0),
            patch.object(
                tts_proxy,
                "_request_metadata",
                return_value=(b'{"ok":true}', {}, 0.0, 0.0, 0.0),
            ),
        ):
            result = tts_proxy.health()

        self.assertTrue(result["proxy"]["active"])
        self.assertEqual(result["proxy"]["source"], "dynamic_bridge")
        self.assertNotIn("service_url", result["proxy"])

    def test_expired_registration_uses_fixed_service_with_bearer(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            return _Response(
                b"\x00\x00\x00\x18ftypisom-video", {"Content-Type": "video/mp4"}
            )

        tts_proxy.register_bridge("https://voice.trycloudflare.com", now=10.0)
        with (
            patch.object(tts_proxy.time, "monotonic", return_value=41.0),
            patch.object(tts_proxy, "_open_no_redirect", side_effect=fake_urlopen),
        ):
            result = tts_proxy.render_lipsync_with_metadata(b"RIFF-fallback")

        self.assertEqual(result.body, b"\x00\x00\x00\x18ftypisom-video")
        self.assertEqual(captured["url"], "http://127.0.0.1:8002/render")
        self.assertEqual(captured["authorization"], f"Bearer {VALID_TOKEN}")


class TTSApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.voice_patch = patch.object(
            api.voice_mod, "active_voice_id", return_value="voice-test"
        )
        self.voice_patch.start()
        with api._tts_rate_lock:
            api._tts_rate_events.clear()
            api._tts_global_rate_events.clear()
            api._tts_rate_last_cleanup = 0.0
        api._tts_capacity = threading.BoundedSemaphore(api.TTS_MAX_CONCURRENT)
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None

    def tearDown(self):
        self.voice_patch.stop()
        with api._tts_rate_lock:
            api._tts_rate_events.clear()
            api._tts_global_rate_events.clear()
            api._tts_rate_last_cleanup = 0.0
        api._tts_capacity = threading.BoundedSemaphore(api.TTS_MAX_CONCURRENT)
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None

    def test_health_keeps_audio_available_when_optional_lipsync_is_down(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "ELEVENLABS_API_KEY": "sk_test",
                },
                clear=False,
            ),
            patch.object(
                tts_proxy,
                "health",
                side_effect=tts_proxy.TTSUnavailable("MuseTalk offline"),
            ),
            patch.object(
                api.elevenlabs_tts,
                "resolve_voice_id_by_name",
                return_value="voice-test",
            ),
        ):
            response = self.client.get("/api/tts/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["tts"]["configured"])
        self.assertTrue(body["tts"]["default_voice_ready"])
        self.assertEqual(body["tts"]["engine"], "elevenlabs")
        self.assertFalse(body["lipsync"]["available"])

    def test_register_endpoint_authenticates_and_returns_state(self):
        payload = {"service_url": "https://voice.trycloudflare.com"}
        with (
            patch.object(tts_proxy, "BRIDGE_TOKEN", API_TOKEN),
            patch.object(tts_proxy, "BRIDGE_TTL_SECONDS", 30.0),
        ):
            missing = self.client.post("/api/tts/bridge/register", json=payload)
            wrong = self.client.post(
                "/api/tts/bridge/register",
                json=payload,
                headers={"Authorization": "Bearer wrong"},
            )
            accepted = self.client.post(
                "/api/tts/bridge/register",
                json=payload,
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        body = accepted.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["active"])
        self.assertEqual(body["source"], "dynamic_bridge")
        self.assertEqual(body["ttl_seconds"], 30.0)

    def test_register_endpoint_rejects_unconfigured_or_untrusted_bridge(self):
        payload = {"service_url": "https://voice.trycloudflare.com"}
        with patch.object(tts_proxy, "BRIDGE_TOKEN", ""):
            unconfigured = self.client.post(
                "/api/tts/bridge/register",
                json=payload,
                headers={"Authorization": "Bearer anything"},
            )

        with patch.object(tts_proxy, "BRIDGE_TOKEN", API_TOKEN):
            untrusted = self.client.post(
                "/api/tts/bridge/register",
                json={"service_url": "https://attacker.example"},
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )

        self.assertEqual(unconfigured.status_code, 503)
        self.assertEqual(untrusted.status_code, 400)

    def test_public_tts_is_rate_limited_by_request_client(self):
        with (
            patch.object(api, "TTS_RATE_LIMIT_PER_MINUTE", 2),
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=_speech_result(),
            ),
        ):
            first = self.client.post("/api/tts", json={"text": "one", "persona_id": "persona_jeonghun"})
            second = self.client.post("/api/tts", json={"text": "two", "persona_id": "persona_jeonghun"})
            blocked = self.client.post("/api/tts", json={"text": "three", "persona_id": "persona_jeonghun"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)

    def test_public_tts_keeps_500_character_validation_limit(self):
        with patch.object(elevenlabs_tts, "synthesize_with_metadata") as synthesize:
            response = self.client.post("/api/tts", json={"text": "x" * 501})

        self.assertEqual(response.status_code, 422)
        synthesize.assert_not_called()

    def test_public_video_route_renders_lipsync_after_elevenlabs_audio(self):
        video = _proxy_result(body=b"\x00\x00\x00\x18ftypisom-video")
        with (
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=_speech_result(),
            ) as synthesize,
            patch.object(
                tts_proxy,
                "render_lipsync_with_metadata",
                return_value=video,
            ) as render,
            patch.object(api, "_musetalk_enabled", return_value=True),
        ):
            response = self.client.post("/api/tts/video", json={"text": "video", "persona_id": "persona_jeonghun"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response.content, video.body)
        synthesize.assert_called_once()
        render.assert_called_once()

    def test_public_video_route_falls_back_to_audio_when_musetalk_unavailable(self):
        with (
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=_speech_result(body=b"RIFF-fallback-wave"),
            ),
            patch.object(
                tts_proxy,
                "render_lipsync_with_metadata",
                side_effect=tts_proxy.TTSUnavailable("MuseTalk busy"),
            ),
            patch.object(api, "_musetalk_enabled", return_value=True),
        ):
            response = self.client.post("/api/tts/video", json={"text": "video", "persona_id": "persona_jeonghun"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.headers["x-lipsync-fallback"], "audio")
        self.assertEqual(response.content, b"RIFF-fallback-wave")

    def test_public_video_route_skips_musetalk_by_default(self):
        with (
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=_speech_result(body=b"RIFF-audio-only"),
            ),
            patch.object(api, "_musetalk_enabled", return_value=False),
            patch.object(
                tts_proxy,
                "render_lipsync_with_metadata",
            ) as render,
        ):
            response = self.client.post(
                "/api/tts/video",
                json={"text": "video", "persona_id": "persona_jeonghun"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.headers["x-lipsync-disabled"], "musetalk")
        self.assertEqual(response.content, b"RIFF-audio-only")
        render.assert_not_called()

    def test_public_tts_propagates_only_safe_latency_metadata(self):
        request_id = "b" * 32
        result = elevenlabs_tts.SpeechResult(
            body=b"RIFF-timed",
            audio_duration_seconds=2.75,
            generation_seconds=1.5,
            local_request_id="c" * 32,
        )
        fake_uuid = type("FakeUuid", (), {"hex": request_id})()
        with (
            patch.object(api.uuid, "uuid4", return_value=fake_uuid),
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=result,
            ) as synthesize,
        ):
            response = self.client.post("/api/tts", json={"text": "timed", "persona_id": "persona_jeonghun"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"RIFF-timed")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-tts-engine"], "elevenlabs")
        self.assertEqual(response.headers["x-request-id"], request_id)
        self.assertEqual(response.headers["x-audio-duration"], "2.750")
        self.assertEqual(response.headers["x-generation-seconds"], "1.500")
        self.assertNotIn("authorization", response.headers)
        synthesize.assert_called_once_with(
            "timed", 0.93, request_id=request_id, voice_id="voice-test"
        )

    def test_public_tts_uses_approved_persona_voice_when_present(self):
        request_id = "d" * 32
        fake_uuid = type("FakeUuid", (), {"hex": request_id})()
        with (
            patch.object(api.uuid, "uuid4", return_value=fake_uuid),
            patch.object(api.voice_mod, "active_voice_id", return_value="voice-family") as active,
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                return_value=_speech_result(),
            ) as synthesize,
        ):
            response = self.client.post(
                "/api/tts",
                json={"text": "가족 목소리", "persona_id": "persona_jeonghun"},
            )

        self.assertEqual(response.status_code, 200)
        active.assert_called_once_with("persona_jeonghun")
        synthesize.assert_called_once_with(
            "가족 목소리", 0.93, request_id=request_id, voice_id="voice-family",
        )

    def test_global_rate_limit_cannot_be_bypassed_by_changing_client_ip(self):
        def fake_request(host):
            return type(
                "FakeRequest",
                (),
                {"client": type("FakeClient", (), {"host": host})()},
            )()

        with (
            patch.object(api, "TTS_RATE_LIMIT_PER_MINUTE", 100),
            patch.object(api, "TTS_GLOBAL_RATE_LIMIT_PER_MINUTE", 2),
        ):
            api._enforce_tts_rate_limit(fake_request("198.51.100.1"), now=1.0)
            api._enforce_tts_rate_limit(fake_request("198.51.100.2"), now=2.0)
            with self.assertRaises(HTTPException) as raised:
                api._enforce_tts_rate_limit(fake_request("198.51.100.3"), now=3.0)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("Global", raised.exception.detail)

    def test_busy_synthesizer_rejects_without_queueing_gpu_work(self):
        busy = type("BusyCapacity", (), {"acquire": lambda self, blocking: False})()
        with (
            patch.object(api, "_tts_capacity", busy),
            patch.object(elevenlabs_tts, "synthesize_with_metadata") as synthesize,
        ):
            response = self.client.post("/api/tts", json={"text": "busy"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "3")
        synthesize.assert_not_called()

    def test_capacity_is_released_when_remote_synthesis_fails(self):
        class Capacity:
            released = 0

            def acquire(self, blocking):
                return True

            def release(self):
                self.released += 1

        capacity = Capacity()
        with (
            patch.object(api, "_tts_capacity", capacity),
            patch.object(
                elevenlabs_tts,
                "synthesize_with_metadata",
                side_effect=elevenlabs_tts.ElevenLabsUnavailable("offline"),
            ),
        ):
            response = self.client.post("/api/tts", json={"text": "failure", "persona_id": "persona_jeonghun"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(capacity.released, 1)


if __name__ == "__main__":
    unittest.main()
