"""고길동 한 사람의 2026년 8~10월 발표 시연 DB를 만든다.

그림일기는 날짜별 대표 통화의 실제 발화, 확인된 기억, 승인된 그림을
한 행으로 연결한다. 모든 요약 수치는 이 스크립트가 넣은 calls/utterances/
reports에서 다시 집계할 수 있으며 화면 전용 통계 행은 만들지 않는다.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "backend" / "schema.sql"
SEED = ROOT / "data" / "seed.json"
DIARIES = ROOT / "data" / "gildong_diaries_2026.json"
DEFAULT_OUTPUT = ROOT / "data" / "memory_call.presentation.sqlite"
DEMO_DAY = date(2026, 9, 4)

PERSONA_IDS = (
    "persona_godaewoong", "persona_jeonghun", "persona_miyeong", "persona_yujin",
)

DOMAIN_SCENARIOS = (
    ("orientation", "time_confusion", "오늘이 무슨 요일인지 또 헷갈리네.", "시간 혼동"),
    ("memory", "recent_event_confusion", "아침을 먹었던가, 기억이 잘 안 나네.", "최근 사건 혼동"),
    ("language", "word_finding_difficulty", "그… 뭐더라, 말이 생각이 안 나네.", "단어 찾기 어려움"),
    ("executive_judgment", "task_sequencing_difficulty", "차를 끓이려는데 뭐부터 해야 할지 모르겠어.", "행동 순서 어려움"),
    ("emotion", "loneliness", "저녁에 혼자 있으니까 조금 외롭구나.", "외로움"),
    ("behavior_agitation", "agitation", "큰일 났네, 빨리 열쇠를 찾아야 해.", "초조"),
    ("daily_living", "item_location_uncertain", "리모컨이 어디 있는지 못 찾겠어.", "물건 위치 불확실"),
    ("safety_physical", "dizziness", "일어날 때 잠깐 어지럽네.", "어지럼"),
)

AI_REPLIES = {
    "orientation": "괜찮아요. 오늘 날짜를 화면에서 함께 천천히 확인해 볼게요.",
    "memory": "괜찮아요. 식사 여부는 가족이 직접 확인할 수 있게 기록해 둘게요.",
    "language": "서두르지 않으셔도 돼요. 생각나시는 만큼 천천히 말씀해 주세요.",
    "executive_judgment": "한 번에 하나씩 해 볼까요? 우선 컵부터 준비해 보세요.",
    "emotion": "제가 잘 듣고 있어요. 외로운 마음도 천천히 말씀해 주세요.",
    "behavior_agitation": "괜찮아요. 잠깐 숨을 고르고, 자주 두는 자리부터 같이 떠올려 봐요.",
    "daily_living": "자주 두는 탁자와 소파 옆부터 천천히 살펴보세요.",
    "safety_physical": "지금은 앉아서 쉬시고, 계속 어지러우면 가족에게 바로 알려 주세요.",
}

DEMO_DOMAIN_COUNTS = {
    "orientation": 3,
    "memory": 2,
    "language": 2,
    "executive_judgment": 1,
    "emotion": 3,
    "behavior_agitation": 1,
    "daily_living": 2,
    "safety_physical": 1,
}

LIFE_STAGE_DIALOGUES = {
    16: (
        "학교 다닐 때 교실 창가 자리에 앉아 선생님 말씀을 받아 적곤 했지.",
        "학창 시절 교실 풍경이 떠오르셨군요. 그때 친구 이야기도 들려주세요.",
    ),
    20: (
        "애들 밥을 챙겨 주고 옷을 입히느라 아침마다 참 분주했어.",
        "자녀들을 돌보던 아침의 역할이 또렷하게 떠오르셨군요.",
    ),
    24: (
        "회사에 출근하면 작업대부터 살피고 동료들과 하루 일을 시작했지.",
        "직장에 다니시던 시절의 하루 순서를 기억하고 계시는군요.",
    ),
    30: (
        "가족을 먹여 살리려고 돈 벌러 나가던 때에는 책임감이 컸어.",
        "가족을 책임지던 시절의 마음이 떠오르셨군요. 천천히 더 들려주세요.",
    ),
    34: (
        "회사 회의가 있는 날이면 일찍 출근해 자료부터 챙겼어.",
        "직장 생활 때 맡았던 역할과 준비 과정이 생생하게 남아 있군요.",
    ),
}

REPEATED_QUESTION = "오늘이 무슨 요일이지?"


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def first_person(text: str) -> str:
    sentence = (text or "").split(". ", 1)[0].strip().rstrip(".")
    replacements = (
        ("할아버지가", "내가"), ("할아버지는", "나는"),
        ("손자와", "대웅이와"), ("손자가", "대웅이가"),
        ("손녀와", "유진이와"), ("손녀가", "유진이가"),
        ("딸이", "미영이가"), ("딸과", "미영이와"),
        ("아들이", "정훈이가"), ("아들과", "정훈이와"),
    )
    for old, new in replacements:
        sentence = sentence.replace(old, new)
    return f"그때 {sentence}. 참 좋았지."


def insert(conn: sqlite3.Connection, table: str, row: dict) -> int:
    columns = list(row)
    values = [dump(row[name]) if isinstance(row[name], (list, dict)) else row[name] for name in columns]
    marks = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})", values,
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def create_base(conn: sqlite3.Connection, seed: dict) -> None:
    elder = dict(seed["elder"])
    insert(conn, "elder_profiles", elder)
    for persona in seed["personas"]:
        insert(conn, "personas", {**persona, "elder_id": elder["elder_id"]})
    for memory in seed["memories"]:
        insert(conn, "memories", {**memory, "elder_id": elder["elder_id"]})


def preserve_persona_media(conn: sqlite3.Connection, source_path: Path) -> None:
    if not source_path.exists():
        return
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        for table in ("persona_voice_profiles", "persona_voice_samples", "persona_avatar_profiles"):
            if not source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            destination_columns = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})")
            }
            rows = source.execute(
                f"SELECT * FROM {table} WHERE persona_id IN ({','.join('?' for _ in PERSONA_IDS)})",
                PERSONA_IDS,
            ).fetchall()
            for source_row in rows:
                row = {key: source_row[key] for key in source_row.keys() if key in destination_columns}
                if row:
                    columns = list(row)
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) "
                        f"VALUES ({','.join('?' for _ in columns)})",
                        [row[name] for name in columns],
                    )
    finally:
        source.close()


def call_count(day: date) -> int:
    if day == DEMO_DAY:
        return 40
    return 36 + ((day.toordinal() * 7 + day.day * 3) % 9)


def call_type_for(day: date, index: int) -> str:
    if day == DEMO_DAY:
        if index < 36:
            return "ai"
        if index < 38:
            return "direct"
        return "ai_to_direct"
    if index and index % 29 == 0:
        return "direct"
    if index and index % 37 == 0:
        return "ai_to_direct"
    return "ai"


def durations_for(day: date, count: int, rng: random.Random) -> list[int]:
    values = [rng.randint(150, 330) for _ in range(count)]
    if day == DEMO_DAY:
        target = 160 * 60
        values[-1] += target - sum(values)
    return values


def observation_plan(day: date) -> list[tuple[str, str, str, str]]:
    """날짜마다 영역 빈도를 달리하되 시연일에는 8개 영역을 모두 보인다."""
    counts = {}
    for position, (domain, *_rest) in enumerate(DOMAIN_SCENARIOS):
        counts[domain] = (day.toordinal() + position * 2) % 3
    if day.day in (9, 23):
        counts["safety_physical"] = max(1, counts["safety_physical"])
    if day == DEMO_DAY:
        counts = DEMO_DOMAIN_COUNTS
    return [
        scenario
        for scenario in DOMAIN_SCENARIOS
        for _ in range(counts[scenario[0]])
    ]


def repeated_call_indexes(day: date) -> tuple[int, ...]:
    # 9/4에는 후반으로 갈수록 같은 질문의 간격이 실제로 짧아지도록 둔다.
    return (17, 23, 28, 33, 37, 39) if day == DEMO_DAY else (8, 17, 26, 35)


def call_gap_minutes(day: date, index: int) -> int:
    if day == DEMO_DAY:
        if index <= 18:
            return 12
        if index <= 28:
            return 10
        return 8
    return 9 + ((day.toordinal() + index * 3) % 5)


def start_offset_minutes(day: date, index: int) -> int:
    return sum(call_gap_minutes(day, position) for position in range(1, index + 1))


def stable_dialogue(day: date, index: int) -> tuple[str, str]:
    if index in repeated_call_indexes(day):
        return (
            REPEATED_QUESTION,
            "오늘 날짜와 요일을 화면에서 다시 함께 확인해 볼게요.",
        )
    if index in LIFE_STAGE_DIALOGUES:
        return LIFE_STAGE_DIALOGUES[index]
    if index == 27:
        return (
            "통장에 둔 돈을 잘 챙겼는지 걱정되는구나.",
            "통장에 둔 돈이 걱정되시는군요. 가족이 확인할 수 있게 말씀하신 내용을 남겨 둘게요.",
        )
    subjects = (
        "창가의 햇볕", "마당의 상추", "나무 의자", "저녁 노을", "빗소리",
        "가족 사진", "따뜻한 차", "동네 산책길", "라디오 음악", "화분의 새잎",
        "시장 과일", "바닷가 모래", "오래된 공구", "골목의 은행나무",
    )
    reflections = (
        "한참 바라보니 마음이 편안해졌어.",
        "예전 가족들과 보낸 시간이 생각났어.",
        "손으로 천천히 살펴보니 기억이 또렷해졌지.",
        "대웅이에게도 다음에 이 이야기를 들려주고 싶구나.",
        "계절이 바뀌는 모습이 참 반갑더라.",
    )
    subject = subjects[index % len(subjects)]
    reflection = reflections[(index // len(subjects) + day.day) % len(reflections)]
    return (
        f"{subject}을 떠올리며 {reflection}",
        f"{subject}에 담긴 기억을 말씀해 주셨군요. 그 장면을 천천히 이어서 들려주세요.",
    )


def add_call(
    conn: sqlite3.Connection, diary: dict, day: date, index: int, duration: int,
    previous_artwork_by_story: dict[str, str],
) -> None:
    call_id = f"demo-{day:%Y%m%d}-{index + 1:03d}"
    started = datetime.combine(day, time(7, 0)) + timedelta(minutes=start_offset_minutes(day, index))
    ended = started + timedelta(seconds=duration)
    call_type = call_type_for(day, index)
    persona_id = PERSONA_IDS[index % len(PERSONA_IDS)]
    names = {
        "persona_godaewoong": ("대웅", "손자"), "persona_jeonghun": ("정훈", "아들"),
        "persona_miyeong": ("미영", "딸"), "persona_yujin": ("유진", "손녀"),
    }
    counterpart, relation = names[persona_id]
    insert(conn, "calls", {
        "call_id": call_id, "elder_id": "elder_001", "persona_id": persona_id,
        "counterpart_name": counterpart, "counterpart_relation": relation,
        "report_title": diary["title"] if index == 0 else f"{counterpart}과 나눈 추억 통화",
        "call_type": call_type, "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"), "duration_sec": duration,
        "end_reason": "completed", "status": "ended",
    })

    care_data = {"source_utterance_id": None, "observations": [], "meaningful_moments": []}
    used_memory_ids: list[str] = []
    meaningful: list[dict] = []
    care_summary = {domain: [] for domain, *_ in DOMAIN_SCENARIOS}

    if index == 0:
        elder_text = first_person(diary["writing"])
        ai_text = "그 장면을 또렷하게 기억하고 계시는군요. 오늘 말씀을 가족이 함께 볼 수 있게 소중히 기록해 둘게요."
        used_memory_ids = [diary["memory_id"]]
        moment = {
            "category": "joy", "label": "기뻤던 시간", "evidence": elder_text,
            "at": started.isoformat(timespec="seconds"),
            "related_memory_ids": used_memory_ids,
        }
        meaningful = [moment]
    else:
        plan = observation_plan(day)
        observation = plan[index - 1] if 1 <= index <= len(plan) else None
        if observation:
            domain, signal, elder_text, label = observation
            ai_text = AI_REPLIES[domain]
            care_summary[domain] = [{
                "signal": signal, "label": label, "evidence": elder_text,
                "at": started.isoformat(timespec="seconds"),
            }]
        else:
            elder_text, ai_text = stable_dialogue(day, index)
            if index % 17 == 0 and elder_text != REPEATED_QUESTION:
                meaningful = [{
                    "category": "affection", "label": "가족을 향한 애정",
                    "evidence": elder_text, "at": started.isoformat(timespec="seconds"),
                    "related_memory_ids": [],
                }]

    elder_id = insert(conn, "utterances", {
        "call_id": call_id, "seq": 1, "speaker": "elder", "transcript": elder_text,
        "used_memory_ids": [], "care_data": None, "safety_flags": [],
        "was_rewritten": 0, "latency_ms": None,
        "created_at": started.isoformat(timespec="seconds"),
    })
    observations = [
        {**item, "domain": domain, "source_utterance_id": elder_id, "verification": "verified"}
        for domain, items in care_summary.items() for item in items
    ]
    care_data.update({
        "source_utterance_id": elder_id, "observations": observations,
        "meaningful_moments": [
            {"category": item["category"], "related_memory_ids": item.get("related_memory_ids", [])}
            for item in meaningful
        ],
    })
    insert(conn, "utterances", {
        "call_id": call_id, "seq": 2, "speaker": "ai", "transcript": ai_text,
        "certainty": "verified" if used_memory_ids else "general",
        "used_memory_ids": used_memory_ids, "care_data": care_data, "safety_flags": [],
        "was_rewritten": 0, "latency_ms": 640 + (index % 9) * 37,
        "created_at": (started + timedelta(seconds=18)).isoformat(timespec="seconds"),
    })

    repeated_questions = []
    if elder_text == REPEATED_QUESTION:
        repeated_questions = [{
            "question": REPEATED_QUESTION,
            "count": 1,
            "utterance_ids": [elder_id],
        }]

    # 안전 이벤트도 별도 화면용 숫자가 아니라 실제 발화와 통화에 연결한다.
    risk_summary: list[dict] = []
    first_safety_index = next((
        position for position, scenario in enumerate(observation_plan(day), start=1)
        if scenario[0] == "safety_physical"
    ), -1)
    if day.day in (9, 23) and index == first_safety_index:
        payload = {"type": "fall", "level": "medium", "evidence": elder_text}
        event_id = insert(conn, "call_events", {
            "call_id": call_id, "utterance_id": elder_id, "event_type": "risk",
            "payload": payload, "acknowledged": 0,
            "created_at": started.isoformat(timespec="seconds"),
        })
        risk_summary = [{"event_id": event_id, **payload}]

    insert(conn, "reports", {
        "call_id": call_id,
        "summary": "실제 통화 발화를 바탕으로 가족이 확인할 내용을 정리했습니다.",
        "repeated_questions": repeated_questions, "new_recalls": [], "risk_summary": risk_summary,
        "care_summary": care_summary, "meaningful_moments": meaningful,
        "family_mentions": [],
        "guardian_actions": ["현재 상태를 직접 확인해 주세요."] if risk_summary else [],
        "created_at": ended.isoformat(timespec="seconds"),
    })

    if index == 0:
        artwork_id = f"art-{day:%Y%m%d}"
        previous = previous_artwork_by_story.get(diary["storyline"])
        insert(conn, "heart_artworks", {
            "artwork_id": artwork_id, "call_id": call_id,
            "source_utterance_id": elder_id, "memory_id": diary["memory_id"],
            "status": "approved", "image_url": diary["image"],
            "source_quote": elder_text, "alt_text": f"{diary['title']}을 따뜻하게 그린 그림일기",
            "caption": diary["writing"], "prompt_summary": diary["insight"],
            "diary_date": diary["date"], "diary_title": diary["title"],
            "mood_label": diary["mood"], "storyline_id": diary["storyline"],
            "storyline_chapter": diary["chapter"], "previous_artwork_id": previous,
            "continuity_note": diary["continuity_note"],
            "created_at": ended.isoformat(timespec="seconds"),
        })
        previous_artwork_by_story[diary["storyline"]] = artwork_id


def validate(conn: sqlite3.Connection) -> dict:
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("elder_profiles", "personas", "calls", "utterances", "reports", "heart_artworks")
    }
    elder_ids = conn.execute("SELECT group_concat(elder_id) FROM elder_profiles").fetchone()[0]
    demo = conn.execute(
        "SELECT COUNT(*), SUM(duration_sec) FROM calls WHERE substr(started_at,1,10)=?",
        (DEMO_DAY.isoformat(),),
    ).fetchone()
    types = dict(conn.execute(
        "SELECT call_type, COUNT(*) FROM calls WHERE substr(started_at,1,10)=? GROUP BY call_type",
        (DEMO_DAY.isoformat(),),
    ).fetchall())
    dates = conn.execute(
        "SELECT MIN(diary_date), MAX(diary_date), COUNT(DISTINCT diary_date) FROM heart_artworks WHERE status='approved'"
    ).fetchone()
    result = {
        **counts, "elder_ids": elder_ids,
        "demo_day": {"date": DEMO_DAY.isoformat(), "calls": demo[0], "minutes": demo[1] // 60, "types": types},
        "diary_range": {"start": dates[0], "end": dates[1], "days": dates[2]},
    }
    assert elder_ids == "elder_001"
    assert result["heart_artworks"] == 92 and dates[2] == 92
    assert result["demo_day"] == {
        "date": "2026-09-04", "calls": 40, "minutes": 160,
        "types": {"ai": 36, "ai_to_direct": 2, "direct": 2},
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preserve-from", type=Path)
    args = parser.parse_args()
    output = args.database.resolve()
    if output.exists():
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    diary_payload = json.loads(DIARIES.read_text(encoding="utf-8"))
    diaries = diary_payload["diaries"]
    assert len(diaries) == 92

    conn = sqlite3.connect(output)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(
            "CREATE UNIQUE INDEX idx_heart_artworks_diary_day "
            "ON heart_artworks(diary_date) WHERE status = 'approved'"
        )
        create_base(conn, seed)
        if args.preserve_from:
            preserve_persona_media(conn, args.preserve_from.resolve())
        rng = random.Random(20260828)
        previous_artwork_by_story: dict[str, str] = {}
        for diary in diaries:
            day = date.fromisoformat(diary["date"])
            count = call_count(day)
            durations = durations_for(day, count, rng)
            for index, duration in enumerate(durations):
                add_call(conn, diary, day, index, duration, previous_artwork_by_story)
        conn.commit()
        print(json.dumps(validate(conn), ensure_ascii=False, indent=2))
    finally:
        conn.close()
    print(f"presentation database: {output}")


if __name__ == "__main__":
    main()
