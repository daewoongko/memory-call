import gc
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import signaling  # noqa: E402


class SignalingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite"
        with db.connect() as conn:
            db.init_schema(conn)

    def tearDown(self):
        db.DB_PATH = self.original_path
        gc.collect()
        self.tmp.cleanup()

    def test_each_sender_only_receives_the_other_side(self):
        signaling.send("invite_1", "caller", "offer", {"sdp": "a"})
        signaling.send("invite_1", "answerer", "answer", {"sdp": "b"})

        caller = signaling.poll("invite_1", "caller")
        answerer = signaling.poll("invite_1", "answerer")
        self.assertEqual([row["kind"] for row in caller["messages"]], ["answer"])
        self.assertEqual([row["kind"] for row in answerer["messages"]], ["offer"])

    def test_cursor_only_returns_new_messages(self):
        first = signaling.send("invite_2", "answerer", "ice", {"candidate": "a"})
        initial = signaling.poll("invite_2", "caller")
        self.assertEqual(initial["cursor"], first["id"])
        self.assertEqual(
            signaling.poll("invite_2", "caller", initial["cursor"])["messages"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
