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

    # 공개 데모는 새 컨테이너마다 빈 SQLite로 시작할 수 있다. 명시적으로
    # 활성화된 환경에서만, 실제 통화가 한 건도 없을 때 현실적인 30일 데모를
    # 적재한다. 기존 사용자 통화가 있으면 절대 덮어쓰지 않는다.
    if os.getenv("DEMO_SEED_MODE") == "high_volume":
        with db.connect() as conn:
            call_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        if call_count == 0:
            print("빈 공개 데모 DB에 30일 통화 기록을 적재합니다.")
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "seed_high_volume_demo.py")],
                cwd=ROOT,
                check=True,
            )

        # 비교 환자는 배포의 영구 SQLite가 이미 존재해도 추가되어야 한다.
        # 둘 다 데모 전용 ID이므로 기존 실제 환자·통화는 건드리지 않는다.
        with db.connect() as conn:
            comparison_count = conn.execute(
                "SELECT COUNT(*) FROM elder_profiles "
                "WHERE elder_id IN ('elder_002', 'elder_003')"
            ).fetchone()[0]
        if comparison_count < 2:
            print("공개 데모 DB에 담당자 비교 환자 2명을 적재합니다.")
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "seed_comparison_elders.py")],
                cwd=ROOT,
                check=True,
            )

        # 7·8·9월 시연에서는 세 환자의 차이가 같은 집계 화면에서 분명히
        # 드러나야 한다. 전용 접두사만 교체하는 멱등 시드이므로 실제 통화는
        # 보존하며, 중간에 끊겨 일부만 적재된 경우에도 다음 시작 때 복구한다.
        with db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS demo_seed_versions ("
                "seed_name TEXT PRIMARY KEY, version TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            demo_789 = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT elder_id), "
                "MIN(SUBSTR(started_at,1,10)), MAX(SUBSTR(started_at,1,10)) "
                "FROM calls WHERE call_id LIKE 'demo789_%'"
            ).fetchone()
            demo_789_version = conn.execute(
                "SELECT version FROM demo_seed_versions WHERE seed_name='jul_sep_2026'"
            ).fetchone()
        demo_789_complete = (
            demo_789[0] >= 26000
            and demo_789[1] == 3
            and demo_789[2] == "2026-07-01"
            and demo_789[3] == "2026-09-30"
            and demo_789_version is not None
            and demo_789_version[0] == "patient-profile-trends-v2"
        )
        if not demo_789_complete:
            print("공개 데모 DB에 세 환자의 7·8·9월 통화 기록을 적재합니다.")
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "seed_demo_jul_sep_2026.py")],
                cwd=ROOT,
                check=True,
            )

        # 정서 유발 주제의 네 가지 요약과 버블 매트릭스도 로컬 데모와
        # 동일한 실제 집계 경로를 사용한다. 전용 접두사만 확인하므로
        # 사용자가 만든 통화나 기존 비교 환자 데이터는 덮어쓰지 않는다.
        with db.connect() as conn:
            emotion_demo_count = conn.execute(
                "SELECT COUNT(*) FROM calls "
                "WHERE elder_id = 'elder_002' "
                "AND call_id LIKE 'demo_emotion_sunja_%'"
            ).fetchone()[0]
        if emotion_demo_count == 0:
            print("공개 데모 DB에 박순자 어르신 정서 주제 통화를 적재합니다.")
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "seed_emotion_topic_demo.py")],
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
