"""배포용 시작점: DB를 처음 한 번 만들고 FastAPI를 공개 포트로 실행한다."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import uvicorn  # noqa: E402


def main() -> None:
    if not db.DB_PATH.exists():
        print(f"DB가 없어 시드 데이터로 초기화합니다: {db.DB_PATH}")
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "init_db.py")],
            cwd=ROOT,
            check=True,
        )

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        # Do not trust arbitrary client-supplied X-Forwarded-For values. A
        # different trusted proxy range must be configured explicitly.
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
