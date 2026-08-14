"""
SQLite 접근 계층.

지금까지 persona.py가 seed.json을 직접 읽었는데, 이제 여기를 거친다.
load_context()의 반환 형태는 seed.json과 동일해서 persona.py는 그대로 동작한다.
"""

import json
import re
import sqlite3

from storage import DB_PATH, ROOT, ensure_directories

SCHEMA_PATH = ROOT / "backend" / "schema.sql"

JSON_COLUMNS = {
    "anxiety_triggers", "calming_phrases", "frequent_questions",
    "emergency_contacts", "household_members", "frequent_phrases",
    "forbidden_phrases",
    "call_style_scores", "call_style_answers",
    "participants", "days_of_week", "used_memory_ids", "used_schedule_ids",
    "unverified_recall", "care_data", "safety_flags", "payload", "repeated_questions",
    "medication_summary", "new_recalls", "risk_summary", "guardian_actions",
    "care_summary", "meaningful_moments", "family_mentions",
    "care_baseline", "medical_cautions",
    "monitoring_points", "observed_flags",
}

# CREATE TABLE IF NOT EXISTS 는 이미 있는 테이블에 새 컬럼을 붙이지 않는다.
# 시연 DB 를 지우지 않고도 스키마를 따라가게 하려고 여기서 직접 채운다.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "elder_profiles": {
        "residence_type": "TEXT",
        "household_members": "TEXT",
        "diagnosis_label": "TEXT",
        "care_baseline": "TEXT",
        "medical_cautions": "TEXT",
    },
    "personas": {
        "call_style_code": "TEXT",
        "call_style_name": "TEXT",
        "call_style_scores": "TEXT",
        "call_style_answers": "TEXT",
    },
    "utterances": {
        "care_data": "TEXT",
    },
    "calls": {
        "counterpart_name": "TEXT",
        "counterpart_relation": "TEXT",
        "report_title": "TEXT",
        "call_type": "TEXT DEFAULT 'ai'",
    },
    "reports": {
        "care_summary": "TEXT",
        "meaningful_moments": "TEXT",
        "family_mentions": "TEXT",
    },
    "medications": {
        "indication": "TEXT",
        "monitoring_points": "TEXT",
        "review_interval_days": "INTEGER DEFAULT 14",
        "escalation_criteria": "TEXT",
    },
    "call_events": {
        "acknowledged_at": "TEXT",
    },
    "memories": {
        "photo_url": "TEXT",
        "happened_year": "INTEGER",
    },
}


def connect() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """새로 생긴 컬럼만 붙인다. 이미 있으면 아무것도 하지 않는다."""
    added = []
    for table, columns in ADDED_COLUMNS.items():
        present = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if not present:
            continue  # 테이블 자체가 방금 만들어졌으면 스키마에 이미 들어 있다
        for name, decl in columns.items():
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(f"{table}.{name}")
    return added


def init_schema(conn: sqlite3.Connection) -> list[str]:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_call_invite_reasons(conn)
    added = _add_missing_columns(conn)
    _migrate_demo_personas(conn)
    conn.commit()
    return added


def _migrate_call_invite_reasons(conn: sqlite3.Connection) -> None:
    """기존 DB의 CHECK 제약에 미디어 권한 거부 사유를 추가한다."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='call_invites'"
    ).fetchone()
    if not row or "media_permission_denied" in (row["sql"] or ""):
        return
    conn.executescript("""
        CREATE TABLE call_invites_next (
            invite_id TEXT PRIMARY KEY,
            elder_id TEXT NOT NULL REFERENCES elder_profiles(elder_id),
            persona_id TEXT REFERENCES personas(persona_id),
            from_device TEXT, to_device TEXT,
            state TEXT NOT NULL CHECK (state IN
                ('ringing','answered','declined','timeout','ai_takeover','ended','cancelled')),
            ring_timeout_sec INTEGER NOT NULL DEFAULT 15,
            no_live_device INTEGER DEFAULT 0,
            takeover_reason TEXT CHECK (takeover_reason IN
                ('declined','timeout','no_device','transport_failed','media_permission_denied')),
            ai_call_id TEXT REFERENCES calls(call_id),
            created_at TEXT NOT NULL, answered_at TEXT, ended_at TEXT
        );
        INSERT INTO call_invites_next SELECT * FROM call_invites;
        DROP TABLE call_invites;
        ALTER TABLE call_invites_next RENAME TO call_invites;
        CREATE INDEX IF NOT EXISTS idx_invite_ring
            ON call_invites(persona_id, state, created_at);
        CREATE INDEX IF NOT EXISTS idx_invite_elder
            ON call_invites(elder_id, created_at);
    """)


def _migrate_demo_personas(conn: sqlite3.Connection) -> None:
    """초기 데모의 낡은 가족 ID를 현재 네 가족으로 합친다.

    이미 생성된 DB에는 초기 시안에서 쓰던 이름이 남을 수 있다. 통화의
    참조를 먼저 현재 ID로 옮긴 뒤 낡은 행만 지워 기존 기록을 보존한다.
    """
    migrations = {
        "persona_" + "".join(("dae", "woong")): (
            "persona_minjun", "민준", "손자", "우리 민준이",
        ),
        "persona_minsu": ("persona_jeonghun", "정훈", "아들", "우리 정훈이"),
        "persona_jieun": ("persona_miyeong", "미영", "딸", "우리 미영이"),
        "persona_ssuah": ("persona_yujin", "유진", "손녀", "우리 유진이"),
    }
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(personas)")]
    for legacy_id, (current_id, display_name, relationship, elder_call) in migrations.items():
        legacy = conn.execute(
            "SELECT * FROM personas WHERE persona_id = ?", (legacy_id,),
        ).fetchone()
        if legacy is None:
            continue
        current = conn.execute(
            "SELECT 1 FROM personas WHERE persona_id = ?", (current_id,),
        ).fetchone()
        if current is None:
            values = dict(zip(columns, legacy))
            values.update({
                "persona_id": current_id,
                "display_name": display_name,
                "relationship_type": relationship,
                "elder_calls_family": elder_call,
            })
            insert(conn, "personas", values)
        conn.execute(
            "UPDATE calls SET persona_id = ?, counterpart_name = ?, "
            "counterpart_relation = ? WHERE persona_id = ?",
            (current_id, display_name, relationship, legacy_id),
        )
        conn.execute("DELETE FROM personas WHERE persona_id = ?", (legacy_id,))


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


def update(conn: sqlite3.Connection, table: str, id_column: str,
           id_value, data: dict) -> None:
    """한 행의 지정된 컬럼만 갱신한다.

    백그라운드 LLM이 뒤늦게 리포트 메타데이터를 채울 때 사용한다.
    ``INSERT OR REPLACE``와 달리 먼저 저장한 원문·근거·안전 필드를
    지우지 않는다. 테이블명과 컬럼명은 내부 상수만 받도록 검증한다.
    """
    if not data:
        return
    identifiers = [table, id_column, *data]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
           for value in identifiers):
        raise ValueError("invalid SQL identifier")
    assignments = ", ".join(f"{column} = ?" for column in data)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE {id_column} = ?",
        [_dump(value) for value in data.values()] + [id_value],
    )


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
