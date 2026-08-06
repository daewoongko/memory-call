from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_morph_policy import (  # noqa: E402
    morph_anchor_assessment,
    trajectory_assessment,
    visible_child_structure_assessment,
)


def row(*, identity=True, insight_delta=-2.0, mivolo_delta=-2.5):
    return {
        "identity_pass": identity,
        "face_detection_score": 0.92,
        "relative_age_evidence": {"observed_delta_years": insight_delta},
        "mivolo_relative_age_evidence": {
            "observed_delta_years": mivolo_delta
        },
        "structure_3d": {
            "pose_degrees": {"yaw": 1.0, "pitch": 3.0, "roll": 1.0}
        },
        "age_consensus": {"review_status": "fail"},
        "structure_3d_assessment": {
            "status": "advisory_only",
            "growth_direction_score": 0.5,
        },
    }


class AgeMorphPolicyTests(unittest.TestCase):
    def test_child_anchor_requires_visible_structure_direction(self):
        evidence = {
            "growth_direction_score": 0.75,
            "growth_direction_measurements": [
                {"status": "expected"},
                {"status": "expected"},
                {"status": "stable"},
                {"status": "stable"},
            ],
        }
        result = visible_child_structure_assessment(
            {"structure_3d_assessment": evidence}, 15
        )
        self.assertTrue(result["pass"])

    def test_child_anchor_rejects_texture_only_age_signal(self):
        evidence = {
            "growth_direction_score": 0.625,
            "growth_direction_measurements": [
                {"status": "expected"},
                {"status": "stable"},
                {"status": "stable"},
                {"status": "stable"},
            ],
        }
        result = visible_child_structure_assessment(
            {"structure_3d_assessment": evidence}, 13
        )
        self.assertFalse(result["pass"])

    def test_exact_age_failure_does_not_block_plausible_keyframe(self):
        result = morph_anchor_assessment(row(), 26, 23)
        self.assertTrue(result["eligible_for_human_review"])
        self.assertFalse(result["automatic_approval"])
        self.assertFalse(result["exact_age_evidence"]["used_as_hard_gate"])

    def test_unchanged_face_fails_relative_trajectory(self):
        result = trajectory_assessment(
            row(insight_delta=0.0, mivolo_delta=0.1), 26, 23
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["status"], "insufficient_visible_progress")

    def test_subtle_close_stage_progress_can_reach_human_review(self):
        result = trajectory_assessment(
            row(insight_delta=-0.4, mivolo_delta=-0.2), 26, 23
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["required_mean_progress"], 0.25)

    def test_identity_is_still_a_hard_gate(self):
        result = morph_anchor_assessment(row(identity=False), 26, 23)
        self.assertFalse(result["eligible_for_human_review"])
        self.assertFalse(result["identity_hard_gate"])

    def test_large_age_reversal_is_rejected(self):
        result = trajectory_assessment(
            row(insight_delta=2.0, mivolo_delta=1.5), 26, 23
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["status"], "age_reversal")


if __name__ == "__main__":
    unittest.main()
