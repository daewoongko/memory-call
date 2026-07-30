"""근거 연결용 컬럼을 기존 DB 에 추가한다.

schema.sql 은 CREATE TABLE IF NOT EXISTS 라서 이미 만들어진 DB 에는 먹지 않는다.
그래서 같은 변경을 여기서 한 번 더 해야 한다. 나중에 Alembic 이 대신할 일이다.

여러 번 실행해도 안전하다.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

import db  # noqa: E402

ADDITIONS = [
    ("call_events", "utterance_id", "INTEGER"),
    ("call_events", "ai_utterance_id", "INTEGER"),
    ("medication_logs", "utterance_id", "INTEGER"),
]


def main() -> None:
    with db.connect() as conn:
        for table, column, coltype in ADDITIONS:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            if column in cols:
                print(f"  건너뜀  {table}.{column} 이미 있음")
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            print(f"  추가함  {table}.{column}")
        conn.commit()

        # 옛 기록이 몇 건이나 근거 없이 남는지 알려준다.
        # 되살리지 않는다. 시각으로 역추정하면 추정을 근거처럼 보여주게 된다.
        orphan = conn.execute(
            "SELECT COUNT(*) FROM call_events WHERE utterance_id IS NULL"
        ).fetchone()[0]
        blocks = conn.execute(
            "SELECT COUNT(*) FROM call_events WHERE event_type = 'safety_block'"
        ).fetchone()[0]

    print(f"\n근거 연결 이전 이벤트 {orphan}건 (그대로 둔다)")
    print(f"그중 safety_block {blocks}건 — 이제 기록하지 않는 종류")


if __name__ == "__main__":
    main()
