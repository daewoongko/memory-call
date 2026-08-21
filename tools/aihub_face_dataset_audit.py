"""Audit and split the two private AI Hub face datasets without copying images.

The raw photographs stay inside their original ZIP archives.  This command
validates every indexed label, removes ambiguous duplicate records, and writes
leakage-safe manifests for later training.  AI Hub 71415 is split by person;
AI Hub 045 is split by family.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_71415 = ROOT / "data/experiments/aihub71415_full/index/manifest.jsonl"
DEFAULT_045 = ROOT / "data/experiments/aihub045_full/index/manifest.jsonl"
DEFAULT_045_REPORT = ROOT / "data/experiments/aihub045_full/index/report.json"
DEFAULT_OUTPUT = ROOT / "data/experiments/face_dataset_audit"
AGE_BANDS = ((0, 5), (6, 10), (11, 17), (18, 29), (30, 44), (45, 200))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit AI Hub 71415/045 labels and write leakage-safe splits"
    )
    parser.add_argument("--aging-manifest", type=Path, default=DEFAULT_71415)
    parser.add_argument("--family-manifest", type=Path, default=DEFAULT_045)
    parser.add_argument("--family-index-report", type=Path, default=DEFAULT_045_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--salt", default="memory-call-face-datasets-v2")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def stable_bucket(value: str, salt: str, modulo: int = 100) -> int:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulo


def age_band(age: int) -> str:
    for low, high in AGE_BANDS:
        if low <= age <= high:
            return f"{low:02d}-{high if high < 200 else '+'}"
    return "invalid"


def valid_geometry(row: dict) -> bool:
    box = row.get("box") or {}
    values = [float(box.get(key, 0)) for key in ("x", "y", "w", "h")]
    # A valid face box may extend a few pixels outside the photograph.  Crop
    # code clamps it later, so negative x/y is not a labeling failure.
    if not all(math.isfinite(value) for value in values) or values[2] <= 0 or values[3] <= 0:
        return False
    landmarks = row.get("landmarks") or []
    return len(landmarks) >= 5 and all(
        isinstance(point, list)
        and len(point) >= 2
        and math.isfinite(float(point[0]))
        and math.isfinite(float(point[1]))
        for point in landmarks[:5]
    )


def deduplicate(rows: list[dict], *, dataset: str) -> tuple[list[dict], list[dict]]:
    seen_records: dict[str, dict] = {}
    seen_members: dict[tuple, str] = {}
    clean: list[dict] = []
    excluded: list[dict] = []
    for row in rows:
        reason = None
        record_id = str(row.get("record_id") or "")
        member_key = (
            str(row.get("image_archive_path") or ""),
            str(row.get("image_member") or "").casefold(),
            str(row.get("identity_id") or row.get("subject_id") or ""),
        )
        if not record_id:
            reason = "missing_record_id"
        elif not row.get("image_member") or row.get("has_image") is False:
            reason = "missing_image_member"
        elif not valid_geometry(row):
            reason = "invalid_face_geometry"
        elif record_id in seen_records:
            reason = "duplicate_record_id"
        elif member_key in seen_members:
            reason = "duplicate_image_member_for_identity"
        if reason:
            excluded.append(
                {
                    "dataset": dataset,
                    "record_id": record_id,
                    "reason": reason,
                    "kept_record_id": seen_members.get(member_key),
                }
            )
            continue
        seen_records[record_id] = row
        seen_members[member_key] = record_id
        clean.append(row)
    return clean, excluded


def assign_split(row: dict, *, group_key: str, salt: str) -> str:
    # Official Validation remains a sealed test set.  Only official Training is
    # divided into train/validation, and the group key prevents identity leaks.
    if str(row.get("dataset_partition")).lower() == "validation":
        return "test"
    return "validation" if stable_bucket(str(row[group_key]), salt) < 10 else "train"


def dataset_report(rows: list[dict], *, group_key: str, age_key: str) -> dict:
    groups: defaultdict[str, set[str]] = defaultdict(set)
    ages: Counter[int] = Counter()
    splits: Counter[str] = Counter()
    for row in rows:
        group = str(row[group_key])
        split = str(row["split"])
        groups[group].add(split)
        ages[int(row[age_key])] += 1
        splits[split] += 1
    return {
        "records": len(rows),
        "groups": len(groups),
        "split_records": dict(sorted(splits.items())),
        "split_groups": {
            split: len({str(row[group_key]) for row in rows if row["split"] == split})
            for split in ("train", "validation", "test")
        },
        "group_leakage_count": sum(len(value) > 1 for value in groups.values()),
        "age_min": min(ages) if ages else None,
        "age_max": max(ages) if ages else None,
        "age_bands": dict(sorted({
            band: sum(count for age, count in ages.items() if age_band(age) == band)
            for band in {age_band(age) for age in ages}
        }.items())),
        "exact_age_8_records": ages[8],
    }


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    aging_raw = read_jsonl(args.aging_manifest.resolve())
    family_raw = read_jsonl(args.family_manifest.resolve())
    aging_clean, aging_excluded = deduplicate(aging_raw, dataset="aihub71415")
    family_clean, family_excluded = deduplicate(family_raw, dataset="aihub045")

    for row in aging_clean:
        row["split"] = assign_split(
            row, group_key="subject_id", salt=f"{args.salt}:71415"
        )
    for row in family_clean:
        row["split"] = assign_split(
            row, group_key="family_id", salt=f"{args.salt}:045"
        )

    aging_clean.sort(key=lambda row: (row["split"], row["subject_id"], row["photo_age"], row["record_id"]))
    family_clean.sort(key=lambda row: (row["split"], row["family_id"], row["identity_id"], row["age"], row["record_id"]))
    write_jsonl(output / "aihub71415_clean.jsonl", aging_clean)
    write_jsonl(output / "aihub045_clean.jsonl", family_clean)
    write_jsonl(output / "excluded.jsonl", [*aging_excluded, *family_excluded])

    family_index_report = {}
    if args.family_index_report.is_file():
        family_index_report = json.loads(
            args.family_index_report.read_text(encoding="utf-8")
        )
    report = {
        "version": 1,
        "policy": {
            "raw_images_copied": False,
            "aihub71415_group_split": "subject_id",
            "aihub045_group_split": "family_id",
            "official_validation_usage": "sealed_test_only",
            "training_partition_usage": "deterministic_90_10_train_validation",
            "ambiguous_filename_repairs": "excluded_not_guessed",
        },
        "aihub71415": {
            "indexed_records": len(aging_raw),
            "excluded_records": len(aging_excluded),
            **dataset_report(aging_clean, group_key="subject_id", age_key="photo_age"),
        },
        "aihub045": {
            "indexed_records": len(family_raw),
            "index_error_count": int(family_index_report.get("error_count", 0)),
            "excluded_records": len(family_excluded),
            **dataset_report(family_clean, group_key="family_id", age_key="age"),
        },
    }
    if report["aihub71415"]["group_leakage_count"]:
        raise RuntimeError("AI Hub 71415 subject leakage detected")
    if report["aihub045"]["group_leakage_count"]:
        raise RuntimeError("AI Hub 045 family leakage detected")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
