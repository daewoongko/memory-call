"""
페르소나·프로필·사진 관리.

명세 FR-02 — 가족 페르소나는 보호자가 등록한다.
등록된 말투와 호칭이 그대로 시스템 프롬프트에 들어가고,
등록된 사진이 모핑 영상의 재료가 된다.

사진은 파일로 다루므로 여기서만 디스크를 만진다.
"""

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import db
from storage import (
    ALIGNED_FACES_DIR,
    LOOPS_DIR,
    MORPH_PATH,
    RAW_FACES_DIR,
    ROOT,
)

RAW = RAW_FACES_DIR
ALIGNED = ALIGNED_FACES_DIR
LOOPS = LOOPS_DIR
MORPH = MORPH_PATH

ALLOWED_SUFFIX = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 12 * 1024 * 1024

# 화면에서 고칠 수 있는 항목만 허용한다. 나머지는 코드가 관리한다.
PERSONA_FIELDS = {"display_name", "relationship_type", "elder_calls_family",
                  "family_calls_elder", "tone", "frequent_phrases",
                  "forbidden_phrases", "sensitive_policy", "active"}
ELDER_FIELDS = {"name", "preferred_call_name", "birth_date",
                "speech_wait_time_ms", "hearing_support", "vision_support",
                "anxiety_triggers", "calming_phrases", "frequent_questions",
                "emergency_contacts"}


def elders() -> list[dict]:
    """보호자가 돌보는 어르신 목록."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT elder_id, name, preferred_call_name, created_at "
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


def profile(elder_id: str = "elder_001") -> dict:
    with db.connect() as conn:
        elder = conn.execute(
            "SELECT * FROM elder_profiles WHERE elder_id = ?", (elder_id,)
        ).fetchone()
        persona = conn.execute(
            "SELECT * FROM personas WHERE elder_id = ? ORDER BY created_at LIMIT 1",
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


def update_persona(elder_id: str, fields: dict) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT persona_id FROM personas WHERE elder_id = ? LIMIT 1",
            (elder_id,),
        ).fetchone()
    if row is None:
        raise ValueError("페르소나가 없습니다.")
    _patch("personas", "persona_id", row["persona_id"], fields, PERSONA_FIELDS)
    return profile(elder_id)


def update_elder(elder_id: str, fields: dict) -> dict:
    _patch("elder_profiles", "elder_id", elder_id, fields, ELDER_FIELDS)
    return profile(elder_id)


# ------------------------------------------------------------------ 사진

def faces() -> dict:
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

    return {
        "raw": listing(RAW),
        "aligned": [
            dict(f, url=f"/faces/{f['name']}") for f in listing(ALIGNED)
        ],
        "morph": {
            "exists": MORPH.exists(),
            "url": "/media/morph.mp4" if MORPH.exists() else None,
            "size_kb": MORPH.stat().st_size // 1024 if MORPH.exists() else 0,
        },
        "loops": sorted(p.stem for p in LOOPS.glob("*.mp4")) if LOOPS.exists() else [],
    }


def save_face(filename: str, data: bytes) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"{suffix} 형식은 올릴 수 없습니다. png, jpg, webp 만 됩니다.")
    if len(data) > MAX_BYTES:
        raise ValueError("파일이 너무 큽니다. 12MB 이하로 올려주세요.")

    RAW.mkdir(parents=True, exist_ok=True)
    # 파일명이 순서를 정하므로 경로 문자는 지우되 이름은 살린다
    safe = Path(filename).name.replace("/", "_").replace("\\", "_")
    dest = RAW / safe
    dest.write_bytes(data)
    return {"name": safe, "size_kb": len(data) // 1024}


def delete_face(name: str) -> None:
    safe = Path(name).name
    for folder in (RAW, ALIGNED):
        target = folder / safe
        if target.exists():
            target.unlink()


def prepare_faces() -> dict:
    """올린 사진을 3:4 세로로 자르고 눈높이를 맞춘다.

    도구 스크립트를 그대로 호출한다. 크롭 규칙이 한 곳에만 있어야
    화면에서 만든 결과와 터미널에서 만든 결과가 달라지지 않는다.
    """
    script = ROOT / "tools" / "prep_faces.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT
    )
    return {
        "ok": result.returncode == 0,
        "log": (result.stdout + result.stderr)[-2000:],
        "faces": faces(),
    }


def reset_faces() -> None:
    for folder in (RAW, ALIGNED):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
