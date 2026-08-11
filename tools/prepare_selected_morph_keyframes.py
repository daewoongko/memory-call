"""Prepare the approved age path as globally aligned morph keyframes.

The transform is deliberately limited to rotation, uniform scale, and
translation.  It aligns the eye line/camera framing without warping the
age-related internal face proportions that the generators produced.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from storage import (  # noqa: E402
    AGE_CANDIDATES_DIR,
    AGE_PLAN_PATH,
    ALIGNED_FACES_DIR,
    SOURCE_FACES_DIR,
)
from age_policy import path_with_refinements  # noqa: E402


MODEL_PATH = ROOT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 1024


def repository_path(path: Path) -> str:
    """Return a portable repository-relative path when possible."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def read_plan() -> dict:
    if not AGE_PLAN_PATH.is_file():
        raise FileNotFoundError(f"Missing age plan: {AGE_PLAN_PATH}")
    plan = json.loads(AGE_PLAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(plan.get("current_age"), int):
        raise ValueError("The age plan has no current age.")
    if not isinstance(plan.get("selections"), dict):
        raise ValueError("The age plan has no approved selections.")
    return plan


def selected_sources(plan: dict) -> list[tuple[int, Path]]:
    current_age = int(plan["current_age"])
    current_name = Path(str(plan.get("current_photo", ""))).name
    current_path = SOURCE_FACES_DIR / current_name
    if not current_name or not current_path.is_file():
        raise FileNotFoundError(f"Missing current photo: {current_path}")

    entries: list[tuple[int, Path]] = []
    if plan.get("path_mode") == "selected":
        selected_ages = {int(age) for age in plan["selections"]}
        if any(age >= current_age or age < 1 for age in selected_ages):
            raise ValueError("Selected ages must be younger than the current age.")
        descending = [current_age, *sorted(selected_ages, reverse=True)]
    else:
        descending = path_with_refinements(current_age, plan.get("extra_ages") or [])
    for age in reversed(descending):
        if age == current_age:
            entries.append((age, current_path))
            continue
        filename = plan["selections"].get(str(age))
        if not filename:
            raise ValueError(f"The planned age {age} has no approved selection.")
        safe_name = Path(str(filename)).name
        path = AGE_CANDIDATES_DIR / safe_name
        if safe_name != filename or path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsafe selected candidate path for age {age}: {filename}")
        if not path.is_file():
            raise FileNotFoundError(f"Missing selected candidate for age {age}: {path}")
        entries.append((age, path))

    ages = [age for age, _ in entries]
    if len(ages) != len(set(ages)):
        raise ValueError("The selected path contains duplicate ages.")
    return entries


def _smoothstep(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def measure_dark_sweater(image: np.ndarray, nose_x: float) -> dict | None:
    """Measure the navy sweater boundary used by this portrait pipeline."""
    height, width = image.shape[:2]
    start_y = round(height * 540 / 1024)
    end_y = min(height, round(height * 920 / 1024))
    value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
    yy = np.indices(value.shape)[0]
    mask = ((value < 105) & (yy >= start_y)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    boundary = np.full(width, np.nan, dtype=np.float64)
    kernel = np.ones(12, dtype=np.int16)
    for x in range(width):
        run = np.convolve(mask[start_y:end_y, x].astype(np.int16), kernel, mode="valid")
        hits = np.flatnonzero(run >= 10)
        if len(hits):
            boundary[x] = start_y + int(hits[0])

    center_start = round(width * 280 / 768)
    center_end = round(width * 488 / 768)
    center_x = np.arange(center_start, center_end)
    center_y = boundary[center_start:center_end]
    finite = np.isfinite(center_y)
    if finite.sum() < round(width * 120 / 768):
        return None
    percentile = np.nanpercentile(center_y, 35)
    keep = finite & (center_y > percentile)
    if keep.sum() < 30:
        return None
    quadratic, linear, constant = np.polyfit(center_x[keep], center_y[keep], 2)
    if quadratic >= -1e-4:
        return None
    collar_x = float(-linear / (2 * quadratic))
    if not width * 300 / 768 <= collar_x <= width * 468 / 768:
        return None
    collar_apex = float(np.polyval([quadratic, linear, constant], collar_x))

    shoulder_offset = width * 280 / 768

    def robust_boundary(x_value: float) -> float | None:
        center = int(round(x_value))
        left = max(0, center - 6)
        right = min(width, center + 7)
        values = boundary[left:right]
        values = values[np.isfinite(values)]
        return float(np.median(values)) if len(values) else None

    shoulder_left = robust_boundary(collar_x - shoulder_offset)
    shoulder_right = robust_boundary(collar_x + shoulder_offset)
    if shoulder_left is None or shoulder_right is None:
        return None
    return {
        "collar_x": collar_x,
        "collar_apex": collar_apex,
        "shoulder_left": shoulder_left,
        "shoulder_right": shoulder_right,
        "shoulder_mean": (shoulder_left + shoulder_right) / 2.0,
        "shoulder_delta": shoulder_left - shoulder_right,
        "collar_nose_offset": collar_x - float(nose_x),
    }


def interpolate_torso_metrics(young: dict, old: dict, fraction: float) -> dict:
    keys = ("collar_apex", "shoulder_mean", "shoulder_delta", "collar_nose_offset")
    return {
        key: float(young[key] + fraction * (old[key] - young[key]))
        for key in keys
    }


def remap_torso(
    image: np.ndarray,
    current: dict,
    target: dict,
    *,
    damping: float = 1.0,
) -> tuple[np.ndarray, dict]:
    """Apply a face-safe lower-canvas remap toward monotonic torso metrics."""
    height, width = image.shape[:2]
    y_grid, x_grid = np.mgrid[0:height, 0:width].astype(np.float32)
    transition_start = height * 620 / 1024
    transition_size = max(height * 80 / 1024, 1.0)
    gate = _smoothstep((y_grid - transition_start) / transition_size)

    dx_body = float(
        np.clip(target["collar_nose_offset"] - current["collar_nose_offset"], -12, 12)
        * damping
    )
    dy_body = float(
        np.clip(target["shoulder_mean"] - current["shoulder_mean"], -32, 32)
        * damping
    )
    delta_change = float(
        np.clip(target["shoulder_delta"] - current["shoulder_delta"], -24, 24)
        * damping
    )
    desired_collar_shift = target["collar_apex"] - current["collar_apex"]
    collar_residual = float(
        np.clip(desired_collar_shift - dy_body, -28, 28) * damping
    )

    shoulder_radius = max(width * 280 / 768, 1.0)
    horizontal = np.clip((x_grid - current["collar_x"]) / shoulder_radius, -1.0, 1.0)
    tilt_shift = -(delta_change / 2.0) * horizontal
    collar_weight = np.exp(
        -0.5 * ((x_grid - current["collar_x"]) / max(width * 170 / 768, 1.0)) ** 2
    ) * np.exp(
        -0.5 * ((y_grid - current["collar_apex"]) / max(height * 150 / 1024, 1.0)) ** 2
    )
    shift_x = gate * dx_body
    shift_y = gate * (dy_body + tilt_shift + collar_weight * collar_residual)

    map_x = (x_grid - shift_x).astype(np.float32)
    map_y = (y_grid - shift_y).astype(np.float32)
    remapped = cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    unchanged_end = int(math.floor(transition_start))
    remapped[: unchanged_end + 1] = image[: unchanged_end + 1]
    return remapped, {
        "dx_body": round(dx_body, 5),
        "dy_body": round(dy_body, 5),
        "collar_residual": round(collar_residual, 5),
        "shoulder_delta_change": round(delta_change, 5),
        "unchanged_through_y": unchanged_end,
    }


def load_canvas(path: Path, width: int, height: int) -> np.ndarray:
    with Image.open(path) as opened:
        rgb = ImageOps.exif_transpose(opened).convert("RGB")
        if rgb.size != (width, height):
            rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
        return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def create_detector(width: int, height: int):
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Missing YuNet model: {MODEL_PATH}")
    return cv2.FaceDetectorYN.create(
        str(MODEL_PATH),
        "",
        (width, height),
        score_threshold=0.65,
        nms_threshold=0.3,
        top_k=100,
    )


def detect_primary(detector, image: np.ndarray) -> tuple[np.ndarray, float, list[float]]:
    height, width = image.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        raise RuntimeError("YuNet did not detect a face.")
    face = max(faces, key=lambda row: float(row[2] * row[3]))
    points = np.asarray(face[4:14], dtype=np.float64).reshape(5, 2)
    eyes = sorted((points[0], points[1]), key=lambda point: float(point[0]))
    left_eye, right_eye = eyes
    eye_vector = right_eye - left_eye
    eye_span = float(np.linalg.norm(eye_vector))
    if eye_span < 8:
        raise RuntimeError("Detected eye landmarks are too close for stable alignment.")
    eye_center = (left_eye + right_eye) / 2.0
    eye_angle = math.degrees(math.atan2(float(eye_vector[1]), float(eye_vector[0])))
    box = [float(value) for value in face[:4]]
    return points, float(face[-1]), [
        float(eye_center[0]),
        float(eye_center[1]),
        eye_span,
        eye_angle,
        *box,
    ]


def eye_transform(
    source_eye: list[float],
    target_center: np.ndarray,
    target_span: float,
    target_angle: float,
    *,
    align_rotation: bool,
) -> tuple[np.ndarray, float, float]:
    source_center = np.asarray(source_eye[:2], dtype=np.float64)
    source_span = float(source_eye[2])
    source_angle = float(source_eye[3])
    scale = target_span / source_span
    # YuNet eye-angle noise is large enough to make otherwise stable shoulders
    # rock left/right.  Keep the photographed pose by default; opt into whole-
    # canvas rotation only for genuinely tilted source sets.
    rotation = target_angle - source_angle if align_rotation else 0.0
    matrix = cv2.getRotationMatrix2D(tuple(source_center), rotation, scale)
    transformed_center = matrix[:, :2] @ source_center + matrix[:, 2]
    matrix[:, 2] += target_center - transformed_center
    return matrix, float(scale), float(rotation)


def rounded_list(values: np.ndarray | list[float], digits: int = 5) -> list:
    return np.asarray(values).round(digits).tolist()


def contact_sheet(
    rows: list[dict], output: Path, width: int, height: int, *, columns: int = 4
) -> None:
    columns = max(1, min(columns, len(rows)))
    thumb_width = 240
    thumb_height = round(thumb_width * height / width)
    label_height = 34
    line_width = 2
    sheet_rows = math.ceil(len(rows) / columns)
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, sheet_rows * (thumb_height + label_height)),
        (235, 235, 235),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(rows):
        x = (index % columns) * thumb_width
        y = (index // columns) * (thumb_height + label_height)
        with Image.open(row["output_path"]) as opened:
            image = opened.convert("RGB").resize(
                (thumb_width, thumb_height), Image.Resampling.LANCZOS
            )
        sheet.paste(image, (x, y + label_height))
        draw.rectangle((x, y, x + thumb_width, y + label_height), fill=(25, 28, 34))
        draw.text((x + 10, y + 10), f"age {row['age']:02d}", fill="white", font=font)

        center = row["aligned_eye"][0:2]
        eye_y = y + label_height + round(center[1] * thumb_height / height)
        draw.line(
            ((x, eye_y), (x + thumb_width, eye_y)),
            fill=(70, 220, 170),
            width=line_width,
        )
        draw.rectangle(
            (x, y + label_height, x + thumb_width - 1, y + label_height + thumb_height - 1),
            outline=(90, 90, 90),
            width=1,
        )
    sheet.save(output, quality=95)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ALIGNED_FACES_DIR / "age_path",
        help="Non-destructive destination for the RIFE-ready sequence.",
    )
    parser.add_argument(
        "--align-eye-rotation",
        action="store_true",
        help="Rotate the whole canvas to level the detected eye line.",
    )
    parser.add_argument(
        "--no-torso-stabilization",
        action="store_true",
        help="Skip monotonic lower-body remapping for the 8-to-17 sequence.",
    )
    args = parser.parse_args()
    if args.width < 320 or args.height < 320:
        raise ValueError("Output dimensions must both be at least 320 pixels.")

    plan = read_plan()
    sources = selected_sources(plan)
    detector = create_detector(args.width, args.height)

    detected: list[dict] = []
    for age, source_path in sources:
        image = load_canvas(source_path, args.width, args.height)
        points, score, eye = detect_primary(detector, image)
        detected.append(
            {
                "age": age,
                "source_path": source_path,
                "image": image,
                "landmarks": points,
                "detection_score": score,
                "eye": eye,
            }
        )

    target_center = np.median(
        np.asarray([row["eye"][:2] for row in detected], dtype=np.float64), axis=0
    )
    target_span = float(np.median([row["eye"][2] for row in detected]))
    target_angle = float(np.median([row["eye"][3] for row in detected]))

    prepared: list[dict] = []
    for row in detected:
        matrix, scale, rotation = eye_transform(
            row["eye"],
            target_center,
            target_span,
            target_angle,
            align_rotation=args.align_eye_rotation,
        )
        aligned = cv2.warpAffine(
            row["image"],
            matrix,
            (args.width, args.height),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        pre_points, _, _ = detect_primary(detector, aligned)
        torso_metrics = measure_dark_sweater(aligned, float(pre_points[2, 0]))
        prepared.append(
            {
                **row,
                "aligned": aligned,
                "matrix": matrix,
                "scale": scale,
                "rotation": rotation,
                "torso_metrics_before": torso_metrics,
            }
        )

    child_rows = [row for row in prepared if row["age"] <= 17]
    young_torso = min(child_rows, key=lambda row: row["age"]) if child_rows else None
    old_torso = max(child_rows, key=lambda row: row["age"]) if child_rows else None
    torso_targets: dict[int, dict] = {}
    if not args.no_torso_stabilization and young_torso and old_torso:
        if young_torso["torso_metrics_before"] is None or old_torso["torso_metrics_before"] is None:
            raise RuntimeError("Could not measure the torso stabilization endpoints.")
        age_span = max(old_torso["age"] - young_torso["age"], 1)
        for row in child_rows:
            if row["torso_metrics_before"] is None:
                raise RuntimeError(f"Could not measure the age-{row['age']} sweater boundary.")
            fraction = (row["age"] - young_torso["age"]) / age_span
            torso_targets[row["age"]] = interpolate_torso_metrics(
                young_torso["torso_metrics_before"],
                old_torso["torso_metrics_before"],
                fraction,
            )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict] = []
    for index, row in enumerate(prepared, start=1):
        aligned = row["aligned"]
        torso_before = row["torso_metrics_before"]
        torso_target = torso_targets.get(row["age"])
        torso_passes: list[dict] = []
        torso_stabilized = bool(
            torso_target
            and torso_before
            and any(
                abs(torso_target[key] - torso_before[key]) > 0.1
                for key in (
                    "collar_apex",
                    "shoulder_mean",
                    "shoulder_delta",
                    "collar_nose_offset",
                )
            )
        )
        if torso_stabilized:
            aligned, shift = remap_torso(aligned, torso_before, torso_target)
            torso_passes.append(shift)
            for _ in range(2):
                check_points, _, _ = detect_primary(detector, aligned)
                torso_check = measure_dark_sweater(aligned, float(check_points[2, 0]))
                if torso_check is None:
                    raise RuntimeError(
                        f"Lost the age-{row['age']} sweater boundary after remapping."
                    )
                residual_large = (
                    abs(torso_check["collar_apex"] - torso_target["collar_apex"]) > 1.5
                    or abs(torso_check["shoulder_mean"] - torso_target["shoulder_mean"]) > 1.25
                    or abs(torso_check["shoulder_delta"] - torso_target["shoulder_delta"]) > 1.5
                )
                if not residual_large:
                    break
                aligned, shift = remap_torso(
                    aligned, torso_check, torso_target, damping=0.6
                )
                torso_passes.append(shift)

        aligned_points, aligned_score, aligned_eye = detect_primary(detector, aligned)
        torso_after = measure_dark_sweater(aligned, float(aligned_points[2, 0]))
        filename = f"{index:02d}_age{row['age']:02d}.png"
        output_path = output_dir / filename
        if not cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_PNG_COMPRESSION, 4]):
            raise OSError(f"Could not save aligned keyframe: {output_path}")

        warnings: list[str] = []
        if row["scale"] < 0.75 or row["scale"] > 1.35:
            warnings.append("large_camera_scale_correction")
        if abs(row["rotation"]) > 5.0:
            warnings.append("large_rotation_correction")
        manifest_rows.append(
            {
                "index": index,
                "age": row["age"],
                "source_path": repository_path(row["source_path"]),
                "output_path": repository_path(output_path),
                "output_name": filename,
                "detection_score_before": round(row["detection_score"], 6),
                "detection_score_after": round(aligned_score, 6),
                "source_landmarks": rounded_list(row["landmarks"]),
                "aligned_landmarks": rounded_list(aligned_points),
                "source_eye": rounded_list(row["eye"]),
                "aligned_eye": rounded_list(aligned_eye),
                "transform": rounded_list(row["matrix"]),
                "scale": round(row["scale"], 6),
                "rotation_degrees": round(row["rotation"], 6),
                "torso_stabilized": torso_stabilized,
                "torso_metrics_before": torso_before,
                "torso_metrics_target": torso_target,
                "torso_metrics_after": torso_after,
                "torso_remap_passes": torso_passes,
                "warnings": warnings,
            }
        )
        print(
            f"age {row['age']:02d}: {filename} | scale {row['scale']:.3f} | "
            f"rotation {row['rotation']:+.2f} deg | detection {aligned_score:.3f} | "
            f"torso {'locked' if torso_stabilized else 'original'}"
        )

    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "RIFE-ready selected age keyframes",
        "order": "youngest_to_current",
        "canvas": {"width": args.width, "height": args.height},
        "alignment": {
            "type": "eye-center global scale and translation",
            "target_eye_center": rounded_list(target_center),
            "target_eye_span": round(target_span, 5),
            "target_eye_angle_degrees": round(target_angle, 5),
            "rotation_alignment_enabled": args.align_eye_rotation,
            "nonrigid_face_warp": False,
            "photometric_normalization": False,
            "child_torso_stabilization": {
                "enabled": not args.no_torso_stabilization,
                "endpoint_ages": [
                    young_torso["age"] if young_torso else None,
                    old_torso["age"] if old_torso else None,
                ],
                "scope": "monotonic same-image remap below y=620/1024",
                "face_pixels_changed": False,
            },
        },
        "rows": manifest_rows,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    list_path = output_dir / "rife_sequence.txt"
    list_path.write_text(
        "\n".join(row["output_name"] for row in manifest_rows) + "\n", encoding="utf-8"
    )
    sheet_path = output_dir / "contact_sheet.png"
    contact_sheet(manifest_rows, sheet_path, args.width, args.height)
    transition_rows = [row for row in manifest_rows if row["age"] in {15, 16, 17}]
    if transition_rows:
        transition_path = output_dir / "transition_15_16_17.png"
        contact_sheet(
            transition_rows,
            transition_path,
            args.width,
            args.height,
            columns=3,
        )

    print(f"\nPrepared {len(manifest_rows)} keyframes: {output_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Contact sheet: {sheet_path}")
    if transition_rows:
        print(f"15-16-17 transition: {transition_path}")


if __name__ == "__main__":
    main()
