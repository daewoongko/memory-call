"""Prepare private 224px aligned crops for training-only face judges.

The output directory is ignored by Git.  Source or derived licensed faces must
never be copied into frontend/public, data/faces, or a tracked directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from zipfile import ZipFile

import cv2


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import align_record_image, read_jsonl  # noqa: E402


def _prepare_shard(job: tuple[str, list[dict], str, int, int]) -> dict:
    archive_path, rows, output_dir, size, quality = job
    output_root = Path(output_dir)
    written = skipped = failed = 0
    errors: list[dict] = []
    with ZipFile(archive_path) as archive:
        for row in rows:
            output = output_root / f"{row['record_id']}.jpg"
            if output.is_file() and output.stat().st_size > 500:
                skipped += 1
                continue
            try:
                image, _ = align_record_image(
                    archive, row, width=size, height=size
                )
                ok, encoded = cv2.imencode(
                    ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality]
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                encoded.tofile(output)
                written += 1
            except Exception as exc:
                failed += 1
                errors.append({"record_id": row["record_id"], "error": str(exc)})
    return {
        "records": len(rows),
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/experiments/aihub71415_full/index/manifest.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/experiments/aihub71415_full/teacher_crops_224",
    )
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = list(read_jsonl(args.manifest))
    if args.limit:
        rows = rows[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = failed = 0
    errors: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row["image_archive_path"])].append(row)
    jobs = [
        (archive, group, str(args.output_dir), args.size, args.quality)
        for archive, group in groups.items()
    ]
    completed_records = 0
    with ProcessPoolExecutor(max_workers=max(args.workers, 1)) as executor:
        futures = [executor.submit(_prepare_shard, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            completed_records += result["records"]
            written += result["written"]
            skipped += result["skipped"]
            failed += result["failed"]
            errors.extend(result["errors"])
            if completed_records % 1000 < result["records"]:
                print(
                    json.dumps(
                        {"seen": completed_records, "written": written, "failed": failed}
                    ),
                    flush=True,
                )
    report = {
        "manifest": str(args.manifest),
        "output_dir": str(args.output_dir),
        "size": args.size,
        "records": len(rows),
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:50],
    }
    (args.output_dir / "prepare_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
