r"""8개 케어 시나리오의 통화 후 리포트를 근거 기반 기대값과 비교한다.

Gemini를 호출하지 않는다. 기본 실행은 demo_care_ 통화를 다시 적재한 뒤
관찰 영역·신호·위험·마음 기록·가족 언급·보호자 행동·직접 근거를 검사한다.

    .\.venv\Scripts\python.exe tools\eval_reports.py
    .\.venv\Scripts\python.exe tools\eval_reports.py --no-seed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import db  # noqa: E402
import report  # noqa: E402
import seed_care_demo  # noqa: E402


EXPECTATIONS = ROOT / "tools" / "report_expectations.json"


def _elder_transcript(call_id: str) -> str:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT transcript FROM utterances WHERE call_id = ? "
            "AND speaker = 'elder' ORDER BY seq",
            (call_id,),
        ).fetchall()
    return " ".join((row["transcript"] or "") for row in rows)


def validate_report(data: dict, expected: dict, elder_text: str) -> list[str]:
    """실패 이유 목록을 반환한다. 빈 목록이면 통과다."""
    failures = []
    care_summary = data.get("care_summary") or {}
    observed_domains = {key for key, values in care_summary.items() if values}
    observations = [item for values in care_summary.values() for item in (values or [])]
    signals = {item.get("signal") for item in observations}

    for domain in expected.get("domains", []):
        if domain not in observed_domains:
            failures.append(f"관찰 영역 누락: {domain}")
    for signal in expected.get("signals", []):
        if signal not in signals:
            failures.append(f"관찰 신호 누락: {signal}")

    risks = {item.get("type") for item in (data.get("risk_summary") or [])}
    expected_risks = set(expected.get("risks", []))
    if risks != expected_risks:
        failures.append(f"위험 신호 {sorted(risks)} (기대 {sorted(expected_risks)})")

    meanings = {item.get("category") for item in (data.get("meaningful_moments") or [])}
    for category in expected.get("meaning", []):
        if category not in meanings:
            failures.append(f"마음 기록 누락: {category}")

    mentions = {item.get("name"): item.get("count", 0) for item in (data.get("family_mentions") or [])}
    for name, minimum in expected.get("family_mentions", {}).items():
        if mentions.get(name, 0) < minimum:
            failures.append(f"가족 언급 {name} {mentions.get(name, 0)}회 (최소 {minimum}회)")

    heart = data.get("heart_report") or {}
    if expected.get("heart_missed_word") and not heart.get("missed_word"):
        failures.append("마음 리포트의 '놓친 한마디' 누락")
    family_word = expected.get("heart_family_contains")
    family_translation = (heart.get("day_translation") or {}).get("family", "")
    if family_word and family_word not in family_translation:
        failures.append(f"가족 관점 번역에 {family_word!r} 누락")
    memory_mode = expected.get("heart_memory_mode")
    actual_mode = (heart.get("memory_bridge") or {}).get("mode")
    if memory_mode and actual_mode != memory_mode:
        failures.append(f"기억 연결 모드 {actual_mode!r} (기대 {memory_mode!r})")

    actions = " ".join(data.get("guardian_actions") or [])
    action_words = expected.get("action_any", [])
    if action_words and not any(word in actions for word in action_words):
        failures.append(f"보호자 확인 행동 누락: {action_words} 중 하나 필요")

    evidence_words = expected.get("evidence_any", [])
    evidence = " ".join(
        str(item.get("evidence") or "")
        for item in observations
        + (data.get("risk_summary") or [])
        + (data.get("meaningful_moments") or [])
    )
    if evidence_words and not any(word in evidence for word in evidence_words):
        failures.append(f"기대 발화 근거 누락: {evidence_words} 중 하나 필요")

    for item in observations:
        quote = str(item.get("evidence") or "").strip()
        if not quote or quote not in elder_text:
            failures.append(f"원문에 없는 관찰 근거: {quote!r}")
    return failures


def evaluate(prefix: str = seed_care_demo.DEFAULT_PREFIX) -> tuple[int, int, list[str]]:
    expectations = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    passed = 0
    messages = []
    for scenario_id, expected in expectations.items():
        call_id = f"{prefix}{scenario_id.lower()}"
        data = report.build(call_id)
        failures = validate_report(data, expected, _elder_transcript(call_id))
        if failures:
            messages.append(f"FAIL {scenario_id}: " + " / ".join(failures))
        else:
            passed += 1
            messages.append(f"PASS {scenario_id}: 관찰·근거·보호자 확인 기준 충족")
    return passed, len(expectations), messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-seed", action="store_true", help="기존 demo_care_ 통화만 검사")
    args = parser.parse_args()
    if not args.no_seed:
        seed_care_demo.seed("elder_001")
    passed, total, messages = evaluate()
    print("\n".join(messages))
    print(f"\n통화 후 리포트 평가: {passed}/{total} 통과")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
