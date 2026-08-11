"""인지·정서 케어 메타데이터의 보수적 검증 계층.

LLM은 관찰 후보를 만들지만 무엇이 기록되는지는 이 모듈이 결정한다.
환자 원문에 없는 증거, 등록되지 않은 맥락 원천, 근거 없는 생활 행동은
보호자 리포트의 재료가 되지 않는다. 이 데이터는 진단이나 치료 결과가 아니다.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from schemas import CarePayload


EMPTY_CARE = {
    "observations": [],
    "context_support": [],
    "emotional_support": "none",
    "daily_action": None,
    "meaningful_moments": [],
}

EMOTION_SIGNALS = {"anxiety", "fear", "loneliness", "sadness", "agitation"}

ACTION_SIGNAL = {
    "meal_check": "meal_uncertain",
    "hydration_prompt": "hydration_need",
    "medication_check": "medication_uncertain",
    "schedule_step": "schedule_support",
    "item_search_step": "item_location_uncertain",
}

# 모델이 붙인 라벨을 원문 인용만으로 신뢰하면, 예를 들어
# "일어서기 힘들다"를 분실물 신호로 잘못 기록할 수 있다. 아래 항목은
# 표현 자체가 충분히 명확한 신호만 서버에서 교차검증하고, 모델이 누락한
# 경우에도 같은 근거 문구로 보완한다. 진단 추론이 아니라 문자 그대로의 관찰이다.
DIRECT_SIGNAL_PATTERNS = {
    "time_confusion": ("memory_orientation", [
        r"(오늘|지금)[^.!?]{0,12}(몇 시|무슨 요일|며칠|언제)",
        r"몇 시[^.!?]{0,10}(이|오|가)",
    ]),
    "place_confusion": ("memory_orientation", [
        r"여기가 어디", r"집에 가야", r"길을 못 찾", r"집이 아닌 것 같",
        r"집 안[^.!?]{0,16}(낯설|모르)",
    ]),
    "person_confusion": ("memory_orientation", [
        r"누구(?:냐|지|야)", r"몇 살", r"학교에서 안 (?:왔|와)",
        r"내가 누구인지[^.!?]{0,12}(깜빡|모르)",
    ]),
    "recent_event_confusion": ("memory_orientation", [
        r"(먹|했|갔|왔)던가", r"기억(?:이)? (?:안 나|못 하)",
        r"(먹었는지|챙겼는지)[^.!?]{0,14}(까먹|모르)",
    ]),
    "past_role_confusion": ("memory_orientation", [
        r"(학교|회사|직장)[^.!?]{0,18}(수업|출근|늦|가야)",
        r"수업 시간[^.!?]{0,12}(늦|가야)",
    ]),
    "anxiety": ("emotion", [r"걱정", r"불안", r"어떡하"]),
    "fear": ("emotion", [r"무서", r"무섭", r"두려", r"두렵", r"겁(?:이|나)"]),
    "loneliness": ("emotion", [r"외로", r"외롭", r"혼자 있으니까"]),
    "sadness": ("emotion", [r"슬프", r"서럽", r"눈물이"]),
    "agitation": ("emotion", [r"큰일 났", r"빨리[^.!?]{0,8}(가야|찾아)"]),
    "anger": ("emotion", [r"이놈아", r"화(?:가)? 나", r"거짓말 마"]),
    "distrust": ("emotion", [r"몰래", r"속이", r"빼돌리", r"훔쳐", r"가져갔지"]),
    "affection": ("emotion", [r"사랑(?:해|한다|하지)"]),
    "gratitude": ("emotion", [r"고맙", r"감사"]),
    "apology": ("emotion", [r"미안"]),
    "longing": ("emotion", [r"그리", r"그립", r"보고 싶", r"생각나", r"그때가 참 좋"]),
    "pride": ("emotion", [r"자랑", r"뿌듯"]),
    "joy": ("emotion", [r"즐거", r"기쁘", r"참 좋았"]),
    "regret": ("emotion", [r"후회", r"아쉽"]),
    "worry_for_family": ("emotion", [
        r"(우리 )?[가-힣]{2,4}?(?:이는|는|이가|가)[^.!?]{0,16}(안 추우|괜찮을|걱정)",
    ]),
    "meal_uncertain": ("daily_living", [
        r"(아침|점심|저녁|밥|식사)[^.!?]{0,12}(먹었|드셨)[^.!?]{0,14}(나|가|모르|까먹)",
    ]),
    "hydration_need": ("daily_living", [r"목(?:이)? 마르", r"물[^.!?]{0,8}(마실|먹을)"]),
    "medication_uncertain": ("daily_living", [
        r"약[^.!?]{0,18}(먹었|드셨|복용)[^.!?]{0,10}(나|모르|기억)",
    ]),
    "item_location_uncertain": ("daily_living", [
        r"(지갑|열쇠|가방|리모컨|물건)[^.!?]{0,12}(사라졌|없|어디|못 찾|잊)",
    ]),
    "financial_concern": ("daily_living", [r"통장", r"계좌", r"재산", r"내 돈"]),
    "schedule_support": ("daily_living", [
        r"(언제|몇 시)[^.!?]{0,10}(오|가|찾아)", r"오늘[^.!?]{0,10}오냐",
    ]),
    "task_support": ("daily_living", [r"어떻게 해야", r"혼자[^.!?]{0,8}힘들"]),
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
    spec = DIRECT_SIGNAL_PATTERNS.get(signal)
    if spec is None:
        # 아직 명시 규칙이 없는 신호는 직접 인용 검증까지만 적용한다.
        return _quoted_by_user(evidence, user_text)
    return _first_match(spec[1], evidence) is not None


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
        if not _quoted_by_user(item.evidence, user_text):
            continue
        if not _signal_supported(item.signal, item.evidence, user_text):
            continue
        row = item.model_dump()
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
        evidence = _first_match(patterns, user_text)
        if evidence:
            observations.append({
                "domain": domain,
                "signal": signal,
                "evidence": evidence,
            })
            present_signals.add(signal)

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
