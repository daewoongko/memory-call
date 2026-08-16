"""가족별 Anam 아바타 생성·저장·비공개 동작."""

from __future__ import annotations

import gc
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "backend"))

import anam  # noqa: E402
import db  # noqa: E402
import persona_avatar  # noqa: E402
from storage import PersonaFaceStorage  # noqa: E402


class PersonaAvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(db, "DB_PATH", self.root / "test.sqlite")
        self.storage_patch = patch.object(
            persona_avatar,
            "persona_face_storage",
            side_effect=self._storage,
        )
        self.db_patch.start()
        self.storage_patch.start()
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
        source = self._storage("persona_test").source
        source.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (600, 800), "#d8cfc3").save(source / "portrait.png")

    def tearDown(self):
        self.storage_patch.stop()
        self.db_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def _storage(self, persona_id: str) -> PersonaFaceStorage:
        root = self.root / persona_id
        aligned = root / "aligned"
        return PersonaFaceStorage(
            persona_id, root, root / "source", root / "age_candidates",
            root / "age_anchors", root / "age_debug", root / "age_plan.json",
            root / "raw", aligned, aligned / "age_path_final", root / "loops",
            root / "morph.mp4", False,
        )

    def test_confirmed_photo_creates_private_avatar_once(self):
        with (
            patch.object(persona_avatar.anam, "configured", return_value=True),
            patch.object(
                persona_avatar.anam,
                "create_avatar",
                return_value={"avatar_id": "private-avatar-id", "avatar_model": "cara-4"},
            ) as create,
        ):
            first = persona_avatar.sync_from_confirmed_photo(
                "persona_test", "portrait.png", "elder_test",
            )
            second = persona_avatar.sync_from_confirmed_photo(
                "persona_test", "portrait.png", "elder_test",
            )

        self.assertTrue(first["ready"])
        self.assertEqual(first["avatar_status"], "ready")
        self.assertNotIn("avatar_id", first)
        self.assertNotIn("avatar_id", second)
        self.assertEqual(persona_avatar.active_avatar_id("persona_test"), "private-avatar-id")
        self.assertEqual(
            persona_avatar.active_avatar("persona_test"),
            {"avatar_id": "private-avatar-id", "avatar_model": "cara-4"},
        )
        create.assert_called_once()
        image_payload = create.call_args.kwargs["image"]
        self.assertLess(len(image_payload), 4_500_000)
        with Image.open(io.BytesIO(image_payload)) as rendered:
            self.assertEqual(rendered.size, (1280, 1280))

    def test_missing_provider_key_keeps_photo_without_avatar_id(self):
        with patch.object(persona_avatar.anam, "configured", return_value=False):
            profile = persona_avatar.sync_from_confirmed_photo(
                "persona_test", "portrait.png", "elder_test",
            )

        self.assertFalse(profile["provider_configured"])
        self.assertFalse(profile["ready"])
        self.assertEqual(profile["avatar_status"], "unregistered")
        self.assertIsNone(persona_avatar.active_avatar_id("persona_test"))

    def test_provider_failure_is_visible_without_exposing_provider_id(self):
        with (
            patch.object(persona_avatar.anam, "configured", return_value=True),
            patch.object(
                persona_avatar.anam,
                "create_avatar",
                side_effect=anam.AnamUnavailable("생성 실패"),
            ),
        ):
            profile = persona_avatar.sync_from_confirmed_photo(
                "persona_test", "portrait.png", "elder_test",
            )

        self.assertEqual(profile["avatar_status"], "failed")
        self.assertEqual(profile["last_error"], "생성 실패")
        self.assertNotIn("avatar_id", profile)


if __name__ == "__main__":
    unittest.main()
