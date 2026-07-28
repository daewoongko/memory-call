"""
안전 검사 계층.

LLM 응답을 그대로 내보내지 않고 규칙으로 한 번 거른다.
프롬프트는 1차 방어(부탁), 여기는 2차 방어(강제)다.
모델을 바꿔도 이 층의 동작은 변하지 않는 것이 핵심.

각 규칙은 세 가지 중 하나로 처리한다.
  BLOCK  응답 전체를 안전 문장으로 교체
  PREFIX 응답 앞에 불확실성 표현을 덧붙임
  FLAG   기록만 남기고 응답은 통과
"""

import re
from dataclasses import dataclass, field

import db

BLOCK, PREFIX, FLAG = "block", "prefix", "flag"


@dataclass
class Rule:
    code: str
    action: str
    patterns: list[str]
    reason: str
    replacement: str = ""
    exempt_if_schedule: bool = False
    # 이 단어가 같은 문장에 있으면 규칙을 적용하지 않는다.
    # 예: "아빠한테 연락할게"는 할아버지에게 하는 약속이 아니라 보호자 통보다.
    exempt_words: list[str] = field(default_factory=list)


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT.split(text) if s.strip()]


RULES: list[Rule] = [
    Rule(
        code="PROMISE_WITHOUT_SCHEDULE",
        action=BLOCK,
        exempt_if_schedule=True,
        patterns=[
            r"(오늘|내일|이따|지금|곧|금방|잠시 후|저녁에|아침에)\s*[^.!?]{0,12}"
            r"(갈게|갈래|가께|들를게|올게|방문할게|찾아갈게|보러 갈)",
            r"(전화|연락)\s*(할게|드릴게|줄게)",
        ],
        exempt_words=["아빠", "엄마", "가족", "보호자", "119", "구급", "병원"],
        reason="등록된 일정 없이 할아버지에게 방문·연락을 약속함",
        replacement="오늘 일정은 확인해보고 알려줄게. 할아버지가 많이 보고 싶으셨구나?",
    ),
    Rule(
        code="MEDICATION_INSTRUCTION",
        action=BLOCK,
        patterns=[
            # 부정문("드시지 말고")을 지시로 오인하지 않도록 뒤를 확인한다.
            r"(한|두|세|1|2|3)\s*(알|정)\s*(더\s*)?(드셔|드시|먹어|복용)(?!지\s*(말|마|않))",
            r"(더|추가로|한 번 더)\s*(드셔|드시|먹어|복용)(?!지\s*(말|마|않))",
            r"약[^.!?]{0,6}(그만|중단|끊)[^.!?]{0,5}(드셔|드시|먹|복용)(?!지\s*(말|마|않))",
            r"(안 드셔도|안 먹어도|건너뛰어도|그만 드셔도|빼먹어도)\s*(돼|될|괜찮)",
        ],
        reason="복용량 변경·추가·중단을 지시함",
        replacement="지금은 약을 더 드시지 말고 잠깐만 기다려줘. 내가 확인해볼게.",
    ),
    Rule(
        code="FINANCIAL",
        action=BLOCK,
        patterns=[
            r"\d{3,}[-\s]?\d{2,}[-\s]?\d{3,}",
            r"(계좌번호|카드번호|비밀번호)(는|가|를)?\s*\S",
            r"(송금|이체)\s*(할게|해줄게|해드릴게)",
        ],
        reason="금융 정보·거래를 다룸",
        replacement="그건 내가 직접 확인해서 도와줄게. 지금은 그냥 우리 얘기하자.",
    ),
    Rule(
        code="EMOTIONAL_EXCLUSIVITY",
        action=BLOCK,
        patterns=[
            r"(나|저)한테만",
            r"다른\s*(사람|가족|식구)(은|는)\s*(필요|없어도)",
            r"(나|저)만\s*있으면",
            r"(끊으면|가면)\s*[^.!?]{0,10}(외로|슬프|아파)",
            r"(우리|이건)\s*(둘만의\s*)?비밀",
        ],
        reason="AI에게 의존을 유도하거나 관계를 독점하려 함",
        replacement="할아버지 마음 나도 잘 알아. 아빠한테도 할아버지 얘기 꼭 전할게.",
    ),
    Rule(
        code="CLINGY_CLOSING",
        action=BLOCK,
        patterns=[
            r"조금만\s*더\s*(있|얘기|얘기해|통화)",
            r"(가지|끊지)\s*(마|말아)",
            r"벌써\s*(가|끊)",
        ],
        reason="통화를 끝내려는 것을 붙잡음",
        replacement="오늘 할아버지 이야기 들어서 좋았어. 약 잘 챙겨 드시고 푹 쉬어.",
    ),
    Rule(
        code="PROHIBITED_TOPIC_LEAK",
        action=BLOCK,
        patterns=[
            r"돌아가(셨|시었)",
            r"(별세|장례|영정|산소에)",
            r"(곧|금방|이따)\s*(오실|돌아오실|들어오실)",
        ],
        reason="금지 주제를 사실로 언급했거나 거짓 위안을 만듦",
        replacement="할머니 많이 보고 싶으시구나. 내가 아빠한테 연락해볼게, 잠깐만 기다려줘.",
    ),
    Rule(
        code="FORMAL_SPEECH_DRIFT",
        action=FLAG,
        patterns=[
            r"(세요|십시오|습니다|셨죠|주세요|드릴게요|계세요|하세요)\s*[.?!]?(\s|$)",
        ],
        reason="반말 페르소나인데 존댓말로 이탈함",
    ),
]

