"""
시연 준비.

리허설을 여러 번 하려면 매번 같은 상태에서 시작해야 한다.
지난 통화 기록을 지우고, 기억을 시드 상태로 되돌리고,
복약 시간과 방문 일정을 시연 시각에 맞춰 다시 잡는다.

    python tools/demo_reset.py                  기본 (복약 2분 뒤)
    python tools/demo_reset.py --med-in 5       복약을 5분 뒤로
    python tools/demo_reset.py --no-med         복약 없이 (일반 통화 시연)
    python tools/demo_reset.py --keep-calls     통화 기록은 남기고 일정만 조정

시연 직전에 한 번 실행하면 된다.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402

SEED = ROOT / "data" / "seed.json"
GREEN, YELLOW, DIM, RESET = "\033[92m", "\033[93m", "\033[2m", "\033[0m"

# 통화가 남기는 것들. 시연 때마다 깨끗하게 비운다.
CALL_TABLES = ("recall_reviews", "reports", "call_events", "utterances",
               "medication_logs", "calls")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--med-in", type=int, default=2,
                    help="몇 분 뒤로 복약 시간을 잡을지 (기본 2분)")
    ap.add_argument("--no-med", action="store_true", help="복약 일정을 비활성화")
    ap.add_argument("--keep-calls", action="store_true", help="통화 기록 유지")
    ap.add_argument("--elder", default="elder_001")
    args = ap.parse_args()

    if not SEED.exists():
        sys.exit(f"{SEED} 없음")
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    now = datetime.now()

    conn = db.connect()
    db.init_schema(conn)

    if not args.keep_calls:
        for table in CALL_TABLES:
            conn.execute(f"DELETE FROM {table}")
        print(f"{DIM}통화 기록 삭제됨{RESET}")

    # 기억을 시드 상태로 되돌린다.
    # 시연 중 승인한 기억이 남아 있으면 "확인 대기" 장면이 재현되지 않는다.
    conn.execute("DELETE FROM memories WHERE elder_id = ?", (args.elder,))
    for m in seed["memories"]:
        db.insert(conn, "memories", dict(m, elder_id=args.elder))
    print(f"{DIM}기억 {len(seed['memories'])}개 복원{RESET}")

    # 방문 일정을 다가오는 주말로 옮긴다.
    # 지난 날짜면 프롬프트에 안 들어가서 "언제 와?" 장면이 죽는다.
    days_ahead = (5 - now.weekday()) % 7 or 7   # 다음 토요일
    visit = now.date() + timedelta(days=days_ahead)
    conn.execute("DELETE FROM schedules WHERE elder_id = ?", (args.elder,))
    db.insert(conn, "schedules", {
        "schedule_id": "sch_visit",
        "elder_id": args.elder,
        "title": "민준이 방문",
        "date": visit.isoformat(),
        "time": "14:00",
        "note": "주말 오후에 할아버지 댁 방문 예정",
        "confirmed": 1,
    })
    print(f"{DIM}방문 일정 → {visit.isoformat()} (토요일){RESET}")

    # 복약 일정을 시연 시각에 맞춘다.
    conn.execute("UPDATE medications SET active = 0 WHERE elder_id = ?", (args.elder,))
    if args.no_med:
        print(f"{DIM}복약 일정 비활성화{RESET}")
    else:
        at = now + timedelta(minutes=args.med_in)
        db.insert(conn, "medications", {
            "schedule_id": "med_demo",
            "elder_id": args.elder,
            "medication_name": "저녁 혈압약",
            "dosage_text": "1정",
            "scheduled_time": at.strftime("%H:%M"),
            "meal_relation": "after",
            "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
            "active": 1,
        })
        print(f"{DIM}복약 시간 → {at.strftime('%H:%M')} "
              f"({args.med_in}분 뒤){RESET}")

    conn.commit()

    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("memories", "schedules", "medications", "calls")
    }
    conn.close()

    print(f"\n{GREEN}시연 준비 완료{RESET}")
    for k, v in counts.items():
        print(f"  {k:14} {v}")

    print(f"\n{YELLOW}확인할 것{RESET}")
    print("  1. python tools/serve.py 가 켜져 있는가")
    print("  2. cd frontend && npm run dev 가 켜져 있는가")
    print("  3. Chrome 으로 localhost:5173 을 열었는가 (Safari 는 음성 인식 불가)")
    print("  4. 마이크 권한을 허용했는가")
    print("  5. 스피커 볼륨이 켜져 있는가")
    if not args.no_med:
        print(f"  6. {args.med_in}분 뒤 전화가 걸려온다. 그 전에 일반 통화를 먼저 시연할 것")
    print()


if __name__ == "__main__":
    main()
