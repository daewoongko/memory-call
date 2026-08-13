import gc
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import memories  # noqa: E402
from PIL import Image  # noqa: E402


class MemoryArtworkFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "memory.sqlite"
        with db.connect() as conn:
            db.init_schema(conn)
            db.insert(conn, "elder_profiles", {"elder_id": "elder_test", "name": "테스트"})
            db.insert(conn, "calls", {
                "call_id": "call_memory", "elder_id": "elder_test",
                "status": "ended", "duration_sec": 60,
            })
            utterance_id = db.insert(conn, "utterances", {
                "call_id": "call_memory", "seq": 1, "speaker": "elder",
                "transcript": "옛날 고향 냇가가 생각난다.",
                "unverified_recall": {
                    "summary": "고향 냇가 이야기",
                    "quote": "옛날 고향 냇가가 생각난다.",
                },
            })
            self.utterance_id = utterance_id
            db.insert(conn, "heart_artworks", {
                "artwork_id": "art_candidate", "call_id": "call_memory",
                "source_utterance_id": utterance_id, "status": "candidate",
                "image_url": "/heart-art/test.png",
                "source_quote": "옛날 고향 냇가가 생각난다.",
                "alt_text": "고향 냇가 그림",
                "caption": "실제 장면을 재현한 사진은 아닙니다.",
            })
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.original_path
        gc.collect()
        self.temp.cleanup()

    def test_approval_links_artwork_to_verified_memory_and_delete_hides_it(self):
        result = memories.review(self.utterance_id, "approved", "elder_test")
        memory_id = result["memory"]["memory_id"]

        listed = memories.listing("elder_test")
        self.assertEqual(listed[0]["memory_id"], memory_id)
        self.assertEqual(listed[0]["artwork"]["image_url"], "/heart-art/test.png")

        with db.connect() as conn:
            artwork = conn.execute(
                "SELECT status, memory_id FROM heart_artworks WHERE artwork_id = ?",
                ("art_candidate",),
            ).fetchone()
        self.assertEqual(artwork["status"], "approved")
        self.assertEqual(artwork["memory_id"], memory_id)

        memories.delete(memory_id)
        with db.connect() as conn:
            artwork = conn.execute(
                "SELECT status, memory_id FROM heart_artworks WHERE artwork_id = ?",
                ("art_candidate",),
            ).fetchone()
        self.assertEqual(artwork["status"], "rejected")
        self.assertIsNone(artwork["memory_id"])

    def test_memory_photo_is_validated_saved_and_returned(self):
        created = memories.create("elder_test", {
            "title": "봄 소풍", "happened_year": 1975,
        })
        original_root = memories.MEMORY_PHOTOS_ROOT
        memories.MEMORY_PHOTOS_ROOT = Path(self.temp.name) / "photos"
        try:
            buffer = BytesIO()
            Image.new("RGB", (48, 36), "green").save(buffer, "JPEG")
            result = memories.save_photo(
                "elder_test", created["memory_id"], "pic.jpg", buffer.getvalue()
            )
            self.assertTrue(result["photo_url"].startswith("/memory-photos/elder_test/"))
            self.assertTrue(next((memories.MEMORY_PHOTOS_ROOT / "elder_test").iterdir()).exists())
            listed = memories.listing("elder_test")
            self.assertEqual(listed[0]["happened_year"], 1975)
            self.assertEqual(listed[0]["photo_url"], result["photo_url"])
            with self.assertRaisesRegex(ValueError, "해당 어르신"):
                memories.save_photo("other", created["memory_id"], "pic.jpg", buffer.getvalue())
        finally:
            memories.MEMORY_PHOTOS_ROOT = original_root


if __name__ == "__main__":
    unittest.main()
