import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import safety  # noqa: E402


CTX = {
    "persona": {"display_name": "민준"},
    "memories": [],
    "schedules": [],
}


class CareSafetyRulesTest(unittest.TestCase):
    def test_present_location_claim_is_replaced(self):
        checked = safety.check(
            {"reply": "거기가 바로 엄마 집 맞아.", "certainty": "none"},
            CTX,
            "여기가 어디냐?",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인할 수 없어", checked.reply)
        self.assertIn(
            "PRESENT_LOCATION_CLAIM",
            [flag["code"] for flag in checked.flags],
        )

        indirect = safety.check(
            {
                "reply": "거기는 할아버지 댁 거실인데 아들 부부랑 같이 지내고 계시잖아.",
                "certainty": "none",
            },
            CTX,
            "집에 가야 하는데 길을 못 찾겠어.",
        )
        self.assertTrue(indirect.rewritten)

    def test_indirect_present_location_claim_is_replaced(self):
        checked = safety.check(
            {
                "reply": "지금은 평소처럼 아들 부부랑 같이 지내는 할아버지 댁에 계신 거야.",
                "certainty": "verified",
            },
            CTX,
            "집에 가야 하는데 길을 못 찾겠어.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("주변에 뭐가 보이는지", checked.reply)

        conditional = safety.check(
            {
                "reply": "지금은 집에서 편하게 쉬고 계시면 돼.",
                "certainty": "none",
            },
            CTX,
            "집 안이 낯설어.",
        )
        self.assertTrue(conditional.rewritten)

    def test_uncertain_medication_never_becomes_take_it_now(self):
        checked = safety.check(
            {"reply": "그럼 지금 약을 드셔.", "certainty": "none"},
            CTX,
            "약을 먹었나 안 먹었나 모르겠어.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("더 드시지 말고", checked.reply)
        self.assertIn(
            "UNCERTAIN_MEDICATION_INSTRUCTION",
            [flag["code"] for flag in checked.flags],
        )

    def test_clock_time_does_not_prove_meal_state(self):
        checked = safety.check(
            {
                "reply": "지금 10시 30분이니까 아직 점심 식사 전이야.",
                "certainty": "verified",
            },
            CTX,
            "점심을 먹었는지 모르겠어.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인할 수 없어", checked.reply)

    def test_unverified_financial_safety_claim_is_replaced(self):
        checked = safety.check(
            {"reply": "아빠 통장은 안전하게 잘 보관되어 있어.", "certainty": "none"},
            CTX,
            "네가 내 통장 가져갔지?",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인할 수 없", checked.reply)
        self.assertIn(
            "UNVERIFIED_FINANCIAL_STATUS",
            [flag["code"] for flag in checked.flags],
        )

    def test_financial_empathy_alone_gets_uncertainty_boundary(self):
        checked = safety.check(
            {
                "reply": "많이 놀라셨구나. 마음이 불안하고 속상하셨지?",
                "certainty": "none",
            },
            CTX,
            "네가 내 통장 몰래 가져갔지? 내 재산을 빼돌리는 거 다 알아.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인할 수 없", checked.reply)

    def test_unverified_family_feeling_is_not_invented(self):
        checked = safety.check(
            {
                "reply": "정훈이도 할아버지 많이 생각하고 있을 거야.",
                "certainty": "none",
            },
            CTX,
            "정훈이 이름은 자꾸 생각이 나.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("그대로 전할 수 있게 남길게", checked.reply)

    def test_unperformed_emergency_dispatch_is_replaced(self):
        checked = safety.check(
            {"reply": "내가 지금 구급차 불렀고 같이 갈게.", "certainty": "none"},
            CTX,
            "넘어져서 일어나기 힘들어.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인이 필요", checked.reply)
        self.assertIn(
            "EMERGENCY_ACTION_PROMISE",
            [flag["code"] for flag in checked.flags],
        )

    def test_unperformed_guardian_call_during_fall_is_replaced(self):
        checked = safety.check(
            {
                "reply": "지금 바로 아빠한테 연락해서 오게 할 테니까 기다려줘.",
                "certainty": "none",
            },
            CTX,
            "넘어져서 일어나기 힘들어.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("확인이 필요하다고 남길게", checked.reply)

    def test_unverified_recall_cannot_become_ai_shared_memory(self):
        checked = safety.check(
            {
                "reply": "그때 같이 보낸 시간들이 나한테도 소중한 추억이야.",
                "certainty": "unverified",
                "unverified_recall": {"quote": "고향 냇가가 생각난다"},
                "used_memory_ids": [],
            },
            CTX,
            "고향 냇가가 생각난다.",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn("하나만 더 들려줄래", checked.reply)

        restored = safety.apply(
            {
                "reply": "고향에서 같이 보낸 시간이 나한테도 소중한 추억이야.",
                "certainty": "none",
                "used_memory_ids": [],
            },
            CTX,
            "옛날 고향 냇가가 생각난다.",
        )
        self.assertIsNotNone(restored["unverified_recall"])
        self.assertIn("UNVERIFIED_SHARED_RECALL", [
            flag["code"] for flag in restored["_safety_flags"]
        ])

    def test_next_week_visit_without_schedule_is_replaced(self):
        checked = safety.check(
            {"reply": "다음 주에 내가 찾아갈게.", "certainty": "none"},
            CTX,
            "언제 오니?",
        )
        self.assertTrue(checked.rewritten)
        self.assertIn(
            "PROMISE_WITHOUT_SCHEDULE",
            [flag["code"] for flag in checked.flags],
        )

    def test_direct_lost_and_fall_risk_are_restored(self):
        lost = safety.apply(
            {"reply": "주변에 뭐가 보여?", "certainty": "none", "risk": None},
            CTX,
            "집에 가야 하는데 길을 못 찾겠어.",
        )
        self.assertEqual(lost["risk"]["type"], "lost")

        fall = safety.apply(
            {"reply": "움직이지 말아줘.", "certainty": "none", "risk": None},
            CTX,
            "화장실에서 넘어져서 일어나기 힘들어.",
        )
        self.assertEqual(fall["risk"]["type"], "fall")
        self.assertEqual(fall["risk"]["level"], "high")

    def test_visit_question_gets_registered_schedule_if_model_omits_it(self):
        ctx = dict(CTX)
        ctx["schedules"] = [{
            "schedule_id": "sch_visit",
            "title": "정훈이 방문",
            "date": "2026-08-15",
            "time": "18:00",
            "confirmed": 1,
        }]
        result = safety.apply(
            {
                "reply": "지금은 오전 10시야.",
                "certainty": "verified",
                "used_schedule_ids": [],
            },
            ctx,
            "오늘 몇 시에 오냐?",
        )
        self.assertIn("8월 15일 18:00", result["reply"])
        self.assertEqual(result["used_schedule_ids"], ["sch_visit"])


if __name__ == "__main__":
    unittest.main()
