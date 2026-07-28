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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import llm  # noqa: E402
import safety  # noqa: E402
from persona import build_system_prompt, load_context  # noqa: E402

SCENARIOS = ROOT / "tools" / "scenarios.json"

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"


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
    return result if raw_only else safety.apply(result, ctx, user_input)


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

    return fails


# ---------------------------------------------------------------- 실행

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="실행할 시나리오 ID (없으면 전체)")
    ap.add_argument("--category", help="카테고리로 필터")
    ap.add_argument("--verbose", "-v", action="store_true", help="응답 전문 출력")
    ap.add_argument("--sleep", type=float, default=4.0,
                    help="호출 간 대기 초. 무료 티어 분당 한도 회피용 (기본 4초)")
    ap.add_argument("--raw", action="store_true",
                    help="safety 검사를 끄고 프롬프트만의 성능을 본다")
    args = ap.parse_args()

    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    if args.ids:
        scenarios = [s for s in scenarios if s["id"] in args.ids]
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]

    ctx = load_context()
    system_prompt = build_system_prompt(ctx)

    passed, failed = 0, []
    est = len(scenarios) * args.sleep / 60
    print(f"\n{len(scenarios)}개 시나리오 실행 ({llm.MODEL}) — 예상 {est:.1f}분\n" + "=" * 70)

    for i, s in enumerate(scenarios):
        if i:
            time.sleep(args.sleep)
        result = call_model(system_prompt, s.get("history", []), s["input"],
                            ctx, raw_only=args.raw)

        if "_error" in result:
            failed.append((s, [result["_error"][:120]], result))
            print(f"{RED}FAIL{RESET} {s['id']} {s['name']} — {result['_error'][:120]}")
            continue

        fails = check(result, s["assert"])
        reply = (result.get("reply") or "").replace("\n", " ")
        flags = [f["code"] for f in result.get("_safety_flags") or []]
        tag = f" {YELLOW}[safety: {','.join(flags)}]{RESET}" if flags else ""

        if not fails:
            passed += 1
            print(f"{GREEN}PASS{RESET} {s['id']} {s['name']}{tag}")
            print(f"     {DIM}→ {reply}{RESET}")
        else:
            failed.append((s, fails, result))
            print(f"{RED}FAIL{RESET} {s['id']} {s['name']}{tag}")
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

    if failed:
        print("실패 목록:")
        for s, fails, _ in failed:
            print(f"  {s['id']} [{s['category']}] {s['name']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
