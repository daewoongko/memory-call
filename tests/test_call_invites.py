"""호출 상태머신.

여기서 지키려는 것은 하나다. **"받지 않았다"를 서버가 판정한다.**
이전 구현은 어르신 기기의 15초 타이머가 끝나면 보호자가 무엇을 하든
AI 로 넘어갔다. 그래서 아래 시험은 대부분 "누가 판정하는가"를 본다.
"""

import gc
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import invites  # noqa: E402


class CallInviteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "memory.sqlite"
        with db.connect() as conn:
            db.init_schema(conn)
            db.insert(conn, "elder_profiles",
                      {"elder_id": "elder_test", "name": "고길동"})
            for persona_id, name in (("persona_godaewoong", "대웅"),
                                     ("persona_miyeong", "미영")):
                db.insert(conn, "personas", {
                    "persona_id": persona_id, "elder_id": "elder_test",
                    "display_name": name, "relationship_type": "손자",
                })
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.original_path
        gc.collect()
        self.temp.cleanup()

    # -------------------------------------------------------------- 기기

    def _guardian(self, device_id="dev_guardian", persona_id="persona_godaewoong"):
        return invites.register_device(
            device_id=device_id, elder_id="elder_test", role="guardian",
            persona_id=persona_id, label="대웅 폰",
        )

    def test_guardian_device_must_declare_which_family_member_it_is(self):
        """persona_id 가 없으면 어르신이 고른 사람에게 벨을 보낼 수 없다."""
        with self.assertRaises(ValueError):
            invites.register_device(
                device_id="dev_x", elder_id="elder_test", role="guardian",
            )

    def test_registering_twice_updates_without_losing_created_at(self):
        first = self._guardian()
        with db.connect() as conn:
            created = conn.execute(
                "SELECT created_at FROM devices WHERE device_id = ?",
                (first["device_id"],),
            ).fetchone()["created_at"]

        invites.register_device(
            device_id="dev_guardian", elder_id="elder_test", role="guardian",
            persona_id="persona_godaewoong", label="대웅 새 폰",
        )
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", ("dev_guardian",),
            ).fetchone()
        self.assertEqual(row["label"], "대웅 새 폰")
        self.assertEqual(row["created_at"], created)

    # -------------------------------------------------------------- 벨

    def test_no_guardian_still_keeps_the_full_intro(self):
        """기기가 없어도 어르신의 음악·AI 영상은 같은 24.2초 동안 재생한다."""
        invite = invites.create("elder_test", "persona_godaewoong")
        self.assertEqual(invite["state"], invites.RINGING)
        self.assertEqual(invite["ring_timeout_sec"], invites.DEFAULT_RING_SEC)
        self.assertGreaterEqual(invite["intro_seconds_left"], 24.1)
        self.assertLessEqual(invite["intro_seconds_left"], 24.2)
        self.assertEqual(invite["no_live_device"], 1)

    def test_full_ring_when_a_guardian_device_is_listening(self):
        self.assertEqual(invites.DEFAULT_RING_SEC, 24.2)
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        self.assertEqual(invite["ring_timeout_sec"], invites.DEFAULT_RING_SEC)
        self.assertEqual(invite["no_live_device"], 0)

    def test_stale_guardian_device_does_not_count_as_listening(self):
        """폴링이 끊긴 기기는 화면이 닫힌 것이다. 살아 있다고 보면 안 된다."""
        self._guardian()
        stale = (datetime.now()
                 - timedelta(seconds=invites.DEVICE_ALIVE_SEC + 5)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE devices SET last_seen_at = ?", (stale,))
            conn.commit()

        invite = invites.create("elder_test", "persona_godaewoong")
        self.assertEqual(invite["no_live_device"], 1)

    # -------------------------------------------------------------- 수신

    def test_guardian_sees_only_invites_aimed_at_their_persona(self):
        self._guardian("dev_minjun", "persona_godaewoong")
        self._guardian("dev_miyeong", "persona_miyeong")
        invites.create("elder_test", "persona_godaewoong")

        self.assertIsNotNone(invites.incoming_for("dev_minjun"))
        self.assertIsNone(invites.incoming_for("dev_miyeong"))

    def test_polling_for_incoming_calls_counts_as_heartbeat(self):
        """별도 heartbeat 를 두지 않는 이유. 폴링 자체가 살아 있다는 증거다."""
        self._guardian()
        stale = (datetime.now()
                 - timedelta(seconds=invites.DEVICE_ALIVE_SEC + 5)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE devices SET last_seen_at = ?", (stale,))
            conn.commit()

        invites.incoming_for("dev_guardian")
        invite = invites.create("elder_test", "persona_godaewoong")
        self.assertEqual(invite["no_live_device"], 0)

    def test_elder_device_never_receives_incoming_calls(self):
        invites.register_device(device_id="dev_elder", elder_id="elder_test",
                                role="elder")
        invites.create("elder_test", "persona_godaewoong")
        self.assertIsNone(invites.incoming_for("dev_elder"))

    def test_risk_alert_rings_the_guardian_once_and_skips_the_intro(self):
        """위험 역호출은 즉시 보이고, 같은 AI 통화에서 중복 생성되지 않는다."""
        self._guardian()
        risk = {
            "type": "gas_leak",
            "evidence": "주방에서 가스 냄새가 계속 난다.",
        }
        self._make_call("call_risk_1")
        first = invites.create_risk_alert(
            "elder_test", "persona_godaewoong", "call_risk_1", risk,
        )
        second = invites.create_risk_alert(
            "elder_test", "persona_godaewoong", "call_risk_1", risk,
        )

        self.assertEqual(first["invite_id"], second["invite_id"])
        self.assertEqual(first["purpose"], "risk")
        self.assertEqual(first["alert_type"], "gas_leak")
        self.assertEqual(first["alert_evidence"], risk["evidence"])
        self.assertEqual(first["intro_duration_sec"], 0)
        self.assertTrue(first["intro_complete"])
        incoming = invites.incoming_for("dev_guardian")
        self.assertEqual(incoming["invite_id"], first["invite_id"])

    def test_guardian_handoff_is_answered_once_and_skips_the_intro(self):
        self._guardian()
        self._make_call("call_handoff_1")

        first = invites.create_handoff(
            "elder_test", "persona_godaewoong", "call_handoff_1", "dev_guardian",
        )
        second = invites.create_handoff(
            "elder_test", "persona_godaewoong", "call_handoff_1", "dev_guardian",
        )

        self.assertEqual(first["invite_id"], second["invite_id"])
        self.assertEqual(first["state"], invites.ANSWERED)
        self.assertEqual(first["purpose"], "handoff")
        self.assertEqual(first["source_call_id"], "call_handoff_1")
        self.assertEqual(first["to_device"], "dev_guardian")
        self.assertTrue(first["intro_complete"])
        self.assertEqual(first["intro_duration_sec"], 0)
        self.assertEqual(
            invites.for_source_call("call_handoff_1")["invite_id"],
            first["invite_id"],
        )

    def test_handoff_rejects_a_device_for_another_family_member(self):
        self._guardian("dev_miyeong", "persona_miyeong")
        self._make_call("call_handoff_2")
        with self.assertRaises(ValueError):
            invites.create_handoff(
                "elder_test", "persona_godaewoong", "call_handoff_2", "dev_miyeong",
            )

    # -------------------------------------------------------------- 전이

    def test_answer_records_which_device_picked_up(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        answered = invites.answer(invite["invite_id"], "dev_guardian")

        self.assertEqual(answered["state"], invites.ANSWERED)
        self.assertEqual(answered["to_device"], "dev_guardian")
        self.assertIsNotNone(answered["answered_at"])
        self.assertFalse(answered["should_take_over"])
        self.assertFalse(answered["intro_complete"])
        self.assertGreater(answered["intro_seconds_left"], 0)

    def test_answer_waits_for_the_shared_intro_before_connecting(self):
        """받기는 예약되고 사람 통화 공개 시점은 24.2초 재생 뒤다."""
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        answered = invites.answer(invite["invite_id"], "dev_guardian")
        self.assertFalse(answered["intro_complete"])

        self._age(invite["invite_id"], invites.INTRO_DURATION_SEC + 1)
        ready = invites.get(invite["invite_id"])
        self.assertEqual(ready["state"], invites.ANSWERED)
        self.assertTrue(ready["intro_complete"])
        self.assertEqual(ready["intro_seconds_left"], 0)

    def test_decline_hands_over_immediately_without_waiting_out_the_ring(self):
        """거절은 실패가 아니라 'AI 가 대신 받아라'는 뜻이다."""
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        declined = invites.decline(invite["invite_id"], "dev_guardian")

        self.assertEqual(declined["state"], invites.DECLINED)
        self.assertEqual(declined["takeover_reason"], "declined")
        self.assertTrue(declined["should_take_over"])

    def test_permission_denial_is_recorded_before_ai_takeover(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        declined = invites.decline(
            invite["invite_id"], "dev_guardian", "media_permission_denied")
        self.assertEqual(declined["takeover_reason"], "media_permission_denied")
        self.assertTrue(declined["should_take_over"])

    def test_server_expires_the_ring_without_any_client_timer(self):
        """이 시험이 0단계의 전부다.

        어르신 기기가 아무 말도 하지 않아도 서버가 무응답을 판정해야 한다.
        """
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        self._age(invite["invite_id"], invites.DEFAULT_RING_SEC + 1)

        expired = invites.get(invite["invite_id"])
        self.assertEqual(expired["state"], invites.TIMEOUT)
        self.assertEqual(expired["takeover_reason"], "timeout")
        self.assertTrue(expired["should_take_over"])
        self.assertEqual(expired["seconds_left"], 0)

    def test_timeout_reason_separates_no_answer_from_nobody_listening(self):
        """보호자 리포트에서 '거절'과 '기기 꺼짐'은 다른 이야기다."""
        invite = invites.create("elder_test", "persona_godaewoong")
        self._age(invite["invite_id"], invites.NO_DEVICE_RING_SEC + 1)
        self.assertEqual(invites.get(invite["invite_id"])["takeover_reason"],
                         "no_device")

    def test_answer_after_timeout_is_refused(self):
        """늦게 누른 받기가 이미 시작된 AI 통화를 덮어쓰면 안 된다."""
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        self._age(invite["invite_id"], invites.DEFAULT_RING_SEC + 1)

        with self.assertRaises(ValueError):
            invites.answer(invite["invite_id"], "dev_guardian")

    def test_only_one_of_two_devices_can_answer(self):
        self._guardian("dev_a", "persona_godaewoong")
        self._guardian("dev_b", "persona_godaewoong")
        invite = invites.create("elder_test", "persona_godaewoong")

        first = invites.answer(invite["invite_id"], "dev_a")
        second = invites.answer(invite["invite_id"], "dev_b")

        self.assertEqual(first["to_device"], "dev_a")
        self.assertEqual(second["to_device"], "dev_a")

    def test_answer_is_idempotent_for_a_retried_request(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        invites.answer(invite["invite_id"], "dev_guardian")
        again = invites.answer(invite["invite_id"], "dev_guardian")
        self.assertEqual(again["state"], invites.ANSWERED)

    def test_elder_hanging_up_does_not_hand_over_to_ai(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        cancelled = invites.cancel(invite["invite_id"])

        self.assertEqual(cancelled["state"], invites.CANCELLED)
        self.assertFalse(cancelled["should_take_over"])

    # -------------------------------------------------------------- 진단

    def test_device_list_reports_who_can_take_a_call_right_now(self):
        """폰에서 "왜 벨이 안 오지"를 확인할 데가 있어야 한다."""
        self._guardian()
        invites.register_device(device_id="dev_elder", elder_id="elder_test",
                                role="elder")

        rows = {row["device_id"]: row for row in invites.devices("elder_test")}
        self.assertTrue(rows["dev_guardian"]["listening"])
        # 어르신 기기는 거는 쪽이지 받는 쪽이 아니다
        self.assertFalse(rows["dev_elder"]["listening"])

        stale = (datetime.now()
                 - timedelta(seconds=invites.DEVICE_ALIVE_SEC + 5)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                         (stale, "dev_guardian"))
            conn.commit()

        after = {row["device_id"]: row for row in invites.devices("elder_test")}
        self.assertFalse(after["dev_guardian"]["listening"])
        self.assertGreater(after["dev_guardian"]["seconds_since_seen"],
                           invites.DEVICE_ALIVE_SEC)

    # -------------------------------------------------------------- 인계

    def test_take_over_links_the_ai_call_and_keeps_the_original_reason(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        invites.decline(invite["invite_id"], "dev_guardian")
        self._make_call("call_ai_1")

        handed = invites.take_over(invite["invite_id"], "call_ai_1")
        self.assertEqual(handed["state"], invites.AI_TAKEOVER)
        self.assertEqual(handed["ai_call_id"], "call_ai_1")
        # 거절이었다는 사실이 ai_takeover 로 덮여 사라지면 안 된다
        self.assertEqual(handed["takeover_reason"], "declined")

    def test_answered_call_requires_transport_failure_reason_for_takeover(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        invites.answer(invite["invite_id"], "dev_guardian")
        self._make_call("call_ai_2")

        with self.assertRaises(ValueError):
            invites.take_over(invite["invite_id"], "call_ai_2")

    def test_answered_call_can_fall_back_after_transport_failure(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        invites.answer(invite["invite_id"], "dev_guardian")
        self._make_call("call_ai_transport")

        handed = invites.take_over(
            invite["invite_id"], "call_ai_transport", "transport_failed")
        self.assertEqual(handed["state"], invites.AI_TAKEOVER)
        self.assertEqual(handed["takeover_reason"], "transport_failed")

    def test_take_over_from_a_ringing_invite_defaults_to_transport_failed(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        self._make_call("call_ai_3")

        handed = invites.take_over(invite["invite_id"], "call_ai_3",
                                   reason="transport_failed")
        self.assertEqual(handed["takeover_reason"], "transport_failed")

    def test_elder_permission_denial_is_kept_on_direct_takeover(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        self._make_call("call_ai_permission")
        handed = invites.take_over(
            invite["invite_id"], "call_ai_permission", "media_permission_denied")
        self.assertEqual(handed["takeover_reason"], "media_permission_denied")

    def test_answered_human_call_cannot_be_handed_to_ai(self):
        self._guardian()
        invite = invites.create("elder_test", "persona_godaewoong")
        invites.answer(invite["invite_id"], "dev_guardian")
        self._make_call("call_ai_4")
        with self.assertRaises(ValueError):
            invites.take_over(invite["invite_id"], "call_ai_4")

    def test_history_shows_why_each_call_ended_up_with_the_ai(self):
        """리포트가 '거절 1건 / 무응답 1건'을 구분할 수 있어야 한다."""
        self._guardian()
        declined = invites.create("elder_test", "persona_godaewoong")
        invites.decline(declined["invite_id"], "dev_guardian")

        ignored = invites.create("elder_test", "persona_godaewoong")
        self._age(ignored["invite_id"], invites.DEFAULT_RING_SEC + 1)
        invites.get(ignored["invite_id"])

        reasons = {row["invite_id"]: row["takeover_reason"]
                   for row in invites.recent("elder_test")}
        self.assertEqual(reasons[declined["invite_id"]], "declined")
        self.assertEqual(reasons[ignored["invite_id"]], "timeout")

    # -------------------------------------------------------------- 보조

    def _age(self, invite_id: str, seconds: float) -> None:
        """건 시각을 과거로 옮겨 벨이 다 울린 상황을 만든다."""
        older = (datetime.now() - timedelta(seconds=seconds)).isoformat(
            timespec="seconds")
        with db.connect() as conn:
            conn.execute("UPDATE call_invites SET created_at = ? "
                         "WHERE invite_id = ?", (older, invite_id))
            conn.commit()

    def _make_call(self, call_id: str) -> None:
        with db.connect() as conn:
            db.insert(conn, "calls", {"call_id": call_id,
                                      "elder_id": "elder_test"})
            conn.commit()


class UnreadableTimestampTest(unittest.TestCase):
    """시간을 읽을 수 없으면 AI 쪽으로 떨어뜨린다.

    잘못될 수 있는 두 방향 중 'AI 가 대신 받는다'는 정상 동작이고
    '어르신이 벨 화면에 갇힌다'는 사고다.
    """

    def test_broken_created_at_expires_instead_of_ringing_forever(self):
        self.assertEqual(invites._elapsed("망가진 값"), float("inf"))
        self.assertEqual(invites._elapsed(None), float("inf"))


if __name__ == "__main__":
    unittest.main()
