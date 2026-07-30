"""
기존 DB 를 지우지 않고 스키마 변경을 적용한다.

    python tools/migrate.py           # 필요한 것만 적용
    python tools/migrate.py --check   # 적용하지 않고 확인만

SQLite 는 CHECK 제약을 ALTER 로 바꿀 수 없다. 테이블을 새로 만들어 데이터를
옮기고 이름을 바꾸는 수밖에 없다 (SQLite 공식 문서의 "Making Other Kinds Of
Table Schema Changes" 절차).

그 절차의 핵심은 **작업 중 foreign_keys 를 꺼 두는 것**이다. 켜 둔 상태로
ALTER TABLE ... RENAME 을 하면 SQLite 가 다른 테이블의 REFERENCES 절까지
새 이름으로 고쳐 버린다.

각 마이그레이션은 여러 번 돌려도 안전해야 한다 (idempotent).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402

GREEN, YELLOW, DIM, RESET = "\033[92m", "\033[93m", "\033[2m", "\033[0m"


def _table_sql(conn, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row["sql"] if row else ""


def _columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _rebuild(conn, table: str, create_sql: str) -> None:
    """테이블을 새 정의로 재구축하면서 데이터를 그대로 옮긴다.

    create_sql 은 `{tmp}` 자리에 임시 테이블 이름이 들어간 CREATE 문이어야 한다.
    공통 컬럼만 복사하므로 컬럼이 늘어난 경우에도 동작한다.
    """
    tmp = f"{table}__migrating"
    old_cols = _columns(conn, table)

    conn.executescript(create_sql.format(tmp=tmp))
    new_cols = _columns(conn, tmp)
    shared = [c for c in old_cols if c in new_cols]
    cols = ", ".join(shared)

    conn.execute(f"INSERT INTO {tmp} ({cols}) SELECT {cols} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


# ------------------------------------------------------------------ 마이그레이션

CALLS_SQL = """
CREATE TABLE {tmp} (
    call_id      TEXT PRIMARY KEY,
    elder_id     TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    persona_id   TEXT REFERENCES personas(persona_id),
    call_type    TEXT DEFAULT 'ai' CHECK (call_type IN ('direct','ai','ai_to_direct')),
    started_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at     TEXT,
    duration_sec INTEGER,
    end_reason   TEXT,
    status       TEXT DEFAULT 'ai_disclosure'
                 CHECK (status IN ('requested','ai_disclosure','active',
                                   'human_handoff','ended','failed'))
);
"""

MEDLOG_SQL = """
CREATE TABLE {tmp} (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    elder_id      TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    schedule_id   TEXT NOT NULL REFERENCES medications(schedule_id),
    call_id       TEXT,
    taken_date    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN
                     ('USER_CONFIRMED','UNCLEAR','REFUSED','DUPLICATE_SUSPECTED',
                      'GUARDIAN_CONFIRMED')),
    evidence_text TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def needs_call_states(conn) -> bool:
    return "ai_disclosure" not in _table_sql(conn, "calls")


def needs_guardian_confirmed(conn) -> bool:
    return "GUARDIAN_CONFIRMED" not in _table_sql(conn, "medication_logs")


MIGRATIONS = [
    (
        "calls.status 에 ai_disclosure / human_handoff 추가",
        needs_call_states,
        lambda conn: _rebuild(conn, "calls", CALLS_SQL),
    ),
    (
        "medication_logs.status 에 GUARDIAN_CONFIRMED 추가",
        needs_guardian_confirmed,
        lambda conn: (
            _rebuild(conn, "medication_logs", MEDLOG_SQL),
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_medlog_day "
                "ON medication_logs(elder_id, taken_date, schedule_id)"
            ),
        ),
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="적용하지 않고 확인만")
    args = ap.parse_args()

    if not db.DB_PATH.exists():
        print(f"{DIM}{db.DB_PATH} 가 없습니다. "
              f"python tools/init_db.py 를 실행하면 최신 스키마로 만들어집니다.{RESET}")
        return 0

    conn = db.connect()
    # 재구축 중에는 FK 를 꺼야 한다. 위 docstring 참고.
    conn.execute("PRAGMA foreign_keys = OFF")

    pending = [(name, apply) for name, check, apply in MIGRATIONS if check(conn)]

    if not pending:
        print(f"{GREEN}적용할 마이그레이션이 없습니다.{RESET} 스키마가 최신입니다.")
        conn.close()
        return 0

    print(f"{YELLOW}적용할 마이그레이션 {len(pending)}개{RESET}")
    for name, _ in pending:
        print(f"  · {name}")

    if args.check:
        print(f"\n{DIM}--check 이므로 적용하지 않았습니다.{RESET}")
        conn.close()
        return 1

    conn.execute("BEGIN")
    try:
        for name, apply in pending:
            apply(conn)
            print(f"{GREEN}✓{RESET} {name}")

        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"외래키 검사 실패: {broken[:5]}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        print(f"\n{YELLOW}실패해서 되돌렸습니다. DB 는 그대로입니다.{RESET}")
        conn.close()
        raise

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print(f"\n{GREEN}완료{RESET} → {db.DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
