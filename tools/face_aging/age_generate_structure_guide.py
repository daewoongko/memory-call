"""Generate low-frequency age-structure guides with the FRAN residual model.

The guides are not final portraits.  They provide a population-trained aging
direction to FLUX while the accepted parent, identity LoRA, and current-photo
embeddings remain responsible for continuity and identity.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "face_aging"))

import age_timeline  # noqa: E402
from age_generate_fran import (  # noqa: E402
    FRAN_ASSETS,
    MASK_PATH,
    MODEL_PATH,
    UNet,
    apply_residual,
    face_crop_bounds,
    infer_residual,
    largest_face,
    make_analyzer,
    protect_outside_mask,
    read_rgb,
    write_rgb,
)
from storage import AGE_CANDIDATES_DIR, SOURCE_FACES_DIR  # noqa: E402


GUIDE_DIR = ROOT / "data" / "faces" / "age_debug" / "structure_guides"
DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, required=True)
    parser.add_argument(
        "--conditioning-offsets",
        type=int,
        nargs="+",
        default=[2, 3],
        help="FRAN set-points below the real target; zipped with residual scales.",
    )
    parser.add_argument(
        "--residual-scales", type=float, nargs="+", default=[1.0, 0.85]
    )
    parser.add_argument("--window-size", type=int, default=512)
    parser.add_argument("--stride", type=int, default=256)
    parser.add_argument(
        "--lock-mouth-expression",
        action="store_true",
        help=(
            "Restore the accepted parent's lips and mouth corners with a "
            "feathered local mask after FRAN structure transfer."
        ),
    )
    parser.add_argument(
        "--restore-parent-appearance",
        action="store_true",
        help=(
            "Transfer only low-frequency FRAN change while restoring the "
            "accepted parent's skin tone and high-frequency texture."
        ),
    )
    return parser.parse_args()


def preserve_parent_mouth_expression(
    parent_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    keypoints: np.ndarray,
) -> tuple[np.ndarray, dict]:
    """Prevent FRAN age residuals from introducing a parted-mouth expression."""
    points = np.asarray(keypoints, dtype=np.float32)
    if points.shape != (5, 2):
        raise ValueError("Mouth expression lock requires five facial keypoints")
    mouth_left, mouth_right = points[3], points[4]
    mouth_width = float(np.linalg.norm(mouth_right - mouth_left))
    if mouth_width <= 1.0:
        raise ValueError("Detected mouth keypoints are degenerate")

    center_x, center_y = ((mouth_left + mouth_right) / 2.0).tolist()
    radius_x = max(4.0, mouth_width * 0.70)
    radius_y = max(3.0, mouth_width * 0.34)
    height, width = parent_rgb.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    distance = np.sqrt(
        ((xx - center_x) / radius_x) ** 2
        + ((yy - center_y) / radius_y) ** 2
    )
    # Full parent preservation through the lips, then a broad smooth feather
    # so the copied expression does not create a visible boundary.
    alpha = np.clip((1.18 - distance) / 0.33, 0.0, 1.0).astype(np.float32)
    alpha = alpha[:, :, None]
    output = np.rint(
        parent_rgb.astype(np.float32) * alpha
        + candidate_rgb.astype(np.float32) * (1.0 - alpha)
    ).clip(0, 255).astype(np.uint8)
    return output, {
        "mode": "accepted_parent_mouth_soft_lock_v1",
        "center_xy": [round(center_x, 2), round(center_y, 2)],
        "radius_xy": [round(radius_x, 2), round(radius_y, 2)],
        "mouth_keypoint_width_px": round(mouth_width, 2),
    }


def restore_parent_appearance(
    parent_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    face_mask: np.ndarray,
) -> tuple[np.ndarray, dict]:
    """Preserve candidate geometry while correcting only skin appearance drift.

    Rebuilding the output as ``parent + blurred(candidate - parent)`` also
    blurred the edge-pair residuals that move the jaw, cheeks, and lower face.
    The result was nearly identical to the parent.  This version starts from
    the candidate and applies color/texture correction only on low-gradient
    skin, leaving FRAN's structural displacement intact.
    """
    parent_ycrcb = cv2.cvtColor(parent_rgb, cv2.COLOR_RGB2YCrCb)
    candidate_ycrcb = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2YCrCb)
    parent_f = parent_ycrcb.astype(np.float32)
    candidate_f = candidate_ycrcb.astype(np.float32)

    def skin_pixels(image: np.ndarray) -> np.ndarray:
        return (
            (image[:, :, 0] >= 55)
            & (image[:, :, 1] >= 125)
            & (image[:, :, 1] <= 180)
            & (image[:, :, 2] >= 75)
            & (image[:, :, 2] <= 135)
        )

    skin = (
        (face_mask >= 96)
        & skin_pixels(parent_ycrcb)
        & skin_pixels(candidate_ycrcb)
    )

    # Eyes, brows, nostrils, lips, and the face boundary carry structural
    # displacement.  Excluding high-gradient pixels prevents the appearance
    # correction from undoing that geometry or creating doubled features.
    parent_y = parent_f[:, :, 0]
    candidate_y = candidate_f[:, :, 0]
    parent_gradient = cv2.magnitude(
        cv2.Sobel(parent_y, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(parent_y, cv2.CV_32F, 0, 1, ksize=3),
    )
    candidate_gradient = cv2.magnitude(
        cv2.Sobel(candidate_y, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(candidate_y, cv2.CV_32F, 0, 1, ksize=3),
    )
    gradient_limit = 0.0
    stable_skin = skin
    if int(skin.sum()) >= 100:
        combined_gradient = np.maximum(parent_gradient, candidate_gradient)
        gradient_limit = float(np.percentile(combined_gradient[skin], 65.0))
        stable_skin = skin & (combined_gradient <= gradient_limit)

    alpha = cv2.GaussianBlur(
        stable_skin.astype(np.float32), (0, 0), sigmaX=3.0, sigmaY=3.0
    )
    alpha *= np.clip(face_mask.astype(np.float32) / 255.0, 0.0, 1.0)

    color_offset = np.zeros(3, dtype=np.float32)
    corrected = candidate_f.copy()
    if int(stable_skin.sum()) >= 100:
        color_offset = np.median(
            candidate_f[stable_skin] - parent_f[stable_skin], axis=0
        )
        # Preserve FRAN shading/volume.  Only a tiny global luminance drift is
        # removed, while chroma is matched more directly to the parent.
        color_offset[0] = np.clip(color_offset[0], -3.0, 3.0)
        corrected[:, :, 0] -= color_offset[0] * alpha
        corrected[:, :, 1] -= color_offset[1] * alpha
        corrected[:, :, 2] -= color_offset[2] * alpha

        parent_high = parent_y - cv2.GaussianBlur(
            parent_y, (0, 0), sigmaX=1.25, sigmaY=1.25
        )
        candidate_high = candidate_y - cv2.GaussianBlur(
            candidate_y, (0, 0), sigmaX=1.25, sigmaY=1.25
        )
        texture_delta = np.clip(parent_high - candidate_high, -6.0, 6.0)
        corrected[:, :, 0] += texture_delta * alpha * 0.55

    corrected = np.rint(corrected).clip(0, 255).astype(np.uint8)
    restored = cv2.cvtColor(corrected, cv2.COLOR_YCrCb2RGB)
    return restored, {
        "mode": "candidate_geometry_skin_appearance_restore_v2",
        "skin_sample_pixels": int(skin.sum()),
        "stable_skin_pixels": int(stable_skin.sum()),
        "gradient_percentile": 65.0,
        "gradient_limit": round(gradient_limit, 4),
        "skin_alpha_mean": round(float(alpha.mean()), 6),
        "texture_sigma": 1.25,
        "texture_restore_fraction": 0.55,
        "removed_rgb_offset": [round(float(value), 4) for value in color_offset],
    }


def resolve_parent(target_age: int) -> tuple[dict, int, Path]:
    plan = age_timeline.get_plan()
    if not plan.get("configured"):
        raise RuntimeError("Configure the current age and representative photo first")
    path = [int(age) for age in plan.get("generation_path") or []]
    if target_age not in path[1:]:
        raise ValueError(f"Target age {target_age} is not in the saved path: {path}")
    index = path.index(target_age)
    parent_age = path[index - 1]
    if parent_age == int(plan["current_age"]):
        parent_path = SOURCE_FACES_DIR / Path(str(plan["current_photo"])).name
    else:
        stage = next(
            (item for item in plan["stages"] if int(item["age"]) == parent_age),
            None,
        )
        selected = Path(str((stage or {}).get("selected") or "")).name
        if not selected:
            raise RuntimeError(
                f"Select an accepted age-{parent_age} parent before age {target_age}"
            )
        parent_path = AGE_CANDIDATES_DIR / selected
    if not parent_path.is_file():
        raise FileNotFoundError(parent_path)
    return plan, parent_age, parent_path


def main() -> None:
    args = parse_args()
    if len(args.conditioning_offsets) != len(args.residual_scales):
        raise ValueError("conditioning offsets and residual scales must have equal length")
    if not 1 <= len(args.conditioning_offsets) <= 4:
        raise ValueError("Generate between one and four structure guides")
    if any(offset < 0 for offset in args.conditioning_offsets):
        raise ValueError("conditioning offsets must be non-negative")
    if any(not 0.25 <= scale <= 1.0 for scale in args.residual_scales):
        raise ValueError("residual scales must be between 0.25 and 1.0")
    if args.window_size != 512 or args.stride != 256:
        raise ValueError("The FRAN checkpoint requires window=512 and stride=256")
    plan, parent_age, parent_path = resolve_parent(args.age)
    if parent_age <= args.age:
        raise ValueError("The parent must be older than the target")
    required = [
        MODEL_PATH,
        MASK_PATH,
        FRAN_ASSETS / "mask512.jpg",
        FRAN_ASSETS / "mask1024.jpg",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing FRAN resources:\n" + "\n".join(missing))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable")

    parent_rgb = read_rgb(parent_path)
    mask = cv2.imdecode(np.fromfile(MASK_PATH, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"Cannot read mask: {MASK_PATH}")
    mask = cv2.resize(
        mask,
        (parent_rgb.shape[1], parent_rgb.shape[0]),
        interpolation=cv2.INTER_LANCZOS4,
    )
    analyzer = make_analyzer("antelopev2", include_age=True)
    face = largest_face(analyzer, parent_rgb)
    bounds = face_crop_bounds(face, parent_rgb.shape)
    left, top, right, bottom = bounds
    crop = parent_rgb[top:bottom, left:right]

    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Structure-guide stage: {parent_age} -> {args.age}")
    print(f"Accepted parent: {parent_path.name}")
    print("Loading FRAN population aging prior on GPU...")
    model = UNet().cuda()
    state = torch.load(MODEL_PATH, map_location="cuda", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    outputs = []

    for offset, scale in zip(args.conditioning_offsets, args.residual_scales):
        conditioning_age = max(0, args.age - int(offset))
        print(
            f"FRAN guide: chronological target {args.age}, "
            f"internal set-point {conditioning_age}, residual {scale:.2f}"
        )
        residual = infer_residual(
            model,
            crop,
            parent_age,
            conditioning_age,
            args.window_size,
            args.stride,
        )
        changed = apply_residual(parent_rgb, bounds, residual, scale)
        guide, protected_change = protect_outside_mask(changed, parent_rgb, mask)
        appearance_restore = None
        if args.restore_parent_appearance:
            guide, appearance_restore = restore_parent_appearance(
                parent_rgb, guide, mask
            )
            guide, protected_change = protect_outside_mask(
                guide, parent_rgb, mask
            )
        mouth_lock = None
        if args.lock_mouth_expression:
            guide, mouth_lock = preserve_parent_mouth_expression(
                parent_rgb, guide, face.kps
            )
        scale_label = f"{scale:.2f}".replace(".", "p")
        appearance_suffix = "_appearancev2" if appearance_restore else ""
        mouth_suffix = "_mouthlock" if mouth_lock else ""
        name = (
            f"age{args.age:02d}_guidefran_src{parent_age:02d}_"
            f"t{conditioning_age:02d}_r{scale_label}"
            f"{appearance_suffix}{mouth_suffix}.png"
        )
        output_path = GUIDE_DIR / name
        write_rgb(output_path, guide)
        outputs.append(
            {
                "path": str(output_path),
                "conditioning_age": conditioning_age,
                "residual_scale": scale,
                "protected_area_max_pixel_change": protected_change,
                "appearance_restore": appearance_restore,
                "mouth_expression_lock": mouth_lock,
            }
        )
        print(f"Saved guide: {output_path}")

    elapsed = time.perf_counter() - started
    summary = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "structure_guide_not_final_portrait",
        "model": "FRAN face_reaging",
        "current_age": plan["current_age"],
        "parent_age": parent_age,
        "target_age_label": args.age,
        "parent_photo": str(parent_path),
        "parent_appearance_restore_enabled": args.restore_parent_appearance,
        "mouth_expression_lock_enabled": args.lock_mouth_expression,
        "outputs": outputs,
        "elapsed_seconds": round(elapsed, 2),
        "peak_cuda_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
        "note": (
            "The guide supplies a population-trained aging direction only. "
            "FLUX and the identity LoRA produce the review portrait."
        ),
    }
    summary_path = DEBUG_DIR / f"age{args.age:02d}_structure_guide_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Structure guides complete: {len(outputs)}")
    print(f"Summary: {summary_path}")

    del model, analyzer
    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
