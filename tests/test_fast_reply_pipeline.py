"""Fast reply and background metadata pipeline tests."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import conversation  # noqa: E402
import db  # noqa: E402
import llm  # noqa: E402
import safety  # noqa: E402


class FastReplySchemaTests(unittest.TestCase):
    def test_fast_schema_does_not_mutate_original_messages(self):
        messages = [
            {"role": "system", "content": "base instructions"},
            {"role": "user", "content": "안녕하세요"},
        ]
        with patch.object(llm, "call_json", return_value={"reply": "네."}) as call:
            result = llm.call_json_fast(messages, temperature=0.1)

        self.assertEqual(result["reply"], "네.")
        self.assertEqual(messages[0]["content"], "base instructions")
        patched_messages = call.call_args.args[0]
        self.assertIn("이번 응답 전용 출력 형식", patched_messages[0]["content"])
        self.assertIn('"reply"', patched_messages[0]["content"])
        self.assertEqual(call.call_args.kwargs["temperature"], 0.1)

    def test_metadata_prompt_json_escapes_final_reply(self):
        prompt = llm.metadata_schema_override('그분이 "곧 온다"고 했어요.\\')
        self.assertIn('그분이 \\"곧 온다\\"고 했어요.\\\\', prompt)
        self.assertIn('"intent"', prompt)
        self.assertIn("새 답변을\n만들지 말고", prompt)


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
            patch.object(llm, "call_json_fast", return_value=fast.copy()) as fast_call,
            patch.object(llm, "call_json_metadata") as metadata_call,
            patch.object(session, "_apply_safety", side_effect=lambda value, _text: value),
        ):
            result = session.turn("조금 불안하다")

        fast_call.assert_called_once()
        metadata_call.assert_not_called()
        self.assertEqual(result["reply"], fast["reply"])
        self.assertEqual(result["_elder_uid"], 101)
        self.assertEqual(result["_ai_uid"], 102)
        self.assertEqual(result["_due_meds"], [])
        self.assertEqual(session.history[-1]["content"], fast["reply"])

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
