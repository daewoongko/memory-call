"""
SQLite 접근 계층.

지금까지 persona.py가 seed.json을 직접 읽었는데, 이제 여기를 거친다.
load_context()의 반환 형태는 seed.json과 동일해서 persona.py는 그대로 동작한다.
"""

import json
import sqlite3

from storage import DB_PATH, ROOT, ensure_directories

SCHEMA_PATH = ROOT / "backend" / "schema.sql"

JSON_COLUMNS = {
    "anxiety_triggers", "calming_phrases", "frequent_questions",
    "emergency_contacts", "frequent_phrases", "forbidden_phrases",
    "participants", "days_of_week", "used_memory_ids", "used_schedule_ids",
    "unverified_recall", "safety_flags", "payload", "repeated_questions",
    "medication_summary", "new_recalls", "risk_summary", "guardian_actions",
}


def connect() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _row(row: sqlite3.Row) -> dict:
    """JSON 컬럼을 파싱해서 평범한 dict로."""
    out = {}
    for key in row.keys():
        value = row[key]
        if key in JSON_COLUMNS and isinstance(value, str) and value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        out[key] = value
    return out


def _dump(value):
    """리스트·딕셔너리는 JSON 문자열로, 나머지는 그대로."""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value


def insert(conn: sqlite3.Connection, table: str, data: dict) -> int:
    """새로 넣은 행의 rowid 를 돌려준다.

    이벤트를 어느 발화 때문에 만들었는지 잇기 위해 필요하다.
    반환값이 필요 없는 호출부는 그냥 무시하면 된다.
    """
    cols = ", ".join(data)
    marks = ", ".join("?" * len(data))
    cur = conn.execute(
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
        [_dump(v) for v in data.values()],
    )
    return cur.lastrowid


# ------------------------------------------------------------------ 조회

def personas(elder_id: str = "elder_001") -> list[dict]:
    """통화 대상 목록. 등록이 끝난 사람과 대기 중인 사람을 함께 준다."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM personas WHERE elder_id = ? "
            "ORDER BY active DESC, created_at", (elder_id,)
        ).fetchall()
    return [_row(r) for r in rows]


def load_context(elder_id: str = "elder_001",
                 persona_id: str | None = None) -> dict:
    """대화에 필요한 컨텍스트 전체. seed.json과 같은 구조를 돌려준다."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} 가 없습니다. python tools/init_db.py 를 먼저 실행하세요."
        )

    with connect() as conn:
        elder = conn.execute(
            "SELECT * FROM elder_profiles WHERE elder_id = ?", (elder_id,)
        ).fetchone()
        if elder is None:
            raise ValueError(f"elder_id={elder_id} 없음")

        # 통화 상대를 지정하지 않으면 등록이 끝난 첫 사람과 연결한다
        if persona_id:
            persona = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ?", (persona_id,)
            ).fetchone()
        else:
            persona = conn.execute(
                "SELECT * FROM personas WHERE elder_id = ? AND active = 1 "
                "ORDER BY created_at LIMIT 1",
                (elder_id,),
            ).fetchone()

        memories = conn.execute(
            "SELECT * FROM memories WHERE elder_id = ? ORDER BY memory_id",
            (elder_id,),
        ).fetchall()

        # 지난 일정은 프롬프트에 넣지 않는다. 과거 약속을 미래로 착각시키지 않기 위함.
        schedules = conn.execute(
            "SELECT * FROM schedules WHERE elder_id = ? AND confirmed = 1 "
            "AND date >= date('now','localtime') ORDER BY date",
            (elder_id,),
        ).fetchall()

        medications = conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
            "ORDER BY scheduled_time",
            (elder_id,),
        ).fetchall()

    return {
        "elder": _row(elder),
        "persona": _row(persona) if persona else {},
        "memories": [_row(m) for m in memories],
        "schedules": [_row(s) for s in schedules],
        "medications": [_row(m) for m in medications],
    }


def get_memory(memory_id: str) -> dict | None:
    """safety.py가 인용된 기억의 status를 확인할 때 쓴다."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
    return _row(row) if row else None
