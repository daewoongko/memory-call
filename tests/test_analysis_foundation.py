import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
from analysis import medication, rates  # noqa: E402
from analysis.observation_catalog import DOMAIN_LABELS  # noqa: E402


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
