"""
API 키가 살아있는지, 어떤 모델을 쓸 수 있는지 확인한다.
설정 끝내고 제일 먼저 돌릴 것.

    python tools/check_key.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import llm  # noqa: E402

GREEN, RED, DIM, RESET = "\033[92m", "\033[91m", "\033[2m", "\033[0m"

print(f"\n{DIM}엔드포인트: {llm.BASE_URL}")
print(f"설정된 모델: {llm.MODEL}{RESET}\n")

# 1. 모델 목록
try:
    models = llm.list_models()
    print(f"{GREEN}✓{RESET} 키 인증 성공 — 사용 가능 모델 {len(models)}개")
    flash = [m for m in models if "flash" in m.lower()]
    print(f"{DIM}  Flash 계열 (무료 티어 후보):{RESET}")
    for m in flash[:15]:
        mark = " ←현재" if llm.MODEL in m else ""
        print(f"{DIM}    {m}{mark}{RESET}")
except Exception as e:  # noqa: BLE001
    print(f"{RED}✗{RESET} 모델 목록 실패: {e}")
    print("\n키가 잘못됐거나 .env가 안 읽혔을 가능성이 큽니다.")
    sys.exit(1)

# 2. 실제 호출
print(f"\n{DIM}JSON 응답 테스트 중…{RESET}")
try:
    result = llm.call_json([
        {"role": "system",
         "content": '반드시 {"greeting": "...", "ok": true} 형식 JSON만 출력하세요.'},
        {"role": "user", "content": "한국어로 짧게 인사해줘."},
    ], temperature=0.3)
    print(f"{GREEN}✓{RESET} 호출 성공 → {result}")
    print(f"\n{GREEN}준비 완료. python tools/chat.py 로 넘어가세요.{RESET}\n")
except Exception as e:  # noqa: BLE001
    print(f"{RED}✗{RESET} 호출 실패: {e}\n")
    sys.exit(1)
