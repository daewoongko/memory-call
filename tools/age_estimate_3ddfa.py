"""Extract pose-normalized 3D facial structure with official 3DDFA-V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--repo-revision", default="unknown")
    return parser.parse_args()


def read_bgr(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distance(points: np.ndarray, first: int, second: int) -> float:
    return float(np.linalg.norm(points[:, first] - points[:, second]))


def normalized_shape_landmarks(tddfa, alpha_shape: np.ndarray) -> np.ndarray:
    """Return shape-only landmarks without camera pose or facial expression."""
    points = (
        tddfa.bfm.u_base + tddfa.bfm.w_shp_base @ alpha_shape
    ).reshape(3, -1, order="F")
    left_eye = points[:, 36:42].mean(axis=1)
    right_eye = points[:, 42:48].mean(axis=1)
    center = (left_eye + right_eye) / 2.0
    scale = float(np.linalg.norm(left_eye - right_eye))
    if scale <= 1e-6:
        raise ValueError("3DDFA returned a degenerate inter-eye scale")
    return (points - center[:, None]) / scale


def structural_metrics(points: np.ndarray) -> dict[str, float]:
    face_width = distance(points, 0, 16)
    upper_to_chin = distance(points, 27, 8)
    if face_width <= 1e-6 or upper_to_chin <= 1e-6:
        raise ValueError("3DDFA returned degenerate canonical landmarks")
    return {
        "face_width_height": round(face_width / upper_to_chin, 5),
        "jaw_width_ratio": round(distance(points, 4, 12) / face_width, 5),
        "lower_face_ratio": round(distance(points, 33, 8) / upper_to_chin, 5),
        "midface_ratio": round(distance(points, 27, 33) / upper_to_chin, 5),
        "mouth_width_ratio": round(distance(points, 48, 54) / face_width, 5),
        "nose_width_ratio": round(distance(points, 31, 35) / face_width, 5),
    }


def main() -> None:
    args = parse_args()
    if not args.repo.is_dir():
        raise FileNotFoundError(f"3DDFA-V2 repository not found: {args.repo}")
    sys.path.insert(0, str(args.repo.resolve()))

    # 3DDFA-V2 predates NumPy 1.24 and uses the removed np.long alias.
    if "long" not in np.__dict__:
        np.long = np.int64  # type: ignore[attr-defined]

    from TDDFA import TDDFA
    from utils.pose import calc_pose
    from utils.tddfa_util import _parse_param

    config_path = args.repo / "configs" / "mb1_120x120.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for name in ("checkpoint_fp", "bfm_fp"):
        config[name] = str((args.repo / config[name]).resolve())
    model = TDDFA(gpu_mode=False, **config)

    request = json.loads(args.request.read_text(encoding="utf-8"))
    entries = request.get("entries") or []
    if not entries:
        raise ValueError("3DDFA request has no entries")

    rows = []
    for entry in entries:
        image = read_bgr(Path(entry["path"]))
        bbox = np.asarray(entry["bbox"], dtype=np.float32)
        param_list, roi_list = model(image, [bbox])
        param = param_list[0]
        _, _, alpha_shape, alpha_expression = _parse_param(param)
        points = normalized_shape_landmarks(model, alpha_shape)
        _, pose = calc_pose(param)
        rows.append(
            {
                "id": str(entry["id"]),
                "path": str(Path(entry["path"]).resolve()),
                "bbox": [round(float(value), 3) for value in bbox],
                "roi_box": [round(float(value), 3) for value in roi_list[0]],
                "pose_degrees": {
                    "yaw": round(float(pose[0]), 2),
                    "pitch": round(float(pose[1]), 2),
                    "roll": round(float(pose[2]), 2),
                },
                "shape_coefficients": [
                    round(float(value), 6) for value in alpha_shape.flatten()
                ],
                "expression_coefficient_l2": round(
                    float(np.linalg.norm(alpha_expression)), 5
                ),
                "pose_normalized_metrics": structural_metrics(points),
                "normalized_landmark_sha256": hashlib.sha256(
                    points.astype(np.float32).tobytes()
                ).hexdigest(),
            }
        )

    checkpoint = Path(config["checkpoint_fp"])
    bfm = Path(config["bfm_fp"])
    output = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "available",
        "model": {
            "name": "3DDFA-V2 MobileNet V1 120x120",
            "repository": "https://github.com/cleardusk/3DDFA_V2",
            "repository_revision": args.repo_revision,
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": sha256(checkpoint),
            "bfm": str(bfm),
            "bfm_sha256": sha256(bfm),
            "device": "cpu",
            "torch_version": torch.__version__,
            "shape_dimensions": 40,
            "expression_dimensions": 10,
        },
        "pose_normalization": (
            "3DMM shape coefficients and canonical 68 landmarks exclude camera "
            "rotation, translation, scale, and expression"
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
