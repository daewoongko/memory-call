from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_growth import assess_3d_structure, growth_prior, personal_structure_profile


def row(coefficients, metrics=None):
    return {
        "shape_coefficients": coefficients,
        "pose_normalized_metrics": metrics
        or {
            "face_width_height": 1.0,
            "jaw_width_ratio": 0.7,
            "lower_face_ratio": 0.6,
            "midface_ratio": 0.4,
        },
        "pose_degrees": {"yaw": 1.0, "pitch": 2.0, "roll": 1.0},
    }


class AgeGrowthTests(unittest.TestCase):
    def test_growth_prior_is_demographic_but_advisory(self):
        prior = growth_prior(29, 26, "male", "korean")
        self.assertEqual(prior["stage"], "younger_adult_subtle")
        self.assertEqual(prior["population_group"], "korean")
        self.assertFalse(prior["calibrated"])
        self.assertFalse(prior["used_as_hard_gate"])

    def test_personal_profile_uses_real_source_median(self):
        profile = personal_structure_profile(
            [row([0.0, 1.0]), row([0.2, 1.2]), row([0.1, 1.1])]
        )
        self.assertEqual(profile["shape_coefficient_median"], [0.1, 1.1])
        self.assertEqual(profile["reference_count"], 3)

    def test_3d_assessment_never_becomes_hard_gate(self):
        sources = [row([0.0, 1.0]), row([0.1, 1.1]), row([-0.1, 0.9])]
        profile = personal_structure_profile(sources)
        prior = growth_prior(17, 15)
        parent = row([0.0, 1.0])
        candidate = row(
            [0.05, 1.05],
            {
                "face_width_height": 1.02,
                "jaw_width_ratio": 0.68,
                "lower_face_ratio": 0.58,
                "midface_ratio": 0.38,
            },
        )
        result = assess_3d_structure(profile, parent, candidate, prior)
        self.assertEqual(result["growth_direction_score"], 1.0)
        self.assertEqual(result["status"], "advisory_only")
        self.assertFalse(result["used_as_hard_gate"])


if __name__ == "__main__":
    unittest.main()
