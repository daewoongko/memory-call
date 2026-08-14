"""
P2P 가 이 망에서 붙는지 재는 진단.

`docs/call_transport_decision.md` 는 WebRTC P2P 를 고르면서 §8 에 "이 결정은
아직 실측이 아니라 추론"이라고 적어 두었다. 여기가 그 자리를 메운다.
붙지 않는 망이면 TURN 을 더하거나 관리형 SFU 로 갈아타야 하는데, 발표
전에 알아야 갈아탈 시간이 있다.

서버가 하는 일은 둘뿐이다.

  1. 두 기기가 주고받는 신호(SDP·ICE)를 방 단위로 전달한다. 내용은 보지 않는다.
  2. 측정 결과를 남긴다.

신호는 오갈 때마다 쌓이므로 오래된 것은 버린다. 상주 청소 작업을 두지 않고
쓰는 김에 치운다 — invites.py 의 lazy expiry 와 같은 이유로, Render 무료
인스턴스에서 백그라운드 작업이 살아 있다고 가정할 수 없다.
"""

import random
from datetime import datetime

import db
import signaling

KINDS = ("offer", "answer", "ice")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_room() -> str:
    """어르신이 아니라 개발자가 읽는 코드지만, 폰 두 대에 입력하므로 짧게."""
    return f"{random.randint(0, 999999):06d}"


def send(room: str, sender: str, kind: str, payload) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind 는 {KINDS} 중 하나여야 합니다.")
    return signaling.send(room, sender, kind, payload)


def poll(room: str, sender: str, since: int = 0) -> dict:
    return signaling.poll(room, sender, since)


def record(result: dict) -> dict:
    """측정 하나를 남긴다. 어느 망에서 쟀는지는 사람이 label 로 적는다."""
    with db.connect() as conn:
        result_id = db.insert(conn, "nettest_results", {
            "room": result.get("room"),
            "label": (result.get("label") or "").strip()[:60] or None,
            "connected": 1 if result.get("connected") else 0,
            "route": result.get("route"),
            "symmetric": (
                None if result.get("symmetric") is None
                else int(bool(result.get("symmetric")))
            ),
            "stun_ok": (
                None if result.get("stun_ok") is None
                else int(bool(result.get("stun_ok")))
            ),
            "elapsed_ms": result.get("elapsed_ms"),
            "round_trip_ms": result.get("round_trip_ms"),
            # 기종을 알아야 결과를 읽을 수 있다. 길게 저장하지는 않는다.
            "user_agent": (result.get("user_agent") or "")[:120] or None,
            "created_at": _now(),
        })
        conn.commit()
    return {"result_id": result_id}


def results(limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM nettest_results ORDER BY result_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [db._row(row) for row in rows]
