from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_biology import (  # noqa: E402
    apply_personal_age_bias,
    assess_younger_structure,
    calibrate_personal_age_bias,
    relative_age_evidence,
    structure_metrics,
    summarize_age_votes,
)


class AgeBiologyTests(unittest.TestCase):
    def test_vote_summary_distinguishes_strong_borderline_and_fail(self):
        limits = {"min": 24, "max": 28}
        strong = summarize_age_votes([25, 26, 26, 27, 27], limits)
        borderline = summarize_age_votes([27, 28, 28, 28, 29], limits)
        failed = summarize_age_votes([28, 29, 29, 29, 30], limits)
        self.assertEqual(strong["review_status"], "strong_pass")
        self.assertEqual(borderline["review_status"], "borderline")
        self.assertEqual(failed["review_status"], "fail")
        self.assertFalse(failed["range_pass"])

    def test_structure_metrics_are_scale_invariant(self):
        first = structure_metrics(
            [0, 0, 100, 120],
            [[30, 40], [70, 40], [50, 65], [35, 85], [65, 85]],
        )
        second = structure_metrics(
            [0, 0, 200, 240],
            [[60, 80], [140, 80], [100, 130], [70, 170], [130, 170]],
        )
        self.assertEqual(first, second)

    def test_growth_direction_is_advisory(self):
        parent = {
            "face_width_height": 0.80,
            "inter_eye_ratio": 0.35,
            "mouth_width_ratio": 0.30,
            "eye_to_mouth_ratio": 0.40,
            "eye_to_chin_ratio": 0.68,
            "nose_to_mouth_ratio": 0.16,
        }
        candidate = dict(parent)
        candidate.update(
            face_width_height=0.83,
            inter_eye_ratio=0.37,
            eye_to_mouth_ratio=0.38,
            eye_to_chin_ratio=0.65,
        )
        result = assess_younger_structure(parent, candidate, 17, 15)
        self.assertEqual(result["score"], 1.0)
        self.assertFalse(result["calibrated"])
        self.assertEqual(result["status"], "advisory_only")

    def test_personal_bias_uses_real_reference_median(self):
        calibration = calibrate_personal_age_bias([34, 35, 33, 34, 36], 32)
        self.assertEqual(calibration["bias_years"], 2.0)
        self.assertEqual(apply_personal_age_bias(29, calibration), 27.0)
        self.assertFalse(calibration["calibrated_probability"])

    def test_relative_age_evidence_uses_parent_candidate_delta(self):
        evidence = relative_age_evidence(30, 29, 29, 26)
        self.assertEqual(evidence["observed_delta_years"], -1.0)
        self.assertEqual(evidence["expected_delta_years"], -3.0)
        self.assertEqual(evidence["status"], "expected_within_tolerance")
        self.assertFalse(evidence["used_as_hard_gate"])


if __name__ == "__main__":
    unittest.main()
