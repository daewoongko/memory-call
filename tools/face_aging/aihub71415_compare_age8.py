"""Compare FRAN checkpoints against hidden exact-age-8 AI Hub references.

The official validation subjects remain inference-only.  No source, generated,
or target face is written to disk; the command stores aggregate/per-case numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import cv2
import lpips
import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "face_aging" / "fran_vendor"))

from aihub71415 import align_record_image, read_jsonl  # noqa: E402
from face_training_teachers import load_age_teacher  # noqa: E402
from model.models import UNet  # noqa: E402


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    experiment = ROOT / "data" / "experiments" / "aihub71415_full"
    parser.add_argument("--manifest", type=Path, default=experiment / "index" / "manifest.jsonl")
    parser.add_argument("--holdouts", type=Path, default=experiment / "pairs" / "age8_holdouts.jsonl")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--age-teacher-checkpoint",
        type=Path,
        default=experiment / "teachers" / "age_pilot_500" / "age_teacher_best.pth",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--max-cases", type=int, default=0)
    return parser.parse_args()


def _fixed_face_geometry(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Return ArcFace-order landmarks and a stable box for aligned crops.

    The evaluator must not run a second detector over images that were already
    aligned from AI Hub's licensed five-point labels. Tight canonical crops can
    receive low detector confidence even when the face is visually valid. The
    fixed geometry makes the hidden-age comparison measure identity and age,
    rather than detector threshold behaviour.
    """

    # ArcFace order: left eye, right eye, nose, left mouth, right mouth.
    landmarks = np.asarray(
        [
            [0.32 * size, 0.38 * size],
            [0.68 * size, 0.38 * size],
            [0.50 * size, 0.56 * size],
            [0.38 * size, 0.69 * size],
            [0.62 * size, 0.69 * size],
        ],
        dtype=np.float32,
    )
    bbox = np.asarray([0.18 * size, 0.14 * size, 0.82 * size, 0.88 * size], dtype=np.float32)
    return landmarks, bbox


