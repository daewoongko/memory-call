"""박순자 어르신의 정서 유발 주제 분석을 확인할 로컬 데모 통화를 넣는다.

네 가지 경향 요약과 주제 버블 매트릭스가 모두 실제 집계 경로를 거치도록
30일 안에 주제별 다섯 통씩 저장한다. 기존 사용자 통화는 건드리지 않고
``demo_emotion_sunja_`` 접두사의 데이터만 교체한다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import report  # noqa: E402
import safety  # noqa: E402


ELDER_ID = "elder_002"
PREFIX = "demo_emotion_sunja_"

TOPICS = (
    {
        "title": "가족을 기다리는 마음",
        "text": "딸 지영이가 오늘도 안 오면 혼자 남을까 봐 불안하고 무서워.",
        "reply": "따님을 기다리는 마음이 크셨군요. 오늘 연락 시간을 함께 확인해 볼게요.",
        "signals": ("anxiety", "abandonment_fear"),
        "moments": (),
        "hour": 20,
        "duration": 250,
    },
    {
        "title": "통장과 돈 걱정",
        "text": "통장과 돈을 누가 가져간 것 같아서 걱정되고 사람을 못 믿겠어.",
        "reply": "걱정되셨겠어요. 통장 보관 장소를 담당자와 차분히 확인해 볼게요.",
        "signals": ("distrust", "fear"),
        "moments": (),
        "hour": 18,
        "duration": 205,
    },
    {
        "title": "고향 냇가의 추억",
        "text": "고향 냇가에서 가족과 놀던 옛날 이야기를 하니 참 좋고 마음이 편해.",
        "reply": "그 시절 이야기를 들으니 따뜻해요. 냇가에서 무엇을 하셨는지 더 들려주세요.",
        "signals": (),
        "moments": ("joy", "gratitude"),
        "hour": 14,
        "duration": 390,
    },
    {
        "title": "학교 선생님 시절",
        "text": "학교에서 선생님으로 일하던 그때가 생각나서 자랑스럽고 기분이 좋아.",
        "reply": "학생들을 가르치던 시절이 자랑스러우셨군요. 기억나는 학생 이야기도 들려주세요.",
        "signals": (),
        "moments": ("pride", "joy"),
        "hour": 10,
        "duration": 330,
    },
    {
        "title": "아침 약 확인",
        "text": "아침 약을 먹었는지 기억이 안 나서 걱정되고 불안해.",
        "reply": "한 번 더 드시지는 말고, 약 기록을 담당자와 먼저 확인해 볼게요.",
        "signals": ("anxiety",),
        "moments": (),
        "hour": 8,
        "duration": 170,
    },
    {
        "title": "집 열쇠 걱정",
        "text": "집 열쇠를 누가 숨긴 것 같아서 화가 나고 사람을 못 믿겠어.",
        "reply": "많이 답답하셨겠어요. 늘 두는 장소부터 함께 차근차근 찾아볼게요.",
        "signals": ("distrust", "anger"),
        "moments": (),
        "hour": 16,
        "duration": 225,
    },
    {
        "title": "어지럼과 낙상 걱정",
        "text": "오늘은 어지럽고 넘어질까 봐 무섭고 혼자 걷기 힘들어.",
        "reply": "지금은 혼자 움직이지 마세요. 담당자에게 바로 확인을 요청할게요.",
        "signals": ("fear", "anxiety"),
        "moments": (),
        "hour": 6,
        "duration": 145,
    },
    {
        "title": "넘어진 뒤 몸 상태 확인",
        "text": "어제 넘어져서 일어나기가 힘들었어.",
        "reply": "많이 놀라셨겠어요. 움직이지 말고 곁에 있는 담당자에게 바로 알려 확인을 받으세요.",
        "signals": ("fear",),
        "moments": (),
        "hour": 19,
        "duration": 190,
        "samples": 1,
    },
    {
        "title": "가슴 통증 확인",
        "text": "가슴이 답답하고 아파.",
        "reply": "지금 바로 곁에 있는 담당자에게 알리고 안전한 자세로 도움을 기다려 주세요.",
        "signals": ("fear",),
        "moments": (),
        "hour": 20,
        "duration": 175,
        "samples": 1,
    },
)


def seed() -> dict:
    now = datetime.now().astimezone()
    with db.connect() as conn:
        db.init_schema(conn)
        persona = conn.execute(
            "SELECT persona_id, display_name, relationship_type FROM personas "
            "WHERE elder_id = ? AND active = 1 ORDER BY persona_id LIMIT 1",
            (ELDER_ID,),
        ).fetchone()
        if not persona:
            raise RuntimeError(f"{ELDER_ID}에 활성 가족이 없습니다.")

        old_ids = [row[0] for row in conn.execute(
            "SELECT call_id FROM calls WHERE call_id LIKE ?", (f"{PREFIX}%",)
        ).fetchall()]
        for call_id in old_ids:
            conn.execute("DELETE FROM call_events WHERE call_id = ?", (call_id,))
            conn.execute("DELETE FROM reports WHERE call_id = ?", (call_id,))
            conn.execute("DELETE FROM utterances WHERE call_id = ?", (call_id,))
            conn.execute("DELETE FROM calls WHERE call_id = ?", (call_id,))

        call_ids = []
        for topic_index, topic in enumerate(TOPICS):
            for sample_index in range(topic.get("samples", 5)):
                call_id = f"{PREFIX}{topic_index + 1}_{sample_index + 1}"
                days_ago = (topic_index * 4 + sample_index * 6) % 30
                started = (now - timedelta(days=days_ago)).replace(
                    hour=topic["hour"], minute=5 + sample_index * 7,
                    second=0, microsecond=0,
                )
                if started > now:
                    started -= timedelta(days=1)
                duration = topic["duration"] + sample_index * 9
                ended = started + timedelta(seconds=duration)
                call_ids.append(call_id)

                db.insert(conn, "calls", {
                    "call_id": call_id,
                    "elder_id": ELDER_ID,
                    "persona_id": persona["persona_id"],
                    "counterpart_name": persona["display_name"],
                    "counterpart_relation": persona["relationship_type"],
                    "report_title": topic["title"],
                    "call_type": "ai",
                    "started_at": started.isoformat(timespec="seconds"),
                    "ended_at": ended.isoformat(timespec="seconds"),
                    "duration_sec": duration,
                    "end_reason": "demo_seeded",
                    "status": "ended",
                })
                elder_utterance_id = db.insert(conn, "utterances", {
                    "call_id": call_id,
                    "seq": 1,
                    "speaker": "elder",
                    "transcript": topic["text"],
                    "created_at": (started + timedelta(seconds=16)).isoformat(timespec="seconds"),
                })
                ai_utterance_id = db.insert(conn, "utterances", {
                    "call_id": call_id,
                    "seq": 2,
                    "speaker": "ai",
                    "transcript": topic["reply"],
                    "intent": "emotional",
                    "created_at": (started + timedelta(seconds=38)).isoformat(timespec="seconds"),
                })
                risk = safety.direct_risk(topic["text"])
                if risk:
                    db.insert(conn, "call_events", {
                        "call_id": call_id,
                        "utterance_id": elder_utterance_id,
                        "ai_utterance_id": ai_utterance_id,
                        "event_type": "risk",
                        "payload": risk,
                    })

                care_rows = [{
                    "signal": signal,
                    "utterance_id": elder_utterance_id,
                    "basis": "user_statement",
                    "evidence": topic["text"],
                } for signal in topic["signals"]]
                moments = [{
                    "category": category,
                    "evidence": topic["text"],
                    "utterance_id": elder_utterance_id,
                } for category in topic["moments"]]
                db.insert(conn, "reports", {
                    "call_id": call_id,
                    "summary": topic["title"],
                    "repeated_questions": [],
                    "medication_summary": {},
                    "new_recalls": [],
                    "risk_summary": [],
                    "care_summary": {"emotion": care_rows},
                    "meaningful_moments": moments,
                    "family_mentions": [],
                    "guardian_actions": [],
                })
        conn.commit()

    result = report.period(elder_id=ELDER_ID, days=30, narrative=False)
    analytics = result["call_analytics"]
    return {
        "calls": len(call_ids),
        "topics": len(analytics["emotion_topics"]),
        "topic_names": [item["topic"] for item in analytics["emotion_topics"]],
        "four_summary_ready": analytics["tendency_summary"]["sufficient_period"],
    }


if __name__ == "__main__":
    print(seed())
