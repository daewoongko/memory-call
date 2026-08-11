"""
안전 레이어 자동 평가.

    python tools/eval.py                # 전체 실행
    python tools/eval.py S03 S07        # 특정 시나리오만
    python tools/eval.py --category risk
    python tools/eval.py --sleep 6      # 무료 티어 한도에 걸리면 간격을 늘린다

이 스크립트가 D4의 핵심이다. 프롬프트를 고칠 때마다 돌려서
'전에 통과하던 게 깨지지 않았는지'를 확인한다.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# 한국어 콘솔(cp949)에서는 이 스크립트가 첫 줄부터 UnicodeEncodeError 로 죽는다.
# 프롬프트를 고칠 때마다 돌려야 하는 도구가 터미널 종류에 따라 안 돌면 안 된다.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import care  # noqa: E402
import llm  # noqa: E402
import safety  # noqa: E402
from persona import build_system_prompt, load_context  # noqa: E402

SCENARIOS = ROOT / "tools" / "scenarios.json"

# 아래 칸이 무너지면 위 칸의 통과율은 의미가 없다. 일반 대화에서 페르소나가
# 깨지는 모델은 안전 시나리오만 잘 넘긴 것이다.
TIER_NAMES = {
    0: "일반 대화",
    1: "지남력",
    2: "등록된 사실",
    3: "안전 경계",
}

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"


# ---------------------------------------------------------------- 고정 컨텍스트

# 시나리오는 "다가오는 주말 방문" 같은 상대 시점을 가정하는데, load_context()
# 는 지난 일정을 걸러낸다. 시드 날짜가 지나면 프롬프트에서 일정이 통째로
# 사라지고, 회귀가 아닌 이유로 테스트가 빨개진다. 회귀 테스트가 벽시계에
# 흔들리면 신호로 쓸 수 없다.
#
# 그래서 날짜에 의존하는 부분만 상대 시점으로 다시 만든다. DB 는 건드리지
# 않고 컨텍스트 사본만 바꾼다. safety 는 일정 ID 를 ctx 에서 확인하므로
# (safety.py 의 valid_schedules) 이것으로 충분하다.
#
# 방문을 "다음 토요일" 로 두는 이유는 요일 이름이 언제 돌려도 불변이기
# 때문이다. 날짜는 매주 바뀌지만 "토요일" 은 바뀌지 않으므로 시나리오가
# 날짜를 하드코딩하지 않아도 된다. demo_reset.py 와 같은 규칙이라 시연
# 상태와도 어긋나지 않는다.

FIXTURE_VISIT_ID = "sch_visit"
FIXTURE_MED_ID = "med_evening"
FIXTURE_VISIT_WEEKDAY = "토요일"

# 현재 시각도 고정한다. 일정만 고정하면 방문이 실행 요일에 따라 "내일" 이
# 되기도 하고 "6일 뒤" 가 되기도 해서, 약속을 얼마나 쉽게 할 수 있는지가
# 매번 달라진다. 거짓 약속 회귀를 가릴 수 있는 흔들림이다.
#
# 수요일 오전으로 둔 이유는 다음 토요일이 3일 뒤라 모델이 "내일"·"모레"
# 같은 지름길을 못 쓰고 요일 이름을 써야 하기 때문이다. 복약 19:00 도
# 아직 오지 않은 시각이라 "약 먹었어?" 대화가 자연스럽다.
FIXTURE_NOW = datetime(2026, 5, 13, 10, 30)
FIXTURE_PERSONA = {
    "persona_id": "persona_daewoong", "display_name": "대웅",
    "relationship_type": "손자", "elder_calls_family": "우리 대웅이",
    "family_calls_elder": "할아버지",
    "tone": "따뜻하고 편안한 반말. 서두르지 않고 천천히.",
    "frequent_phrases": ["할아버지, 천천히 말씀해줘."],
    "forbidden_phrases": ["왜 또 물어봐?", "아까 말했잖아."],
    "sensitive_policy": "감정을 먼저 인정하되 확인되지 않은 사실은 단정하지 않는다.",
}
CARE_PERSONA_FIXTURES = {
    "S30": ("미영", "딸"), "S31": ("정훈", "아들"),
    "S32": ("미영", "딸"), "S33": ("정훈", "아들"),
    "S34": ("미영", "딸"), "S35": ("정훈", "아들"),
    "S36": ("정훈", "아들"), "S37": ("정훈", "아들"),
}


def next_saturday(today: date) -> date:
    """오늘이 토요일이면 다음 주 토요일. demo_reset.py 와 같은 계산."""
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def pin_context_dates(ctx: dict, today: date | None = None) -> dict:
    """일정·복약을 상대 시점으로 고정한 사본. 원본 ctx 는 그대로 둔다."""
    today = today or date.today()
    pinned = dict(ctx)
    # DB의 현재 활성 가족이 누구인지와 무관하게 일반 회귀 시나리오는 대웅으로 고정한다.
    pinned["persona"] = dict(FIXTURE_PERSONA)
    pinned["schedules"] = [{
        "schedule_id": FIXTURE_VISIT_ID,
        "title": "대웅이 방문",
        "date": next_saturday(today).isoformat(),
        "time": "14:00",
        "note": "주말 오후에 할아버지 댁 방문 예정",
        "confirmed": 1,
    }]
    pinned["medications"] = [{
        "schedule_id": FIXTURE_MED_ID,
        "medication_name": "저녁 혈압약",
        "dosage_text": "1정",
        "scheduled_time": "19:00",
        "meal_relation": "after",
        "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
        "active": 1,
    }]
    return pinned


def scenario_context(ctx: dict, scenario_id: str) -> dict:
    """케어 시나리오는 제공된 가족 이름·관계로 평가한다."""
    fixture = CARE_PERSONA_FIXTURES.get(scenario_id)
    if not fixture:
        return ctx
    name, relation = fixture
    out = dict(ctx)
    out["persona"] = dict(
        ctx["persona"],
        persona_id=f"persona_{name}",
        display_name=name,
        relationship_type=relation,
        elder_calls_family=f"우리 {name}이",
        family_calls_elder="아버지",
    )
    return out


# ---------------------------------------------------------------- 모델 호출

def call_model(system_prompt: str, history: list[dict], user_input: str,
               ctx: dict, raw_only: bool = False) -> dict:
    """모델 호출 후 safety 검사까지 통과시킨다.

    검사 대상은 사용자가 실제로 듣게 될 문장이어야 하므로 기본값은 검사 적용이다.
    --raw 로 끄면 프롬프트만의 성능을 볼 수 있다.
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_input})
    try:
        result = llm.call_json(messages)
    except llm.QuotaExceeded as e:
        return {"_quota": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}
    if raw_only:
        return result
    result = safety.apply(result, ctx, user_input)
    result["care"] = care.normalize(
        result.get("care"),
        user_text=user_input,
        ctx=ctx,
        due_medications=[],
        response_rewritten=bool(result.get("_rewritten")),
    )
    return result


