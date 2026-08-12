"""Medication adherence analysis with four distinct states.

The module only matches signals explicitly registered by a caregiver.  It
never infers a drug-effect relationship and never recommends changing a drug.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from analysis.observation_catalog import SIGNALS


STATUSES = ("USER_CONFIRMED", "UNCLEAR", "REFUSED", "DUPLICATE_SUSPECTED")
STATUS_LABELS = {
    "USER_CONFIRMED": "복용 확인",
    "UNCLEAR": "복용 불확실",
    "REFUSED": "복용 거부",
    "DUPLICATE_SUSPECTED": "중복 복용 의심",
}
WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


def _status_counts(logs: list[dict]) -> dict[str, int]:
    counts = Counter(str(log.get("status") or "") for log in logs)
    return {status: counts[status] for status in STATUSES}


def _display_counts(logs: list[dict]) -> dict[str, int]:
    """Expose stable UI aliases without collapsing the four source states."""
    counts = _status_counts(logs)
    return {
        **counts,
        "confirmed": counts["USER_CONFIRMED"],
        "unclear": counts["UNCLEAR"],
        "refused": counts["REFUSED"],
        "duplicate_suspected": counts["DUPLICATE_SUSPECTED"],
        "needs_check": sum(counts[state] for state in STATUSES if state != "USER_CONFIRMED"),
    }


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build(*, medications: list[dict], logs: list[dict], previous_logs: list[dict],
          reviews: list[dict], links: list[dict], reports: list[dict],
          period_start: date, period_end: date) -> dict:
    medication_by_id = {row["schedule_id"]: row for row in medications}
    by_day = []
    cursor = period_start
    while cursor <= period_end:
        day_logs = [row for row in logs if str(row.get("taken_date"))[:10] == cursor.isoformat()]
        by_day.append({"date": cursor.isoformat(), **_display_counts(day_logs)})
        cursor += timedelta(days=1)

    grouped: dict[str, list[dict]] = defaultdict(list)
    weekday_time: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for log in logs:
        schedule_id = str(log.get("schedule_id") or "")
        grouped[schedule_id].append(log)
        taken = _day(log.get("taken_date") or "")
        medication = medication_by_id.get(schedule_id, {})
        if taken:
            weekday_time[(schedule_id, taken.weekday(), medication.get("scheduled_time") or "미등록")].append(log)

    by_medication = []
    for medication in medications:
        schedule_id = medication["schedule_id"]
        rows = grouped.get(schedule_id, [])
        counts = _display_counts(rows)
        total = sum(counts[state] for state in STATUSES)
        by_medication.append({
            "schedule_id": schedule_id,
            "medication_name": medication.get("medication_name"),
            "scheduled_time": medication.get("scheduled_time"),
            **counts,
            "confirmation_rate": round(counts["USER_CONFIRMED"] / total * 100) if total else None,
        })

    by_weekday_time = [{
        "schedule_id": schedule_id,
        "medication_name": medication_by_id.get(schedule_id, {}).get("medication_name", "등록 약"),
        "weekday": weekday,
        "weekday_label": WEEKDAY_LABELS[weekday],
        "scheduled_time": scheduled_time,
        **_display_counts(rows),
    } for (schedule_id, weekday, scheduled_time), rows in sorted(weekday_time.items())]

    latest_reviews = {}
    for review in sorted(reviews, key=lambda row: (str(row.get("review_date") or ""), int(row.get("review_id") or 0)), reverse=True):
        latest_reviews.setdefault(review.get("schedule_id"), review)
    review_status = []
    for medication in medications:
        latest = latest_reviews.get(medication["schedule_id"])
        interval = int(medication.get("review_interval_days") or 14)
        latest_day = _day((latest or {}).get("review_date") or "")
        due_on = latest_day + timedelta(days=interval) if latest_day else period_start
        review_status.append({
            "schedule_id": medication["schedule_id"],
            "medication_name": medication.get("medication_name"),
            "latest_review": latest,
            "review_due_on": due_on.isoformat(),
            "review_due": due_on <= period_end,
            "monitoring_points": medication.get("monitoring_points") or [],
            "escalation_criteria": medication.get("escalation_criteria") or "",
        })

    evidence_by_signal: dict[str, list[dict]] = defaultdict(list)
    for report in reports:
        for domain, observations in (report.get("care_summary") or {}).items():
            if domain == "meaningful_moments":
                continue
            for observation in observations or []:
                signal = observation.get("signal")
                if signal:
                    evidence_by_signal[signal].append({
                        "call_id": report.get("call_id"),
                        "utterance_id": observation.get("utterance_id"),
                        "at": observation.get("at"),
                        "evidence": observation.get("evidence"),
                    })

    registered_matches = []
    for link in links:
        signal = link.get("signal")
        matches = evidence_by_signal.get(signal, [])
        if not matches:
            continue
        medication = medication_by_id.get(link.get("schedule_id"), {})
        registered_matches.append({
            "schedule_id": link.get("schedule_id"),
            "medication_name": medication.get("medication_name", "등록 약"),
            "signal": signal,
            "signal_label": SIGNALS.get(signal).label if signal in SIGNALS else signal,
            "link_level": link.get("link_level"),
            "criterion_text": link.get("criterion_text"),
            "count": len(matches),
            "evidence": matches[:5],
            "action": "등록된 관찰 기준과 같은 발화가 확인됐습니다. 담당자가 상태를 확인하고 필요 시 처방 의료진에게 보고하세요.",
        })

    current_counts = _status_counts(logs)
    previous_counts = _status_counts(previous_logs)
    return {
        "status_counts": current_counts,
        "status_labels": STATUS_LABELS,
        "confirmed": current_counts["USER_CONFIRMED"],
        "needs_check": sum(current_counts[s] for s in STATUSES if s != "USER_CONFIRMED"),
        "confirmation_rate": round(current_counts["USER_CONFIRMED"] / sum(current_counts.values()) * 100) if sum(current_counts.values()) else None,
        "unclear": current_counts["UNCLEAR"],
        "refused": current_counts["REFUSED"],
        "duplicate_suspected": current_counts["DUPLICATE_SUSPECTED"],
        "status_change": {status: current_counts[status] - previous_counts[status] for status in STATUSES},
        "needs_check_change": sum(current_counts[s] - previous_counts[s] for s in STATUSES if s != "USER_CONFIRMED"),
        "by_day": by_day,
        "by_medication": sorted(by_medication, key=lambda row: (-(row["UNCLEAR"] + row["REFUSED"] + row["DUPLICATE_SUSPECTED"]), row.get("scheduled_time") or "")),
        "by_weekday_time": by_weekday_time,
        "reviews": review_status,
        "registered_signal_matches": registered_matches,
        "safety_notice": "복약 상태와 등록된 관찰 기준의 대조 결과입니다. 약 변경·중단 지시가 아닙니다.",
    }
