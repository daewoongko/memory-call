from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import persona  # noqa: E402


class CallStyleMigrationTests(unittest.TestCase):
    def test_existing_persona_table_gains_call_and_avatar_style_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE personas (persona_id TEXT PRIMARY KEY)")

        added = db._add_missing_columns(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(personas)")}

        self.assertTrue({
            "call_style_code", "call_style_name", "call_style_scores", "call_style_answers",
            "avatar_performance_style",
        }.issubset(columns))
        self.assertEqual(len([name for name in added if name.startswith("personas.")]), 5)
        self.assertEqual(db._add_missing_columns(conn), [])
        conn.close()

    def test_call_style_answers_round_trip_as_json(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE personas (persona_id TEXT PRIMARY KEY, call_style_answers TEXT)"
        )
        answers = {"tone_1": "C", "lead_7": "G"}
        db.insert(conn, "personas", {"persona_id": "persona_test", "call_style_answers": answers})
        row = conn.execute("SELECT * FROM personas").fetchone()
        self.assertEqual(db._row(row)["call_style_answers"], answers)
        conn.close()


class CallStylePromptTests(unittest.TestCase):
    def test_saved_style_is_visible_in_persona_prompt_block(self):
        block = persona._persona_block({
            "display_name": "미영", "relationship_type": "딸",
            "elder_calls_family": "우리 미영이", "tone": "차분하게 말한다.",
            "call_style_code": "CEOG", "call_style_name": "안심 케어 내비게이터",
        })
        self.assertIn("CEOG · 안심 케어 내비게이터", block)
        self.assertIn("차분하게 말한다", block)


if __name__ == "__main__":
    unittest.main()
