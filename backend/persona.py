"""
페르소나 시스템 프롬프트 조립.

persona_system.md 템플릿의 {{PLACEHOLDER}}를 seed.json 데이터로 채운다.
D1에서는 seed.json을 직접 읽고, D2부터는 SQLite에서 읽도록 load_context()만 교체하면 된다.
"""

from datetime import date, datetime
from pathlib import Path

from db import load_context  # noqa: F401  (chat.py / eval.py 가 여기서 가져다 씀)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "backend" / "prompts" / "persona_system.md"


def _memory_block(memories: list[dict]) -> str:
    """기억 목록을 프롬프트용 텍스트로.

    prohibited 기억도 포함시킨다. AI가 '말하면 안 되는 것'을 알아야
    할아버지가 언급했을 때 정책대로 대응할 수 있기 때문이다.
    (대신 note 필드로 취급 방법을 명시)
    """
    lines = []
    for m in memories:
        if not m.get("conversation_allowed") and m.get("status") != "prohibited":
            continue
        line = (
            f"- id: {m['memory_id']} | status: {m['status']}\n"
            f"  제목: {m['title']}\n"
            f"  내용: {m['description']}\n"
            f"  시기: {m['date_text']} | 장소: {m['location']} | "
            f"인물: {', '.join(m['participants'])}"
        )
        if m.get("note"):
            line += f"\n  ※ 취급: {m['note']}"
        lines.append(line)
    return "\n".join(lines)


_WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")

NO_SCHEDULE = "(등록된 일정 없음. 일정에 관한 어떤 약속도 하지 말 것.)"


def _weekday_ko(d: date) -> str:
    """요일은 서버가 정한다.

    strftime("%A") 는 로케일에 따라 "Thursday" 가 나가고, 그러면 모델이
    한국어로 옮기는 단계가 하나 늘어난다. 요일은 날짜에서 규칙으로 나오는
    값이라 모델에게 계산시킬 이유가 없다.
    """
    return _WEEKDAY_KO[d.weekday()] + "요일"


def _relative_day(target: date, today: date) -> str:
    """며칠 뒤인지 말로 바꾼다. 모델이 날짜를 세지 않게 한다."""
    diff = (target - today).days
    fixed = {0: "오늘", 1: "내일", 2: "모레", -1: "어제", -2: "그저께"}
    if diff in fixed:
        return fixed[diff]
    return f"{diff}일 뒤" if diff > 0 else f"{-diff}일 전"


def _schedule_block(schedules: list[dict], today: date | None = None) -> str:
    """일정을 프롬프트 줄로 만든다.

    요일과 "모레" 같은 상대 표현을 서버가 붙여서 넘긴다. 이게 없으면 모델이
    note 의 자유 문장에 적힌 요일을 그대로 읽는데, 그 문장이 날짜와 어긋나
    있으면 어긋난 요일이 그대로 약속이 된다. 할아버지가 엉뚱한 날 기다리는
    것은 없는 약속을 만드는 것과 같은 사고다.
    """
    today = today or date.today()
    lines = []
    for s in schedules or []:
        if not s.get("confirmed"):
            continue
        try:
            d = date.fromisoformat(s["date"])
        except (KeyError, TypeError, ValueError):
            # 날짜를 못 읽으면 요일을 지어내지 않는다. 있는 값만 넘긴다.
            lines.append(
                f"- id: {s['schedule_id']} | {s.get('date')} {s['time']} | "
                f"{s['title']} | {s['note']}"
            )
            continue
        lines.append(
            f"- id: {s['schedule_id']} | {s['date']} "
            f"{_weekday_ko(d)} ({_relative_day(d, today)}) {s['time']} | "
            f"{s['title']} | {s['note']}"
        )
    # confirmed 가 하나도 없으면 빈 문자열이 아니라 경고를 넣는다. 빈칸은
    # 모델에게 아무 지시도 하지 않는 것이라 약속을 지어낼 여지를 남긴다.
    return "\n".join(lines) or NO_SCHEDULE


