from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

VALID_TOKEN = "server-test-secret-" + "s" * 40
WRONG_TOKEN = "wrong-test-secret-" + "w" * 40


def load_tts_server_module():
    fake_librosa = types.ModuleType("librosa")
    fake_librosa.effects = types.SimpleNamespace(time_stretch=lambda samples, rate: samples)

    fake_numpy = types.ModuleType("numpy")
    fake_numpy.clip = lambda samples, _minimum, _maximum: samples

    fake_soundfile = types.ModuleType("soundfile")
    fake_soundfile.write = lambda *_args, **_kwargs: None

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_name=lambda _index: "Test GPU",
    )
    fake_torch.inference_mode = nullcontext

    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *_args, **_kwargs: None

    fake_chatterbox = types.ModuleType("chatterbox")
    fake_mtl = types.ModuleType("chatterbox.mtl_tts")
    fake_mtl.ChatterboxMultilingualTTS = type("FakeChatterbox", (), {})

    modules = {
        "librosa": fake_librosa,
        "numpy": fake_numpy,
        "soundfile": fake_soundfile,
        "torch": fake_torch,
        "uvicorn": fake_uvicorn,
        "chatterbox": fake_chatterbox,
        "chatterbox.mtl_tts": fake_mtl,
    }
    path = Path(__file__).resolve().parents[1] / "tools" / "tts_server.py"
    spec = importlib.util.spec_from_file_location("tts_server_auth_test_target", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class FakeEngine:
    def __init__(self):
        self.reference = Path("reference.wav")
        self.model = object()
        self.loaded_seconds = 1.25
        self.load_count = 0

    def load(self):
        self.load_count += 1

    def synthesize(self, text: str, rate: float):
        return b"RIFF-test-wave", 1.5, 0.25


class TtsServerAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_tts_server_module()

    def test_health_and_synthesis_require_matching_bearer_token(self):
        engine = FakeEngine()
        app = self.server.create_app(engine, bridge_token=VALID_TOKEN)
        with TestClient(app) as client:
            missing = client.get("/health")
            wrong = client.get(
                "/health", headers={"Authorization": f"Bearer {WRONG_TOKEN}"}
            )
            valid = client.get(
                "/health", headers={"Authorization": f"Bearer {VALID_TOKEN}"}
            )
            synth_missing = client.post(
                "/synthesize", json={"text": "안녕하세요", "rate": 0.92}
            )
            synth_valid = client.post(
                "/synthesize",
                json={"text": "안녕하세요", "rate": 0.92},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json()["ok"])
        self.assertEqual(synth_missing.status_code, 401)
        self.assertEqual(synth_valid.status_code, 200)
        self.assertEqual(synth_valid.content, b"RIFF-test-wave")
        self.assertEqual(synth_valid.headers["x-tts-model"], "chatterbox-multilingual-v3")
        self.assertEqual(engine.load_count, 1)

    def test_missing_token_fails_before_server_start(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                self.server.create_app(FakeEngine())
        self.assertIn("TTS_BRIDGE_TOKEN", str(raised.exception))
        self.assertIn("token_urlsafe", str(raised.exception))

    def test_placeholder_token_fails_before_server_start(self):
        with self.assertRaises(RuntimeError):
            self.server.create_app(
                FakeEngine(), bridge_token="replace-with-a-long-random-token"
            )

    def test_cpu_fallback_remains_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.wav"
            reference.touch()
            engine = self.server.VoiceEngine(reference)
            with patch.object(self.server.torch.cuda, "is_available", return_value=False):
                with self.assertRaises(RuntimeError) as raised:
                    engine.load()
        self.assertIn("CUDA GPU", str(raised.exception))

    def test_server_default_bind_remains_loopback(self):
        source = (Path(__file__).resolve().parents[1] / "tools" / "tts_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('parser.add_argument("--host", default="127.0.0.1")', source)


if __name__ == "__main__":
    unittest.main()
