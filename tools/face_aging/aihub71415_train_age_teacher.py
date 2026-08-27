"""Train a differentiable Korean-face age judge on AI Hub 71415.

The official validation partition is held out until final evaluation.  The
training partition is split by person using the already-built pair manifests,
so the same identity never leaks between train and validation.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import read_jsonl  # noqa: E402
from face_training_teachers import AGE_CLASSES, AgeTeacher  # noqa: E402


DEFAULT_EXPERIMENT = ROOT / "data/experiments/aihub71415_full"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def _subjects(path: Path) -> set[str]:
    return {str(row["subject_id"]) for row in read_jsonl(path)}


def split_records(manifest: Path, train_pairs: Path, val_pairs: Path) -> dict[str, list[dict]]:
    train_subjects = _subjects(train_pairs)
    val_subjects = _subjects(val_pairs)
    if train_subjects & val_subjects:
        raise ValueError("Train/validation subject leakage in pair manifests")
    result = {"train": [], "val": [], "test": []}
    for row in read_jsonl(manifest):
        if not row.get("has_image", True):
            continue
        subject = str(row["subject_id"])
        if row.get("dataset_partition") == "validation":
            result["test"].append(row)
        elif subject in train_subjects:
            result["train"].append(row)
        elif subject in val_subjects:
            result["val"].append(row)
    return result


class AgeDataset(Dataset):
    def __init__(self, rows: list[dict], crop_dir: Path, *, augment: bool):
        self.rows = rows
        self.crop_dir = crop_dir
        self.transform = v2.Compose(
            [
                v2.ToImage(),
                v2.RandomHorizontalFlip(0.5) if augment else v2.Identity(),
                v2.RandomApply(
                    [v2.ColorJitter(brightness=0.12, contrast=0.12, saturation=0.08)],
                    p=0.6 if augment else 0.0,
                ),
                v2.RandomAffine(3, translate=(0.015, 0.015), scale=(0.98, 1.02))
                if augment
                else v2.Identity(),
                v2.ToDtype(torch.float32, scale=True),
                v2.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        row = self.rows[index]
        path = self.crop_dir / f"{row['record_id']}.jpg"
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(path)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return {
            "image": self.transform(image),
            "age": torch.tensor(float(row["photo_age"]), dtype=torch.float32),
            "subject_id": str(row["subject_id"]),
        }


def gaussian_age_targets(ages: torch.Tensor, sigma: float) -> torch.Tensor:
    values = torch.arange(AGE_CLASSES, device=ages.device, dtype=ages.dtype)[None]
    targets = torch.exp(-0.5 * ((values - ages[:, None]) / sigma) ** 2)
    return targets / targets.sum(dim=1, keepdim=True)


def age_loss(outputs: dict[str, torch.Tensor], ages: torch.Tensor, sigma: float) -> tuple[torch.Tensor, dict]:
    soft_targets = gaussian_age_targets(ages, sigma)
    distribution = -(soft_targets * outputs["logits"].log_softmax(dim=1)).sum(dim=1).mean()
    regression = F.smooth_l1_loss(outputs["expected_age"], ages, beta=2.0)
    total = distribution + 0.25 * regression
    return total, {"distribution": float(distribution.detach()), "regression": float(regression.detach())}


@torch.no_grad()
def evaluate(model: AgeTeacher, loader: DataLoader, device: torch.device) -> dict:
    model.eval()
    absolute: list[float] = []
    by_band: dict[str, list[float]] = {"00-05": [], "06-10": [], "11-17": [], "18-29": [], "30-44": [], "45+": []}
    age8: list[float] = []
    for batch in loader:
        images = batch["image"].to(device, non_blocking=True)
        ages = batch["age"].to(device, non_blocking=True)
        predicted = model(images)["expected_age"]
        errors = (predicted - ages).abs().cpu().tolist()
        for age, error in zip(ages.cpu().tolist(), errors):
            absolute.append(error)
            if age <= 5:
                band = "00-05"
            elif age <= 10:
                band = "06-10"
            elif age <= 17:
                band = "11-17"
            elif age <= 29:
                band = "18-29"
            elif age <= 44:
                band = "30-44"
            else:
                band = "45+"
            by_band[band].append(error)
            if int(round(age)) == 8:
                age8.append(error)
    return {
        "count": len(absolute),
        "mae": float(np.mean(absolute)) if absolute else math.inf,
        "age8_count": len(age8),
        "age8_mae": float(np.mean(age8)) if age8 else math.inf,
        "band_mae": {key: float(np.mean(values)) if values else None for key, values in by_band.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_EXPERIMENT / "index/manifest.jsonl")
    parser.add_argument("--train-pairs", type=Path, default=DEFAULT_EXPERIMENT / "pairs/train_pairs.jsonl")
    parser.add_argument("--val-pairs", type=Path, default=DEFAULT_EXPERIMENT / "pairs/val_pairs.jsonl")
    parser.add_argument("--crop-dir", type=Path, default=DEFAULT_EXPERIMENT / "teacher_crops_224")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPERIMENT / "teachers/age_pilot")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--sigma", type=float, default=2.0)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--final-test", action="store_true", help="Evaluate official holdout only after model selection")
    parser.add_argument("--evaluate-checkpoint", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    splits = split_records(args.manifest, args.train_pairs, args.val_pairs)
    missing = [row["record_id"] for rows in splits.values() for row in rows if not (args.crop_dir / f"{row['record_id']}.jpg").is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} prepared crops missing; run aihub71415_prepare_teacher.py first")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    (args.output_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    train_data = AgeDataset(splits["train"], args.crop_dir, augment=True)
    val_data = AgeDataset(splits["val"], args.crop_dir, augment=False)
    age_counts = Counter(int(row["photo_age"]) for row in splits["train"])
    subject_counts = Counter(str(row["subject_id"]) for row in splits["train"])
    weights = []
    for row in splits["train"]:
        age = int(row["photo_age"])
        age_weight = math.sqrt(len(splits["train"]) / (len(age_counts) * age_counts[age]))
        subject_weight = math.sqrt(np.median(list(subject_counts.values())) / subject_counts[str(row["subject_id"])])
        focus = 2.0 if 6 <= age <= 10 else 1.0
        weights.append(float(np.clip(age_weight * subject_weight * focus, 0.15, 8.0)))
    sampler = WeightedRandomSampler(torch.tensor(weights, dtype=torch.double), len(train_data), replacement=True, generator=torch.Generator().manual_seed(args.seed))
    common = {"batch_size": args.batch_size, "num_workers": args.workers, "pin_memory": True, "persistent_workers": args.workers > 0}
    train_loader = DataLoader(train_data, sampler=sampler, **common)
    val_loader = DataLoader(val_data, shuffle=False, **common)

    device = torch.device("cuda")
    if args.evaluate_checkpoint:
        model = AgeTeacher(pretrained=False).to(device)
        payload = torch.load(args.evaluate_checkpoint, map_location=device, weights_only=True)
        model.load_state_dict(payload.get("model", payload), strict=True)
        result = {"checkpoint": str(args.evaluate_checkpoint), "validation": evaluate(model, val_loader, device)}
        if args.final_test:
            test_loader = DataLoader(
                AgeDataset(splits["test"], args.crop_dir, augment=False),
                shuffle=False,
                **common,
            )
            result["official_test"] = evaluate(model, test_loader, device)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return
    model = AgeTeacher(pretrained=True).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda")
    iterator = iter(train_loader)
    metrics_path = args.output_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    baseline = evaluate(model, val_loader, device)
    print(json.dumps({"stage": "baseline", "validation": baseline}, ensure_ascii=False), flush=True)
    best_score = math.inf
    best_path = args.output_dir / "age_teacher_best.pth"
    started = time.perf_counter()
    for step in range(1, args.steps + 1):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(train_loader)
            batch = next(iterator)
        model.train()
        images = batch["image"].to(device, non_blocking=True)
        ages = batch["age"].to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda"):
            outputs = model(images)
            loss, parts = age_loss(outputs, ages, args.sigma)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        row = {"step": step, "loss": float(loss.detach()), **parts, "seconds": round(time.perf_counter() - started, 2)}
        if step == 1 or step % args.eval_every == 0 or step == args.steps:
            validation = evaluate(model, val_loader, device)
            row["validation"] = validation
            score = validation["age8_mae"] + 0.25 * validation["mae"]
            if score < best_score:
                best_score = score
                torch.save({"model": model.state_dict(), "step": step, "validation": validation, "config": config}, best_path)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    payload = torch.load(best_path, map_location=device, weights_only=True)
    model.load_state_dict(payload["model"])
    final_val = evaluate(model, val_loader, device)
    result = {"best_step": payload["step"], "validation": final_val, "checkpoint": str(best_path), "seconds": round(time.perf_counter() - started, 2)}
    if args.final_test:
        test_loader = DataLoader(AgeDataset(splits["test"], args.crop_dir, augment=False), shuffle=False, **common)
        result["official_test"] = evaluate(model, test_loader, device)
    (args.output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
