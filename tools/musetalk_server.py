"""Persistent, authenticated loopback MuseTalk 1.5 rendering service.

Only raw WAV bytes are accepted.  The avatar, model paths and output directory
are fixed when this process starts, so a remote caller cannot select local
files or make MuseTalk overwrite arbitrary paths.
"""

from __future__ import annotations

import argparse
import copy
import hmac
import io
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience for direct runs
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
TOKEN_ENV = "TTS_BRIDGE_TOKEN"
TOKEN_PLACEHOLDER = "replace-with-a-long-random-token"
DEFAULT_AVATAR_ID = "memory_call_idle_ko"
DEFAULT_PORT = 8002
MAX_WAV_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024
# 통화 중에는 화질보다 첫 소리까지의 시간이 중요하다. veryfast/CRF 20 은
# 이 해상도에서 육안 차이가 없으면서 인코딩을 수백 ms 안에 끝낸다.
ENCODER_PRESET = "veryfast"
ENCODER_CRF = 20
ENCODER_TIMEOUT_SECONDS = 120
# 0.4초짜리 워밍업은 배치 하나를 채우지 못해 batch_size 경로의 CUDA 커널이
# 첫 실제 발화에서야 초기화됐다. 통화의 첫 마디가 가장 느려지면 안 된다.
WARMUP_SECONDS = 3.0

# Receives one composited BGR frame at a time, in playback order.
FrameSink = Callable[[Any], None]


class MuseTalkBusy(RuntimeError):
    """Another inference already owns the single GPU worker."""


class InvalidWave(ValueError):
    """The request body is not a bounded RIFF/WAVE payload."""


@dataclass(frozen=True)
class MuseTalkConfig:
    musetalk_dir: Path
    source_video: Path
    ffmpeg: Path
    avatar_id: str = DEFAULT_AVATAR_ID
    fps: int = 25
    batch_size: int = 32
    fallback_batch_size: int = 20
    gpu_id: int = 0

    @property
    def avatar_dir(self) -> Path:
        return (
            self.musetalk_dir
            / "results"
            / "v15"
            / "avatars"
            / self.avatar_id
        )

    @property
    def work_dir(self) -> Path:
        return self.musetalk_dir / "results" / "v15" / "service_tmp"


@dataclass(frozen=True)
class RenderOutcome:
    video: bytes
    elapsed_seconds: float
    frame_count: int


def load_local_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env", override=False)


def require_bridge_token(value: str | None = None) -> str:
    token = (value if value is not None else os.getenv(TOKEN_ENV, "")).strip()
    if (
        len(token) >= 32
        and not any(character.isspace() for character in token)
        and token != TOKEN_PLACEHOLDER
    ):
        return token
    raise RuntimeError(
        "TTS_BRIDGE_TOKEN must be a non-placeholder secret of at least 32 "
        "characters with no whitespace."
    )


