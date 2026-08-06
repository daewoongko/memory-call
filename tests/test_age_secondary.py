from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_secondary import (
    combine_age_evidence,
    summarize_continuous_age_estimates,
    summarize_mivolo_row,
    summarize_person_offset_advisory,
)


class AgeSecondaryTests(unittest.TestCase):
    def test_person_offset_is_advisory_and_raw_output_drives_gate(self):
        row = {"estimates": [25.81, 26.13, 26.21, 26.41, 28.72]}
        limits = {"min": 24, "max": 28}
        calibration = {"bias_years": -5.06}

        raw = summarize_mivolo_row(row, limits)
        corrected = summarize_person_offset_advisory(row, calibration, limits)

        self.assertEqual(raw["median"], 26.21)
        self.assertEqual(raw["target_range_vote_share"], 0.8)
        self.assertTrue(raw["range_pass"])
        self.assertTrue(raw["used_as_hard_gate"])
        self.assertEqual(corrected["median"], 31.27)
        self.assertFalse(corrected["range_pass"])
        self.assertEqual(corrected["status"], "advisory_only")
        self.assertFalse(corrected["used_as_hard_gate"])

    def test_continuous_summary_requires_center_and_vote_share(self):
        limits = {"min": 24, "max": 28}
        passed = summarize_continuous_age_estimates(
            [25.1, 25.7, 26.0, 26.4, 27.2], limits
        )
        failed = summarize_continuous_age_estimates(
            [27.9, 28.1, 28.2, 28.4, 28.8], limits
        )
        self.assertTrue(passed["range_pass"])
        self.assertFalse(failed["range_pass"])
        self.assertTrue(failed["mae_interval_overlaps_target"])
        self.assertIn("not_calibrated_confidence", failed["uncertainty_kind"])

    def test_two_models_must_agree_for_auto_pass(self):
        relative = {"younger_direction": True}
        primary = {"range_pass": True, "review_status": "strong_pass"}
        secondary = {"range_pass": True, "review_status": "strong_pass"}
        result = combine_age_evidence(primary, secondary, relative)
        self.assertTrue(result["automated_pass"])
        self.assertTrue(result["model_agreement"])

    def test_disagreement_requires_human_review(self):
        relative = {"younger_direction": True}
        primary = {"range_pass": False, "review_status": "fail"}
        secondary = {"range_pass": True, "review_status": "strong_pass"}
        result = combine_age_evidence(primary, secondary, relative)
        self.assertFalse(result["automated_pass"])
        self.assertEqual(result["review_status"], "human_review")
        self.assertFalse(result["model_agreement"])

    def test_missing_secondary_keeps_explicit_degraded_mode(self):
        primary = {"range_pass": True, "review_status": "borderline"}
        result = combine_age_evidence(primary, None, {"younger_direction": True})
        self.assertTrue(result["automated_pass"])
        self.assertFalse(result["secondary_available"])
        self.assertIn("degraded_mode", result["reason"])


if __name__ == "__main__":
    unittest.main()
