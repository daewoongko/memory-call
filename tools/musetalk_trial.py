"""Prepare, run, and verify an isolated MuseTalk 1.5 Korean lip-sync trial.

The finalized morph and frontend assets are never overwritten. All generated
trial material lives below data/faces/lipsync_trials, which is private and
gitignored by the project.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import cv2
import imageio_ffmpeg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MUSETALK_DIR = ROOT.parent / "Models" / "MuseTalk"
DEFAULT_TRIAL_DIR = (
    ROOT / "data" / "faces" / "lipsync_trials" / "musetalk_v15_idle_ko"
)
DEFAULT_SENTENCE = "민수야, 보고 싶었어. 오늘 뭐 먹고 싶니?"
DEFAULT_RESULT_NAME = "musetalk_v15_idle_ko_25fps.mp4"
EXPECTED_UNET_SHA256 = (
    "7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007"
)


def required_model_paths(musetalk_dir: Path) -> list[Path]:
    return [
        musetalk_dir / "models" / "musetalkV15" / "musetalk.json",
        musetalk_dir / "models" / "musetalkV15" / "unet.pth",
        musetalk_dir / "models" / "sd-vae" / "config.json",
        musetalk_dir / "models" / "sd-vae" / "diffusion_pytorch_model.bin",
        musetalk_dir / "models" / "whisper" / "config.json",
        musetalk_dir / "models" / "whisper" / "pytorch_model.bin",
        musetalk_dir / "models" / "whisper" / "preprocessor_config.json",
        musetalk_dir / "models" / "dwpose" / "dw-ll_ucoco_384.pth",
        musetalk_dir / "models" / "face-parse-bisent" / "79999_iter.pth",
        musetalk_dir
        / "models"
        / "face-parse-bisent"
        / "resnet18-5c106cde.pth",
        musetalk_dir
        / "musetalk"
        / "utils"
        / "face_detection"
        / "detection"
        / "sfd"
        / "s3fd.pth",
    ]


def missing_model_paths(musetalk_dir: Path) -> list[Path]:
    return [path for path in required_model_paths(musetalk_dir) if not path.is_file()]


def find_musetalk_python(explicit: str | None = None) -> Path:
    candidates = [
        Path(explicit) if explicit else None,
        ROOT / ".tools" / "python310" / "bin" / "python.exe",
        ROOT / ".venv-musetalk" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "MuseTalk Python 3.10 was not found. Run tools/setup_musetalk_runtime.ps1."
    )


def ensure_ffmpeg_alias() -> tuple[Path, Path]:
    source = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    destination_dir = ROOT / ".tools" / "ffmpeg"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "ffmpeg.exe"
    if not destination.is_file() or destination.stat().st_size != source.stat().st_size:
        shutil.copy2(source, destination)
    return destination, destination_dir


def synthesize_korean_trial_audio(destination: Path, sentence: str) -> None:
    """Use the same ElevenLabs client the live backend uses for TTS."""
    sys.path.insert(0, str(ROOT / "backend"))
    import elevenlabs_tts  # noqa: PLC0415 - optional dependency of this trial tool only

    try:
        result = elevenlabs_tts.synthesize_with_metadata(sentence, 0.92)
    except (
        elevenlabs_tts.ElevenLabsNotConfigured,
        elevenlabs_tts.ElevenLabsUnavailable,
    ) as exc:
        raise RuntimeError(f"ElevenLabs TTS is unavailable: {exc}") from exc
    if len(result.body) < 44 or not result.body.startswith(b"RIFF"):
        raise RuntimeError("ElevenLabs returned an invalid WAV response.")
    destination.write_bytes(result.body)


def validate_trial_audio(path: Path) -> dict[str, float | int]:
    """Validate a prepared trial WAV before MuseTalk consumes it."""
    if not path.is_file() or path.stat().st_size <= 44:
        raise RuntimeError(f"Prepared Korean WAV is missing or empty: {path}")
    try:
        with wave.open(str(path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.getnframes()
    except (EOFError, wave.Error) as exc:
        raise RuntimeError(f"Prepared Korean WAV is invalid: {path}") from exc
    if sample_rate != 24_000 or channels != 1 or sample_width != 2 or frames <= 0:
        raise RuntimeError(
            "Prepared Korean WAV must be non-empty 24 kHz mono PCM16; "
            f"found {sample_rate} Hz, {channels} channel(s), {sample_width * 8}-bit."
        )
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width": sample_width,
        "frames": frames,
        "duration_seconds": frames / sample_rate,
    }


def run_command(command: list[str], *, cwd: Path | None = None, env=None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {command[0]}"
        )


def convert_idle_to_25fps(ffmpeg: Path, source: Path, destination: Path) -> None:
    run_command(
        [
            str(ffmpeg),
            "-nostdin",
            "-y",
            "-v",
            "warning",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            "fps=25",
            "-an",
            "-map_metadata",
            "-1",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
    )


def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def write_trial_config(path: Path, video: Path, audio: Path) -> None:
    path.write_text(
        "trial_idle_ko:\n"
        f"  video_path: '{yaml_path(video)}'\n"
        f"  audio_path: '{yaml_path(audio)}'\n"
        f"  result_name: '{DEFAULT_RESULT_NAME}'\n",
        encoding="utf-8",
    )


def read_video(path: Path, *, keep_frames: bool = False) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = []
    frame_count = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_count += 1
        if keep_frames:
            frames.append(frame)
    capture.release()
    if frame_count == 0 or fps <= 0:
        raise RuntimeError(f"Video contains no decodable frames: {path}")
    result = {
        "fps": fps,
        "width": width,
        "height": height,
        "frames": frame_count,
        "duration_seconds": frame_count / fps,
    }
    if keep_frames:
        result["decoded_frames"] = frames
    return result


def make_contact_sheet(frames: list, destination: Path) -> None:
    indexes = sorted(
        {0, len(frames) // 4, len(frames) // 2, 3 * len(frames) // 4, len(frames) - 1}
    )
    cells = []
    for index in indexes:
        frame = frames[index]
        target_width = 220
        target_height = round(frame.shape[0] * target_width / frame.shape[1])
        cell = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
        cv2.putText(
            cell,
            f"frame {index}",
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cells.append(cell)
    sheet = cv2.hconcat(cells)
    if not cv2.imwrite(str(destination), sheet):
        raise RuntimeError(f"Could not write QC contact sheet: {destination}")


def verify_ffmpeg_stream(ffmpeg: Path, output: Path, stream: str) -> None:
    run_command(
        [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(output),
            "-map",
            stream,
            "-f",
            "null",
            "NUL",
        ]
    )


def validate_output(ffmpeg: Path, audio: Path, output: Path, report_path: Path) -> dict:
    if not output.is_file() or output.stat().st_size <= 100_000:
        raise RuntimeError("MuseTalk did not create a non-empty final MP4.")
    verify_ffmpeg_stream(ffmpeg, output, "0:v:0")
    verify_ffmpeg_stream(ffmpeg, output, "0:a:0")
    video = read_video(output, keep_frames=True)
    with wave.open(str(audio), "rb") as wav_file:
        audio_duration = wav_file.getnframes() / wav_file.getframerate()
    expected_frames = math.floor(audio_duration * 25)
    errors = []
    if abs(video["fps"] - 25.0) > 0.01:
        errors.append(f"fps={video['fps']:.3f}")
    if (video["width"], video["height"]) != (830, 1108):
        errors.append(f"size={video['width']}x{video['height']}")
    if abs(video["frames"] - expected_frames) > 1:
        errors.append(f"frames={video['frames']} expected={expected_frames}")
    duration_delta = abs(video["duration_seconds"] - audio_duration)
    if duration_delta > 0.12:
        errors.append(f"duration_delta={duration_delta:.3f}s")
    if errors:
        raise RuntimeError("MuseTalk output validation failed: " + ", ".join(errors))

    decoded_frames = video.pop("decoded_frames")
    contact_sheet = report_path.with_name("musetalk_v15_idle_ko_qc.png")
    make_contact_sheet(decoded_frames, contact_sheet)
    report = {
        "ok": True,
        "model": "MuseTalk 1.5",
        "language": "ko",
        "output": str(output.resolve()),
        "bytes": output.stat().st_size,
        "video": video,
        "audio_duration_seconds": audio_duration,
        "duration_delta_seconds": duration_delta,
        "contact_sheet": str(contact_sheet.resolve()),
        "visual_review_required": True,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--musetalk-dir", default=os.getenv("MEMORY_CALL_MUSETALK_DIR"))
    parser.add_argument("--musetalk-python")
    parser.add_argument("--trial-dir", type=Path, default=DEFAULT_TRIAL_DIR)
    parser.add_argument("--sentence", default=DEFAULT_SENTENCE)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--reuse-audio",
        action="store_true",
        help="Reuse the already prepared local Chatterbox WAV without calling TTS.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv(ROOT / ".env", override=False)
    musetalk_dir = Path(args.musetalk_dir or DEFAULT_MUSETALK_DIR).resolve()
    trial_dir = args.trial_dir.resolve()
    trial_dir.mkdir(parents=True, exist_ok=True)
    source_video = ROOT / "data" / "faces" / "loops" / "idle.mp4"
    audio = trial_dir / "chatterbox_ko.wav"
    video_25fps = trial_dir / "idle_25fps.mp4"
    config = trial_dir / "trial.yaml"
    report_path = trial_dir / "validation.json"
    ffmpeg, ffmpeg_dir = ensure_ffmpeg_alias()

    if args.reuse_audio:
        validate_trial_audio(audio)
        print(f"Reusing prepared local Chatterbox WAV: {audio}")
    else:
        synthesize_korean_trial_audio(audio, args.sentence)
        validate_trial_audio(audio)
    convert_idle_to_25fps(ffmpeg, source_video, video_25fps)
    input_video = read_video(video_25fps)
    if abs(input_video["fps"] - 25.0) > 0.01:
        raise RuntimeError(f"25fps conversion failed: {input_video['fps']:.3f}")
    write_trial_config(config, video_25fps, audio)

    missing = missing_model_paths(musetalk_dir)
    print(f"Prepared Korean WAV: {audio}")
    print(f"Prepared 25fps video: {video_25fps}")
    print(f"Prepared trial config: {config}")
    if args.prepare_only:
        print(f"MuseTalk model files missing: {len(missing)}")
        return
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise RuntimeError(
            "MuseTalk model files are missing. Run tools/setup_musetalk_runtime.ps1.\n"
            + formatted
        )

    python = find_musetalk_python(args.musetalk_python)
    output = trial_dir / "run" / "v15" / DEFAULT_RESULT_NAME
    if output.exists():
        output.unlink()
    command = [
        str(python),
        "-m",
        "scripts.inference",
        "--inference_config",
        str(config),
        "--result_dir",
        str(trial_dir / "run"),
        "--unet_model_path",
        str(musetalk_dir / "models" / "musetalkV15" / "unet.pth"),
        "--unet_config",
        str(musetalk_dir / "models" / "musetalkV15" / "musetalk.json"),
        "--whisper_dir",
        str(musetalk_dir / "models" / "whisper"),
        "--vae_type",
        "sd-vae",
        "--version",
        "v15",
        "--fps",
        "25",
        "--batch_size",
        "4",
        "--use_float16",
        "--saved_coord",
        "--ffmpeg_path",
        str(ffmpeg_dir),
    ]
    child_env = os.environ.copy()
    child_env["PATH"] = str(ffmpeg_dir) + os.pathsep + child_env.get("PATH", "")
    started = time.perf_counter()
    run_command(command, cwd=musetalk_dir, env=child_env)
    report = validate_output(ffmpeg, audio, output, report_path)
    report["inference_seconds"] = time.perf_counter() - started
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("MuseTalk Korean trial passed technical validation.")
    print(f"Output: {output}")
    print(f"QC: {report['contact_sheet']}")
    print("Final lip/teeth/seam quality still requires visual review.")


if __name__ == "__main__":
    main()
