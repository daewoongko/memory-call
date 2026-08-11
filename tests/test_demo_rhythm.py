import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")

import seed_high_volume_demo as demo  # noqa: E402


class HighVolumeDemoRhythmTest(unittest.TestCase):
    def test_only_explicit_rare_slots_use_safety_templates(self):
        risk_indices = set(demo.RARE_RISK_CALLS.values())
        self.assertFalse(risk_indices.intersection(demo.MORNING_ROTATION))
        self.assertFalse(risk_indices.intersection(demo.DAY_ROTATION))
        self.assertFalse(risk_indices.intersection(demo.EVENING_ROTATION))
        self.assertEqual(len(demo.RARE_RISK_CALLS), 8)

        detected = {
            demo.safety._direct_risk(demo.TEMPLATES[index]["user"])["type"]
            for index in risk_indices
        }
        self.assertEqual(detected, {
            "fall", "lost", "overdose", "intrusion", "fire",
            "breathing", "chest_pain", "gas_leak",
        })

    def test_past_calls_are_concentrated_in_evening_window(self):
        now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        calls = [demo._call_time(now, 3, index, 40) for index in range(40)]
        evening = sum(1 for started in calls if 18 <= started.hour < 20)
        morning = sum(1 for started in calls if 7 <= started.hour < 10)
        self.assertGreater(evening, morning)

    def test_recent_evening_calls_include_grounded_loneliness_examples(self):
        started = datetime(2026, 8, 11, 18, 20, tzinfo=timezone.utc)
        selected = {
            demo._template_index(2, index, started)
            for index in range(16)
        }
        self.assertIn(6, selected)

    def test_repetition_is_common_but_not_forced_into_every_call(self):
        counts = [demo._repeat_count(0, 3, index) for index in range(40)]
        self.assertIn(4, counts)
        self.assertGreater(counts.count(1), counts.count(4))

        safety_counts = [
            demo._repeat_count(template_index, days_ago, index)
            for (days_ago, index), template_index in demo.RARE_RISK_CALLS.items()
        ]
        self.assertEqual(safety_counts, [1] * len(safety_counts))


if __name__ == "__main__":
    unittest.main()
