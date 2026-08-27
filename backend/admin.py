"""
페르소나·프로필·사진 관리.

명세 FR-02 — 가족 페르소나는 보호자가 등록한다.
등록된 말투와 호칭이 그대로 시스템 프롬프트에 들어가고,
등록된 사진이 모핑 영상의 재료가 된다.

사진은 파일로 다루므로 여기서만 디스크를 만진다.
"""

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import db
import face_quality
from storage import (
    ALIGNED_FACES_DIR,
    FINAL_AGE_PATH_DIR,
    LOOPS_DIR,
    MORPH_PATH,
    RAW_FACES_DIR,
    ROOT,
    SOURCE_FACES_DIR,
    DEFAULT_FACE_PERSONA_ID,
    PersonaFaceStorage,
    ensure_persona_face_directories,
)

RAW = RAW_FACES_DIR
ALIGNED = ALIGNED_FACES_DIR
FINAL_AGE_PATH = FINAL_AGE_PATH_DIR
LOOPS = LOOPS_DIR
MORPH = MORPH_PATH
SOURCE = SOURCE_FACES_DIR

ALLOWED_SUFFIX = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 12 * 1024 * 1024
MIN_SOURCE_PHOTOS = 3
MAX_SOURCE_PHOTOS = 6

# 화면에서 고칠 수 있는 항목만 허용한다. 나머지는 코드가 관리한다.
PERSONA_FIELDS = {"display_name", "relationship_type", "elder_calls_family",
                  "family_calls_elder", "tone", "frequent_phrases",
                  "forbidden_phrases", "sensitive_policy", "active",
                  "call_style_code", "call_style_name", "call_style_scores",
                  "call_style_answers", "avatar_performance_style"}
ELDER_FIELDS = {"name", "preferred_call_name", "birth_date",
                "speech_wait_time_ms", "hearing_support", "vision_support",
                "anxiety_triggers", "calming_phrases", "frequent_questions",
                "emergency_contacts"}


