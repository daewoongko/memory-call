"""
기억 관리.

가족 추억은 보호자만 등록·수정할 수 있다. AI 는 등록된 것을 읽기만 한다.

명세 FR-05 — 통화 중 노인이 처음 듣는 이야기를 꺼내면 AI 는 사실로 확정하지
않고 넘긴다. 그 내용은 여기 '확인 대기'로 쌓이고, 보호자가 승인해야만
다음 통화부터 사실로 쓰인다. 거절하면 다시 묻지 않는다.
"""

import uuid
from io import BytesIO
from pathlib import Path

import db
from PIL import Image, ImageOps
from storage import MEMORY_PHOTOS_ROOT

STATUSES = ("verified", "partial", "unverified", "prohibited")
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_MAX_BYTES = 12 * 1024 * 1024


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
        memories = [db._row(r) for r in conn.execute(sql, params).fetchall()]
        usage_rows = [db._row(r) for r in conn.execute(
            "SELECT u.used_memory_ids, u.created_at FROM utterances u "
            "JOIN calls c ON c.call_id = u.call_id "
            "WHERE c.elder_id = ? AND u.speaker = 'ai' "
            "AND u.used_memory_ids IS NOT NULL AND u.used_memory_ids != ''",
            (elder_id,),
        ).fetchall()]
        artwork_rows = [db._row(r) for r in conn.execute(
            "SELECT a.memory_id, a.image_url, a.alt_text, a.caption, a.source_quote, a.status "
            "FROM heart_artworks a JOIN memories m ON m.memory_id = a.memory_id "
            "WHERE a.memory_id IS NOT NULL AND a.status = 'approved' "
            "AND m.status = 'verified' AND m.conversation_allowed = 1 "
            "ORDER BY a.created_at DESC"
        ).fetchall()]

    usage: dict[str, dict] = {}
    for row in usage_rows:
        for memory_id in row.get("used_memory_ids") or []:
            slot = usage.setdefault(memory_id, {"used_count": 0, "last_used_at": None})
            slot["used_count"] += 1
            if not slot["last_used_at"] or row["created_at"] > slot["last_used_at"]:
                slot["last_used_at"] = row["created_at"]

    for memory in memories:
        memory.update(usage.get(memory["memory_id"], {
            "used_count": 0,
            "last_used_at": None,
        }))
    artwork_by_memory = {}
    for artwork in artwork_rows:
        artwork_by_memory.setdefault(artwork["memory_id"], artwork)
    for memory in memories:
        memory["artwork"] = artwork_by_memory.get(memory["memory_id"])
    return memories


def save_photo(elder_id: str, memory_id: str, filename: str, content: bytes) -> dict:
    """가족이 올린 실제 추억 사진을 검증·회전 보정해 저장한다."""
    suffix = Path(filename or "photo.jpg").suffix.lower()
    if suffix not in PHOTO_SUFFIXES:
        raise ValueError("jpg, png, webp 사진만 올릴 수 있습니다.")
    if not content or len(content) > PHOTO_MAX_BYTES:
        raise ValueError("사진은 12MB 이하로 올려주세요.")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT elder_id FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
    if row is None or row["elder_id"] != elder_id:
        raise ValueError("해당 어르신의 기억을 찾지 못했습니다.")
    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            output_suffix = ".png" if image.mode == "RGBA" else ".jpg"
            target_dir = MEMORY_PHOTOS_ROOT / elder_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{memory_id}_{uuid.uuid4().hex[:8]}{output_suffix}"
            if output_suffix == ".png":
                image.save(target, "PNG", optimize=True)
            else:
                image.save(target, "JPEG", quality=88, optimize=True)
    except (OSError, ValueError) as exc:
        raise ValueError("열 수 있는 정상적인 이미지 파일이 아닙니다.") from exc
    url = f"/memory-photos/{elder_id}/{target.name}"
    updated = update(memory_id, {"photo_url": url})
    return {"memory_id": memory_id, "photo_url": url, "memory": updated}


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
        "photo_url": data.get("photo_url"),
        "happened_year": data.get("happened_year"),
    }
    with db.connect() as conn:
        db.insert(conn, "memories", memory)
        conn.commit()
    return memory


def update(memory_id: str, fields: dict) -> dict:
    allowed = {"title", "description", "date_text", "location", "participants",
               "status", "conversation_allowed", "note", "photo_url",
               "happened_year"}
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
        conn.execute(
            "UPDATE heart_artworks SET memory_id = NULL, status = 'rejected' "
            "WHERE memory_id = ?", (memory_id,),
        )
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

        candidate_rows = [db._row(r) for r in conn.execute(
            "SELECT source_utterance_id, image_url, alt_text, caption, source_quote "
            "FROM heart_artworks WHERE status = 'candidate' "
            "AND source_utterance_id IS NOT NULL ORDER BY created_at DESC"
        ).fetchall()]

    candidate_by_utterance = {}
    for artwork in candidate_rows:
        candidate_by_utterance.setdefault(artwork["source_utterance_id"], artwork)
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
            "artwork": candidate_by_utterance.get(row["utterance_id"]),
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

    created = None
    if decision == "approved":
        with db.connect() as conn:
            row = conn.execute(
                "SELECT call_id, unverified_recall FROM utterances "
                "WHERE utterance_id = ?", (utterance_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"발화 {utterance_id} 없음")
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
        if created:
            # 확인 전 미리보기 후보가 있었다면 이제 확정된 가족 기억에 귀속한다.
            # 운영에서는 이 시점에 가족이 보완한 세부 정보로 최종 이미지를 생성한다.
            conn.execute(
                "UPDATE heart_artworks SET memory_id = ?, status = 'approved' "
                "WHERE source_utterance_id = ? AND status = 'candidate'",
                (created["memory_id"], utterance_id),
            )
        conn.commit()

    return {"decision": decision, "memory": created}
