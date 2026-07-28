"""
복약 챙기기.

일정은 보호자가 등록하고, 노인은 아무것도 입력하지 않는다.
복용 여부는 통화 중 말로 확인해서 기록한다 (명세 FR-08).

두 가지 경로로 동작한다.
  1. 복약 시간이 되면 AI 가 먼저 전화를 건다
  2. 이미 통화 중이면 대웅이가 먼저 약 이야기를 꺼낸다

먼저 꺼내는 문장은 규칙으로 만든다. 복용량이나 시간을 모델이 지어내면
그대로 위험이 되므로, 등록된 값만 그대로 읽어 준다.
"""

from datetime import date, datetime, timedelta

import db

# 정시보다 조금 이르게 챙기고, 늦어도 두 시간 안에는 확인한다.
BEFORE_MIN = 30
AFTER_MIN = 120

WEEKDAY = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MEAL_TEXT = {"before": "식전", "after": "식후", "none": ""}


def _parse_time(value: str) -> tuple[int, int]:
    hh, _, mm = (value or "00:00").partition(":")
    return int(hh or 0), int(mm or 0)


def due(elder_id: str = "elder_001", now: datetime | None = None) -> list[dict]:
    """지금 챙겨야 하는데 아직 확인되지 않은 약."""
    now = now or datetime.now()
    today = now.date().isoformat()
    weekday = WEEKDAY[now.weekday()]

    with db.connect() as conn:
        meds = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1",
            (elder_id,),
        ).fetchall()]
        logged = {
            r["schedule_id"] for r in conn.execute(
                "SELECT schedule_id FROM medication_logs "
                "WHERE elder_id = ? AND taken_date = ? AND status = 'USER_CONFIRMED'",
                (elder_id, today),
            ).fetchall()
        }

    out = []
    for m in meds:
        days = m.get("days_of_week") or WEEKDAY
        if weekday not in days:
            continue
        if m["schedule_id"] in logged:
            continue

        hh, mm = _parse_time(m.get("scheduled_time"))
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (at - timedelta(minutes=BEFORE_MIN)
                <= now
                <= at + timedelta(minutes=AFTER_MIN)):
            continue

        out.append(dict(m, scheduled_at=at.isoformat(timespec="minutes"),
                        minutes_late=max(0, int((now - at).total_seconds() // 60))))
    return out


def opening_line(persona_name: str, call_name: str, meds: list[dict]) -> str:
    """통화를 열 때 먼저 꺼낼 문장.

    등록된 약 이름과 복용량만 그대로 쓴다. 모델을 거치지 않는다.
    """
    if not meds:
        return ""
    m = meds[0]
    meal = MEAL_TEXT.get(m.get("meal_relation") or "none", "")
    dose = m.get("dosage_text") or ""
    detail = " ".join(x for x in (meal, dose) if x)

    # 페르소나 규칙대로 두 문장을 넘기지 않는다.
    # 문장이 길면 자막이 화면을 덮고, 노인이 한 번에 알아듣기도 어렵다.
    what = f"{m['medication_name']} {detail}".strip()
    return f"{call_name}, {what} 드실 시간이야. 혹시 벌써 드셨어?"


def record(elder_id: str, schedule_id: str, status: str,
           call_id: str | None = None, evidence: str | None = None) -> None:
    with db.connect() as conn:
        db.insert(conn, "medication_logs", {
            "elder_id": elder_id,
            "schedule_id": schedule_id,
            "call_id": call_id,
            "taken_date": date.today().isoformat(),
            "status": status,
            "evidence_text": evidence,
        })
        conn.commit()


def today_status(elder_id: str = "elder_001") -> list[dict]:
    """보호자 화면에 보여줄 오늘의 복약 현황."""
    today = date.today().isoformat()
    weekday = WEEKDAY[datetime.now().weekday()]

    with db.connect() as conn:
        meds = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
            "ORDER BY scheduled_time",
            (elder_id,),
        ).fetchall()]
        logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? AND taken_date = ?",
            (elder_id, today),
        ).fetchall()]

    by_schedule = {}
    for log in logs:
        by_schedule.setdefault(log["schedule_id"], []).append(log)

    out = []
    for m in meds:
        if weekday not in (m.get("days_of_week") or WEEKDAY):
            continue
        entries = by_schedule.get(m["schedule_id"], [])
        confirmed = any(e["status"] == "USER_CONFIRMED" for e in entries)
        out.append({
            "schedule_id": m["schedule_id"],
            "medication_name": m["medication_name"],
            "dosage_text": m.get("dosage_text"),
            "scheduled_time": m.get("scheduled_time"),
            "meal_relation": m.get("meal_relation"),
            "confirmed": confirmed,
            "last_status": entries[-1]["status"] if entries else None,
        })
    return out
