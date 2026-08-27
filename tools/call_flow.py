"""
호출 흐름 확인.

브라우저 없이 "보호자가 받았는가"가 실제로 갈리는지 본다. 화면을 만들기 전에
이 스크립트가 통과해야 한다. 이전 구현은 어르신 기기 안의 타이머가 전부여서
보호자가 무엇을 하든 결과가 같았고, 그래서 눈으로는 구분되지 않았다.

    python tools/serve.py --no-reload          # 터미널 1
    python tools/call_flow.py                  # 터미널 2

    python tools/call_flow.py --case decline   # 한 가지만
    python tools/call_flow.py --base http://127.0.0.1:8021
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
ELDER = "elder_001"
PERSONA = "persona_godaewoong"
GUARDIAN_DEVICE = "dev_flow_guardian"
ELDER_DEVICE = "dev_flow_elder"

GREEN, RED, DIM, BOLD, RESET = (
    "\033[92m", "\033[91m", "\033[2m", "\033[1m", "\033[0m")


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{RED}{method} {path} → {exc.code}{RESET}\n{detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"{RED}서버에 연결하지 못했습니다 ({BASE}).{RESET}\n"
            f"  python tools/serve.py --no-reload 가 켜져 있는지 확인하세요.\n  {exc}"
        )


def ok(condition: bool, message: str) -> bool:
    mark = f"{GREEN}통과{RESET}" if condition else f"{RED}실패{RESET}"
    print(f"    [{mark}] {message}")
    return condition


def register_guardian() -> None:
    call("POST", "/api/devices", {
        "device_id": GUARDIAN_DEVICE, "elder_id": ELDER,
        "role": "guardian", "persona_id": PERSONA, "label": "대웅 폰",
    })


def poll_guardian() -> dict | None:
    """보호자 화면의 수신 폴링. 이 호출이 heartbeat 를 겸한다."""
    return call("GET", f"/api/call-invites?device_id={GUARDIAN_DEVICE}")["invite"]


def ring() -> dict:
    return call("POST", "/api/call-invites", {
        "elder_id": ELDER, "persona_id": PERSONA, "from_device": ELDER_DEVICE,
    })


def wait_for_ring_to_end(invite: dict) -> dict:
    """어르신 기기의 폴링을 그대로 흉내낸다. 판정은 서버가 한다."""
    deadline = time.time() + invite["ring_timeout_sec"] + 5
    while time.time() < deadline:
        current = call("GET", f"/api/call-invites/{invite['invite_id']}")
        if current["state"] != "ringing":
            return current
        print(f"    {DIM}벨 울리는 중… {current['seconds_left']:.0f}초 남음{RESET}")
        time.sleep(1.5)
    raise SystemExit(f"{RED}벨이 끝나지 않았습니다. 서버 타임아웃이 동작하지 않습니다.{RESET}")


# ------------------------------------------------------------------ 시나리오

def case_no_answer() -> bool:
    """보호자가 화면을 열어 두고도 받지 않는다 → 서버가 무응답을 판정한다."""
    register_guardian()
    poll_guardian()  # 화면을 열어 둔 상태로 만든다

    invite = ring()
    intro = invite["intro_duration_sec"]
    passed = ok(invite["ring_timeout_sec"] == intro,
                f"어르신 화면의 소개 영상과 같은 {intro}초를 기다린다")
    passed &= ok(poll_guardian() is not None, "보호자 기기에 벨이 실제로 도착한다")

    final = wait_for_ring_to_end(invite)
    passed &= ok(final["state"] == "timeout", "서버가 무응답으로 판정한다")
    passed &= ok(final["takeover_reason"] == "timeout",
                 "사유가 '거절'이 아니라 '무응답'으로 남는다")

    handed = call("POST", f"/api/call-invites/{invite['invite_id']}/ai-takeover", {})
    passed &= ok(bool(handed.get("call_id")), "AI 통화가 열린다")
    passed &= ok(handed["invite"]["state"] == "ai_takeover",
                 "호출 기록이 AI 인계로 닫힌다")
    return passed


def case_decline() -> bool:
    """보호자가 거절한다 → 15초를 기다리지 않고 곧바로 AI 로 간다."""
    register_guardian()
    poll_guardian()
    invite = ring()

    started = time.time()
    declined = call("POST", f"/api/call-invites/{invite['invite_id']}/decline",
                    {"device_id": GUARDIAN_DEVICE})
    passed = ok(declined["state"] == "declined", "거절이 기록된다")
    passed &= ok(declined["should_take_over"], "곧바로 AI 인계 대상이 된다")
    passed &= ok(time.time() - started < 2,
                 "벨이 끝나기를 기다리지 않는다")

    handed = call("POST", f"/api/call-invites/{invite['invite_id']}/ai-takeover", {})
    passed &= ok(handed["invite"]["takeover_reason"] == "declined",
                 "거절이었다는 사실이 AI 인계 후에도 남는다")
    return passed


def case_answer() -> bool:
    """보호자가 받는다 → AI 는 열리지 않는다. 이게 갈리지 않으면 전부 무의미하다."""
    register_guardian()
    poll_guardian()
    invite = ring()

    incoming = poll_guardian()
    passed = ok(incoming and incoming["invite_id"] == invite["invite_id"],
                "보호자가 이 호출을 집어 든다")

    answered = call("POST", f"/api/call-invites/{invite['invite_id']}/answer",
                    {"device_id": GUARDIAN_DEVICE})
    passed &= ok(answered["state"] == "answered", "사람 통화로 연결된다")
    passed &= ok(not answered["should_take_over"], "AI 인계 대상이 아니다")

    elder_view = call("GET", f"/api/call-invites/{invite['invite_id']}")
    passed &= ok(elder_view["state"] == "answered",
                 "어르신 기기도 폴링으로 같은 결과를 본다")

    try:
        call("POST", f"/api/call-invites/{invite['invite_id']}/ai-takeover", {})
        passed &= ok(False, "받은 통화는 AI 로 넘어가지 않는다")
    except SystemExit:
        passed &= ok(True, "받은 통화는 AI 로 넘어가지 않는다")

    call("POST", f"/api/call-invites/{invite['invite_id']}/end")
    return passed


def case_no_device() -> bool:
    """받을 기기가 아예 없다 → 같은 시간을 울리되 사유가 따로 남는다."""
    invite = call("POST", "/api/call-invites", {
        "elder_id": ELDER, "persona_id": "persona_yujin",
        "from_device": ELDER_DEVICE,
    })
    # 받을 기기가 없어도 대기 시간을 줄이지 않는다. 어르신 화면에서 도는
    # 소개 영상과 어긋나면 화면이 끝나기 전에 통화가 바뀌어 버린다.
    # 기기 유무는 대기 시간이 아니라 사유(no_device)로만 드러난다.
    intro = invite["intro_duration_sec"]
    passed = ok(invite["ring_timeout_sec"] == intro,
                f"기기가 없어도 소개 영상과 같은 {intro}초를 기다린다")
    passed &= ok(bool(invite["no_live_device"]),
                 "받을 기기가 없다는 사실은 대기 시간이 아니라 여기 남는다")

    final = wait_for_ring_to_end(invite)
    passed &= ok(final["takeover_reason"] == "no_device",
                 "'무응답'이 아니라 '받을 기기 없음'으로 구분된다")
    return passed


CASES = {
    "no_answer": ("보호자가 받지 않음", case_no_answer),
    "decline": ("보호자가 거절", case_decline),
    "answer": ("보호자가 받음", case_answer),
    "no_device": ("받을 기기 없음", case_no_device),
}


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--case", choices=sorted(CASES))
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    call("GET", "/api/health")
    selected = [args.case] if args.case else list(CASES)

    results = {}
    for name in selected:
        title, runner = CASES[name]
        print(f"\n{BOLD}{title}{RESET} {DIM}({name}){RESET}")
        results[name] = runner()

    failed = [name for name, passed in results.items() if not passed]
    print()
    if failed:
        print(f"{RED}실패: {', '.join(failed)}{RESET}")
        return 1
    print(f"{GREEN}호출 흐름 {len(results)}가지 모두 통과{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
