from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_morph import build_timing, segment_seconds  # noqa: E402


class MorphTimingTests(unittest.TestCase):
    def test_age_weighted_timing_slows_childhood_without_losing_years(self):
        self.assertEqual(
            segment_seconds(8, 12, timing_mode="age-weighted"), 6.0
        )
        self.assertEqual(
            segment_seconds(12, 15, timing_mode="age-weighted"), 3.0
        )

        timing = build_timing(
            [8, 9, 10, 11, 12, 15, 17, 20, 24, 28],
            timing_mode="age-weighted",
        )
        transition_seconds = sum(
            row["duration_seconds"] for row in timing["segments"]
        )
        self.assertEqual(transition_seconds, 22.0)
        self.assertEqual(timing["expected_duration_seconds"], 23.8)

    def test_seconds_per_year_scales_the_weighted_timeline(self):
        self.assertEqual(
            segment_seconds(
                8,
                28,
                timing_mode="age-weighted",
                seconds_per_year=2.0,
            ),
            44.0,
        )


if __name__ == "__main__":
    unittest.main()
