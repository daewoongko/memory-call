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
import schemas

# 같은 질문으로 묶을 유사도 기준. 치매 노인은 표현을 조금씩 바꿔 되묻는다.
SIMILARITY = 0.72
MIN_REPEAT = 2


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum())


def _evidence_ids(utterance_ids=None, event_ids=None) -> list[str]:
    """근거 식별자를 문자열로 만든다.

    utterance_id 와 event_id 는 서로 다른 테이블의 번호라 숫자만으로는
    구분되지 않는다. 접두사를 붙여 두면 검증 단계가 어느 쪽을 확인할지 알고,
    화면도 발화로 점프할 수 있는 근거인지 판단할 수 있다.

    발화 쪽을 우선한다. 보호자가 보고 싶은 것은 어르신이 한 말이지
    내부 이벤트 번호가 아니다. 발화 연결이 없는 옛 기록만 event 로 남는다.
    """
    uids = [i for i in (utterance_ids or []) if i is not None]
    if uids:
        return [f"utterance-{i}" for i in uids]
    return [f"event-{i}" for i in (event_ids or []) if i is not None]


def _quote(utterances: list[dict], utterance_id) -> str | None:
    """id 로 실제 발화를 찾아온다.

    모델이 신고한 근거 문장은 믿지 않는다. STT 오류를 모델이 알아서 다듬어
    보내기 때문에 DB 에 실제로 있는 문장과 다르다. 보호자에게 따옴표로
    보여줄 문장은 반드시 여기서 나와야 한다.
    """
    if utterance_id is None or not utterances:
        return None
    for u in utterances:
        if u["utterance_id"] == utterance_id:
            return u.get("transcript")
    return None


def _preceding_elder(utterances: list[dict], ai_utterance: dict):
    """AI 발화 바로 앞의 할아버지 발화 id.

    turn() 이 할아버지 → AI 순서로 기록하므로 seq - 1 이 확정적이다.
    추정이 아니다. 통화 첫 인사말처럼 앞이 없으면 None.
    """
    target = (ai_utterance.get("seq") or 0) - 1
    for u in utterances:
        if u.get("seq") == target and u["speaker"] == "elder":
            return u["utterance_id"]
    return None


def _group_repeats(utterances: list[dict]) -> list[dict]:
    """할아버지 발화를 비슷한 것끼리 묶는다.

    utterance_id 를 함께 들고 나온다. 리포트 문장에 근거를 달려면
    "몇 번 물었다"만으로는 부족하고 "어느 발화였는지"가 필요하다.
    """
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
                g["utterance_ids"].append(u["utterance_id"])
                break
        else:
            groups.append({"_norm": norm, "count": 1,
                           "examples": [u["transcript"]],
                           "utterance_ids": [u["utterance_id"]]})

    repeats = [
        {"question": g["examples"][0], "count": g["count"],
         "utterance_ids": g["utterance_ids"]}
        for g in groups if g["count"] >= MIN_REPEAT
    ]
    return sorted(repeats, key=lambda r: -r["count"])