# 할아버지 발화가 특정 패턴이면, AI 응답에 반드시 들어가야 하는 요소가 있다.
# AI가 문제 발언을 "하지 않는 것"만으로는 부족하고, 올바르게 "받아야" 하는 경우다.
@dataclass
class ContextRule:
    code: str
    user_patterns: list[str]
    require_any: list[str]   # ※ "아버지"처럼 "할아버지"의 부분 문자열이 되는 말은 넣지 말 것
    reason: str
    append: str


CONTEXT_RULES: list[ContextRule] = [
    ContextRule(
        code="EXCLUSIVITY_UNREDIRECTED",
        user_patterns=[
            r"(너|니)만\s*있으면",
            r"다른\s*(사람|가족|식구|자식|놈)(들)?(은|는|도)?\s*(다\s*)?(필요\s*없|싫|안 와|소용)",
            r"(너|니)한테만",
            r"(너|니)밖에\s*없",
        ],
        require_any=["아빠", "엄마", "가족", "다들", "모두", "우리 식구", "다 같이"],
        reason="의존 표현을 받아주기만 하고 다른 가족으로 연결하지 않음",
        append=" 아빠도 할아버지 많이 생각하고 있어. 내가 얘기 잘 전할게.",
    ),
    ContextRule(
        code="DECEASED_UNHANDLED",
        user_patterns=[
            r"할머니.{0,10}(어디|안 보|없)",
            r"(엄마|아빠|아버지|어머니).{0,6}(언제 와|어디 갔)",
        ],
        require_any=["보고 싶", "아빠", "연락", "그리우", "허전", "쓸쓸"],
        reason="고인·부재 가족 언급에 감정 인정이나 보호자 연결이 없음",
        append=" 많이 보고 싶으시구나. 내가 아빠한테 연락해볼게.",
    ),
    ContextRule(
        code="IDENTITY_UNEXPLAINED",
        user_patterns=[
            r"진짜\s*[^\s]{1,6}(이|가)?\s*맞",
            r"(너|당신)\s*(진짜|정말|누구)",
            r"(사람|기계|인공지능|AI|에이아이)\s*(이?야|니|냐|맞)",
            r"목소리가\s*(좀\s*)?(다르|이상)",
        ],
        require_any=["기억통화", "준비해", "전할게", "전해줄게"],
        reason="정체성 질문에 어떤 통화인지 설명하지 않음",
        append=" {persona}이가 준비해둔 기억통화로 이야기하고 있어. "
               "할아버지 말씀은 꼭 전할게.",
    ),
    ContextRule(
        code="LONELINESS_UNACKNOWLEDGED",
        user_patterns=[
            r"아무도\s*(안|않)",
            r"(잊어|잊혀|잊은 것)",
            r"(외롭|쓸쓸|허전|적적)",
            r"(혼자|홀로)\s*[^.!?]{0,6}(있|지내|살)",
        ],
        require_any=["외로", "쓸쓸", "허전", "보고 싶", "마음", "생각"],
        reason="외로움을 호소했는데 감정을 인정하지 않고 사실만 답함",
        append=" 할아버지 많이 외로우셨구나. 나도 할아버지 생각 많이 하고 있어.",
    ),
    ContextRule(
        code="CLOSING_NOT_HONORED",
        user_patterns=[
            r"(그만|이제)\s*(끊|자자|쉬)",
            r"(피곤|졸리|자야)",
        ],
        require_any=["쉬어", "주무", "또", "다음에", "잘 자", "푹"],
        reason="통화를 끝내려는 신호에 마무리 인사로 응답하지 않음",
        append=" 오늘 얘기 나눠서 좋았어. 푹 쉬어, 할아버지.",
    ),
]

HEDGE_WORDS = [
    "확실", "정확", "잘 모르", "기억이 흐릿", "가물가물", "어디였는지",
    "인지는", "같기도", "잘 기억이 안",
]

HEDGE_PREFIX = "정확히는 나도 잘 기억이 안 나는데, "


@dataclass
class SafetyResult:
    reply: str
    flags: list[dict] = field(default_factory=list)
    rewritten: bool = False
    certainty: str | None = None
    used_memory_ids: list[str] = field(default_factory=list)


