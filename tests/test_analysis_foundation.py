import sys
import json
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
from analysis import medication, rates  # noqa: E402
from analysis.observation_catalog import DOMAIN_LABELS, SIGNALS, find_evidence  # noqa: E402


class EightDomainObservationTest(unittest.TestCase):
    def test_catalog_has_all_eight_domains(self):
        self.assertEqual(len(DOMAIN_LABELS), 8)

    def test_direct_signals_are_canonicalized(self):
        result = care.normalize({}, user_text="여기가 어디냐? 약을 먹었는지 모르겠다.", ctx={})
        by_signal = {row["signal"]: row for row in result["observations"]}
        self.assertEqual(by_signal["place_confusion"]["domain"], "orientation")
        self.assertEqual(by_signal["medication_uncertain"]["domain"], "daily_living")
        self.assertEqual(by_signal["place_confusion"]["verification"], "confirmed")

    def test_negated_known_medication_state_is_not_confusion(self):
        result = care.normalize({}, user_text="약은 아직 안 먹었다.", ctx={})
        self.assertNotIn("medication_uncertain", {row["signal"] for row in result["observations"]})

    def test_safety_risk_and_d8_share_one_definition(self):
        result = care.normalize({}, user_text="넘어져서 허리가 아프고 일어나기 힘들다.", ctx={})
        signals = {row["signal"] for row in result["observations"]}
        self.assertIn("fall_reported", signals)
        self.assertIn("pain_report", signals)

    def test_meal_and_medication_uncertainty_do_not_collide(self):
        medication_text = "아침 약을 먹었나? 약을 먹었는지 기억이 안 난다."
        meal_text = "아침밥을 먹었는지 기억이 안 난다."
        self.assertIsNone(find_evidence("meal_uncertain", medication_text))
        self.assertIsNotNone(find_evidence("medication_uncertain", medication_text))
        self.assertIsNotNone(find_evidence("meal_uncertain", meal_text))
        self.assertIsNone(find_evidence("medication_uncertain", meal_text))

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
        self.assertIn("medication_uncertain", matrix["O13"])
        self.assertNotIn("meal_uncertain", matrix["O13"])
        self.assertIn("meal_uncertain", matrix["O12"])
        self.assertNotIn("medication_uncertain", matrix["O12"])


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


class MedicationAnalysisTest(unittest.TestCase):
    def test_four_states_and_registered_signal_match_stay_separate(self):
        meds = [{
            "schedule_id": "med_1", "medication_name": "저녁약", "scheduled_time": "20:00",
            "review_interval_days": 14, "monitoring_points": ["어지럼"],
            "escalation_criteria": "낙상 시 의료진 보고",
        }]
        logs = [
            {"schedule_id": "med_1", "taken_date": "2026-08-10", "status": status}
            for status in medication.STATUSES
        ]
        result = medication.build(
            medications=meds, logs=logs, previous_logs=[], reviews=[],
            links=[{"schedule_id": "med_1", "signal": "dizziness", "link_level": "monitoring", "criterion_text": "어지럼 표현"}],
            reports=[{"call_id": "c1", "care_summary": {"safety_physical": [{"signal": "dizziness", "utterance_id": 1, "evidence": "어지럽다"}]}}],
            period_start=date(2026, 8, 10), period_end=date(2026, 8, 10),
        )
        self.assertEqual(result["status_counts"], {status: 1 for status in medication.STATUSES})
        self.assertEqual(result["registered_signal_matches"][0]["signal"], "dizziness")
        self.assertIn("약 변경", result["safety_notice"])


if __name__ == "__main__":
    unittest.main()
