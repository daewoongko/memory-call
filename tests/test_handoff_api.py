import gc
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import db  # noqa: E402
import invites  # noqa: E402


class HandoffApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "memory.sqlite"
        with db.connect() as conn:
            db.init_schema(conn)
            db.insert(conn, "elder_profiles", {"elder_id": "elder_test", "name": "고길동"})
            db.insert(conn, "personas", {
                "persona_id": "persona_guardian", "elder_id": "elder_test",
                "display_name": "대웅", "relationship_type": "손자",
            })
            db.insert(conn, "calls", {
                "call_id": "call_active_1", "elder_id": "elder_test",
                "persona_id": "persona_guardian", "call_type": "ai",
                "started_at": "2026-08-28T09:04:00+09:00", "status": "active",
            })
            conn.commit()
        invites.register_device(
            "device_guardian", "elder_test", "guardian", "persona_guardian", "갤럭시",
        )
        api.SESSIONS["call_active_1"] = SimpleNamespace(
            call_id="call_active_1", elder_id="elder_test",
            persona_id="persona_guardian", _started=1.0,
        )
        self.client = TestClient(api.app)

    def tearDown(self):
        api.SESSIONS.pop("call_active_1", None)
        db.DB_PATH = self.original_path
        gc.collect()
        self.temp.cleanup()

    def test_guardian_handoff_waits_for_explicit_transport_confirmation(self):
        active = self.client.get(
            "/api/calls/active?elder_id=elder_test&persona_id=persona_guardian"
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["call"]["call_id"], "call_active_1")

        requested = self.client.post("/api/calls/call_active_1/handoff", json={
            "device_id": "device_guardian", "persona_id": "persona_guardian",
        })
        self.assertEqual(requested.status_code, 200)
        invite = requested.json()
        self.assertEqual(invite["state"], "answered")
        self.assertEqual(invite["purpose"], "handoff")

        with db.connect() as conn:
            before = conn.execute(
                "SELECT call_type FROM calls WHERE call_id = 'call_active_1'"
            ).fetchone()["call_type"]
        self.assertEqual(before, "ai")

        confirmed = self.client.post(
            "/api/calls/call_active_1/human-connected",
            json={"invite_id": invite["invite_id"]},
        )
        self.assertEqual(confirmed.status_code, 200)
        with db.connect() as conn:
            after = conn.execute(
                "SELECT call_type FROM calls WHERE call_id = 'call_active_1'"
            ).fetchone()["call_type"]
        self.assertEqual(after, "ai_to_direct")


if __name__ == "__main__":
    unittest.main()