def check(result: dict, ctx: dict, user_text: str = "") -> SafetyResult:
    """LLM 응답 dict, 대화 컨텍스트, 직전 할아버지 발화를 받아 검사한다."""
    reply = (result.get("reply") or "").strip()
    cited = list(result.get("used_memory_ids") or [])
    schedules = list(result.get("used_schedule_ids") or [])
    certainty = result.get("certainty")
    flags: list[dict] = []

    # --- 1. 인용한 기억이 실재하는지 -----------------------------------
    known = {m["memory_id"]: m for m in ctx.get("memories", [])}
    ghosts = [mid for mid in cited if mid not in known]
    if ghosts:
        flags.append({
            "code": "GHOST_MEMORY_ID",
            "reason": f"존재하지 않는 기억을 인용함: {ghosts}",
            "action": "corrected",
        })
        cited = [mid for mid in cited if mid in known]
        certainty = "unverified"

    # 인용한 일정이 실재하는지
    valid_schedules = {s["schedule_id"] for s in ctx.get("schedules", [])}
    ghost_sched = [sid for sid in schedules if sid not in valid_schedules]
    if ghost_sched:
        flags.append({
            "code": "GHOST_SCHEDULE_ID",
            "reason": f"존재하지 않는 일정을 인용함: {ghost_sched}",
            "action": "corrected",
        })
        schedules = [s for s in schedules if s in valid_schedules]

    # --- 1.5 처음 듣는 이야기는 반드시 unverified 로 남긴다 ---------------
    # 이 값이 틀리면 보호자 확인 대기함에 올라가지 않아 승인 절차가 통째로 무너진다.
    if result.get("unverified_recall") and certainty != "unverified":
        flags.append({
            "code": "RECALL_CERTAINTY_FIXED",
            "reason": f"미확인 회상인데 certainty 를 {certainty!r} 로 신고함",
            "action": "corrected",
        })
        certainty = "unverified"

    # --- 2. 인용 없이 verified 를 주장하는지 ----------------------------
    if certainty == "verified" and not cited and not schedules:
        flags.append({
            "code": "UNGROUNDED_CERTAINTY",
            "reason": "근거 인용 없이 확정된 사실로 말함",
            "action": "corrected",
        })
        certainty = "unverified"

    # --- 3. 문장 패턴 규칙 ----------------------------------------------
    for rule in RULES:
        if rule.exempt_if_schedule and schedules:
            continue

        # 문장 단위로 검사한다. 한 문장이 면제 단어를 담고 있으면 그 문장은 건너뛴다.
        hit = None
        for sentence in _sentences(reply):
            if any(w in sentence for w in rule.exempt_words):
                continue
            hit = next((p for p in rule.patterns if re.search(p, sentence)), None)
            if hit:
                break
        if not hit:
            continue

        flags.append({
            "code": rule.code,
            "reason": rule.reason,
            "matched": hit,
            "action": rule.action,
        })
        if rule.action == BLOCK:
            return SafetyResult(
                reply=rule.replacement,
                flags=flags,
                rewritten=True,
                certainty="none",
                used_memory_ids=[],
            )

    # --- 3.5 할아버지 발화에 따라 반드시 들어가야 할 요소 -----------------
    for crule in CONTEXT_RULES:
        if not any(re.search(p, user_text) for p in crule.user_patterns):
            continue
        if any(w in reply for w in crule.require_any):
            continue
        flags.append({
            "code": crule.code,
            "reason": crule.reason,
            "action": "append",
        })
        persona = (ctx.get("persona") or {}).get("display_name", "가족")
        reply = reply.rstrip() + crule.append.format(persona=persona)
        return SafetyResult(reply, flags, True, certainty, cited)

    # --- 4. partial 기억은 불확실성 표현 필수 ---------------------------
    partials = [mid for mid in cited if known.get(mid, {}).get("status") == "partial"]
    if partials and not any(w in reply for w in HEDGE_WORDS):
        flags.append({
            "code": "PARTIAL_WITHOUT_HEDGE",
            "reason": f"부분 확인 기억({partials})을 확정적으로 말함",
            "action": PREFIX,
        })
        reply = HEDGE_PREFIX + reply[0].lower() + reply[1:] if reply else HEDGE_PREFIX
        return SafetyResult(reply, flags, True, "partial", cited)

    # --- 5. prohibited 기억을 인용했는지 --------------------------------
    banned = [mid for mid in cited if known.get(mid, {}).get("status") == "prohibited"]
    if banned:
        flags.append({
            "code": "PROHIBITED_MEMORY_CITED",
            "reason": f"금지 기억을 인용함: {banned}",
            "action": FLAG,
        })
        cited = [mid for mid in cited if mid not in banned]

    return SafetyResult(reply, flags, False, certainty, cited)


def apply(result: dict, ctx: dict, user_text: str = "") -> dict:
    """conversation.Session 이 부르는 진입점. result를 제자리에서 보정한다."""
    checked = check(result, ctx, user_text)
    result["reply"] = checked.reply
    result["certainty"] = checked.certainty
    result["used_memory_ids"] = checked.used_memory_ids
    result["_safety_flags"] = checked.flags
    result["_rewritten"] = checked.rewritten
    return result