def _medication_block(meds: list[dict]) -> str:
    if not meds:
        return "(등록된 복약 없음)"
    rel = {"after": "식후", "before": "식전", "none": ""}
    return "\n".join(
        f"- id: {m['schedule_id']} | {m['scheduled_time']} | "
        f"{m['medication_name']} {m['dosage_text']} {rel.get(m['meal_relation'], '')}"
        for m in meds
        if m.get("active")
    )


def _residence_line(e: dict) -> str:
    """평소 거주 사실만 넣는다.

    통화 시점에 어디 있는지는 시스템이 알 수 없다. "평소 지내는 곳"이라는
    이름 자체로 현재 위치와 구분해 두어야 모델이 지금 거기 있다고 단정하지
    않는다. 등록이 없으면 비워 두지 않고 "미등록"이라고 적는다. 빼 버리면
    모델이 지어낸다.
    """
    kind = str(e.get("residence_type") or "").strip()
    members = e.get("household_members") or []
    names = [
        f"{m.get('name')}({m.get('relation')})"
        for m in members
        if isinstance(m, dict) and m.get("name")
    ]
    return (
        f"평소 지내는 곳: {kind or '미등록'}\n"
        f"평소 함께 사는 사람: {', '.join(names) if names else '미등록'}"
    )


def _elder_block(e: dict) -> str:
    return (
        f"이름: {e['name']}\n"
        f"부르는 호칭: {e['preferred_call_name']}\n"
        f"{_residence_line(e)}\n"
        f"불안을 느끼는 상황: {', '.join(e['anxiety_triggers'])}\n"
        f"안정에 도움이 되는 표현: {' / '.join(e['calming_phrases'])}\n"
        f"자주 반복하는 질문: {' / '.join(e['frequent_questions'])}\n"
        f"청각 지원 필요: {'예 (짧고 또박또박)' if e['hearing_support'] else '아니오'}"
    )


def _persona_block(p: dict) -> str:
    style = ""
    if p.get("call_style_code"):
        style = f"\n통화 성향: {p['call_style_code']} · {p.get('call_style_name') or '이름 미등록'}"
    return (
        f"이름: {p['display_name']} ({p['relationship_type']})\n"
        f"할아버지가 부르는 호칭: {p['elder_calls_family']}\n"
        f"말투: {p['tone']}"
        f"{style}"
    )


def _search_grams(text: str) -> set[str]:
    """Return simple language-agnostic character grams for live memory lookup."""
    compact = "".join(ch.lower() for ch in str(text or "") if ch.isalnum())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _relevant_memories(memories: list[dict], user_text: str,
                       limit: int = 4) -> list[dict]:
    """Select only memories that overlap the current utterance.

    The full report prompt still receives every memory.  The live path keeps
    the prompt small so a greeting does not pay the latency cost of all stored
    history, and it asks for clarification when no registered fact matches.
    """
    query = _search_grams(user_text)
    if not query:
        return []
    ranked: list[tuple[int, int, dict]] = []
    for index, memory in enumerate(memories or []):
        searchable = " ".join([
            str(memory.get("title") or ""),
            str(memory.get("description") or ""),
            str(memory.get("date_text") or ""),
            str(memory.get("location") or ""),
            " ".join(str(value) for value in memory.get("participants") or []),
        ])
        score = len(query & _search_grams(searchable))
        if score:
            ranked.append((score, -index, memory))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


