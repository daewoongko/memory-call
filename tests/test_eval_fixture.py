"""eval 의 회귀 신호가 벽시계 날짜에 흔들리지 않는지 확인한다.

시드 일정이 과거가 되면 load_context() 가 걸러 버려서, 회귀가 아닌 이유로
S04 같은 시나리오가 실패한다. 고정 컨텍스트는 그것을 막는 장치다.
"""

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
    "display_name": "민준",
    "relationship_type": "손자",
    "elder_calls_family": "우리 민준이",
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

    def test_visit_always_lands_on_a_saturday(self):
        """요일 이름이 불변이어야 시나리오가 날짜를 하드코딩하지 않는다."""
        start = date(2026, 8, 3)  # 월요일
        for offset in range(21):
            today = date.fromordinal(start.toordinal() + offset)
            with self.subTest(today=today.isoformat()):
                visit = self.evaluator.next_saturday(today)
                self.assertEqual(visit.weekday(), 5)
                self.assertGreater(visit, today, "지난 날짜는 프롬프트에서 걸러진다")

    def test_today_saturday_moves_a_full_week(self):
        saturday = date(2026, 8, 8)
        self.assertEqual(saturday.weekday(), 5)
        self.assertEqual(
            self.evaluator.next_saturday(saturday), date(2026, 8, 15)
        )

    def test_pinned_schedule_reaches_the_prompt_as_saturday(self):
        pinned = self.evaluator.pin_context_dates({}, today=date(2026, 8, 7))
        block = persona._schedule_block(
            pinned["schedules"], today=date(2026, 8, 7)
        )

        self.assertIn(self.evaluator.FIXTURE_VISIT_WEEKDAY, block)
        self.assertIn(self.evaluator.FIXTURE_VISIT_ID, block)
        self.assertNotIn(persona.NO_SCHEDULE, block)

    def test_pinning_does_not_mutate_the_original_context(self):
        original = {"schedules": [], "medications": [], "memories": ["keep"]}
        pinned = self.evaluator.pin_context_dates(original, today=date(2026, 8, 7))

        self.assertEqual(original["schedules"], [])
        self.assertEqual(original["medications"], [])
        self.assertEqual(pinned["memories"], ["keep"])
        self.assertTrue(pinned["schedules"])
        self.assertTrue(pinned["medications"])

    def test_fixed_now_keeps_the_visit_three_days_out(self):
        """방문이 "내일" 이 되면 약속을 하기 쉬워져 거짓 약속 회귀를 가린다."""
        pinned_now = self.evaluator.FIXTURE_NOW
        self.assertEqual(pinned_now.weekday(), 2, "수요일이어야 한다")

        visit = self.evaluator.next_saturday(pinned_now.date())
        self.assertEqual((visit - pinned_now.date()).days, 3)

    def test_fixed_now_reaches_the_prompt(self):
        evaluator = self.evaluator
        ctx = evaluator.pin_context_dates(
            {"elder": ELDER, "persona": PERSONA, "memories": []},
            evaluator.FIXTURE_NOW.date(),
        )
        prompt = persona.build_system_prompt(ctx, now=evaluator.FIXTURE_NOW)

        self.assertIn("2026년 05월 13일", prompt)
        self.assertIn("수요일", prompt)
        # 방문은 3일 뒤이므로 "내일"/"모레" 로 렌더되면 안 된다.
        schedule_line = next(
            line for line in prompt.splitlines()
            if evaluator.FIXTURE_VISIT_ID in line
        )
        self.assertIn("토요일", schedule_line)
        self.assertIn("3일 뒤", schedule_line)

    def test_pinned_schedule_id_matches_what_safety_will_accept(self):
        """safety 는 used_schedule_ids 를 ctx 의 일정과 대조한다."""
        pinned = self.evaluator.pin_context_dates({}, today=date(2026, 8, 7))
        valid = {s["schedule_id"] for s in pinned["schedules"]}
        self.assertIn(self.evaluator.FIXTURE_VISIT_ID, valid)

    def test_care_scenario_uses_its_registered_demo_family(self):
        base = self.evaluator.pin_context_dates(
            {"elder": ELDER, "persona": PERSONA, "memories": []},
            self.evaluator.FIXTURE_NOW.date(),
        )
        daughter = self.evaluator.scenario_context(base, "S30")
        son = self.evaluator.scenario_context(base, "S37")

        self.assertEqual((daughter["persona"]["display_name"], daughter["persona"]["relationship_type"]), ("미영", "딸"))
        self.assertEqual((son["persona"]["display_name"], son["persona"]["relationship_type"]), ("정훈", "아들"))
        self.assertEqual(base["persona"]["display_name"], "민준")


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
        """고정 컨텍스트가 만들 수 있는 요일은 '오늘'과 '방문일' 둘뿐이다."""
        allowed = {
            self.evaluator.FIXTURE_VISIT_WEEKDAY,
            persona._weekday_ko(self.evaluator.FIXTURE_NOW.date()),
        }
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
