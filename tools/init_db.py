"""
seed.json 을 읽어 SQLite 데이터베이스를 만든다.

    python tools/init_db.py           # 없으면 생성, 있으면 시드만 다시 넣음
    python tools/init_db.py --reset   # 기존 DB 삭제 후 새로 생성

나중에 보호자 화면에서 입력받게 되면 seed.json 대신 API가 이 테이블을 채운다.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402

SEED_PATH = ROOT / "data" / "seed.json"
GREEN, DIM, RESET = "\033[92m", "\033[2m", "\033[0m"

ap = argparse.ArgumentParser()
ap.add_argument("--reset", action="store_true", help="기존 DB 삭제 후 재생성")
args = ap.parse_args()

if args.reset and db.DB_PATH.exists():
    db.DB_PATH.unlink()
    print(f"{DIM}기존 DB 삭제됨{RESET}")

seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
elder_id = seed["elder"]["elder_id"]

conn = db.connect()
db.init_schema(conn)

# elder
db.insert(conn, "elder_profiles", seed["elder"])

# 페르소나 여러 명. seed 에는 elder_id 가 없으므로 붙여준다.
for p in seed.get("personas") or [seed.get("persona")]:
    db.insert(conn, "personas", dict(p, elder_id=elder_id))

for m in seed["memories"]:
    db.insert(conn, "memories", dict(m, elder_id=elder_id))

for s in seed["schedules"]:
    db.insert(conn, "schedules", dict(s, elder_id=elder_id))

for m in seed["medications"]:
    medication = dict(m, elder_id=elder_id)
    links = medication.pop("signal_links", [])
    db.insert(conn, "medications", medication)
    for link in links:
        db.insert(conn, "medication_signal_links", {
            "schedule_id": m["schedule_id"], **link,
        })

conn.commit()

counts = {
    t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    for t in ("elder_profiles", "personas", "memories", "schedules", "medications")
}
status = dict(
    conn.execute(
        "SELECT status, COUNT(*) FROM memories GROUP BY status"
    ).fetchall()
)
upcoming = conn.execute(
    "SELECT COUNT(*) FROM schedules WHERE confirmed = 1 "
    "AND date >= date('now','localtime')"
).fetchone()[0]
conn.close()

print(f"\n{GREEN}DB 생성 완료{RESET} → {db.DB_PATH}")
for table, n in counts.items():
    print(f"  {table:18} {n}")
print(f"\n{DIM}기억 상태별: {status}{RESET}")
print(f"{DIM}오늘 이후 일정: {upcoming}건{RESET}")
if upcoming == 0:
    print(f"{DIM}  ※ 다가오는 일정이 없으면 AI는 어떤 방문 약속도 하지 않습니다.{RESET}")
