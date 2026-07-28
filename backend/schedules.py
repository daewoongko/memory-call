"""
일정 관리.

명세 FR-04 — AI 는 등록된 일정만 이야기한다.
여기 없는 방문이나 통화를 약속하면 안전 규칙이 응답을 막는다.

두 가지가 중요하다.
  1. 확정된 일정만 대화에 쓰인다. 미확정은 프롬프트에 들어가지 않는다.
  2. 지난 일정은 자동으로 빠진다. 남아 있으면 미래 약속으로 착각한다.
"""

import uuid
from datetime import date, timedelta

import db

# 지난 일정도 화면에는 보여준다. 보호자가 무엇이 있었는지 알아야 하기 때문이다.
PAST_WINDOW_DAYS = 30


def _new_id() -> str:
    return f"sch_{uuid.uuid4().hex[:8]}"


def listing(elder_id: str = "elder_001") -> dict:
    today = date.today()
    since = (today - timedelta(days=PAST_WINDOW_DAYS)).isoformat()

    with db.connect() as conn:
        rows = [db._row(r) for r in conn.execute(
            "SELECT * FROM schedules WHERE elder_id = ? AND date >= ? "
            "ORDER BY date, time",
            (elder_id, since),
        ).fetchall()]

    upcoming, past = [], []
    for r in rows:
        entry = dict(r, confirmed=bool(r.get("confirmed")))
        # 대화에 실제로 쓰이는 조건을 그대로 표시한다.
        # 화면에서 보이는 것과 AI 가 아는 것이 어긋나면 안 된다.
        entry["used_in_call"] = entry["confirmed"] and entry["date"] >= today.isoformat()
        (upcoming if entry["date"] >= today.isoformat() else past).append(entry)

    return {"upcoming": upcoming, "past": list(reversed(past))}


def create(elder_id: str, data: dict) -> dict:
    row = {
        "schedule_id": _new_id(),
        "elder_id": elder_id,
        "title": data["title"],
        "date": data["date"],
        "time": data.get("time") or "",
        "note": data.get("note") or "",
        "confirmed": int(bool(data.get("confirmed", True))),
    }
    with db.connect() as conn:
        db.insert(conn, "schedules", row)
        conn.commit()
    return row


def update(schedule_id: str, fields: dict) -> dict:
    allowed = {"title", "date", "time", "note", "confirmed"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "confirmed" in patch:
        patch["confirmed"] = int(bool(patch["confirmed"]))
    if not patch:
        raise ValueError("바꿀 내용이 없습니다.")

    sets = ", ".join(f"{k} = ?" for k in patch)
    values = [db._dump(v) for v in patch.values()] + [schedule_id]
    with db.connect() as conn:
        conn.execute(f"UPDATE schedules SET {sets} WHERE schedule_id = ?", values)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"일정 {schedule_id} 없음")
    return db._row(row)


def delete(schedule_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
        conn.commit()
