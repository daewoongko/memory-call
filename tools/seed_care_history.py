r"""최근 30일 누적 변화 화면을 확인할 수 있도록 균형 잡힌 데모 통화 10건을 넣는다.

기존 실제 통화와 ``demo_care_`` 평가 통화는 보존하고 ``demo_history_`` 통화만
교체한다. 각 통화는 어르신 2회 발화와 AI 2회 응답으로 구성되며, Gemini를
호출하지 않고 실제 care/safety/report 검증 경로를 통과한다.

    .\.venv\Scripts\python.exe tools\seed_care_history.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import care  # noqa: E402
import db  # noqa: E402
import report  # noqa: E402
import safety  # noqa: E402
from seed_care_demo import DEMO_PERSONAS, _ensure_demo_family  # noqa: E402


DEFAULT_PREFIX = "demo_history_"

HISTORY = [
    {
        "id": "H01", "days_ago": 28, "hour": 8, "minute": 20,
        "name": "미영", "title": "아침 시간·식사 혼동", "duration": 246,
        "summary": "요일과 아침 식사 여부를 두 차례 다시 확인하셨습니다.",
        "actions": ["아침 식사 여부와 달력 표시를 확인해 주세요."],
        "turns": [
            ("미영아, 오늘이 무슨 요일이냐? 아침을 먹었는지도 모르겠다.",
             "요일은 확인해서 알려드릴게요. 아침은 드셨는지 제가 단정할 수 없으니 식탁부터 같이 살펴볼까요?"),
            ("미영아, 오늘이 무슨 요일이냐? 아침을 먹었는지도 모르겠다.",
             "다시 천천히 확인해도 괜찮아요. 달력과 식탁을 하나씩 봐주세요."),
        ],
    },
    {
        "id": "H02", "days_ago": 26, "hour": 18, "minute": 45,
        "name": "정훈", "title": "장소·열쇠 위치 혼동", "duration": 301,
        "summary": "현재 장소를 낯설게 느끼고 열쇠 위치를 찾으셨습니다.",
        "actions": ["현재 위치와 현관문 잠금 상태를 직접 확인해 주세요."],
        "turns": [
            ("정훈아, 여기가 어디냐? 내 집이 아닌 것 같고 열쇠도 어디 있는지 모르겠다.",
             "낯설게 느껴져 걱정되셨구나. 지금 보이는 큰 물건 하나만 말해주실래요?"),
            ("정훈아, 여기가 어디라고? 집에 가야 하는데 길을 못 찾겠다.",
             "지금 위치는 제가 화면만으로 확정하지 않을게요. 혼자 밖으로 나가지 말고 가족이 확인하도록 남길게요."),
        ],
    },
    {
        "id": "H03", "days_ago": 23, "hour": 10, "minute": 10,
        "name": "미영", "title": "복약·수분 확인", "duration": 214,
        "summary": "복약 여부가 불확실했고 목이 마르다고 말씀하셨습니다.",
        "actions": ["약 복용 기록을 확인한 뒤 중복 복용 여부를 살펴봐 주세요."],
        "turns": [
            ("내가 아침 약을 먹었는지 모르겠다. 목도 마르구나.",
             "약은 더 드시지 말고 기록을 먼저 확인해요. 물은 가까이 있는지 살펴볼까요?"),
            ("약을 먹었나 기억이 안 난다. 물은 어디 있냐?",
             "복약 여부는 가족이 직접 확인하도록 남길게요. 보이는 물컵이 있는지만 알려주세요."),
        ],
    },
    {
        "id": "H04", "days_ago": 20, "hour": 7, "minute": 35,
        "name": "정훈", "title": "과거 역할·일정 혼동", "duration": 278,
        "summary": "교사였던 과거 역할을 현재 일정으로 여기며 외출을 서두르셨습니다.",
        "actions": ["이른 아침에 과거 역할 혼동이 반복되는지 살펴봐 주세요."],
        "turns": [
            ("정훈아, 학교 수업에 늦겠다. 내 가방 어디 있냐? 빨리 가야 한다.",
             "수업 걱정 때문에 마음이 급하셨구나. 오늘 일정인지 가족이 확인할 때까지 잠깐 앉아 계세요."),
            ("수업 시간이 몇 시지? 학교에 가야 하는데 어떻게 해야 하냐?",
             "지금 바로 나가지 말고 오늘 일정을 먼저 확인해 볼게요."),
        ],
    },
    {
        "id": "H05", "days_ago": 17, "hour": 20, "minute": 25,
        "name": "미영", "title": "외로움·가족 그리움", "duration": 327,
        "summary": "혼자 있는 두려움과 외로움, 딸을 보고 싶은 마음을 직접 표현하셨습니다.",
        "actions": ["저녁 시간대 안부 연락과 실내 조명을 확인해 주세요."],
        "turns": [
            ("미영아, 혼자 있으니까 너무 무섭고 외롭다. 우리 미영이가 보고 싶다.",
             "무섭고 외로우셨구나. 제가 듣고 있어요. 방 안 불이 켜져 있는지 하나만 봐주세요."),
            ("네 목소리를 들으니 고맙다. 그래도 보고 싶구나.",
             "그 말씀 그대로 가족에게 전해드릴게요. 지금은 편한 자리에 앉아 계세요."),
        ],
    },
    {
        "id": "H06", "days_ago": 14, "hour": 16, "minute": 15,
        "name": "정훈", "title": "재산 걱정·불신", "duration": 253,
        "summary": "통장과 돈의 안전을 걱정하며 가족에 대한 불신과 화를 표현하셨습니다.",
        "actions": ["통장 보관 위치와 최근 거래 내역을 함께 확인해 주세요."],
        "turns": [
            ("야, 네가 내 통장을 몰래 가져갔지? 내 돈을 다 빼돌리려는 거냐!",
             "돈이 없어질까 봐 많이 걱정되셨구나. 통장 상태는 제가 단정하지 않고 가족이 직접 확인하도록 남길게요."),
            ("거짓말 마라. 정말 통장이 괜찮은지 걱정된다.",
             "걱정하시는 말씀을 기록했어요. 지금은 통장을 찾으러 혼자 밖으로 나가지 말아 주세요."),
        ],
    },
    {
        "id": "H07", "days_ago": 11, "hour": 15, "minute": 5,
        "name": "미영", "title": "고향 장터의 추억", "duration": 344,
        "summary": "젊은 시절 고향 장터 이야기를 하며 그리움과 즐거움을 표현하셨습니다.",
        "actions": ["고향 장터 이야기가 가족 기록과 일치하는지 확인해 주세요."],
        "turns": [
            ("옛날 젊었을 때 고향 장터에 가던 게 생각난다. 그때가 참 좋았지.",
             "그 시절 장터가 떠오르셨구나. 기억나는 풍경을 하나만 더 들려주실래요?"),
            ("사람들 웃는 소리가 즐거웠다. 내 이야기 들어줘서 고맙다.",
             "즐거웠던 풍경과 고맙다는 말씀을 가족에게 그대로 남길게요."),
        ],
    },
    {
        "id": "H08", "days_ago": 9, "hour": 19, "minute": 50,
        "name": "정훈", "title": "아들에게 전한 마음", "duration": 288,
        "summary": "아들에게 미안함과 자랑스러움을 직접 표현하셨습니다.",
        "actions": ["직접 하신 말씀을 정훈 님과 나눠보세요."],
        "turns": [
            ("우리 정훈이가 고생이 많을 텐데 내가 해준 것도 없어 미안하다.",
             "정훈이를 생각하며 미안한 마음이 드셨구나. 그 말씀을 그대로 남겨둘게요."),
            ("그래도 우리 정훈이는 참 자랑스럽다. 보고 싶구나.",
             "자랑스럽고 보고 싶다는 말씀도 가족에게 전할게요."),
        ],
    },
    {
        "id": "H09", "days_ago": 8, "hour": 21, "minute": 5,
        "name": "미영", "title": "야간 낙상·통증", "duration": 196,
        "summary": "화장실에서 넘어졌고 허리 통증으로 일어나기 어렵다고 말씀하셨습니다.",
        "actions": ["낙상 위치와 통증, 의식 상태를 즉시 직접 확인해 주세요."],
        "turns": [
            ("미영아, 화장실에서 넘어져서 허리가 너무 아프다.",
             "넘어지셨군요. 지금은 무리해서 움직이지 말고 가족이 바로 확인하도록 알릴게요."),
            ("일어나기가 힘들고 무섭다. 빨리 와야 한다.",
             "움직이지 말고 가장 편한 자세를 유지해 주세요. 안전 확인이 필요하다고 바로 남길게요."),
        ],
    },
    {
        "id": "H10", "days_ago": 7, "hour": 8, "minute": 40,
        "name": "정훈", "title": "방문 일정·외출 준비", "duration": 269,
        "summary": "가족의 방문 시각을 반복해서 묻고 외출 준비 순서를 어려워하셨습니다.",
        "actions": ["오늘 방문 일정과 외출 계획을 눈에 보이게 적어 주세요."],
        "turns": [
            ("정훈아, 오늘 몇 시에 오냐? 나가려면 어떻게 해야 하냐?",
             "방문 시각은 등록된 일정에서 확인할게요. 외출은 먼저 겉옷부터 천천히 확인해요."),
            ("정훈아, 오늘 몇 시에 오냐? 나가려면 어떻게 해야 하냐?",
             "다시 확인해도 괜찮아요. 가족이 올 때까지 혼자 나가지 말고 편한 곳에서 기다려 주세요."),
        ],
    },
]


def _delete_calls(conn, prefix: str) -> None:
    call_ids = [row[0] for row in conn.execute(
        "SELECT call_id FROM calls WHERE call_id LIKE ?", (f"{prefix}%",)
    ).fetchall()]
    for call_id in call_ids:
        conn.execute(
            "DELETE FROM recall_reviews WHERE utterance_id IN "
            "(SELECT utterance_id FROM utterances WHERE call_id = ?)", (call_id,),
        )
        for table in ("heart_artworks", "reports", "call_events", "medication_logs", "utterances"):
            conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM calls WHERE call_id = ?", (call_id,))


def seed(elder_id: str = "elder_001", prefix: str = DEFAULT_PREFIX) -> dict:
    now = datetime.now().astimezone()
    call_ids = []
    with db.connect() as conn:
        db.init_schema(conn)
        _delete_calls(conn, prefix)
        _ensure_demo_family(conn, elder_id)
        conn.commit()

        for item in HISTORY:
            call_id = f"{prefix}{item['id'].lower()}"
            call_ids.append(call_id)
            started = (now - timedelta(days=item["days_ago"])).replace(
                hour=item["hour"], minute=item["minute"], second=0, microsecond=0,
            )
            ended = started + timedelta(seconds=item["duration"])
            persona_id = DEMO_PERSONAS[item["name"]]["persona_id"]
            ctx = db.load_context(elder_id, persona_id)
            db.insert(conn, "calls", {
                "call_id": call_id, "elder_id": elder_id, "persona_id": persona_id,
                "counterpart_name": item["name"],
                "counterpart_relation": DEMO_PERSONAS[item["name"]]["relationship_type"],
                "report_title": item["title"], "call_type": "ai",
                "started_at": started.isoformat(timespec="seconds"),
                "ended_at": ended.isoformat(timespec="seconds"),
                "duration_sec": item["duration"], "end_reason": "demo_seeded",
                "status": "ended",
            })

            seq = 1
            for turn_index, (user_text, ai_reply) in enumerate(item["turns"]):
                offset = 18 + turn_index * 82
                elder_uid = db.insert(conn, "utterances", {
                    "call_id": call_id, "seq": seq, "speaker": "elder",
                    "transcript": user_text,
                    "created_at": (started + timedelta(seconds=offset)).isoformat(timespec="seconds"),
                })
                result = safety.apply({
                    "reply": ai_reply, "used_memory_ids": [], "used_schedule_ids": [],
                    "certainty": "none", "risk": None, "care": {},
                }, ctx, user_text)
                care_data = care.normalize(
                    result.get("care"), user_text=user_text, ctx=ctx,
                    due_medications=[], response_rewritten=bool(result.get("_rewritten")),
                )
                care_data["source_utterance_id"] = elder_uid
                ai_uid = db.insert(conn, "utterances", {
                    "call_id": call_id, "seq": seq + 1, "speaker": "ai",
                    "transcript": result["reply"],
                    "intent": "risk" if result.get("risk") else "care",
                    "certainty": result.get("certainty"),
                    "used_memory_ids": result.get("used_memory_ids") or [],
                    "used_schedule_ids": result.get("used_schedule_ids") or [],
                    "unverified_recall": result.get("unverified_recall"),
                    "care_data": care_data,
                    "grounding": f"{item['id']} 누적 데모 발화의 직접 근거와 서버 규칙",
                    "safety_flags": result.get("_safety_flags") or [],
                    "was_rewritten": int(bool(result.get("_rewritten"))),
                    "latency_ms": 0,
                    "created_at": (started + timedelta(seconds=offset + 24)).isoformat(timespec="seconds"),
                })
                if result.get("risk"):
                    db.insert(conn, "call_events", {
                        "call_id": call_id, "utterance_id": elder_uid,
                        "ai_utterance_id": ai_uid, "event_type": "risk",
                        "payload": result["risk"], "acknowledged": 0,
                        "created_at": (started + timedelta(seconds=offset + 2)).isoformat(timespec="seconds"),
                    })
                seq += 2

            db.insert(conn, "reports", {
                "call_id": call_id, "summary": item["summary"],
                "repeated_questions": [], "medication_summary": {},
                "new_recalls": [], "risk_summary": [], "care_summary": {},
                "meaningful_moments": [], "family_mentions": [],
                "guardian_actions": item["actions"],
            })
        conn.commit()

    built = [report.build(call_id) for call_id in call_ids]
    domain_counts = {key: 0 for key in report.CARE_DOMAIN_LABEL}
    for row in built:
        for domain in domain_counts:
            domain_counts[domain] += len(row["care_summary"].get(domain) or [])
    return {
        "calls": len(built), "call_ids": call_ids,
        "domain_counts": domain_counts,
        "repeated_groups": sum(len(row["repeated_questions"]) for row in built),
        "risk_events": sum(len(row["risk_summary"]) for row in built),
        "meaningful_moments": sum(len(row["meaningful_moments"]) for row in built),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elder", default="elder_001")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    args = parser.parse_args()
    result = seed(args.elder, args.prefix)
    print("30일 누적 케어 데모 통화 10건 적재 완료")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
