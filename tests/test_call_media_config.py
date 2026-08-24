import base64
import hashlib
import hmac
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402


class CallMediaConfigTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_stun_is_available_without_turn_account(self):
        with patch.dict(
            "os.environ",
            {"TURN_URLS": "", "TURN_SHARED_SECRET": "", "TURN_USERNAME": "", "TURN_CREDENTIAL": ""},
        ):
            result = self.client.get("/api/call-media-config").json()
        self.assertFalse(result["turn_configured"])
        self.assertEqual(len(result["ice_servers"]), 1)
        self.assertTrue(result["ice_servers"][0]["urls"])

    def test_coturn_shared_secret_creates_temporary_credentials(self):
        with patch.dict(
            "os.environ",
            {
                "TURN_URLS": "turn:turn.example.com:3478,turns:turn.example.com:5349",
                "TURN_SHARED_SECRET": "server-only-secret",
                "TURN_TTL_SECONDS": "600",
                "TURN_USERNAME": "",
                "TURN_CREDENTIAL": "",
            },
        ):
            result = self.client.get("/api/call-media-config").json()
        self.assertTrue(result["turn_configured"])
        relay = result["ice_servers"][1]
        expected = base64.b64encode(
            hmac.new(
                b"server-only-secret",
                relay["username"].encode(),
                hashlib.sha1,
            ).digest()
        ).decode()
        self.assertEqual(relay["credential"], expected)
        self.assertEqual(len(relay["urls"]), 2)


if __name__ == "__main__":
    unittest.main()
