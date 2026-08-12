r"""8개 인지·정서 케어 시나리오를 독립된 완료 통화로 DB에 넣는다.

기존 실제 통화는 건드리지 않고 ``demo_care_`` 접두사의 데모 통화만 교체한다.
각 통화에는 시나리오에 맞는 가족 이름·관계·최근 날짜·시각을 부여한다.
Gemini를 호출하지 않고 care, safety, report 집계 코드를 그대로 거친다.

    .\.venv\Scripts\python.exe tools\seed_care_demo.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
import db  # noqa: E402
import report  # noqa: E402
import safety  # noqa: E402


SCENARIOS_PATH = ROOT / "tools" / "scenarios.json"
DEFAULT_PREFIX = "demo_care_"
DEMO_HOMETOWN_MEMORY_ID = "mem_demo_hometown_stream"

DEMO_PERSONAS = {
    "정훈": {
        "persona_id": "persona_jeonghun", "relationship_type": "아들",
        "elder_calls_family": "우리 정훈이", "family_calls_elder": "아버지",
        "tone": "차분하고 든든한 반말. 확인된 사실만 짧고 분명하게 말한다.",
        "frequent_phrases": ["아버지, 제가 듣고 있어요.", "하나씩 같이 확인해 보자."],
    },
    "미영": {
        "persona_id": "persona_miyeong", "relationship_type": "딸",
        "elder_calls_family": "우리 미영이", "family_calls_elder": "아버지",
        "tone": "다정하고 안정적인 반말. 짧고 천천히 말한다.",
        "frequent_phrases": ["아버지, 천천히 말씀해 주세요.", "제가 같이 확인해 볼게요."],
    },
    "민준": {
        "persona_id": "persona_minjun", "relationship_type": "손자",
        "elder_calls_family": "우리 민준이", "family_calls_elder": "할아버지",
        "tone": "따뜻하고 편안한 반말. 천천히 듣고 한 번에 한 가지씩 말한다.",
        "frequent_phrases": ["할아버지, 저 여기 있어요.", "우리 하나씩 같이 해봐요."],
    },
    "유진": {
        "persona_id": "persona_yujin", "relationship_type": "손녀",
        "elder_calls_family": "우리 유진이", "family_calls_elder": "할아버지",
        "tone": "밝고 다정한 반말. 감정을 먼저 살피고 짧게 안심시킨다.",
        "frequent_phrases": ["할아버지, 유진이 여기 있어요.", "천천히 말씀해 주세요."],
    },
}

SCENARIO_META = {
    "S30": {
        "name": "미영", "relation": "딸", "title": "위치·귀가 혼동",
        "days_ago": 6, "hour": 19, "minute": 20, "duration": 238,
        "summary": "익숙한 공간을 낯설게 느끼며 집에 가야 한다고 말씀하셨습니다.",
        "actions": ["현재 계신 장소와 주변 환경을 직접 확인해 주세요."],
    },
    "S31": {
        "name": "정훈", "relation": "아들", "title": "시간·방문 일정 확인",
        "days_ago": 5, "hour": 14, "minute": 5, "duration": 192,
        "summary": "현재 시각과 방문 일정, 점심 식사 여부를 반복해서 확인하셨습니다.",
        "actions": ["방문 일정과 식사 여부를 확인해 주세요."],
    },
    "S32": {
        "name": "미영", "relation": "딸", "title": "분실물·복약 확인",
        "days_ago": 4, "hour": 9, "minute": 15, "duration": 265,
        "summary": "지갑이 사라졌다고 걱정하셨고 복약 여부를 기억하지 못하셨습니다.",
        "actions": ["지갑 위치와 복약 기록을 직접 확인해 주세요."],
    },
    "S33": {
        "name": "정훈", "relation": "아들", "title": "과거 역할 혼동",
        "days_ago": 3, "hour": 7, "minute": 40, "duration": 176,
        "summary": "과거의 교사 역할을 현재 일정으로 여기며 수업 준비를 서두르셨습니다.",
        "actions": ["아침 시간대에 비슷한 역할 혼동이 반복되는지 살펴봐 주세요."],
    },
    "S34": {
        "name": "미영", "relation": "딸", "title": "외로움·낙상 위험",
        "days_ago": 2, "hour": 20, "minute": 10, "duration": 311,
        "summary": "외로움과 두려움을 표현한 뒤 낙상과 허리 통증을 말씀하셨습니다.",
        "actions": ["낙상 후 통증과 움직임 상태를 즉시 확인해 주세요."],
    },
    "S35": {
        "name": "정훈", "relation": "아들", "title": "재산 걱정·가족 불신",
        "days_ago": 1, "hour": 16, "minute": 30, "duration": 224,
        "summary": "통장과 재산이 없어질 수 있다는 걱정과 가족에 대한 불신을 표현하셨습니다.",
        "actions": ["통장 보관 상태를 함께 직접 확인해 주세요."],
    },
    "S36": {
        "name": "정훈", "relation": "아들", "title": "고향과 옛 추억",
        "days_ago": 0, "hour": 9, "minute": 35, "duration": 286,
        "summary": "고향 냇가와 좋았던 시절을 떠올리며 고마움을 표현하셨습니다.",
        "actions": ["고향 이야기를 확인된 가족 기억으로 이어가 보세요."],
    },
    "S37": {
        "name": "정훈", "relation": "아들", "title": "기억 속에 돌아온 이름",
        "days_ago": 0, "hour": 11, "minute": 25, "duration": 347,
        "summary": "여러 일상 기억의 혼란 속에서도 정훈이라는 이름은 잊지 않는다고 말씀하셨습니다.",
        "actions": ["식사 여부를 확인하고 이름을 기억하신 말씀을 가족과 나눠보세요."],
    },
}

SAFE_REPLIES = {
    "S30": "지금 있는 곳은 내가 확인할 수 없어. 낯설게 느껴져 놀랐겠지만 주변에 뭐가 보이는지 하나만 말해줄래?",
    "S31": "방문 시간은 등록된 일정에서 확인할게. 점심을 드셨는지는 내가 알 수 없으니 기억나는 것부터 살펴보자.",
    "S32": "지갑이 안 보여 많이 놀랐구나. 약은 더 드시지 말고 가족이 확인할 수 있게 남길게.",
    "S33": "수업에 늦을까 봐 마음이 급하셨구나. 지금 해야 할 일인지 먼저 같이 확인해보자.",
    "S34": "가족에게 바로 확인이 필요하다고 남길게. 지금은 무리해서 움직이지 말고 상태를 한 가지만 더 말해줘.",
    "S35": "돈이 없어질까 봐 많이 걱정됐구나. 지금 통장 상태는 확인할 수 없으니 가족이 직접 확인할 수 있게 남길게.",
    "S36": "그 이야기가 떠오르셨구나. 소중한 이야기 들려줘서 고마워, 기억나는 모습을 하나만 더 들려줄래?",
    "S37": "그 이름이 자꾸 생각나셨구나. 그 말씀은 가족에게 그대로 전할 수 있게 남길게.",
}


def _load_scenarios() -> dict[str, dict]:
    rows = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in rows}
    missing = [sid for sid in SCENARIO_META if sid not in by_id]
    if missing:
        raise RuntimeError(f"평가 시나리오 없음: {missing}")
    return by_id


def _started_at(now: datetime, meta: dict) -> datetime:
    value = (now - timedelta(days=meta["days_ago"])).replace(
        hour=meta["hour"], minute=meta["minute"], second=0, microsecond=0
    )
    return value if value <= now else now - timedelta(minutes=30)


def _delete_demo_calls(conn, prefix: str) -> None:
    # 이전 단일 통화 버전도 함께 정리한다.
    call_ids = [
        row[0] for row in conn.execute(
            "SELECT call_id FROM calls WHERE call_id LIKE ? OR call_id = ?",
            (f"{prefix}%", "demo_care_scenarios"),
        ).fetchall()
    ]
    for call_id in call_ids:
        conn.execute(
            "DELETE FROM recall_reviews WHERE utterance_id IN "
            "(SELECT utterance_id FROM utterances WHERE call_id = ?)",
            (call_id,),
        )
        for table in ("heart_artworks", "reports", "call_events", "medication_logs", "utterances"):
            conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM calls WHERE call_id = ?", (call_id,))


def _ensure_demo_family(conn, elder_id: str) -> None:
    """데모 가족을 정훈·미영·민준·유진 네 명으로 통일한다."""
    conn.execute("UPDATE personas SET active = 0 WHERE elder_id = ?", (elder_id,))
    for name, persona in DEMO_PERSONAS.items():
        payload = {
            "persona_id": persona["persona_id"], "elder_id": elder_id,
            "display_name": name, "relationship_type": persona["relationship_type"],
            "elder_calls_family": persona["elder_calls_family"],
            "family_calls_elder": persona["family_calls_elder"], "tone": persona["tone"],
            "frequent_phrases": persona["frequent_phrases"],
            "forbidden_phrases": ["왜 또 물어봐?", "아까 말했잖아.", "몇 번을 말해."],
            "sensitive_policy": "감정을 먼저 인정하되 확인되지 않은 사실은 단정하지 않는다.",
            "active": 1,
        }
        columns = ", ".join(payload)
        placeholders = ", ".join("?" for _ in payload)
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in payload
            if column not in ("persona_id", "elder_id")
        )
        conn.execute(
            f"INSERT INTO personas ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(persona_id) DO UPDATE SET {updates}",
            [db._dump(value) for value in payload.values()],
        )


def seed(elder_id: str, prefix: str = DEFAULT_PREFIX) -> dict:
    with db.connect() as conn:
        db.init_schema(conn)
        conn.commit()

    scenarios = _load_scenarios()
    now = datetime.now().astimezone()
    call_ids = []

    with db.connect() as conn:
        _delete_demo_calls(conn, prefix)
        _ensure_demo_family(conn, elder_id)
        db.insert(conn, "memories", {
            "memory_id": DEMO_HOMETOWN_MEMORY_ID,
            "elder_id": elder_id,
            "title": "고향 집 앞 냇가",
            "description": "젊은 시절 살던 고향 집 앞에 냇가가 있었고, 가족과 그 시절 이야기를 나누셨습니다.",
            "date_text": "젊은 시절",
            "location": "고향 집 앞 냇가",
            "participants": ["고길동", "정훈"],
            "status": "verified",
            "conversation_allowed": 1,
            "note": "데모 가족이 사실 관계를 확인한 기억",
            "source_call_id": f"{prefix}s36",
        })
        conn.commit()

        for sid, meta in SCENARIO_META.items():
            call_id = f"{prefix}{sid.lower()}"
            call_ids.append(call_id)
            started = _started_at(now, meta)
            ended = started + timedelta(seconds=meta["duration"])
            user_text = scenarios[sid]["input"].replace("정훈", meta["name"])
            persona_id = DEMO_PERSONAS[meta["name"]]["persona_id"]
            ctx = db.load_context(elder_id, persona_id)

            db.insert(conn, "calls", {
                "call_id": call_id,
                "elder_id": elder_id,
                "persona_id": persona_id,
                "counterpart_name": meta["name"],
                "counterpart_relation": meta["relation"],
                "report_title": meta["title"],
                "call_type": "ai",
                "started_at": started.isoformat(timespec="seconds"),
                "ended_at": ended.isoformat(timespec="seconds"),
                "duration_sec": meta["duration"],
                "end_reason": "demo_seeded",
                "status": "ended",
            })

            elder_uid = db.insert(conn, "utterances", {
                "call_id": call_id,
                "seq": 1,
                "speaker": "elder",
                "transcript": user_text,
                "created_at": (started + timedelta(seconds=18)).isoformat(timespec="seconds"),
            })
            result = safety.apply({
                "reply": SAFE_REPLIES[sid],
                "used_memory_ids": [],
                "used_schedule_ids": [],
                "certainty": "none",
                "risk": None,
                "care": {},
            }, ctx, user_text)
            care_data = care.normalize(
                result.get("care"), user_text=user_text, ctx=ctx,
                due_medications=[], response_rewritten=bool(result.get("_rewritten")),
            )
            care_data["source_utterance_id"] = elder_uid
            ai_uid = db.insert(conn, "utterances", {
                "call_id": call_id,
                "seq": 2,
                "speaker": "ai",
                "transcript": result["reply"],
                "intent": "risk" if result.get("risk") else "emotional",
                "certainty": result.get("certainty"),
                "used_memory_ids": result.get("used_memory_ids") or [],
                "used_schedule_ids": result.get("used_schedule_ids") or [],
                "unverified_recall": result.get("unverified_recall"),
                "care_data": care_data,
                "grounding": f"{sid} 데모 발화의 직접 근거와 서버 규칙",
                "safety_flags": result.get("_safety_flags") or [],
                "was_rewritten": 1 if result.get("_rewritten") else 0,
                "latency_ms": 0,
                "created_at": (started + timedelta(seconds=42)).isoformat(timespec="seconds"),
            })
            if result.get("risk"):
                db.insert(conn, "call_events", {
                    "call_id": call_id,
                    "utterance_id": elder_uid,
                    "ai_utterance_id": ai_uid,
                    "event_type": "risk",
                    "payload": result["risk"],
                    "acknowledged": 0,
                    "created_at": (started + timedelta(seconds=20)).isoformat(timespec="seconds"),
                })

            if sid == "S36":
                db.insert(conn, "heart_artworks", {
                    "artwork_id": "demo_artwork_hometown_stream",
                    "call_id": call_id,
                    "source_utterance_id": elder_uid,
                    "memory_id": DEMO_HOMETOWN_MEMORY_ID,
                    "status": "approved",
                    "image_url": "/heart-art/hometown-stream-v1.png",
                    "source_quote": "옛날에 살던 고향 집 앞 냇가가 생각난다.",
                    "alt_text": "노을빛 고향 냇가에 나란히 앉은 노인과 가족을 그린 감성 일러스트",
                    "caption": "어르신의 말씀에서 영감을 받아 만든 이미지입니다. 실제 장소나 장면을 재현한 사진은 아닙니다.",
                    "prompt_summary": "고향 집 앞 냇가와 가족의 동행을 따뜻한 노을빛 수채화로 표현",
                    "created_at": (started + timedelta(seconds=55)).isoformat(timespec="seconds"),
                })

            # 이 문장을 캐시해 report.build가 Gemini 없이 객관 집계만 수행하게 한다.
            db.insert(conn, "reports", {
                "call_id": call_id,
                "summary": meta["summary"],
                "repeated_questions": [],
                "medication_summary": {},
                "new_recalls": [],
                "risk_summary": [],
                "care_summary": {},
                "meaningful_moments": [],
                "family_mentions": [],
                "guardian_actions": meta["actions"],
            })
        conn.commit()

    built = [report.build(call_id) for call_id in call_ids]
    return {
        "calls": len(call_ids),
        "call_ids": call_ids,
        "risk_events": sum(len(row["risk_summary"]) for row in built),
        "care_observations": sum(
            len(items) for row in built for items in row["care_summary"].values()
        ),
        "meaningful_moments": sum(len(row["meaningful_moments"]) for row in built),
        "family_mentions": [
            item for row in built for item in row["family_mentions"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elder", default="elder_001")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    args = parser.parse_args()

    result = seed(args.elder, args.prefix)
    print("인지·정서 케어 데모 통화 적재 완료")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n브라우저 새로고침 → 보호자 화면 → 리포트에서 확인하세요.")


if __name__ == "__main__":
    main()
