from __future__ import annotations

import io
import tempfile
import types
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from fastapi.testclient import TestClient

from tools import musetalk_server


VALID_TOKEN = "musetalk-test-secret-" + "m" * 40
WRONG_TOKEN = "wrong-musetalk-secret-" + "w" * 40


def make_wav(
    *,
    rate: int = 24000,
    channels: int = 1,
    width: int = 2,
    seconds: float = 0.1,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        target.writeframes(b"\x00" * int(rate * channels * width * seconds))
    return output.getvalue()


class FakeEngine:
    def __init__(self):
        self.config = types.SimpleNamespace(avatar_id="fixed-avatar")
        self.loaded = False
        self.loaded_seconds = 1.25
        self.batch_size = 32
        self.load_count = 0
        self.render_count = 0

    def load(self):
        self.load_count += 1
        self.loaded = True

    def render(self, audio: bytes):
        self.render_count += 1
        self.audio = audio
        return musetalk_server.RenderOutcome(
            video=b"\x00\x00\x00\x18ftypisom-video",
            elapsed_seconds=0.5,
            frame_count=10,
        )


class MuseTalkServerTests(unittest.TestCase):
    def test_health_and_render_require_the_shared_bearer(self):
        engine = FakeEngine()
        app = musetalk_server.create_app(engine, VALID_TOKEN)
        with TestClient(app) as client:
            missing = client.get("/health")
            wrong = client.post(
                "/render",
                content=make_wav(),
                headers={
                    "Authorization": f"Bearer {WRONG_TOKEN}",
                    "Content-Type": "audio/wav",
                },
            )
            health = client.get(
                "/health",
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )
            rendered = client.post(
                "/render",
                content=make_wav(),
                headers={
                    "Authorization": f"Bearer {VALID_TOKEN}",
                    "Content-Type": "audio/wav",
                },
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        self.assertEqual(rendered.status_code, 200)
        self.assertEqual(rendered.headers["content-type"], "video/mp4")
        self.assertEqual(rendered.headers["x-lipsync-seconds"], "0.500")
        self.assertEqual(engine.load_count, 1)
        self.assertEqual(engine.render_count, 1)

    def test_only_mono_pcm16_24khz_wav_is_accepted(self):
        for audio in (
            b"not-wave",
            make_wav(rate=16000),
            make_wav(channels=2),
            make_wav(width=1),
        ):
            with self.subTest(length=len(audio)):
                with self.assertRaises(musetalk_server.InvalidWave):
                    musetalk_server.validate_wav(audio)

        musetalk_server.validate_wav(make_wav())

    def test_busy_worker_returns_retryable_conflict(self):
        engine = FakeEngine()

        def busy(_audio):
            raise musetalk_server.MuseTalkBusy("busy")

        engine.render = busy
        app = musetalk_server.create_app(engine, VALID_TOKEN)
        with TestClient(app) as client:
            response = client.post(
                "/render",
                content=make_wav(),
                headers={
                    "Authorization": f"Bearer {VALID_TOKEN}",
                    "Content-Type": "audio/wav",
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers["retry-after"], "1")

    def test_content_type_is_not_caller_selectable(self):
        app = musetalk_server.create_app(FakeEngine(), VALID_TOKEN)
        with TestClient(app) as client:
            response = client.post(
                "/render",
                content=make_wav(),
                headers={
                    "Authorization": f"Bearer {VALID_TOKEN}",
                    "Content-Type": "application/octet-stream",
                },
            )
        self.assertEqual(response.status_code, 415)


class MuseTalkEncoderTests(unittest.TestCase):
    """Cover the real render path, which the FakeEngine tests cannot reach."""

    FPS = 25
    WIDTH = 48
    HEIGHT = 64

    def build_engine(self) -> musetalk_server.MuseTalkEngine:
        root = Path(tempfile.mkdtemp(prefix="musetalk-encoder-test-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        config = musetalk_server.MuseTalkConfig(
            musetalk_dir=root,
            source_video=root / "idle.mp4",
            ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe()),
            fps=self.FPS,
        )
        config.work_dir.mkdir(parents=True, exist_ok=True)
        engine = musetalk_server.MuseTalkEngine(config)
        engine.loaded = True
        engine.avatar = types.SimpleNamespace(
            frame_list_cycle=[
                np.full((self.HEIGHT, self.WIDTH, 3), value, dtype=np.uint8)
                for value in range(0, 200, 20)
            ]
        )
        return engine

    def test_encoder_command_is_a_single_pass_from_stdin(self):
        engine = self.build_engine()
        command = engine.encoder_command(
            Path("speech.wav"), Path("out.mp4"), self.WIDTH, self.HEIGHT
        )

        self.assertIn("rawvideo", command)
        self.assertIn("pipe:0", command)
        self.assertIn(f"{self.WIDTH}x{self.HEIGHT}", command)
        self.assertEqual(command.count("-i"), 2)
        self.assertIn("0:v:0", command)
        self.assertIn("1:a:0", command)
        # An image2 input would mean frames were written to disk first.
        self.assertNotIn("image2", command)

    def test_render_muxes_piped_frames_without_writing_images(self):
        engine = self.build_engine()
        cycle = engine.avatar.frame_list_cycle
        produced = 30

        def fake_infer(audio_path, frame_sink):
            for index in range(produced):
                frame_sink(cycle[index % len(cycle)])
            return produced

        engine._infer = fake_infer
        outcome = engine.render(make_wav(seconds=produced / self.FPS))

        self.assertEqual(outcome.frame_count, produced)
        self.assertEqual(outcome.video[4:8], b"ftyp")
        self.assertEqual(engine.phase, produced % len(cycle))

        images = list(engine.config.work_dir.rglob("*.png"))
        self.assertEqual(images, [], "frames must never round-trip through disk")
        self.assertEqual(list(engine.config.work_dir.iterdir()), [])

        # Decode with the same ffmpeg that encoded it; cv2's video backend is
        # not dependable inside CI containers.
        playable = Path(tempfile.mkdtemp()) / "out.mp4"
        self.addCleanup(lambda: playable.unlink(missing_ok=True))
        playable.write_bytes(outcome.video)
        reader = imageio_ffmpeg.read_frames(str(playable))
        meta = next(reader)
        decoded = sum(1 for _ in reader)

        self.assertEqual(meta["size"], (self.WIDTH, self.HEIGHT))
        self.assertEqual(decoded, produced)

    def test_gpu_cache_is_released_after_success_and_after_failure(self):
        """Holding the inference peak indefinitely wastes VRAM on a long-running worker."""
        for should_fail in (False, True):
            with self.subTest(failed=should_fail):
                engine = self.build_engine()
                released = []
                engine.torch = types.SimpleNamespace(
                    cuda=types.SimpleNamespace(
                        empty_cache=lambda: released.append(True)
                    )
                )
                cycle = engine.avatar.frame_list_cycle

                def fake_infer(audio_path, frame_sink):
                    if should_fail:
                        raise RuntimeError("inference blew up")
                    for index in range(10):
                        frame_sink(cycle[index % len(cycle)])
                    return 10

                engine._infer = fake_infer
                if should_fail:
                    with self.assertRaises(RuntimeError):
                        engine.render(make_wav(seconds=0.4))
                else:
                    engine.render(make_wav(seconds=0.4))

                self.assertEqual(len(released), 1)

    def test_warmup_audio_fills_at_least_one_full_batch(self):
        """A sub-batch warmup left the first real reply paying CUDA init."""
        engine = self.build_engine()
        target = Path(tempfile.mkdtemp()) / "warmup.wav"
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        engine._write_silence(target)

        with wave.open(str(target), "rb") as source:
            seconds = source.getnframes() / source.getframerate()

        self.assertGreaterEqual(seconds * self.FPS, engine.config.batch_size)

    def test_mis_sized_frame_fails_instead_of_shearing_the_video(self):
        engine = self.build_engine()

        def fake_infer(audio_path, frame_sink):
            frame_sink(np.zeros((self.HEIGHT + 2, self.WIDTH, 3), dtype=np.uint8))
            return 1

        engine._infer = fake_infer
        with self.assertRaises(RuntimeError):
            engine.render(make_wav())

        # The lock and the ffmpeg child must not leak after a failed render.
        self.assertTrue(engine.lock.acquire(blocking=False))
        engine.lock.release()
        self.assertEqual(list(engine.config.work_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
