"""Prepare and train a small paired FLUX.2 age-conversion LoRA pilot.

The product moves through adjacent age anchors.  This tool mirrors that
interaction instead of teaching a single adult-to-child jump:

    38 -> 32 -> 26 -> 20 -> 15 -> 11 -> 8

Only AI Hub 71415 training identities are used for optimisation.  Validation
and test identities stay sealed.  Raw licensed images remain in their ZIP
archives; this tool writes aligned, derived crops under data/experiments,
which is ignored by Git.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import align_record_image  # noqa: E402


DEFAULT_MANIFEST = ROOT / "data" / "experiments" / "face_dataset_audit" / "aihub71415_clean.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "experiments" / "aihub71415_paired_flux_pilot"
DEFAULT_MODEL = Path(r"C:\Users\PJ02\Models\FLUX2-klein-base-4B")
DEFAULT_TRAINER = Path(
    r"C:\Users\PJ02\Documents\Codex\Models\diffusers-flux2-train"
    r"\examples\dreambooth\train_dreambooth_lora_flux2_klein_img2img.py"
)
DEFAULT_PYTHON = ROOT / ".venv-flux2" / "Scripts" / "python.exe"
DEFAULT_ACCELERATE = ROOT / ".venv-flux2" / "Scripts" / "accelerate.exe"


@dataclass(frozen=True)
class Transition:
    source_anchor: int
    target_anchor: int
    source_range: tuple[int, int]
    target_range: tuple[int, int]


ALL_TRANSITIONS = (
    Transition(38, 32, (36, 42), (29, 35)),
    Transition(32, 26, (29, 35), (23, 28)),
    Transition(26, 20, (23, 28), (18, 22)),
    Transition(20, 15, (18, 22), (13, 17)),
    Transition(15, 11, (13, 17), (10, 12)),
    Transition(11, 8, (10, 12), (6, 9)),
)

CHILD_TRANSITIONS = tuple(
    transition for transition in ALL_TRANSITIONS if transition.target_anchor <= 15
)


def selected_transitions(name: str) -> tuple[Transition, ...]:
    if name == "all":
        return ALL_TRANSITIONS
    if name == "child":
        return CHILD_TRANSITIONS
    raise ValueError(f"Unknown transition set: {name}")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def in_range(value: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= int(value) <= bounds[1]


def pair_distance(source: dict, target: dict, transition: Transition) -> tuple[float, str, str]:
    distance = abs(int(source["photo_age"]) - transition.source_anchor)
    distance += abs(int(target["photo_age"]) - transition.target_anchor)
    return distance, str(source["record_id"]), str(target["record_id"])


def candidate_pairs(
    rows: list[dict], *, seed: int, transitions: tuple[Transition, ...]
) -> dict[int, list[tuple[dict, dict]]]:
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("split") == "train" and row.get("has_image"):
            by_subject[str(row["subject_id"])].append(row)

    rng = random.Random(seed)
    subjects = sorted(by_subject)
    rng.shuffle(subjects)
    result: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
    for transition in transitions:
        for subject_id in subjects:
            subject_rows = by_subject[subject_id]
            sources = [row for row in subject_rows if in_range(row["photo_age"], transition.source_range)]
            targets = [row for row in subject_rows if in_range(row["photo_age"], transition.target_range)]
            pairs = [
                (source, target)
                for source in sources
                for target in targets
                if int(source["photo_age"]) > int(target["photo_age"])
            ]
            if not pairs:
                continue
            pairs.sort(key=lambda pair: pair_distance(pair[0], pair[1], transition))
            # One pair per identity and transition prevents prolific subjects
            # from dominating the small pilot.
            result[transition.target_anchor].append(pairs[0])
    return result


class ArchiveCache:
    def __init__(self) -> None:
        self._archives: dict[str, ZipFile] = {}

    def get(self, path: str) -> ZipFile:
        if path not in self._archives:
            self._archives[path] = ZipFile(path)
        return self._archives[path]

    def close(self) -> None:
        for archive in self._archives.values():
            archive.close()
        self._archives.clear()

    def __enter__(self) -> "ArchiveCache":
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def crop_quality(image) -> tuple[bool, dict]:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    accepted = 35.0 <= brightness <= 225.0 and sharpness >= 20.0
    return accepted, {
        "brightness": round(brightness, 3),
        "laplacian_variance": round(sharpness, 3),
    }


def encode_png(path: Path, image) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"Could not encode {path}")
    encoded.tofile(path)


def prepare(args: argparse.Namespace) -> None:
    rows = read_jsonl(args.manifest)
    transitions = selected_transitions(args.transition_set)
    pools = candidate_pairs(rows, seed=args.seed, transitions=transitions)
    pair_root = args.output / "pairs"
    dataset_root = args.output / "dataset"
    if pair_root.exists():
        shutil.rmtree(pair_root)
    if dataset_root.exists():
        shutil.rmtree(dataset_root)
    pair_root.mkdir(parents=True, exist_ok=True)
    dataset_root.mkdir(parents=True, exist_ok=True)

    accepted_rows: list[dict] = []
    rejected_rows: list[dict] = []
    with ArchiveCache() as archives:
        for transition in transitions:
            accepted_for_transition = 0
            for source, target in pools[transition.target_anchor]:
                if accepted_for_transition >= args.pairs_per_transition:
                    break
                try:
                    source_image, source_alignment = align_record_image(
                        archives.get(source["image_archive_path"]), source, width=args.resolution, height=args.resolution
                    )
                    target_image, target_alignment = align_record_image(
                        archives.get(target["image_archive_path"]), target, width=args.resolution, height=args.resolution
                    )
                    source_ok, source_quality = crop_quality(source_image)
                    target_ok, target_quality = crop_quality(target_image)
                    if not source_ok or not target_ok:
                        rejected_rows.append(
                            {
                                "subject_id": source["subject_id"],
                                "source_record_id": source["record_id"],
                                "target_record_id": target["record_id"],
                                "reason": "derived_crop_quality",
                                "source_quality": source_quality,
                                "target_quality": target_quality,
                            }
                        )
                        continue
                except Exception as exc:
                    rejected_rows.append(
                        {
                            "subject_id": source["subject_id"],
                            "source_record_id": source["record_id"],
                            "target_record_id": target["record_id"],
                            "reason": f"alignment:{type(exc).__name__}",
                        }
                    )
                    continue

                pair_id = f"{transition.source_anchor:02d}_{transition.target_anchor:02d}_{source['subject_id']}"
                source_path = pair_root / "conditioning" / f"{pair_id}.png"
                target_path = pair_root / "target" / f"{pair_id}.png"
                encode_png(source_path, source_image)
                encode_png(target_path, target_image)
                accepted_rows.append(
                    {
                        "pair_id": pair_id,
                        "subject_id": str(source["subject_id"]),
                        "source_age": int(source["photo_age"]),
                        "target_age": int(target["photo_age"]),
                        "source_anchor": transition.source_anchor,
                        "target_anchor": transition.target_anchor,
                        "conditioning_image": str(source_path.resolve()),
                        "image": str(target_path.resolve()),
                        "caption": build_caption(
                            int(source["photo_age"]), int(target["photo_age"])
                        ),
                        "source_quality": source_quality,
                        "target_quality": target_quality,
                        "source_alignment": source_alignment,
                        "target_alignment": target_alignment,
                    }
                )
                accepted_for_transition += 1

    if not accepted_rows:
        raise RuntimeError("No paired examples passed alignment and quality checks")

    training_subjects = {str(row["subject_id"]) for row in accepted_rows}
    sealed_subjects = {
        str(row["subject_id"])
        for row in rows
        if str(row.get("split", "")).lower() != "train"
    }
    identity_overlap = sorted(training_subjects & sealed_subjects)
    if identity_overlap:
        preview = ", ".join(identity_overlap[:10])
        raise RuntimeError(
            "Held-out identity leakage detected in the training pairs: " + preview
        )

    from datasets import Dataset, Features, Image, Value

    features = Features(
        {
            "image": Image(),
            "conditioning_image": Image(),
            "caption": Value("string"),
        }
    )
    dataset = Dataset.from_dict(
        {
            "image": [row["image"] for row in accepted_rows],
            "conditioning_image": [row["conditioning_image"] for row in accepted_rows],
            "caption": [row["caption"] for row in accepted_rows],
        },
        features=features,
    )
    dataset.to_parquet(str(dataset_root / "train.parquet"))
    (args.output / "pairs.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in accepted_rows), encoding="utf-8"
    )
    (args.output / "rejected.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rejected_rows), encoding="utf-8"
    )
    counts = defaultdict(int)
    for row in accepted_rows:
        counts[str(row["target_anchor"])] += 1
    report = {
        "version": 2,
        "manifest": str(args.manifest),
        "split_policy": "AI Hub training identities only; one pair per identity per transition",
        "transition_set": args.transition_set,
        "transitions": [
            {
                "source_anchor": transition.source_anchor,
                "target_anchor": transition.target_anchor,
                "source_range": list(transition.source_range),
                "target_range": list(transition.target_range),
            }
            for transition in transitions
        ],
        "raw_images_copied": False,
        "accepted_pairs": len(accepted_rows),
        "rejected_pairs": len(rejected_rows),
        "training_subjects": len(training_subjects),
        "sealed_subjects": len(sealed_subjects),
        "identity_overlap": identity_overlap,
        "pairs_by_target_anchor": dict(sorted(counts.items(), key=lambda item: int(item[0]))),
        "resolution": args.resolution,
        "seed": args.seed,
    }
    (args.output / "prepare_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def build_caption(source_age: int, target_age: int) -> str:
    """Condition the adapter on exact ages and the actual backward age gap."""
    gap = source_age - target_age
    if target_age <= 9:
        stage = (
            "an unmistakable elementary-school child with a short lower face, "
            "small undeveloped jaw and chin, and full childhood cheeks"
        )
    elif target_age <= 12:
        stage = (
            "a preteen child with a shorter lower face, soft small jaw and chin, "
            "and youthful cheek volume"
        )
    else:
        stage = (
            "a mid-adolescent teenager with a less developed jaw and chin, "
            "shorter lower face, and natural teenage proportions"
        )
    return (
        "photorealistic portrait of the same Korean person; "
        f"source age {source_age}; target age {target_age}; regress age by {gap} years; "
        f"target growth stage: {stage}; preserve identity, pose, expression, lighting, "
        "and skin hue; change craniofacial age structure rather than only smoothing skin"
    )


def training_command(
    args: argparse.Namespace, *, dataset_path: Path | None = None, output_dir: Path | None = None
) -> list[str]:
    dataset_path = dataset_path or (args.output / "dataset")
    output_dir = output_dir or (args.output / "lora")
    return [
        str(args.accelerate),
        "launch",
        str(args.trainer),
        "--pretrained_model_name_or_path",
        str(args.model),
        "--dataset_name",
        str(dataset_path.resolve()),
        "--image_column",
        "image",
        "--cond_image_column",
        "conditioning_image",
        "--caption_column",
        "caption",
        "--output_dir",
        str(output_dir.resolve()),
        "--resolution",
        str(args.resolution),
        "--train_batch_size",
        "1",
        "--gradient_accumulation_steps",
        "4",
        "--max_train_steps",
        str(args.steps),
        "--learning_rate",
        str(args.learning_rate),
        "--rank",
        str(args.rank),
        "--lora_alpha",
        str(args.rank),
        "--lr_scheduler",
        "constant_with_warmup",
        "--lr_warmup_steps",
        str(max(10, args.steps // 20)),
        "--checkpointing_steps",
        str(args.checkpointing_steps or max(100, args.steps // 2)),
        "--checkpoints_total_limit",
        str(args.checkpoints_total_limit),
        "--gradient_checkpointing",
        "--cache_latents",
        "--offload",
        "--use_8bit_adam",
        "--mixed_precision",
        "bf16",
        "--seed",
        str(args.seed),
    ]


def train(args: argparse.Namespace, *, smoke: bool = False) -> None:
    dataset_dir = args.output / "dataset"
    dataset_path = dataset_dir / "train.parquet"
    output_dir = args.output / "lora"
    if not dataset_path.exists():
        raise FileNotFoundError(f"Prepare the paired dataset first: {dataset_path}")
    if smoke:
        from datasets import load_dataset

        smoke_dir = args.output / "smoke_dataset"
        if smoke_dir.exists():
            shutil.rmtree(smoke_dir)
        smoke_dir.mkdir(parents=True)
        dataset = load_dataset(str(dataset_dir), split="train")
        dataset.select(range(min(12, len(dataset)))).to_parquet(str(smoke_dir / "train.parquet"))
        dataset_dir = smoke_dir
        output_dir = args.output / "smoke_lora"
        args.steps = 2
    for required in (args.accelerate, args.trainer, args.model):
        if not required.exists():
            raise FileNotFoundError(required)
    command = training_command(args, dataset_path=dataset_dir, output_dir=output_dir)
    command_path = args.output / ("smoke_command.json" if smoke else "train_command.json")
    command_path.write_text(
        json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(subprocess.list2cmdline(command))
    if not args.dry_run:
        log_path = args.output / ("smoke_train.log" if smoke else "train.log")
        print(f"Training log: {log_path}", flush=True)
        with log_path.open("w", encoding="utf-8") as log_file:
            result = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            raise RuntimeError(
                f"Training failed with exit code {result.returncode}.\n"
                + "\n".join(tail)
            )
        print(f"Training complete: {output_dir}", flush=True)


def status(args: argparse.Namespace) -> None:
    paths = {
        "prepare_report": args.output / "prepare_report.json",
        "dataset": args.output / "dataset" / "train.parquet",
        "lora": args.output / "lora",
    }
    print(json.dumps({name: path.exists() for name, path in paths.items()}, indent=2))
    if paths["prepare_report"].exists():
        print(paths["prepare_report"].read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "smoke", "train", "status"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--trainer", type=Path, default=DEFAULT_TRAINER)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--accelerate", type=Path, default=DEFAULT_ACCELERATE)
    parser.add_argument("--pairs-per-transition", type=int, default=64)
    parser.add_argument(
        "--transition-set",
        choices=("all", "child"),
        default="all",
        help="Use all age anchors or only the 20->15->11->8 child stages.",
    )
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument(
        "--checkpointing-steps",
        type=int,
        default=0,
        help="Checkpoint interval; 0 keeps the legacy half-run interval.",
    )
    parser.add_argument("--checkpoints-total-limit", type=int, default=3)
    parser.add_argument("--seed", type=int, default=71415)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.pairs_per_transition < 1:
        parser.error("--pairs-per-transition must be positive")
    if args.checkpointing_steps < 0:
        parser.error("--checkpointing-steps cannot be negative")
    if args.checkpoints_total_limit < 1:
        parser.error("--checkpoints-total-limit must be positive")
    return args


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "smoke":
        train(args, smoke=True)
    elif args.command == "train":
        train(args)
    else:
        status(args)


if __name__ == "__main__":
    main()
