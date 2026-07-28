"""
페르소나 시스템 프롬프트 조립.

persona_system.md 템플릿의 {{PLACEHOLDER}}를 seed.json 데이터로 채운다.
D1에서는 seed.json을 직접 읽고, D2부터는 SQLite에서 읽도록 load_context()만 교체하면 된다.
"""

from datetime import datetime
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


def _schedule_block(schedules: list[dict]) -> str:
    if not schedules:
        return "(등록된 일정 없음. 일정에 관한 어떤 약속도 하지 말 것.)"
    return "\n".join(
        f"- id: {s['schedule_id']} | {s['date']} {s['time']} | {s['title']} | {s['note']}"
        for s in schedules
        if s.get("confirmed")
    )


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


def _elder_block(e: dict) -> str:
    return (
        f"이름: {e['name']}\n"
        f"부르는 호칭: {e['preferred_call_name']}\n"
        f"불안을 느끼는 상황: {', '.join(e['anxiety_triggers'])}\n"
        f"안정에 도움이 되는 표현: {' / '.join(e['calming_phrases'])}\n"
        f"자주 반복하는 질문: {' / '.join(e['frequent_questions'])}\n"
        f"청각 지원 필요: {'예 (짧고 또박또박)' if e['hearing_support'] else '아니오'}"
    )


def _persona_block(p: dict) -> str:
    return (
        f"이름: {p['display_name']} ({p['relationship_type']})\n"
        f"할아버지가 부르는 호칭: {p['elder_calls_family']}\n"
        f"말투: {p['tone']}"
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
        "SCHEDULE_BLOCK": _schedule_block(ctx["schedules"]),
        "MEDICATION_BLOCK": _medication_block(ctx["medications"]),
        "ELDER_BLOCK": _elder_block(e),
        "NOW": now.strftime("%Y년 %m월 %d일 %A %H:%M"),
    }

    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


if __name__ == "__main__":
    print(build_system_prompt(load_context()))
