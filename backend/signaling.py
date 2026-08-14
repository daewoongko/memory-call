"""WebRTC 신호를 방 단위로 전달하는 공용 저장소.

진단(nettest)과 실제 통화는 같은 SDP/ICE 중계가 필요하다. 신호 중계는
측정 기능이 아니므로 이 모듈에 두고, 호출 쪽에서는 ``room=invite_id`` 로
재사용한다. 서버는 payload 내용을 해석하지 않는다.
"""

import json
from datetime import datetime, timedelta

import db

ROOM_TTL_MINUTES = 30
KINDS = ("offer", "answer", "ice")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sweep(conn) -> None:
    cutoff = (datetime.now() - timedelta(minutes=ROOM_TTL_MINUTES)).isoformat(
        timespec="seconds")
    conn.execute("DELETE FROM signal_messages WHERE created_at < ?", (cutoff,))


def send(room: str, sender: str, kind: str, payload) -> dict:
    room = room.strip()
    sender = sender.strip()
    if not room or not sender:
        raise ValueError("room 과 sender 가 필요합니다.")
    if kind not in KINDS:
        raise ValueError(f"kind 는 {KINDS} 중 하나여야 합니다.")
    with db.connect() as conn:
        _sweep(conn)
        message_id = db.insert(conn, "signal_messages", {
            "room": room,
            "sender": sender,
            "kind": kind,
            "payload": json.dumps(payload, ensure_ascii=False),
            "created_at": _now(),
        })
        conn.commit()
    return {"id": message_id}


def poll(room: str, sender: str, since: int = 0) -> dict:
    """상대가 보낸 신호만 돌려준다."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_messages "
            "WHERE room = ? AND sender != ? AND id > ? ORDER BY id",
            (room.strip(), sender.strip(), since),
        ).fetchall()

    messages = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        messages.append({
            "id": row["id"], "kind": row["kind"], "payload": payload,
        })
    return {
        "messages": messages,
        "cursor": rows[-1]["id"] if rows else since,
    }
