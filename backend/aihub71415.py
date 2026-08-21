"""Utilities for the AI Hub 71415 longitudinal face-aging dataset.

The raw archive contains sensitive face images.  This module deliberately reads
the archive in place and only emits explicit experiment artefacts.  It never
copies raw files into the repository's public media directories.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator
from zipfile import ZipFile


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_SPLIT_SALT = "memory-call-aihub71415-v1"


def _target_age_band(age: int) -> str:
    if age <= 5:
        return "00-05"
    if age <= 10:
        return "06-10"
    if age <= 17:
        return "11-17"
    if age <= 29:
        return "18-29"
    if age <= 44:
        return "30-44"
    return "45+"


def build_balanced_sampling_weights(
    pairs: list[dict],
    *,
    focus_target_age: int,
    focus_radius: int,
    focus_boost: float,
) -> tuple[list[float], dict]:
    """Balance people, target-age bands and age gaps without ML imports."""

    if not pairs:
        raise ValueError("Cannot build sampling weights for an empty pair list")
    subject_counts = Counter(str(pair["subject_id"]) for pair in pairs)
    target_bands = Counter(_target_age_band(int(pair["target_age"])) for pair in pairs)
    gap_bands = Counter(str(pair["gap_band"]) for pair in pairs)
    subject_median = float(statistics.median(subject_counts.values()))
    total = float(len(pairs))
    raw_weights: list[float] = []
    for pair in pairs:
        target_age = int(pair["target_age"])
        age_band = _target_age_band(target_age)
        gap_band = str(pair["gap_band"])
        age_factor = total / (len(target_bands) * target_bands[age_band])
        gap_factor = total / (len(gap_bands) * gap_bands[gap_band])
        subject_factor = math.sqrt(
            subject_median / subject_counts[str(pair["subject_id"])]
        )
        focus_factor = (
            focus_boost
            if abs(target_age - focus_target_age) <= focus_radius
            else 1.0
        )
        raw_weights.append(age_factor * gap_factor * subject_factor * focus_factor)

    clipped = [min(10.0, max(0.1, value)) for value in raw_weights]
    mean_weight = sum(clipped) / len(clipped)
    weights = [value / mean_weight for value in clipped]
    mass_by_target_band: Counter[str] = Counter()
    mass_by_gap_band: Counter[str] = Counter()
    focus_mass = 0.0
    for pair, weight in zip(pairs, weights):
        target_age = int(pair["target_age"])
        mass_by_target_band[_target_age_band(target_age)] += weight
        mass_by_gap_band[str(pair["gap_band"])] += weight
        if abs(target_age - focus_target_age) <= focus_radius:
            focus_mass += weight
    weight_sum = sum(weights)
    report = {
        "strategy": "balanced_age_gap_subject",
        "pair_count": len(pairs),
        "subject_count": len(subject_counts),
        "focus_target_age": focus_target_age,
        "focus_radius": focus_radius,
        "focus_boost": focus_boost,
        "expected_focus_fraction": focus_mass / weight_sum,
        "expected_target_band_fraction": {
            key: value / weight_sum for key, value in sorted(mass_by_target_band.items())
        },
        "expected_gap_band_fraction": {
            key: value / weight_sum for key, value in sorted(mass_by_gap_band.items())
        },
        "weight_min": min(weights),
        "weight_max": max(weights),
    }
    return weights, report


@dataclass(frozen=True)
class AgingRecord:
    """One labeled photograph without embedding the image itself."""

    record_id: str
    subject_id: str
    birth_year: int
    photo_age: int
    current_age: int
    gender: str
    filename: str
    image_format: str
    width: int
    height: int
    device: str
    label_member: str
    image_member: str | None
    box: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]

    @property
    def has_image(self) -> bool:
        return self.image_member is not None

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "subject_id": self.subject_id,
            "birth_year": self.birth_year,
            "photo_age": self.photo_age,
            "current_age": self.current_age,
            "gender": self.gender,
            "filename": self.filename,
            "image_format": self.image_format,
            "width": self.width,
            "height": self.height,
            "device": self.device,
            "label_member": self.label_member,
            "image_member": self.image_member,
            "has_image": self.has_image,
            "box": {
                "x": self.box[0],
                "y": self.box[1],
                "w": self.box[2],
                "h": self.box[3],
            },
            "landmarks": [list(point) for point in self.landmarks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgingRecord":
        box = data["box"]
        return cls(
            record_id=str(data["record_id"]),
            subject_id=str(data["subject_id"]),
            birth_year=int(data["birth_year"]),
            photo_age=int(data["photo_age"]),
            current_age=int(data["current_age"]),
            gender=str(data.get("gender") or "unspecified"),
            filename=str(data["filename"]),
            image_format=str(data.get("image_format") or "png"),
            width=int(data["width"]),
            height=int(data["height"]),
            device=str(data.get("device") or "unknown"),
            label_member=str(data["label_member"]),
            image_member=data.get("image_member"),
            box=(float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])),
            landmarks=tuple(
                (float(point[0]), float(point[1])) for point in data.get("landmarks", [])
            ),
        )


def _member_key(member: str) -> str:
    """Return the dataset filename key independent of packaging quirks.

    AI Hub 71415 contains two harmless but important naming variants: some
    source members use lower-case device suffixes while labels use upper-case,
    and one subject stores ``.png`` inside the label's ``filename`` field.
    ZIP lookups are case-sensitive, so normalize both sides before matching.
    """

    return PurePosixPath(str(member)).stem.casefold()


def _stable_id(*parts: object, length: int = 20) -> str:
    raw = ":".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def _single_face_annotation(label: dict, member: str) -> tuple[dict, list]:
    annotations = label.get("annotation")
    if not isinstance(annotations, list) or len(annotations) != 1:
        raise ValueError(f"Expected exactly one face annotation: {member}")
    annotation = annotations[0]
    box = annotation.get("box")
    landmarks = annotation.get("landmark")
    if not isinstance(box, dict) or not {"x", "y", "w", "h"}.issubset(box):
        raise ValueError(f"Invalid face box: {member}")
    if not isinstance(landmarks, list) or len(landmarks) < 5:
        raise ValueError(f"Expected five face landmarks: {member}")
    return box, landmarks


def index_archive(
    archive_path: Path,
    image_archive_path: Path | None = None,
) -> tuple[list[AgingRecord], dict]:
    """Read a sample/full archive and return metadata records plus a summary."""

    archive_path = Path(archive_path).expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)

    image_archive_path = Path(image_archive_path or archive_path).expanduser().resolve()
    if not image_archive_path.is_file():
        raise FileNotFoundError(image_archive_path)

    records: list[AgingRecord] = []
    invalid_labels: list[dict] = []
    duplicate_images: list[str] = []
    with ZipFile(image_archive_path) as image_archive:
        image_members: dict[str, str] = {}
        for member in image_archive.namelist():
            suffix = PurePosixPath(member).suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                key = _member_key(member)
                if key in image_members:
                    duplicate_images.append(key)
                else:
                    image_members[key] = member
    with ZipFile(archive_path) as archive:
        label_members = [
            member
            for member in archive.namelist()
            if PurePosixPath(member).suffix.lower() == ".json"
        ]

        for member in sorted(label_members):
            try:
                label = json.loads(archive.read(member).decode("utf-8-sig"))
                filename = str(label["filename"])
                box, landmarks = _single_face_annotation(label, member)
                subject_id = str(label["id"]).zfill(4)
                record_id = _stable_id(subject_id, filename)
                image_member = image_members.get(_member_key(filename))
                records.append(
                    AgingRecord(
                        record_id=record_id,
                        subject_id=subject_id,
                        birth_year=int(label["birth"]),
                        photo_age=int(label["age_past"]),
                        current_age=int(label["age_now"]),
                        gender=str(label.get("gender") or "unspecified").lower(),
                        filename=filename,
                        image_format=str(label.get("format") or "png").lower(),
                        width=int(label["width"]),
                        height=int(label["height"]),
                        device=str(label.get("device") or "unknown"),
                        label_member=member,
                        image_member=image_member,
                        box=(
                            float(box["x"]),
                            float(box["y"]),
                            float(box["w"]),
                            float(box["h"]),
                        ),
                        landmarks=tuple(
                            (float(point[0]), float(point[1])) for point in landmarks[:5]
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                invalid_labels.append({"member": member, "error": str(exc)})

    records.sort(key=lambda item: (item.subject_id, item.photo_age, item.filename))
    age_counts = Counter(record.photo_age for record in records if record.has_image)
    per_subject = Counter(record.subject_id for record in records if record.has_image)
    summary = {
        "dataset": "AI Hub 71415 안면 인식 에이징 이미지 데이터",
        "label_archive_name": archive_path.name,
        "image_archive_name": image_archive_path.name,
        "labels": len(records),
        "matched_images": sum(record.has_image for record in records),
        "label_only": sum(not record.has_image for record in records),
        "invalid_label_count": len(invalid_labels),
        "invalid_labels": invalid_labels[:25],
        "duplicate_image_key_count": len(duplicate_images),
        "subjects_with_images": len(per_subject),
        "images_per_subject_min": min(per_subject.values(), default=0),
        "images_per_subject_max": max(per_subject.values(), default=0),
        "photo_age_min": min(age_counts, default=None),
        "photo_age_max": max(age_counts, default=None),
        "exact_age_8_images": age_counts.get(8, 0),
        "exact_age_8_subjects": len(
            {record.subject_id for record in records if record.has_image and record.photo_age == 8}
        ),
        "age_counts": {str(age): age_counts[age] for age in sorted(age_counts)},
    }
    return records, summary


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc


def prepare_aligned_record(
    archive: ZipFile,
    row: dict,
    *,
    output_path: Path,
    width: int = 768,
    height: int = 1024,
) -> dict:
    """Align one face from its labeled five points and write a derived crop."""

    aligned, alignment = align_record_image(
        archive,
        row,
        width=width,
        height=height,
    )

    import cv2

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, output_encoded = cv2.imencode(".png", aligned)
    if not ok:
        raise RuntimeError(f"Could not encode aligned face: {output_path}")
    output_encoded.tofile(output_path)

    prepared = dict(row)
    prepared["prepared_path"] = output_path.as_posix()
    prepared["prepared_width"] = width
    prepared["prepared_height"] = height
    prepared["alignment"] = alignment
    return prepared


def align_record_image(
    archive: ZipFile,
    row: dict,
    *,
    width: int = 512,
    height: int = 512,
):
    """Decode and align one labeled face without writing it to disk.

    The training loader uses this function so the licensed raw images remain in
    their AI Hub ZIP archives.  The returned image uses OpenCV's BGR channel
    order; callers that create tensors must convert it to RGB.
    """

    import cv2
    import numpy as np

    image_member = row.get("image_member")
    if not image_member:
        raise ValueError(f"Record has no source image: {row.get('record_id')}")
    encoded = np.frombuffer(archive.read(image_member), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode: {image_member}")

    actual_height, actual_width = image.shape[:2]
    label_width = max(int(row["width"]), 1)
    label_height = max(int(row["height"]), 1)
    scale_x = actual_width / label_width
    scale_y = actual_height / label_height

    points = np.asarray(row.get("landmarks", []), dtype=np.float32)
    if points.shape != (5, 2):
        raise ValueError(f"Expected exactly five landmarks: {row.get('record_id')}")
    points[:, 0] *= scale_x
    points[:, 1] *= scale_y
    # Dataset order: nose, left eye, right eye, left mouth, right mouth.
    canonical = np.asarray(
        [
            [0.50 * width, 0.56 * height],
            [0.32 * width, 0.38 * height],
            [0.68 * width, 0.38 * height],
            [0.38 * width, 0.69 * height],
            [0.62 * width, 0.69 * height],
        ],
        dtype=np.float32,
    )
    matrix, inliers = cv2.estimateAffinePartial2D(points, canonical, method=cv2.LMEDS)
    if matrix is None:
        raise ValueError(f"Could not estimate face alignment: {row.get('record_id')}")
    aligned = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    transformed = cv2.transform(points[None, :, :], matrix)[0]
    landmark_error = float(
        np.linalg.norm(transformed - canonical, axis=1).mean()
        / max(float(np.hypot(width, height)), 1.0)
    )

    alignment = {
        "method": "labeled_5_point_similarity",
        "normalized_landmark_error": round(landmark_error, 8),
        "inlier_count": int(inliers.sum()) if inliers is not None else 5,
        "label_size_matches_image": label_width == actual_width and label_height == actual_height,
    }
    return aligned, alignment


def assign_subject_split(
    subject_id: str,
    *,
    salt: str = DEFAULT_SPLIT_SALT,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
) -> str:
    """Assign one person to one stable split, preventing identity leakage."""

    if train_ratio <= 0 or val_ratio < 0 or train_ratio + val_ratio >= 1:
        raise ValueError("Split ratios must leave a non-empty test range")
    digest = hashlib.sha256(f"{salt}:{subject_id}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / float(2**64)
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def assign_official_subject_split(
    subject_id: str,
    dataset_partition: str | None,
    *,
    salt: str = DEFAULT_SPLIT_SALT,
    training_val_ratio: float = 0.1,
) -> str:
    """Keep the official validation people hidden and split training people only.

    AI Hub already separates people between Training and Validation.  The
    official Validation partition is therefore the final test set.  A stable
    subset of official Training people is used for model selection.
    """

    partition = str(dataset_partition or "").strip().casefold()
    if partition == "validation":
        return "test"
    if partition == "training":
        if not 0 < training_val_ratio < 1:
            raise ValueError("training_val_ratio must be between zero and one")
        digest = hashlib.sha256(f"{salt}:official:{subject_id}".encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big") / float(2**64)
        return "val" if value < training_val_ratio else "train"
    return assign_subject_split(subject_id, salt=salt)


def _spread(records: list[dict], limit: int) -> list[dict]:
    """Keep age coverage without letting prolific subjects dominate."""

    if limit <= 0 or len(records) <= limit:
        return records
    records = sorted(records, key=lambda row: (int(row["photo_age"]), row["record_id"]))
    if limit == 1:
        return [records[-1]]
    indexes = {
        round(index * (len(records) - 1) / (limit - 1)) for index in range(limit)
    }
    return [records[index] for index in sorted(indexes)]


def build_pair_and_holdout_rows(
    rows: Iterable[dict],
    *,
    target_age: int = 8,
    max_sources_per_target: int = 6,
    salt: str = DEFAULT_SPLIT_SALT,
) -> tuple[list[dict], list[dict], dict]:
    """Create same-person older→younger pairs and hidden age-target cases."""

    usable = [row for row in rows if row.get("has_image", True)]
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for row in usable:
        subject_id = str(row["subject_id"])
        enriched = dict(row)
        enriched["split"] = assign_official_subject_split(
            subject_id,
            row.get("dataset_partition"),
            salt=salt,
        )
        by_subject[subject_id].append(enriched)

    pairs: list[dict] = []
    holdouts: list[dict] = []
    for subject_id, subject_rows in sorted(by_subject.items()):
        subject_rows.sort(key=lambda row: (int(row["photo_age"]), row["record_id"]))
        subject_splits = {row["split"] for row in subject_rows}
        if len(subject_splits) != 1:
            raise ValueError(f"Subject {subject_id} appears in multiple splits: {subject_splits}")
        split = subject_rows[0]["split"]
        if split in {"train", "val"}:
            for target in subject_rows:
                older = [
                    row
                    for row in subject_rows
                    if int(row["photo_age"]) > int(target["photo_age"])
                ]
                for source in _spread(older, max_sources_per_target):
                    gap = int(source["photo_age"]) - int(target["photo_age"])
                    pairs.append(
                        {
                            "pair_id": _stable_id(source["record_id"], target["record_id"]),
                            "subject_id": subject_id,
                            "split": split,
                            "source_record_id": source["record_id"],
                            "source_age": int(source["photo_age"]),
                            "source_path": source.get("prepared_path") or source["image_member"],
                            "source_archive_path": source.get("image_archive_path"),
                            "target_record_id": target["record_id"],
                            "target_age": int(target["photo_age"]),
                            "target_path": target.get("prepared_path") or target["image_member"],
                            "target_archive_path": target.get("image_archive_path"),
                            "age_gap": gap,
                            "gap_band": "small" if gap <= 4 else "medium" if gap <= 12 else "large",
                        }
                    )

        exact_targets = [row for row in subject_rows if int(row["photo_age"]) == target_age]
        if exact_targets:
            target = sorted(
                exact_targets,
                key=lambda row: (-int(row.get("width", 0)) * int(row.get("height", 0)), row["record_id"]),
            )[0]
            available = [row for row in subject_rows if int(row["photo_age"]) > target_age]
            adults = [row for row in available if int(row["photo_age"]) >= 18]

            def source_view(source: dict) -> dict:
                return {
                    "record_id": source["record_id"],
                    "photo_age": int(source["photo_age"]),
                    "path": source.get("prepared_path") or source["image_member"],
                    "archive_path": source.get("image_archive_path"),
                }

            holdouts.append(
                {
                    "case_id": f"age{target_age}_{subject_id}",
                    "subject_id": subject_id,
                    "split": split,
                    "formal_eval": split == "test" and bool(adults),
                    "target_age": target_age,
                    "hidden_target": {
                        "record_id": target["record_id"],
                        "path": target.get("prepared_path") or target["image_member"],
                        "archive_path": target.get("image_archive_path"),
                    },
                    "excluded_target_record_ids": [row["record_id"] for row in exact_targets],
                    "adult_only_sources": [source_view(row) for row in _spread(adults, 5)],
                    "available_anchor_sources": [source_view(row) for row in _spread(available, 5)],
                }
            )

    split_subject_counts = Counter(
        rows[0]["split"] for rows in by_subject.values()
    )
    pair_counts = Counter(pair["split"] for pair in pairs)
    summary = {
        "subjects": len(by_subject),
        "split_subject_counts": dict(sorted(split_subject_counts.items())),
        "training_pairs": pair_counts.get("train", 0),
        "validation_pairs": pair_counts.get("val", 0),
        "pair_rows_total": len(pairs),
        "target_age": target_age,
        "holdout_cases": len(holdouts),
        "formal_eval_cases": sum(case["formal_eval"] for case in holdouts),
        "adult_only_cases": sum(bool(case["adult_only_sources"]) for case in holdouts),
        "available_anchor_cases": sum(bool(case["available_anchor_sources"]) for case in holdouts),
        "identity_leakage_policy": "official Validation is test-only; official Training people are deterministically split into train/val",
        "target_leakage_policy": f"all exact age {target_age} records are excluded from each case's sources",
    }
    return pairs, holdouts, summary