# ---------------------------------------------------------------- 검사기

def check(result: dict, rules: dict) -> list[str]:
    """실패한 규칙 목록을 반환한다. 빈 리스트면 통과."""
    fails = []
    reply = result.get("reply", "") or ""

    for pattern in rules.get("reply_must_not_match", []):
        if re.search(pattern, reply):
            fails.append(f"금지 표현 매칭: /{pattern}/")

    if "reply_must_match_any" in rules:
        pats = rules["reply_must_match_any"]
        if not any(re.search(p, reply) for p in pats):
            fails.append(f"필수 표현 없음: {pats} 중 하나 필요")

    # 프롬프트는 "2문장 이내"를 요구하는데 지금까지 아무도 확인하지 않았다.
    # 개인 정보가 없는 질문일수록 모델이 백과사전처럼 길어진다.
    limit = rules.get("reply_max_chars")
    if limit and len(reply) > limit:
        fails.append(f"응답이 김: {len(reply)}자 (최대 {limit}자)")

    for field, expected in rules.get("field_equals", {}).items():
        if result.get(field) != expected:
            fails.append(f"{field} = {result.get(field)!r} (기대: {expected!r})")

    for field in rules.get("field_not_null", []):
        if result.get(field) in (None, "", [], {}):
            fails.append(f"{field}가 비어 있음 (채워져야 함)")

    for field in rules.get("field_null", []):
        if result.get(field) not in (None, "", [], {}):
            fails.append(f"{field}가 채워져 있음 (비어야 함)")

    for field in rules.get("field_not_empty", []):
        if not result.get(field):
            fails.append(f"{field}가 비어 있음")

    if "certainty_in" in rules:
        if result.get("certainty") not in rules["certainty_in"]:
            fails.append(
                f"certainty = {result.get('certainty')!r} "
                f"(허용: {rules['certainty_in']})"
            )

    ids = result.get("used_memory_ids") or []
    for mid in rules.get("memory_ids_must_include", []):
        if mid not in ids:
            fails.append(f"기억 {mid} 인용 안 됨 (인용: {ids})")
    for mid in rules.get("memory_ids_must_not_include", []):
        if mid in ids:
            fails.append(f"금지 기억 {mid} 인용됨")
    if rules.get("memory_ids_must_be_empty") and ids:
        fails.append(f"기억을 인용하면 안 되는데 인용함: {ids}")

    risk = result.get("risk") or {}
    if "risk_type_in" in rules:
        if risk.get("type") not in rules["risk_type_in"]:
            fails.append(
                f"risk.type = {risk.get('type')!r} (허용: {rules['risk_type_in']})"
            )
    if "risk_level_in" in rules:
        if risk.get("level") not in rules["risk_level_in"]:
            fails.append(
                f"risk.level = {risk.get('level')!r} (허용: {rules['risk_level_in']})"
            )

    med = result.get("medication_status") or {}
    if "medication_status_in" in rules:
        if med.get("status") not in rules["medication_status_in"]:
            fails.append(
                f"medication_status = {med.get('status')!r} "
                f"(허용: {rules['medication_status_in']})"
            )

    care_data = result.get("care") or {}
    care_signals = {
        item.get("signal")
        for item in (care_data.get("observations") or [])
        if item.get("signal")
    }
    for signal in rules.get("care_signals_must_include", []):
        if signal not in care_signals:
            fails.append(
                f"care 신호 {signal!r} 없음 (관찰: {sorted(care_signals)})"
            )
    for signal in rules.get("care_signals_must_not_include", []):
        if signal in care_signals:
            fails.append(f"금지 care 신호 {signal!r} 포함")

    meaning_categories = {
        item.get("category")
        for item in (care_data.get("meaningful_moments") or [])
        if item.get("category")
    }
    for category in rules.get("meaning_categories_must_include", []):
        if category not in meaning_categories:
            fails.append(
                f"마음 기록 {category!r} 없음 "
                f"(기록: {sorted(meaning_categories)})"
            )

    return fails


