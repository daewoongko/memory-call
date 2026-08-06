"""Generate a target-age anchor with the FRAN residual face re-aging model."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from insightface.app import FaceAnalysis
from PIL import Image
from torchvision.transforms import InterpolationMode
from torchvision.transforms import functional as TF


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from fran_vendor.model import UNet  # noqa: E402
from storage import AGE_ANCHORS_DIR, AGE_PLAN_PATH, SOURCE_FACES_DIR  # noqa: E402


MODEL_PATH = Path(
    os.getenv(
        "REAGING_MODEL_PATH",
        str(Path.home() / "Models" / "face_reaging" / "best_unet_model.pth"),
    )
).expanduser().resolve()
MASK_PATH = ROOT / "data" / "faces" / "age_mask" / "current_change_mask.png"
FRAN_ASSETS = ROOT / "tools" / "fran_vendor" / "assets"
OUTPUT_DIR = ROOT / "data" / "faces" / "age_candidates"
DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"
INSIGHTFACE_ROOT = Path.home() / ".insightface"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
PARENT_AGES = {20: 25, 16: 20, 12: 16, 8: 12}

# FRAN is deterministic. Nearby conditioning ages provide calibrated candidates.
CONDITIONING_AGES = {
    20: (17, 18, 19, 20),
    # The model's perceived-age response becomes weak when recursively applied
    # to an already re-aged image. Younger stages therefore start from the
    # clean current photo and probe a wider conditioning range.
    16: (5, 8, 11, 14),
    12: (0, 3, 6, 9),
    8: (0, 2, 4, 6),
}
RESIDUAL_SCALES = (1.0, 0.85, 0.70, 0.55)

# Strict 25 -> 20 identity and adjacent-stage continuity gates.
MIN_REFERENCE = 0.75
MEAN_REFERENCE = 0.80
MAX_REFERENCE = 0.88
PARENT_SIMILARITY = 0.88


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, default=20)
    parser.add_argument("--window-size", type=int, default=512)
    parser.add_argument("--stride", type=int, default=256)
    return parser.parse_args()


def read_rgb(path: Path) -> np.ndarray:
    bgr = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def write_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError(f"Cannot encode image: {path}")
    encoded.tofile(path)


def largest_face(app: FaceAnalysis, rgb: np.ndarray):
    faces = app.get(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not faces:
        raise ValueError("No face detected")
    return max(
        faces,
        key=lambda face: float(
            (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
        ),
    )


def make_analyzer(name: str, *, include_age: bool = False) -> FaceAnalysis:
    allowed = None if include_age else ["detection", "recognition"]
    app = FaceAnalysis(
        name=name,
        root=str(INSIGHTFACE_ROOT),
        allowed_modules=allowed,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_thresh=0.5, det_size=(640, 640))
    return app


def collect_reference_embeddings(app: FaceAnalysis) -> np.ndarray:
    paths = sorted(
        path
        for path in SOURCE_FACES_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not paths:
        raise FileNotFoundError(f"No identity references in {SOURCE_FACES_DIR}")
    return np.stack(
        [largest_face(app, read_rgb(path)).normed_embedding.copy() for path in paths]
    )


def load_gray_tensor(path: Path, size: int) -> torch.Tensor:
    with Image.open(path) as opened:
        image = opened.convert("L").resize((size, size), Image.Resampling.BILINEAR)
    return torch.from_numpy(np.asarray(image, dtype=np.float32) / 255.0)


def face_crop_bounds(face, image_shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    """Match the crop proportions used by the official FRAN demo."""
    height, width = image_shape[:2]
    x1, y1, x2, y2 = [float(value) for value in face.bbox]
    face_width = x2 - x1
    face_height = y2 - y1
    margin_x = face_width * 0.425
    margin_top = face_height * 0.5355
    margin_bottom = face_height * 0.3145
    # The official demo expands the upper margin once more so that the crop is
    # square before it is resized. This prevents subtle face stretching.
    margin_top += 2 * margin_x - margin_top - margin_bottom
    left = max(0, int(round(x1 - margin_x)))
    right = min(width, int(round(x2 + margin_x)))
    top = max(0, int(round(y1 - margin_top)))
    bottom = min(height, int(round(y2 + margin_bottom)))
    if right - left < 128 or bottom - top < 128:
        raise RuntimeError("Detected face crop is unexpectedly small")
    return left, top, right, bottom


def infer_residual(
    model: UNet,
    crop_rgb: np.ndarray,
    source_age: int,
    conditioning_age: int,
    window_size: int,
    stride: int,
) -> np.ndarray:
    device = next(model.parameters()).device
    crop_tensor = TF.to_tensor(Image.fromarray(crop_rgb)).to(torch.float32)
    crop_tensor = TF.resize(
        crop_tensor,
        [1024, 1024],
        interpolation=InterpolationMode.BILINEAR,
        antialias=True,
    )
    source_channel = torch.full_like(crop_tensor[:1], source_age / 100.0)
    target_channel = torch.full_like(crop_tensor[:1], conditioning_age / 100.0)
    input_tensor = torch.cat(
        [crop_tensor, source_channel, target_channel], dim=0
    ).unsqueeze(0).to(device)

    large_mask = load_gray_tensor(FRAN_ASSETS / "mask1024.jpg", 1024).to(device)
    small_mask = load_gray_tensor(
        FRAN_ASSETS / "mask512.jpg", window_size
    ).to(device)
    output = torch.zeros((1, 3, 1024, 1024), device=device)
    count = torch.zeros_like(output)

    with torch.inference_mode():
        for y in range(0, 1024 - window_size + 1, stride):
            for x in range(0, 1024 - window_size + 1, stride):
                window = input_tensor[:, :, y : y + window_size, x : x + window_size]
                residual = model(window)
                output[:, :, y : y + window_size, x : x + window_size] += (
                    residual * small_mask
                )
                count[:, :, y : y + window_size, x : x + window_size] += small_mask
    output /= torch.clamp(count, min=1.0)
    output *= large_mask
    return output.squeeze(0).detach().cpu().permute(1, 2, 0).numpy()


def apply_residual(
    parent_rgb: np.ndarray,
    bounds: tuple[int, int, int, int],
    residual_1024: np.ndarray,
    scale: float,
) -> np.ndarray:
    left, top, right, bottom = bounds
    crop_height = bottom - top
    crop_width = right - left
    residual = cv2.resize(
        residual_1024,
        (crop_width, crop_height),
        interpolation=cv2.INTER_LINEAR,
    )
    output = parent_rgb.astype(np.float32) / 255.0
    output[top:bottom, left:right] += residual * scale
    return np.rint(np.clip(output, 0.0, 1.0) * 255.0).astype(np.uint8)


def protect_outside_mask(
    candidate_rgb: np.ndarray,
    parent_rgb: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, float]:
    alpha = mask.astype(np.float32)[:, :, None] / 255.0
    output = np.rint(
        candidate_rgb.astype(np.float32) * alpha
        + parent_rgb.astype(np.float32) * (1.0 - alpha)
    ).clip(0, 255).astype(np.uint8)
    protected = mask == 0
    output[protected] = parent_rgb[protected]
    difference = np.abs(
        output[protected].astype(np.int16) - parent_rgb[protected].astype(np.int16)
    )
    return output, float(difference.max()) if difference.size else 0.0


def identity_metrics(
    candidate_rgb: np.ndarray,
    references: np.ndarray,
    parent_embedding: np.ndarray,
    app: FaceAnalysis,
) -> dict:
    face = largest_face(app, candidate_rgb)
    scores = references @ face.normed_embedding
    return {
        "similarity_min": round(float(scores.min()), 4),
        "similarity_mean": round(float(scores.mean()), 4),
        "similarity_max": round(float(scores.max()), 4),
        "parent_similarity": round(
            float(parent_embedding @ face.normed_embedding), 4
        ),
        "face_detection_score": round(float(face.det_score), 4),
    }


def passes_identity(metrics: dict) -> bool:
    return (
        metrics["similarity_min"] >= MIN_REFERENCE
        and metrics["similarity_mean"] >= MEAN_REFERENCE
        and metrics["similarity_max"] >= MAX_REFERENCE
        and metrics["parent_similarity"] >= PARENT_SIMILARITY
    )


def current_source() -> tuple[int, Path]:
    if not AGE_PLAN_PATH.is_file():
        raise FileNotFoundError(f"Missing age plan: {AGE_PLAN_PATH}")
    plan = json.loads(AGE_PLAN_PATH.read_text(encoding="utf-8"))
    age = plan.get("current_age")
    filename = Path(str(plan.get("current_photo") or "")).name
    path = SOURCE_FACES_DIR / filename
    if not isinstance(age, int) or not path.is_file():
        raise ValueError("The current-age source photo is not configured correctly")
    return age, path


def validate(args: argparse.Namespace) -> tuple[int, Path, int, Path]:
    if args.age not in PARENT_AGES:
        raise ValueError(f"Supported ages: {sorted(PARENT_AGES)}")
    if args.window_size != 512 or args.stride != 256:
        raise ValueError("The official checkpoint is calibrated for window=512, stride=256")
    parent_age = PARENT_AGES[args.age]
    parent_path = AGE_ANCHORS_DIR / f"age{parent_age:02d}.png"
    if args.age == 20:
        source_age, source_path = parent_age, parent_path
    else:
        source_age, source_path = current_source()
    required = [
        source_path,
        parent_path,
        MODEL_PATH,
        MASK_PATH,
        FRAN_ASSETS / "mask512.jpg",
        FRAN_ASSETS / "mask1024.jpg",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required files:\n" + "\n".join(missing))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable")
    return source_age, source_path, parent_age, parent_path


def main() -> None:
    args = parse_args()
    source_age, source_path, parent_age, parent_path = validate(args)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    source_rgb = read_rgb(source_path)
    parent_rgb = read_rgb(parent_path)

    approved_mask = cv2.imdecode(
        np.fromfile(MASK_PATH, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    if approved_mask is None:
        raise ValueError(f"Cannot read approved mask: {MASK_PATH}")
    approved_mask = cv2.resize(
        approved_mask,
        (source_rgb.shape[1], source_rgb.shape[0]),
        interpolation=cv2.INTER_LANCZOS4,
    )

    print(f"FRAN stage: age {source_age} -> age {args.age}")
    print(f"Generation source: {source_path}")
    print(f"Parent anchor: {parent_path}")
    print("Loading identity and age analyzers on CPU...")
    age_app = make_analyzer("antelopev2", include_age=True)
    identity_app = make_analyzer("buffalo_l")
    age_face = largest_face(age_app, source_rgb)
    parent_identity = largest_face(identity_app, parent_rgb)
    references = collect_reference_embeddings(identity_app)
    bounds = face_crop_bounds(age_face, source_rgb.shape)
    left, top, right, bottom = bounds
    crop_rgb = source_rgb[top:bottom, left:right]
    write_rgb(DEBUG_DIR / f"age{source_age:02d}_fran_crop.png", crop_rgb)

    print("Loading official FRAN U-Net on GPU...")
    device = torch.device("cuda")
    model = UNet().to(device)
    state = torch.load(MODEL_PATH, map_location=device, weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()

    selected = []
    all_results = []
    for conditioning_age in CONDITIONING_AGES[args.age]:
        print(f"\nFRAN conditioning age {conditioning_age}...")
        residual = infer_residual(
            model,
            crop_rgb,
            source_age,
            conditioning_age,
            args.window_size,
            args.stride,
        )
        chosen = None
        for residual_scale in RESIDUAL_SCALES:
            full_rgb = apply_residual(source_rgb, bounds, residual, residual_scale)
            candidate_rgb, protected_change = protect_outside_mask(
                full_rgb, source_rgb, approved_mask
            )
            metrics = identity_metrics(
                candidate_rgb,
                references,
                parent_identity.normed_embedding,
                identity_app,
            )
            estimated_face = largest_face(age_app, candidate_rgb)
            estimated_age = int(estimated_face.age)
            identity_pass = passes_identity(metrics)
            age_pass = args.age - 2 <= estimated_age <= args.age + 2
            passed = identity_pass and age_pass
            result = {
                "target_age": args.age,
                "source_age": source_age,
                "parent_age": parent_age,
                "conditioning_age": conditioning_age,
                "residual_scale": residual_scale,
                "estimated_age": estimated_age,
                "protected_area_max_pixel_change": protected_change,
                **metrics,
                "identity_pass": identity_pass,
                "age_pass": age_pass,
                "full_pass": passed,
            }
            all_results.append(result)
            print(
                f"  scale={residual_scale:.2f} age={estimated_age:2d} "
                f"mean={metrics['similarity_mean']:.4f} "
                f"max={metrics['similarity_max']:.4f} "
                f"parent={metrics['parent_similarity']:.4f} "
                f"{'PASS' if passed else 'FAIL'}"
            )
            debug_name = (
                f"age{args.age:02d}_fran_t{conditioning_age:02d}_"
                f"r{round(residual_scale * 100):03d}.png"
            )
            write_rgb(DEBUG_DIR / debug_name, candidate_rgb)
            if passed and chosen is None:
                chosen = (candidate_rgb, result)

        if chosen is not None:
            candidate_rgb, result = chosen
            output_name = (
                f"age{args.age:02d}_fran_t{conditioning_age:02d}_"
                f"r{round(result['residual_scale'] * 100):03d}_review.png"
            )
            output_path = OUTPUT_DIR / output_name
            write_rgb(output_path, candidate_rgb)
            output_path.with_suffix(".json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            selected.append({"output": output_name, **result})
            print(f"Saved strict-pass candidate: {output_path}")

    elapsed = time.perf_counter() - started
    peak_gb = torch.cuda.max_memory_allocated() / (1024**3)
    summary = {
        "target_age": args.age,
        "source_age": source_age,
        "source_photo": source_path.name,
        "parent_age": parent_age,
        "parent_anchor": parent_path.name,
        "model": "FRAN face_reaging",
        "selected": selected,
        "all_results": all_results,
        "elapsed_seconds": round(elapsed, 1),
        "peak_cuda_gb": round(peak_gb, 2),
    }
    summary_path = DEBUG_DIR / f"age{args.age:02d}_fran_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nFRAN age-{args.age} generation complete")
    print(f"Strict-pass candidates: {len(selected)}/{len(CONDITIONING_AGES[args.age])}")
    print(f"Total time: {elapsed:.1f}s")
    print(f"Peak CUDA memory: {peak_gb:.2f}GB")
    print(f"Summary: {summary_path}")

    del model, age_app, identity_app
    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
