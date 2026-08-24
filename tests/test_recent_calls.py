import os
import sys
import tempfile
import unittest
import gc
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")

import db  # noqa: E402
import report  # noqa: E402


class RecentCallsTest(unittest.TestCase):
    def test_recent_exposes_call_type_for_family_call_board(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database = Path(directory) / "recent.sqlite"
            with patch.object(db, "DB_PATH", database):
                with db.connect() as conn:
                    db.init_schema(conn)
                    db.insert(conn, "elder_profiles", {
                        "elder_id": "elder_001",
                        "name": "고길동",
                    })
                    db.insert(conn, "calls", {
                        "call_id": "call_direct_test",
                        "elder_id": "elder_001",
                        "counterpart_name": "정훈",
                        "counterpart_relation": "아들",
                        "report_title": "가족이 직접 나눈 통화",
                        "call_type": "direct",
                        "started_at": "2026-08-13T16:00:00+09:00",
                        "ended_at": "2026-08-13T16:04:00+09:00",
                        "duration_sec": 240,
                        "status": "ended",
                    })
                    conn.commit()

                calls = report.recent("elder_001", 10)
            gc.collect()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["call_type"], "direct")

    def test_recent_can_be_scoped_to_one_selected_day(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database = Path(directory) / "recent-day.sqlite"
            with patch.object(db, "DB_PATH", database):
                with db.connect() as conn:
                    db.init_schema(conn)
                    db.insert(conn, "elder_profiles", {
                        "elder_id": "elder_001",
                        "name": "고길동",
                    })
                    for call_id, started_at in (
                        ("call_july", "2026-07-07T09:00:00+09:00"),
                        ("call_august", "2026-08-08T09:00:00+09:00"),
                    ):
                        db.insert(conn, "calls", {
                            "call_id": call_id,
                            "elder_id": "elder_001",
                            "call_type": "ai",
                            "started_at": started_at,
                            "ended_at": started_at,
                            "duration_sec": 30,
                            "status": "ended",
                        })
                    conn.commit()

                calls = report.recent(
                    "elder_001", 120, on_date="2026-07-07"
                )
            gc.collect()

        self.assertEqual([row["call_id"] for row in calls], ["call_july"])


if __name__ == "__main__":
    unittest.main()
