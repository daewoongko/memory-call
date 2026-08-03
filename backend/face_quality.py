"""사용자가 올린 얼굴 사진이 나이 변환 입력으로 적합한지 검사한다."""

from __future__ import annotations

import io
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"
MAX_PIXELS = 40_000_000
DETECTION_MAX_EDGE = 1280


def _issue(code: str, level: str, message: str) -> dict:
    return {"code": code, "level": level, "message": message}


def _decode(data: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise ValueError("사진 해상도가 너무 큽니다. 4천만 픽셀 이하로 올려주세요.")
            rgb = np.asarray(image.convert("RGB"))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("읽을 수 있는 이미지가 아닙니다.") from exc
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _detect(image: np.ndarray) -> tuple[np.ndarray, float]:
    if not MODEL_PATH.is_file():
        raise RuntimeError(f"YuNet 모델을 찾을 수 없습니다: {MODEL_PATH}")

    height, width = image.shape[:2]
    scale = min(1.0, DETECTION_MAX_EDGE / max(width, height))
    if scale < 1.0:
        detected = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        detected = image

    dh, dw = detected.shape[:2]
    try:
        detector = cv2.FaceDetectorYN.create(
            str(MODEL_PATH),
            "",
            (dw, dh),
            score_threshold=0.72,
            nms_threshold=0.3,
            top_k=100,
        )
        _, faces = detector.detect(detected)
    except cv2.error as exc:
        raise RuntimeError("얼굴 검사 모델을 실행하지 못했습니다.") from exc
    if faces is None:
        return np.empty((0, 15), dtype=np.float32), scale
    return faces, scale


def analyze_bytes(data: bytes) -> dict:
    image = _decode(data)
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    metric_scale = min(1.0, 1024 / max(width, height))
    metric_gray = (
        cv2.resize(
            gray,
            (max(1, round(width * metric_scale)), max(1, round(height * metric_scale))),
            interpolation=cv2.INTER_AREA,
        )
        if metric_scale < 1.0
        else gray
    )
    brightness = float(metric_gray.mean())
    contrast = float(metric_gray.std())
    sharpness = float(cv2.Laplacian(metric_gray, cv2.CV_64F).var())
    faces, detection_scale = _detect(image)

    issues: list[dict] = []
    score = 100
    short_edge = min(width, height)
    if short_edge < 320:
        issues.append(_issue("resolution", "error", "사진이 너무 작습니다. 가로·세로 모두 320px 이상이어야 해요."))
        score -= 45
    elif short_edge < 720:
        issues.append(_issue("resolution", "warning", "조금 더 선명한 사진을 권장해요. 짧은 변이 720px 이상이면 좋아요."))
        score -= 12

    if brightness < 45:
        issues.append(_issue("brightness", "warning", "얼굴이 너무 어둡습니다. 밝은 곳에서 찍은 사진이 좋아요."))
        score -= 15
    elif brightness > 215:
        issues.append(_issue("brightness", "warning", "사진이 너무 밝아 얼굴 윤곽이 약합니다."))
        score -= 12
    if contrast < 24:
        issues.append(_issue("contrast", "warning", "명암 차이가 작아 얼굴 특징이 흐립니다."))
        score -= 10
    if sharpness < 45:
        issues.append(_issue("sharpness", "error", "초점이 많이 흐립니다. 흔들리지 않은 사진을 골라주세요."))
        score -= 35
    elif sharpness < 90:
        issues.append(_issue("sharpness", "warning", "사진이 조금 흐립니다. 더 선명한 사진이 있으면 바꿔주세요."))
        score -= 12

    face_count = len(faces)
    face_metrics = None
    if face_count == 0:
        issues.append(_issue("face_count", "error", "얼굴을 찾지 못했습니다. 정면에 가까운 사진을 골라주세요."))
        score -= 60
    elif face_count > 1:
        issues.append(_issue("face_count", "error", "얼굴이 여러 명입니다. 한 사람만 나온 사진을 골라주세요."))
        score -= 60
    else:
        face = faces[0]
        x, y, fw, fh = (float(value) / detection_scale for value in face[:4])
        points = np.asarray(face[4:14], dtype=float).reshape(5, 2) / detection_scale
        eye_a, eye_b, nose = points[0], points[1], points[2]
        left_eye, right_eye = sorted((eye_a, eye_b), key=lambda point: point[0])
        eye_span = max(float(right_eye[0] - left_eye[0]), 1.0)
        roll = abs(math.degrees(math.atan2(
            float(right_eye[1] - left_eye[1]),
            float(right_eye[0] - left_eye[0]),
        )))
        nose_ratio = float((nose[0] - left_eye[0]) / eye_span)
        face_ratio = float((fw * fh) / (width * height))
        center_x = (x + fw / 2) / width
        center_y = (y + fh / 2) / height
        center_offset = math.hypot(center_x - 0.5, center_y - 0.47)
        confidence = float(face[14])

        if face_ratio < 0.035:
            issues.append(_issue("face_size", "error", "얼굴이 너무 작습니다. 얼굴이 크게 나온 사진을 골라주세요."))
            score -= 35
        elif face_ratio < 0.09:
            issues.append(_issue("face_size", "warning", "얼굴이 조금 작습니다. 상반신보다 얼굴 중심 사진이 좋아요."))
            score -= 12
        elif face_ratio > 0.60:
            issues.append(_issue("face_size", "warning", "얼굴이 화면에 너무 꽉 찼습니다. 머리 전체가 보이는 사진이 좋아요."))
            score -= 8
        if roll > 20:
            issues.append(_issue("roll", "error", "고개가 많이 기울어져 있습니다. 수평에 가까운 사진을 골라주세요."))
            score -= 25
        elif roll > 12:
            issues.append(_issue("roll", "warning", "고개가 조금 기울어져 있습니다."))
            score -= 8
        if not 0.20 <= nose_ratio <= 0.80:
            issues.append(_issue("pose", "warning", "얼굴이 옆을 많이 보고 있습니다. 정면 사진도 함께 올려주세요."))
            score -= 12
        if center_offset > 0.30:
            issues.append(_issue("center", "warning", "얼굴이 사진 가장자리에 있습니다. 중앙에 가까운 사진이 좋아요."))
            score -= 8

        face_metrics = {
            "confidence": round(confidence, 3),
            "area_ratio": round(face_ratio, 3),
            "roll_degrees": round(roll, 1),
            "center_offset": round(center_offset, 3),
        }

    has_error = any(item["level"] == "error" for item in issues)
    status = "rejected" if has_error else ("warning" if issues else "good")
    return {
        "status": status,
        "usable": not has_error,
        "score": max(0, min(100, round(score))),
        "width": width,
        "height": height,
        "face_count": face_count,
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "sharpness": round(sharpness, 1),
        "face": face_metrics,
        "issues": issues,
    }


def analyze_file(path: Path) -> dict:
    return analyze_bytes(path.read_bytes())
