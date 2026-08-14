"""가족별 IVC 등록과 승인 흐름."""

from __future__ import annotations

import sys
import tempfile
import unittest
import gc
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import persona_voice  # noqa: E402


class PersonaVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(db, "DB_PATH", self.root / "test.sqlite")
        self.store_patch = patch.object(
            persona_voice,
            "persona_voice_storage",
            side_effect=lambda persona_id: self._voice_dir(persona_id),
        )
        self.db_patch.start()
        self.store_patch.start()
        with db.connect() as conn:
            db.init_schema(conn)
            conn.execute(
                "INSERT INTO elder_profiles(elder_id, name) VALUES (?, ?)",
                ("elder_test", "테스트 어르신"),
            )
            conn.execute(
                "INSERT INTO personas(persona_id, elder_id, display_name, relationship_type) "
                "VALUES (?, ?, ?, ?)",
                ("persona_test", "elder_test", "정훈", "아들"),
            )
            conn.commit()

    def tearDown(self):
        self.store_patch.stop()
        self.db_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def _voice_dir(self, persona_id: str) -> Path:
        path = self.root / persona_id / "voice"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _quality() -> dict:
        return {"passed": True, "average_level": 0.08, "clipped_ratio": 0.0}

    def _save(self, prompt_id: str, seconds: float = 45) -> dict:
        return persona_voice.save_sample(
            "persona_test", "elder_test", phase="ivc", prompt_id=prompt_id,
            original_name=f"{prompt_id}.webm", mime_type="audio/webm",
            payload=b"voice-data", duration_seconds=seconds,
            quality=self._quality(),
        )

    def test_two_recordings_create_preview_candidate_and_approval(self):
        profile = persona_voice.record_consent("persona_test", "elder_test", True)
        self.assertTrue(profile["consented"])
        self._save("general")
        ready = self._save("care")
        self.assertTrue(ready["ivc_can_create"])

        with patch.object(
            persona_voice, "_create_ivc_remote",
            return_value={"voice_id": "private-voice-id", "requires_verification": False},
        ):
            created = persona_voice.create_ivc("persona_test", "elder_test")
        self.assertEqual(created["voice_status"], "ivc_ready")
        self.assertNotIn("ivc_voice_id", created)
        self.assertEqual(
            persona_voice.candidate_voice_id("persona_test", "elder_test"),
            "private-voice-id",
        )

        approved = persona_voice.approve_ivc("persona_test", "elder_test")
        self.assertEqual(approved["active_voice_type"], "ivc")
        self.assertEqual(persona_voice.active_voice_id("persona_test"), "private-voice-id")

    def test_rerecording_same_prompt_replaces_old_sample(self):
        persona_voice.record_consent("persona_test", "elder_test", True)
        self._save("general", 45)
        profile = self._save("general", 50)
        general = [sample for sample in profile["samples"] if sample["prompt_id"] == "general"]
        self.assertEqual(len(general), 1)
        self.assertEqual(general[0]["duration_seconds"], 50)

    def test_failed_quality_is_not_saved(self):
        persona_voice.record_consent("persona_test", "elder_test", True)
        with self.assertRaises(persona_voice.VoiceProfileError):
            persona_voice.save_sample(
                "persona_test", "elder_test", phase="ivc", prompt_id="general",
                original_name="bad.webm", mime_type="audio/webm", payload=b"bad",
                duration_seconds=50, quality={"passed": False},
            )

    def test_delete_profile_removes_remote_voice_and_private_samples(self):
        persona_voice.record_consent("persona_test", "elder_test", True)
        self._save("general")
        sample_path = next((self.root / "persona_test" / "voice").iterdir())
        with db.connect() as conn:
            conn.execute(
                "UPDATE persona_voice_profiles SET ivc_voice_id = ?, "
                "active_voice_type = 'ivc', active_voice_id = ? WHERE persona_id = ?",
                ("private-voice-id", "private-voice-id", "persona_test"),
            )
            conn.commit()

        with patch.object(persona_voice, "_delete_remote_voice") as remote_delete:
            profile = persona_voice.delete_profile("persona_test", "elder_test")

        remote_delete.assert_called_once_with("private-voice-id")
        self.assertFalse(sample_path.exists())
        self.assertFalse(profile["consented"])
        self.assertEqual(profile["voice_status"], "unregistered")
        self.assertEqual(profile["samples"], [])
        self.assertIsNone(persona_voice.active_voice_id("persona_test"))


if __name__ == "__main__":
    unittest.main()
