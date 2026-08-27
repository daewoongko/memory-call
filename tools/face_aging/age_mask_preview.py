"""현재 원본에서 나이 변환을 허용할 머리·얼굴 영역을 미리 본다.

YuNet 얼굴 검출과 GrabCut 전경 분리를 결합해 실제 머리 윤곽을 찾는다.
흰색 마스크만 AI가 바꿀 수 있고 검은색 영역은 원본을 그대로 보존한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[0]
# 이 파일은 저장소 안 어느 깊이로 옮겨져도 실행될 수 있어야 한다.
# 한 단계만 올라가면 폴더를 하나 더 만드는 순간 backend 를 놓친다.
while not (ROOT / "backend").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "backend"))

import age_timeline  # noqa: E402
from storage import SOURCE_FACES_DIR  # noqa: E402


MODEL_PATH = ROOT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"
OUTPUT_DIR = ROOT / "data" / "faces" / "age_mask"


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise RuntimeError(f"이미지를 저장하지 못했습니다: {path}")
    encoded.tofile(path)


def detect_face(image: np.ndarray) -> np.ndarray:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"얼굴 검출 모델이 없습니다: {MODEL_PATH}")
    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(MODEL_PATH), "", (width, height),
        score_threshold=0.72, nms_threshold=0.3, top_k=20,
    )
    _, faces = detector.detect(image)
    if faces is None or len(faces) != 1:
        count = 0 if faces is None else len(faces)
        raise ValueError(f"현재 기준 사진에서 얼굴이 정확히 1명이어야 합니다: {count}명")
    return faces[0]


def component_at(mask: np.ndarray, point: tuple[int, int]) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask
    px = min(max(point[0], 0), mask.shape[1] - 1)
    py = min(max(point[1], 0), mask.shape[0] - 1)
    label = int(labels[py, px])
    if label == 0:
        label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == label, 255, 0).astype(np.uint8)


def make_mask(image: np.ndarray, face: np.ndarray) -> tuple[np.ndarray, dict]:
    """GrabCut으로 실제 머리 윤곽을 찾고 목까지만 남긴다."""
    height, width = image.shape[:2]
    x, y, face_width, face_height = [float(value) for value in face[:4]]

    center_x = round(x + face_width * 0.50)
    face_center = (center_x, round(y + face_height * 0.53))
    head_center = (center_x, round(y + face_height * 0.24))
    head_axes = (round(face_width * 0.75), round(face_height * 0.90))
    neck_top = round(y + face_height * 0.68)
    neck_bottom = min(height - 1, round(y + face_height * 1.35))
    neck_top_half = round(face_width * 0.40)
    neck_bottom_half = round(face_width * 0.60)
    neck_points = np.array(
        [
            [center_x - neck_top_half, neck_top],
            [center_x + neck_top_half, neck_top],
            [center_x + neck_bottom_half, neck_bottom],
            [center_x - neck_bottom_half, neck_bottom],
        ],
        dtype=np.int32,
    )

    # 넓은 타원은 탐색 범위일 뿐 최종 마스크가 아니다.
    gate = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(gate, head_center, head_axes, 0, 0, 360, 255, thickness=-1)
    cv2.fillConvexPoly(gate, neck_points, 255)

    grab = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    grab[gate > 0] = cv2.GC_PR_FGD

    # 얼굴 안쪽은 확실한 전경으로 지정한다.
    core = np.zeros((height, width), dtype=np.uint8)
    core_center = (center_x, round(y + face_height * 0.52))
    core_axes = (round(face_width * 0.43), round(face_height * 0.48))
    cv2.ellipse(core, core_center, core_axes, 0, 0, 360, 255, thickness=-1)
    grab[core > 0] = cv2.GC_FGD

    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(
        image, grab, None, background_model, foreground_model,
        6, cv2.GC_INIT_WITH_MASK,
    )
    foreground = np.where(
        (grab == cv2.GC_FGD) | (grab == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    foreground = cv2.bitwise_and(foreground, gate)
    foreground = component_at(foreground, face_center)
    foreground = cv2.bitwise_or(foreground, core)

    # GrabCut follows the head well, but a narrow geometric neck can leave
    # current-age skin on both sides.  Extend only pixels whose chroma matches
    # the person's cheek skin.  The wide polygon is merely a search area, so
    # the grey background and dark sweater remain protected.
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    skin_sample = np.zeros((height, width), dtype=np.uint8)
    sample_center = (center_x, round(y + face_height * 0.58))
    sample_axes = (round(face_width * 0.29), round(face_height * 0.25))
    cv2.ellipse(
        skin_sample, sample_center, sample_axes, 0, 0, 360, 255, thickness=-1
    )
    sample_values = ycrcb[skin_sample > 0, 1:3].astype(np.float32)
    skin_chroma = np.median(sample_values, axis=0)
    chroma_delta = ycrcb[:, :, 1:3].astype(np.float32) - skin_chroma
    chroma_distance = np.sqrt(np.sum(chroma_delta * chroma_delta, axis=2))
    neck_skin = np.where(chroma_distance <= 24.0, 255, 0).astype(np.uint8)

    neck_search = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(neck_search, neck_points, 255)
    neck_skin = cv2.bitwise_and(neck_skin, neck_search)
    neck_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    neck_skin = cv2.morphologyEx(neck_skin, cv2.MORPH_CLOSE, neck_kernel)
    neck_skin = component_at(
        neck_skin, (center_x, round(y + face_height * 0.94))
    )
    foreground = cv2.bitwise_or(foreground, neck_skin)

    close_size = max(7, round(min(face_width, face_height) * 0.025))
    if close_size % 2 == 0:
        close_size += 1
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (close_size, close_size)
    )
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, close_kernel)

    contours, _ = cv2.findContours(
        foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    hard_mask = np.zeros_like(foreground)
    cv2.drawContours(hard_mask, contours, -1, 255, thickness=-1)
    hard_mask = cv2.bitwise_and(hard_mask, gate)

    feather_kernel = max(7, round(min(face_width, face_height) * 0.022))
    if feather_kernel % 2 == 0:
        feather_kernel += 1
    feathered = cv2.GaussianBlur(
        hard_mask, (feather_kernel, feather_kernel), 0
    )

    metadata = {
        "face_box": [round(x), round(y), round(face_width), round(face_height)],
        "method": "yunet-grabcut-head-skin-neck",
        "head_center": list(head_center),
        "head_axes": list(head_axes),
        "neck_bottom": neck_bottom,
        "skin_chroma_ycrcb": [
            round(float(skin_chroma[0]), 2),
            round(float(skin_chroma[1]), 2),
        ],
        "skin_chroma_tolerance": 24.0,
        "feather_kernel": feather_kernel,
        "coverage_percent": round(float(np.mean(hard_mask > 0) * 100), 2),
    }
    return feathered, metadata


def make_preview(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    preview = image.astype(np.float32)
    tint = np.zeros_like(preview)
    tint[:, :, 1] = 185
    tint[:, :, 2] = 255
    alpha = (mask.astype(np.float32) / 255.0 * 0.42)[:, :, None]
    preview = preview * (1.0 - alpha) + tint * alpha
    hard = np.where(mask >= 128, 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(hard, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(preview, contours, -1, (40, 220, 255), 5)
    return np.clip(preview, 0, 255).astype(np.uint8)


def main() -> None:
    plan = age_timeline.get_plan()
    if not plan["configured"]:
        raise RuntimeError("현재 나이와 현재 기준 사진을 먼저 저장해 주세요.")
    source = SOURCE_FACES_DIR / plan["current_photo"]
    image = read_image(source)
    face = detect_face(image)
    mask, metadata = make_mask(image, face)
    preview = make_preview(image, mask)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mask_path = OUTPUT_DIR / "current_change_mask.png"
    preview_path = OUTPUT_DIR / "current_mask_preview.png"
    metadata_path = OUTPUT_DIR / "current_mask.json"
    write_image(mask_path, mask)
    write_image(preview_path, preview)
    metadata_path.write_text(
        json.dumps(
            {"current_age": plan["current_age"], "source": source.name, **metadata},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"현재 원본: {source}")
    print(f"마스크: {mask_path}")
    print(f"미리보기: {preview_path}")
    print(f"변경 가능 영역: {metadata['coverage_percent']}%")
    print("노란 영역만 변경하고 나머지 옷·배경은 현재 원본을 유지합니다.")


if __name__ == "__main__":
    main()
