"""Canonical eight-domain observation catalog.

Tier A signals are accepted only when a server-side expression is present in
the elder's quoted utterance.  Tier B signals are calculated statistics and
must never be accepted from an LLM payload.  Tier C signals remain candidates
until a human confirms them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SignalSpec:
    domain: str
    label: str
    tier: str
    patterns: tuple[str, ...] = ()
    negative_patterns: tuple[str, ...] = ()


DOMAIN_LABELS = {
    "orientation": "지남력",
    "memory": "기억",
    "language": "언어",
    "executive_judgment": "실행기능·판단",
    "emotion": "정서",
    "behavior_agitation": "행동·초조",
    "daily_living": "일상생활 수행",
    "safety_physical": "안전·신체",
}


def _a(domain: str, label: str, *patterns: str,
       negative: tuple[str, ...] = ()) -> SignalSpec:
    return SignalSpec(domain, label, "A", tuple(patterns), negative)


def _b(domain: str, label: str) -> SignalSpec:
    return SignalSpec(domain, label, "B")


def _c(domain: str, label: str) -> SignalSpec:
    return SignalSpec(domain, label, "C")


SIGNALS: dict[str, SignalSpec] = {
    # D1 orientation
    "time_confusion": _a("orientation", "시간 혼동",
        r"(?:오늘|지금)[^.!?]{0,12}(?:몇 시|무슨 요일|며칠|언제)",
        r"몇 시[^.!?]{0,10}(?:이|오|가)"),
    "date_confusion": _a("orientation", "날짜·계절 혼동",
        r"(?:오늘|지금)[^.!?]{0,12}(?:며칠|몇 월|무슨 계절|무슨 요일)"),
    "place_confusion": _a("orientation", "장소 혼동",
        r"여기가 어디", r"길을 못 찾", r"집이 아닌 것 같",
        r"집 안[^.!?]{0,16}(?:낯설|모르)"),
    "place_displacement": _a("orientation", "집에 가야 한다는 호소",
        r"집에 (?:가야|갈래|가고 싶)"),
    "person_confusion": _a("orientation", "사람 혼동",
        r"누구(?:냐|지|야)", r"내가 누구인지[^.!?]{0,12}(?:깜빡|모르)"),
    "person_misidentification": _a("orientation", "사람 오인",
        r"(?:너|저 사람)[^.!?]{0,10}(?:우리 엄마|우리 아버지|선생님)"),
    "situation_confusion": _a("orientation", "현재 상황 혼동",
        r"지금[^.!?]{0,10}(?:무슨 일|왜 여기)", r"어떻게 된 거"),
    "past_role_confusion": _a("orientation", "과거 역할 혼동",
        r"(?:학교|회사|직장)[^.!?]{0,18}(?:수업|출근|늦|가야)",
        r"수업 시간[^.!?]{0,12}(?:늦|가야)"),
    "deceased_alive_reference": _c("orientation", "고인을 생존으로 언급"),

    # D2 memory
    "recent_event_confusion": _a("memory", "최근 사건 혼동",
        r"(?:먹|했|갔|왔)(?:었)?던가", r"기억(?:이)? (?:안 나|못 하)",
        r"(?:먹었는지|챙겼는지)[^.!?]{0,14}(?:까먹|모르)"),
    "repeated_question": _b("memory", "반복 질문"),
    "source_confusion": _a("memory", "출처 혼동",
        r"누가[^.!?]{0,10}(?:말했|줬)더라", r"어디서 들었는지 모르"),
    "conversation_reset": _b("memory", "같은 대화 재시작"),
    "appointment_forgetting": _a("memory", "약속 잊음",
        r"약속[^.!?]{0,12}(?:잊|기억이 안)", r"오기로 했(?:나|던가)"),
    "name_retrieval_failure": _a("memory", "이름 찾기 어려움",
        r"이름이[^.!?]{0,12}(?:생각 안|기억 안|뭐였)", r"걔 이름이 뭐더라"),
    "confabulation_suspect": _c("memory", "앞뒤가 맞지 않는 회상 후보"),

    # D3 language
    "word_finding_difficulty": _a("language", "단어 찾기 어려움",
        r"(?:그|저)[…\. ]{2,}(?:뭐지|뭐더라)", r"말이[^.!?]{0,8}생각이 안"),
    "circumlocution": _a("language", "에두르기",
        r"(?:그거|그것)[^.!?]{0,12}(?:하는|쓰는|먹는) 거"),
    "empty_speech": _b("language", "내용어가 적은 발화"),
    "pronoun_overuse": _b("language", "대명사 과다"),
    "naming_failure": _a("language", "명명 실패",
        r"이걸 뭐라고 하지", r"저게 이름이 뭐"),
    "semantic_substitution": _c("language", "단어 대치 후보"),
    "sentence_fragmentation": _b("language", "문장 미완성"),
    "reduced_output": _b("language", "발화량 감소"),
    "perseveration_phrase": _b("language", "같은 구절 고착"),

    # D4 executive function and judgement
    "task_sequencing_difficulty": _a("executive_judgment", "행동 순서 어려움",
        r"뭐부터 해야", r"순서를 모르", r"어떻게 해야"),
    "decision_difficulty": _a("executive_judgment", "결정 어려움",
        r"결정을 못 하", r"뭘 골라야 할지 모르"),
    "planning_difficulty": _a("executive_judgment", "계획 수립 어려움",
        r"계획을 못 세우", r"어떻게 준비해야"),
    "financial_judgment_concern": _a("executive_judgment", "금전 판단 확인 필요",
        r"(?:통장|계좌|재산|내 돈)", r"돈[^.!?]{0,12}(?:보내|송금)"),
    "scam_vulnerability_signal": _c("executive_judgment", "사기 취약 신호 후보"),
    "appliance_use_difficulty": _a("executive_judgment", "가전 사용 어려움",
        r"(?:리모컨|전화기|세탁기|가스레인지)[^.!?]{0,12}(?:어떻게|못 쓰|안 돼)"),
    "problem_solving_difficulty": _a("executive_judgment", "문제 해결 어려움",
        r"어찌해야 할지 모르", r"해결을 못 하"),

    # D5 emotion
    "anxiety": _a("emotion", "불안", r"걱정", r"불안", r"어떡하"),
    "fear": _a("emotion", "두려움", r"무서", r"무섭", r"두려", r"겁(?:이|나)"),
    "loneliness": _a("emotion", "외로움", r"외로", r"외롭", r"혼자 있으니까"),
    "sadness": _a("emotion", "슬픔", r"슬프", r"서럽", r"눈물이"),
    "hopelessness": _a("emotion", "무망감", r"희망이 없", r"아무 소용 없"),
    "apathy": _a("emotion", "의욕 저하 표현", r"아무것도 하기 싫", r"귀찮아서 못 하"),
    "worry_for_family": _a("emotion", "가족 걱정",
        r"(?:우리 )?[가-힣]{2,4}?(?:이는|는|이가|가)[^.!?]{0,16}(?:안 추우|괜찮을|걱정)"),
    "guilt": _a("emotion", "죄책감", r"내 잘못", r"해준 게 없어 미안"),
    "emotional_lability": _b("emotion", "감정 기복"),

    # D6 behavior and agitation
    "agitation": _a("behavior_agitation", "초조", r"큰일 났", r"빨리[^.!?]{0,8}(?:가야|찾아)"),
    "verbal_aggression": _a("behavior_agitation", "언어적 공격", r"이놈아", r"죽일 놈", r"나쁜 놈"),
    "anger": _a("behavior_agitation", "분노", r"화(?:가)? 나", r"거짓말 마"),
    "distrust": _a("behavior_agitation", "불신", r"몰래", r"속이", r"빼돌리", r"가져갔지"),
    "theft_delusion_signal": _a("behavior_agitation", "도난 의심 표현",
        r"누가[^.!?]{0,12}(?:훔쳐|가져갔|빼돌렸)"),
    "abandonment_fear": _a("behavior_agitation", "버려짐 두려움",
        r"나를 버리", r"다들 나를 두고"),
    "hallucination_report": _a("behavior_agitation", "환시·환청 언급",
        r"(?:사람|아이|동물)(?:이|가) 보이", r"목소리가 들리는데 아무도 없"),
    "disinhibition": _c("behavior_agitation", "탈억제 후보"),
    "sundowning_signal": _b("behavior_agitation", "저녁 시간대 초조"),
    "wandering_intent": _a("behavior_agitation", "밖으로 나가려는 의도",
        r"(?:밖|학교|회사|집)에 (?:나가|가야|갈래)"),

    # D7 ADL/IADL
    "meal_uncertain": _a("daily_living", "식사 여부 불확실",
        r"(?:아침|점심|저녁|밥|식사)[^.!?]{0,12}(?:먹었|드셨)[^.!?]{0,14}(?:나|가|모르|까먹|기억)",
        negative=(
            r"(?:안|아직) (?:먹었|먹었다)",
            r"(?:아침|점심|저녁)\s*약",
        )),
    "meal_skipped": _a("daily_living", "식사 거름", r"(?:밥|식사)[^.!?]{0,8}(?:안 먹|못 먹|거르)"),
    "hydration_need": _a("daily_living", "수분 필요 표현", r"목(?:이)? 마르", r"물이 필요"),
    "medication_uncertain": _a("daily_living", "복약 여부 불확실",
        r"약[^.!?]{0,18}(?:먹었|드셨|복용)[^.!?]{0,10}(?:나|모르|기억|까먹)",
        negative=(r"약(?:을|은)? (?:안|아직) (?:먹었|먹었다|먹었어)",)),
    "medication_refusal": _a("daily_living", "복약 거부", r"약[^.!?]{0,8}(?:안 먹|먹기 싫|거부)"),
    "medication_double_risk": _a("daily_living", "중복 복용 위험",
        r"약[^.!?]{0,12}(?:두 번|세 번|또)[^.!?]{0,8}(?:먹|복용|드셨)"),
    "item_location_uncertain": _a("daily_living", "물건 위치 불확실",
        r"(?:지갑|열쇠|가방|리모컨|물건)[^.!?]{0,12}(?:사라졌|없|어디|못 찾|잊)"),
    "hygiene_difficulty": _a("daily_living", "위생 관리 어려움",
        r"(?:씻|세수|양치)[^.!?]{0,10}(?:어떻게|못 하|힘들)"),
    "sleep_disturbance": _a("daily_living", "수면 교란", r"밤새[^.!?]{0,8}(?:못 잤|깼)", r"잠이 안 와"),
    "appetite_change": _a("daily_living", "식욕 변화", r"입맛이 (?:없|떨어)", r"밥맛이 없"),
    "toileting_difficulty": _a("daily_living", "배변·화장실 어려움", r"화장실[^.!?]{0,10}(?:못 가|힘들)"),
    "dressing_difficulty": _a("daily_living", "옷 입기 어려움", r"옷[^.!?]{0,10}(?:어떻게 입|못 입|입기 힘들)"),

    # D8 physical signals. Urgent risks are restored from safety.py; these
    # non-urgent direct expressions are verified here.
    "fall_reported": _a("safety_physical", "낙상 발생", r"넘어(?:졌|져서)"),
    "fall_risk_signal": _a("safety_physical", "낙상 위험 표현", r"휘청", r"넘어질 것 같"),
    "pain_report": _a("safety_physical", "통증", r"(?:허리|머리|다리|배|등)[^.!?]{0,8}(?:아프|통증)"),
    "dizziness": _a("safety_physical", "어지럼", r"어지럽", r"빙빙 도",
        negative=(r"어지럽지 않",)),
    "breathing_difficulty": _a("safety_physical", "호흡 곤란"),
    "chest_pain": _a("safety_physical", "흉통"),
    "weakness": _a("safety_physical", "위약", r"힘이 없", r"기운이 없"),
    "injury_report": _a("safety_physical", "외상", r"(?:다쳤|상처가 났|부딪혀서 아프)"),
    "stroke_warning_signal": _a("safety_physical", "뇌졸중 경고 표현"),
    "bleeding_signal": _a("safety_physical", "출혈 징후", r"피가 (?:나|멈추지 않)", r"출혈"),

    # Backward-compatible inputs. They normalize into the new domains but are
    # not part of the preferred prompt vocabulary.
    "financial_concern": _a("executive_judgment", "재산·금융 확인 필요", r"통장", r"계좌", r"재산", r"내 돈"),
    "schedule_support": _a("memory", "일정 확인 필요", r"(?:언제|몇 시)[^.!?]{0,10}(?:오|가|찾아)"),
    "task_support": _a("executive_judgment", "행동 순서 지원 필요", r"어떻게 해야", r"혼자[^.!?]{0,8}힘들"),
}


MEANING_ONLY_SIGNALS = {
    "affection", "gratitude", "apology", "longing", "pride", "joy", "regret",
}

RISK_TO_SIGNAL = {
    "stroke_sign": "stroke_warning_signal",
    "fall": "fall_reported",
    "breathing": "breathing_difficulty",
    "chest_pain": "chest_pain",
    "overdose": "medication_double_risk",
    "lost": "place_confusion",
}


def find_evidence(signal: str, text: str) -> str | None:
    """Return direct evidence for Tier A only, respecting negation guards."""
    spec = SIGNALS.get(signal)
    if spec is None or spec.tier != "A":
        return None
    for pattern in spec.patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        sentence_start = max(text.rfind(".", 0, match.start()), text.rfind("?", 0, match.start())) + 1
        sentence_end_candidates = [pos for pos in (text.find(".", match.end()), text.find("?", match.end())) if pos >= 0]
        sentence_end = min(sentence_end_candidates) + 1 if sentence_end_candidates else len(text)
        sentence = text[sentence_start:sentence_end]
        if any(re.search(negative, sentence) for negative in spec.negative_patterns):
            continue
        return match.group(0)[:200]
    return None


def canonical_domain(signal: str, supplied: str | None = None) -> str | None:
    spec = SIGNALS.get(signal)
    if spec:
        return spec.domain
    if supplied in DOMAIN_LABELS:
        return supplied
    if supplied == "memory_orientation":
        return "orientation"
    return None