def _embedding(recognition, rgb: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    from insightface.utils import face_align

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    crop = face_align.norm_crop(bgr, landmark=landmarks, image_size=112)
    return np.asarray(recognition.get_feat(crop)[0], dtype=np.float32)


def _estimated_age(genderage, rgb: np.ndarray, bbox: np.ndarray) -> int:
    from insightface.app.common import Face

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    face = Face(bbox=bbox)
    _, age = genderage.get(bgr, face)
    return int(age)


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    left = left.astype(np.float64)
    right = right.astype(np.float64)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else float("nan")


def _aligned(records: dict[str, dict], record_id: str, size: int) -> np.ndarray:
    row = records[record_id]
    with ZipFile(row["image_archive_path"]) as archive:
        bgr, _ = align_record_image(archive, row, width=size, height=size)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _input(source: np.ndarray, source_age: int, target_age: int, device: torch.device):
    rgb = torch.from_numpy(source.copy()).permute(2, 0, 1).float().div(255.0)
    height, width = source.shape[:2]
    source_map = torch.full((1, height, width), source_age / 100.0)
    target_map = torch.full((1, height, width), target_age / 100.0)
    return torch.cat((rgb, source_map, target_map), dim=0).unsqueeze(0).to(device), rgb.to(device)


def _load_model(path: Path, device: torch.device) -> UNet:
    model = UNet().to(device)
    model.load_state_dict(torch.load(path, map_location=device, weights_only=True), strict=True)
    return model.eval()


def _age_teacher_input(image: torch.Tensor) -> torch.Tensor:
    resized = torch.nn.functional.interpolate(
        image.unsqueeze(0), size=(224, 224), mode="bilinear", align_corners=False
    )
    mean = resized.new_tensor(IMAGENET_MEAN)[None, :, None, None]
    std = resized.new_tensor(IMAGENET_STD)[None, :, None, None]
    return (resized - mean) / std


def _summary(rows: list[dict], label: str) -> dict:
    values = [row[label] for row in rows]
    extracted = [row for row in values if row["embedding_extracted"]]

    def mean(key: str, source: list[dict] = extracted) -> float | None:
        nums = [float(row[key]) for row in source if row.get(key) is not None]
        return float(np.mean(nums)) if nums else None

    return {
        "cases": len(values),
        "embedding_extraction_rate": len(extracted) / max(len(values), 1),
        "identity_to_hidden_age8_mean": mean("identity_to_hidden_age8"),
        "identity_to_adult_source_mean": mean("identity_to_adult_source"),
        "insightface_age_mae_mean": mean("insightface_age_mae"),
        "aihub_age_estimate_mean": mean("aihub_age_estimate"),
        "aihub_age_mae_mean": mean("aihub_age_mae"),
        "target_l1_mean": mean("target_l1", values),
        "target_lpips_mean": mean("target_lpips", values),
    }


@torch.inference_mode()
def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required")
    from insightface.model_zoo import model_zoo

    records = {row["record_id"]: row for row in read_jsonl(args.manifest)}
    cases = [row for row in read_jsonl(args.holdouts) if row.get("formal_eval")]
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        raise ValueError("No formal exact-age-8 cases found")

    device = torch.device("cuda")
    models = {
        "baseline": _load_model(args.baseline, device),
        "candidate": _load_model(args.candidate, device),
    }
    perceptual = lpips.LPIPS(net="alex", verbose=False).to(device).eval()
    age_teacher = load_age_teacher(str(args.age_teacher_checkpoint), device)
    insightface_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    recognition = model_zoo.get_model(
        str(insightface_dir / "w600k_r50.onnx"), providers=["CPUExecutionProvider"]
    )
    genderage = model_zoo.get_model(
        str(insightface_dir / "genderage.onnx"), providers=["CPUExecutionProvider"]
    )
    recognition.prepare(ctx_id=-1)
    genderage.prepare(ctx_id=-1)
    landmarks, bbox = _fixed_face_geometry(args.image_size)
    results: list[dict] = []
    for index, case in enumerate(cases, start=1):
        # The oldest adult source best matches the real service input condition.
        source_ref = max(case["adult_only_sources"], key=lambda row: int(row["photo_age"]))
        source = _aligned(records, source_ref["record_id"], args.image_size)
        target = _aligned(records, case["hidden_target"]["record_id"], args.image_size)
        source_embedding = _embedding(recognition, source, landmarks)
        target_embedding = _embedding(recognition, target, landmarks)
        inputs, source_tensor = _input(source, int(source_ref["photo_age"]), 8, device)
        target_tensor = torch.from_numpy(target.copy()).permute(2, 0, 1).float().div(255.0).to(device)
        row = {
            "case_id": case["case_id"],
            "subject_id": case["subject_id"],
            "source_age": int(source_ref["photo_age"]),
        }
        for label, model in models.items():
            generated = torch.clamp(source_tensor + model(inputs)[0], 0.0, 1.0)
            generated_rgb = (generated.permute(1, 2, 0).cpu().numpy() * 255.0).astype(np.uint8)
            generated_embedding = _embedding(recognition, generated_rgb, landmarks)
            estimated_age = _estimated_age(genderage, generated_rgb, bbox)
            aihub_estimated_age = float(
                age_teacher(_age_teacher_input(generated))["expected_age"].item()
            )
            metrics = {
                "embedding_extracted": True,
                "identity_to_hidden_age8": _cosine(generated_embedding, target_embedding),
                "identity_to_adult_source": _cosine(generated_embedding, source_embedding),
                "insightface_estimated_age": estimated_age,
                "insightface_age_mae": abs(estimated_age - 8),
                "aihub_age_estimate": aihub_estimated_age,
                "aihub_age_mae": abs(aihub_estimated_age - 8.0),
                "target_l1": float(torch.nn.functional.l1_loss(generated, target_tensor)),
                "target_lpips": float(
                    perceptual(
                        generated.unsqueeze(0) * 2.0 - 1.0,
                        target_tensor.unsqueeze(0) * 2.0 - 1.0,
                    ).mean()
                ),
            }
            row[label] = metrics
        results.append(row)
        print(f"{index}/{len(cases)} {case['case_id']}", flush=True)

    report = {
        "status": "complete",
        "warning": (
            "Identity and age use fixed geometry from the licensed five-point labels after "
            "canonical alignment; detector confidence is intentionally not part of this test. "
            "Pixel/LPIPS comparisons remain secondary because longitudinal photos differ in "
            "expression, pose and lighting. No hidden age-8 image was used as input."
        ),
        "baseline_checkpoint": str(args.baseline),
        "candidate_checkpoint": str(args.candidate),
        "baseline": _summary(results, "baseline"),
        "candidate": _summary(results, "candidate"),
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": report["baseline"], "candidate": report["candidate"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
