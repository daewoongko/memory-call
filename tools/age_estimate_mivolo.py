"""Run the official face-only MiVOLO age model in its isolated environment.

The caller supplies InsightFace face boxes.  MiVOLO remains an independent age
estimator: the primary detector is reused only to make deterministic face crops.
This checkpoint is age-only, so no gender inference is performed.
"""

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


VIEW_COUNT = 5
REPORTED_MAE_YEARS = 4.29
REPORTED_CS_AT_5 = 0.6771


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--repo-revision", default="unknown")
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args()


def read_bgr(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def expanded_square_crop(
    image: np.ndarray, bbox: list[float], scale: float = 1.35
) -> np.ndarray:
    """Crop the whole face with symmetric context while preserving image pixels."""
    if len(bbox) != 4:
        raise ValueError("bbox must contain x1, y1, x2, y2")
    x1, y1, x2, y2 = (float(value) for value in bbox)
    width, height = x2 - x1, y2 - y1
    if width <= 1 or height <= 1:
        raise ValueError(f"Invalid face bbox: {bbox}")

    center_x = (x1 + x2) / 2.0
    # Keep slightly more forehead than lower background.
    center_y = (y1 + y2) / 2.0 - height * 0.04
    side = max(width, height) * scale
    left = int(np.floor(center_x - side / 2.0))
    top = int(np.floor(center_y - side / 2.0))
    right = int(np.ceil(center_x + side / 2.0))
    bottom = int(np.ceil(center_y + side / 2.0))

    image_height, image_width = image.shape[:2]
    pad_left, pad_top = max(0, -left), max(0, -top)
    pad_right, pad_bottom = max(0, right - image_width), max(0, bottom - image_height)
    if pad_left or pad_top or pad_right or pad_bottom:
        image = cv2.copyMakeBorder(
            image,
            pad_top,
            pad_bottom,
            pad_left,
            pad_right,
            cv2.BORDER_REFLECT_101,
        )
        left += pad_left
        right += pad_left
        top += pad_top
        bottom += pad_top
    return np.ascontiguousarray(image[top:bottom, left:right])


def age_views(crop: np.ndarray) -> list[np.ndarray]:
    """Five correlated test-time views used only as a stability screen."""
    return [
        np.ascontiguousarray(crop),
        np.ascontiguousarray(np.flip(crop, axis=1)),
        cv2.convertScaleAbs(crop, alpha=0.96, beta=0),
        cv2.convertScaleAbs(crop, alpha=1.04, beta=0),
        cv2.convertScaleAbs(crop, alpha=1.0, beta=4),
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_normalized_ages(model, images: list[np.ndarray], batch_size: int) -> list[float]:
    from mivolo.data.misc import prepare_classification_images

    ages: list[float] = []
    for start in range(0, len(images), batch_size):
        chunk = images[start : start + batch_size]
        model_input = prepare_classification_images(
            chunk,
            model.input_size,
            model.data_config["mean"],
            model.data_config["std"],
            device=model.device,
        )
        output = model.inference(model_input)
        normalized = output.reshape(output.shape[0], -1)[:, 0]
        denormalized = (
            normalized * (model.meta.max_age - model.meta.min_age)
            + model.meta.avg_age
        )
        ages.extend(float(value) for value in denormalized.cpu().tolist())
    return ages


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")
    if not args.repo.is_dir():
        raise FileNotFoundError(f"MiVOLO repository not found: {args.repo}")
    if not args.checkpoint.is_file():
        raise FileNotFoundError(f"MiVOLO checkpoint not found: {args.checkpoint}")

    sys.path.insert(0, str(args.repo.resolve()))
    from mivolo.model.mi_volo import MiVOLO

    request = json.loads(args.request.read_text(encoding="utf-8"))
    entries = request.get("entries") or []
    if not entries:
        raise ValueError("MiVOLO request has no entries")

    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    model = MiVOLO(
        str(args.checkpoint.resolve()),
        device="cpu",
        half=False,
        disable_faces=False,
        use_persons=False,
        verbose=False,
    )
    if not model.meta.only_age or model.meta.with_persons_model:
        raise ValueError("Expected the official face-only, age-only MiVOLO checkpoint")

    all_views: list[np.ndarray] = []
    for entry in entries:
        crop = expanded_square_crop(
            read_bgr(Path(entry["path"])),
            entry["bbox"],
        )
        all_views.extend(age_views(crop))

    raw_ages = infer_normalized_ages(model, all_views, args.batch_size)
    if len(raw_ages) != len(entries) * VIEW_COUNT:
        raise RuntimeError("MiVOLO returned an unexpected number of predictions")

    rows = []
    for index, entry in enumerate(entries):
        start = index * VIEW_COUNT
        estimates = [round(value, 2) for value in raw_ages[start : start + VIEW_COUNT]]
        rows.append(
            {
                "id": str(entry["id"]),
                "path": str(Path(entry["path"]).resolve()),
                "estimates": estimates,
            }
        )

    output = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "available",
        "model": {
            "name": "MiVOLO volo_d1 face-only age-only",
            "repository": "https://github.com/WildChlamydia/MiVOLO",
            "repository_revision": args.repo_revision,
            "checkpoint": str(args.checkpoint.resolve()),
            "checkpoint_sha256": sha256(args.checkpoint),
            "checkpoint_reported_dataset": "IMDB-cleaned",
            "checkpoint_reported_mae_years": REPORTED_MAE_YEARS,
            "checkpoint_reported_cs_at_5": REPORTED_CS_AT_5,
            "gender_inference_enabled": False,
            "body_input_enabled": False,
            "device": "cpu",
            "torch_version": torch.__version__,
        },
        "view_count": VIEW_COUNT,
        "uncertainty_kind": "test_time_view_stability_not_calibrated_confidence",
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
