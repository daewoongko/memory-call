"""발표 DB를 고길동 2026년 8~10월 기준 상태로 원자적으로 되돌린다."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402


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
    print("대표 시연일 2026-09-04 · 40통 · 160분 · 그림일기 92일")


if __name__ == "__main__":
    main()
