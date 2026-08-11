from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from urllib import error
from unittest.mock import patch

from tools import tts_bridge

VALID_TOKEN = "bridge-test-secret-" + "z" * 40


class FakeResponse:
    def __init__(self, body: bytes = b'{"ok":true}', status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class TtsBridgeUrlTests(unittest.TestCase):
    def test_extracts_only_quick_tunnel_origin(self):
        line = "INF Your quick Tunnel has been created! https://Quiet-Fox.trycloudflare.com"
        self.assertEqual(
            tts_bridge.parse_trycloudflare_url(line),
            "https://quiet-fox.trycloudflare.com",
        )

    def test_does_not_accept_suffix_confusion(self):
        self.assertIsNone(
            tts_bridge.parse_trycloudflare_url(
                "https://quiet-fox.trycloudflare.com.attacker.example"
            )
        )

    def test_render_origin_requires_https_except_loopback(self):
        self.assertEqual(
            tts_bridge.normalize_render_url("https://memory-call.onrender.com/"),
            "https://memory-call.onrender.com",
        )
        self.assertEqual(
            tts_bridge.normalize_render_url("http://127.0.0.1:8000/"),
            "http://127.0.0.1:8000",
        )
        with self.assertRaises(tts_bridge.BridgeError):
            tts_bridge.normalize_render_url("http://memory-call.onrender.com")
        with self.assertRaises(tts_bridge.BridgeError):
            tts_bridge.normalize_render_url("https://memory-call.onrender.com/path")


class TtsBridgeDiscoveryTests(unittest.TestCase):
    def test_cloudflared_explicit_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = root / "explicit-cloudflared.exe"
            explicit.touch()
            repository = root / ".tools" / "cloudflared.exe"
            repository.parent.mkdir()
            repository.touch()
            result = tts_bridge.find_cloudflared(
                root,
                {"CLOUDFLARED_PATH": str(explicit)},
                which=lambda _name: None,
            )
            self.assertEqual(result, explicit.resolve())

    def test_musetalk_runtime_prefers_prepared_portable_python(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = (
                Path(".tools/python310/bin/python.exe")
                if os.name == "nt"
                else Path(".tools/python310/bin/python")
            )
            python = root / relative
            python.parent.mkdir(parents=True)
            python.touch()
            result = tts_bridge.find_musetalk_python(
                root,
                {},
                probe=lambda value: value == python.resolve(),
            )
        self.assertEqual(result, python.resolve())

    def test_musetalk_runtime_explicit_broken_python_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "python.exe"
            path.touch()
            with self.assertRaises(tts_bridge.BridgeError):
                tts_bridge.find_musetalk_python(
                    Path(temporary),
                    {"MUSETALK_PYTHON_PATH": str(path)},
                    probe=lambda _value: False,
                )


class TtsBridgeLifecycleTests(unittest.TestCase):
    @staticmethod
    def config() -> tts_bridge.BridgeConfig:
        return tts_bridge.BridgeConfig(
            render_url="https://memory-call.onrender.com",
            token=VALID_TOKEN,
            cloudflared=Path("cloudflared.exe"),
            musetalk_python=Path("musetalk-python.exe"),
            musetalk_dir=Path("MuseTalk"),
            musetalk_source_video=Path("idle.mp4"),
            restart_delay=0.001,
        )

    def test_process_start_failures_are_supervisor_errors(self):
        with patch.object(
            tts_bridge.subprocess, "Popen", side_effect=OSError("not executable")
        ):
            with self.assertRaises(tts_bridge.BridgeError):
                tts_bridge.start_musetalk(self.config())
            with self.assertRaises(tts_bridge.BridgeError):
                tts_bridge.start_tunnel(self.config())

    def test_musetalk_starts_offline_on_its_fixed_loopback_port(self):
        config = self.config()
        process = object()
        with patch.object(
            tts_bridge.subprocess,
            "Popen",
            return_value=process,
        ) as popen:
            returned = tts_bridge.start_musetalk(config)

        self.assertIs(returned, process)
        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertIn("--port", command)
        self.assertEqual(command[command.index("--port") + 1], "8002")
        self.assertIn("musetalk_server.py", command[2])
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(environment["TTS_BRIDGE_TOKEN"], VALID_TOKEN)

    def test_tunnel_targets_the_musetalk_port(self):
        config = replace(self.config(), musetalk_port=8002)
        stub_process = type("StubProcess", (), {"stdout": None})()
        with patch.object(
            tts_bridge.subprocess, "Popen", return_value=stub_process
        ) as popen:
            tts_bridge.start_tunnel(config)

        command = popen.call_args.args[0]
        self.assertIn("http://127.0.0.1:8002", command)

    def test_loopback_health_opener_has_no_proxy(self):
        proxy_handlers = [
            handler
            for handler in tts_bridge._LOOPBACK_OPENER.handlers
            if isinstance(handler, tts_bridge.request.ProxyHandler)
        ]
        # urllib omits an empty ProxyHandler from the installed handler list;
        # either absence or an explicit empty mapping means no system proxy.
        self.assertTrue(
            not proxy_handlers or all(handler.proxies == {} for handler in proxy_handlers)
        )

    def test_retryable_registration_error_is_retried(self):
        process = type("AliveProcess", (), {"poll": lambda self: None})()
        retry = tts_bridge.RegistrationError("temporary", retryable=True, status=503)
        with patch.object(
            tts_bridge,
            "register_bridge",
            side_effect=[retry, {"ok": True}],
        ) as register:
            tts_bridge._register_until_success(
                self.config(),
                "https://voice.trycloudflare.com",
                process,
                threading.Event(),
            )
        self.assertEqual(register.call_count, 2)

    def test_termination_timeout_does_not_hide_original_failure(self):
        class StubbornProcess:
            def poll(self):
                return None

            def terminate(self):
                return None

            def kill(self):
                return None

            def wait(self, timeout):
                raise subprocess.TimeoutExpired("child", timeout)

        tts_bridge.terminate_process(StubbornProcess(), timeout=0.001)


class TtsBridgeRegistrationTests(unittest.TestCase):
    def test_registration_uses_exact_contract_and_bearer_header(self):
        captured = {}

        def opener(req, *, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["authorization"] = req.get_header("Authorization")
            captured["content_type"] = req.get_header("Content-type")
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        response = tts_bridge.register_bridge(
            "https://memory-call.onrender.com",
            "https://quiet-fox.trycloudflare.com",
            VALID_TOKEN,
            timeout=7,
            opener=opener,
        )

        self.assertEqual(response, {"ok": True})
        self.assertEqual(
            captured["url"],
            "https://memory-call.onrender.com/api/tts/bridge/register",
        )
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["authorization"], f"Bearer {VALID_TOKEN}")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(
            captured["payload"],
            {"service_url": "https://quiet-fox.trycloudflare.com"},
        )
        self.assertEqual(captured["timeout"], 7)

    def test_registration_rejects_non_quick_tunnel_url_before_network(self):
        with self.assertRaises(tts_bridge.BridgeError):
            tts_bridge.register_bridge(
                "https://memory-call.onrender.com",
                "https://quiet-fox.trycloudflare.com.attacker.example",
                VALID_TOKEN,
                opener=lambda *_args, **_kwargs: self.fail("network must not be called"),
            )

    def test_authentication_error_is_not_retryable(self):
        def opener(req, *, timeout):
            raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with self.assertRaises(tts_bridge.RegistrationError) as raised:
            tts_bridge.register_bridge(
                "https://memory-call.onrender.com",
                "https://quiet-fox.trycloudflare.com",
                VALID_TOKEN,
                opener=opener,
            )
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.status, 401)

    def test_server_error_is_retryable(self):
        def opener(req, *, timeout):
            raise error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

        with self.assertRaises(tts_bridge.RegistrationError) as raised:
            tts_bridge.register_bridge(
                "https://memory-call.onrender.com",
                "https://quiet-fox.trycloudflare.com",
                VALID_TOKEN,
                opener=opener,
            )
        self.assertTrue(raised.exception.retryable)


class TtsBridgeSecretTests(unittest.TestCase):
    def test_missing_token_has_actionable_error_without_secret_value(self):
        with self.assertRaises(tts_bridge.BridgeError) as raised:
            tts_bridge.require_bridge_token({})
        self.assertIn("TTS_BRIDGE_TOKEN", str(raised.exception))
        self.assertIn("token_urlsafe", str(raised.exception))

    def test_token_is_read_without_modification(self):
        self.assertEqual(
            tts_bridge.require_bridge_token(
                {"TTS_BRIDGE_TOKEN": f"  {VALID_TOKEN}  "}
            ),
            VALID_TOKEN,
        )

    def test_placeholder_and_short_tokens_fail_closed(self):
        for value in ("short", "replace-with-a-long-random-token"):
            with self.subTest(value=value):
                with self.assertRaises(tts_bridge.BridgeError):
                    tts_bridge.require_bridge_token({"TTS_BRIDGE_TOKEN": value})


if __name__ == "__main__":
    unittest.main()
