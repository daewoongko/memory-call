"""Index AI Hub dataset 71415 without extracting private face images."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import index_archive, write_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="Label ZIP, or the combined sample ZIP")
    source.add_argument(
        "--dataset-root",
        type=Path,
        help="AI Hub 71415 root containing Training/Validation source and label ZIP shards",
    )
    parser.add_argument(
        "--image-archive",
        type=Path,
        default=None,
        help="Source-image ZIP when full dataset images and labels are separate",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "experiments" / "aihub71415_sample" / "index",
    )
    return parser.parse_args()


def _archive_id(path: Path) -> int:
    match = re.search(r"(\d+)", path.stem)
    if not match:
        raise ValueError(f"Archive has no numeric shard id: {path}")
    return int(match.group(1))


def _discover_shards(dataset_root: Path) -> list[tuple[str, int, Path, Path]]:
    """Pair official source/label shards without relying on Korean folder names."""

    dataset_root = dataset_root.expanduser().resolve()
    if not dataset_root.is_dir():
        raise FileNotFoundError(dataset_root)

    specs = (
        ("training", "TS_*.zip", "TL_*.zip"),
        ("validation", "VS_*.zip", "VL_*.zip"),
    )
    pairs: list[tuple[str, int, Path, Path]] = []
    for partition, image_pattern, label_pattern in specs:
        images = {_archive_id(path): path for path in dataset_root.rglob(image_pattern)}
        labels = {_archive_id(path): path for path in dataset_root.rglob(label_pattern)}
        missing_labels = sorted(set(images) - set(labels))
        missing_images = sorted(set(labels) - set(images))
        if missing_labels or missing_images:
            raise ValueError(
                f"Unpaired {partition} shards: source_only={missing_labels}, label_only={missing_images}"
            )
        pairs.extend(
            (partition, shard_id, labels[shard_id], images[shard_id])
            for shard_id in sorted(images)
        )
    if not pairs:
        raise ValueError(f"No AI Hub 71415 shard pairs found under {dataset_root}")
    return pairs


def _index_dataset_root(dataset_root: Path) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    shard_summaries: list[dict] = []
    age_counts: Counter[int] = Counter()
    subjects: set[str] = set()
    exact_age_8_subjects: set[str] = set()

    for index, (partition, shard_id, label_path, image_path) in enumerate(
        _discover_shards(dataset_root), start=1
    ):
        records, summary = index_archive(label_path, image_path)
        for record in records:
            row = record.to_dict()
            row.update(
                {
                    "dataset_partition": partition,
                    "archive_shard": shard_id,
                    "image_archive_path": str(image_path),
                    "label_archive_path": str(label_path),
                }
            )
            rows.append(row)
            subjects.add(record.subject_id)
            if record.has_image:
                age_counts[record.photo_age] += 1
                if record.photo_age == 8:
                    exact_age_8_subjects.add(record.subject_id)
        shard_summaries.append(
            {
                "partition": partition,
                "shard": shard_id,
                "labels": summary["labels"],
                "matched_images": summary["matched_images"],
                "label_only": summary["label_only"],
                "invalid_label_count": summary["invalid_label_count"],
            }
        )
        if index % 100 == 0:
            print(f"indexed {index} archive pairs")

    per_partition = Counter(row["dataset_partition"] for row in rows if row["has_image"])
    summary = {
        "dataset": "AI Hub 71415 face aging image data",
        "dataset_root": str(dataset_root.expanduser().resolve()),
        "archive_pairs": len(shard_summaries),
        "archive_pairs_by_partition": dict(
            Counter(item["partition"] for item in shard_summaries)
        ),
        "labels": len(rows),
        "matched_images": sum(bool(row["has_image"]) for row in rows),
        "label_only": sum(not row["has_image"] for row in rows),
        "invalid_label_count": sum(item["invalid_label_count"] for item in shard_summaries),
        "subjects_with_images": len(subjects),
        "images_by_partition": dict(sorted(per_partition.items())),
        "photo_age_min": min(age_counts, default=None),
        "photo_age_max": max(age_counts, default=None),
        "exact_age_8_images": age_counts.get(8, 0),
        "exact_age_8_subjects": len(exact_age_8_subjects),
        "age_counts": {str(age): age_counts[age] for age in sorted(age_counts)},
        "privacy": "manifest contains metadata and local archive paths, not face pixels",
    }
    return rows, summary


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if args.dataset_root:
        rows, summary = _index_dataset_root(args.dataset_root)
    else:
        records, summary = index_archive(args.archive, args.image_archive)
        rows = [record.to_dict() for record in records]
    manifest = output_dir / "manifest.jsonl"
    write_jsonl(manifest, rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest  {manifest}")
    print(f"labels    {summary['labels']}")
    print(f"images    {summary['matched_images']}")
    print(f"subjects  {summary['subjects_with_images']}")
    print(f"age 8     {summary['exact_age_8_images']} images / {summary['exact_age_8_subjects']} subjects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
