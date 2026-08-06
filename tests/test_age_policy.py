from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_policy import (  # noqa: E402
    age_range,
    identity_thresholds,
    initial_path,
    path_with_refinements,
    planned_stages,
    split_segment,
    stage_policy,
)


class AgePolicyTests(unittest.TestCase):
    def test_age_32_path(self):
        self.assertEqual(
            initial_path(32),
            [32, 29, 26, 23, 20, 17, 15, 13, 11, 9, 8],
        )

    def test_age_45_path(self):
        self.assertEqual(
            initial_path(45),
            [45, 40, 35, 32, 29, 26, 23, 20, 17, 15, 13, 11, 9, 8],
        )

    def test_failed_segment_can_be_split(self):
        self.assertEqual(split_segment(32, 26), 29)

    def test_two_year_segment_pauses_instead_of_splitting(self):
        with self.assertRaises(ValueError):
            split_segment(26, 24)

    def test_three_year_segment_is_below_model_resolution(self):
        with self.assertRaises(ValueError):
            split_segment(26, 23)

    def test_age_ranges_are_not_exact_single_years(self):
        self.assertEqual(age_range(8), {"min": 7, "max": 10})
        self.assertEqual(age_range(16), {"min": 14, "max": 18})
        self.assertEqual(age_range(29), {"min": 27, "max": 31})
        self.assertEqual(
            stage_policy(32, 15, 17)["allowed_apparent_age"],
            {"min": 13, "max": 16},
        )

    def test_current_identity_gates_relax_across_development(self):
        expected = {
            31: (0.82, 0.86),
            26: (0.78, 0.82),
            20: (0.72, 0.76),
            17: (0.72, 0.76),
            15: (0.68, 0.68),
            13: (0.64, 0.64),
            11: (0.64, 0.64),
            9: (0.60, 0.60),
            8: (0.60, 0.60),
        }
        for target_age, (mean_gate, primary_gate) in expected.items():
            with self.subTest(target_age=target_age):
                gates = identity_thresholds(32, target_age)
                self.assertEqual(gates["current_reference_mean"], mean_gate)
                self.assertEqual(gates["current_primary"], primary_gate)

    def test_adjacent_parent_gate_does_not_relax_in_childhood(self):
        for target_age in (17, 15, 13, 11, 9, 8):
            with self.subTest(target_age=target_age):
                self.assertEqual(
                    identity_thresholds(32, target_age)["adjacent_parent"],
                    0.88,
                )

    def test_stages_are_chronological_for_ui(self):
        stages = planned_stages(32)
        self.assertEqual(stages[0]["age"], 8)
        self.assertEqual(stages[-1]["age"], 32)
        self.assertEqual(stages[-1]["kind"], "current")
        generated = [stage for stage in stages if stage["kind"] == "generated"]
        self.assertTrue(all(stage["policy"] for stage in generated))


if __name__ == "__main__":
    unittest.main()
