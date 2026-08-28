"""eval의 날짜·요일 회귀 신호가 벽시계 날짜에 흔들리지 않는지 확인한다."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import persona  # noqa: E402


# 이 저장소에는 런타임 DB 가 없다. load_context() 를 쓰면 CI 에서 죽으므로
# 프롬프트를 만드는 데 필요한 최소한만 직접 만든다.
ELDER = {
    "name": "고길동",
    "preferred_call_name": "할아버지",
    "residence_type": "자택 (아들 부부와 함께)",
    "household_members": [{"name": "정훈", "relation": "아들"}],
    "anxiety_triggers": ["날짜를 모를 때"],
    "calming_phrases": ["괜찮아."],
    "frequent_questions": ["오늘이 무슨 요일이야?"],
    "hearing_support": True,
}

PERSONA = {
    "display_name": "대웅",
    "relationship_type": "손자",
    "elder_calls_family": "우리 대웅이",
    "family_calls_elder": "할아버지",
    "tone": "다정한 반말",
    "frequent_phrases": ["밥은 먹었어?"],
    "forbidden_phrases": ["걱정 마세요"],
    "sensitive_policy": "먼저 꺼내지 않는다",
}


def load_eval_module():
    path = ROOT / "tools" / "eval.py"
    spec = importlib.util.spec_from_file_location("eval_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class EvalFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = load_eval_module()

    def test_pinning_does_not_mutate_the_original_context(self):
        original = {"memories": ["keep"]}
        pinned = self.evaluator.pin_context_dates(original, today=date(2026, 8, 7))

        self.assertEqual(pinned["memories"], ["keep"])
        self.assertNotIn("schedules", pinned)

    def test_fixed_now_reaches_the_prompt(self):
        evaluator = self.evaluator
        ctx = evaluator.pin_context_dates(
            {"elder": ELDER, "persona": PERSONA, "memories": []},
            evaluator.FIXTURE_NOW.date(),
        )
        prompt = persona.build_system_prompt(ctx, now=evaluator.FIXTURE_NOW)

        self.assertIn("2026년 05월 13일", prompt)
        self.assertIn("수요일", prompt)
        self.assertNotIn("schedule_id", prompt)

    def test_care_scenario_uses_its_registered_demo_family(self):
        base = self.evaluator.pin_context_dates(
            {"elder": ELDER, "persona": PERSONA, "memories": []},
            self.evaluator.FIXTURE_NOW.date(),
        )
        daughter = self.evaluator.scenario_context(base, "S30")
        son = self.evaluator.scenario_context(base, "S37")

        self.assertEqual((daughter["persona"]["display_name"], daughter["persona"]["relationship_type"]), ("미영", "딸"))
        self.assertEqual((son["persona"]["display_name"], son["persona"]["relationship_type"]), ("정훈", "아들"))
        self.assertEqual(base["persona"]["display_name"], "대웅")


class ScenarioContractTests(unittest.TestCase):
    """단언이 고정 컨텍스트와 어긋나면 무슨 답을 해도 통과할 수 없다."""

    @classmethod
    def setUpClass(cls):
        import json

        cls.evaluator = load_eval_module()
        cls.scenarios = json.loads(
            (ROOT / "tools" / "scenarios.json").read_text(encoding="utf-8")
        )

    def _required_patterns(self):
        for scenario in self.scenarios:
            for pattern in scenario["assert"].get("reply_must_match_any", []):
                yield scenario["id"], pattern

    def test_no_scenario_hardcodes_a_calendar_date(self):
        """'8월 2일' 같은 단언은 그 날이 지나면 조용히 깨진다."""
        import re

        calendar_date = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}-\d{2}-\d{2}")
        offenders = [
            f"{sid}: {p}"
            for sid, p in self._required_patterns()
            if calendar_date.search(p)
        ]
        self.assertEqual(offenders, [], "고정 컨텍스트의 요일 이름을 쓰세요")

    def test_only_weekdays_the_fixture_can_produce_are_asserted(self):
        """고정 컨텍스트가 만드는 요일은 오늘뿐이다."""
        allowed = {persona._weekday_ko(self.evaluator.FIXTURE_NOW.date())}
        every_weekday = {f"{day}요일" for day in "월화수목금토일"}

        offenders = [
            f"{sid}: {p}"
            for sid, p in self._required_patterns()
            for weekday in every_weekday - allowed
            if weekday in p
        ]
        self.assertEqual(
            offenders, [], f"고정 컨텍스트가 만드는 요일은 {sorted(allowed)} 뿐입니다"
        )


if __name__ == "__main__":
    unittest.main()
