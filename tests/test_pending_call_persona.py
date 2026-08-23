import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
from storage import DEFAULT_FACE_PERSONA_ID  # noqa: E402


class PendingMedicationCallPersonaTest(unittest.TestCase):
    def test_due_medication_selects_the_designated_dawoong_persona(self):
        with patch.object(api.med_mod, "due", return_value=[{
            "medication_name": "저녁 혈압약",
            "scheduled_time": "20:00",
            "minutes_late": 2,
        }]):
            result = api.pending_call("elder_001")

        self.assertTrue(result["due"])
        self.assertEqual(result["reason"], "medication")
        self.assertEqual(result["persona_id"], DEFAULT_FACE_PERSONA_ID)

    def test_no_due_medication_has_no_caller_persona(self):
        with patch.object(api.med_mod, "due", return_value=[]):
            result = api.pending_call("elder_001")

        self.assertFalse(result["due"])
        self.assertIsNone(result["reason"])
        self.assertIsNone(result["persona_id"])


if __name__ == "__main__":
    unittest.main()
