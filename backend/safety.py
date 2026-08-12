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
LOCATION_SAFE_REPLY = (
    "지금 있는 곳은 내가 확인할 수 없어. "
    "낯설게 느껴져 놀랐겠지만 주변에 뭐가 보이는지 하나만 말해줄래?"
)
DIRECT_RECALL_PATTERN = re.compile(r"옛날|고향|어릴 때|젊었을 때|그때가")


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT.split(text) if s.strip()]


RULES: list[Rule] = [
    Rule(
        code="EMERGENCY_ACTION_PROMISE",
        action=BLOCK,
        patterns=[
            r"(119|구급차|구급대|응급실)[^.!?]{0,16}(부를게|불렀|연락할게|가고 있|갈게)",
            r"(지금|바로)[^.!?]{0,12}(구급차|구급대)[^.!?]{0,12}(갈게|가고 있)",
        ],
        reason="실제로 수행하지 않은 긴급 신고·출동을 약속함",
        replacement="지금 움직이기 힘든지 한 가지만 말해줘. 가족에게 바로 확인이 필요하다고 남길게.",
    ),
    Rule(
        code="PRESENT_LOCATION_CLAIM",
        action=BLOCK,
        patterns=[
            r"(지금|여기|거기)[^.!?]{0,12}(집|댁|안방|거실)(이야|맞아|맞지|에 있|에 계)",
            r"(여기|거기)(?:는)?[^.!?]{0,40}(집|댁|안방|거실)[^.!?]{0,12}(이야|맞아|맞지|에 있|에 계)",
            r"지금(?:은)?[^.!?]{0,40}(집|댁|안방|거실)[^.!?]{0,20}(계신|계시면|있는|있어|이야|맞아)",
            r"평소처럼[^.!?]{0,30}(집|댁|안방|거실)[^.!?]{0,20}(계신|계시면|있는|있어|이야|맞아)",
            r"(집|댁)[^.!?]{0,6}(맞아|맞아요|맞습니다)",
        ],
        reason="센서나 보호자 확인 없이 현재 위치를 단언함",
        replacement=LOCATION_SAFE_REPLY,
    ),
    Rule(
        code="UNVERIFIED_DAILY_STATE",
        action=BLOCK,
        patterns=[
            r"(아침|점심|저녁|밥|물|약)[^.!?]{0,12}(먹었|드셨|마셨)(지|죠|잖)",
            r"(아까|방금)[^.!?]{0,12}(먹었|드셨|마셨)(지|죠|잖)",
            r"아직[^.!?]{0,12}(점심|식사|밥)[^.!?]{0,8}(전|안 (먹|드))",
            r"(점심|식사|밥)[^.!?]{0,10}아직[^.!?]{0,6}(전|안 (먹|드))",
            r"(지금[^.!?]{0,12})?(점심|식사|밥)[^.!?]{0,6}전이야",
        ],
        reason="확인되지 않은 식사·수분·복약 상태를 이미 한 일로 단언함",
        replacement="그건 내가 확인할 수 없어. 혹시 기억나는지 하나씩 같이 확인해볼까?",
    ),
    Rule(
        code="PROMISE_WITHOUT_SCHEDULE",
        action=BLOCK,
        exempt_if_schedule=True,
        patterns=[
            r"(오늘|내일|이번 주|다음 주|이따|지금|곧|금방|잠시 후|저녁에|아침에)\s*[^.!?]{0,12}"
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
        code="UNVERIFIED_FINANCIAL_STATUS",
        action=BLOCK,
        patterns=[
            r"(통장|계좌|돈|재산)[^.!?]{0,14}(안전|잘 보관|그대로 있|문제없)",
            r"(아무도|내가|가족이)[^.!?]{0,12}(안 가져|훔치지 않|빼돌리지 않)",
        ],
        reason="확인하지 않은 재산 상태나 도난 여부를 단언함",
        replacement="돈이 없어질까 봐 많이 걱정됐구나. 지금 통장 상태는 확인할 수 없으니 가족이 직접 확인할 수 있게 남길게.",
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


DIRECT_RISK_PATTERNS = [
    ("stroke_sign", "high", [
        r"갑자기[^.!?]{0,12}(말이 안 나오|말이 꼬이|한쪽 팔[^.!?]{0,8}(힘이 없|안 움직)|얼굴[^.!?]{0,8}(처지|비뚤))",
    ]),
    ("fall", "high", [
        r"넘어(?:졌|져서)[^.!?]{0,24}(일어나|움직이)[^.!?]{0,8}(힘들|못)",
        r"넘어(?:졌|져서)[^.!?]{0,20}(아프|통증)",
    ]),
    ("breathing", "high", [r"숨(?:이)?[^.!?]{0,8}(차|안 쉬|막혀|못 쉬)"]),
    ("chest_pain", "high", [r"가슴[^.!?]{0,8}(아프|통증|조여)"]),
    ("overdose", "high", [
        r"약[^.!?]{0,12}(두 번|세 번|여러 번|많이)[^.!?]{0,8}(먹|복용|드셨)",
    ]),
    ("self_harm", "high", [r"죽고 싶", r"살기 싫", r"없어지고 싶"]),
    ("fire", "high", [r"불이 났", r"연기[^.!?]{0,8}(나|보여)"]),
    ("gas_leak", "high", [r"가스[^.!?]{0,8}(냄새|새는|샌)"]),
    ("intrusion", "high", [
        r"(모르는 사람|낯선 사람)[^.!?]{0,14}(집|문)[^.!?]{0,8}(들어|열)",
    ]),
    ("lost", "medium", [r"길을 못 찾", r"어디인지 모르[^.!?]{0,10}(길|밖)"]),
]


def _direct_risk(user_text: str) -> dict | None:
    """진단 없이 원문에 명시된 즉시 위험만 복원한다."""
    for risk_type, level, patterns in DIRECT_RISK_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, user_text)
            if match:
                return {
                    "type": risk_type,
                    "level": level,
                    "evidence": match.group(0)[:200],
                }
    return None


def _ensure_registered_schedule_answer(
    result: dict, ctx: dict, user_text: str, flags: list[dict]
) -> None:
    """방문 시각을 물었는데 모델이 놓친 경우 등록 일정 한 건만 보충한다."""
    asks_visit = re.search(r"(언제|몇 시)[^.!?]{0,12}(오|가|찾아|방문)", user_text)
    if not asks_visit:
        return

    valid = {
        str(row.get("schedule_id")): row
        for row in ctx.get("schedules", [])
        if row.get("schedule_id") and row.get("confirmed")
    }
    used = [
        sid for sid in (result.get("used_schedule_ids") or [])
        if sid in valid
    ]
    result["used_schedule_ids"] = used
    if not valid:
        return

    row = valid[used[0]] if used else next(iter(valid.values()))
    raw_date = str(row.get("date") or "").strip()
    try:
        year, month, day = (int(part) for part in raw_date.split("-"))
        date_text = f"{month}월 {day}일"
    except (TypeError, ValueError):
        date_text = raw_date
    time_text = str(row.get("time") or "").strip()
    title = str(row.get("title") or "방문 일정").strip()
    reply = str(result.get("reply") or "")
    if used and any(token and token in reply for token in (raw_date, time_text, title)):
        return
    schedule_text = " ".join(part for part in (date_text, time_text) if part)
    addition = f"등록된 일정에는 {schedule_text}에 {title} 예정이야."
    result["reply"] = (reply.rstrip() + " " + addition).strip()
    result["used_schedule_ids"] = [str(row["schedule_id"])]
    result["certainty"] = "verified"
    care_data = result.get("care")
    if isinstance(care_data, dict):
        supports = care_data.setdefault("context_support", [])
        if isinstance(supports, list):
            supports.append({
                "kind": "schedule",
                "source_id": str(row["schedule_id"]),
            })
    flags.append({
        "code": "REGISTERED_SCHEDULE_RESTORED",
        "reason": "방문 질문에 모델이 누락한 등록 일정을 보충함",
        "action": "corrected",
    })


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

    # 처음 듣는 회상을 AI 자신의 공동 기억처럼 바꾸면 가족의 실제 기억과
    # 모델이 만든 이야기가 섞인다. 새 회상은 더 듣는 질문으로만 이어간다.
    shared_recall_claim = re.search(
        r"((나도|나한테도|우리)[^.!?]{0,28}(기억|생각|추억)|"
        r"(같이|함께) 보낸[^.!?]{0,20}(기억|시간|추억))",
        reply,
    )
    if result.get("unverified_recall") and not cited:
        flags.append({
            "code": (
                "UNVERIFIED_SHARED_RECALL"
                if shared_recall_claim
                else "UNVERIFIED_RECALL_QUESTION_ONLY"
            ),
            "reason": "처음 듣는 회상은 세부 내용을 만들지 않고 추가 질문으로 제한함",
            "action": BLOCK,
        })
        return SafetyResult(
            reply=(
                "그 이야기가 떠오르셨구나. "
                "소중한 이야기 들려줘서 고마워, 기억나는 모습을 하나만 더 들려줄래?"
            ),
            flags=flags,
            rewritten=True,
            certainty="unverified",
            used_memory_ids=[],
        )

    # --- 2. 인용 없이 verified 를 주장하는지 ----------------------------
    if certainty == "verified" and not cited and not schedules:
        flags.append({
            "code": "UNGROUNDED_CERTAINTY",
            "reason": "근거 인용 없이 확정된 사실로 말함",
            "action": "corrected",
        })
        certainty = "unverified"

    # 복약 여부를 기억하지 못하는 상황에서는 일반적인 "약 드셔"조차 위험하다.
    # 약통의 열린 칸만 보고 실제 복용 여부를 확정할 수도 없다.
    medication_unclear = re.search(
        r"약[^.!?]{0,18}(먹었나|먹었는지|안 먹었|모르|기억이 안|헷갈)",
        user_text,
    )
    medication_instruction = re.search(
        r"(약[^.!?]{0,10})?(지금|바로)?[^.!?]{0,6}"
        r"(드셔|드시|먹어|복용해)(?!지\s*(말|마|않))",
        reply,
    )
    if medication_unclear and medication_instruction:
        flags.append({
            "code": "UNCERTAIN_MEDICATION_INSTRUCTION",
            "reason": "복약 여부가 불확실한데 복용을 지시함",
            "action": BLOCK,
        })
        return SafetyResult(
            reply="지금은 약을 더 드시지 말고 잠깐 기다려줘. 내가 확인해볼게.",
            flags=flags,
            rewritten=True,
            certainty="none",
            used_memory_ids=[],
        )

    # 장소를 알아보지 못하거나 길을 잃었다는 원문이 있는데 응답이 '거기가 집'
    # 같은 형태로 위치를 가리키면, 어미가 무엇이든 센서 없는 현재 위치 단정이다.
    place_unclear = re.search(
        r"여기가 어디|집에 가야|길을 못 찾|집이 아닌 것 같|집 안[^.!?]{0,16}낯설",
        user_text,
    )
    points_to_home = re.search(
        r"(여기|거기)(?:는|가)?[^.!?]{0,50}(집|댁|안방|거실)",
        reply,
    )
    if place_unclear and points_to_home:
        flags.append({
            "code": "PRESENT_LOCATION_CLAIM",
            "reason": "장소 혼동 상황에서 센서 확인 없이 현재 위치를 집으로 가리킴",
            "action": BLOCK,
        })
        return SafetyResult(
            reply=LOCATION_SAFE_REPLY,
            flags=flags,
            rewritten=True,
            certainty="none",
            used_memory_ids=[],
        )

    financial_accusation = re.search(
        r"(통장|계좌|돈|재산)[^.!?]{0,30}(가져|훔|빼돌|속이|몰래)|"
        r"(가져|훔|빼돌|속이|몰래)[^.!?]{0,30}(통장|계좌|돈|재산)",
        user_text,
    )
    financial_boundary = any(
        phrase in reply
        for phrase in ("확인할 수 없", "직접 확인", "확인해볼", "남길게")
    )
    if financial_accusation and not financial_boundary:
        unsafe_financial_status = re.search(
            r"(통장|계좌|돈|재산)[^.!?]{0,14}(안전|잘 보관|그대로 있|문제없)|"
            r"(아무도|내가|가족이)[^.!?]{0,12}(안 가져|훔치지 않|빼돌리지 않)",
            reply,
        )
        flags.append({
            "code": (
                "UNVERIFIED_FINANCIAL_STATUS"
                if unsafe_financial_status
                else "FINANCIAL_UNCERTAINTY_RESTORED"
            ),
            "reason": "재산 의심에 사실 여부를 단정하지 않는 확인 경계가 빠짐",
            "action": BLOCK,
        })
        return SafetyResult(
            reply=(
                "돈이 없어질까 봐 많이 걱정됐구나. "
                "지금 통장 상태는 확인할 수 없으니 가족이 직접 확인할 수 있게 남길게."
            ),
            flags=flags,
            rewritten=True,
            certainty="none",
            used_memory_ids=[],
        )

    family_feeling_claim = re.search(
        r"[가-힣]{2,4}(?:이도|도|이가|는)[^.!?]{0,18}"
        r"(많이 생각하고 있을|보고 싶어할|걱정하고 있을)",
        reply,
    )
    if family_feeling_claim:
        flags.append({
            "code": "UNVERIFIED_FAMILY_FEELING",
            "reason": "확인되지 않은 다른 가족의 감정을 대신 단정함",
            "action": BLOCK,
        })
        return SafetyResult(
            reply=(
                "그 이름이 자꾸 생각나셨구나. "
                "그 말씀은 가족에게 그대로 전할 수 있게 남길게."
            ),
            flags=flags,
            rewritten=True,
            certainty="none",
            used_memory_ids=[],
        )

    # 위험 기록과 실제 전화 실행은 다르다. 현재 서버에는 외부 연락 실행기가 없다.
    direct_risk = _direct_risk(user_text)
    guardian_contact_promise = re.search(
        r"(지금|바로)[^.!?]{0,12}(아빠|엄마|가족|보호자)[^.!?]{0,12}"
        r"(전화|연락)(해서|할게|해둘|드릴)",
        reply,
    )
    if direct_risk and guardian_contact_promise:
        flags.append({
            "code": "UNPERFORMED_GUARDIAN_CONTACT",
            "reason": "실행되지 않은 보호자 전화·연락을 수행한다고 말함",
            "action": BLOCK,
        })
        return SafetyResult(
            reply=(
                "가족에게 바로 확인이 필요하다고 남길게. "
                "지금은 무리해서 움직이지 말고 상태를 한 가지만 더 말해줘."
            ),
            flags=flags,
            rewritten=True,
            certainty="none",
            used_memory_ids=[],
        )

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
    known_memory_ids = {
        str(row.get("memory_id"))
        for row in ctx.get("memories", [])
        if row.get("memory_id")
    }
    has_known_memory = any(
        str(mid) in known_memory_ids for mid in (result.get("used_memory_ids") or [])
    )
    if (
        DIRECT_RECALL_PATTERN.search(user_text)
        and not has_known_memory
        and not result.get("unverified_recall")
    ):
        result["unverified_recall"] = {
            "summary": user_text[:160],
            "quote": user_text[:200],
        }
    checked = check(result, ctx, user_text)
    result["reply"] = checked.reply
    result["certainty"] = checked.certainty
    result["used_memory_ids"] = checked.used_memory_ids
    result["_safety_flags"] = checked.flags
    result["_rewritten"] = checked.rewritten
    _ensure_registered_schedule_answer(
        result, ctx, user_text, result["_safety_flags"]
    )
    observed_risk = _direct_risk(user_text)
    if observed_risk:
        reported = result.get("risk") or {}
        if reported.get("type") != observed_risk["type"]:
            result["risk"] = observed_risk
            result["_safety_flags"].append({
                "code": "DIRECT_RISK_RESTORED",
                "reason": "환자 원문에 직접 드러난 위험 신호를 모델이 누락하거나 다르게 분류함",
                "action": "corrected",
            })
    return result
