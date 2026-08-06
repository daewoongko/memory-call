"""배포 환경과 로컬 개발에서 공통으로 쓰는 저장 경로."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 로컬에서는 기존 data/를 그대로 쓰고, 배포에서는 영구 디스크 경로를 지정한다.
STORAGE_DIR = Path(
    os.getenv("STORAGE_DIR", str(ROOT / "data"))
).expanduser().resolve()

DB_PATH = STORAGE_DIR / "memory_call.sqlite"
FACES_ROOT = STORAGE_DIR / "faces"
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

SEED_PATH = ROOT / "data" / "seed.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"


def ensure_directories() -> None:
    """StaticFiles 마운트와 업로드 전에 필요한 폴더를 만든다."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_FACES_DIR.mkdir(parents=True, exist_ok=True)
    AGE_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    AGE_ANCHORS_DIR.mkdir(parents=True, exist_ok=True)
    AGE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_FACES_DIR.mkdir(parents=True, exist_ok=True)
    ALIGNED_FACES_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_AGE_PATH_DIR.mkdir(parents=True, exist_ok=True)
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
