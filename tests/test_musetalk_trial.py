from __future__ import annotations

import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path


def load_trial_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "musetalk_trial.py"
    spec = importlib.util.spec_from_file_location("musetalk_trial_test_target", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MuseTalkTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trial = load_trial_module()

    def test_required_model_manifest_is_complete_and_detects_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = self.trial.required_model_paths(root)
            self.assertEqual(len(required), 11)
            self.assertEqual(self.trial.missing_model_paths(root), required)
            for path in required:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(self.trial.missing_model_paths(root), [])

    def test_trial_config_uses_safe_forward_slash_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "trial.yaml"
            video = root / "idle_25fps.mp4"
            audio = root / "chatterbox_ko.wav"
            self.trial.write_trial_config(config, video, audio)
            text = config.read_text(encoding="utf-8")
            self.assertIn("trial_idle_ko:", text)
            self.assertIn("video_path: '", text)
            self.assertIn("audio_path: '", text)
            self.assertNotIn("\\\\", text)
            self.assertIn(self.trial.DEFAULT_RESULT_NAME, text)

    def test_setup_script_pins_huggingface_and_downloads_exact_files(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "tools" / "setup" / "setup_musetalk_runtime.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"huggingface_hub==0.30.2"', script)
        self.assertIn('"hf-xet==1.6.0"', script)
        self.assertIn('Get-ModelFile "TMElyralab/MuseTalk"', script)
        self.assertIn('"musetalkV15/musetalk.json"', script)
        self.assertIn('"79999_iter.pth"', script)
        self.assertNotIn(" --include ", script)
        self.assertNotIn('mim install "mmpose==1.1.0"', script)

    def test_prepared_audio_validation_accepts_only_chatterbox_pcm(self):
        with tempfile.TemporaryDirectory() as temporary:
            wav_path = Path(temporary) / "voice.wav"
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24_000)
                wav_file.writeframes(b"\x00\x00" * 2_400)
            details = self.trial.validate_trial_audio(wav_path)
            self.assertEqual(details["sample_rate"], 24_000)
            self.assertAlmostEqual(details["duration_seconds"], 0.1)

            invalid = Path(temporary) / "invalid.wav"
            invalid.write_bytes(b"not a wav file")
            with self.assertRaisesRegex(RuntimeError, "missing or empty|invalid"):
                self.trial.validate_trial_audio(invalid)


if __name__ == "__main__":
    unittest.main()