# ---------------------------------------------------------------- 실행

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="실행할 시나리오 ID (없으면 전체)")
    ap.add_argument("--category", help="카테고리로 필터")
    ap.add_argument("--tier", type=int, action="append",
                    help="난이도 단계로 필터. 여러 번 줄 수 있다. "
                         "0 일반 대화 / 1 지남력 / 2 등록된 사실 / 3 안전 경계")
    ap.add_argument("--max-tier", type=int,
                    help="이 단계까지만 실행. 사다리를 아래부터 올릴 때 쓴다")
    ap.add_argument("--verbose", "-v", action="store_true", help="응답 전문 출력")
    ap.add_argument("--sleep", type=float, default=4.0,
                    help="호출 간 대기 초. 무료 티어 분당 한도 회피용 (기본 4초)")
    ap.add_argument("--raw", action="store_true",
                    help="safety 검사를 끄고 프롬프트만의 성능을 본다")
    ap.add_argument("--live-context", action="store_true",
                    help="일정 고정 없이 실제 DB 그대로 본다. "
                         "리허설 직전 시연 DB 점검용")
    args = ap.parse_args()

    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    if args.ids:
        scenarios = [s for s in scenarios if s["id"] in args.ids]
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]
    if args.tier is not None:
        scenarios = [s for s in scenarios if s.get("tier") in args.tier]
    if args.max_tier is not None:
        scenarios = [s for s in scenarios if s.get("tier", 0) <= args.max_tier]
    scenarios.sort(key=lambda s: (s.get("tier", 0), s["id"]))

    ctx = load_context()
    now = None
    if not args.live_context:
        ctx = pin_context_dates(ctx, FIXTURE_NOW.date())
        now = FIXTURE_NOW
    passed, failed = 0, []
    est = len(scenarios) * args.sleep / 60
    context_mode = (
        "실제 DB·실제 시각 (--live-context)" if args.live_context
        else f"고정 — {FIXTURE_NOW:%Y-%m-%d %H:%M} 기준, "
             f"방문 = 다음 {FIXTURE_VISIT_WEEKDAY}"
    )
    print(f"\n{len(scenarios)}개 시나리오 실행 ({llm.MODEL}) — 예상 {est:.1f}분")
    print(f"{DIM}컨텍스트: {context_mode}{RESET}\n" + "=" * 70)

    for i, s in enumerate(scenarios):
        if i:
            time.sleep(args.sleep)
        active_ctx = scenario_context(ctx, s["id"])
        system_prompt = build_system_prompt(active_ctx, now=now)
        result = call_model(system_prompt, s.get("history", []), s["input"],
                            active_ctx, raw_only=args.raw)

        if "_error" in result:
            failed.append((s, [result["_error"][:120]], result))
            print(f"{RED}FAIL{RESET} {s['id']} {s['name']} — {result['_error'][:120]}")
            continue

        fails = check(result, s["assert"])
        reply = (result.get("reply") or "").replace("\n", " ")
        flags = [f["code"] for f in result.get("_safety_flags") or []]
        tag = f" {YELLOW}[safety: {','.join(flags)}]{RESET}" if flags else ""

        tier = f"{DIM}[T{s.get('tier', 0)}]{RESET} "
        if not fails:
            passed += 1
            print(f"{GREEN}PASS{RESET} {tier}{s['id']} {s['name']}{tag}")
            print(f"     {DIM}→ {reply}{RESET}")
        else:
            failed.append((s, fails, result))
            print(f"{RED}FAIL{RESET} {tier}{s['id']} {s['name']}{tag}")
            print(f"     → {reply}")
            for f in fails:
                print(f"     {RED}✗ {f}{RESET}")
            print(f"     {DIM}근거: {result.get('grounding')}{RESET}")

        if args.verbose:
            print(f"     {DIM}{json.dumps(result, ensure_ascii=False)}{RESET}")

    total = len(scenarios)
    print("=" * 70)
    mode = "프롬프트만" if args.raw else "프롬프트 + safety"
    print(f"{DIM}검사 모드: {mode}{RESET}")
    rate = passed / total * 100 if total else 0
    color = GREEN if rate == 100 else (YELLOW if rate >= 80 else RED)
    print(f"{color}{passed}/{total} 통과 ({rate:.0f}%){RESET}\n")

    # 단계별 통과율. 사다리를 아래부터 올리려면 어느 칸이 비었는지 보여야 한다.
    by_tier: dict[int, list[bool]] = {}
    failed_ids = {s["id"] for s, _, _ in failed}
    for s in scenarios:
        by_tier.setdefault(s.get("tier", 0), []).append(s["id"] not in failed_ids)
    for tier in sorted(by_tier):
        results = by_tier[tier]
        ok = sum(results)
        mark = GREEN if ok == len(results) else RED
        print(f"{DIM}  T{tier} {TIER_NAMES.get(tier, '')}{RESET} "
              f"{mark}{ok}/{len(results)}{RESET}")

    if failed:
        print("\n실패 목록:")
        for s, fails, _ in failed:
            print(f"  [T{s.get('tier', 0)}] {s['id']} [{s['category']}] {s['name']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
