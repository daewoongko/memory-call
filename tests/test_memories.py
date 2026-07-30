"""
기억 계약.

핵심은 **AI 는 스스로 기억을 늘리지 못한다**는 것이다. 통화 중 처음 나온
이야기는 `unverified_recall` 로 남고, 보호자가 승인해야만 기억이 된다.

이 경로가 깨지면 AI 가 자기가 지어낸 이야기를 다음 통화에서 사실로 쓰게 된다.
"""

import db


def _statuses(elder_id):
    with db.connect() as conn:
        return dict(conn.execute(
            "SELECT status, COUNT(*) FROM memories WHERE elder_id = ? "
            "GROUP BY status", (elder_id,)
        ).fetchall())


# ------------------------------------------------------------ 상태값 제약

def test_네_가지_상태만_허용한다(client):
    for status in ("verified", "partial", "unverified", "prohibited"):
        res = client.post(f"/api/elders/{client.elder_id}/memories",
                          json={"title": f"기억 {status}", "status": status})
        assert res.status_code == 200, f"{status} 가 거부됐다"


def test_모르는_상태값은_거부한다(client):
    res = client.post(f"/api/elders/{client.elder_id}/memories",
                      json={"title": "이상한 기억", "status": "maybe"})
    assert res.status_code == 422


def test_제목_없는_기억은_거부한다(client):
    res = client.post(f"/api/elders/{client.elder_id}/memories",
                      json={"title": "", "status": "verified"})
    assert res.status_code == 422


# ------------------------------------------------------------ 조회 · 수정

def test_상태로_필터링할_수_있다(client):
    res = client.get(f"/api/elders/{client.elder_id}/memories",
                     params={"status": "verified"})

    assert res.status_code == 200
    rows = res.json()
    items = rows["memories"] if isinstance(rows, dict) else rows
    assert all(m["status"] == "verified" for m in items)


def test_기억_상태를_바꿀_수_있다(client):
    created = client.post(f"/api/elders/{client.elder_id}/memories",
                          json={"title": "속초 여행", "status": "partial"}).json()
    memory_id = created.get("memory_id") or created["memory"]["memory_id"]

    res = client.patch(f"/api/memories/{memory_id}", json={"status": "verified"})

    assert res.status_code == 200
    assert db.get_memory(memory_id)["status"] == "verified"


def test_금지로_바꿀_수_있다(client):
    """보호자가 민감한 기억을 금지 처리하는 경로."""
    created = client.post(f"/api/elders/{client.elder_id}/memories",
                          json={"title": "가족 갈등", "status": "verified"}).json()
    memory_id = created.get("memory_id") or created["memory"]["memory_id"]

    client.patch(f"/api/memories/{memory_id}", json={"status": "prohibited"})

    assert db.get_memory(memory_id)["status"] == "prohibited"


def test_기억을_삭제할_수_있다(client):
    created = client.post(f"/api/elders/{client.elder_id}/memories",
                          json={"title": "지울 기억", "status": "verified"}).json()
    memory_id = created.get("memory_id") or created["memory"]["memory_id"]

    assert client.delete(f"/api/memories/{memory_id}").status_code == 200
    assert db.get_memory(memory_id) is None


# ------------------------------------------------------------ 미확인 회상 승인

def _recall_utterance(client, call_id):
    """AI 가 미확인 회상을 신고한 발화 하나를 만든다."""
    client.llm.set_reply(
        reply="그런 일이 있었구나. 더 얘기해줘.",
        certainty="unverified",
        unverified_recall={"title": "낚시 갔던 날", "description": "손자와 함께"},
    )
    client.post(f"/api/calls/{call_id}/turn",
                json={"text": "그때 너랑 낚시 갔던 거 기억나니?"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT utterance_id FROM utterances WHERE call_id = ? "
            "AND speaker = 'ai' AND unverified_recall IS NOT NULL "
            "ORDER BY seq DESC LIMIT 1", (call_id,)
        ).fetchone()
    assert row is not None, "미확인 회상이 기록되지 않았다"
    return row["utterance_id"]


def test_미확인_회상이_발화에_기록된다(client, open_call):
    utterance_id = _recall_utterance(client, open_call["call_id"])
    assert utterance_id > 0


def test_승인하면_기억이_된다(client, open_call):
    utterance_id = _recall_utterance(client, open_call["call_id"])
    before = _statuses(client.elder_id).get("verified", 0)

    res = client.post(f"/api/recalls/{utterance_id}/review",
                      params={"elder_id": client.elder_id},
                      json={"decision": "approved", "title": "낚시 갔던 날",
                            "status": "verified"})

    assert res.status_code == 200
    assert _statuses(client.elder_id).get("verified", 0) == before + 1


def test_거부하면_기억이_되지_않는다(client, open_call):
    utterance_id = _recall_utterance(client, open_call["call_id"])
    before = sum(_statuses(client.elder_id).values())

    res = client.post(f"/api/recalls/{utterance_id}/review",
                      params={"elder_id": client.elder_id},
                      json={"decision": "rejected"})

    assert res.status_code == 200
    assert sum(_statuses(client.elder_id).values()) == before


def test_판단은_기록되어_다시_묻지_않는다(client, open_call):
    utterance_id = _recall_utterance(client, open_call["call_id"])

    client.post(f"/api/recalls/{utterance_id}/review",
                params={"elder_id": client.elder_id},
                json={"decision": "rejected"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT decision FROM recall_reviews WHERE utterance_id = ?",
            (utterance_id,)
        ).fetchone()
    assert row["decision"] == "rejected"


def test_모르는_판단값은_거부한다(client, open_call):
    utterance_id = _recall_utterance(client, open_call["call_id"])

    res = client.post(f"/api/recalls/{utterance_id}/review",
                      params={"elder_id": client.elder_id},
                      json={"decision": "maybe"})

    assert res.status_code == 422


def test_승인_시_verified_또는_partial만_허용한다(client, open_call):
    """승인한 기억을 곧바로 prohibited 로 만들 수는 없다."""
    utterance_id = _recall_utterance(client, open_call["call_id"])

    res = client.post(f"/api/recalls/{utterance_id}/review",
                      params={"elder_id": client.elder_id},
                      json={"decision": "approved", "title": "x",
                            "status": "prohibited"})

    assert res.status_code == 422


def test_없는_발화의_판단은_400(client):
    res = client.post("/api/recalls/999999/review",
                      params={"elder_id": client.elder_id},
                      json={"decision": "rejected"})
    assert res.status_code == 400
