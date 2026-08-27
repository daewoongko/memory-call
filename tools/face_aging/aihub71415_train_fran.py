"""Fine-tune the vendored FRAN replica on AI Hub 71415 paired faces.

The script reads licensed source images directly from their ZIP shards, aligns
them from the supplied five landmarks, and writes only model/metric artefacts.
It never copies raw dataset images into a public application directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
import time
from collections import OrderedDict
from pathlib import Path
from zipfile import ZipFile

import cv2
import lpips
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "face_aging" / "fran_vendor"))

from aihub71415 import (  # noqa: E402
    align_record_image,
    build_balanced_sampling_weights as build_sampling_weight_values,
    read_jsonl,
)
from face_training_teachers import (  # noqa: E402
    load_age_teacher,
    load_identity_teacher,
)
from model.models import PatchGANDiscriminator, UNet  # noqa: E402


DEFAULT_EXPERIMENT = ROOT / "data" / "experiments" / "aihub71415_full"
DEFAULT_GENERATOR = Path.home() / "Models" / "face_reaging" / "best_unet_model.pth"
DEFAULT_DISCRIMINATOR = (
    Path.home() / "Models" / "face_reaging" / "best_discriminator_model.pth"
)
DEFAULT_AGE_TEACHER = DEFAULT_EXPERIMENT / "teachers" / "age_pilot_500" / "age_teacher_best.pth"
DEFAULT_IDENTITY_TEACHER = (
    ROOT
    / "data"
    / "experiments"
    / "aihub045_full"
    / "teachers"
    / "identity_pilot_500"
    / "identity_teacher_best.pth"
)
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class ZipCache:
    """Small LRU cache so a training step does not reopen every AI Hub shard."""

    def __init__(self, limit: int = 12):
        self.limit = limit
        self.archives: OrderedDict[str, ZipFile] = OrderedDict()

    def get(self, path: str | Path) -> ZipFile:
        key = str(Path(path))
        archive = self.archives.pop(key, None)
        if archive is None:
            archive = ZipFile(key)
        self.archives[key] = archive
        while len(self.archives) > self.limit:
            _, oldest = self.archives.popitem(last=False)
            oldest.close()
        return archive

    def close(self) -> None:
        for archive in self.archives.values():
            archive.close()
        self.archives.clear()

    def __del__(self):
        self.close()


def _bounded_rows(path: Path, limit: int, seed: int) -> list[dict]:
    rows = list(read_jsonl(path))
    if limit > 0 and len(rows) > limit:
        rng = random.Random(seed)
        rows = rng.sample(rows, limit)
    return rows


def build_balanced_sampling_weights(
    pairs: list[dict],
    *,
    focus_target_age: int,
    focus_radius: int,
    focus_boost: float,
) -> tuple[torch.Tensor, dict]:
    values, report = build_sampling_weight_values(
        pairs,
        focus_target_age=focus_target_age,
        focus_radius=focus_radius,
        focus_boost=focus_boost,
    )
    return torch.as_tensor(values, dtype=torch.double), report


class AIHubFRANPairs(Dataset):
    """Same-person source/target pairs with identical paired augmentation."""

    def __init__(
        self,
        manifest_path: Path,
        pairs_path: Path,
        *,
        image_size: int,
        limit: int = 0,
        seed: int = 20260816,
        augment: bool = False,
    ):
        self.records = {
            row["record_id"]: row for row in read_jsonl(manifest_path)
        }
        self.pairs = _bounded_rows(pairs_path, limit, seed)
        self.image_size = image_size
        self.augment = augment
        self.cache = ZipCache()
        if not self.pairs:
            raise ValueError(f"No pairs found in {pairs_path}")

    def __len__(self) -> int:
        return len(self.pairs)

    def _aligned_rgb(self, record_id: str) -> np.ndarray:
        row = self.records[record_id]
        archive_path = row.get("image_archive_path")
        if not archive_path:
            raise ValueError(f"Missing image archive for {record_id}")
        image, _ = align_record_image(
            self.cache.get(archive_path),
            row,
            width=self.image_size,
            height=self.image_size,
        )
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def _paired_augment(
        self, source: np.ndarray, target: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        if random.random() < 0.5:
            source = np.ascontiguousarray(source[:, ::-1])
            target = np.ascontiguousarray(target[:, ::-1])

        angle = random.uniform(-3.0, 3.0)
        scale = random.uniform(0.97, 1.03)
        shift = self.image_size * 0.018
        tx, ty = random.uniform(-shift, shift), random.uniform(-shift, shift)
        matrix = cv2.getRotationMatrix2D(
            (self.image_size / 2, self.image_size / 2), angle, scale
        )
        matrix[:, 2] += (tx, ty)
        source = cv2.warpAffine(
            source,
            matrix,
            (self.image_size, self.image_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        target = cv2.warpAffine(
            target,
            matrix,
            (self.image_size, self.image_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

        gain = random.uniform(0.92, 1.08)
        bias = random.uniform(-0.035, 0.035) * 255.0
        source = np.clip(source.astype(np.float32) * gain + bias, 0, 255).astype(np.uint8)
        target = np.clip(target.astype(np.float32) * gain + bias, 0, 255).astype(np.uint8)
        return source, target

    def __getitem__(self, index: int) -> dict[str, torch.Tensor | str | int]:
        pair = self.pairs[index]
        source = self._aligned_rgb(pair["source_record_id"])
        target = self._aligned_rgb(pair["target_record_id"])
        if self.augment:
            source, target = self._paired_augment(source, target)
        source_rgb = torch.from_numpy(source.copy()).permute(2, 0, 1).float() / 255.0
        target_rgb = torch.from_numpy(target.copy()).permute(2, 0, 1).float() / 255.0
        source_age = float(pair["source_age"]) / 100.0
        target_age = float(pair["target_age"]) / 100.0
        source_map = torch.full((1, self.image_size, self.image_size), source_age)
        target_map = torch.full((1, self.image_size, self.image_size), target_age)
        return {
            "input": torch.cat((source_rgb, source_map, target_map), dim=0),
            "source": source_rgb,
            "target": target_rgb,
            "source_age_map": source_map,
            "target_age_map": target_map,
            "pair_id": pair["pair_id"],
            "source_age": int(pair["source_age"]),
            "target_age": int(pair["target_age"]),
        }


def _age_input(image: torch.Tensor, age_map: torch.Tensor) -> torch.Tensor:
    return torch.cat((image, age_map), dim=1)


def _d_loss(
    discriminator: nn.Module,
    fake: torch.Tensor,
    target: torch.Tensor,
    source: torch.Tensor,
    source_age: torch.Tensor,
    target_age: torch.Tensor,
) -> torch.Tensor:
    real_logits = discriminator(_age_input(target, target_age))
    fake_logits = discriminator(_age_input(fake.detach(), target_age))
    source_mismatch = discriminator(_age_input(source, target_age))
    target_mismatch = discriminator(_age_input(target, source_age))
    real = F.binary_cross_entropy_with_logits(real_logits, torch.ones_like(real_logits))
    fake_loss = F.binary_cross_entropy_with_logits(fake_logits, torch.zeros_like(fake_logits))
    mismatch_source = F.binary_cross_entropy_with_logits(
        source_mismatch, torch.zeros_like(source_mismatch)
    )
    mismatch_target = F.binary_cross_entropy_with_logits(
        target_mismatch, torch.zeros_like(target_mismatch)
    )
    return (2.0 * real + fake_loss + 0.25 * mismatch_source + 0.25 * mismatch_target) / 3.5


def _teacher_input(images: torch.Tensor) -> torch.Tensor:
    resized = F.interpolate(images, size=(224, 224), mode="bilinear", align_corners=False)
    mean = resized.new_tensor(IMAGENET_MEAN)[None, :, None, None]
    std = resized.new_tensor(IMAGENET_STD)[None, :, None, None]
    return (resized - mean) / std


def _background_mask(images: torch.Tensor) -> torch.Tensor:
    """Softly protect aligned-image corners while allowing the face and hair to age."""

    height, width = images.shape[-2:]
    y = torch.linspace(-1.0, 1.0, height, device=images.device, dtype=images.dtype)
    x = torch.linspace(-1.0, 1.0, width, device=images.device, dtype=images.dtype)
    yy, xx = torch.meshgrid(y, x, indexing="ij")
    # The AI Hub aligner places the face slightly above centre.
    ellipse = (xx / 0.78) ** 2 + ((yy + 0.08) / 0.92) ** 2
    foreground = torch.sigmoid((1.0 - ellipse) * 16.0)
    return (1.0 - foreground)[None, None]


def _generator_losses(
    discriminator: nn.Module,
    perceptual: nn.Module,
    age_teacher: nn.Module,
    identity_teacher: nn.Module,
    generated: torch.Tensor,
    source: torch.Tensor,
    target: torch.Tensor,
    legacy_reference: torch.Tensor,
    target_age_map: torch.Tensor,
    target_age_years: torch.Tensor,
    adversarial_weight: float,
    age_weight: float,
    identity_weight: float,
    background_weight: float,
    legacy_weight: float,
) -> tuple[torch.Tensor, dict[str, float]]:
    paired_l1 = F.l1_loss(generated, target)
    # LPIPS is calibrated for inputs in [-1, 1].
    lpips_loss = perceptual(
        generated * 2.0 - 1.0, target * 2.0 - 1.0
    ).mean()
    logits = discriminator(_age_input(generated, target_age_map))
    adversarial = F.binary_cross_entropy_with_logits(logits, torch.ones_like(logits))

    generated_teacher_input = _teacher_input(generated)
    age_prediction = age_teacher(generated_teacher_input)["expected_age"]
    # Convert years to roughly decade-sized units so this term does not swamp
    # perceptual and identity losses.
    age_target = F.smooth_l1_loss(age_prediction, target_age_years, beta=2.0) / 10.0
    generated_identity = identity_teacher(generated_teacher_input)
    with torch.no_grad():
        source_identity = identity_teacher(_teacher_input(source))
        target_identity = identity_teacher(_teacher_input(target))
    identity_source = (1.0 - F.cosine_similarity(generated_identity, source_identity)).mean()
    identity_target = (1.0 - F.cosine_similarity(generated_identity, target_identity)).mean()
    identity = 0.5 * (identity_source + identity_target)
    background = (
        (generated - source).abs() * _background_mask(generated)
    ).sum() / (_background_mask(generated).sum() * generated.shape[0] * generated.shape[1]).clamp_min(1.0)
    legacy = F.l1_loss(generated, legacy_reference)

    total = (
        0.75 * paired_l1
        + lpips_loss
        + adversarial_weight * adversarial
        + age_weight * age_target
        + identity_weight * identity
        + background_weight * background
        + legacy_weight * legacy
    )
    return total, {
        "g_total": float(total.detach()),
        "paired_l1": float(paired_l1.detach()),
        "lpips": float(lpips_loss.detach()),
        "adversarial": float(adversarial.detach()),
        "age_target": float(age_target.detach()),
        "predicted_age": float(age_prediction.detach().mean()),
        "identity": float(identity.detach()),
        "identity_source": float(identity_source.detach()),
        "identity_target": float(identity_target.detach()),
        "background": float(background.detach()),
        "legacy": float(legacy.detach()),
    }


@torch.no_grad()
def validate(
    generator: nn.Module,
    perceptual: nn.Module,
    loader: DataLoader,
    device: torch.device,
    max_batches: int,
    teacher: nn.Module | None = None,
    age_teacher: nn.Module | None = None,
    identity_teacher: nn.Module | None = None,
) -> dict[str, float]:
    generator.eval()
    totals = {
        "l1": 0.0,
        "lpips": 0.0,
        "teacher_l1": 0.0,
        "age_mae": 0.0,
        "identity_source_cosine": 0.0,
        "identity_target_cosine": 0.0,
    }
    seen = 0
    for batch_index, batch in enumerate(loader):
        if batch_index >= max_batches:
            break
        inputs = batch["input"].to(device, non_blocking=True)
        source = batch["source"].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        generated = torch.clamp(source + generator(inputs), 0.0, 1.0)
        totals["l1"] += float(F.l1_loss(generated, target))
        totals["lpips"] += float(
            perceptual(generated * 2.0 - 1.0, target * 2.0 - 1.0).mean()
        )
        if teacher is not None:
            teacher_generated = torch.clamp(source + teacher(inputs), 0.0, 1.0)
            totals["teacher_l1"] += float(F.l1_loss(generated, teacher_generated))
        if age_teacher is not None:
            ages = batch["target_age"].to(device, dtype=torch.float32, non_blocking=True)
            predicted = age_teacher(_teacher_input(generated))["expected_age"]
            totals["age_mae"] += float((predicted - ages).abs().mean())
        if identity_teacher is not None:
            generated_identity = identity_teacher(_teacher_input(generated))
            source_identity = identity_teacher(_teacher_input(source))
            target_identity = identity_teacher(_teacher_input(target))
            totals["identity_source_cosine"] += float(
                F.cosine_similarity(generated_identity, source_identity).mean()
            )
            totals["identity_target_cosine"] += float(
                F.cosine_similarity(generated_identity, target_identity).mean()
            )
        seen += 1
    generator.train()
    divisor = max(seen, 1)
    return {f"val_{key}": value / divisor for key, value in totals.items()}


@torch.no_grad()
def save_preview(
    generator: nn.Module,
    dataset: AIHubFRANPairs,
    output_path: Path,
    device: torch.device,
    count: int = 4,
) -> None:
    generator.eval()
    panels: list[Image.Image] = []
    width = dataset.image_size
    for index in np.linspace(0, len(dataset) - 1, min(count, len(dataset)), dtype=int):
        sample = dataset[int(index)]
        inputs = sample["input"].unsqueeze(0).to(device)
        source = sample["source"].unsqueeze(0).to(device)
        generated = torch.clamp(source + generator(inputs), 0.0, 1.0)[0]
        images = [sample["source"], generated.cpu(), sample["target"]]
        row = Image.new("RGB", (width * 3, width + 34), "white")
        labels = (
            f"source {sample['source_age']}",
            f"generated {sample['target_age']}",
            f"target {sample['target_age']}",
        )
        draw = ImageDraw.Draw(row)
        for column, (tensor, label) in enumerate(zip(images, labels)):
            array = (
                tensor.detach().clamp(0, 1).permute(1, 2, 0).numpy() * 255.0
            ).astype(np.uint8)
            row.paste(Image.fromarray(array), (column * width, 34))
            draw.text((column * width + 8, 9), label, fill="black")
        panels.append(row)
    contact = Image.new("RGB", (width * 3, sum(panel.height for panel in panels)), "white")
    top = 0
    for panel in panels:
        contact.paste(panel, (0, top))
        top += panel.height
    output_path.parent.mkdir(parents=True, exist_ok=True)
    contact.save(output_path, quality=92)
    generator.train()


def save_checkpoint(
    output_dir: Path,
    step: int,
    generator: nn.Module,
    discriminator: nn.Module,
    generator_optimizer: torch.optim.Optimizer,
    discriminator_optimizer: torch.optim.Optimizer,
    config: dict,
) -> tuple[Path, Path]:
    generator_path = output_dir / f"fran_aihub71415_step_{step:06d}.pth"
    training_path = output_dir / f"training_state_step_{step:06d}.pth"
    torch.save(generator.state_dict(), generator_path)
    torch.save(
        {
            "step": step,
            "generator": generator.state_dict(),
            "discriminator": discriminator.state_dict(),
            "generator_optimizer": generator_optimizer.state_dict(),
            "discriminator_optimizer": discriminator_optimizer.state_dict(),
            "config": config,
        },
        training_path,
    )
    return generator_path, training_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_EXPERIMENT / "index" / "manifest.jsonl")
    parser.add_argument("--train-pairs", type=Path, default=DEFAULT_EXPERIMENT / "pairs" / "train_pairs.jsonl")
    parser.add_argument("--val-pairs", type=Path, default=DEFAULT_EXPERIMENT / "pairs" / "val_pairs.jsonl")
    parser.add_argument("--generator-checkpoint", type=Path, default=DEFAULT_GENERATOR)
    parser.add_argument("--discriminator-checkpoint", type=Path, default=DEFAULT_DISCRIMINATOR)
    parser.add_argument("--age-teacher-checkpoint", type=Path, default=DEFAULT_AGE_TEACHER)
    parser.add_argument("--identity-teacher-checkpoint", type=Path, default=DEFAULT_IDENTITY_TEACHER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPERIMENT / "training" / "pilot")
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--max-train-pairs", type=int, default=0)
    parser.add_argument("--max-val-pairs", type=int, default=256)
    parser.add_argument("--val-batches", type=int, default=16)
    parser.add_argument("--val-every", type=int, default=100)
    parser.add_argument("--save-every", type=int, default=100)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--adversarial-weight", type=float, default=0.05)
    parser.add_argument("--age-weight", type=float, default=0.08)
    parser.add_argument("--identity-weight", type=float, default=0.40)
    parser.add_argument("--background-weight", type=float, default=0.35)
    parser.add_argument("--legacy-weight", type=float, default=0.10)
    parser.add_argument(
        "--sampling",
        choices=("uniform", "balanced_age_gap_subject"),
        default="uniform",
    )
    parser.add_argument("--focus-target-age", type=int, default=8)
    parser.add_argument("--focus-radius", type=int, default=2)
    parser.add_argument("--focus-boost", type=float, default=2.0)
    parser.add_argument(
        "--objective",
        choices=("revised", "distribution", "paired"),
        default="revised",
        help=(
            "revised combines paired targets with Korean age and family-hard-negative identity judges; "
            "distribution and paired remain only as historical ablations"
        ),
    )
    parser.add_argument("--discriminator-warmup-steps", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--no-amp", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.image_size < 64 or args.image_size % 16:
        raise ValueError("image-size must be at least 64 and divisible by 16")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for FRAN fine-tuning")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }
    (args.output_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    train_dataset = AIHubFRANPairs(
        args.manifest,
        args.train_pairs,
        image_size=args.image_size,
        limit=args.max_train_pairs,
        seed=args.seed,
        augment=True,
    )
    val_dataset = AIHubFRANPairs(
        args.manifest,
        args.val_pairs,
        image_size=args.image_size,
        limit=args.max_val_pairs,
        seed=args.seed + 1,
        augment=False,
    )
    sampler = None
    sampling_report = {"strategy": "uniform", "pair_count": len(train_dataset)}
    if args.sampling == "balanced_age_gap_subject":
        weights, sampling_report = build_balanced_sampling_weights(
            train_dataset.pairs,
            focus_target_age=args.focus_target_age,
            focus_radius=args.focus_radius,
            focus_boost=args.focus_boost,
        )
        sampler_generator = torch.Generator().manual_seed(args.seed)
        sampler = WeightedRandomSampler(
            weights,
            num_samples=len(train_dataset),
            replacement=True,
            generator=sampler_generator,
        )
    (args.output_dir / "sampling_report.json").write_text(
        json.dumps(sampling_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=sampler is None,
        sampler=sampler,
        num_workers=0,
        pin_memory=True,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=True,
    )

    device = torch.device("cuda")
    generator = UNet().to(device)
    discriminator = PatchGANDiscriminator(input_channels=4).to(device)
    generator.load_state_dict(
        torch.load(args.generator_checkpoint, map_location=device, weights_only=True),
        strict=True,
    )
    discriminator.load_state_dict(
        torch.load(args.discriminator_checkpoint, map_location=device, weights_only=True),
        strict=True,
    )
    teacher = copy.deepcopy(generator).eval()
    for parameter in teacher.parameters():
        parameter.requires_grad_(False)
    perceptual = lpips.LPIPS(net="alex", verbose=False).to(device).eval()
    for parameter in perceptual.parameters():
        parameter.requires_grad_(False)
    age_teacher = load_age_teacher(str(args.age_teacher_checkpoint), device)
    identity_teacher = load_identity_teacher(str(args.identity_teacher_checkpoint), device)
    for judge in (age_teacher, identity_teacher):
        for parameter in judge.parameters():
            parameter.requires_grad_(False)

    generator_optimizer = torch.optim.Adam(generator.parameters(), lr=args.learning_rate)
    discriminator_optimizer = torch.optim.Adam(
        discriminator.parameters(), lr=args.learning_rate
    )
    use_amp = not args.no_amp
    scaler_g = torch.amp.GradScaler("cuda", enabled=use_amp)
    scaler_d = torch.amp.GradScaler("cuda", enabled=use_amp)
    metrics_path = args.output_dir / "metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")

    baseline = validate(
        generator,
        perceptual,
        val_loader,
        device,
        args.val_batches,
        teacher,
        age_teacher,
        identity_teacher,
    )
    save_preview(generator, val_dataset, args.output_dir / "preview_before.jpg", device)
    print(json.dumps({"stage": "baseline", **baseline}, ensure_ascii=False), flush=True)
    latest_validation = dict(baseline)

    generator.train()
    discriminator.train()
    data_iterator = iter(train_loader)
    started = time.perf_counter()
    peak_memory = 0.0
    last_generator_path: Path | None = None
    for step in range(1, args.steps + 1):
        try:
            batch = next(data_iterator)
        except StopIteration:
            data_iterator = iter(train_loader)
            batch = next(data_iterator)
        inputs = batch["input"].to(device, non_blocking=True)
        source = batch["source"].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        source_age = batch["source_age_map"].to(device, non_blocking=True)
        target_age = batch["target_age_map"].to(device, non_blocking=True)

        discriminator_optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=use_amp):
            with torch.no_grad():
                fake_for_d = torch.clamp(source + generator(inputs), 0.0, 1.0)
            discriminator_loss = _d_loss(
                discriminator,
                fake_for_d,
                target,
                source,
                source_age,
                target_age,
            )
        scaler_d.scale(discriminator_loss).backward()
        scaler_d.step(discriminator_optimizer)
        scaler_d.update()

        values = {
            "g_total": 0.0,
            "paired_l1": 0.0,
            "lpips": 0.0,
            "adversarial": 0.0,
            "age_target": 0.0,
            "predicted_age": 0.0,
            "identity": 0.0,
            "identity_source": 0.0,
            "identity_target": 0.0,
            "background": 0.0,
            "legacy": 0.0,
        }
        if step > args.discriminator_warmup_steps:
            for parameter in discriminator.parameters():
                parameter.requires_grad_(False)
            generator_optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=use_amp):
                generated = torch.clamp(source + generator(inputs), 0.0, 1.0)
                with torch.no_grad():
                    legacy_reference = torch.clamp(source + teacher(inputs), 0.0, 1.0)
                if args.objective == "revised":
                    target_age_years = batch["target_age"].to(
                        device, dtype=torch.float32, non_blocking=True
                    )
                    generator_loss, values = _generator_losses(
                        discriminator,
                        perceptual,
                        age_teacher,
                        identity_teacher,
                        generated,
                        source,
                        target,
                        legacy_reference,
                        target_age,
                        target_age_years,
                        args.adversarial_weight,
                        args.age_weight,
                        args.identity_weight,
                        args.background_weight,
                        args.legacy_weight,
                    )
                else:
                    reference = legacy_reference if args.objective == "distribution" else target
                    paired_l1 = F.l1_loss(generated, reference)
                    lpips_loss = perceptual(generated * 2.0 - 1.0, reference * 2.0 - 1.0).mean()
                    logits = discriminator(_age_input(generated, target_age))
                    adversarial = F.binary_cross_entropy_with_logits(logits, torch.ones_like(logits))
                    generator_loss = paired_l1 + lpips_loss + args.adversarial_weight * adversarial
                    values.update(
                        g_total=float(generator_loss.detach()),
                        paired_l1=float(paired_l1.detach()),
                        lpips=float(lpips_loss.detach()),
                        adversarial=float(adversarial.detach()),
                    )
            scaler_g.scale(generator_loss).backward()
            scaler_g.step(generator_optimizer)
            scaler_g.update()
            for parameter in discriminator.parameters():
                parameter.requires_grad_(True)

        elapsed = time.perf_counter() - started
        peak_memory = max(
            peak_memory, torch.cuda.max_memory_allocated(device) / (1024**3)
        )
        metric = {
            "step": step,
            **values,
            "d_total": float(discriminator_loss.detach()),
            "generator_updated": step > args.discriminator_warmup_steps,
            "elapsed_seconds": round(elapsed, 3),
            "seconds_per_step": round(elapsed / step, 3),
            "peak_gpu_gib": round(peak_memory, 3),
        }
        if step == 1 or step % args.val_every == 0 or step == args.steps:
            latest_validation = validate(
                generator,
                perceptual,
                val_loader,
                device,
                args.val_batches,
                teacher,
                age_teacher,
                identity_teacher,
            )
            metric.update(latest_validation)
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metric, ensure_ascii=False) + "\n")
        if step == 1 or step % args.log_every == 0 or step == args.steps:
            print(json.dumps(metric, ensure_ascii=False), flush=True)

        if step % args.save_every == 0 or step == args.steps:
            last_generator_path, _ = save_checkpoint(
                args.output_dir,
                step,
                generator,
                discriminator,
                generator_optimizer,
                discriminator_optimizer,
                config,
            )

    save_preview(generator, val_dataset, args.output_dir / "preview_after.jpg", device)
    result = {
        "status": "complete",
        "steps": args.steps,
        "seconds": round(time.perf_counter() - started, 3),
        "seconds_per_step": round((time.perf_counter() - started) / args.steps, 3),
        "peak_gpu_gib": round(peak_memory, 3),
        "generator_checkpoint": str(last_generator_path),
        "baseline": baseline,
        "final_validation": latest_validation,
    }
    (args.output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
