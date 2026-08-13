"""
호출(invite) 상태.

지금까지 "전화를 건다"는 어르신 기기 안의 15초 타이머였다. 보호자 기기에는
아무 신호도 가지 않았으므로 받지 않았다는 것을 판정할 주체가 없었고, AI
대리통화는 대리가 아니라 그냥 15초 늦게 시작하는 AI 통화였다.

여기서 호출을 서버의 상태로 만든다. 그래야 세 가지가 성립한다.

  - 보호자 기기가 실제로 벨을 받는다
  - 받지 않은 것과 거절한 것이 구분된다
  - AI 가 왜 대신 받았는지가 기록에 남는다 (takeover_reason)

상태 전이

    ringing ──answer───→ answered ──end──→ ended
       │
       ├──decline──→ declined ─┐
       ├──(시간초과)→ timeout  ─┼→ ai_takeover ──end──→ ended
       │                        │
       └──cancel───→ cancelled  ┘   (transport_failed 도 같은 자리로 들어온다)

타임아웃은 서버가 판정한다. 클라이언트 타이머를 믿으면 처음 문제로 돌아간다.
다만 상주 스케줄러는 두지 않고 조회 시점에 만료시킨다(lazy expiry). Render
무료 인스턴스는 유휴 상태에서 잠들기 때문에 백그라운드 타이머가 살아 있다고
가정할 수 없다.

시간 계산이 실패하면 만료된 것으로 본다. 이 서비스에서 잘못될 수 있는 두
방향 중 "AI 가 대신 받는다"는 정상 동작이고, "어르신이 벨 화면에 갇힌다"는
사고다. 그래서 실패는 AI 쪽으로 떨어뜨린다.
"""

import uuid
from datetime import datetime

import db

# 벨이 울리는 기본 시간. 명세 FR-01 의 가족 응답 대기 시간이다.
DEFAULT_RING_SEC = 15

# 받을 기기가 하나도 없을 때의 대기 시간. 아무도 없는데 15초를 기다리게 할
# 이유는 없지만, 0초로 만들면 어르신이 전화를 건 감각을 잃는다.
NO_DEVICE_RING_SEC = 6

# 이 시간 안에 수신 폴링을 한 기기만 살아 있다고 본다.
# 프론트가 1.5초 주기로 물어보므로 몇 번 놓쳐도 죽었다고 판정하지 않는다.
DEVICE_ALIVE_SEC = 12

RINGING = "ringing"
ANSWERED = "answered"
DECLINED = "declined"
TIMEOUT = "timeout"
AI_TAKEOVER = "ai_takeover"
ENDED = "ended"
CANCELLED = "cancelled"

