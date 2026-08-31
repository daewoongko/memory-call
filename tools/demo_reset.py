"""발표 DB를 고길동 2026년 8~10월 기준 상태로 원자적으로 되돌린다."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
from tools.demo_config import (  # noqa: E402
    DEMO_CALL_COUNT,
    DEMO_DATE,
    DEMO_DIARY_COUNT,
    DEMO_DURATION_MINUTES,
)


def main() -> None:
    target = db.DB_PATH.resolve()
    temporary = target.with_name(f"{target.stem}.reset{target.suffix}")
    command = [
        sys.executable, str(ROOT / "tools" / "seed_gildong_demo.py"),
        "--database", str(temporary),
    ]
    if target.exists():
        command.extend(["--preserve-from", str(target)])
    subprocess.run(command, cwd=ROOT, check=True)
    os.replace(temporary, target)
    print(f"시연 준비 완료: {target}")
    print(
        f"대표 시연일 {DEMO_DATE} · {DEMO_CALL_COUNT}통 · "
        f"{DEMO_DURATION_MINUTES}분 · 그림일기 {DEMO_DIARY_COUNT}일"
    )


if __name__ == "__main__":
    main()
