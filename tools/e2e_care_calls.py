r"""대표 케어 통화 3종을 실제 API 세션으로 끝까지 검증한다.

실제 Gemini 응답, 서버 안전검사, DB 발화 저장, 통화 종료, 상세 리포트와
마음 리포트 생성을 확인한다. 브라우저 마이크·TTS 재생은 별도 수동 점검 대상이다.

    .\.venv\Scripts\python.exe tools\e2e_care_calls.py
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import seed_care_demo  # noqa: E402


CASES = [
    {
        "name": "위치 혼동",
        "persona_id": "persona_miyeong",
        "persona_name": "미영",
        "text": "여기가 어디냐? 집에 가야 하는데 길을 못 찾겠다. 주변이 낯설다.",
        "signals": {"place_confusion"},
        "risk": "lost",
    },
    {
        "name": "외로움 뒤 낙상",
        "persona_id": "persona_miyeong",
        "persona_name": "미영",
        "text": "혼자 있으니까 무섭고 외롭다. 화장실에서 넘어져서 허리가 아프고 일어나기 힘들다.",
        "signals": {"fear", "loneliness"},
        "risk": "fall",
    },
    {
        "name": "고향 회상",
        "persona_id": "persona_jeonghun",
        "persona_name": "정훈",
        "text": "옛날에 살던 고향 집 앞 냇가가 생각난다. 그때가 참 좋았고 다시 가자는 말도 고맙구나.",
        "signals": {"longing", "gratitude"},
        "meaning": {"longing", "life_story"},
    },
]


def main() -> None:
    seed_care_demo.seed("elder_001")
    client = TestClient(api.app)
    failures = []

    for case in CASES:
        started = client.post("/api/calls", json={
            "elder_id": "elder_001", "persona_id": case["persona_id"],
        })
        if started.status_code != 200:
            failures.append(f"{case['name']}: 통화 시작 실패 {started.text}")
            continue
        start_data = started.json()
        call_id = start_data["call_id"]
        turn = client.post(f"/api/calls/{call_id}/turn", json={"text": case["text"]})
        if turn.status_code != 200:
            failures.append(f"{case['name']}: 발화 처리 실패 {turn.text}")
            continue
        turn_data = turn.json()
        client.post(f"/api/calls/{call_id}/end", json={"reason": "e2e_verified"})
        report_response = client.get(f"/api/calls/{call_id}/report")
        if report_response.status_code != 200:
            failures.append(f"{case['name']}: 리포트 실패 {report_response.text}")
            continue
        report_data = report_response.json()

        actual_signals = {
            item.get("signal")
            for values in (report_data.get("care_summary") or {}).values()
            for item in values
        }
        missing = case["signals"] - actual_signals
        if missing:
            failures.append(f"{case['name']}: 관찰 누락 {sorted(missing)}")
        actual_risks = {item.get("type") for item in report_data.get("risk_summary") or []}
        if case.get("risk") and case["risk"] not in actual_risks:
            failures.append(f"{case['name']}: 위험 {case['risk']} 누락")
        actual_meaning = {item.get("category") for item in report_data.get("meaningful_moments") or []}
        if case.get("meaning") and not case["meaning"].issubset(actual_meaning):
            failures.append(f"{case['name']}: 마음 기록 누락 {sorted(case['meaning'] - actual_meaning)}")
        if report_data.get("call_meta", {}).get("counterpart_name") != case["persona_name"]:
            failures.append(f"{case['name']}: 통화 가족 이름 불일치")
        if not report_data.get("heart_report", {}).get("day_translation"):
            failures.append(f"{case['name']}: 마음 리포트 누락")

        print(
            f"PASS {case['name']} · {case['persona_name']} · "
            f"관찰 {len(actual_signals)} · 위험 {len(actual_risks)} · "
            f"마음 {len(actual_meaning)} · call_id={call_id}"
        )

    if failures:
        print("\n".join(f"FAIL {failure}" for failure in failures))
        raise SystemExit(1)
    print("\n대표 실제 API 통화 3/3 통과")


if __name__ == "__main__":
    main()
