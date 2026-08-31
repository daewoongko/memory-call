"""배포 시작점: 고길동 단일 발표 DB를 준비하고 FastAPI를 실행한다."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import uvicorn  # noqa: E402


DEMO_DATE = "2026-09-01"
DEMO_DIARY_TITLE = "대웅이와 강가 공놀이"
DEMO_MEMORY_ID = "mem_016"
DEMO_MEMORY_TITLE = "대웅이와 강가 공놀이"


def _demo_seed_is_current() -> bool:
    if not db.DB_PATH.exists():
        return False
    conn = None
    try:
        conn = db.connect()
        calls = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_sec), 0) FROM calls "
            "WHERE substr(started_at, 1, 10) = ?",
            (DEMO_DATE,),
        ).fetchone()
        diary = conn.execute(
            "SELECT diary_title FROM heart_artworks "
            "WHERE diary_date = ? AND status = 'approved'",
            (DEMO_DATE,),
        ).fetchone()
        memory = conn.execute(
            "SELECT title, status, conversation_allowed FROM memories "
            "WHERE memory_id = ? AND elder_id = ?",
            (DEMO_MEMORY_ID, "elder_001"),
        ).fetchone()
        return (
            calls[0] == 40
            and calls[1] == 160 * 60
            and diary is not None
            and diary[0] == DEMO_DIARY_TITLE
            and memory is not None
            and memory[0] == DEMO_MEMORY_TITLE
            and memory[1] == "verified"
            and memory[2] == 1
        )
    except Exception:
        return False
    finally:
        if conn is not None:
            conn.close()


def _prepare_demo_database() -> None:
    demo_mode = os.getenv("DEMO_SEED_MODE", "").strip() == "gildong"
    if db.DB_PATH.exists() and (not demo_mode or _demo_seed_is_current()):
        return

    reason = "DB가 없음" if not db.DB_PATH.exists() else f"대표 시연일을 {DEMO_DATE}로 갱신"
    print(f"{reason}: 고길동 92일 발표 데이터로 초기화합니다: {db.DB_PATH}")
    temporary = db.DB_PATH.with_name(f"{db.DB_PATH.stem}.next{db.DB_PATH.suffix}")
    command = [
        sys.executable, str(ROOT / "tools" / "seed_gildong_demo.py"),
        "--database", str(temporary),
    ]
    if db.DB_PATH.exists():
        command.extend(["--preserve-from", str(db.DB_PATH)])
    subprocess.run(command, cwd=ROOT, check=True)
    os.replace(temporary, db.DB_PATH)


def main() -> None:
    _prepare_demo_database()

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "api:app", host="0.0.0.0", port=port, proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
