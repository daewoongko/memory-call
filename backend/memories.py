"""
기억 관리.

가족 추억은 보호자만 등록·수정할 수 있다. AI 는 등록된 것을 읽기만 한다.

명세 FR-05 — 통화 중 노인이 처음 듣는 이야기를 꺼내면 AI 는 사실로 확정하지
않고 넘긴다. 그 내용은 여기 '확인 대기'로 쌓이고, 보호자가 승인해야만
다음 통화부터 사실로 쓰인다. 거절하면 다시 묻지 않는다.
"""

import uuid

import db

STATUSES = ("verified", "partial", "unverified", "prohibited")


def _new_id() -> str:
    return f"mem_{uuid.uuid4().hex[:8]}"


def listing(elder_id: str = "elder_001", status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM memories WHERE elder_id = ?"
    params: list = [elder_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY CASE status WHEN 'prohibited' THEN 1 ELSE 0 END, created_at DESC"

    with db.connect() as conn:
        return [db._row(r) for r in conn.execute(sql, params).fetchall()]


def create(elder_id: str, data: dict) -> dict:
    memory = {
        "memory_id": data.get("memory_id") or _new_id(),
        "elder_id": elder_id,
        "title": data["title"],
        "description": data.get("description") or "",
        "date_text": data.get("date_text") or "",
        "location": data.get("location") or "",
        "participants": data.get("participants") or [],
        "status": data.get("status") or "verified",
        # 금지 기억은 어떤 경우에도 대화에 쓰지 않는다
        "conversation_allowed": 0 if data.get("status") == "prohibited"
                                 else int(bool(data.get("conversation_allowed", True))),
        "note": data.get("note"),
        "source_call_id": data.get("source_call_id"),
    }
    with db.connect() as conn:
        db.insert(conn, "memories", memory)
        conn.commit()
    return memory


def update(memory_id: str, fields: dict) -> dict:
    allowed = {"title", "description", "date_text", "location", "participants",
               "status", "conversation_allowed", "note"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if patch.get("status") == "prohibited":
        patch["conversation_allowed"] = 0
    if not patch:
        raise ValueError("바꿀 내용이 없습니다.")

    sets = ", ".join(f"{k} = ?" for k in patch)
    values = [db._dump(v) for v in patch.values()] + [memory_id]
    with db.connect() as conn:
        conn.execute(f"UPDATE memories SET {sets} WHERE memory_id = ?", values)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"기억 {memory_id} 없음")
    return db._row(row)


def delete(memory_id: str) -> None:
    """삭제 요청된 기억은 보관하지 않는다 (명세 21장)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
        conn.commit()


def pending_recalls(elder_id: str = "elder_001") -> list[dict]:
    """아직 보호자가 판단하지 않은 회상."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT u.utterance_id, u.call_id, u.unverified_recall, u.created_at "
            "FROM utterances u "
            "JOIN calls c ON c.call_id = u.call_id "
            "LEFT JOIN recall_reviews r ON r.utterance_id = u.utterance_id "
            "WHERE c.elder_id = ? AND u.unverified_recall IS NOT NULL "
            "  AND u.unverified_recall != '' AND r.utterance_id IS NULL "
            "ORDER BY u.created_at DESC",
            (elder_id,),
        ).fetchall()

    out = []
    for r in rows:
        row = db._row(r)
        recall = row.get("unverified_recall") or {}
        if not isinstance(recall, dict):
            continue
        out.append({
            "utterance_id": row["utterance_id"],
            "call_id": row["call_id"],
            "created_at": row["created_at"],
            "summary": recall.get("summary"),
            "quote": recall.get("quote"),
        })
    return out


def review(utterance_id: int, decision: str, elder_id: str = "elder_001",
           memory: dict | None = None, note: str | None = None) -> dict:
    """회상을 승인하거나 거절한다.

    승인하면 기억으로 등록되어 다음 통화부터 사실로 쓰인다.
    거절하면 기록만 남기고 기억은 만들지 않는다.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("decision 은 approved 또는 rejected 여야 합니다.")

    # 존재 확인은 승인·거절 양쪽 앞에 있어야 한다.
    # 거절 경로에만 없으면 recall_reviews 의 외래키가 터져 500 이 난다.
    with db.connect() as conn:
        row = conn.execute(
            "SELECT call_id, unverified_recall FROM utterances "
            "WHERE utterance_id = ?", (utterance_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"발화 {utterance_id} 없음")

    created = None
    if decision == "approved":
        source = db._row(row)
        recall = source.get("unverified_recall") or {}

        data = dict(memory or {})
        data.setdefault("title", (recall.get("summary") or "확인된 기억")[:60])
        data.setdefault("description", recall.get("quote") or "")
        data.setdefault("status", "verified")
        data["source_call_id"] = source["call_id"]
        created = create(elder_id, data)

    with db.connect() as conn:
        db.insert(conn, "recall_reviews", {
            "utterance_id": utterance_id,
            "decision": decision,
            "memory_id": created["memory_id"] if created else None,
            "note": note,
        })
        conn.commit()

    return {"decision": decision, "memory": created}
