import gc
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import invites  # noqa: E402
import push_notifications  # noqa: E402


class PushNotificationTest(unittest.TestCase):
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
            conn.commit()
        invites.register_device(
            "device_guardian", "elder_test", "guardian", "persona_guardian", "갤럭시",
        )

    def tearDown(self):
        db.DB_PATH = self.original_path
        gc.collect()
        self.temp.cleanup()

    def test_subscription_is_saved_only_for_a_guardian_device(self):
        result = push_notifications.save(
            "device_guardian", "https://push.example/subscription", "public-key", "auth-key",
        )
        self.assertTrue(result["enabled"])
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM push_subscriptions").fetchone()
        self.assertEqual(row["device_id"], "device_guardian")
        self.assertEqual(row["p256dh"], "public-key")

    def test_risk_invite_sends_an_urgent_payload(self):
        push_notifications.save(
            "device_guardian", "https://push.example/subscription", "public-key", "auth-key",
        )
        sent = []

        def capture(**kwargs):
            sent.append(kwargs)

        with (
            patch.object(push_notifications, "webpush", capture),
            patch.dict("os.environ", {
                "WEB_PUSH_VAPID_PUBLIC_KEY": "browser-key",
                "WEB_PUSH_VAPID_PRIVATE_KEY": "server-key",
                "WEB_PUSH_CONTACT": "mailto:test@example.com",
            }, clear=False),
        ):
            result = push_notifications.send_invite({
                "invite_id": "invite_risk",
                "persona_id": "persona_guardian",
                "purpose": "risk",
                "alert_evidence": "가스 냄새가 난다고 말씀하셨어요.",
            })

        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(sent), 1)
        self.assertIn('"kind": "risk"', sent[0]["data"])
        self.assertIn('"urgent": true', sent[0]["data"])
        self.assertEqual(sent[0]["ttl"], 300)

    def test_missing_push_dependency_keeps_foreground_polling_available(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(push_notifications, "webpush", None),
            patch.object(push_notifications, "Vapid", None),
            patch.object(push_notifications, "serialization", None),
        ):
            push_notifications._generated_material.cache_clear()
            result = push_notifications.send_invite({
                "invite_id": "invite_family",
                "persona_id": "persona_guardian",
                "purpose": "family",
            })
            push_notifications._generated_material.cache_clear()
        self.assertFalse(result["configured"])
        self.assertEqual(result["sent"], 0)


if __name__ == "__main__":
    unittest.main()
