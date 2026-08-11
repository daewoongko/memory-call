from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import storage  # noqa: E402


class PersonaFaceStorageTests(unittest.TestCase):
    def test_non_legacy_people_receive_distinct_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            people = Path(temporary) / "personas"
            with patch.object(storage, "PERSONAS_ROOT", people):
                jeonghun = storage.persona_face_storage("persona_jeonghun")
                miyeong = storage.persona_face_storage("persona_miyeong")

            self.assertNotEqual(jeonghun.root, miyeong.root)
            self.assertEqual(jeonghun.source, people / "persona_jeonghun" / "source")
            self.assertEqual(miyeong.morph, people / "persona_miyeong" / "morph.mp4")

    def test_api_returns_only_selected_person_keyframes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "persona_jeonghun"
            final = root / "aligned" / "age_path_final"
            final.mkdir(parents=True)
            (final / "01_age54.png").write_bytes(b"jeonghun")
            paths = storage.PersonaFaceStorage(
                "persona_jeonghun", root, root / "source",
                root / "age_candidates", root / "age_anchors",
                root / "age_debug", root / "age_plan.json", root / "raw",
                root / "aligned", final, root / "loops", root / "morph.mp4",
                False,
            )
            with patch.object(api, "ensure_persona_face_directories", return_value=paths):
                faces = api._face_urls("persona_jeonghun")

            self.assertEqual(
                faces,
                [{
                    "stage": "age54",
                    "url": "/persona-assets/persona_jeonghun/aligned/age_path_final/01_age54.png",
                }],
            )

    def test_api_previews_selected_candidates_before_final_path_is_built(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "persona_miyeong"
            source = root / "source"
            candidates = root / "age_candidates"
            final = root / "aligned" / "age_path_final"
            source.mkdir(parents=True)
            candidates.mkdir(parents=True)
            final.mkdir(parents=True)
            (source / "current.png").write_bytes(b"current")
            (candidates / "age51.png").write_bytes(b"past")
            (final / "99_age56.png").write_bytes(b"current")
            paths = storage.PersonaFaceStorage(
                "persona_miyeong", root, source, candidates,
                root / "age_anchors", root / "age_debug",
                root / "age_plan.json", root / "raw", root / "aligned",
                final, root / "loops", root / "morph.mp4", False,
            )
            plan = {
                "stages": [
                    {"age": 51, "kind": "generated", "selected": "age51.png"},
                    {"age": 56, "kind": "current", "selected": "current.png"},
                ]
            }
            with (
                patch.object(api, "ensure_persona_face_directories", return_value=paths),
                patch.object(api.age_timeline, "get_plan", return_value=plan),
            ):
                faces = api._face_urls("persona_miyeong")

            self.assertEqual([face["stage"] for face in faces], ["age51", "age56"])
            self.assertTrue(all("persona_miyeong" in face["url"] for face in faces))


if __name__ == "__main__":
    unittest.main()
