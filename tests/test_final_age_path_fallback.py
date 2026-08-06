from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import admin  # noqa: E402
import api  # noqa: E402
import storage  # noqa: E402


class FinalAgePathFallbackTests(unittest.TestCase):
    def test_storage_creates_final_age_path_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            faces = root / "faces"
            aligned = faces / "aligned"
            final = aligned / "age_path_final"
            with patch.multiple(
                storage,
                STORAGE_DIR=root,
                SOURCE_FACES_DIR=faces / "source",
                AGE_CANDIDATES_DIR=faces / "age_candidates",
                AGE_ANCHORS_DIR=faces / "age_anchors",
                AGE_DEBUG_DIR=faces / "age_debug",
                RAW_FACES_DIR=faces / "raw",
                ALIGNED_FACES_DIR=aligned,
                FINAL_AGE_PATH_DIR=final,
                LOOPS_DIR=faces / "loops",
            ):
                storage.ensure_directories()
            self.assertTrue(final.is_dir())

    def test_api_prefers_final_keyframes_and_falls_back_to_aligned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            aligned = root / "aligned"
            final = aligned / "age_path_final"
            aligned.mkdir()
            final.mkdir()
            (aligned / "01_age32.png").write_bytes(b"aligned")

            with (
                patch.object(api, "FACES_DIR", aligned),
                patch.object(api, "FINAL_AGE_PATH_DIR", final),
            ):
                self.assertEqual(
                    api._face_urls(),
                    [{"stage": "age32", "url": "/faces/01_age32.png"}],
                )
                (final / "01_age08.png").write_bytes(b"final")
                (final / "contact_sheet.png").write_bytes(b"qc")
                self.assertEqual(
                    api._face_urls(),
                    [{"stage": "age08", "url": "/faces/age_path_final/01_age08.png"}],
                )

    def test_admin_faces_uses_same_priority_without_changing_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            aligned = root / "aligned"
            final = aligned / "age_path_final"
            loops = root / "loops"
            raw.mkdir()
            aligned.mkdir()
            final.mkdir()
            loops.mkdir()
            morph = root / "morph.mp4"
            (aligned / "01_age32.png").write_bytes(b"aligned")

            with (
                patch.object(admin, "RAW", raw),
                patch.object(admin, "ALIGNED", aligned),
                patch.object(admin, "FINAL_AGE_PATH", final),
                patch.object(admin, "LOOPS", loops),
                patch.object(admin, "MORPH", morph),
            ):
                fallback = admin.faces()
                self.assertEqual(fallback["aligned"][0]["url"], "/faces/01_age32.png")

                (final / "01_age08.png").write_bytes(b"final")
                (final / "transition_15_16_17.png").write_bytes(b"qc")
                preferred = admin.faces()
                self.assertEqual(
                    preferred["aligned"],
                    [{"name": "01_age08.png", "size_kb": 0, "url": "/faces/age_path_final/01_age08.png"}],
                )
                self.assertEqual(set(preferred), {"raw", "aligned", "morph", "loops"})


if __name__ == "__main__":
    unittest.main()
