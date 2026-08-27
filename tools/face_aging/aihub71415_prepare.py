"""Create private, aligned crops from AI Hub 71415 labeled landmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import prepare_aligned_record, read_jsonl, write_jsonl  # noqa: E402


AGE_BANDS = (
    ("00_05", 0, 5),
    ("06_12", 6, 12),
    ("13_17", 13, 17),
    ("18_29", 18, 29),
    ("30_44", 30, 44),
    ("45_59", 45, 59),
    ("60_plus", 60, 200),
)


def age_band(age: int) -> str:
    for name, minimum, maximum in AGE_BANDS:
        if minimum <= age <= maximum:
            return name
    return "unknown"


def _stable_order(row: dict) -> tuple[str, str]:
    digest = hashlib.sha256(str(row["record_id"]).encode("utf-8")).hexdigest()
    return digest, str(row["record_id"])


def select_age_band_sample(rows: list[dict], per_band: int) -> list[dict]:
    """Select deterministic, subject-diverse records from every age band."""

    if per_band <= 0:
        return rows
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[age_band(int(row["photo_age"]))].append(row)

    selected: list[dict] = []
    for band_name, _, _ in AGE_BANDS:
        candidates = sorted(grouped.get(band_name, []), key=_stable_order)
        used_subjects: set[str] = set()
        band_rows: list[dict] = []
        for row in candidates:
            subject_id = str(row["subject_id"])
            if subject_id in used_subjects:
                continue
            band_rows.append(row)
            used_subjects.add(subject_id)
            if len(band_rows) == per_band:
                break
        if len(band_rows) < per_band:
            chosen = {str(row["record_id"]) for row in band_rows}
            band_rows.extend(
                row
                for row in candidates
                if str(row["record_id"]) not in chosen
            )
            band_rows = band_rows[:per_band]
        selected.extend(band_rows)
    return selected


def write_contact_sheet(prepared_rows: list[dict], output_path: Path) -> None:
    """Create a private visual QA sheet; never used as a training input."""

    from PIL import Image, ImageDraw, ImageFont

    if not prepared_rows:
        return
    thumb_width, thumb_height, label_height = 180, 240, 44
    columns = 6
    rows_count = (len(prepared_rows) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * thumb_width, rows_count * (thumb_height + label_height)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, row in enumerate(prepared_rows):
        source = output_path.parent / str(row["prepared_path"])
        with Image.open(source) as image:
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail((thumb_width, thumb_height))
            x = (index % columns) * thumb_width + (thumb_width - thumbnail.width) // 2
            y = (index // columns) * (thumb_height + label_height)
            canvas.paste(thumbnail, (x, y))
        label = (
            f"age {row['photo_age']} | id {row['subject_id']}\n"
            f"{row.get('dataset_partition', 'sample')} | {age_band(int(row['photo_age']))}"
        )
        draw.multiline_text((index % columns * thumb_width + 5, y + thumb_height + 3), label, fill="#10281e", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Single source ZIP. Omit for a full manifest containing image_archive_path.",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--limit", type=int, default=0, help="0 prepares every matched image")
    parser.add_argument(
        "--sample-per-age-band",
        type=int,
        default=0,
        help="Deterministically prepare N different people per age band for visual QA",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    prepared_root = output_dir / "prepared"
    rows = [row for row in read_jsonl(args.manifest) if row.get("has_image", True)]
    if args.sample_per_age_band > 0:
        rows = select_age_band_sample(rows, args.sample_per_age_band)
    if args.limit > 0:
        rows = rows[: args.limit]

    prepared: list[dict] = []
    failures: list[dict] = []
    rows_by_archive: dict[Path, list[dict]] = defaultdict(list)
    for row in rows:
        archive_value = args.archive or row.get("image_archive_path")
        if not archive_value:
            failures.append(
                {"record_id": row.get("record_id"), "error": "No source archive path"}
            )
            continue
        rows_by_archive[Path(archive_value).expanduser().resolve()].append(row)

    processed = 0
    for archive_path, archive_rows in sorted(rows_by_archive.items(), key=lambda item: str(item[0])):
        with ZipFile(archive_path) as archive:
            for row in archive_rows:
                processed += 1
                relative = (
                    Path(str(row["subject_id"]))
                    / f"age_{int(row['photo_age']):02d}"
                    / f"{row['record_id']}.png"
                )
                destination = prepared_root / relative
                try:
                    if destination.is_file() and not args.overwrite:
                        prepared_row = dict(row)
                        prepared_row["prepared_path"] = (Path("prepared") / relative).as_posix()
                        prepared_row["prepared_width"] = args.width
                        prepared_row["prepared_height"] = args.height
                        prepared_row["alignment"] = {"method": "existing_file"}
                    else:
                        prepared_row = prepare_aligned_record(
                            archive,
                            row,
                            output_path=destination,
                            width=args.width,
                            height=args.height,
                        )
                        prepared_row["prepared_path"] = (Path("prepared") / relative).as_posix()
                    prepared.append(prepared_row)
                except Exception as exc:  # Keep the batch auditable instead of aborting it.
                    failures.append({"record_id": row.get("record_id"), "error": str(exc)})
                if processed % 250 == 0:
                    print(f"prepared {processed}/{len(rows)}")

    write_jsonl(output_dir / "prepared_manifest.jsonl", prepared)
    write_contact_sheet(prepared, output_dir / "qa_contact_sheet.jpg")
    errors = [row["alignment"].get("normalized_landmark_error") for row in prepared]
    errors = [float(value) for value in errors if value is not None]
    summary = {
        "requested": len(rows),
        "prepared": len(prepared),
        "failed": len(failures),
        "failures": failures[:50],
        "width": args.width,
        "height": args.height,
        "mean_normalized_landmark_error": round(sum(errors) / len(errors), 8) if errors else None,
        "age_band_counts": dict(
            sorted(Counter(age_band(int(row["photo_age"])) for row in prepared).items())
        ),
        "contact_sheet": str(output_dir / "qa_contact_sheet.jpg"),
        "privacy": "derived crops remain local and are excluded by .gitignore",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prepare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"prepared   {summary['prepared']}")
    print(f"failed     {summary['failed']}")
    print(f"manifest   {output_dir / 'prepared_manifest.jsonl'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
