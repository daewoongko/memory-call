"""Per-family Anam avatar lifecycle.

The permanent provider id stays in SQLite. Public callers only receive status
metadata, so a browser can never substitute another family's avatar id.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

import anam
import db
from storage import persona_face_storage


class AvatarProfileError(ValueError):
    pass


def _persona(persona_id: str, elder_id: str | None = None) -> dict:
    with db.connect() as conn:
        if elder_id:
            row = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ? AND elder_id = ?",
                (persona_id, elder_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ?", (persona_id,),
            ).fetchone()
    if row is None:
        raise AvatarProfileError("가족 프로필을 찾을 수 없습니다.")
    return db._row(row)


def _ensure_profile(conn, persona_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO persona_avatar_profiles(persona_id) VALUES (?)",
        (persona_id,),
    )


def public_profile(persona_id: str, elder_id: str | None = None) -> dict:
    persona = _persona(persona_id, elder_id)
    with db.connect() as conn:
        _ensure_profile(conn, persona_id)
        row = conn.execute(
            "SELECT avatar_model, source_photo_name, avatar_status, last_error, "
            "created_at, updated_at FROM persona_avatar_profiles "
            "WHERE persona_id = ?", (persona_id,),
        ).fetchone()
        conn.commit()
    return {
        "persona_id": persona_id,
        "display_name": persona.get("display_name"),
        "provider_configured": anam.configured(),
        "ready": bool(row and row["avatar_status"] == "ready"),
        **(dict(row) if row else {}),
    }


def active_avatar(persona_id: str | None) -> dict | None:
    if not persona_id:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT avatar_id, avatar_model FROM persona_avatar_profiles "
            "WHERE persona_id = ? AND avatar_status = 'ready'",
            (persona_id,),
        ).fetchone()
    if not row or not row["avatar_id"]:
        return None
    return {
        "avatar_id": str(row["avatar_id"]),
        "avatar_model": str(row["avatar_model"] or anam.DEFAULT_AVATAR_MODEL),
    }


def active_avatar_id(persona_id: str | None) -> str | None:
    selected = active_avatar(persona_id)
    return selected["avatar_id"] if selected else None


def _provider_image(source: Path) -> bytes:
    """Return a Cara 4-ready square JPEG with safe head/chest margins."""
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise AvatarProfileError("선택한 사진을 읽을 수 없습니다.") from exc

    size = (1280, 1280)
    background = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(28))
    foreground = ImageOps.contain(image, (920, 1120), method=Image.Resampling.LANCZOS)
    left = (size[0] - foreground.width) // 2
    top = (size[1] - foreground.height) // 2
    background.paste(foreground, (left, top))
    output = io.BytesIO()
    background.save(output, format="JPEG", quality=91, optimize=True)
    return output.getvalue()


def sync_from_confirmed_photo(
    persona_id: str, photo_name: str, elder_id: str | None = None,
    *, force: bool = False,
) -> dict:
    persona = _persona(persona_id, elder_id)
    safe_name = Path(photo_name).name
    if safe_name != photo_name:
        raise AvatarProfileError("사진 이름이 올바르지 않습니다.")
    source = persona_face_storage(persona_id).source / safe_name
    if not source.is_file():
        raise AvatarProfileError("확정한 가족 사진을 찾을 수 없습니다.")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    with db.connect() as conn:
        _ensure_profile(conn, persona_id)
        existing = conn.execute(
            "SELECT source_sha256, avatar_status FROM persona_avatar_profiles "
            "WHERE persona_id = ?", (persona_id,),
        ).fetchone()
        if (
            not force and existing
            and existing["source_sha256"] == source_hash
            and existing["avatar_status"] == "ready"
        ):
            conn.commit()
            return public_profile(persona_id, elder_id)
        conn.execute(
            "UPDATE persona_avatar_profiles SET avatar_id = NULL, "
            "source_photo_name = ?, source_sha256 = ?, avatar_status = 'creating', "
            "last_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
            (safe_name, source_hash, persona_id),
        )
        conn.commit()

    if not anam.configured():
        with db.connect() as conn:
            conn.execute(
                "UPDATE persona_avatar_profiles SET avatar_status = 'unregistered', "
                "last_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
                (persona_id,),
            )
            conn.commit()
        return public_profile(persona_id, elder_id)

    try:
        result = anam.create_avatar(
            display_name=f"다소니 {persona.get('display_name') or persona_id}",
            image=_provider_image(source),
            filename=f"{persona_id}-avatar.jpg",
            content_type="image/jpeg",
        )
    except (anam.AnamNotConfigured, anam.AnamUnavailable, AvatarProfileError) as exc:
        message = str(exc)[:240]
        with db.connect() as conn:
            conn.execute(
                "UPDATE persona_avatar_profiles SET avatar_status = 'failed', "
                "last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
                (message, persona_id),
            )
            conn.commit()
        return public_profile(persona_id, elder_id)

    with db.connect() as conn:
        conn.execute(
            "UPDATE persona_avatar_profiles SET avatar_id = ?, avatar_model = ?, "
            "avatar_status = 'ready', last_error = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
            (result["avatar_id"], result["avatar_model"], persona_id),
        )
        conn.commit()
    return public_profile(persona_id, elder_id)
