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
