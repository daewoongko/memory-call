"""Audit whether stored STT text preserves fillers and incomplete endings.

This command does not claim language decline.  It only measures whether the
current capture path stores the surface forms needed for a later language
metric decision.

    .venv/Scripts/python.exe tools/audit_stt_preservation.py --days 30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import db  # noqa: E402


FILLER = re.compile(r"(?:^|\s)(?:어|음|그|저)(?:[.·… ]{2,}|\s+(?:뭐지|뭐더라))")
INCOMPLETE = re.compile(r"(?:그런데|그러니까|내가 말이|그게)[.·… ]*$")


def audit(days: int, elder_id: str) -> dict:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT u.transcript FROM utterances u JOIN calls c ON c.call_id=u.call_id "
            "WHERE c.elder_id=? AND u.speaker='elder' AND substr(c.started_at,1,10)>=?",
            (elder_id, since),
        ).fetchall()
    texts = [str(row[0] or "") for row in rows]
    fillers = sum(bool(FILLER.search(text)) for text in texts)
    incomplete = sum(bool(INCOMPLETE.search(text)) for text in texts)
    ready = len(texts) >= 100 and (fillers + incomplete) >= 10
    return {
        "elder_id": elder_id, "days": days, "utterances": len(texts),
        "filler_preserved": fillers, "incomplete_preserved": incomplete,
        "ready_for_language_baseline": ready,
        "decision": (
            "표면 표현이 충분히 보존돼 어절 기반 기준선 실험을 시작할 수 있습니다."
            if ready else
            "원문 보존 표본이 부족해 언어 변화 지표를 운영 리포트에 사용하지 않습니다."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--elder-id", default="elder_001")
    args = parser.parse_args()
    print(json.dumps(audit(args.days, args.elder_id), ensure_ascii=False, indent=2))