def build_fast_system_prompt(ctx: dict, user_text: str,
                             now: datetime | None = None) -> str:
    """Compact, safety-preserving prompt for the latency-sensitive voice turn."""
    now = now or datetime.now()
    p, e = ctx["persona"], ctx["elder"]
    memories = _relevant_memories(ctx.get("memories") or [], user_text)
    memory_text = _memory_block(memories) if memories else "(이번 말과 직접 관련된 등록 기억 없음)"
    schedule_text = _schedule_block(ctx.get("schedules") or [], now.date())
    medication_text = _medication_block(ctx.get("medications") or [])
    current_time = (
        f"{now.strftime('%Y년 %m월 %d일')} "
        f"{_weekday_ko(now.date())} {now.strftime('%H:%M')}"
    )

    return f"""# 역할과 말투
너는 {p['display_name']}({p['relationship_type']})이고, 지금 {e['name']}({p['family_calls_elder']})과 영상통화 중이다.
상대는 치매로 질문을 반복하거나 시간·장소·사람을 혼동할 수 있다.
호칭은 {p['family_calls_elder']}. 항상 반말로, {p['tone']}
답은 자연스러운 한국어 1~2개의 짧은 문장, 보통 90자 이내로 말한다. 질문은 한 번에 하나만 한다.
자주 쓰는 표현: {' / '.join(p.get('frequent_phrases') or [])}
금지 표현: {' / '.join(p.get('forbidden_phrases') or [])}

# 반드시 지킬 안전 규칙
- 사실은 아래 등록 정보와 이번 통화에서 상대가 직접 말한 것만 쓴다. 없으면 "확인해보고 알려줄게"라고 한다.
- 등록되지 않은 방문·전화·행동을 약속하거나 현재 위치·곁에 있는 사람을 추측하지 않는다.
- verified 기억만 사실로 말하고 partial은 불확실하다고 밝힌다. 새 기억은 맞다고 확정하지 말고 더 물어본다.
- 약 용량 변경, 추가 복용, 중단, 놓친 약 재복용을 지시하지 않는다. 불확실하면 약을 더 먹지 말고 확인을 기다리라고 한다.
- 송금·계좌·카드·비밀번호·계약 요청은 수행하지 않는다. 정서적 독점이나 죄책감 유발도 하지 않는다.
- 정체성을 물으면 "{p['display_name']}이가 준비해둔 기억통화로 이야기하고 있어. {p['family_calls_elder']} 말씀은 꼭 전해줄게."라고 설명한다.
- 넘어짐·호흡곤란·가슴통증·과다복용·길 잃음·자해·침입·화재는 확인 질문 하나만 하고, 가족에게 알릴 위험 기록을 남긴다고 말하며 먼저 끊지 않는다.

# 지금 답할 때 쓸 수 있는 등록 정보
<페르소나>
{_persona_block(p)}
</페르소나>
<관련 기억>
{memory_text}
</관련 기억>
<일정>
{schedule_text}
</일정>
<복약>
{medication_text}
</복약>
<노인 정보>
{_elder_block(e)}
</노인 정보>
현재 시각: {current_time}

# 출력
JSON 객체만 출력한다:
{{"reply":"실제로 말할 짧은 답", "used_memory_ids":[], "used_schedule_ids":[], "certainty":"verified|partial|unverified|none", "risk":null, "unverified_recall":null}}
"""


def build_system_prompt(ctx: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    p, e = ctx["persona"], ctx["elder"]

    mapping = {
        "PERSONA_NAME": p["display_name"],
        "RELATIONSHIP": p["relationship_type"],
        "ELDER_NAME": e["name"],
        "ELDER_CALL_NAME": p["family_calls_elder"],
        "TONE": p["tone"],
        "FREQUENT_PHRASES": " / ".join(p["frequent_phrases"]),
        "FORBIDDEN_PHRASES": " / ".join(p["forbidden_phrases"]),
        "SENSITIVE_POLICY": p["sensitive_policy"],
        "PERSONA_BLOCK": _persona_block(p),
        "MEMORY_BLOCK": _memory_block(ctx["memories"]),
        "SCHEDULE_BLOCK": _schedule_block(ctx["schedules"], now.date()),
        "MEDICATION_BLOCK": _medication_block(ctx["medications"]),
        "ELDER_BLOCK": _elder_block(e),
        "NOW": (f"{now.strftime('%Y년 %m월 %d일')} "
                f"{_weekday_ko(now.date())} {now.strftime('%H:%M')}"),
    }

    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


if __name__ == "__main__":
    print(build_system_prompt(load_context()))
