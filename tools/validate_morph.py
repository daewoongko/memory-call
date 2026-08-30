#!/usr/bin/env python3
"""Validate a youngest-to-current memory-call RIFE morph.

The validator intentionally decodes every frame.  It checks the delivery contract
(H.264, 768x1024, 30 fps), detects corrupt/black/frozen/jumping frames,
runs YuNet on every decoded frame when the model is available, verifies that the
video starts and ends on its approved youngest/current anchors, and produces both a
contact sheet and ``morph.json``.

The staged ``morph.next`` artifacts stay beside the live media and are installed
only after every required validation check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


PROJECT = (
    Path(os.environ["MEMORY_CALL_ROOT"]).expanduser().resolve()
    if os.environ.get("MEMORY_CALL_ROOT")
    else Path(__file__).resolve().parents[1]
)
FACES_DIR = PROJECT / "data" / "faces"
DEFAULT_SEQUENCE_DIR = PROJECT / "data" / "faces" / "aligned" / "age_path_final"
DEFAULT_VIDEO = FACES_DIR / "morph.next.mp4"
DEFAULT_PUBLISHED_VIDEO = FACES_DIR / "morph.mp4"
DEFAULT_REPORT = FACES_DIR / "morph.next.json"
DEFAULT_CONTACT_SHEET = FACES_DIR / "morph.next.qc.png"
DEFAULT_DETECTOR = PROJECT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"
DEFAULT_RIFE_MODEL = PROJECT / "backend" / "models" / "rife" / "RIFE_fp32_timestep.onnx"

EXPECTED_WIDTH = 768
EXPECTED_HEIGHT = 1024
EXPECTED_FPS = 30.0
DEFAULT_LEAD_HOLD_SECONDS = 0.6
DEFAULT_TAIL_HOLD_SECONDS = 1.2

# Deliberately slower childhood passages and slightly quicker adult passages.
LEGACY_SEGMENTS: tuple[tuple[int, int, float], ...] = (
    (8, 9, 2.4),
    (9, 11, 2.6),
    (11, 13, 2.6),
    (13, 15, 2.6),
    (15, 16, 2.4),
    (16, 17, 2.4),
    (17, 20, 2.2),
    (20, 23, 2.0),
    (23, 26, 2.0),
    (26, 29, 2.0),
    (29, 31, 1.8),
    (31, 32, 1.6),
)
LEGACY_SECONDS = {(start, end): seconds for start, end, seconds in LEGACY_SEGMENTS}


@dataclass
class FaceObservation:
    frame: int
    score: float
    box: tuple[float, float, float, float]
    center: tuple[float, float]
    eye_midpoint: tuple[float, float]
    eye_span: float
    detections: int


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def repo_path(path: Path) -> str:
    """Serialize an existing or planned path relative to the repository root."""

    try:
        return path.expanduser().resolve().relative_to(PROJECT).as_posix()
    except ValueError as exc:
        raise ValueError(f"Metadata path must be inside MEMORY_CALL_ROOT: {path}") from exc


def age_from_name(path: Path) -> int:
    match = re.search(r"age(\d+)", path.stem, re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not extract age from {path.name}")
    return int(match.group(1))


def load_sequence(sequence_dir: Path) -> list[tuple[int, Path]]:
    sequence_file = sequence_dir / "rife_sequence.txt"
    if sequence_file.exists():
        paths = [sequence_dir / line.strip() for line in sequence_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    else:
        paths = sorted(sequence_dir.glob("*_age*.png"))
    if not paths:
        raise FileNotFoundError(f"No keyframes found in {sequence_dir}")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing keyframes: " + ", ".join(missing))
    sequence = [(age_from_name(path), path) for path in paths]
    actual_ages = [age for age, _ in sequence]
    if len(actual_ages) < 2 or actual_ages != sorted(set(actual_ages)):
        raise ValueError(
            f"Keyframe ages must be unique and youngest-to-current: {actual_ages}"
        )
    return sequence


def segment_seconds(
    start_age: int,
    end_age: int,
    *,
    timing_mode: str = "legacy",
    seconds_per_year: float = 1.0,
    child_slowdown_until: int = 12,
    child_slowdown: float = 1.5,
) -> float:
    gap = end_age - start_age
    if gap <= 0:
        raise ValueError(f"Invalid age segment: {start_age}->{end_age}")
    if timing_mode == "age-linear":
        return round(min(4.0, max(1.2, gap * 1.2)), 2)
    if timing_mode == "age-weighted":
        if seconds_per_year <= 0 or child_slowdown < 1.0:
            raise ValueError("Age-weighted timing values must be positive.")
        weighted_years = sum(
            child_slowdown if age < child_slowdown_until else 1.0
            for age in range(start_age, end_age)
        )
        return round(seconds_per_year * weighted_years, 3)
    if timing_mode != "legacy":
        raise ValueError(f"Unknown timing mode: {timing_mode}")
    legacy = LEGACY_SECONDS.get((start_age, end_age))
    if legacy is not None:
        return legacy
    base = 2.4 if end_age <= 18 else 2.2 if end_age <= 30 else 2.0 if end_age <= 50 else 1.8
    return round(min(2.8, base + max(0, gap - 3) * 0.08), 2)


def fourcc_text(value: float) -> str:
    integer = int(value)
    return "".join(chr((integer >> (8 * shift)) & 0xFF) for shift in range(4)).rstrip("\x00")


def true_ssim(left: np.ndarray, right: np.ndarray) -> float:
    """Compute mean SSIM without requiring scikit-image."""
    if left.shape != right.shape:
        raise ValueError("SSIM inputs have different shapes")
    left_f = left.astype(np.float32)
    right_f = right.astype(np.float32)
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    mu_left = cv2.GaussianBlur(left_f, (11, 11), 1.5)
    mu_right = cv2.GaussianBlur(right_f, (11, 11), 1.5)
    mu_left_sq = mu_left * mu_left
    mu_right_sq = mu_right * mu_right
    mu_both = mu_left * mu_right
    sigma_left = cv2.GaussianBlur(left_f * left_f, (11, 11), 1.5) - mu_left_sq
    sigma_right = cv2.GaussianBlur(right_f * right_f, (11, 11), 1.5) - mu_right_sq
    sigma_both = cv2.GaussianBlur(left_f * right_f, (11, 11), 1.5) - mu_both
    numerator = (2.0 * mu_both + c1) * (2.0 * sigma_both + c2)
    denominator = (mu_left_sq + mu_right_sq + c1) * (sigma_left + sigma_right + c2)
    score = numerator / np.maximum(denominator, 1e-12)
    return float(np.mean(score))


def endpoint_metrics(decoded: np.ndarray, anchor_path: Path) -> dict[str, float]:
    anchor = cv2.imread(str(anchor_path), cv2.IMREAD_COLOR)
    if anchor is None:
        raise RuntimeError(f"Failed to read anchor: {anchor_path}")
    if anchor.shape[:2] != decoded.shape[:2]:
        anchor = cv2.resize(anchor, (decoded.shape[1], decoded.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    mse = float(np.mean((decoded.astype(np.float32) - anchor.astype(np.float32)) ** 2))
    psnr = float("inf") if mse == 0.0 else float(10.0 * math.log10((255.0 * 255.0) / mse))
    gray_decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    gray_anchor = cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY)
    return {
        "mse": round(mse, 6),
        "psnr_db": round(psnr, 4) if math.isfinite(psnr) else 999.0,
        "ssim": round(true_ssim(gray_decoded, gray_anchor), 6),
    }


def robust_threshold(values: Iterable[float], minimum: float, z: float = 8.0) -> tuple[float, float, float]:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size == 0:
        return minimum, 0.0, 0.0
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    threshold = max(minimum, median + z * 1.4826 * mad)
    return float(threshold), median, mad


def consecutive_runs(frame_numbers: Iterable[int]) -> list[list[int]]:
    """Return sorted consecutive runs from an iterable of frame numbers."""

    ordered = sorted(set(frame_numbers))
    if not ordered:
        return []
    runs: list[list[int]] = [[ordered[0]]]
    for frame in ordered[1:]:
        if frame == runs[-1][-1] + 1:
            runs[-1].append(frame)
        else:
            runs.append([frame])
    return runs


def build_timing(
    ages: list[int],
    fps: float = EXPECTED_FPS,
    *,
    timing_mode: str = "legacy",
    seconds_per_year: float = 1.0,
    child_slowdown_until: int = 12,
    child_slowdown: float = 1.5,
    lead_hold_seconds: float = DEFAULT_LEAD_HOLD_SECONDS,
    tail_hold_seconds: float = DEFAULT_TAIL_HOLD_SECONDS,
) -> dict[str, Any]:
    lead_frames = round(lead_hold_seconds * fps)
    tail_frames = round(tail_hold_seconds * fps)
    if lead_frames < 1 or tail_frames < 0:
        raise ValueError("Hold durations must produce at least one lead frame and a non-negative tail frame count.")
    segments: list[dict[str, Any]] = []
    source_hit_frame = 0
    next_output_frame = lead_frames
    anchors = [{"age": ages[0], "hit_frame": 0, "elapsed_seconds": 0.0}]
    for from_age, to_age in zip(ages, ages[1:]):
        seconds = segment_seconds(
            from_age,
            to_age,
            timing_mode=timing_mode,
            seconds_per_year=seconds_per_year,
            child_slowdown_until=child_slowdown_until,
            child_slowdown=child_slowdown,
        )
        frame_count = round(seconds * fps)
        target_hit_frame = next_output_frame + frame_count - 1
        elapsed = (target_hit_frame + 1) / fps
        segments.append(
            {
                "from_age": from_age,
                "to_age": to_age,
                "duration_seconds": seconds,
                "interpolated_frame_count": frame_count,
                "source_hit_frame": source_hit_frame,
                "first_output_frame": next_output_frame,
                "target_hit_frame": target_hit_frame,
                "elapsed_at_target_seconds": round(elapsed, 6),
            }
        )
        anchors.append({"age": to_age, "hit_frame": target_hit_frame, "elapsed_seconds": round(elapsed, 6)})
        source_hit_frame = target_hit_frame
        next_output_frame = target_hit_frame + 1
    expected_frames = lead_frames + sum(item["interpolated_frame_count"] for item in segments) + tail_frames
    return {
        "fps": fps,
        "timing_mode": timing_mode,
        "seconds_per_year": seconds_per_year,
        "child_slowdown_until": child_slowdown_until,
        "child_slowdown": child_slowdown,
        "lead_hold_seconds": lead_hold_seconds,
        "lead_hold_frames": lead_frames,
        "tail_hold_seconds": tail_hold_seconds,
        "tail_hold_frames": tail_frames,
        "segments": segments,
        "anchors": anchors,
        "expected_frame_count": expected_frames,
        "expected_duration_seconds": expected_frames / fps,
        "transition_end_frame": expected_frames - tail_frames - 1,
    }


def create_detector(model: Path, frame_size: tuple[int, int]) -> tuple[Any | None, tuple[int, int], float, float]:
    if not model.is_file() or not hasattr(cv2, "FaceDetectorYN_create"):
        return None, frame_size, 1.0, 1.0
    width, height = frame_size
    detect_height = min(640, height)
    detect_width = max(1, round(width * detect_height / height))
    detector = cv2.FaceDetectorYN_create(str(model), "", (detect_width, detect_height), 0.65, 0.3, 5000)
    return detector, (detect_width, detect_height), width / detect_width, height / detect_height


def observe_face(
    detector: Any | None,
    frame: np.ndarray,
    frame_index: int,
    detect_size: tuple[int, int],
    scale_x: float,
    scale_y: float,
) -> FaceObservation | None:
    if detector is None:
        return None
    detect_frame = cv2.resize(frame, detect_size, interpolation=cv2.INTER_AREA)
    detector.setInputSize(detect_size)
    _, faces = detector.detect(detect_frame)
    if faces is None or len(faces) == 0:
        return None
    # Prefer the largest high-confidence face, avoiding tiny background false positives.
    areas = faces[:, 2] * faces[:, 3] * np.maximum(faces[:, -1], 0.0)
    row = faces[int(np.argmax(areas))]
    x, y, width, height = [float(value) for value in row[:4]]
    landmarks = row[4:14].reshape(5, 2).astype(np.float64)
    landmarks[:, 0] *= scale_x
    landmarks[:, 1] *= scale_y
    eye_a, eye_b = landmarks[0], landmarks[1]
    eye_mid = (eye_a + eye_b) / 2.0
    box = (x * scale_x, y * scale_y, width * scale_x, height * scale_y)
    center = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
    return FaceObservation(
        frame=frame_index,
        score=float(row[-1]),
        box=box,
        center=center,
        eye_midpoint=(float(eye_mid[0]), float(eye_mid[1])),
        eye_span=float(np.linalg.norm(eye_a - eye_b)),
        detections=int(len(faces)),
    )


def frame_thumbnail(frame: np.ndarray, label: str, width: int = 240) -> np.ndarray:
    height = round(frame.shape[0] * width / frame.shape[1])
    thumb = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    bar = np.zeros((36, width, 3), dtype=np.uint8)
    cv2.putText(bar, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (245, 245, 245), 1, cv2.LINE_AA)
    return np.vstack([thumb, bar])


def make_contact_sheet(samples: list[tuple[np.ndarray, str]], output: Path, columns: int = 4) -> None:
    if not samples:
        return
    thumbs = [frame_thumbnail(frame, label) for frame, label in samples]
    cell_h, cell_w = thumbs[0].shape[:2]
    rows = math.ceil(len(thumbs) / columns)
    canvas = np.full((rows * cell_h, columns * cell_w, 3), 24, dtype=np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, columns)
        canvas[row * cell_h : (row + 1) * cell_h, col * cell_w : (col + 1) * cell_w] = thumb
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6]):
        raise RuntimeError(f"Failed to write QC contact sheet: {output}")


def serial_face(face: FaceObservation) -> dict[str, Any]:
    return {
        "frame": face.frame,
        "score": round(face.score, 6),
        "detections": face.detections,
        "box": [round(value, 4) for value in face.box],
        "center": [round(value, 4) for value in face.center],
        "eye_midpoint": [round(value, 4) for value in face.eye_midpoint],
        "eye_span": round(face.eye_span, 4),
    }


def validate(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    video = args.video.resolve()
    published_video = args.published_video_path.resolve() if args.published_video_path else video
    sequence_dir = args.sequence_dir.resolve()
    sequence = load_sequence(sequence_dir)
    sequence_ages = [age for age, _ in sequence]
    timing = build_timing(
        sequence_ages,
        EXPECTED_FPS,
        timing_mode=args.timing_mode,
        seconds_per_year=args.seconds_per_year,
        child_slowdown_until=args.child_slowdown_until,
        child_slowdown=args.child_slowdown,
        lead_hold_seconds=args.lead_hold_seconds,
        tail_hold_seconds=args.tail_hold_seconds,
    )
    expected_count = timing["expected_frame_count"]
    anchor_frames = {item["hit_frame"]: item["age"] for item in timing["anchors"]}

    if not video.is_file():
        raise FileNotFoundError(f"Video does not exist: {video}")
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video}")

    declared_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    declared_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    declared_fps = float(capture.get(cv2.CAP_PROP_FPS))
    declared_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    codec = fourcc_text(capture.get(cv2.CAP_PROP_FOURCC))
    detector, detect_size, scale_x, scale_y = create_detector(args.detector_model, (declared_width, declared_height))

    decoded_count = 0
    black_frames: list[int] = []
    blank_frames: list[int] = []
    low_motion_frames: list[int] = []
    pixel_diffs: list[float] = []
    luma_means: list[float] = []
    luma_stds: list[float] = []
    face_observations: list[FaceObservation] = []
    no_face_frames: list[int] = []
    multiple_face_frames: list[int] = []
    low_face_confidence_frames: list[int] = []
    frames_for_qc: dict[int, np.ndarray] = {}
    previous_gray_small: np.ndarray | None = None
    first_frame: np.ndarray | None = None
    last_frame: np.ndarray | None = None
    tail_first = expected_count - timing["tail_hold_frames"]

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index = decoded_count
        decoded_count += 1
        if frame.shape[1] != declared_width or frame.shape[0] != declared_height:
            raise RuntimeError(f"Frame {index} has inconsistent size {frame.shape[1]}x{frame.shape[0]}")
        if first_frame is None:
            first_frame = frame.copy()
        last_frame = frame.copy()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean = float(np.mean(gray))
        std = float(np.std(gray))
        luma_means.append(mean)
        luma_stds.append(std)
        black_fraction = float(np.mean(gray < 5))
        if mean < 6.0 or black_fraction > 0.98:
            black_frames.append(index)
        if std < 2.0:
            blank_frames.append(index)

        gray_small = cv2.resize(gray, (192, 256), interpolation=cv2.INTER_AREA)
        if previous_gray_small is not None:
            difference = float(np.mean(cv2.absdiff(gray_small, previous_gray_small)))
            pixel_diffs.append(difference)
            in_lead_hold = index < timing["lead_hold_frames"]
            in_tail_hold = index >= tail_first
            if difference < 0.025 and not (in_lead_hold or in_tail_hold):
                low_motion_frames.append(index)
        previous_gray_small = gray_small

        face = observe_face(detector, frame, index, detect_size, scale_x, scale_y)
        if detector is not None:
            if face is None:
                no_face_frames.append(index)
            else:
                face_observations.append(face)
                if face.detections > 1:
                    multiple_face_frames.append(index)
                if face.score < 0.75:
                    low_face_confidence_frames.append(index)

        if index in anchor_frames:
            frames_for_qc[index] = frame.copy()
    capture.release()

    if first_frame is None or last_frame is None:
        raise RuntimeError("Video contained no decodable frames")

    # A slowly changing portrait can legitimately quantize to the same 8-bit
    # frame for a few 30-fps samples.  Treat that as advisory low motion; only
    # a continuous stall lasting at least 0.25 seconds is a delivery failure.
    low_motion_runs = consecutive_runs(low_motion_frames)
    minimum_stalled_run_frames = max(2, round(declared_fps * 0.25))
    stalled_runs = [run for run in low_motion_runs if len(run) >= minimum_stalled_run_frames]
    unexpected_frozen_frames = [frame for run in stalled_runs for frame in run]

    # Pixel jump detection is distribution-aware and also enforces an absolute floor.
    pixel_jump_threshold, pixel_diff_median, pixel_diff_mad = robust_threshold(pixel_diffs, minimum=12.0, z=8.0)
    pixel_jump_frames = [index + 1 for index, value in enumerate(pixel_diffs) if value > pixel_jump_threshold]
    severe_pixel_jump_frames = [index + 1 for index, value in enumerate(pixel_diffs) if value > max(28.0, pixel_jump_threshold * 1.75)]

    # Landmark/face-box jumps catch a face discontinuity that a whole-frame average can hide.
    face_by_frame = {face.frame: face for face in face_observations}
    face_center_jumps: list[tuple[int, float]] = []
    face_scale_jumps: list[tuple[int, float]] = []
    diagonal = math.hypot(declared_width, declared_height)
    for frame_index in range(1, decoded_count):
        previous = face_by_frame.get(frame_index - 1)
        current = face_by_frame.get(frame_index)
        if previous is None or current is None:
            continue
        eye_jump = math.dist(previous.eye_midpoint, current.eye_midpoint) / diagonal
        face_center_jumps.append((frame_index, eye_jump))
        if previous.eye_span > 1e-6 and current.eye_span > 1e-6:
            scale_jump = abs(math.log(current.eye_span / previous.eye_span))
            face_scale_jumps.append((frame_index, scale_jump))
    face_center_threshold, face_center_median, face_center_mad = robust_threshold(
        (value for _, value in face_center_jumps), minimum=0.018, z=8.0
    )
    face_scale_threshold, face_scale_median, face_scale_mad = robust_threshold(
        (value for _, value in face_scale_jumps), minimum=0.055, z=8.0
    )
    face_center_jump_frames = [index for index, value in face_center_jumps if value > face_center_threshold]
    face_scale_jump_frames = [index for index, value in face_scale_jumps if value > face_scale_threshold]
    severe_face_jump_frames = sorted(
        {index for index, value in face_center_jumps if value > max(0.06, face_center_threshold * 2.0)}
        | {index for index, value in face_scale_jumps if value > max(0.16, face_scale_threshold * 2.0)}
    )

    start_metrics = endpoint_metrics(first_frame, sequence[0][1])
    end_metrics = endpoint_metrics(last_frame, sequence[-1][1])
    endpoint_pass = all(
        metrics["psnr_db"] >= 30.0 and metrics["ssim"] >= 0.97 for metrics in (start_metrics, end_metrics)
    )

    # Guarantee contact-sheet coverage even when a corrupt/short file misses an expected anchor.
    if decoded_count > 0:
        frames_for_qc.setdefault(0, first_frame)
        frames_for_qc.setdefault(decoded_count - 1, last_frame)
    notable_frames = sorted(
        set(black_frames + unexpected_frozen_frames + severe_pixel_jump_frames + severe_face_jump_frames + no_face_frames)
    )[:8]
    if notable_frames:
        recapture = cv2.VideoCapture(str(video))
        notable_set = set(notable_frames)
        cursor = 0
        while notable_set:
            ok, frame = recapture.read()
            if not ok:
                break
            if cursor in notable_set:
                frames_for_qc[cursor] = frame.copy()
                notable_set.remove(cursor)
            cursor += 1
        recapture.release()

    labels_by_frame = {item["hit_frame"]: f"age {item['age']} | f{item['hit_frame']}" for item in timing["anchors"]}
    qc_samples = [
        (frame, labels_by_frame.get(index, f"QC flag | f{index}"))
        for index, frame in sorted(frames_for_qc.items())
    ]
    make_contact_sheet(qc_samples, args.contact_sheet)

    codec_pass = codec.lower() in {"h264", "avc1", "x264"}
    format_checks = {
        "codec_h264": codec_pass,
        "width_768": declared_width == EXPECTED_WIDTH,
        "height_1024": declared_height == EXPECTED_HEIGHT,
        "fps_30_cfr": abs(declared_fps - EXPECTED_FPS) <= 0.05,
        "declared_frame_count_matches_plan": declared_count == expected_count,
        "decoded_frame_count_matches_plan": decoded_count == expected_count,
        "declared_and_decoded_counts_match": declared_count == decoded_count,
    }
    content_checks = {
        "no_black_frames": not black_frames,
        "no_blank_frames": not blank_frames,
        "no_unexpected_frozen_frames": not unexpected_frozen_frames,
        "no_severe_pixel_jumps": not severe_pixel_jump_frames,
        "no_severe_face_jumps": not severe_face_jump_frames,
        "approved_endpoints_match": endpoint_pass,
    }
    if detector is not None:
        content_checks["face_detected_in_every_frame"] = not no_face_frames

    model_metadata: dict[str, Any] | None = None
    if args.rife_model and args.rife_model.is_file():
        model_metadata = {
            "path": repo_path(args.rife_model),
            "sha256": sha256_file(args.rife_model),
            "size_bytes": args.rife_model.stat().st_size,
        }

    source_items = [
        {"age": age, "file": path.name, "path": repo_path(path), "sha256": sha256_file(path)}
        for age, path in sequence
    ]
    report: dict[str, Any] = {
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "memory-call youngest-to-current RIFE morph",
        "video": {
            "path": repo_path(published_video),
            "file": published_video.name,
            "validated_staging_path": repo_path(video) if published_video != video else None,
            "sha256": sha256_file(video),
            "size_bytes": video.stat().st_size,
            "codec_fourcc": codec,
            "width": declared_width,
            "height": declared_height,
            "fps": round(declared_fps, 6),
            "declared_frame_count": declared_count,
            "decoded_frame_count": decoded_count,
            "duration_seconds": round(decoded_count / declared_fps, 6) if declared_fps > 0 else None,
            "pixel_format_required": "yuv420p",
            "audio_required": False,
        },
        "generator": {
            "name": "RIFE arbitrary-timestep interpolation",
            "model": model_metadata,
            "direction": "youngest_to_current",
            "direct_timestep_inference": True,
        },
        "source_manifest": repo_path(sequence_dir / "manifest.json"),
        "source_sequence": source_items,
        "timing": timing,
        "validation": {
            "passed": bool(all(format_checks.values()) and all(content_checks.values())),
            "format_checks": format_checks,
            "content_checks": content_checks,
            "thresholds": {
                "black_mean_luma_below": 6.0,
                "black_pixel_fraction_above": 0.98,
                "blank_luma_std_below": 2.0,
                "unexpected_frozen_mean_absdiff_below": 0.025,
                "unexpected_frozen_minimum_continuous_frames": minimum_stalled_run_frames,
                "pixel_jump_mean_absdiff_above": round(pixel_jump_threshold, 6),
                "severe_pixel_jump_mean_absdiff_above": round(max(28.0, pixel_jump_threshold * 1.75), 6),
                "face_center_jump_normalized_above": round(face_center_threshold, 8),
                "face_scale_log_jump_above": round(face_scale_threshold, 8),
                "endpoint_psnr_db_min": 30.0,
                "endpoint_ssim_min": 0.97,
                "yunet_score_min": 0.65,
            },
            "statistics": {
                "luma_mean_min": round(min(luma_means), 6),
                "luma_mean_max": round(max(luma_means), 6),
                "luma_std_min": round(min(luma_stds), 6),
                "pixel_diff_median": round(pixel_diff_median, 6),
                "pixel_diff_mad": round(pixel_diff_mad, 6),
                "low_motion_frame_count": len(low_motion_frames),
                "longest_low_motion_run_frames": max((len(run) for run in low_motion_runs), default=0),
                "face_center_jump_median": round(face_center_median, 8),
                "face_center_jump_mad": round(face_center_mad, 8),
                "face_scale_jump_median": round(face_scale_median, 8),
                "face_scale_jump_mad": round(face_scale_mad, 8),
            },
            "flagged_frames": {
                "black": black_frames,
                "blank": blank_frames,
                "advisory_low_motion": low_motion_frames,
                "unexpected_frozen": unexpected_frozen_frames,
                "pixel_jump": pixel_jump_frames,
                "severe_pixel_jump": severe_pixel_jump_frames,
                "no_face": no_face_frames,
                "multiple_faces": multiple_face_frames,
                "low_face_confidence": low_face_confidence_frames,
                "face_center_jump": face_center_jump_frames,
                "face_scale_jump": face_scale_jump_frames,
                "severe_face_jump": severe_face_jump_frames,
            },
            "endpoint_similarity": {
                "youngest_age": sequence_ages[0],
                "current_age": sequence_ages[-1],
                "first_frame_to_youngest": start_metrics,
                "last_frame_to_current": end_metrics,
            },
            "face_detector": {
                "enabled": detector is not None,
                "model": repo_path(args.detector_model) if detector is not None else None,
                "model_sha256": sha256_file(args.detector_model) if detector is not None else None,
                "detection_input_size": list(detect_size) if detector is not None else None,
                "observed_frames": len(face_observations),
                "minimum_score": round(min((face.score for face in face_observations), default=0.0), 6),
                "anchor_observations": [
                    serial_face(face_by_frame[index]) for index in anchor_frames if index in face_by_frame
                ],
            },
            "qc_contact_sheet": repo_path(args.contact_sheet),
        },
    }
    passed = bool(report["validation"]["passed"])
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, passed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--video", type=Path, default=DEFAULT_VIDEO, help="Staged MP4 to validate")
    result.add_argument(
        "--published-video-path",
        type=Path,
        default=DEFAULT_PUBLISHED_VIDEO,
        help="Final deployment path to record in morph.json while validating --video",
    )
    result.add_argument("--sequence-dir", type=Path, default=DEFAULT_SEQUENCE_DIR, help="Approved aligned keyframes")
    result.add_argument("--out-json", type=Path, default=DEFAULT_REPORT)
    result.add_argument("--contact-sheet", type=Path, default=DEFAULT_CONTACT_SHEET)
    result.add_argument("--detector-model", type=Path, default=DEFAULT_DETECTOR)
    result.add_argument("--rife-model", type=Path, default=DEFAULT_RIFE_MODEL)
    result.add_argument("--no-yunet", action="store_true", help="Disable per-frame YuNet validation")
    result.add_argument(
        "--timing-mode",
        choices=("legacy", "age-linear", "age-weighted"),
        default="legacy",
        help="Timing contract used when the morph was rendered.",
    )
    result.add_argument("--seconds-per-year", type=float, default=1.0)
    result.add_argument("--child-slowdown-until", type=int, default=12)
    result.add_argument("--child-slowdown", type=float, default=1.5)
    result.add_argument("--lead-hold-seconds", type=float, default=DEFAULT_LEAD_HOLD_SECONDS)
    result.add_argument("--tail-hold-seconds", type=float, default=DEFAULT_TAIL_HOLD_SECONDS)
    result.add_argument("--strict", action="store_true", help="Exit non-zero when any required validation check fails")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.no_yunet:
        args.detector_model = Path("__disabled__")
    try:
        report, passed = validate(args)
    except Exception as exc:
        print(f"Morph validation failed to run: {exc}", file=sys.stderr)
        return 2
    video = report["video"]
    validation = report["validation"]
    print("Morph validation complete")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    print(
        f"Video: {video['width']}x{video['height']} | {video['fps']:.3f} fps | "
        f"{video['decoded_frame_count']} frames | {video['duration_seconds']:.3f}s | {video['codec_fourcc']}"
    )
    print(
        "Flags: "
        f"black {len(validation['flagged_frames']['black'])} | "
        f"frozen {len(validation['flagged_frames']['unexpected_frozen'])} | "
        f"severe pixel jumps {len(validation['flagged_frames']['severe_pixel_jump'])} | "
        f"no face {len(validation['flagged_frames']['no_face'])} | "
        f"severe face jumps {len(validation['flagged_frames']['severe_face_jump'])}"
    )
    endpoints = validation["endpoint_similarity"]
    print(
        f"Endpoints: age{endpoints['youngest_age']} PSNR "
        f"{endpoints['first_frame_to_youngest']['psnr_db']:.2f} dB, "
        f"SSIM {endpoints['first_frame_to_youngest']['ssim']:.4f} | "
        f"age{endpoints['current_age']} PSNR "
        f"{endpoints['last_frame_to_current']['psnr_db']:.2f} dB, "
        f"SSIM {endpoints['last_frame_to_current']['ssim']:.4f}"
    )
    print(f"Report: {args.out_json.resolve()}")
    print(f"QC sheet: {args.contact_sheet.resolve()}")
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