def make_bearer_guard(expected_token: str):
    def require_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        scheme, separator, supplied = (authorization or "").partition(" ")
        valid = (
            bool(separator)
            and scheme.lower() == "bearer"
            and bool(supplied)
            and hmac.compare_digest(supplied, expected_token)
        )
        if not valid:
            raise HTTPException(
                401,
                "Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_bearer


def validate_wav(audio: bytes) -> None:
    if len(audio) < 44 or len(audio) > MAX_WAV_BYTES:
        raise InvalidWave("WAV body is empty, truncated, or too large")
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise InvalidWave("Request body must be a RIFF/WAVE file")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            frame_bytes = source.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise InvalidWave("Request body contains an invalid WAV file") from exc
    if channels != 1 or sample_width != 2 or sample_rate != 24000 or compression != "NONE":
        raise InvalidWave("WAV must be mono PCM16 at 24000 Hz")
    if frame_count <= 0 or frame_count / sample_rate > 30.0:
        raise InvalidWave("WAV duration must be greater than zero and at most 30 seconds")
    if len(frame_bytes) != frame_count * channels * sample_width:
        raise InvalidWave("WAV audio data is truncated")


def _safe_seconds(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and 0 <= parsed <= 3600 else 0.0


def _required_model_files(root: Path) -> tuple[Path, ...]:
    return (
        root / "models" / "musetalkV15" / "musetalk.json",
        root / "models" / "musetalkV15" / "unet.pth",
        root / "models" / "sd-vae" / "config.json",
        root / "models" / "sd-vae" / "diffusion_pytorch_model.bin",
        root / "models" / "whisper" / "config.json",
        root / "models" / "whisper" / "pytorch_model.bin",
        root / "models" / "whisper" / "preprocessor_config.json",
        root / "models" / "dwpose" / "dw-ll_ucoco_384.pth",
        root / "models" / "face-parse-bisent" / "79999_iter.pth",
        root
        / "musetalk"
        / "utils"
        / "face_detection"
        / "detection"
        / "sfd"
        / "s3fd.pth",
        root
        / "models"
        / "face-parse-bisent"
        / "resnet18-5c106cde.pth",
    )


def validate_avatar_cache(config: MuseTalkConfig) -> dict[str, Any]:
    """Reject partial caches instead of entering MuseTalk's interactive prompts."""
    avatar = config.avatar_dir
    required = (
        avatar / "latents.pt",
        avatar / "coords.pkl",
        avatar / "mask_coords.pkl",
        avatar / "avator_info.json",
    )
    missing = [path for path in required if not path.is_file()]
    for directory in (avatar / "full_imgs", avatar / "mask"):
        if not directory.is_dir() or not any(directory.iterdir()):
            missing.append(directory)
    if missing:
        raise RuntimeError(
            "MuseTalk avatar cache is incomplete; recreate the fixed avatar "
            "before starting the bridge"
        )
    try:
        info = json.loads((avatar / "avator_info.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("MuseTalk avatar metadata is invalid") from exc
    if (
        info.get("avatar_id") != config.avatar_id
        or info.get("version") != "v15"
        or info.get("bbox_shift") != 0
    ):
        raise RuntimeError("MuseTalk avatar metadata does not match this service")
    return info


class MuseTalkEngine:
    """Own the loaded MuseTalk models and one serialized inference worker."""

    def __init__(self, config: MuseTalkConfig):
        self.config = config
        self.lock = threading.Lock()
        self.loaded = False
        self.loaded_seconds = 0.0
        self.batch_size = config.batch_size
        self.phase = 0
        self.runtime: Any = None
        self.torch: Any = None
        self.cv2: Any = None
        self.avatar: Any = None

    def _validate_files(self) -> dict[str, Any]:
        if not (self.config.musetalk_dir / "scripts" / "realtime_inference.py").is_file():
            raise RuntimeError("MuseTalk source checkout was not found")
        missing = [path for path in _required_model_files(self.config.musetalk_dir) if not path.is_file()]
        if missing:
            raise RuntimeError(f"MuseTalk model files are incomplete ({len(missing)} missing)")
        if not self.config.ffmpeg.is_file():
            raise RuntimeError("ffmpeg executable was not found")
        return validate_avatar_cache(self.config)

    def load(self) -> None:
        started = time.perf_counter()
        avatar_info = self._validate_files()
        musetalk_dir = self.config.musetalk_dir
        if str(musetalk_dir) not in sys.path:
            sys.path.insert(0, str(musetalk_dir))
        # The official realtime module resolves its model and avatar paths from
        # the process cwd. This is a dedicated child process, so pinning it is
        # safer than allowing request data to influence any path.
        os.chdir(musetalk_dir)

        import cv2  # type: ignore
        import torch  # type: ignore
        from transformers import WhisperModel  # type: ignore
        from scripts import realtime_inference as runtime  # type: ignore

        if not torch.cuda.is_available():
            raise RuntimeError("MuseTalk requires a CUDA GPU")

        runtime.args = SimpleNamespace(
            version="v15",
            gpu_id=self.config.gpu_id,
            vae_type="sd-vae",
            unet_config=str(musetalk_dir / "models" / "musetalkV15" / "musetalk.json"),
            unet_model_path=str(musetalk_dir / "models" / "musetalkV15" / "unet.pth"),
            whisper_dir=str(musetalk_dir / "models" / "whisper"),
            inference_config="",
            bbox_shift=0,
            result_dir=str(musetalk_dir / "results"),
            extra_margin=10,
            fps=self.config.fps,
            audio_padding_length_left=2,
            audio_padding_length_right=2,
            batch_size=self.config.batch_size,
            output_vid_name=None,
            use_saved_coord=True,
            saved_coord=True,
            parsing_mode="jaw",
            left_cheek_width=90,
            right_cheek_width=90,
            skip_save_images=False,
        )
        runtime.device = torch.device(f"cuda:{self.config.gpu_id}")
        runtime.vae, runtime.unet, runtime.pe = runtime.load_all_model(
            unet_model_path=runtime.args.unet_model_path,
            vae_type=runtime.args.vae_type,
            unet_config=runtime.args.unet_config,
            device=runtime.device,
        )
        runtime.timesteps = torch.tensor([0], device=runtime.device)
        runtime.pe = runtime.pe.half().to(runtime.device)
        runtime.vae.vae = runtime.vae.vae.half().to(runtime.device)
        runtime.unet.model = runtime.unet.model.half().to(runtime.device)
        runtime.audio_processor = runtime.AudioProcessor(
            feature_extractor_path=runtime.args.whisper_dir
        )
        runtime.weight_dtype = runtime.unet.model.dtype
        runtime.whisper = WhisperModel.from_pretrained(runtime.args.whisper_dir)
        runtime.whisper = runtime.whisper.to(
            device=runtime.device,
            dtype=runtime.weight_dtype,
        ).eval()
        runtime.whisper.requires_grad_(False)
        runtime.fp = runtime.FaceParsing(
            left_cheek_width=runtime.args.left_cheek_width,
            right_cheek_width=runtime.args.right_cheek_width,
        )

        cached_source = Path(str(avatar_info.get("video_path", "")))
        source_video = cached_source if cached_source.is_file() else self.config.source_video
        self.avatar = runtime.Avatar(
            avatar_id=self.config.avatar_id,
            video_path=str(source_video),
            bbox_shift=0,
            batch_size=self.batch_size,
            preparation=False,
        )
        self.runtime = runtime
        self.torch = torch
        self.cv2 = cv2
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._warmup()
        except (RuntimeError, torch.cuda.OutOfMemoryError) as exc:
            if self.config.fallback_batch_size >= self.batch_size:
                raise
            print(
                f"MuseTalk batch {self.batch_size} warmup failed; retrying with "
                f"batch {self.config.fallback_batch_size}.",
                flush=True,
            )
            torch.cuda.empty_cache()
            self.batch_size = self.config.fallback_batch_size
            self.avatar.batch_size = self.batch_size
            self._warmup()

        self._release_gpu_cache()
        self.loaded = True
        self.loaded_seconds = time.perf_counter() - started
        print(
            f"MuseTalk ready in {self.loaded_seconds:.1f}s "
            f"(batch {self.batch_size}, avatar {self.config.avatar_id}).",
            flush=True,
        )

    def _write_silence(self, path: Path, seconds: float = WARMUP_SECONDS) -> None:
        sample_rate = 24000
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(b"\x00\x00" * int(sample_rate * seconds))

    def _warmup(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="warmup-", dir=self.config.work_dir
        ) as temporary:
            audio = Path(temporary) / "warmup.wav"
            self._write_silence(audio)
            self._infer(audio, None)

    def _infer(self, audio_path: Path, frame_sink: FrameSink | None) -> int:
        with self.torch.inference_mode():
            return self._infer_without_grad(audio_path, frame_sink)

    def _infer_without_grad(
        self,
        audio_path: Path,
        frame_sink: FrameSink | None,
    ) -> int:
        runtime = self.runtime
        avatar = self.avatar
        whisper_features, librosa_length = runtime.audio_processor.get_audio_feature(
            str(audio_path), weight_dtype=runtime.weight_dtype
        )
        chunks = runtime.audio_processor.get_whisper_chunk(
            whisper_features,
            runtime.device,
            runtime.weight_dtype,
            runtime.whisper,
            librosa_length,
            fps=self.config.fps,
            audio_padding_length_left=runtime.args.audio_padding_length_left,
            audio_padding_length_right=runtime.args.audio_padding_length_right,
        )
        frame_count = len(chunks)
        if frame_count <= 0:
            raise RuntimeError("MuseTalk produced no audio feature frames")

        # Unbounded avoids a deadlock if the compositor fails while the GPU
        # producer is still draining a decoded batch. Requests are serialized
        # and their total frame count is bounded by the input WAV size.
        result_queue: queue.Queue[Any] = queue.Queue()
        sentinel = object()
        worker_errors: list[BaseException] = []

        def compose_frames() -> None:
            index = 0
            try:
                while True:
                    result_frame = result_queue.get()
                    if result_frame is sentinel:
                        break
                    cycle_index = (self.phase + index) % len(avatar.frame_list_cycle)
                    bbox = avatar.coord_list_cycle[cycle_index]
                    original = copy.deepcopy(avatar.frame_list_cycle[cycle_index])
                    x1, y1, x2, y2 = bbox
                    if x2 > x1 and y2 > y1:
                        resized = self.cv2.resize(
                            result_frame.astype("uint8"),
                            (x2 - x1, y2 - y1),
                        )
                        original = runtime.get_image_blending(
                            original,
                            resized,
                            bbox,
                            avatar.mask_list_cycle[cycle_index],
                            avatar.mask_coords_list_cycle[cycle_index],
                        )
                    if frame_sink is not None:
                        frame_sink(original)
                    index += 1
            except BaseException as exc:  # noqa: BLE001 - relayed to request thread
                worker_errors.append(exc)

        worker = threading.Thread(
            target=compose_frames,
            name="musetalk-frame-compositor",
            daemon=True,
        )
        worker.start()
        try:
            batches = runtime.datagen(
                chunks,
                avatar.input_latent_list_cycle,
                self.batch_size,
                delay_frame=self.phase,
                device=runtime.device,
            )
            produced = 0
            for whisper_batch, latent_batch in batches:
                audio_features = runtime.pe(whisper_batch.to(runtime.device))
                latent_batch = latent_batch.to(
                    device=runtime.device,
                    dtype=runtime.unet.model.dtype,
                )
                predicted = runtime.unet.model(
                    latent_batch,
                    runtime.timesteps,
                    encoder_hidden_states=audio_features,
                ).sample
                predicted = predicted.to(
                    device=runtime.device,
                    dtype=runtime.vae.vae.dtype,
                )
                for result_frame in runtime.vae.decode_latents(predicted):
                    result_queue.put(result_frame)
                    produced += 1
        finally:
            result_queue.put(sentinel)
            worker.join()
        if worker_errors:
            raise RuntimeError("MuseTalk frame compositing failed") from worker_errors[0]
        if produced != frame_count:
            raise RuntimeError(
                f"MuseTalk frame count mismatch ({produced} != {frame_count})"
            )
        return frame_count

    def encoder_command(
        self,
        wav_path: Path,
        output_video: Path,
        width: int,
        height: int,
    ) -> list[str]:
        """Build the single ffmpeg pass that reads frames from stdin.

        Saving every frame as a PNG and then re-encoding those files cost more
        wall time than the GPU inference itself, so a short reply took about
        three times its own audio length. Piping raw frames straight into one
        muxing pass removes both the disk round trip and the second decode.
        """
        return [
            str(self.config.ffmpeg),
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(self.config.fps),
            "-i",
            "pipe:0",
            "-i",
            str(wav_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            ENCODER_PRESET,
            "-crf",
            str(ENCODER_CRF),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_video),
        ]

    def _release_gpu_cache(self) -> None:
        """Return the inference peak to the driver instead of hoarding it.

        MuseTalk now has the GPU to itself (TTS moved to the ElevenLabs API),
        but PyTorch's caching allocator still holds the batch VAE decode peak
        indefinitely if left alone. That used to starve a second local process
        (Chatterbox) into host-memory fallback; releasing it here is now just
        good hygiene for a long-running resident worker.
        """
        if self.torch is None:
            return
        try:
            self.torch.cuda.empty_cache()
        except RuntimeError:
            # Reclaiming memory is an optimization; never fail a served request.
            pass

    def _stop_encoder(self, encoder: subprocess.Popen) -> None:
        """Never leave an ffmpeg child behind when inference fails."""
        if encoder.stdin is not None and not encoder.stdin.closed:
            try:
                encoder.stdin.close()
            except OSError:
                pass
        if encoder.poll() is None:
            encoder.kill()
        try:
            encoder.wait(timeout=ENCODER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass

    def render(self, audio: bytes) -> RenderOutcome:
        validate_wav(audio)
        if not self.loaded:
            raise RuntimeError("MuseTalk is not ready")
        if not self.lock.acquire(blocking=False):
            raise MuseTalkBusy("MuseTalk is busy")
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(
                prefix=f"request-{uuid.uuid4().hex}-",
                dir=self.config.work_dir,
            ) as temporary:
                directory = Path(temporary)
                wav_path = directory / "speech.wav"
                output_video = directory / "result.mp4"
                encoder_log = directory / "ffmpeg.log"
                wav_path.write_bytes(audio)

                height, width = self.avatar.frame_list_cycle[0].shape[:2]
                expected_shape = (height, width, 3)
                command = self.encoder_command(wav_path, output_video, width, height)
                with open(encoder_log, "wb") as log:
                    encoder = subprocess.Popen(
                        command,
                        cwd=self.config.musetalk_dir,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=log,
                    )

                def write_frame(frame) -> None:
                    # A single mis-sized frame would silently shear every later
                    # frame, so fail loudly instead of shipping a broken video.
                    if frame.shape != expected_shape:
                        raise RuntimeError("MuseTalk produced an unexpected frame size")
                    encoder.stdin.write(frame.tobytes())

                try:
                    frame_count = self._infer(wav_path, write_frame)
                    encoder.stdin.close()
                    returncode = encoder.wait(timeout=ENCODER_TIMEOUT_SECONDS)
                except BaseException:
                    self._stop_encoder(encoder)
                    raise
                if returncode != 0:
                    detail = encoder_log.read_bytes()[-500:].decode("utf-8", "replace")
                    print(f"ffmpeg exited with {returncode}: {detail}", flush=True)
                    raise RuntimeError("ffmpeg could not assemble the lip-sync video")

                video = output_video.read_bytes()
                if (
                    len(video) < 12
                    or len(video) > MAX_VIDEO_BYTES
                    or video[4:8] != b"ftyp"
                ):
                    raise RuntimeError("MuseTalk produced an invalid MP4")
            self.phase = (self.phase + frame_count) % len(self.avatar.frame_list_cycle)
            return RenderOutcome(
                video=video,
                elapsed_seconds=time.perf_counter() - started,
                frame_count=frame_count,
            )
        finally:
            self._release_gpu_cache()
            self.lock.release()


def create_app(engine: Any, bridge_token: str | None = None) -> FastAPI:
    require_bearer = make_bearer_guard(require_bridge_token(bridge_token))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine.load()
        yield

    app = FastAPI(
        title="Memory Call Local MuseTalk",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", dependencies=[Depends(require_bearer)])
    def health():
        return {
            "ok": bool(getattr(engine, "loaded", False)),
            "model": "musetalk-v1.5",
            "avatar": getattr(getattr(engine, "config", None), "avatar_id", None),
            "batch_size": getattr(engine, "batch_size", None),
            "load_seconds": round(_safe_seconds(getattr(engine, "loaded_seconds", 0)), 2),
        }

    @app.post("/render", dependencies=[Depends(require_bearer)])
    async def render(request: Request):
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "audio/wav":
            raise HTTPException(415, "Content-Type must be audio/wav")
        content_length = request.headers.get("Content-Length")
        try:
            declared_length = int(content_length) if content_length else None
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length") from exc
        if declared_length is not None and declared_length < 0:
            raise HTTPException(400, "Invalid Content-Length")
        if declared_length is not None and declared_length > MAX_WAV_BYTES:
            raise HTTPException(413, "WAV body is too large")
        audio = await request.body()
        try:
            validate_wav(audio)
            outcome = await run_in_threadpool(engine.render, audio)
        except InvalidWave as exc:
            raise HTTPException(400, str(exc)) from exc
        except MuseTalkBusy as exc:
            raise HTTPException(409, str(exc), headers={"Retry-After": "1"}) from exc
        except Exception as exc:  # noqa: BLE001
            print(f"MuseTalk render failed ({type(exc).__name__}).", flush=True)
            raise HTTPException(503, "MuseTalk rendering failed") from exc

        seconds = _safe_seconds(outcome.elapsed_seconds)
        return Response(
            content=outcome.video,
            media_type="video/mp4",
            headers={
                "Cache-Control": "no-store",
                "X-Lipsync-Seconds": f"{seconds:.3f}",
                "X-Lipsync-Frames": str(max(0, int(outcome.frame_count))),
                "Server-Timing": f"lipsync;dur={seconds * 1000:.2f}",
            },
        )

    return app


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _default_musetalk_dir() -> Path:
    configured = os.getenv("MEMORY_CALL_MUSETALK_DIR", "").strip()
    return Path(configured) if configured else ROOT.parent / "Models" / "MuseTalk"


def _default_ffmpeg() -> Path:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_dir():
            candidate = candidate / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        return candidate
    repository = ROOT / ".tools" / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    found = shutil.which("ffmpeg")
    return repository if repository.is_file() or not found else Path(found)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the loopback MuseTalk worker.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--musetalk-dir", type=Path, default=_default_musetalk_dir())
    parser.add_argument(
        "--source-video",
        type=Path,
        default=ROOT / "data" / "faces" / "loops" / "idle.mp4",
    )
    parser.add_argument("--ffmpeg", type=Path, default=_default_ffmpeg())
    parser.add_argument("--avatar-id", default=DEFAULT_AVATAR_ID)
    parser.add_argument("--batch-size", type=_positive_int, default=32)
    parser.add_argument("--fallback-batch-size", type=_positive_int, default=20)
    parser.add_argument("--gpu-id", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("MuseTalk must bind to loopback only.", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print("MuseTalk port must be between 1 and 65535.", file=sys.stderr)
        return 2
    try:
        token = require_bridge_token()
        config = MuseTalkConfig(
            musetalk_dir=args.musetalk_dir.resolve(),
            source_video=args.source_video.resolve(),
            ffmpeg=args.ffmpeg.resolve(),
            avatar_id=args.avatar_id,
            batch_size=args.batch_size,
            fallback_batch_size=args.fallback_batch_size,
            gpu_id=args.gpu_id,
        )
        app = create_app(MuseTalkEngine(config), token)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"MuseTalk configuration error: {exc}", file=sys.stderr)
        return 2
    print(f"MuseTalk loopback service: http://{args.host}:{args.port}")
    print("TTS_BRIDGE_TOKEN: configured (value hidden)")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
