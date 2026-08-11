"""배포 환경과 로컬 개발에서 공통으로 쓰는 저장 경로."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 로컬에서는 기존 data/를 그대로 쓰고, 배포에서는 영구 디스크 경로를 지정한다.
STORAGE_DIR = Path(
    os.getenv("STORAGE_DIR", str(ROOT / "data"))
).expanduser().resolve()

DB_PATH = STORAGE_DIR / "memory_call.sqlite"
PERSONAS_ROOT = STORAGE_DIR / "personas"
DEFAULT_FACE_PERSONA_ID = "persona_daewoong"
LEGACY_FACES_ROOT = STORAGE_DIR / "faces"

# 기존 생성 도구들은 저장 경로 상수를 직접 import한다. 도구 실행 시에만
# FACE_PERSONA_ID를 주면 코드를 복제하지 않고도 해당 가족 폴더를 사용한다.
TOOL_FACE_PERSONA_ID = os.getenv("FACE_PERSONA_ID", "").strip()
if TOOL_FACE_PERSONA_ID and not re.fullmatch(r"persona_[a-z0-9_]+", TOOL_FACE_PERSONA_ID):
    raise ValueError("FACE_PERSONA_ID 형식이 올바르지 않습니다.")
FACES_ROOT = (
    PERSONAS_ROOT / TOOL_FACE_PERSONA_ID
    if TOOL_FACE_PERSONA_ID
    and TOOL_FACE_PERSONA_ID not in {DEFAULT_FACE_PERSONA_ID, "persona_minjun"}
    else LEGACY_FACES_ROOT
)
SOURCE_FACES_DIR = FACES_ROOT / "source"
AGE_CANDIDATES_DIR = FACES_ROOT / "age_candidates"
AGE_ANCHORS_DIR = FACES_ROOT / "age_anchors"
AGE_DEBUG_DIR = FACES_ROOT / "age_debug"
AGE_PLAN_PATH = FACES_ROOT / "age_plan.json"
RAW_FACES_DIR = FACES_ROOT / "raw"
ALIGNED_FACES_DIR = FACES_ROOT / "aligned"
FINAL_AGE_PATH_DIR = ALIGNED_FACES_DIR / "age_path_final"
LOOPS_DIR = FACES_ROOT / "loops"
MORPH_PATH = FACES_ROOT / "morph.mp4"


@dataclass(frozen=True)
class PersonaFaceStorage:
    persona_id: str
    root: Path
    source: Path
    age_candidates: Path
    age_anchors: Path
    age_debug: Path
    age_plan: Path
    raw: Path
    aligned: Path
    final_age_path: Path
    loops: Path
    morph: Path
    legacy: bool = False


def persona_face_storage(persona_id: str | None = None) -> PersonaFaceStorage:
    """한 가족의 얼굴 생성물을 다른 가족과 섞이지 않게 분리한다.

    민준은 이미 완성된 전역 ``data/faces`` 자산과 통화 기록이 있으므로
    기존 ID를 그대로 해당 폴더에 연결한다.
    """
    selected = persona_id or DEFAULT_FACE_PERSONA_ID
    if selected in {DEFAULT_FACE_PERSONA_ID, "persona_minjun"}:
        root = LEGACY_FACES_ROOT
        aligned = root / "aligned"
        return PersonaFaceStorage(
            selected, root, root / "source", root / "age_candidates",
            root / "age_anchors", root / "age_debug", root / "age_plan.json",
            root / "raw", aligned, aligned / "age_path_final", root / "loops",
            root / "morph.mp4", True,
        )
    if not re.fullmatch(r"persona_[a-z0-9_]+", selected):
        raise ValueError("올바르지 않은 페르소나 ID입니다.")
    root = PERSONAS_ROOT / selected
    aligned = root / "aligned"
    return PersonaFaceStorage(
        selected, root, root / "source", root / "age_candidates",
        root / "age_anchors", root / "age_debug", root / "age_plan.json",
        root / "raw", aligned, aligned / "age_path_final", root / "loops",
        root / "morph.mp4", False,
    )


def ensure_persona_face_directories(persona_id: str | None = None) -> PersonaFaceStorage:
    paths = persona_face_storage(persona_id)
    for folder in (
        paths.root, paths.source, paths.age_candidates, paths.age_anchors,
        paths.age_debug, paths.raw, paths.aligned, paths.final_age_path,
        paths.loops,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    return paths

SEED_PATH = ROOT / "data" / "seed.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"


def ensure_directories() -> None:
    """StaticFiles 마운트와 업로드 전에 필요한 폴더를 만든다."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    PERSONAS_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_FACES_DIR.mkdir(parents=True, exist_ok=True)
    AGE_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    AGE_ANCHORS_DIR.mkdir(parents=True, exist_ok=True)
    AGE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_FACES_DIR.mkdir(parents=True, exist_ok=True)
    ALIGNED_FACES_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_AGE_PATH_DIR.mkdir(parents=True, exist_ok=True)
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
