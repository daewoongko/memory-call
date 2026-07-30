"""
통화 상태 머신과 턴 계약.

핵심은 **AI 고지를 건너뛴 통화가 성립하지 않는다**는 것이다 (절대 규칙 7번).
프롬프트가 아니라 상태 전이로 강제하므로, 여기서 깨지면 정책이 깨진 것이다.
"""

import pytest

import conversation


# ------------------------------------------------------------------ 고지 강제

def test_통화는_고지_단계로_시작한다(client):
    res = client.post("/api/calls", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "ai_disclosure"


def test_고지_전에는_대화할_수_없다(client):
    call_id = client.post("/api/calls", json={}).json()["call_id"]

    res = client.post(f"/api/calls/{call_id}/turn", json={"text": "잘 지내니?"})

    assert res.status_code == 409
    assert "고지" in res.json()["detail"]


def test_고지_후에는_대화할_수_있다(client):
    call_id = client.post("/api/calls", json={}).json()["call_id"]

    disclosed = client.post(f"/api/calls/{call_id}/disclosed")
    assert disclosed.status_code == 200
    assert disclosed.json()["status"] == "active"

    res = client.post(f"/api/calls/{call_id}/turn", json={"text": "잘 지내니?"})
    assert res.status_code == 200


def test_고지_안내_문장이_페르소나_이름을_담는다(client):
    body = client.post("/api/calls", json={}).json()
    assert body["persona_name"] in body["announcement"]
    assert "AI" in body["announcement"]


def test_고지를_두_번_불러도_안전하다(client):
    call_id = client.post("/api/calls", json={}).json()["call_id"]

    first = client.post(f"/api/calls/{call_id}/disclosed").json()
    second = client.post(f"/api/calls/{call_id}/disclosed").json()

    assert first["status"] == second["status"] == "active"


# ------------------------------------------------------------------ 턴 계약

def test_턴_응답이_계약된_필드를_전부_담는다(client, open_call):
    res = client.post(f"/api/calls/{open_call['call_id']}/turn",
                      json={"text": "밥은 먹었니?"})

    body = res.json()
    for field in ("reply", "intent", "certainty", "used_memory_ids",
                  "used_schedule_ids", "risk", "medication_status",
                  "unverified_recall", "grounding", "safety_flags",
                  "rewritten", "latency_ms"):
        assert field in body, f"{field} 가 빠졌다"


def test_빈_발화는_거부한다(client, open_call):
    res = client.post(f"/api/calls/{open_call['call_id']}/turn", json={"text": ""})
    assert res.status_code == 422


def test_500자를_넘는_발화는_거부한다(client, open_call):
    res = client.post(f"/api/calls/{open_call['call_id']}/turn",
                      json={"text": "가" * 501})
    assert res.status_code == 422


def test_없는_통화에_턴을_보내면_404(client):
    res = client.post("/api/calls/call_nonexistent/turn", json={"text": "여보세요"})
    assert res.status_code == 404


def test_쿼터_초과는_429로_내려간다(client, open_call, monkeypatch):
    import llm

    def boom(messages, **kwargs):
        raise llm.QuotaExceeded("무료 티어 한도 초과")

    monkeypatch.setattr(llm, "call_json", boom)
    res = client.post(f"/api/calls/{open_call['call_id']}/turn",
                      json={"text": "안녕"})

    assert res.status_code == 429


def test_모델_실패는_502로_내려간다(client, open_call, monkeypatch):
    import llm

    def boom(messages, **kwargs):
        raise RuntimeError("연결 끊김")

    monkeypatch.setattr(llm, "call_json", boom)
    res = client.post(f"/api/calls/{open_call['call_id']}/turn",
                      json={"text": "안녕"})

    assert res.status_code == 502


# ------------------------------------------------------------------ 종료 · 인계

def test_종료하면_상태가_ended가_된다(client, open_call):
    res = client.post(f"/api/calls/{open_call['call_id']}/end",
                      json={"reason": "user_ended"})

    assert res.status_code == 200
    assert res.json()["status"] == "ended"


def test_종료한_통화는_세션에서_사라진다(client, open_call):
    call_id = open_call["call_id"]
    client.post(f"/api/calls/{call_id}/end", json={"reason": "user_ended"})

    res = client.post(f"/api/calls/{call_id}/turn", json={"text": "여보세요"})
    assert res.status_code == 404


def test_사람에게_인계하면_대화가_닫힌다(client, open_call):
    call_id = open_call["call_id"]

    handoff = client.post(f"/api/calls/{call_id}/handoff")
    assert handoff.status_code == 200
    assert handoff.json()["status"] == "human_handoff"

    res = client.post(f"/api/calls/{call_id}/turn", json={"text": "여보세요"})
    assert res.status_code == 409


def test_인계하면_call_type이_ai_to_direct가_된다(client, open_call):
    import db

    client.post(f"/api/calls/{open_call['call_id']}/handoff")

    with db.connect() as conn:
        row = conn.execute("SELECT call_type FROM calls WHERE call_id = ?",
                           (open_call["call_id"],)).fetchone()
    assert row["call_type"] == "ai_to_direct"


def test_인계는_handoff_이벤트를_남긴다(client, open_call):
    import db

    client.post(f"/api/calls/{open_call['call_id']}/handoff")

    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM call_events "
            "WHERE call_id = ? AND event_type = 'handoff'",
            (open_call["call_id"],),
        ).fetchone()[0]
    assert n == 1


# ------------------------------------------------------------------ 기록

def test_발화가_DB에_기록된다(client, open_call):
    call_id = open_call["call_id"]
    client.post(f"/api/calls/{call_id}/turn", json={"text": "오늘 날씨 좋네"})

    log = client.get(f"/api/calls/{call_id}/log").json()

    assert log["call_id"] == call_id
    speakers = [row["speaker"] for row in log["utterances"]]
    assert "elder" in speakers
    assert "ai" in speakers
    # seq 는 순서대로여야 리포트의 반복 질문 집계가 맞는다.
    seqs = [row["seq"] for row in log["utterances"]]
    assert seqs == sorted(seqs)


def test_없는_통화의_로그는_404(client):
    assert client.get("/api/calls/call_nonexistent/log").status_code == 404


def test_safety가_보정한_값이_저장된다(client, open_call):
    """모델이 근거 없이 verified 를 신고하면 강등되어 저장돼야 한다."""
    client.llm.set_reply(certainty="verified", used_memory_ids=[])

    res = client.post(f"/api/calls/{open_call['call_id']}/turn",
                      json={"text": "그때 기억나?"})

    body = res.json()
    assert body["certainty"] != "verified"
    codes = [f["code"] for f in body["safety_flags"]]
    assert "UNGROUNDED_CERTAINTY" in codes


# ------------------------------------------------------------------ Session 직접

def test_Session은_고지_상태로_생성된다(session):
    assert session.status == conversation.DISCLOSURE


def test_Session_turn은_고지_전에_예외를_낸다(session):
    with pytest.raises(conversation.DisclosureRequired):
        session.turn("여보세요")


def test_Session_turn은_종료_후에_예외를_낸다(session):
    session.disclose()
    session.end("user_ended")
    with pytest.raises(conversation.CallClosed):
        session.turn("여보세요")
