"""
터미널 통화 테스트. 이제 통화 세션이 DB에 기록된다.

    python tools/chat.py

/prompt  현재 시스템 프롬프트
/raw     마지막 응답 JSON 전문
/log     이번 통화의 발화 기록
/q       통화 종료 (요약 출력)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import llm  # noqa: E402
from conversation import Session  # noqa: E402

DIM, CYAN, YELLOW, RESET = "\033[2m", "\033[96m", "\033[93m", "\033[0m"

session = Session()
last_raw: dict = {}

print(f"{DIM}통화 시작 ({llm.MODEL}) — call_id={session.call_id}")
print(f"할아버지: {session.ctx['elder']['name']} / "
      f"페르소나: {session.ctx['persona']['display_name']}")
print(f"기억 {len(session.ctx['memories'])}개 · "
      f"일정 {len(session.ctx['schedules'])}건 · "
      f"복약 {len(session.ctx['medications'])}건 — /q 로 종료{RESET}\n")

while True:
    try:
        user = input("할아버지 > ").strip()
    except (EOFError, KeyboardInterrupt):
        user = "/q"

    if not user:
        continue
    if user == "/q":
        break
    if user == "/prompt":
        print(session.system_prompt)
        continue
    if user == "/raw":
        print(json.dumps(last_raw, ensure_ascii=False, indent=2))
        continue
    if user == "/log":
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, speaker, transcript, intent, latency_ms "
                "FROM utterances WHERE call_id = ? ORDER BY seq",
                (session.call_id,),
            ).fetchall()
        for r in rows:
            who = "할아버지" if r["speaker"] == "elder" else "대웅  "
            ms = f" {r['latency_ms']}ms" if r["latency_ms"] else ""
            print(f"{DIM}{r['seq']:>3} {who} | {r['transcript']}{ms}{RESET}")
        continue

    try:
        last_raw = session.turn(user)
    except Exception as e:  # noqa: BLE001
        print(f"오류: {e}\n")
        continue

    print(f"{CYAN}대웅   > {last_raw.get('reply', '')}{RESET}")

    tags = []
    if last_raw.get("intent"):
        tags.append(last_raw["intent"])
    if last_raw.get("certainty") and last_raw["certainty"] != "none":
        tags.append(f"근거:{last_raw['certainty']}")
    if last_raw.get("used_memory_ids"):
        tags.append(",".join(last_raw["used_memory_ids"]))
    if last_raw.get("used_schedule_ids"):
        tags.append("일정:" + ",".join(last_raw["used_schedule_ids"]))
    if last_raw.get("risk"):
        tags.append(f"[!] {last_raw['risk'].get('type')}")
    if last_raw.get("medication_status"):
        tags.append(f"[약] {last_raw['medication_status'].get('status')}")
    if last_raw.get("unverified_recall"):
        tags.append("[?] 미확인회상")

    ms = last_raw.get("_latency_ms", 0)
    slow = YELLOW if ms > 2000 else DIM
    print(f"{DIM}         [{' | '.join(tags)}]{RESET} {slow}{ms}ms{RESET}\n")

summary = session.end()
print(f"\n{DIM}── 통화 종료 ──")
print(f"call_id       {summary['call_id']}")
print(f"통화 시간      {summary['duration_sec']}초")
print(f"AI 응답        {summary['ai_turns']}회")
print(f"평균 응답 지연  {summary['avg_latency_ms']}ms")
print(f"위험 이벤트    {summary['risk_events']}건{RESET}")
