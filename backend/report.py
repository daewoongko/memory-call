"""
통화 리포트 생성.

집계는 전부 규칙으로 한다. 반복 질문 횟수, 복약 상태, 위험 이벤트처럼
보호자가 판단 근거로 쓸 숫자를 모델이 지어내게 두어서는 안 되기 때문이다.

LLM 은 마지막에 한 번만, 이미 확정된 사실을 읽기 좋은 문장으로 바꾸는 데만 쓴다.
새로운 사실을 만들지 못하도록 집계 결과 외에는 아무것도 넘기지 않는다.
"""

import json
from difflib import SequenceMatcher

import db
import llm

# 같은 질문으로 묶을 유사도 기준. 치매 노인은 표현을 조금씩 바꿔 되묻는다.
SIMILARITY = 0.72
MIN_REPEAT = 2


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum())


def _group_repeats(utterances: list[dict]) -> list[dict]:
    """할아버지 발화를 비슷한 것끼리 묶는다."""
    groups: list[dict] = []
    for u in utterances:
        if u["speaker"] != "elder" or not u.get("transcript"):
            continue
        norm = _normalize(u["transcript"])
        if not norm:
            continue
        for g in groups:
            if SequenceMatcher(None, g["_norm"], norm).ratio() >= SIMILARITY:
                g["count"] += 1
                g["examples"].append(u["transcript"])
                break
        else:
            groups.append({"_norm": norm, "count": 1,
                           "examples": [u["transcript"]]})

    repeats = [
        {"question": g["examples"][0], "count": g["count"]}
        for g in groups if g["count"] >= MIN_REPEAT
    ]
    return sorted(repeats, key=lambda r: -r["count"])


def _medication(events: list[dict], meds: list[dict],
                logs: list[dict] | None = None) -> dict:
    status_label = {
        "USER_CONFIRMED": "복용했다고 답하심",
        "UNCLEAR": "복용 여부를 기억하지 못하심",
        "REFUSED": "복용을 거부하심",
        "DUPLICATE_SUSPECTED": "중복 복용이 의심됨",
    }
    # 어떤 약인지는 복약 기록에서 가져온다. 이벤트에는 약 이름이 없다.
    name_of = {m["schedule_id"]: m["medication_name"] for m in meds}
    entries = []
    for log in logs or []:
        status = log.get("status")
        name = name_of.get(log.get("schedule_id"), "약")
        entries.append({
            "medication_name": name,
            "status": status,
            "label": f"{name} — {status_label.get(status, status or '확인되지 않음')}",
        })
    if not entries:
        for e in events:
            if e["event_type"] != "medication":
                continue
            status = (e.get("payload") or {}).get("status")
            entries.append({
                "medication_name": None,
                "status": status,
                "label": status_label.get(status, status or "확인되지 않음"),
            })
    return {
        "registered": [m["medication_name"] for m in meds],
        "mentioned": len(entries),
        "entries": entries,
        "needs_check": any(
            e["status"] in ("UNCLEAR", "DUPLICATE_SUSPECTED", "REFUSED")
            for e in entries
        ),
    }


def _risks(events: list[dict]) -> list[dict]:
    label = {
        "fall": "낙상", "chest_pain": "가슴 통증", "breathing": "호흡 곤란",
        "lost": "길 잃음", "overdose": "약 과다 복용 의심",
        "self_harm": "정서적 위기 표현", "intrusion": "침입", "fire": "화재",
    }
    out = []
    for e in events:
        if e["event_type"] != "risk":
            continue
        p = e.get("payload") or {}
        out.append({
            "type": p.get("type"),
            "label": label.get(p.get("type"), p.get("type")),
            "level": p.get("level"),
            "evidence": p.get("evidence"),
        })
    return out


def _unverified(utterances: list[dict]) -> list[dict]:
    """AI 가 사실로 확정하지 않고 넘긴 기억. 보호자 확인이 필요하다."""
    out = []
    for u in utterances:
        recall = u.get("unverified_recall")
        if recall:
            out.append({
                "summary": recall.get("summary"),
                "quote": recall.get("quote"),
            })
    return out


def _safety(utterances: list[dict]) -> list[dict]:
    """안전 규칙이 응답을 고친 기록. 명세 NFR-05 의 설명 가능성에 해당한다."""
    out = []
    for u in utterances:
        for flag in u.get("safety_flags") or []:
            out.append({"code": flag.get("code"), "reason": flag.get("reason")})
    return out


