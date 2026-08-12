import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")

import db  # noqa: E402


class DemoPersonaMigrationTest(unittest.TestCase):
    def test_legacy_family_is_merged_without_losing_call_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with patch.object(db, "connect", return_value=conn):
            db.init_schema(conn)
        conn.execute(
            "INSERT INTO elder_profiles (elder_id, name) VALUES ('elder_001', '고길동')"
        )
        conn.execute(
            "INSERT INTO personas (persona_id, elder_id, display_name, relationship_type) "
            "VALUES ('persona_minsu', 'elder_001', '민수', '아들')"
        )
        conn.execute(
            "INSERT INTO calls (call_id, elder_id, persona_id, counterpart_name, "
            "counterpart_relation) VALUES ('legacy-call', 'elder_001', "
            "'persona_minsu', '민수', '아들')"
        )

        db._migrate_demo_personas(conn)

        persona = conn.execute(
            "SELECT persona_id, display_name FROM personas"
        ).fetchone()
        call = conn.execute(
            "SELECT persona_id, counterpart_name FROM calls WHERE call_id = 'legacy-call'"
        ).fetchone()
        self.assertEqual(tuple(persona), ("persona_jeonghun", "정훈"))
        self.assertEqual(tuple(call), ("persona_jeonghun", "정훈"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
