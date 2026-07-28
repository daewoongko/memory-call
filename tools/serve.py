"""
API 서버 실행.

    python tools/serve.py             # http://localhost:8000
    python tools/serve.py --port 8010

브라우저에서 http://localhost:8000/docs 를 열면 각 엔드포인트를
클릭만으로 테스트할 수 있다.

※ __main__ 가드가 필요한 이유
   reload=True 이면 uvicorn 이 파일 감시용 자식 프로세스를 띄우고,
   그 자식은 이 스크립트를 다시 불러온다. 가드가 없으면 자식에서도
   uvicorn.run() 이 실행되어 같은 포트를 두 번 잡으려다 실패한다.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-reload", action="store_true",
                    help="파일 변경 감시를 끈다")
    args = ap.parse_args()

    print(f"\n  API      http://{args.host}:{args.port}/api/health")
    print(f"  문서     http://{args.host}:{args.port}/docs")
    print(f"  종료     Ctrl + C\n")

    uvicorn.run(
        "api:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        reload_dirs=[str(ROOT / "backend")],
    )


if __name__ == "__main__":
    main()