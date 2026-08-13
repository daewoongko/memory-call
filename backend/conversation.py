"""
통화 세션.

한 번의 통화를 열고, 발화를 주고받고, 닫는다.
모든 발화는 DB에 기록되어 D11 리포트의 재료가 된다.

D4에서 safety.py가 붙을 자리를 _apply_safety()로 비워뒀다.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import db
import care
import llm
import medication
import safety
from persona import build_system_prompt, load_context

MAX_HISTORY_TURNS = 12  # 최근 12턴만 모델에 보냄. 반복 질문이 많아 길어지기 쉽다.
LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Session:
    def __init__(self, elder_id: str = "elder_001", call_type: str = "ai",
                 persona_id: str | None = None):
        self.ctx = load_context(elder_id, persona_id)
        self.elder_id = elder_id
        self.persona_id = self.ctx["persona"].get("persona_id")
        self.system_prompt = build_system_prompt(self.ctx)
        self.history: list[dict] = []
        self.seq = 0
        self.call_id = f"call_{uuid.uuid4().hex[:12]}"
        self._started = time.time()
        # 지금 챙겨야 하는 약. 통화를 열 때 선택한 AI 가족이 먼저 꺼낸다 (명세 FR-08).
        self.due_meds = medication.due(elder_id)
        self._medication_lock = threading.Lock()

        with db.connect() as conn:
            db.insert(conn, "calls", {
                "call_id": self.call_id,
                "elder_id": elder_id,
                "persona_id": self.persona_id,
                "counterpart_name": self.ctx["persona"].get("display_name"),
                "counterpart_relation": self.ctx["persona"].get("relationship_type"),
                "report_title": "AI 인지·정서 케어 통화",
                "call_type": call_type,
                "started_at": _now(),
                "status": "active",
            })
            conn.commit()

    # -------------------------------------------------------------- 시작

    def opening(self) -> str:
        """통화를 열 때 AI 가 먼저 건네는 말.

        복약 시간대라면 약부터 챙긴다. 문장은 규칙으로 만든다.
        복용량과 시간을 모델이 지어내면 그대로 위험이 되기 때문이다.
        """
        if not self.due_meds:
            return ""

        line = medication.opening_line(
            self.ctx["persona"].get("display_name", "가족"),
            self.ctx["persona"].get("family_calls_elder", "할아버지"),
            self.due_meds,
        )
        self.seq += 1
        self._record({
            "seq": self.seq,
            "speaker": "ai",
            "transcript": line,
            "intent": "medication",
            "certainty": "verified",
            "grounding": "등록된 복약 일정에 따라 먼저 안내함",
        })
        self.history.append({"role": "assistant", "content": line})
        return line

    # -------------------------------------------------------------- 발화

    def turn(self, user_text: str) -> dict:
        """빠른 답변과 안전 필드만 확정해 즉시 돌려준다.

        보호자 리포트용 intent/care/복약 메타데이터는 API 응답 후
        ``finish_turn_metadata``가 별도 생성해 같은 DB 행에 덧붙인다.
        """
        self.seq += 1
        elder_uid = self._record({
            "seq": self.seq,
            "speaker": "elder",
            "transcript": user_text,
        })

        messages = [{"role": "system", "content": self.system_prompt}]
        messages += self.history[-MAX_HISTORY_TURNS * 2:]
        messages.append({"role": "user", "content": user_text})

        t0 = time.time()
        result = llm.call_json_fast(messages)
        latency_ms = int((time.time() - t0) * 1000)

        result = self._apply_safety(result, user_text)
        reply = result.get("reply", "")

        self.seq += 1
        ai_uid = self._record({
            "seq": self.seq,
            "speaker": "ai",
            "transcript": reply,
            "certainty": result.get("certainty"),
            "used_memory_ids": result.get("used_memory_ids") or [],
            "used_schedule_ids": result.get("used_schedule_ids") or [],
            "unverified_recall": result.get("unverified_recall"),
            "safety_flags": result.get("_safety_flags") or [],
            "was_rewritten": 1 if result.get("_rewritten") else 0,
            "latency_ms": latency_ms,
        })

        self._record_risk_event(result, elder_uid, ai_uid)

        self.history += [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ]
        result["_latency_ms"] = latency_ms
        result["_elder_uid"] = elder_uid
        result["_ai_uid"] = ai_uid
        result["_user_text"] = user_text
        result["_due_meds"] = [dict(item) for item in self.due_meds]
        # BackgroundTasks가 같은 요청 문맥을 재구성하지 않도록 호출용 복사본만
        # 넘긴다. API 응답에는 밑줄 필드를 노출하지 않는다.
        result["_messages"] = messages
        return result

    def finish_turn_metadata(self, fast_result: dict) -> None:
        """응답 후 리포트용 메타데이터를 보수적으로 저장한다.

        실패하더라도 이미 안전검사를 거쳐 사용자에게 전달된 답변과 통화는
        영향을 받지 않는다. 세션 종료와 경합해도 DB 행 ID로 직접 갱신한다.
        """
        reply = str(fast_result.get("reply") or "")
        user_text = str(fast_result.get("_user_text") or "")
        elder_uid = fast_result.get("_elder_uid")
        ai_uid = fast_result.get("_ai_uid")
        messages = fast_result.get("_messages") or [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_text},
        ]
        try:
            meta = llm.call_json_metadata(
                messages, reply, temperature=0.2, quiet=True,
            )
        except Exception as exc:  # noqa: BLE001 - 후처리 실패는 실시간 통화를 막지 않는다
            LOGGER.warning("turn metadata generation failed for %s: %s", self.call_id, exc)
            return

        due_meds = fast_result.get("_due_meds") or []

        care_data = care.normalize(
            meta.get("care"),
            user_text=user_text,
            ctx=self.ctx,
            due_medications=due_meds,
            response_rewritten=bool(fast_result.get("_rewritten")),
        )
        if (
            care_data["observations"]
            or care_data["context_support"]
            or care_data["daily_action"] is not None
            or care_data["meaningful_moments"]
        ):
            care_data["source_utterance_id"] = elder_uid

        if ai_uid is not None:
            with db.connect() as conn:
                db.update(conn, "utterances", "utterance_id", ai_uid, {
                    "intent": meta.get("intent"),
                    "care_data": care_data,
                    "grounding": meta.get("grounding"),
                })
                conn.commit()

        self._record_medication_metadata(
            meta, user_text, elder_uid, ai_uid, due_meds=due_meds,
        )

    def _apply_safety(self, result: dict, user_text: str = "") -> dict:
        """규칙 검사. 위반이면 안전 문장으로 교체하고 사유를 남긴다."""
        return safety.apply(result, self.ctx, user_text)

    # -------------------------------------------------------------- 기록

    def _record(self, row: dict) -> int:
        with db.connect() as conn:
            uid = db.insert(conn, "utterances", dict(row, call_id=self.call_id))
            conn.commit()
        return uid

    def _record_medication_metadata(self, result: dict, user_text: str,
                                    elder_uid: int | None = None,
                                    ai_uid: int | None = None,
                                    due_meds: list[dict] | None = None) -> None:
        """백그라운드 분류에서 확인된 복약 상태를 기록한다.

        어떤 약인지는 지금 챙길 대상에서 고른다. 모델이 약을 지목하게 두지 않는다.
        """
        medication_status = result.get("medication_status")
        if medication_status:
            with db.connect() as conn:
                db.insert(conn, "call_events", {
                    "call_id": self.call_id,
                    "utterance_id": elder_uid,
                    "ai_utterance_id": ai_uid,
                    "event_type": "medication",
                    "payload": medication_status,
                })
                conn.commit()

        status = (medication_status or {}).get("status")
        due_snapshot = due_meds if due_meds is not None else self.due_meds
        if not status or not due_snapshot:
            return
        target_id = due_snapshot[0]["schedule_id"]
        lock = getattr(self, "_medication_lock", None) or threading.Lock()
        with lock:
            # 빠르게 연속 발화해 백그라운드 분류가 역순으로 끝나도 이미
            # 처리한 약을 다음 약으로 잘못 기록하지 않는다.
            if not any(row.get("schedule_id") == target_id for row in self.due_meds):
                return
            medication.record(
                elder_id=self.elder_id,
                schedule_id=target_id,
                status=status,
                call_id=self.call_id,
                evidence=user_text[:200],
                utterance_id=elder_uid,
            )
            if status == "USER_CONFIRMED":
                self.due_meds = [
                    row for row in self.due_meds
                    if row.get("schedule_id") != target_id
                ]

    def _record_risk_event(self, result: dict, elder_uid: int | None = None,
                           ai_uid: int | None = None) -> None:
        """안전 계층이 확정한 위험 이벤트를 즉시 남긴다.

        utterance_id 는 할아버지 발화다. 보호자가 리포트에서 위험을 눌렀을 때
        보고 싶은 것은 AI 가 뭐라고 답했는지가 아니라 어르신이 무슨 말을
        했는지이기 때문이다. ai_utterance_id 는 모델이 어느 응답에서 신고했는지
        추적하는 용도로만 쓴다.

        safety_block 은 더 이상 기록하지 않는다. 같은 내용이 이미
        utterances.safety_flags 에 발화와 함께 저장되고, 리포트의 _safety() 도
        그쪽만 읽는다. 이벤트 쪽은 아무도 읽지 않는 중복이었다.
        """
        if not result.get("risk"):
            return
        with db.connect() as conn:
            db.insert(conn, "call_events", {
                "call_id": self.call_id,
                "utterance_id": elder_uid,
                "ai_utterance_id": ai_uid,
                "event_type": "risk",
                "payload": result["risk"],
            })
            conn.commit()

    # -------------------------------------------------------------- 종료

    def end(self, reason: str = "user_ended") -> dict:
        duration = int(time.time() - self._started)
        with db.connect() as conn:
            conn.execute(
                "UPDATE calls SET ended_at = ?, duration_sec = ?, "
                "end_reason = ?, status = 'ended' WHERE call_id = ?",
                (_now(), duration, reason, self.call_id),
            )
            stats = conn.execute(
                "SELECT COUNT(*) AS turns, AVG(latency_ms) AS avg_ms "
                "FROM utterances WHERE call_id = ? AND speaker = 'ai'",
                (self.call_id,),
            ).fetchone()
            risks = conn.execute(
                "SELECT COUNT(*) FROM call_events "
                "WHERE call_id = ? AND event_type = 'risk'",
                (self.call_id,),
            ).fetchone()[0]
            conn.commit()

        return {
            "call_id": self.call_id,
            "duration_sec": duration,
            "ai_turns": stats["turns"] or 0,
            "avg_latency_ms": int(stats["avg_ms"]) if stats["avg_ms"] else 0,
            "risk_events": risks,
        }
