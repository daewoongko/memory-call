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
import tts_proxy  # noqa: E402

VALID_TOKEN = "test-secret-" + "x" * 40
API_TOKEN = "api-secret-" + "y" * 40


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


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
            patch.object(tts_proxy, "SERVICE_URL", "http://127.0.0.1:8001"),
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
        self.assertEqual(expired["service_url"], "http://127.0.0.1:8001")

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

    def test_proxy_uses_bridge_and_forwards_bearer(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response(b"RIFF-wave")

        with (
            patch.object(tts_proxy.time, "monotonic", return_value=100.0),
            patch.object(tts_proxy.request, "urlopen", side_effect=fake_urlopen),
        ):
            tts_proxy.register_bridge("https://voice.trycloudflare.com")
            audio = tts_proxy.synthesize("hello", 0.92)

        self.assertEqual(audio, b"RIFF-wave")
        self.assertEqual(
            captured["url"],
            "https://voice.trycloudflare.com/synthesize",
        )
        self.assertEqual(captured["authorization"], f"Bearer {VALID_TOKEN}")
        self.assertEqual(captured["payload"], {"text": "hello", "rate": 0.92})
        self.assertEqual(captured["timeout"], 120)

    def test_public_health_status_does_not_expose_tunnel_origin(self):
        tts_proxy.register_bridge("https://voice.trycloudflare.com", now=100.0)
        with (
            patch.object(tts_proxy.time, "monotonic", return_value=110.0),
            patch.object(tts_proxy, "_call", return_value=b'{"ok":true}'),
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
            return _Response(b"fixed")

        tts_proxy.register_bridge("https://voice.trycloudflare.com", now=10.0)
        with (
            patch.object(tts_proxy.time, "monotonic", return_value=41.0),
            patch.object(tts_proxy.request, "urlopen", side_effect=fake_urlopen),
        ):
            audio = tts_proxy.synthesize("fallback", 1.0)

        self.assertEqual(audio, b"fixed")
        self.assertEqual(captured["url"], "http://127.0.0.1:8001/synthesize")
        self.assertEqual(captured["authorization"], f"Bearer {VALID_TOKEN}")


class TTSApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        with api._tts_rate_lock:
            api._tts_rate_events.clear()
            api._tts_global_rate_events.clear()
            api._tts_rate_last_cleanup = 0.0
        api._tts_capacity = threading.BoundedSemaphore(api.TTS_MAX_CONCURRENT)
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None

    def tearDown(self):
        with api._tts_rate_lock:
            api._tts_rate_events.clear()
            api._tts_global_rate_events.clear()
            api._tts_rate_last_cleanup = 0.0
        api._tts_capacity = threading.BoundedSemaphore(api.TTS_MAX_CONCURRENT)
        with tts_proxy._bridge_lock:
            tts_proxy._bridge_registration = None

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
            patch.object(tts_proxy, "synthesize", return_value=b"RIFF-wave"),
        ):
            first = self.client.post("/api/tts", json={"text": "one"})
            second = self.client.post("/api/tts", json={"text": "two"})
            blocked = self.client.post("/api/tts", json={"text": "three"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)

    def test_public_tts_keeps_500_character_validation_limit(self):
        with patch.object(tts_proxy, "synthesize") as synthesize:
            response = self.client.post("/api/tts", json={"text": "x" * 501})

        self.assertEqual(response.status_code, 422)
        synthesize.assert_not_called()

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
            patch.object(tts_proxy, "synthesize") as synthesize,
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
                tts_proxy,
                "synthesize",
                side_effect=tts_proxy.TTSUnavailable("offline"),
            ),
        ):
            response = self.client.post("/api/tts", json={"text": "failure"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(capacity.released, 1)


if __name__ == "__main__":
    unittest.main()
