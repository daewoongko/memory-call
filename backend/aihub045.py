"""Private-data helpers for AI Hub 045 family-aware face photographs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator
from zipfile import ZipFile


def stable_id(*parts: object, length: int = 24) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).hexdigest()[:length]


def read_jsonl(path: Path) -> Iterator[dict]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def archive_key(path: Path) -> str:
    stem = path.stem.casefold()
    return stem[2:] if stem.startswith(("tl", "ts", "vl", "vs")) else stem


def index_dataset(root: Path) -> tuple[list[dict], dict]:
    root = root.resolve()
    archives = list(root.rglob("*.zip"))
    image_archives = {
        archive_key(path): path
        for path in archives
        if path.stem.casefold().startswith(("ts", "vs"))
    }
    label_archives = [
        path for path in archives if path.stem.casefold().startswith(("tl", "vl"))
    ]
    rows: list[dict] = []
    errors: list[dict] = []
    for label_archive in sorted(label_archives):
        image_archive = image_archives.get(archive_key(label_archive))
        if image_archive is None:
            errors.append({"archive": str(label_archive), "error": "matching source ZIP missing"})
            continue
        with ZipFile(image_archive) as source_zip:
            image_members = {
                PurePosixPath(member).name.casefold(): member
                for member in source_zip.namelist()
                if PurePosixPath(member).suffix.lower() in {".jpg", ".jpeg", ".png"}
            }
        with ZipFile(label_archive) as label_zip:
            for member_name in label_zip.namelist():
                if not member_name.lower().endswith(".json"):
                    continue
                try:
                    label = json.loads(label_zip.read(member_name).decode("utf-8-sig"))
                    image_member = image_members[PurePosixPath(label["filename"]).name.casefold()]
                    family_id = str(label["family_id"])
                    partition = (
                        "validation"
                        if label_archive.stem.casefold().startswith("vl")
                        or "validation" in str(label_archive).casefold()
                        else "training"
                    )
                    for person in label.get("member", []):
                        regions = person.get("regions") or []
                        if not regions:
                            continue
                        region = regions[0]
                        points_by_index = {
                            int(point["idx"]): [float(point["x"]), float(point["y"])]
                            for point in region.get("keypoint", [])
                        }
                        boxes = {int(box["idx"]): box for box in region.get("boundingbox", [])}
                        if not all(index in points_by_index for index in range(5)) or 0 not in boxes:
                            raise ValueError("missing five landmarks or face box")
                        box = boxes[0]
                        personal_id = str(person["personal_id"])
                        rows.append(
                            {
                                "record_id": stable_id(label["file_id"], personal_id),
                                "file_id": str(label["file_id"]),
                                "family_id": family_id,
                                "personal_id": personal_id,
                                "identity_id": f"{family_id}:{personal_id}",
                                "age": int(person["age"]),
                                "dataset_partition": partition,
                                "label_archive_path": str(label_archive),
                                "label_member": member_name,
                                "image_archive_path": str(image_archive),
                                "image_member": image_member,
                                "landmarks": [points_by_index[index] for index in range(5)],
                                "box": {key: float(box[key]) for key in ("x", "y", "w", "h")},
                            }
                        )
                except Exception as exc:
                    errors.append({"archive": str(label_archive), "member": member_name, "error": str(exc)})
    rows.sort(key=lambda row: (row["family_id"], row["personal_id"], row["file_id"]))
    identities = {row["identity_id"] for row in rows}
    families = {row["family_id"] for row in rows}
    report = {
        "root": str(root),
        "records": len(rows),
        "families": len(families),
        "identities": len(identities),
        "training_records": sum(row["dataset_partition"] == "training" for row in rows),
        "validation_records": sum(row["dataset_partition"] == "validation" for row in rows),
        "error_count": len(errors),
        "errors": errors[:50],
    }
    return rows, report