def elders() -> list[dict]:
    """보호자가 돌보는 어르신 목록."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT elder_id, name, preferred_call_name, diagnosis_label, "
            "residence_type, created_at "
            "FROM elder_profiles ORDER BY created_at"
        ).fetchall()
    return [db._row(r) for r in rows]


def create_elder(name: str, call_name: str = "할아버지",
                 persona_name: str = "가족",
                 relationship: str = "손자") -> dict:
    """새 어르신과 기본 페르소나를 함께 만든다.

    페르소나 없이 어르신만 만들면 통화를 걸 대상이 없어 화면이 비어 보인다.
    """
    elder_id = f"elder_{uuid.uuid4().hex[:8]}"
    with db.connect() as conn:
        db.insert(conn, "elder_profiles", {
            "elder_id": elder_id,
            "name": name,
            "preferred_call_name": call_name,
            "speech_wait_time_ms": 2000,
            "hearing_support": 1,
            "vision_support": 0,
            "anxiety_triggers": [],
            "calming_phrases": [],
            "frequent_questions": [],
            "emergency_contacts": [],
        })
        db.insert(conn, "personas", {
            "persona_id": f"persona_{uuid.uuid4().hex[:8]}",
            "elder_id": elder_id,
            "display_name": persona_name,
            "relationship_type": relationship,
            "family_calls_elder": call_name,
            "elder_calls_family": f"우리 {persona_name}",
            "tone": "따뜻하고 편안한 반말. 서두르지 않고 천천히.",
            "frequent_phrases": [],
            "forbidden_phrases": ["왜 또 물어봐?", "아까 말했잖아."],
            "sensitive_policy": "감정 중심으로 대응하고 사실은 확정하지 않는다.",
            "active": 0,
        })
        conn.commit()
    return {"elder_id": elder_id, "name": name}


def create_persona(elder_id: str, display_name: str, relationship: str,
                   elder_calls_family: str, family_calls_elder: str) -> dict:
    """연결된 어르신에게 새 가족 프로필을 만든다.

    얼굴·목소리 승인이 끝나기 전에는 통화 대상에 나타나지 않도록 active=0으로
    시작한다. 최초 설정의 마지막 검토에서 명시적으로 활성화한다.
    """
    persona_id = f"persona_{uuid.uuid4().hex[:12]}"
    with db.connect() as conn:
        elder = conn.execute(
            "SELECT 1 FROM elder_profiles WHERE elder_id = ?", (elder_id,)
        ).fetchone()
        if elder is None:
            raise ValueError("연결할 어르신을 찾지 못했습니다.")
        db.insert(conn, "personas", {
            "persona_id": persona_id,
            "elder_id": elder_id,
            "display_name": display_name,
            "relationship_type": relationship,
            "family_calls_elder": family_calls_elder,
            "elder_calls_family": elder_calls_family,
            "tone": "따뜻하고 편안하게, 서두르지 않고 천천히 말한다.",
            "frequent_phrases": [],
            "forbidden_phrases": ["왜 또 물어봐?", "아까 말했잖아."],
            "sensitive_policy": "감정 중심으로 대응하고 확인되지 않은 사실은 단정하지 않는다.",
            "active": 0,
        })
        conn.commit()
    return profile(elder_id, persona_id)


def profile(elder_id: str = "elder_001", persona_id: str | None = None) -> dict:
    with db.connect() as conn:
        elder = conn.execute(
            "SELECT * FROM elder_profiles WHERE elder_id = ?", (elder_id,)
        ).fetchone()
        if persona_id:
            persona = conn.execute(
                "SELECT * FROM personas WHERE elder_id = ? AND persona_id = ?",
                (elder_id, persona_id),
            ).fetchone()
        else:
            persona = conn.execute(
                "SELECT * FROM personas WHERE elder_id = ? "
                "ORDER BY active DESC, created_at LIMIT 1",
                (elder_id,),
            ).fetchone()
    if elder is None:
        raise ValueError(f"{elder_id} 없음")
    return {
        "elder": db._row(elder),
        "persona": db._row(persona) if persona else None,
    }


def _patch(table: str, key: str, key_value: str, fields: dict,
           allowed: set[str]) -> None:
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not patch:
        raise ValueError("바꿀 내용이 없습니다.")
    sets = ", ".join(f"{k} = ?" for k in patch)
    values = [db._dump(v) for v in patch.values()] + [key_value]
    with db.connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", values)
        conn.commit()


def update_persona(elder_id: str, fields: dict,
                   persona_id: str | None = None) -> dict:
    with db.connect() as conn:
        if persona_id:
            row = conn.execute(
                "SELECT persona_id FROM personas "
                "WHERE elder_id = ? AND persona_id = ?",
                (elder_id, persona_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT persona_id FROM personas WHERE elder_id = ? "
                "ORDER BY active DESC, created_at LIMIT 1",
                (elder_id,),
            ).fetchone()
    if row is None:
        raise ValueError("페르소나가 없습니다.")
    _patch("personas", "persona_id", row["persona_id"], fields, PERSONA_FIELDS)
    return profile(elder_id, row["persona_id"])


def update_elder(elder_id: str, fields: dict) -> dict:
    _patch("elder_profiles", "elder_id", elder_id, fields, ELDER_FIELDS)
    return profile(elder_id)


# ------------------------------------------------------------------ 사진

def _admin_paths(persona_id: str | None = None) -> PersonaFaceStorage:
    if persona_id is not None:
        return ensure_persona_face_directories(persona_id)
    return PersonaFaceStorage(
        DEFAULT_FACE_PERSONA_ID, SOURCE.parent, SOURCE,
        SOURCE.parent / "age_candidates", SOURCE.parent / "age_anchors",
        SOURCE.parent / "age_debug", SOURCE.parent / "age_plan.json", RAW,
        ALIGNED, FINAL_AGE_PATH, LOOPS, MORPH, True,
    )


def _asset_url(persona_id: str | None, folder: str, name: str) -> str:
    paths = _admin_paths(persona_id)
    if paths.legacy:
        return {
            "source": f"/identity-faces/{name}",
            "final": f"/faces/age_path_final/{name}",
            "aligned": f"/faces/{name}",
            "morph": "/media/morph.mp4",
            "loop": f"/media/loops/{name}",
        }[folder]
    mapped = {
        "source": "source",
        "final": "aligned/age_path_final",
        "aligned": "aligned",
        "morph": "morph.mp4",
        "loop": "loops",
    }
    suffix = mapped[folder]
    if folder == "morph":
        return f"/persona-assets/{paths.persona_id}/{suffix}"
    return f"/persona-assets/{paths.persona_id}/{suffix}/{name}"


def identity_photos(persona_id: str | None = None) -> dict:
    """현재 얼굴 참조 사진과 로컬 품질검사 결과."""
    paths = _admin_paths(persona_id)
    source = paths.source
    photos = []
    for path in sorted(source.iterdir()):
        if path.suffix.lower() not in ALLOWED_SUFFIX:
            continue
        try:
            quality = face_quality.analyze_file(path)
        except (ValueError, RuntimeError) as exc:
            quality = {
                "status": "rejected",
                "usable": False,
                "score": 0,
                "issues": [{"code": "analysis", "level": "error", "message": str(exc)}],
            }
        photos.append({
            "name": path.name,
            "size_kb": path.stat().st_size // 1024,
            "url": _asset_url(persona_id, "source", path.name),
            "quality": quality,
            "recommended": False,
        })

    usable = [photo for photo in photos if photo["quality"].get("usable")]
    recommended = max(
        usable,
        key=lambda photo: (
            photo["quality"].get("status") == "good",
            photo["quality"].get("score", 0),
        ),
        default=None,
    )
    if recommended:
        recommended["recommended"] = True

    return {
        "photos": photos,
        "count": len(photos),
        "usable_count": len(usable),
        "minimum": MIN_SOURCE_PHOTOS,
        "maximum": MAX_SOURCE_PHOTOS,
        "ready": len(usable) >= MIN_SOURCE_PHOTOS,
        "recommended": recommended["name"] if recommended else None,
        "persona_id": paths.persona_id,
    }


def save_identity_photo(filename: str, data: bytes,
                        persona_id: str | None = None) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"{suffix} 형식은 올릴 수 없습니다. png, jpg, webp만 됩니다.")
    if len(data) > MAX_BYTES:
        raise ValueError("파일이 너무 큽니다. 12MB 이하로 올려주세요.")

    source = _admin_paths(persona_id).source
    current = [path for path in source.iterdir() if path.suffix.lower() in ALLOWED_SUFFIX]
    if len(current) >= MAX_SOURCE_PHOTOS:
        raise ValueError(f"사진은 최대 {MAX_SOURCE_PHOTOS}장까지 올릴 수 있습니다.")

    quality = face_quality.analyze_bytes(data)
    original = Path(filename).stem
    clean = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", original).strip(" ._")[:50]
    clean = clean or "photo"
    safe = f"{uuid.uuid4().hex[:8]}_{clean}{suffix}"
    destination = source / safe
    destination.write_bytes(data)
    return {
        "name": safe,
        "size_kb": len(data) // 1024,
        "url": _asset_url(persona_id, "source", safe),
        "quality": quality,
    }


def delete_identity_photo(name: str, persona_id: str | None = None) -> None:
    target = _admin_paths(persona_id).source / Path(name).name
    if target.exists() and target.suffix.lower() in ALLOWED_SUFFIX:
        target.unlink()


def confirm_identity_photo(name: str, persona_id: str) -> dict:
    """통화 카드와 아바타에 쓸 대표 가족 사진을 명시적으로 확정한다."""
    safe = Path(name).name
    paths = _admin_paths(persona_id)
    target = paths.source / safe
    if safe != name or not target.is_file():
        raise ValueError("확정할 가족 사진을 찾을 수 없습니다.")
    manifest = paths.root / "profile.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload["representative_photo"] = f"source/{safe}"
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"name": safe, "url": _asset_url(persona_id, "source", safe)}

def faces(persona_id: str | None = None) -> dict:
    """등록된 사진과 생성물 상태.

    raw 는 보호자가 올린 원본, aligned 는 크기와 눈높이를 맞춘 결과다.
    모핑 영상은 aligned 를 재료로 만든다.
    """
    def listing(folder: Path) -> list[dict]:
        if not folder.exists():
            return []
        return [
            {"name": p.name, "size_kb": p.stat().st_size // 1024}
            for p in sorted(folder.iterdir())
            if p.suffix.lower() in ALLOWED_SUFFIX and not p.name.startswith("_")
        ]

    paths = _admin_paths(persona_id)
    final_aligned = [
        item
        for item in listing(paths.final_age_path)
        if Path(item["name"]).suffix.lower() == ".png"
        and Path(item["name"]).stem.split("_", 1)[0].isdigit()
        and "_age" in Path(item["name"]).stem.lower()
    ]
    if final_aligned:
        aligned = [
            dict(item, url=_asset_url(persona_id, "final", item["name"]))
            for item in final_aligned
        ]
    else:
        aligned = [
            dict(item, url=_asset_url(persona_id, "aligned", item["name"]))
            for item in listing(paths.aligned)
        ]

    result = {
        "raw": listing(paths.raw),
        "aligned": aligned,
        "morph": {
            "exists": paths.morph.exists(),
            "url": _asset_url(persona_id, "morph", paths.morph.name)
            if paths.morph.exists() else None,
            "size_kb": paths.morph.stat().st_size // 1024 if paths.morph.exists() else 0,
        },
        "loops": sorted(p.stem for p in paths.loops.glob("*.mp4"))
        if paths.loops.exists() else [],
    }
    if persona_id is not None:
        result["persona_id"] = paths.persona_id
    return result


def save_face(filename: str, data: bytes, persona_id: str | None = None) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"{suffix} 형식은 올릴 수 없습니다. png, jpg, webp 만 됩니다.")
    if len(data) > MAX_BYTES:
        raise ValueError("파일이 너무 큽니다. 12MB 이하로 올려주세요.")

    raw = _admin_paths(persona_id).raw
    # 파일명이 순서를 정하므로 경로 문자는 지우되 이름은 살린다
    safe = Path(filename).name.replace("/", "_").replace("\\", "_")
    dest = raw / safe
    dest.write_bytes(data)
    return {"name": safe, "size_kb": len(data) // 1024}


def delete_face(name: str, persona_id: str | None = None) -> None:
    safe = Path(name).name
    paths = _admin_paths(persona_id)
    for folder in (paths.raw, paths.aligned):
        target = folder / safe
        if target.exists():
            target.unlink()


def prepare_faces(persona_id: str | None = None) -> dict:
    """올린 사진을 3:4 세로로 자르고 눈높이를 맞춘다.

    도구 스크립트를 그대로 호출한다. 크롭 규칙이 한 곳에만 있어야
    화면에서 만든 결과와 터미널에서 만든 결과가 달라지지 않는다.
    """
    script = ROOT / "tools" / "prep_faces.py"
    command = [sys.executable, str(script)]
    if persona_id:
        command.extend(["--persona-id", persona_id])
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    return {
        "ok": result.returncode == 0,
        "log": (result.stdout + result.stderr)[-2000:],
        "faces": faces(persona_id),
    }
