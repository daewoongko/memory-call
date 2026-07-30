"""
복약 계약.

두 가지가 핵심이다.

1. **LLM 이 약 이름·용량을 만들 수 없다.** 안내 문장은 등록된 값으로 규칙이
   조립한다. `opening_line()` 이 모델을 거치지 않는지 확인한다.
2. **본인 응답과 보호자 확인을 구분한다.** 리포트에서 둘을 나눠 보여줘야 하고,
   보호자가 확인한 약은 AI 가 다시 전화해서 묻지 않아야 한다.
"""

from datetime import datetime, timedelta

import pytest

import db
import medication


def _add_med(elder_id, schedule_id="med_test", name="혈압약",
             dosage="1정", at="09:00", meal="after"):
    with db.connect() as conn:
        db.insert(conn, "medications", {
            "schedule_id": schedule_id,
            "elder_id": elder_id,
            "medication_name": name,
            "dosage_text": dosage,
            "scheduled_time": at,
            "meal_relation": meal,
            "days_of_week": list(medication.WEEKDAY),
            "active": 1,
        })
        conn.commit()
    return schedule_id


# ------------------------------------------------------------ 안내 문장

def test_안내_문장은_등록된_약_이름과_용량만_쓴다():
    meds = [{"medication_name": "혈압약", "dosage_text": "1정",
             "meal_relation": "after"}]

    line = medication.opening_line("대웅", "할아버지", meds)

    assert "혈압약" in line
    assert "1정" in line
    assert "식후" in line
    assert "할아버지" in line


def test_챙길_약이_없으면_안내_문장이_비어_있다():
    assert medication.opening_line("대웅", "할아버지", []) == ""


def test_안내_문장은_이미_먹었는지_묻는다():
    """중복 복용을 막기 위해 먼저 확인해야 한다."""
    meds = [{"medication_name": "혈압약", "dosage_text": "1정",
             "meal_relation": "none"}]

    line = medication.opening_line("대웅", "할아버지", meds)

    assert "드셨어" in line or "드셨" in line


# ------------------------------------------------------------ due()

def test_복약_시간대면_챙길_약으로_잡힌다(fresh_db):
    now = datetime.now().replace(second=0, microsecond=0)
    _add_med(fresh_db, at=now.strftime("%H:%M"))

    due = medication.due(fresh_db, now=now)

    assert any(m["schedule_id"] == "med_test" for m in due)


def test_시간대를_벗어나면_챙기지_않는다(fresh_db):
    now = datetime.now().replace(second=0, microsecond=0)
    far = (now + timedelta(hours=5)).strftime("%H:%M")
    _add_med(fresh_db, at=far)

    due = medication.due(fresh_db, now=now)

    assert not any(m["schedule_id"] == "med_test" for m in due)


def test_본인이_확인한_약은_다시_챙기지_않는다(fresh_db):
    now = datetime.now().replace(second=0, microsecond=0)
    sid = _add_med(fresh_db, at=now.strftime("%H:%M"))
    medication.record(fresh_db, sid, "USER_CONFIRMED")

    due = medication.due(fresh_db, now=now)

    assert not any(m["schedule_id"] == sid for m in due)


def test_보호자가_확인한_약도_다시_챙기지_않는다(fresh_db):
    """이걸 빼면 이미 확인된 약으로 AI 가 계속 전화를 건다."""
    now = datetime.now().replace(second=0, microsecond=0)
    sid = _add_med(fresh_db, at=now.strftime("%H:%M"))
    medication.guardian_confirm(fresh_db, sid)

    due = medication.due(fresh_db, now=now)

    assert not any(m["schedule_id"] == sid for m in due)


def test_모호한_응답은_확인으로_치지_않는다(fresh_db):
    now = datetime.now().replace(second=0, microsecond=0)
    sid = _add_med(fresh_db, at=now.strftime("%H:%M"))
    medication.record(fresh_db, sid, "UNCLEAR")

    due = medication.due(fresh_db, now=now)

    assert any(m["schedule_id"] == sid for m in due)


# ------------------------------------------------------------ 보호자 확인

def test_보호자_확인은_별도_상태로_기록된다(fresh_db):
    sid = _add_med(fresh_db)

    medication.guardian_confirm(fresh_db, sid, note="직접 봤음")

    with db.connect() as conn:
        row = conn.execute(
            "SELECT status, evidence_text FROM medication_logs "
            "WHERE schedule_id = ?", (sid,)
        ).fetchone()
    assert row["status"] == "GUARDIAN_CONFIRMED"
    assert row["evidence_text"] == "직접 봤음"


def test_등록되지_않은_약은_보호자_확인을_거부한다(fresh_db):
    with pytest.raises(ValueError):
        medication.guardian_confirm(fresh_db, "med_does_not_exist")


def test_today_status가_본인과_보호자를_구분한다(fresh_db):
    a = _add_med(fresh_db, schedule_id="med_a", name="A약")
    b = _add_med(fresh_db, schedule_id="med_b", name="B약", at="21:00")
    medication.record(fresh_db, a, "USER_CONFIRMED")
    medication.guardian_confirm(fresh_db, b)

    rows = {r["schedule_id"]: r for r in medication.today_status(fresh_db)}

    assert rows[a]["confirmed_by_user"] is True
    assert rows[a]["confirmed_by_guardian"] is False
    assert rows[b]["confirmed_by_user"] is False
    assert rows[b]["confirmed_by_guardian"] is True
    # 어느 쪽이든 확인은 확인이다
    assert rows[a]["confirmed"] and rows[b]["confirmed"]


def test_보호자_확인이_통화_기록을_덮어쓰지_않는다(fresh_db):
    """누가 언제 확인했는지 추적할 수 있어야 한다."""
    sid = _add_med(fresh_db)
    medication.record(fresh_db, sid, "REFUSED")
    medication.guardian_confirm(fresh_db, sid)

    with db.connect() as conn:
        statuses = [r["status"] for r in conn.execute(
            "SELECT status FROM medication_logs WHERE schedule_id = ? "
            "ORDER BY log_id", (sid,)
        ).fetchall()]

    assert statuses == ["REFUSED", "GUARDIAN_CONFIRMED"]


# ------------------------------------------------------------ API 계약

def test_보호자_확인_엔드포인트(client):
    sid = _add_med(client.elder_id, at="09:00")

    res = client.post(f"/api/medications/{sid}/guardian-confirm",
                      json={"elder_id": client.elder_id, "note": "확인함"})

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "GUARDIAN_CONFIRMED"
    assert any(r["schedule_id"] == sid and r["confirmed_by_guardian"]
               for r in body["today"])


def test_없는_약의_보호자_확인은_404(client):
    res = client.post("/api/medications/med_nope/guardian-confirm",
                      json={"elder_id": client.elder_id})
    assert res.status_code == 404


def test_pending_call은_복약_사유를_알려준다(client):
    now = datetime.now().replace(second=0, microsecond=0)
    _add_med(client.elder_id, at=now.strftime("%H:%M"), name="저녁약")

    res = client.get(f"/api/elders/{client.elder_id}/pending-call")

    body = res.json()
    assert body["due"] is True
    assert body["reason"] == "medication"
    assert any(m["name"] == "저녁약" for m in body["medications"])
