from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from aihub71415_paired_flux_lora import (  # noqa: E402
    build_caption,
    selected_transitions,
)


class PairedAgeLoraPolicyTests(unittest.TestCase):
    def test_child_transition_set_keeps_only_childhood_stages(self):
        transitions = selected_transitions("child")

        self.assertEqual([item.source_anchor for item in transitions], [20, 15, 11])
        self.assertEqual([item.target_anchor for item in transitions], [15, 11, 8])

    def test_caption_conditions_on_actual_ages_and_gap(self):
        caption = build_caption(12, 8)

        self.assertIn("source age 12", caption)
        self.assertIn("target age 8", caption)
        self.assertIn("regress age by 4 years", caption)
        self.assertIn("elementary-school child", caption)
        self.assertIn("rather than only smoothing skin", caption)

    def test_unknown_transition_set_is_rejected(self):
        with self.assertRaises(ValueError):
            selected_transitions("unknown")


if __name__ == "__main__":
    unittest.main()
