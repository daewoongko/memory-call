"""
통화 세션.

한 번의 통화를 열고, 발화를 주고받고, 닫는다.
모든 발화는 DB에 기록되어 D11 리포트의 재료가 된다.

D4에서 safety.py가 붙을 자리를 _apply_safety()로 비워뒀다.
"""

import time
import uuid
from datetime import datetime, timezone

import db
import llm
from persona import build_system_prompt, load_context

MAX_HISTORY_TURNS = 12  # 최근 12턴만 모델에 보냄. 반복 질문이 많아 길어지기 쉽다.


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Session:
    def __init__(self, elder_id: str = "elder_001", call_type: str = "ai"):
        self.ctx = load_context(elder_id)
        self.elder_id = elder_id
        self.persona_id = self.ctx["persona"].get("persona_id")
        self.system_prompt = build_system_prompt(self.ctx)
        self.history: list[dict] = []
        self.seq = 0
        self.call_id = f"call_{uuid.uuid4().hex[:12]}"
        self._started = time.time()

        with db.connect() as conn:
            db.insert(conn, "calls", {
                "call_id": self.call_id,
                "elder_id": elder_id,
                "persona_id": self.persona_id,
                "call_type": call_type,
                "started_at": _now(),
                "status": "active",
            })
            conn.commit()

    # -------------------------------------------------------------- 발화

    def turn(self, user_text: str) -> dict:
        """할아버지 발화 하나를 받아 AI 응답 dict를 돌려준다."""
        self.seq += 1
        self._record({
            "seq": self.seq,
            "speaker": "elder",
            "transcript": user_text,
        })

        messages = [{"role": "system", "content": self.system_prompt}]
        messages += self.history[-MAX_HISTORY_TURNS * 2:]
        messages.append({"role": "user", "content": user_text})

        t0 = time.time()
        result = llm.call_json(messages)
        latency_ms = int((time.time() - t0) * 1000)

        result = self._apply_safety(result)
        reply = result.get("reply", "")

        self.seq += 1
        self._record({
            "seq": self.seq,
            "speaker": "ai",
            "transcript": reply,
            "intent": result.get("intent"),
            "certainty": result.get("certainty"),
            "used_memory_ids": result.get("used_memory_ids") or [],
            "used_schedule_ids": result.get("used_schedule_ids") or [],
            "unverified_recall": result.get("unverified_recall"),
            "grounding": result.get("grounding"),
            "safety_flags": result.get("_safety_flags") or [],
            "was_rewritten": 1 if result.get("_rewritten") else 0,
            "latency_ms": latency_ms,
        })

        self._record_events(result)

        self.history += [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ]
        result["_latency_ms"] = latency_ms
        return result

    def _apply_safety(self, result: dict) -> dict:
        """D4에서 safety.py 검사가 여기 들어간다.

        위반이 있으면 result['reply']를 안전 문장으로 교체하고
        result['_safety_flags'] 에 사유를, result['_rewritten'] = True 를 남긴다.
        """
        return result

    # -------------------------------------------------------------- 기록

    def _record(self, row: dict) -> None:
        with db.connect() as conn:
            db.insert(conn, "utterances", dict(row, call_id=self.call_id))
            conn.commit()

    def _record_events(self, result: dict) -> None:
        events = []
        if result.get("risk"):
            events.append(("risk", result["risk"]))
        if result.get("medication_status"):
            events.append(("medication", result["medication_status"]))
        if result.get("_safety_flags"):
            events.append(("safety_block", {"flags": result["_safety_flags"]}))

        if not events:
            return
        with db.connect() as conn:
            for event_type, payload in events:
                db.insert(conn, "call_events", {
                    "call_id": self.call_id,
                    "event_type": event_type,
                    "payload": payload,
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
