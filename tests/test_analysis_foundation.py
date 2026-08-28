import sys
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
from analysis import rates  # noqa: E402
from analysis.observation_catalog import DOMAIN_LABELS, SIGNALS, find_evidence  # noqa: E402


class EightDomainObservationTest(unittest.TestCase):
    def test_catalog_has_all_eight_domains(self):
        self.assertEqual(len(DOMAIN_LABELS), 8)

    def test_direct_signals_are_canonicalized(self):
        result = care.normalize({}, user_text="여기가 어디냐? 오늘 아침을 먹었는지 모르겠다.", ctx={})
        by_signal = {row["signal"]: row for row in result["observations"]}
        self.assertEqual(by_signal["place_confusion"]["domain"], "orientation")
        self.assertEqual(by_signal["meal_uncertain"]["domain"], "daily_living")
        self.assertEqual(by_signal["place_confusion"]["verification"], "confirmed")

    def test_safety_risk_and_d8_share_one_definition(self):
        result = care.normalize({}, user_text="넘어져서 허리가 아프고 일어나기 힘들다.", ctx={})
        signals = {row["signal"] for row in result["observations"]}
        self.assertIn("fall_reported", signals)
        self.assertIn("pain_report", signals)

    def test_registered_observation_scenarios_respect_positive_and_negative_examples(self):
        scenarios = json.loads((ROOT / "tools" / "observation_scenarios.json").read_text(encoding="utf-8"))
        for row in scenarios:
            with self.subTest(row=row["id"], kind="positive"):
                self.assertIsNotNone(find_evidence(row["signal"], row["positive"]))
            with self.subTest(row=row["id"], kind="negative"):
                self.assertIsNone(find_evidence(row["signal"], row["negative"]))

    def test_tier_a_catalog_can_be_audited_pairwise(self):
        tier_a = [signal for signal, spec in SIGNALS.items() if spec.tier == "A"]
        scenarios = json.loads((ROOT / "tools" / "observation_scenarios.json").read_text(encoding="utf-8"))
        matrix = {
            row["id"]: [signal for signal in tier_a if find_evidence(signal, row["positive"])]
            for row in scenarios
        }
        self.assertIn("meal_uncertain", matrix["O12"])


class NormalizedRateTest(unittest.TestCase):
    def test_rates_use_declared_denominators(self):
        result = rates.window_rates(calls=20, elder_utterances=100, observations=12, repeats=10, risks=2)
        self.assertEqual(result["observation_per_100_utterances"], 12)
        self.assertEqual(result["repeat_per_call"], 0.5)
        self.assertEqual(result["risk_per_100_calls"], 10)

    def test_small_sample_is_not_called_change(self):
        result = rates.compare(2, 1, label="반복", unit="회/통화", current_sample=3,
                               previous_sample=5, minimum_sample=10)
        self.assertEqual(result["status"], "insufficient_sample")


if __name__ == "__main__":
    unittest.main()