SUMMARY_SYSTEM = """너는 치매 노인의 통화 기록을 보호자에게 전하는 역할이다.

아래 집계 결과만 사용한다. 여기에 없는 사실을 추론하거나 덧붙이지 않는다.
진단하지 않는다. "치매가 악화되었다" 같은 의학적 판단은 절대 쓰지 않는다.
관찰된 사실과 보호자가 할 수 있는 행동만 적는다.

반드시 아래 JSON 만 출력한다.
{
  "summary": "통화 내용 요약. 3문장 이내. 존댓말.",
  "guardian_actions": ["보호자가 오늘 확인하면 좋을 일. 최대 3개. 없으면 빈 배열"]
}"""


def _narrative(facts: dict) -> dict:
    try:
        return llm.call_json([
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ], temperature=0.3)
    except Exception:  # noqa: BLE001
        # 모델이 실패해도 리포트는 나와야 한다. 집계는 이미 확정되어 있다.
        return {"summary": "통화가 정상적으로 진행되었습니다.", "guardian_actions": []}


def build(call_id: str, regenerate: bool = False) -> dict:
    """통화 하나의 리포트를 만들어 저장하고 돌려준다.

    집계는 매번 다시 한다. DB 만 읽으므로 비용이 없고, 집계 규칙을 고쳤을 때
    예전 리포트가 낡은 채로 남아 있는 것을 막는다.
    비싼 것은 LLM 문장뿐이라 그것만 저장해 두고 재사용한다.
    """
    with db.connect() as conn:
        call = conn.execute(
            "SELECT * FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if call is None:
            raise ValueError(f"통화 {call_id} 없음")

        cached = None if regenerate else conn.execute(
            "SELECT summary, guardian_actions FROM reports WHERE call_id = ?",
            (call_id,),
        ).fetchone()

        utterances = [db._row(r) for r in conn.execute(
            "SELECT * FROM utterances WHERE call_id = ? ORDER BY seq", (call_id,)
        ).fetchall()]
        events = [db._row(r) for r in conn.execute(
            "SELECT * FROM call_events WHERE call_id = ?", (call_id,)
        ).fetchall()]
        meds = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ?", (call["elder_id"],)
        ).fetchall()]
        med_logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE call_id = ? ORDER BY log_id",
            (call_id,)
        ).fetchall()]

    elder_turns = [u for u in utterances if u["speaker"] == "elder"]
    ai_turns = [u for u in utterances if u["speaker"] == "ai"]
    latencies = [u["latency_ms"] for u in ai_turns if u.get("latency_ms")]

    repeats = _group_repeats(utterances)
    medication = _medication(events, meds, med_logs)
    risks = _risks(events)
    unverified = _unverified(utterances)
    safety = _safety(utterances)

    topics = sorted({
        mid for u in ai_turns for mid in (u.get("used_memory_ids") or [])
    })

    facts = {
        "통화시간_초": call["duration_sec"],
        "할아버지_발화수": len(elder_turns),
        "AI_응답수": len(ai_turns),
        "반복질문": [{"질문": r["question"], "횟수": r["count"]} for r in repeats],
        "복약": {
            "언급횟수": medication["mentioned"],
            "확인필요": medication["needs_check"],
            "상태": [e["label"] for e in medication["entries"]],
        },
        "위험이벤트": [{"종류": r["label"], "수준": r["level"]} for r in risks],
        "확인이필요한_기억": [u["summary"] for u in unverified],
        "안전규칙_개입횟수": len(safety),
    }

    if cached and cached["summary"]:
        story = {
            "summary": cached["summary"],
            "guardian_actions": json.loads(cached["guardian_actions"] or "[]"),
        }
    else:
        story = _narrative(facts)

    report = {
        "call_id": call_id,
        "summary": story.get("summary", ""),
        "repeated_questions": repeats,
        "medication_summary": medication,
        "new_recalls": unverified,
        "risk_summary": risks,
        "guardian_actions": story.get("guardian_actions", []),
    }

    with db.connect() as conn:
        conn.execute("DELETE FROM reports WHERE call_id = ?", (call_id,))
        db.insert(conn, "reports", report)
        conn.commit()

    return dict(report, stats={
        "duration_sec": call["duration_sec"],
        "elder_turns": len(elder_turns),
        "ai_turns": len(ai_turns),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "memories_used": topics,
        "safety_interventions": safety,
        "started_at": call["started_at"],
    })


