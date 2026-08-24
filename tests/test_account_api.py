import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import db  # noqa: E402


class AccountApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "account-api.sqlite"
        )
        self.db_patch.start()
        with db.connect() as conn:
            db.init_schema(conn)
        self.client = TestClient(api.app)

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_authenticated_role_progress_and_consent_round_trip(self):
        registered = self.client.post("/api/auth/register", json={
            "phone": "01012345678", "display_name": "정훈", "pin": "123456",
        })
        self.assertEqual(registered.status_code, 200)
        token = registered.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        initial = self.client.get("/api/onboarding/child", headers=headers)
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["complete"])

        saved = self.client.patch("/api/onboarding/child", headers=headers, json={
            "current_step": "connection",
            "data": {"relationship": "아들"},
            "complete": False,
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["data"]["relationship"], "아들")

        consent = self.client.post("/api/consents", headers=headers, json={
            "role": "child",
            "consent_types": ["basic_profile", "call_recording"],
            "consent_version": "2026-08-24.v1",
            "consent_mode": "self",
            "elder_id": "elder_001",
        })
        self.assertEqual(consent.status_code, 200)
        self.assertEqual(len(consent.json()["consents"]), 2)

    def test_onboarding_rejects_missing_or_invalid_session(self):
        response = self.client.get("/api/onboarding/elder")
        self.assertEqual(response.status_code, 401)
        self.assertIn("로그인", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
