#!/usr/bin/env python3
"""Build the final 8 -> 32 memory-call morph with direct-timestep RIFE.

The approved anchors are intentionally copied verbatim at each segment boundary.
Only the frames strictly between adjacent anchors are synthesized by RIFE.  Frame
counts are age-dependent so the visibly faster childhood changes are shown more
slowly than the adult passages.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from rife_ort_ctypes import RifeOrt


PROJECT = (
    Path(os.environ["MEMORY_CALL_ROOT"]).expanduser().resolve()
    if os.environ.get("MEMORY_CALL_ROOT")
    else Path(__file__).resolve().parents[1]
)
SEQUENCE_DIR = PROJECT / "data" / "faces" / "aligned" / "age_path_final"
SEQUENCE_FILE = SEQUENCE_DIR / "rife_sequence.txt"
MODEL = PROJECT / "backend" / "models" / "rife" / "RIFE_fp32_timestep.onnx"
OUTPUT = PROJECT / "data" / "faces" / "morph.next.mp4"


def resolve_ffmpeg() -> str:
    configured = os.environ.get("FFMPEG_PATH")
    if configured:
        return str(Path(configured).expanduser().resolve())
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        executable = shutil.which("ffmpeg")
        if executable:
            return executable
        raise RuntimeError(
            "ffmpeg is unavailable; install imageio-ffmpeg or set FFMPEG_PATH"
        )


FFMPEG = resolve_ffmpeg()

WIDTH = 768
HEIGHT = 1024
FPS = 30
LEAD_HOLD_FRAMES = 18
TAIL_HOLD_FRAMES = 36
SEGMENTS: tuple[tuple[int, int, float], ...] = (
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
EXPECTED_FRAMES = LEAD_HOLD_FRAMES + TAIL_HOLD_FRAMES + sum(round(s * FPS) for _, _, s in SEGMENTS)


def parse_age(path: Path) -> int:
    match = re.search(r"age(\d+)", path.stem, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse age from {path.name}")
    return int(match.group(1))


def load_sequence() -> tuple[list[int], list[np.ndarray], list[Path]]:
    if not SEQUENCE_FILE.is_file():
        raise FileNotFoundError(SEQUENCE_FILE)
    names = [line.strip() for line in SEQUENCE_FILE.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    paths = [SEQUENCE_DIR / name for name in names]
    ages = [parse_age(path) for path in paths]
    expected_ages = [SEGMENTS[0][0], *(end for _, end, _ in SEGMENTS)]
    if ages != expected_ages:
        raise ValueError(f"Sequence ages {ages} do not match timing plan {expected_ages}")
    frames: list[np.ndarray] = []
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not decode {path}")
        if image.shape[:2] != (HEIGHT, WIDTH):
            raise ValueError(f"Unexpected image size for {path.name}: {image.shape[:2]}")
        frames.append(np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
    return ages, frames, paths


def ffmpeg_command(part_path: Path) -> list[str]:
    return [
        FFMPEG,
        "-hide_banner",
        "-loglevel", "info",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s:v", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-an",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "17",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-pix_fmt", "yuv420p",
        "-tag:v", "avc1",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-fps_mode", "cfr",
        "-g", "60",
        "-keyint_min", "60",
        "-sc_threshold", "0",
        "-movflags", "+faststart",
        "-video_track_timescale", "90000",
        str(part_path),
    ]


def build(output: Path, *, prefer_cuda: bool, segment_limit: int | None = None) -> None:
    ages, anchors, paths = load_sequence()
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(output.suffix + ".part.mp4")
    log_path = output.with_suffix(".ffmpeg.log")
    if part.exists():
        part.unlink()

    print(f"Approved anchors: {', '.join(map(str, ages))}", flush=True)
    print(f"RIFE model: {MODEL}", flush=True)
    engine = RifeOrt(MODEL, prefer_cuda=prefer_cuda)
    print(f"Execution provider: {engine.provider}", flush=True)

    segments = SEGMENTS if segment_limit is None else SEGMENTS[:segment_limit]
    expected = LEAD_HOLD_FRAMES + sum(round(s * FPS) for _, _, s in segments)
    tail_frames = TAIL_HOLD_FRAMES if segment_limit is None else 0
    expected += tail_frames

    written = 0
    started = time.perf_counter()
    with log_path.open("wb") as log:
        process = subprocess.Popen(ffmpeg_command(part), stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        assert process.stdin is not None

        def write(frame: np.ndarray) -> None:
            nonlocal written
            process.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
            written += 1

        try:
            for _ in range(LEAD_HOLD_FRAMES):
                write(anchors[0])

            for segment_index, (start_age, end_age, seconds) in enumerate(segments):
                left = anchors[segment_index]
                right = anchors[segment_index + 1]
                count = round(seconds * FPS)
                segment_start = time.perf_counter()
                print(f"Segment {start_age}->{end_age}: {count} frames ({seconds:.1f}s)", flush=True)
                for k in range(1, count + 1):
                    if k == count:
                        frame = right
                    else:
                        frame = engine.interpolate(left, right, k / count)
                    write(frame)
                    if k % 15 == 0 or k == count:
                        elapsed = time.perf_counter() - segment_start
                        print(f"  {k:>3}/{count} | {elapsed:6.1f}s", flush=True)

            final_anchor = anchors[len(segments)]
            for _ in range(tail_frames):
                write(final_anchor)
        except BaseException:
            process.stdin.close()
            process.kill()
            process.wait()
            raise
        else:
            process.stdin.close()
            return_code = process.wait()
            if return_code:
                raise RuntimeError(f"ffmpeg failed with exit code {return_code}; see {log_path}")

    if written != expected:
        raise RuntimeError(f"Frame-count bug: wrote {written}, expected {expected}")
    if segment_limit is None and written != EXPECTED_FRAMES:
        raise RuntimeError(f"Final frame-count bug: wrote {written}, expected {EXPECTED_FRAMES}")
    os.replace(part, output)
    elapsed = time.perf_counter() - started
    print(f"Saved: {output}", flush=True)
    print(f"Frames: {written} | duration: {written / FPS:.3f}s | build time: {elapsed:.1f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--cpu", action="store_true", help="Force CPU inference")
    parser.add_argument("--segment-limit", type=int, choices=range(1, len(SEGMENTS) + 1))
    args = parser.parse_args()
    build(args.output.resolve(), prefer_cuda=not args.cpu, segment_limit=args.segment_limit)


if __name__ == "__main__":
    main()
