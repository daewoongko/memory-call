import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from eval_reports import validate_report  # noqa: E402


class ReportExpectationTests(unittest.TestCase):
    def test_direct_evidence_and_guardian_action_pass(self):
        data = {
            "care_summary": {
                "memory_orientation": [{"signal": "place_confusion", "evidence": "집에 가야 한다"}],
                "emotion": [], "daily_living": [],
            },
            "risk_summary": [{"type": "lost", "evidence": "길을 못 찾겠다"}],
            "meaningful_moments": [], "family_mentions": [],
            "guardian_actions": ["현재 장소를 직접 확인해 주세요."],
        }
        expected = {
            "domains": ["memory_orientation"], "signals": ["place_confusion"],
            "risks": ["lost"], "evidence_any": ["길을 못 찾"], "action_any": ["직접 확인"],
        }
        self.assertEqual(validate_report(data, expected, "집에 가야 한다 길을 못 찾겠다"), [])

    def test_invented_evidence_and_missing_action_fail(self):
        data = {
            "care_summary": {
                "memory_orientation": [{"signal": "place_confusion", "evidence": "지금 집에 있다"}],
            },
            "risk_summary": [], "meaningful_moments": [], "family_mentions": [],
            "guardian_actions": [],
        }
        failures = validate_report(data, {
            "domains": ["memory_orientation"], "signals": ["place_confusion"],
            "risks": [], "action_any": ["확인"],
        }, "여기가 어디냐")
        self.assertTrue(any("보호자 확인 행동" in failure for failure in failures))
        self.assertTrue(any("원문에 없는 관찰 근거" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
