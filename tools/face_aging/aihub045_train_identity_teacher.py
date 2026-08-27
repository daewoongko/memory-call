"""Train a family-aware identity judge on private AI Hub 045 crops.

Relatives are deliberately treated as hard negatives.  They are never used as
positive pairs or as substitutes for longitudinal photographs of one person.
The official validation families stay unseen until evaluation.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub045 import read_jsonl  # noqa: E402
from face_training_teachers import IdentityTeacher  # noqa: E402


DEFAULT_EXPERIMENT = ROOT / "data/experiments/aihub045_full"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def available_rows(manifest: Path, crop_dir: Path) -> list[dict]:
    return [
        row
        for row in read_jsonl(manifest)
        if (crop_dir / f"{row['record_id']}.jpg").is_file()
    ]


def build_groups(rows: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    identities: dict[str, list[dict]] = defaultdict(list)
    families: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        identities[str(row["identity_id"])].append(row)
        families[str(row["family_id"])].add(str(row["identity_id"]))
    usable = {
        identity: values
        for identity, values in identities.items()
        if len(values) >= 2 and len(families[str(values[0]["family_id"])]) >= 2
    }
    family_members = {
        family: sorted(identity for identity in members if identity in usable)
        for family, members in families.items()
    }
    family_members = {family: members for family, members in family_members.items() if len(members) >= 2}
    usable = {
        identity: values
        for identity, values in usable.items()
        if str(values[0]["family_id"]) in family_members
    }
    return usable, family_members


class FamilyTriplets(Dataset):
    def __init__(self, rows: list[dict], crop_dir: Path, *, augment: bool, length: int, seed: int):
        self.identities, self.families = build_groups(rows)
        self.identity_ids = sorted(self.identities)
        self.family_ids = sorted(self.families)
        self.crop_dir = crop_dir
        self.length = length
        self.seed = seed
        if not self.identity_ids:
            raise ValueError("No identities have two views plus a related hard negative")
        augment_ops = [
            v2.RandomHorizontalFlip(0.5),
            v2.RandomApply([v2.ColorJitter(0.12, 0.12, 0.08)], p=0.6),
            v2.RandomAffine(3, translate=(0.015, 0.015), scale=(0.98, 1.02)),
        ] if augment else []
        self.transform = v2.Compose(
            [v2.ToImage(), *augment_ops, v2.ToDtype(torch.float32, scale=True), v2.Normalize(IMAGENET_MEAN, IMAGENET_STD)]
        )

    def __len__(self) -> int:
        return self.length

    def _image(self, row: dict) -> torch.Tensor:
        path = self.crop_dir / f"{row['record_id']}.jpg"
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(path)
        return self.transform(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        rng = random.Random(self.seed + index * 104729)
        identity = self.identity_ids[index % len(self.identity_ids)]
        values = self.identities[identity]
        anchor_row, positive_row = rng.sample(values, 2)
        family = str(anchor_row["family_id"])
        hard_identity = rng.choice([item for item in self.families[family] if item != identity])
        hard_row = rng.choice(self.identities[hard_identity])
        other_family = rng.choice([item for item in self.family_ids if item != family])
        random_identity = rng.choice(self.families[other_family])
        random_row = rng.choice(self.identities[random_identity])
        return {
            "anchor": self._image(anchor_row),
            "positive": self._image(positive_row),
            "hard_negative": self._image(hard_row),
            "random_negative": self._image(random_row),
        }


def identity_loss(embeddings: torch.Tensor, batch_size: int) -> tuple[torch.Tensor, dict[str, float]]:
    anchor, positive, hard, random_negative = embeddings.split(batch_size)
    positive_distance = 1.0 - F.cosine_similarity(anchor, positive)
    hard_distance = 1.0 - F.cosine_similarity(anchor, hard)
    random_distance = 1.0 - F.cosine_similarity(anchor, random_negative)
    hard_triplet = F.relu(positive_distance - hard_distance + 0.30).mean()
    random_triplet = F.relu(positive_distance - random_distance + 0.20).mean()
    positive_pull = positive_distance.mean()
    loss = hard_triplet + 0.5 * random_triplet + 0.15 * positive_pull
    return loss, {
        "hard_triplet": float(hard_triplet.detach()),
        "random_triplet": float(random_triplet.detach()),
        "positive_pull": float(positive_pull.detach()),
    }


@torch.no_grad()
def evaluate(model: IdentityTeacher, loader: DataLoader, device: torch.device, max_batches: int = 64) -> dict:
    model.eval()
    positive, hard, random_values = [], [], []
    for batch_index, batch in enumerate(loader):
        if batch_index >= max_batches:
            break
        batch_size = batch["anchor"].shape[0]
        images = torch.cat([batch[key] for key in ("anchor", "positive", "hard_negative", "random_negative")]).to(device, non_blocking=True)
        anchor, pos, hard_neg, random_neg = model(images).split(batch_size)
        positive.extend(F.cosine_similarity(anchor, pos).cpu().tolist())
        hard.extend(F.cosine_similarity(anchor, hard_neg).cpu().tolist())
        random_values.extend(F.cosine_similarity(anchor, random_neg).cpu().tolist())
    pos = np.asarray(positive)
    hard_arr = np.asarray(hard)
    random_arr = np.asarray(random_values)
    return {
        "pairs": int(len(pos)),
        "same_identity_cosine": float(pos.mean()),
        "same_family_other_identity_cosine": float(hard_arr.mean()),
        "different_family_cosine": float(random_arr.mean()),
        "hard_negative_margin": float((pos - hard_arr).mean()),
        "hard_negative_accuracy": float((pos > hard_arr).mean()),
        "random_negative_accuracy": float((pos > random_arr).mean()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_EXPERIMENT / "index/teacher_selection.jsonl")
    parser.add_argument("--crop-dir", type=Path, default=DEFAULT_EXPERIMENT / "teacher_crops_224")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPERIMENT / "teachers/identity_pilot_500")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260817)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    rows = available_rows(args.manifest, args.crop_dir)
    train_rows = [row for row in rows if row["dataset_partition"] == "training"]
    validation_rows = [row for row in rows if row["dataset_partition"] == "validation"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    config.update({"available_crops": len(rows), "training_crops": len(train_rows), "validation_crops": len(validation_rows)})
    (args.output_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    train_data = FamilyTriplets(train_rows, args.crop_dir, augment=True, length=max(args.steps * args.batch_size * 2, 100_000), seed=args.seed)
    val_data = FamilyTriplets(validation_rows, args.crop_dir, augment=False, length=8_192, seed=args.seed + 1)
    common = {"batch_size": args.batch_size, "num_workers": args.workers, "pin_memory": True, "persistent_workers": args.workers > 0}
    train_loader = DataLoader(train_data, shuffle=True, generator=torch.Generator().manual_seed(args.seed), **common)
    val_loader = DataLoader(val_data, shuffle=False, **common)
    device = torch.device("cuda")
    model = IdentityTeacher(pretrained=True).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda")
    baseline = evaluate(model, val_loader, device)
    print(json.dumps({"stage": "baseline", "validation": baseline}, ensure_ascii=False), flush=True)
    best_score = -float("inf")
    best_path = args.output_dir / "identity_teacher_best.pth"
    metrics_path = args.output_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    iterator = iter(train_loader)
    started = time.perf_counter()
    for step in range(1, args.steps + 1):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(train_loader)
            batch = next(iterator)
        model.train()
        batch_size = batch["anchor"].shape[0]
        images = torch.cat([batch[key] for key in ("anchor", "positive", "hard_negative", "random_negative")]).to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda"):
            loss, parts = identity_loss(model(images), batch_size)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        row = {"step": step, "loss": float(loss.detach()), **parts, "seconds": round(time.perf_counter() - started, 2)}
        if step == 1 or step % args.eval_every == 0 or step == args.steps:
            validation = evaluate(model, val_loader, device)
            row["validation"] = validation
            score = validation["hard_negative_accuracy"] + validation["hard_negative_margin"]
            if score > best_score:
                best_score = score
                torch.save({"model": model.state_dict(), "step": step, "validation": validation, "config": config}, best_path)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    best = torch.load(best_path, map_location=device, weights_only=True)
    model.load_state_dict(best["model"])
    result = {"best_step": best["step"], "validation": evaluate(model, val_loader, device), "checkpoint": str(best_path), "seconds": round(time.perf_counter() - started, 2)}
    (args.output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
