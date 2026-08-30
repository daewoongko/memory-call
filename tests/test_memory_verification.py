import gc
import json
import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import memories  # noqa: E402
import persona  # noqa: E402


class MemoryVerificationPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "memory.sqlite"
        with db.connect() as conn:
            db.init_schema(conn)
            db.insert(conn, "elder_profiles", {"elder_id": "elder_test", "name": "테스트"})
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.original_path
        gc.collect()
        self.temp.cleanup()

    def test_partial_memory_cannot_be_enabled_until_verified(self):
        created = memories.create("elder_test", {
            "title": "확인 중인 이야기",
            "status": "partial",
            "conversation_allowed": True,
        })
        self.assertEqual(created["status"], "partial")
        self.assertEqual(created["conversation_allowed"], 0)

        still_partial = memories.update(created["memory_id"], {
            "conversation_allowed": True,
        })
        self.assertEqual(still_partial["conversation_allowed"], 0)

        verified = memories.update(created["memory_id"], {
            "status": "verified",
            "conversation_allowed": True,
        })
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["conversation_allowed"], 1)

    def test_prompt_receives_only_allowed_verified_memories_and_prohibitions(self):
        rows = [
            {"memory_id": "ok", "status": "verified", "conversation_allowed": 1,
             "title": "확인된 봄날", "description": "봄 소풍", "date_text": "1975년",
             "location": "공원", "participants": []},
            {"memory_id": "hidden", "status": "verified", "conversation_allowed": 0,
             "title": "잠시 뺀 기억", "description": "", "date_text": "", "location": "",
             "participants": []},
            {"memory_id": "partial", "status": "partial", "conversation_allowed": 0,
             "title": "확인 중인 시장", "description": "", "date_text": "", "location": "",
             "participants": []},
            {"memory_id": "blocked", "status": "prohibited", "conversation_allowed": 0,
             "title": "먼저 말하지 않을 일", "description": "", "date_text": "", "location": "",
             "participants": [], "note": "먼저 꺼내지 않는다"},
        ]
        block = persona._memory_block(rows)
        self.assertIn("확인된 봄날", block)
        self.assertIn("먼저 말하지 않을 일", block)
        self.assertNotIn("잠시 뺀 기억", block)
        self.assertNotIn("확인 중인 시장", block)

    def test_demo_seed_marks_unknown_stories_as_partial_and_disabled(self):
        seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
        by_id = {row["memory_id"]: row for row in seed["memories"]}
        for memory_id in ("mem_002", "mem_007", "mem_012"):
            self.assertEqual(by_id[memory_id]["status"], "partial")
            self.assertFalse(by_id[memory_id]["conversation_allowed"])


if __name__ == "__main__":
    unittest.main()
