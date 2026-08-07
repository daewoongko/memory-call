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
    fake_torch.seed_calls = []
    fake_torch.manual_seed = lambda seed: fake_torch.seed_calls.append(seed)
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
        self.synthesize_count = 0

    def load(self):
        self.load_count += 1

    def synthesize(self, text: str, rate: float):
        self.synthesize_count += 1
        return b"RIFF-test-wave", 1.5, 0.25


class FakeSamples:
    def squeeze(self):
        return self

    def __len__(self):
        return 24000


class FakeWave:
    def __init__(self):
        self.samples = FakeSamples()

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.samples


class FakeChatterboxModel:
    sr = 24000

    def __init__(self):
        self.events = []

    def prepare_conditionals(self, path: str, *, exaggeration: float):
        self.events.append(("conditionals", path, exaggeration))

    def generate(self, text: str, **kwargs):
        self.events.append(("generate", text, kwargs))
        return FakeWave()


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
        self.assertEqual(synth_valid.headers["cache-control"], "no-store")
        self.assertEqual(synth_valid.headers["x-generation-seconds"], "0.250")
        self.assertEqual(synth_valid.headers["x-tts-generation-seconds"], "0.250")
        self.assertIn("tts-request;dur=", synth_valid.headers["server-timing"])
        self.assertIn("tts-generate;dur=250.00", synth_valid.headers["server-timing"])
        self.assertEqual(engine.load_count, 1)

    def test_video_endpoint_returns_mp4_without_synthesizing_twice(self):
        engine = FakeEngine()

        class Renderer:
            def render(self, audio):
                self.audio = audio
                return self_server.MuseTalkRender(
                    b"\x00\x00\x00\x18ftypisom-video", 0.75
                )

        self_server = self.server
        renderer = Renderer()
        app = self.server.create_app(
            engine,
            bridge_token=VALID_TOKEN,
            musetalk=renderer,
        )
        with TestClient(app) as client:
            response = client.post(
                "/synthesize-video",
                json={"text": "입 모양 테스트", "rate": 0.92},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response.headers["x-lipsync-seconds"], "0.750")
        self.assertEqual(renderer.audio, b"RIFF-test-wave")
        self.assertEqual(engine.synthesize_count, 1)

    def test_video_endpoint_returns_byte_identical_wav_on_any_renderer_error(self):
        engine = FakeEngine()

        class BrokenRenderer:
            def render(self, _audio):
                raise RuntimeError("private worker detail")

        app = self.server.create_app(
            engine,
            bridge_token=VALID_TOKEN,
            musetalk=BrokenRenderer(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/synthesize-video",
                json={"text": "오디오 대체", "rate": 0.92},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.headers["x-lipsync-fallback"], "audio")
        self.assertEqual(response.content, b"RIFF-test-wave")
        self.assertNotIn("private worker detail", response.text)
        self.assertEqual(engine.synthesize_count, 1)

    def test_reference_conditionals_and_korean_warmup_run_once_before_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.wav"
            reference.touch()
            model = FakeChatterboxModel()
            engine = self.server.VoiceEngine(reference)

            with patch.object(
                self.server.ChatterboxMultilingualTTS,
                "from_pretrained",
                return_value=model,
                create=True,
            ) as load_model:
                engine.load()
                engine.synthesize("첫 번째 응답", 1.0)
                engine.synthesize("두 번째 응답", 1.0)

        load_model.assert_called_once_with(device="cuda", t3_model="v3")
        conditionals = [event for event in model.events if event[0] == "conditionals"]
        generations = [event for event in model.events if event[0] == "generate"]
        self.assertEqual(conditionals, [("conditionals", str(reference), 0.5)])
        self.assertEqual(generations[0][1], self.server.WARMUP_TEXT)
        self.assertEqual([event[1] for event in generations[1:]], ["첫 번째 응답", "두 번째 응답"])
        self.assertTrue(all("audio_prompt_path" not in event[2] for event in generations))
        self.assertIs(engine.model, model)
        self.assertGreaterEqual(engine.conditionals_seconds, 0.0)
        self.assertGreaterEqual(engine.warmup_seconds, 0.0)

    def test_generation_seed_is_reset_for_warmup_and_each_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.wav"
            reference.touch()
            model = FakeChatterboxModel()
            engine = self.server.VoiceEngine(reference, generation_seed=12345)
            self.server.torch.seed_calls.clear()

            with patch.object(
                self.server.ChatterboxMultilingualTTS,
                "from_pretrained",
                return_value=model,
                create=True,
            ):
                engine.load()
                engine.synthesize("같은 문장", 1.0)
                engine.synthesize("같은 문장", 1.0)

        self.assertEqual(self.server.torch.seed_calls, [12345, 12345, 12345])

    def test_synthesis_records_each_phase_without_changing_legacy_tuple(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.wav"
            reference.touch()
            model = FakeChatterboxModel()
            engine = self.server.VoiceEngine(reference)
            engine.model = model

            with patch.object(
                self.server.librosa.effects,
                "time_stretch",
                wraps=self.server.librosa.effects.time_stretch,
            ) as stretch:
                audio, duration, elapsed = engine.synthesize("속도 검사", 0.92)

        stretch.assert_called_once()
        self.assertIsInstance(audio, bytes)
        self.assertEqual(duration, 1.0)
        self.assertGreaterEqual(elapsed, 0.0)
        timings = engine.last_timings()
        self.assertIsNotNone(timings)
        self.assertGreaterEqual(timings.queue_seconds, 0.0)
        self.assertGreaterEqual(timings.model_seconds, 0.0)
        self.assertGreaterEqual(timings.time_stretch_seconds, 0.0)
        self.assertGreaterEqual(timings.wav_encode_seconds, 0.0)
        self.assertEqual(timings.pipeline_seconds, elapsed)

        generation = [event for event in model.events if event[0] == "generate"]
        self.assertEqual(len(generation), 1)
        self.assertNotIn("audio_prompt_path", generation[0][2])

    def test_timing_headers_sanitize_non_finite_values(self):
        timings = self.server.SynthesisTimings(
            queue_seconds=float("inf"),
            pipeline_seconds=0.0,
            model_seconds=-1.0,
            time_stretch_seconds=float("nan"),
            wav_encode_seconds=0.125,
        )
        headers = self.server._timing_headers(float("nan"), -5.0, timings)

        self.assertEqual(headers["X-TTS-Request-Seconds"], "0.000")
        self.assertEqual(headers["X-TTS-Queue-Seconds"], "0.000")
        self.assertEqual(headers["X-TTS-Generation-Seconds"], "0.000")
        self.assertEqual(headers["X-TTS-Time-Stretch-Seconds"], "0.000")
        self.assertEqual(headers["X-TTS-Wav-Encode-Seconds"], "0.125")
        self.assertNotIn("nan", headers["Server-Timing"].lower())
        self.assertNotIn("inf", headers["Server-Timing"].lower())

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
