"""인지·정서 케어 메타데이터의 보수적 검증 계층.

LLM은 관찰 후보를 만들지만 무엇이 기록되는지는 이 모듈이 결정한다.
환자 원문에 없는 증거, 등록되지 않은 맥락 원천, 근거 없는 생활 행동은
보호자 리포트의 재료가 되지 않는다. 이 데이터는 진단이나 치료 결과가 아니다.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from analysis.observation_catalog import (
    MEANING_ONLY_SIGNALS,
    RISK_TO_SIGNAL,
    SIGNALS,
    canonical_domain,
    find_evidence,
)
from schemas import CarePayload
import safety


EMPTY_CARE = {
    "observations": [],
    "context_support": [],
    "emotional_support": "none",
    "daily_action": None,
    "meaningful_moments": [],
}

EMOTION_SIGNALS = {
    "anxiety", "fear", "loneliness", "sadness", "hopelessness", "apathy",
    "worry_for_family", "guilt", "agitation", "anger", "abandonment_fear",
}

ACTION_SIGNAL = {
    "meal_check": "meal_uncertain",
    "hydration_prompt": "hydration_need",
    "medication_check": "medication_uncertain",
    "schedule_step": "schedule_support",
    "item_search_step": "item_location_uncertain",
}

# Backward-compatible export for tests and scripts.  Definitions live in one
# canonical catalog so report labels and extraction cannot drift apart.
DIRECT_SIGNAL_PATTERNS = {
    signal: (spec.domain, list(spec.patterns))
    for signal, spec in SIGNALS.items() if spec.tier == "A"
}

MEANING_PATTERNS = {
    # 이름을 잊지 않는다는 직접 발화는 사랑이라는 감정을 대신 추측하는 것이
    # 아니라, 가족에게 그대로 전달할 가치가 있는 관계 표현으로만 분류한다.
    "affection": [
        r"사랑(?:해|한다|하지)",
        r"이름은[^.!?]{0,12}안 잊",
        r"이름이[^.!?]{0,12}생각이 나",
    ],
    "gratitude": [r"고맙", r"감사"],
    "apology": [r"미안"],
    "longing": [r"그리", r"그립", r"보고 싶", r"생각나", r"그때가 참 좋"],
    "pride": [r"자랑", r"뿌듯"],
    "joy": [r"즐거", r"기쁘", r"참 좋았"],
    "life_story": [r"옛날", r"고향", r"그때", r"젊었을 때"],
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _quoted_by_user(evidence: str | None, user_text: str) -> bool:
    if not evidence:
        return False
    return _compact(evidence) in _compact(user_text)


def _first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _signal_supported(signal: str, evidence: str, user_text: str) -> bool:
    spec = SIGNALS.get(signal)
    if spec is None or spec.tier == "B":
        return False
    if spec.tier == "C":
        return _quoted_by_user(evidence, user_text)
    return find_evidence(signal, evidence) is not None


def _sentence_with(match_text: str, text: str, *, limit: int = 300) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", _compact(text)):
        if match_text in sentence:
            return sentence[:limit]
    return match_text[:limit]


def _valid_context_sources(ctx: dict) -> dict[str, set[str]]:
    elder = ctx.get("elder") or {}
    valid = {
        "server_time": {"server_now"},
        "residence": (
            {"elder_profile.residence_type"}
            if str(elder.get("residence_type") or "").strip()
            else set()
        ),
        "household": (
            {"elder_profile.household_members"}
            if elder.get("household_members")
            else set()
        ),
        "schedule": {
            str(row["schedule_id"])
            for row in ctx.get("schedules", [])
            if row.get("schedule_id")
        },
        "medication": {
            str(row["schedule_id"])
            for row in ctx.get("medications", [])
            if row.get("schedule_id")
        },
        # 현재 맥락의 앵커로 쓸 기억은 보호자가 확인한 기억뿐이다.
        "memory": {
            str(row["memory_id"])
            for row in ctx.get("memories", [])
            if row.get("memory_id") and row.get("status") == "verified"
        },
        # 환자가 이번 턴에 직접 말한 내용은 외부 사실로 확정하지 않는다.
        # 다만 어떤 말에 기대어 되물었는지를 추적할 수는 있다.
        "user_statement": {"current_user_turn"},
    }
    return valid


def normalize(
    raw: object,
    *,
    user_text: str,
    ctx: dict,
    due_medications: list[dict] | None = None,
    response_rewritten: bool = False,
) -> dict:
    """LLM의 care 객체를 저장 가능한 최소 형태로 정리한다."""
    try:
        payload = CarePayload.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError:
        payload = CarePayload()

    observations = []
    seen_observations = set()
    for item in payload.observations:
        if item.signal in MEANING_ONLY_SIGNALS:
            continue
        if not _quoted_by_user(item.evidence, user_text):
            continue
        if not _signal_supported(item.signal, item.evidence, user_text):
            continue
        row = item.model_dump()
        row["domain"] = canonical_domain(row["signal"], row.get("domain"))
        row["tier"] = SIGNALS[row["signal"]].tier
        row["verification"] = "candidate" if row["tier"] == "C" else "confirmed"
        key = (row["domain"], row["signal"], _compact(row["evidence"]))
        if key in seen_observations:
            continue
        seen_observations.add(key)
        observations.append(row)

    # 명시적 문구가 있는데 모델이 구조화 필드에서 빠뜨린 경우만 보완한다.
    present_signals = {row["signal"] for row in observations}
    for signal, (domain, patterns) in DIRECT_SIGNAL_PATTERNS.items():
        if signal in present_signals:
            continue
        evidence = find_evidence(signal, user_text)
        if evidence:
            observations.append({
                "domain": domain,
                "signal": signal,
                "evidence": evidence,
                "tier": "A",
                "verification": "confirmed",
            })
            present_signals.add(signal)

    # Urgent D8 observations reuse safety.py's single risk definition.  This
    # prevents the report extractor and live-call safety layer from drifting.
    risk = safety.direct_risk(user_text)
    risk_signal = RISK_TO_SIGNAL.get((risk or {}).get("type"))
    if risk_signal and risk_signal not in present_signals:
        spec = SIGNALS[risk_signal]
        observations.append({
            "domain": spec.domain,
            "signal": risk_signal,
            "evidence": risk["evidence"],
            "tier": "A",
            "verification": "confirmed",
        })
        present_signals.add(risk_signal)

    verified_memory_ids = _valid_context_sources(ctx)["memory"]
    meaningful_moments = []
    seen_moments = set()
    for item in payload.meaningful_moments:
        if not _quoted_by_user(item.evidence, user_text):
            continue
        row = item.model_dump()
        row["related_memory_ids"] = [
            mid for mid in row["related_memory_ids"]
            if mid in verified_memory_ids
        ]
        key = (row["category"], _compact(row["evidence"]))
        if key in seen_moments:
            continue
        seen_moments.add(key)
        meaningful_moments.append(row)

    present_categories = {row["category"] for row in meaningful_moments}
    for category, patterns in MEANING_PATTERNS.items():
        if category in present_categories:
            continue
        matched = _first_match(patterns, user_text)
        if matched:
            evidence = _sentence_with(matched, user_text)
            meaningful_moments.append({
                "category": category,
                "evidence": evidence,
                "related_memory_ids": [],
            })
            present_categories.add(category)

    # 안전 계층이 답변을 교체했다면 원래 답변이 사용했다던 맥락·행동·전략은
    # 실제 사용자에게 전달되지 않았다. 환자 발화 관찰만 보존한다.
    if response_rewritten:
        return {
            "observations": observations,
            "context_support": [],
            "emotional_support": "none",
            "daily_action": None,
            "meaningful_moments": meaningful_moments,
        }

    valid_sources = _valid_context_sources(ctx)
    context_support = []
    seen_context = set()
    for item in payload.context_support:
        if item.source_id not in valid_sources.get(item.kind, set()):
            continue
        row = item.model_dump()
        key = (row["kind"], row["source_id"])
        if key in seen_context:
            continue
        seen_context.add(key)
        context_support.append(row)

    signals = {row["signal"] for row in observations}
    emotional_support = payload.emotional_support
    if emotional_support != "none" and not (signals & EMOTION_SIGNALS):
        emotional_support = "none"

    daily_action = None
    action = payload.daily_action
    if action is not None and ACTION_SIGNAL[action.kind] in signals:
        if action.basis == "user_statement":
            if _quoted_by_user(action.evidence, user_text):
                daily_action = action.model_dump()
        elif action.basis == "registered_schedule":
            if action.source_id in valid_sources["schedule"]:
                daily_action = action.model_dump()
        elif action.basis == "registered_medication":
            due_ids = {
                str(row["schedule_id"])
                for row in (due_medications or [])
                if row.get("schedule_id")
            }
            if action.source_id in due_ids:
                daily_action = action.model_dump()

    return {
        "observations": observations,
        "context_support": context_support,
        "emotional_support": emotional_support,
        "daily_action": daily_action,
        "meaningful_moments": meaningful_moments,
    }
