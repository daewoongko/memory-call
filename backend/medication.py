"""
복약 챙기기.

일정은 보호자가 등록하고, 노인은 아무것도 입력하지 않는다.
복용 여부는 통화 중 말로 확인해서 기록한다 (명세 FR-08).

두 가지 경로로 동작한다.
  1. 복약 시간이 되면 AI 가 먼저 전화를 건다
  2. 이미 통화 중이면 선택한 AI 가족이 먼저 약 이야기를 꺼낸다

먼저 꺼내는 문장은 규칙으로 만든다. 복용량이나 시간을 모델이 지어내면
그대로 위험이 되므로, 등록된 값만 그대로 읽어 준다.
"""

import re
from datetime import date, datetime, timedelta

import db

# 정시보다 조금 이르게 챙기고, 늦어도 두 시간 안에는 확인한다.
BEFORE_MIN = 30
AFTER_MIN = 120

WEEKDAY = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MEAL_TEXT = {"before": "식전", "after": "식후", "none": ""}


def is_due_medication_prompt(text: str, due_meds: list[dict]) -> bool:
    """직전 AI 문장이 현재 복약 대상에 관한 질문인지 보수적으로 판별한다."""
    if not text or not due_meds:
        return False
    if re.search(r"(?:약|복용|알약)[^.!?]{0,24}(?:먹|드|챙|복용)", text):
        return True
    compact = re.sub(r"\s+", "", text)
    return any(
        re.sub(r"\s+", "", str(row.get("medication_name") or "")) in compact
        for row in due_meds
        if row.get("medication_name")
    )


def classify_explicit_status(
    user_text: str,
    due_meds: list[dict],
    *,
    prompted: bool = False,
) -> dict | None:
    """명시적인 복약 답변만 네트워크 호출 없이 즉시 보존한다.

    애매한 일반 대화의 ``먹었어``를 약으로 오인하지 않도록 약을 직접
    언급했거나 직전 문장이 현재 복약 질문일 때만 분류한다. ``NOT_TAKEN``은
    DB의 기존 허용 상태를 바꾸지 않고 ``UNCLEAR``로 저장하되 claim에 원뜻을
    보존한다. 따라서 복용 완료로 처리되거나 대상 약이 목록에서 빠지지 않는다.
    """
    text = (user_text or "").strip()
    if not text or not due_meds:
        return None

    compact = re.sub(r"\s+", "", text)
    med_names = [
        re.sub(r"\s+", "", str(row.get("medication_name") or ""))
        for row in due_meds
        if row.get("medication_name")
    ]
    mentions_medication = bool(re.search(r"약|복용|알약", text)) or any(
        name and name in compact for name in med_names
    )
    if not mentions_medication and not prompted:
        return None

    def payload(status: str, claim: str) -> dict:
        return {
            "schedule_id": str(due_meds[0]["schedule_id"]),
            "status": status,
            "claim": claim,
            "source": "local_explicit",
        }

    # 중복 복용 가능성은 단순 복용 확인보다 먼저 잡는다.
    if re.search(
        r"(?:약[^.!?]{0,14})?(?:두|세|2|3|여러)\s*번[^.!?]{0,10}"
        r"(?:먹|복용|챙)|(?:또|다시)[^.!?]{0,8}(?:먹|복용)",
        text,
    ):
        return payload("DUPLICATE_SUSPECTED", "DUPLICATE_SUSPECTED")

    if re.search(
        r"(?:먹었나|먹었는지|복용했는지|먹었을까|기억(?:이)?\s*안|"
        r"기억나지\s*않|헷갈|모르겠|모르지)",
        text,
    ):
        return payload("UNCLEAR", "UNCERTAIN")

    if re.search(r"(?:안\s*먹을|먹기\s*싫|복용하기\s*싫|거부|싫어)", text):
        return payload("REFUSED", "REFUSED")

    if re.search(
        r"(?:아직[^.!?]{0,8})?(?:안|못)\s*(?:먹었|먹었어|먹음|복용했)|"
        r"복용\s*(?:안|못)\s*했",
        text,
    ):
        return payload("UNCLEAR", "NOT_TAKEN")

    if re.search(r"(?:먹었|먹었어|먹었지|복용했|챙겨\s*먹|챙겼)", text):
        return payload("USER_CONFIRMED", "TAKEN")

    if prompted and re.fullmatch(r"(?:응|어|그래|네|예|맞아|맞아요)[.!?~ ]*", text):
        return payload("USER_CONFIRMED", "TAKEN")
    if prompted and re.fullmatch(r"(?:아니|아니야|아니요|아직)[.!?~ ]*", text):
        return payload("UNCLEAR", "NOT_TAKEN")
    return None


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
           call_id: str | None = None, evidence: str | None = None,
           utterance_id: int | None = None) -> None:
    """복약 상태를 기록한다.

    evidence_text 는 할아버지 발화를 그대로 자른 것이라 모델이 지어낸 값은
    아니지만, 200자에서 잘리고 어느 발화였는지 알 수 없다.
    utterance_id 로 원문을 되찾을 수 있게 한다.
    """
    with db.connect() as conn:
        db.insert(conn, "medication_logs", {
            "elder_id": elder_id,
            "schedule_id": schedule_id,
            "call_id": call_id,
            "utterance_id": utterance_id,
            "taken_date": date.today().isoformat(),
            "status": status,
            "evidence_text": evidence,
        })
        conn.commit()


def status_on(elder_id: str = "elder_001", selected_day: date | None = None) -> list[dict]:
    """선택 날짜의 복약 현황. 과거 기록도 같은 규칙으로 재현한다."""
    selected_day = selected_day or date.today()
    day_text = selected_day.isoformat()
    weekday = WEEKDAY[selected_day.weekday()]

    with db.connect() as conn:
        meds = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
            "ORDER BY scheduled_time",
            (elder_id,),
        ).fetchall()]
        logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? AND taken_date = ?",
            (elder_id, day_text),
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


def today_status(elder_id: str = "elder_001") -> list[dict]:
    """보호자 화면에 보여줄 오늘의 복약 현황."""
    return status_on(elder_id, date.today())


def listing(elder_id: str = "elder_001") -> list[dict]:
    """달력 표시용 전체 활성 복약 일정.

    오늘 복용 여부와 달리 반복 요일 자체가 필요하므로 days_of_week를 보존한다.
    """
    with db.connect() as conn:
        rows = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
            "ORDER BY scheduled_time, medication_name",
            (elder_id,),
        ).fetchall()]
        links = [db._row(r) for r in conn.execute(
            "SELECT l.* FROM medication_signal_links l JOIN medications m "
            "ON m.schedule_id = l.schedule_id WHERE m.elder_id = ?",
            (elder_id,),
        ).fetchall()]
    by_schedule = {}
    for link in links:
        by_schedule.setdefault(link["schedule_id"], []).append(link)
    for row in rows:
        row["signal_links"] = by_schedule.get(row["schedule_id"], [])
    return rows
