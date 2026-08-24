import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import accounts
import db


class AccountFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "accounts.sqlite"
        )
        self.path_patch.start()
        with db.connect() as conn:
            db.init_schema(conn)

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def test_register_login_and_expiring_session(self):
        created = accounts.register("010-1234-5678", "정훈", "123456")
        self.assertNotIn("pin_hash", created["user"])
        self.assertEqual(created["user"]["phone"], "01012345678")
        self.assertEqual(
            accounts.authenticate(created["token"])["user_id"],
            created["user"]["user_id"],
        )

        signed_in = accounts.login("01012345678", "123456")
        self.assertEqual(signed_in["user"]["display_name"], "정훈")
        accounts.logout(signed_in["token"])
        with self.assertRaisesRegex(ValueError, "만료"):
            accounts.authenticate(signed_in["token"])

    def test_wrong_pin_and_duplicate_phone_are_rejected(self):
        accounts.register("01012345678", "정훈", "123456")
        with self.assertRaisesRegex(ValueError, "이미 가입"):
            accounts.register("010-1234-5678", "다른 이름", "654321")
        with self.assertRaisesRegex(ValueError, "맞지 않아요"):
            accounts.login("01012345678", "654321")

    def test_onboarding_merges_progress_and_resumes(self):
        registered = accounts.register("01011112222", "미영", "123456")
        user_id = registered["user"]["user_id"]
        first = accounts.save_onboarding(
            user_id, "child", "relationship", {"elder_id": "elder_001"}
        )
        self.assertFalse(first["complete"])
        resumed = accounts.save_onboarding(
            user_id, "child", "voice", {"relationship": "딸"}
        )
        self.assertEqual(resumed["data"]["elder_id"], "elder_001")
        self.assertEqual(resumed["data"]["relationship"], "딸")

        completed = accounts.save_onboarding(
            user_id, "child", "complete", {"persona_id": "persona_miyeong"}, True
        )
        self.assertTrue(completed["complete"])
        self.assertIsNotNone(completed["completed_at"])

    def test_consent_versions_and_modes_are_recorded_separately(self):
        registered = accounts.register("01033334444", "고길동", "123456")
        user_id = registered["user"]["user_id"]
        rows = accounts.record_consents(
            user_id,
            "elder",
            ["basic_profile", "call_recording", "sensitive_care"],
            "2026-08-24.v1",
            "with_guardian",
            "elder_001",
        )
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["consent_mode"] == "with_guardian" for row in rows))
        self.assertTrue(all(row["consent_version"] == "2026-08-24.v1" for row in rows))

        accounts.record_consents(
            user_id, "elder", ["call_recording"], "2026-09-01.v2",
            "legal_representative", "elder_001"
        )
        active = accounts.consents(user_id, "elder")
        recording = [row for row in active if row["consent_type"] == "call_recording"]
        self.assertEqual(len(recording), 1)
        self.assertEqual(recording[0]["consent_version"], "2026-09-01.v2")


if __name__ == "__main__":
    unittest.main()