def recent(elder_id: str = "elder_001", limit: int = 20) -> list[dict]:
    """보호자 화면 목록용. 통화별 한 줄 요약."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT c.call_id, c.started_at, c.duration_sec, "
            "       r.summary, r.repeated_questions, r.risk_summary "
            "FROM calls c LEFT JOIN reports r ON r.call_id = c.call_id "
            "WHERE c.elder_id = ? AND c.status = 'ended' "
            "ORDER BY c.started_at DESC LIMIT ?",
            (elder_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        row = db._row(r)
        out.append({
            "call_id": row["call_id"],
            "started_at": row["started_at"],
            "duration_sec": row["duration_sec"],
            "summary": row.get("summary"),
            "repeat_count": len(row.get("repeated_questions") or []),
            "risk_count": len(row.get("risk_summary") or []),
        })
    return out


# ------------------------------------------------------------------ 기간 요약

WEEKLY_SYSTEM = """너는 치매 노인의 통화 기록을 보호자에게 전하는 역할이다.

아래 집계 결과만 사용한다. 여기에 없는 사실을 추론하거나 덧붙이지 않는다.
진단하지 않는다. "치매가 악화되었다" 같은 의학적 판단은 절대 쓰지 않는다.
숫자가 늘거나 줄었다는 사실만 말하고 원인을 단정하지 않는다.

