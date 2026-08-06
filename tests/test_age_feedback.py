from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_feedback import generation_controls  # noqa: E402


OLD_ROWS = [
    {"estimated_age": 30, "identity_pass": True},
    {"estimated_age": 29, "identity_pass": True},
    {"estimated_age": 29, "identity_pass": True},
    {"estimated_age": 29, "identity_pass": True},
]


class AgeFeedbackTests(unittest.TestCase):
    def test_initial_age_29_to_26_controls(self):
        result = generation_controls(parent_age=29, target_age=26, attempt=1)
        self.assertEqual(result["control_age"], 26)
        self.assertEqual(result["edit_strength"], 0.40)
        self.assertEqual(result["lora_scale"], 0.80)
        self.assertEqual(result["reference_count"], 5)

    def test_first_old_retry_uses_compensated_control_age(self):
        result = generation_controls(
            parent_age=29,
            target_age=26,
            attempt=2,
            previous_rows=OLD_ROWS,
        )
        self.assertEqual(result["control_age"], 23)
        self.assertEqual(result["edit_strength"], 0.48)
        self.assertEqual(result["lora_scale"], 0.72)
        self.assertEqual(result["reference_count"], 3)

    def test_second_old_retry_is_stronger_but_bounded(self):
        result = generation_controls(
            parent_age=29,
            target_age=26,
            attempt=3,
            previous_rows=OLD_ROWS,
        )
        self.assertEqual(result["control_age"], 22)
        self.assertEqual(result["edit_strength"], 0.54)
        self.assertEqual(result["lora_scale"], 0.68)

    def test_fourth_attempt_is_explicit_structural_rescue(self):
        rows = [
            {
                "estimated_age": 29,
                "insightface_age_estimation": {"median": 29.0},
                "mivolo_raw_age_estimation": {
                    "status": "available",
                    "age_basis": "raw_model_output",
                    "median": 27.4,
                },
                "identity_pass": True,
            }
        ]

        result = generation_controls(
            parent_age=26,
            target_age=24,
            attempt=4,
            previous_rows=rows,
        )

        self.assertEqual(result["control_age"], 18)
        self.assertEqual(result["edit_strength"], 0.56)
        self.assertEqual(result["lora_scale"], 0.64)
        self.assertEqual(result["reference_count"], 3)
        self.assertEqual(result["reason"], "age_too_old_retry_3")

    def test_identity_failure_backs_off_age_edit(self):
        rows = [
            {"estimated_age": 28, "identity_pass": False},
            {"estimated_age": 27, "identity_pass": False},
            {"estimated_age": 26, "identity_pass": True},
        ]
        result = generation_controls(
            parent_age=29,
            target_age=26,
            attempt=2,
            previous_rows=rows,
        )
        self.assertEqual(result["reason"], "identity_recovery_backoff")
        self.assertEqual(result["control_age"], 26)
        self.assertEqual(result["lora_scale"], 0.84)
        self.assertEqual(result["reference_count"], 5)

    def test_retry_uses_raw_models_and_ignores_person_offset_advisory(self):
        rows = [
            {
                "estimated_age": 29,
                "corrected_estimated_age": 30.0,
                "insightface_age_estimation": {"median": 28.0},
                "mivolo_raw_age_estimation": {
                    "status": "available",
                    "age_basis": "raw_model_output",
                    "median": 26.2,
                },
                "mivolo_age_estimation": {
                    "status": "available",
                    "age_basis": "raw_model_output",
                    "median": 26.2,
                },
                "mivolo_corrected_age_estimation": {
                    "status": "advisory_only",
                    "median": 31.3,
                    "used_as_hard_gate": False,
                },
                "identity_pass": True,
            }
        ]
        result = generation_controls(
            parent_age=29,
            target_age=26,
            attempt=2,
            previous_rows=rows,
        )
        self.assertEqual(result["control_age"], 25)
        self.assertEqual(result["feedback"]["observed_age"], 27.1)
        self.assertEqual(
            result["feedback"]["age_signals"]["mivolo_raw"], 26.2
        )
        self.assertNotIn(
            "mivolo_corrected", result["feedback"]["age_signals"]
        )


if __name__ == "__main__":
    unittest.main()