# AI 인계로 이어질 수 있는 상태. 이미 사람이 받았거나 끝난 통화는 넘기지 않는다.
TAKEOVER_SOURCES = {RINGING, DECLINED, TIMEOUT}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _elapsed(created_at: str | None) -> float:
    """건 지 몇 초 지났는가. 읽을 수 없으면 만료된 것으로 본다."""
    try:
        return (datetime.now() - datetime.fromisoformat(created_at)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


# ------------------------------------------------------------------ 기기

def register_device(device_id: str, elder_id: str, role: str,
                    persona_id: str | None = None,
                    label: str | None = None) -> dict:
    """기기를 등록한다. 같은 device_id 로 다시 부르면 등록 내용을 갱신한다.

    device_id 는 클라이언트가 만들어 localStorage 에 보관한다. 치매가 있는
    분이 아이디와 비밀번호를 입력할 수 없다는 link_codes 의 전제가 여기도
    그대로 적용된다.
    """
    if role not in ("elder", "guardian"):
        raise ValueError("role 은 elder 또는 guardian 이어야 합니다.")
    if role == "guardian" and not persona_id:
        raise ValueError("보호자 기기는 어떤 가족인지(persona_id) 알려야 합니다.")

    now = _now()
    with db.connect() as conn:
        if persona_id:
            exists = conn.execute(
                "SELECT 1 FROM personas WHERE persona_id = ? AND elder_id = ?",
                (persona_id, elder_id),
            ).fetchone()
            if exists is None:
                raise ValueError(f"persona_id={persona_id} 가 이 어르신에 없습니다.")

        created = conn.execute(
            "SELECT created_at FROM devices WHERE device_id = ?", (device_id,),
        ).fetchone()
        db.insert(conn, "devices", {
            "device_id": device_id,
            "elder_id": elder_id,
            "role": role,
            "persona_id": persona_id,
            "label": label,
            "last_seen_at": now,
            "created_at": created["created_at"] if created else now,
        })
        conn.commit()

    return {"device_id": device_id, "elder_id": elder_id, "role": role,
            "persona_id": persona_id, "label": label}


def _touch(conn, device_id: str) -> None:
    conn.execute("UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                 (_now(), device_id))


def _live_guardian_count(conn, persona_id: str | None) -> int:
    """이 페르소나로 등록되어 최근까지 폴링한 보호자 기기 수."""
    if not persona_id:
        return 0
    rows = conn.execute(
        "SELECT last_seen_at FROM devices "
        "WHERE persona_id = ? AND role = 'guardian'",
        (persona_id,),
    ).fetchall()
    return sum(1 for row in rows
               if _elapsed(row["last_seen_at"]) <= DEVICE_ALIVE_SEC)


# ------------------------------------------------------------------ 호출

def create(elder_id: str, persona_id: str | None,
           from_device: str | None = None) -> dict:
    """어르신이 가족에게 전화를 건다."""
    invite_id = f"invite_{uuid.uuid4().hex[:12]}"
    with db.connect() as conn:
        live = _live_guardian_count(conn, persona_id)
        if from_device:
            _touch(conn, from_device)
        db.insert(conn, "call_invites", {
            "invite_id": invite_id,
            "elder_id": elder_id,
            "persona_id": persona_id,
            "from_device": from_device,
            "state": RINGING,
            "ring_timeout_sec": DEFAULT_RING_SEC if live else NO_DEVICE_RING_SEC,
            "no_live_device": 0 if live else 1,
            "created_at": _now(),
        })
        conn.commit()
    return get(invite_id)


def _expire_if_due(conn, row: dict) -> dict:
    """울릴 시간이 지난 호출을 timeout 으로 확정한다.

    조회할 때마다 확인하므로 별도 스케줄러가 필요 없다. 조건부 UPDATE 라
    그 사이에 보호자가 받았다면 덮어쓰지 않는다.
    """
    if row["state"] != RINGING:
        return row
    if _elapsed(row["created_at"]) < row["ring_timeout_sec"]:
        return row

    reason = "no_device" if row["no_live_device"] else "timeout"
    changed = conn.execute(
        "UPDATE call_invites SET state = ?, takeover_reason = ? "
        "WHERE invite_id = ? AND state = ?",
        (TIMEOUT, reason, row["invite_id"], RINGING),
    ).rowcount
    conn.commit()
    if not changed:
        return _fetch(conn, row["invite_id"])
    return {**row, "state": TIMEOUT, "takeover_reason": reason}


def _fetch(conn, invite_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM call_invites WHERE invite_id = ?", (invite_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"invite_id={invite_id} 없음")
    return db._row(row)


def get(invite_id: str) -> dict:
    """어르신 기기가 이걸 폴링한다. 상태가 곧 다음에 할 일이다."""
    with db.connect() as conn:
        return _decorate(_expire_if_due(conn, _fetch(conn, invite_id)))


def _decorate(row: dict) -> dict:
    """화면이 판단하지 않아도 되도록 남은 시간과 다음 동작을 붙인다."""
    remaining = 0.0
    if row["state"] == RINGING:
        remaining = max(0.0, row["ring_timeout_sec"] - _elapsed(row["created_at"]))
    return {
        **row,
        "seconds_left": round(remaining, 1),
        # 화면은 이 값만 보고 분기하면 된다. 상태 이름을 화면마다 해석하면
        # 규칙이 흩어져서 어긋난다.
        "should_take_over": row["state"] in (DECLINED, TIMEOUT),
    }


def incoming_for(device_id: str) -> dict | None:
    """보호자 기기의 수신 폴링. 울리고 있는 호출 하나를 준다.

    이 호출이 곧 heartbeat 다. 여기서 last_seen_at 을 갱신하므로 보호자가
    화면을 열어 두고 있다는 사실이 자동으로 서버에 남는다.
    """
    with db.connect() as conn:
        device = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,),
        ).fetchone()
        if device is None:
            raise ValueError("등록되지 않은 기기입니다.")
        _touch(conn, device_id)
        conn.commit()

        if device["role"] != "guardian":
            return None

        rows = conn.execute(
            "SELECT * FROM call_invites WHERE persona_id = ? AND state = ? "
            "ORDER BY created_at DESC LIMIT 5",
            (device["persona_id"], RINGING),
        ).fetchall()
        for row in rows:
            fresh = _expire_if_due(conn, db._row(row))
            if fresh["state"] == RINGING:
                return _decorate(fresh)
    return None


def _transition(invite_id: str, to_state: str, allowed: set[str],
                **fields) -> dict:
    """조건부 전이. 두 기기가 동시에 받아도 한 번만 성립한다."""
    with db.connect() as conn:
        row = _expire_if_due(conn, _fetch(conn, invite_id))
        if row["state"] == to_state:
            return _decorate(row)  # 같은 요청이 두 번 와도 안전하다
        if row["state"] not in allowed:
            raise ValueError(
                f"'{row['state']}' 상태에서는 '{to_state}' 로 바꿀 수 없습니다."
            )

        updates = {"state": to_state, **fields}
        marks = ", ".join(f"{key} = ?" for key in updates)
        changed = conn.execute(
            f"UPDATE call_invites SET {marks} WHERE invite_id = ? AND state = ?",
            [*updates.values(), invite_id, row["state"]],
        ).rowcount
        conn.commit()
        if not changed:
            # 그사이 다른 기기가 먼저 바꿨다. 실패가 아니라 현재 상태를 준다.
            return _decorate(_fetch(conn, invite_id))
        return _decorate(_fetch(conn, invite_id))


def answer(invite_id: str, device_id: str) -> dict:
    """보호자가 받는다. 사람↔사람 통화 구간이 시작된다."""
    return _transition(invite_id, ANSWERED, {RINGING},
                       to_device=device_id, answered_at=_now())


def decline(invite_id: str, device_id: str | None = None) -> dict:
    """보호자가 거절한다.

    거절은 실패가 아니다. 이 서비스에서 거절은 AI 가 대신 받으라는 뜻이고,
    15초를 기다리지 않고 곧바로 넘어간다.
    """
    return _transition(invite_id, DECLINED, {RINGING},
                       to_device=device_id, takeover_reason="declined")


def cancel(invite_id: str) -> dict:
    """어르신이 먼저 끊는다. AI 로 넘기지 않는다."""
    return _transition(invite_id, CANCELLED, {RINGING}, ended_at=_now())


def take_over(invite_id: str, call_id: str,
              reason: str | None = None) -> dict:
    """AI 가 대신 받는다. call_id 는 이미 열린 AI 세션이다.

    AI 세션 생성은 여기서 하지 않는다. conversation 을 끌어오면 순환 참조가
    되고, 무엇보다 "언제 세션을 여는가"는 화면의 사정이기 때문이다.
    """
    with db.connect() as conn:
        row = _expire_if_due(conn, _fetch(conn, invite_id))
    if row["state"] not in TAKEOVER_SOURCES:
        raise ValueError(f"'{row['state']}' 상태에서는 AI 로 넘길 수 없습니다.")

    # 벨이 울리는 중에 넘긴 경우에만 사유가 비어 있다. 호출자가 준 값을 쓰되
    # 없으면 전송 실패로 본다 (WebRTC 가 붙지 않은 경우).
    resolved = row["takeover_reason"] or reason or "transport_failed"
    return _transition(invite_id, AI_TAKEOVER, TAKEOVER_SOURCES,
                       ai_call_id=call_id, takeover_reason=resolved)


def end(invite_id: str) -> dict:
    """통화가 끝났다. 사람 통화든 AI 통화든 여기로 온다."""
    return _transition(invite_id, ENDED, {ANSWERED, AI_TAKEOVER, RINGING},
                       ended_at=_now())


def recent(elder_id: str = "elder_001", limit: int = 20) -> list[dict]:
    """누가 받았고 AI 가 몇 번 대신 받았는지. 보호자 리포트의 재료다."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM call_invites WHERE elder_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (elder_id, limit),
        ).fetchall()
    return [db._row(row) for row in rows]