반드시 아래 JSON 만 출력한다.
{
  "summary": "기간 전체 요약. 3문장 이내. 존댓말.",
  "guardian_actions": ["보호자가 이번 주에 확인하면 좋을 일. 최대 3개"]
}"""


def _window(elder_id: str, since: str, until: str | None = None) -> dict:
    """한 구간의 숫자만 뽑는다. 이전 구간과 비교하려면 같은 방식으로 두 번 부른다."""
    upper = until or "9999-12-31"
    with db.connect() as conn:
        calls = [db._row(r) for r in conn.execute(
            "SELECT * FROM calls WHERE elder_id = ? AND status = 'ended' "
            "AND date(started_at) >= ? AND date(started_at) <= ?",
            (elder_id, since, upper),
        ).fetchall()]
        risks = conn.execute(
            "SELECT COUNT(*) FROM call_events e JOIN calls c ON c.call_id = e.call_id "
            "WHERE c.elder_id = ? AND e.event_type = 'risk' "
            "AND date(c.started_at) >= ? AND date(c.started_at) <= ?",
            (elder_id, since, upper),
        ).fetchone()[0]
        logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? "
            "AND taken_date >= ? AND taken_date <= ?",
            (elder_id, since, upper),
        ).fetchall()]
        reports = [db._row(r) for r in conn.execute(
            "SELECT r.* FROM reports r JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND date(c.started_at) >= ? "
            "AND date(c.started_at) <= ?",
            (elder_id, since, upper),
        ).fetchall()]

    repeat_total = sum(
        q.get("count", 0)
        for r in reports for q in (r.get("repeated_questions") or [])
    )
    return {
        "calls": len(calls),
        "seconds": sum(c["duration_sec"] or 0 for c in calls),
        "risks": risks,
        "med_confirmed": sum(1 for x in logs if x["status"] == "USER_CONFIRMED"),
        "med_unclear": sum(1 for x in logs if x["status"] != "USER_CONFIRMED"),
        "repeat_total": repeat_total,
    }


def _delta(now: int, before: int, unit: str, more_is_better: bool) -> dict | None:
    """이전 구간과의 차이. 비교할 것이 없으면 만들지 않는다."""
    if now == before:
        return None
    diff = now - before
    direction = "up" if diff > 0 else "down"
    good = (diff > 0) == more_is_better
    word = "많아요" if diff > 0 else "적어요"
    return {
        "text": f"지난 기간보다 {abs(diff)}{unit} {word}",
        "direction": direction,
        "good": good,
    }


def period(elder_id: str = "elder_001", days: int = 7,
           narrative: bool = True) -> dict:
    """며칠치를 모아서 본다.

    통화 하나짜리 리포트로는 변화가 보이지 않는다.
    반복 질문이 늘었는지, 복약을 얼마나 챙기셨는지는 기간으로 봐야 한다.
    같은 길이의 직전 구간과 비교해 늘고 줄었다는 사실만 전한다.
    """
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=days - 1)).isoformat()
    prev_since = (date.today() - timedelta(days=days * 2 - 1)).isoformat()
    prev_until = (date.today() - timedelta(days=days)).isoformat()

    with db.connect() as conn:
        calls = [db._row(r) for r in conn.execute(
            "SELECT * FROM calls WHERE elder_id = ? AND status = 'ended' "
            "AND date(started_at) >= ? ORDER BY started_at",
            (elder_id, since),
        ).fetchall()]
        risks = [db._row(r) for r in conn.execute(
            "SELECT e.*, c.started_at FROM call_events e "
            "JOIN calls c ON c.call_id = e.call_id "
            "WHERE c.elder_id = ? AND e.event_type = 'risk' "
            "AND date(c.started_at) >= ? ORDER BY c.started_at DESC",
            (elder_id, since),
        ).fetchall()]
        med_logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? AND taken_date >= ?",
            (elder_id, since),
        ).fetchall()]
        reports = [db._row(r) for r in conn.execute(
            "SELECT r.* FROM reports r JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND date(c.started_at) >= ?",
            (elder_id, since),
        ).fetchall()]

    by_day: dict[str, dict] = {}
    for c in calls:
        day = (c["started_at"] or "")[:10]
        slot = by_day.setdefault(day, {"date": day, "calls": 0, "seconds": 0})
        slot["calls"] += 1
        slot["seconds"] += c["duration_sec"] or 0

    repeats = []
    for r in reports:
        repeats.extend(r.get("repeated_questions") or [])
    top_repeats = sorted(repeats, key=lambda x: -x.get("count", 0))[:5]

    confirmed = sum(1 for log in med_logs if log["status"] == "USER_CONFIRMED")
    unclear = sum(1 for log in med_logs
                  if log["status"] in ("UNCLEAR", "REFUSED", "DUPLICATE_SUSPECTED"))

    facts = {
        "기간_일수": days,
        "통화_횟수": len(calls),
        "총_통화시간_초": sum(c["duration_sec"] or 0 for c in calls),
        "반복질문_상위": [{"질문": r["question"], "횟수": r["count"]} for r in top_repeats],
        "복약_확인됨": confirmed,
        "복약_불확실": unclear,
        "위험_건수": len(risks),
    }

    story = {"summary": "", "guardian_actions": []}
    if narrative and calls:
        story = _narrative_period(facts)

    this_w = _window(elder_id, since)
    prev_w = _window(elder_id, prev_since, prev_until)
    changes = [
        c for c in (
            _delta(this_w["calls"], prev_w["calls"], "번", True),
            _delta(this_w["repeat_total"], prev_w["repeat_total"], "번", False),
            _delta(this_w["med_confirmed"], prev_w["med_confirmed"], "번", True),
            _delta(this_w["risks"], prev_w["risks"], "건", False),
        ) if c
    ]
    labels = ["통화 횟수가", "되물으신 횟수가", "복약 확인이", "위험 신호가"]
    for label, change in zip(
        [l for l, c in zip(labels, (
            _delta(this_w["calls"], prev_w["calls"], "번", True),
            _delta(this_w["repeat_total"], prev_w["repeat_total"], "번", False),
            _delta(this_w["med_confirmed"], prev_w["med_confirmed"], "번", True),
            _delta(this_w["risks"], prev_w["risks"], "건", False),
        )) if c], changes
    ):
        change["label"] = label

    return {
        "days": days,
        "since": since,
        "changes": changes,
        "repeat_total": this_w["repeat_total"],
        "calls": len(calls),
        "total_seconds": facts["총_통화시간_초"],
        "by_day": sorted(by_day.values(), key=lambda d: d["date"]),
        "top_repeats": top_repeats,
        "medication": {"confirmed": confirmed, "needs_check": unclear},
        "risks": [
            {
                "event_id": r["event_id"],
                "call_id": r["call_id"],
                "at": r["started_at"],
                "acknowledged": bool(r["acknowledged"]),
                **(r.get("payload") or {}),
            }
            for r in risks
        ],
        "summary": story.get("summary", ""),
        "guardian_actions": story.get("guardian_actions", []),
    }


def _narrative_period(facts: dict) -> dict:
    try:
        return llm.call_json([
            {"role": "system", "content": WEEKLY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ], temperature=0.3)
    except Exception:  # noqa: BLE001
        return {"summary": "", "guardian_actions": []}


def acknowledge(event_id: int) -> dict:
    with db.connect() as conn:
        conn.execute(
            "UPDATE call_events SET acknowledged = 1 WHERE event_id = ?", (event_id,)
        )
        conn.commit()
    return {"event_id": event_id, "acknowledged": True}