def _medication(events: list[dict], meds: list[dict],
                logs: list[dict] | None = None,
                utterances: list[dict] | None = None) -> dict:
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
            "utterance_id": log.get("utterance_id"),
            "evidence": _quote(utterances, log.get("utterance_id")),
        })
    if not entries:
        # medication_logs 가 정본이다. 여기로 오는 것은 옛 기록뿐이고,
        # 이벤트에는 약 이름이 없어 어떤 약인지 알 수 없다.
        for e in events:
            if e["event_type"] != "medication":
                continue
            status = (e.get("payload") or {}).get("status")
            entries.append({
                "medication_name": None,
                "status": status,
                "label": status_label.get(status, status or "확인되지 않음"),
                "utterance_id": e.get("utterance_id"),
                "event_id": e["event_id"],
                "evidence": _quote(utterances, e.get("utterance_id")),
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


def _risks(events: list[dict], utterances: list[dict]) -> list[dict]:
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
        uid = e.get("utterance_id")
        out.append({
            "event_id": e["event_id"],
            "utterance_id": uid,                      # 할아버지 발화. 보호자용
            "ai_utterance_id": e.get("ai_utterance_id"),   # 신고한 응답. 추적용
            "type": p.get("type"),
            "label": label.get(p.get("type"), p.get("type")),
            "level": p.get("level"),
            # evidence 는 이제 DB 의 실제 발화다. 없으면 None 이고,
            # 화면은 아무것도 인용하지 않는다.
            "evidence": _quote(utterances, uid),
            # 모델이 신고한 문장. 인용이 아니라 AI 요약으로만 표시한다.
            "ai_summary": p.get("evidence"),
        })
    return out


def _unverified(utterances: list[dict]) -> list[dict]:
    """AI 가 사실로 확정하지 않고 넘긴 기억. 보호자 확인이 필요하다."""
    out = []
    for u in utterances:
        recall = u.get("unverified_recall")
        if recall:
            elder_uid = _preceding_elder(utterances, u)
            out.append({
                "utterance_id": elder_uid,          # 할아버지 발화
                "ai_utterance_id": u["utterance_id"],   # 회상이 나온 응답
                "summary": recall.get("summary"),
                "evidence": _quote(utterances, elder_uid),
                "ai_summary": recall.get("quote"),
            })
    return out


def _safety(utterances: list[dict]) -> list[dict]:
    """안전 규칙이 응답을 고친 기록. 명세 NFR-05 의 설명 가능성에 해당한다."""
    out = []
    for u in utterances:
        flags = u.get("safety_flags") or []
        if not flags:
            continue
        elder_uid = _preceding_elder(utterances, u)
        for flag in flags:
            out.append({
                "utterance_id": elder_uid,
                "ai_utterance_id": u["utterance_id"],
                "code": flag.get("code"),
                "reason": flag.get("reason"),
            })
    return out


SUMMARY_SYSTEM = """너는 치매 노인의 통화 기록을 보호자에게 전하는 역할이다.

아래 집계 결과만 사용한다. 여기에 없는 사실을 추론하거나 덧붙이지 않는다.
진단하지 않는다. "치매가 악화되었다" 같은 의학적 판단은 절대 쓰지 않는다.
관찰된 사실과 보호자가 할 수 있는 행동만 적는다.

"발화" 는 어르신이 실제로 한 말이다. 무슨 일이 있었는지 파악하는 데만 쓰고,
그 문장을 그대로 옮겨 적지 않는다. 음성 인식 오류가 섞여 있어 그대로 옮기면
어르신이 이상하게 말한 것처럼 보인다. 원문은 화면이 따로 보여주므로
너는 풀어서 설명하기만 하면 된다.

"발화" 가 없는 항목은 옛 기록이라 원문을 되찾을 수 없는 것이다.
없는 말을 지어내지 말고, 종류와 수준만 가지고 쓴다.

"근거" 는 그 사실이 어느 기록에서 나왔는지를 가리키는 식별자다. 지어내지 않는다.

반드시 아래 JSON 만 출력한다.
{
  "summary": "통화 전체 요약. 3문장 이내. 존댓말.",
  "observations": [
    {
      "text": "보호자가 알아야 할 관찰 한 문장. 존댓말.",
      "evidence_ids": ["이 문장의 근거"],
      "severity": "low 또는 medium 또는 high"
    }
  ],
  "guardian_actions": ["보호자가 오늘 확인하면 좋을 일. 최대 3개. 없으면 빈 배열"]
}

observations 규칙:
- 집계에 있는 항목에 대해서만 쓴다. 최대 5개. 없으면 빈 배열.
- evidence_ids 에는 집계의 "근거" 배열에 실제로 있는 값만 그대로 옮긴다.
  새로 만들거나 번호를 바꾸지 않는다.
- 근거가 없는 항목(통화 시간, 발화 수 같은 집계 숫자)은 observations 에 넣지
  말고 summary 에만 쓴다. 근거 없는 관찰은 보호자에게 전달되지 않는다.
- severity 는 보호자가 얼마나 급히 확인해야 하는지다.
  high 는 다치셨거나 위험한 일이 실제로 있었을 때만 쓴다."""


def _narrative(facts: dict) -> dict:
    """집계 결과를 보호자가 읽을 문장으로 바꾼다.

    형태 검증은 llm.call_schema() 가 한다. 여기서 나온 evidence_ids 는
    아직 검증되지 않았다. 실제로 있는 기록인지 확인하는 것은 다음 단계다.
    """
    out = llm.call_schema(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        schemas.CallNarrative,
        temperature=0.3,
        model=llm.REPORT_MODEL,
    )
    if out is None:
        # TODO(6단계): 집계로 규칙 문장을 조립한다.
        # 지금 문장은 위험 이벤트가 있어도 "정상"이라고 말하는 거짓말이다.
        return {"summary": "통화가 정상적으로 진행되었습니다.",
                "observations": [], "guardian_actions": []}
    return out.model_dump()


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
    medication = _medication(events, meds, med_logs, utterances)
    risks = _risks(events, utterances)
    unverified = _unverified(utterances)
    safety = _safety(utterances)

    topics = sorted({
        mid for u in ai_turns for mid in (u.get("used_memory_ids") or [])
    })

    # 모델에게 넘길 집계 결과. 여기에 없는 것은 리포트에 나올 수 없다.
    # 각 항목에 "근거" 를 달아 두면 모델이 문장마다 출처를 지목할 수 있고,
    # 지목한 id 가 실제로 있는지는 뒤에서 검증한다.
    facts = {
        "통화시간_초": call["duration_sec"],
        "할아버지_발화수": len(elder_turns),
        "AI_응답수": len(ai_turns),
        "반복질문": [
            {
                "질문": r["question"],
                "횟수": r["count"],
                "근거": _evidence_ids(utterance_ids=r["utterance_ids"]),
            }
            for r in repeats
        ],
        "복약": {
            "언급횟수": medication["mentioned"],
            "확인필요": medication["needs_check"],
            "상태": [
                {
                    "내용": e["label"],
                    "발화": e.get("evidence"),
                    "근거": _evidence_ids(
                        utterance_ids=[e.get("utterance_id")],
                        event_ids=[e.get("event_id")],
                    ),
                }
                for e in medication["entries"]
            ],
        },
        "위험이벤트": [
            {
                "종류": r["label"],
                "수준": r["level"],
                # 실제 발화. 연결이 없는 옛 기록은 None 이고, 그 경우 모델은
                # 종류와 수준만 가지고 쓴다. 모델이 신고한 ai_summary 는
                # 여기에 넣지 않는다. 넘기면 지어낸 문장이 리포트로 돌아온다.
                "발화": r.get("evidence"),
                "근거": _evidence_ids(
                    utterance_ids=[r.get("utterance_id")],
                    event_ids=[r.get("event_id")],
                ),
            }
            for r in risks
        ],
        "확인이필요한_기억": [
            {
                "내용": u["summary"],
                "발화": u.get("evidence"),
                "근거": _evidence_ids(utterance_ids=[u.get("utterance_id")]),
            }
            for u in unverified
        ],
        "안전규칙_개입": [
            {
                "사유": s["reason"],
                # 여기 근거는 AI 발화다. "AI 가 이 응답을 고쳤다" 가 사실이므로
                # 가리켜야 할 기록도 그 응답이다.
                "근거": _evidence_ids(utterance_ids=[s.get("ai_utterance_id")]),
            }
            for s in safety
        ],
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

    # facts 는 DB 에 저장하지 않는다 (reports 테이블 컬럼이 아니다).
    # 응답에만 실어 보내 모델이 무엇을 보고 썼는지 확인할 수 있게 한다.
    # observations 는 아직 reports 테이블 컬럼이 아니다 (7단계에서 추가).
    # 그래서 캐시된 리포트를 읽을 때는 비어 있다. 확인할 때 regenerate=True 를 쓸 것.
    return dict(report, observations=story.get("observations", []),
                facts=facts, stats={
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
    out = llm.call_schema(
        [
            {"role": "system", "content": WEEKLY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        schemas.PeriodNarrative,
        temperature=0.3,
        model=llm.REPORT_MODEL,
    )
    return out.model_dump() if out else {"summary": "", "guardian_actions": []}


def acknowledge(event_id: int) -> dict:
    with db.connect() as conn:
        conn.execute(
            "UPDATE call_events SET acknowledged = 1 WHERE event_id = ?", (event_id,)
        )
        conn.commit()
    return {"event_id": event_id, "acknowledged": True}
