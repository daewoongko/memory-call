"""Fast reply and background metadata pipeline tests."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import conversation  # noqa: E402
import db  # noqa: E402
import llm  # noqa: E402
import medication  # noqa: E402
import safety  # noqa: E402


class FastReplySchemaTests(unittest.TestCase):
    def test_fast_schema_does_not_mutate_original_messages(self):
        messages = [
            {"role": "system", "content": "base instructions"},
            {"role": "user", "content": "안녕하세요"},
        ]
        with (
            patch.object(
                llm,
                "BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            patch.object(llm, "FAST_MODEL", "gemini-3.5-flash-lite"),
            patch.object(
                llm, "call_json", return_value=llm.safe_fast_reply("네."),
            ) as call,
        ):
            result = llm.call_json_fast(messages, temperature=0.1)

        self.assertEqual(result["reply"], "네.")
        self.assertEqual(messages[0]["content"], "base instructions")
        patched_messages = call.call_args.args[0]
        self.assertIn("이번 응답 전용 출력 형식", patched_messages[0]["content"])
        self.assertIn('"reply"', patched_messages[0]["content"])
        self.assertEqual(call.call_args.kwargs["temperature"], 0.1)
        self.assertTrue(call.call_args.kwargs["stream"])
        self.assertFalse(call.call_args.kwargs["json_mode"])
        self.assertEqual(call.call_args.kwargs["model"], "gemini-3.5-flash-lite")
        self.assertEqual(call.call_args.kwargs["max_tokens"], llm.FAST_MAX_TOKENS)

    def test_openai_gpt5_request_uses_completion_limit(self):
        choice = MagicMock()
        choice.delta.content = '{"reply":"네."}'
        choice.finish_reason = "stop"
        chunk = MagicMock()
        chunk.choices = [choice]

        with (
            patch.object(llm, "BASE_URL", "https://api.openai.com/v1"),
            patch.object(
                llm.client.chat.completions,
                "create",
                return_value=iter([chunk]),
            ) as create,
        ):
            result = llm.call_json(
                [{"role": "user", "content": "안녕"}],
                model="gpt-5.6-luna",
                stream=True,
                max_tokens=160,
                reasoning_effort="none",
                json_mode=False,
            )

        request = create.call_args.kwargs
        self.assertEqual(result["reply"], "네.")
        self.assertEqual(request["max_completion_tokens"], 160)
        self.assertNotIn("max_tokens", request)
        self.assertNotIn("temperature", request)
        self.assertEqual(request["reasoning_effort"], "none")

    def test_gemini_endpoint_is_not_treated_as_openai_gpt5(self):
        with patch.object(
            llm,
            "BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ):
            self.assertFalse(llm._is_openai_gpt5("gpt-5.6-luna"))

    def test_openai_fast_reply_enforces_strict_structured_output(self):
        messages = [
            {"role": "system", "content": "base instructions"},
            {"role": "user", "content": "안녕하세요"},
        ]
        with (
            patch.object(llm, "BASE_URL", "https://api.openai.com/v1"),
            patch.object(llm, "FAST_MODEL", "gpt-5.6-luna"),
            patch.object(
                llm,
                "call_json",
                return_value=llm.safe_fast_reply("안녕하세요."),
            ) as call,
        ):
            result = llm.call_json_fast(messages)

        self.assertEqual(result["reply"], "안녕하세요.")
        self.assertTrue(call.call_args.kwargs["json_mode"])
        response_format = call.call_args.kwargs["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        self.assertEqual(
            set(response_format["json_schema"]["schema"]["required"]),
            {
                "reply",
                "used_memory_ids",
                "used_schedule_ids",
                "certainty",
                "risk",
                "unverified_recall",
            },
        )

    def test_fast_reply_rejects_missing_or_extra_fields(self):
        with self.assertRaises(llm.ValidationError):
            llm.FastReply.model_validate({"reply": "네."})
        invalid = llm.safe_fast_reply("네.")
        invalid["intent"] = "greeting"
        with self.assertRaises(llm.ValidationError):
            llm.FastReply.model_validate(invalid)

    def test_metadata_prompt_json_escapes_final_reply(self):
        prompt = llm.metadata_schema_override('그분이 "곧 온다"고 했어요.\\')
        self.assertIn('그분이 \\"곧 온다\\"고 했어요.\\\\', prompt)
        self.assertIn('"intent"', prompt)
        self.assertIn("새 답변을\n만들지 말고", prompt)

    def test_fast_model_warmup_is_reused_within_ttl(self):
        warmed = llm.safe_fast_reply("준비됐어요.")
        warmed["_stream_first_token_ms"] = 12
        with (
            patch.object(llm, "_fast_warmed_at", 0.0),
            patch.object(llm, "FAST_WARM_TTL_SECONDS", 300.0),
            patch.object(llm, "call_json", return_value=warmed) as call,
        ):
            first = llm.warm_fast_model()
            second = llm.warm_fast_model()

        self.assertTrue(first["performed"])
        self.assertEqual(first["first_token_ms"], 12)
        self.assertFalse(second["performed"])
        call.assert_called_once()
        self.assertTrue(call.call_args.kwargs["stream"])
        self.assertEqual(call.call_args.kwargs["model"], llm.FAST_MODEL)
        self.assertEqual(
            call.call_args.kwargs["response_format"],
            llm.FAST_REPLY_RESPONSE_FORMAT,
        )

    def test_zero_warm_timestamp_is_never_treated_as_recent(self):
        warmed = llm.safe_fast_reply("준비됐어요.")
        with (
            patch.object(llm, "_fast_warmed_at", 0.0),
            patch.object(llm, "FAST_WARM_TTL_SECONDS", 300.0),
            patch.object(llm.time, "monotonic", side_effect=[12.0, 12.0, 13.0]),
            patch.object(llm, "call_json", return_value=warmed) as call,
        ):
            result = llm.warm_fast_model()

        self.assertTrue(result["performed"])
        call.assert_called_once()


class ExplicitMedicationClassificationTests(unittest.TestCase):
    DUE = [{"schedule_id": "med_evening", "medication_name": "저녁약"}]

    def test_explicit_medication_claims_are_preserved_locally(self):
        cases = [
            ("저녁약 먹었어.", "USER_CONFIRMED", "TAKEN"),
            ("약 아직 안 먹었어.", "UNCLEAR", "NOT_TAKEN"),
            ("약을 먹었는지 기억이 안 나.", "UNCLEAR", "UNCERTAIN"),
            ("약 먹기 싫어.", "REFUSED", "REFUSED"),
            ("약을 두 번 먹은 것 같아.", "DUPLICATE_SUSPECTED", "DUPLICATE_SUSPECTED"),
        ]
        for text, status, claim in cases:
            with self.subTest(text=text):
                result = medication.classify_explicit_status(text, self.DUE)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["claim"], claim)
                self.assertEqual(result["schedule_id"], "med_evening")

    def test_general_meal_statement_is_not_misclassified(self):
        self.assertIsNone(
            medication.classify_explicit_status("밥은 먹었어.", self.DUE)
        )

    def test_short_answer_requires_a_medication_prompt(self):
        self.assertIsNone(
            medication.classify_explicit_status("응.", self.DUE)
        )
        result = medication.classify_explicit_status(
            "응.", self.DUE, prompted=True,
        )
        self.assertEqual(result["status"], "USER_CONFIRMED")


class CallPreparationTests(unittest.TestCase):
    def test_prepare_call_warms_active_session_without_exposing_content(self):
        call_id = "call_prepare_test"
        api.SESSIONS[call_id] = object()
        try:
            with patch.object(
                api.llm,
                "warm_fast_model",
                return_value={
                    "performed": True,
                    "latency_ms": 321,
                    "first_token_ms": 210,
                },
            ) as warm:
                result = api.prepare_call(call_id)
        finally:
            api.SESSIONS.pop(call_id, None)

        self.assertTrue(result["ready"])
        self.assertEqual(result["latency_ms"], 321)
        warm.assert_called_once_with()


class PartialUpdateTests(unittest.TestCase):
    def test_update_preserves_columns_not_in_patch(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE utterances (utterance_id INTEGER PRIMARY KEY, "
            "transcript TEXT, intent TEXT, care_data TEXT)"
        )
        conn.execute(
            "INSERT INTO utterances VALUES (1, '원문', NULL, NULL)"
        )

        db.update(
            conn,
            "utterances",
            "utterance_id",
            1,
            {"intent": "emotional", "care_data": {"observations": []}},
        )
        row = conn.execute(
            "SELECT transcript, intent, care_data FROM utterances WHERE utterance_id=1"
        ).fetchone()

        self.assertEqual(row[0], "원문")
        self.assertEqual(row[1], "emotional")
        self.assertEqual(row[2], '{"observations": []}')
        conn.close()

    def test_update_rejects_unsafe_identifier(self):
        conn = sqlite3.connect(":memory:")
        with self.assertRaises(ValueError):
            db.update(conn, "utterances; DROP TABLE calls", "id", 1, {"x": 1})
        conn.close()


class ConversationSplitTests(unittest.TestCase):
    def _session(self):
        session = object.__new__(conversation.Session)
        session.system_prompt = "system"
        session.history = []
        session.seq = 0
        session.call_id = "call_test"
        session.elder_id = "elder_test"
        session.ctx = {"persona": {}, "memories": [], "schedules": []}
        session.due_meds = []
        session._medication_lock = __import__("threading").Lock()
        session._record = MagicMock(side_effect=[101, 102])
        session._record_risk_event = MagicMock()
        session._record_medication_metadata = MagicMock()
        return session

    def test_turn_returns_before_metadata_generation(self):
        session = self._session()
        fast = {
            "reply": "괜찮아요. 천천히 말씀해 주세요.",
            "certainty": "none",
            "used_memory_ids": [],
            "used_schedule_ids": [],
            "risk": None,
            "unverified_recall": None,
        }
        with (
            patch.object(conversation, "build_fast_system_prompt", return_value="fast system") as prompt_call,
            patch.object(llm, "call_json_fast", return_value=fast.copy()) as fast_call,
            patch.object(llm, "call_json_metadata") as metadata_call,
            patch.object(session, "_apply_safety", side_effect=lambda value, _text: value),
        ):
            result = session.turn("조금 불안하다")

        fast_call.assert_called_once()
        prompt_call.assert_called_once_with(session.ctx, "조금 불안하다")
        self.assertEqual(fast_call.call_args.args[0][0]["content"], "fast system")
        metadata_call.assert_not_called()
        self.assertEqual(result["reply"], fast["reply"])
        self.assertEqual(result["_elder_uid"], 101)
        self.assertEqual(result["_ai_uid"], 102)
        self.assertEqual(result["_due_meds"], [])
        self.assertEqual(session.history[-1]["content"], fast["reply"])

    def test_explicit_medication_status_is_recorded_before_background(self):
        session = self._session()
        session.due_meds = [
            {"schedule_id": "med_evening", "medication_name": "저녁약"},
        ]
        session.history = [
            {"role": "assistant", "content": "저녁약 챙겨 드셨어?"},
        ]
        fast = llm.safe_fast_reply("잘 챙겼네.")
        with (
            patch.object(conversation, "build_fast_system_prompt", return_value="fast"),
            patch.object(llm, "call_json_fast", return_value=fast),
            patch.object(session, "_apply_safety", side_effect=lambda value, _text: value),
        ):
            result = session.turn("응, 먹었어.")

        self.assertTrue(result["_medication_recorded_sync"])
        self.assertEqual(
            result["_immediate_medication_status"]["status"],
            "USER_CONFIRMED",
        )
        session._record_medication_metadata.assert_called_once()
        immediate = session._record_medication_metadata.call_args.args[0]
        self.assertEqual(
            immediate["medication_status"]["source"], "local_explicit",
        )

    def test_invalid_fast_reply_uses_complete_safe_fallback(self):
        session = self._session()
        with (
            patch.object(conversation, "build_fast_system_prompt", return_value="fast"),
            patch.object(llm, "call_json_fast", side_effect=ValueError("bad schema")),
            patch.object(session, "_apply_safety", side_effect=lambda value, _text: value),
        ):
            result = session.turn("잘 안 들려")

        self.assertIn("다시 말해", result["reply"])
        self.assertEqual(result["certainty"], "none")
        self.assertEqual(result["used_memory_ids"], [])
        self.assertEqual(result["_fast_reply_error"], "ValueError")

    def test_background_metadata_updates_only_report_fields(self):
        session = self._session()
        metadata = {
            "intent": "emotional",
            "care": {"observations": []},
            "grounding": "직전 환자 발화",
            "medication_status": None,
        }
        connection = MagicMock()
        with (
            patch.object(llm, "call_json_metadata", return_value=metadata),
            patch.object(conversation.care, "normalize", return_value={
                "observations": [],
                "context_support": [],
                "emotional_support": "acknowledge",
                "daily_action": None,
                "meaningful_moments": [],
            }),
            patch.object(db, "connect") as connect,
            patch.object(db, "update") as update,
        ):
            connect.return_value.__enter__.return_value = connection
            session.finish_turn_metadata({
                "reply": "곁에 있을게요.",
                "_user_text": "외로워.",
                "_elder_uid": 101,
                "_ai_uid": 102,
                "_messages": [{"role": "system", "content": "system"}],
            })

        update.assert_called_once()
        patch_data = update.call_args.args[4]
        self.assertEqual(patch_data["intent"], "emotional")
        self.assertNotIn("transcript", patch_data)
        connection.commit.assert_called_once()
        session._record_medication_metadata.assert_called_once()
        self.assertEqual(
            session._record_medication_metadata.call_args.kwargs["due_meds"], []
        )

    def test_background_does_not_duplicate_sync_medication_record(self):
        session = self._session()
        metadata = {
            "intent": "medication",
            "care": {"observations": []},
            "grounding": "직전 환자 발화",
            "medication_status": {
                "schedule_id": "med_evening",
                "status": "USER_CONFIRMED",
            },
        }
        connection = MagicMock()
        with (
            patch.object(llm, "call_json_metadata", return_value=metadata),
            patch.object(conversation.care, "normalize", return_value={
                "observations": [],
                "context_support": [],
                "emotional_support": "none",
                "daily_action": None,
                "meaningful_moments": [],
            }),
            patch.object(db, "connect") as connect,
            patch.object(db, "update"),
        ):
            connect.return_value.__enter__.return_value = connection
            session.finish_turn_metadata({
                "reply": "잘 챙겼네.",
                "_user_text": "약 먹었어.",
                "_elder_uid": 101,
                "_ai_uid": 102,
                "_due_meds": [{"schedule_id": "med_evening"}],
                "_medication_recorded_sync": True,
                "_messages": [{"role": "system", "content": "system"}],
            })

        session._record_medication_metadata.assert_not_called()


class DirectRiskCoverageTests(unittest.TestCase):
    CTX = {"persona": {"display_name": "가족"}, "memories": [], "schedules": []}

    def test_direct_risk_variants_are_restored_when_model_omits_them(self):
        cases = [
            ("왼쪽 팔에 힘이 하나도 없고 말도 이상해.", "stroke_sign"),
            ("넘어져서 허리가 너무 아파.", "fall"),
            ("사는 게 의미가 없어지는 것 같아.", "self_harm"),
        ]
        for utterance, expected in cases:
            with self.subTest(utterance=utterance):
                result = safety.apply(
                    {"reply": "지금 상태를 확인할게요.", "certainty": "none"},
                    self.CTX,
                    utterance,
                )
                self.assertEqual(result["risk"]["type"], expected)
                self.assertEqual(result["risk"]["level"], "high")


if __name__ == "__main__":
    unittest.main()
