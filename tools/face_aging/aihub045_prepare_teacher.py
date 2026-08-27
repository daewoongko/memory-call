"""Create a bounded private face-crop cache for AI Hub 045 identity training."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub045 import read_jsonl, write_jsonl  # noqa: E402


def _spread(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    indexes = {round(i * (len(rows) - 1) / (limit - 1)) for i in range(limit)}
    return [rows[index] for index in sorted(indexes)]


def _align(image: np.ndarray, row: dict, size: int) -> np.ndarray:
    points = np.asarray(row["landmarks"], dtype=np.float32)
    canonical = np.asarray(
        [[0.50 * size, 0.56 * size], [0.32 * size, 0.38 * size], [0.68 * size, 0.38 * size], [0.38 * size, 0.69 * size], [0.62 * size, 0.69 * size]],
        dtype=np.float32,
    )
    matrix, _ = cv2.estimateAffinePartial2D(points, canonical, method=cv2.LMEDS)
    if matrix is None:
        raise ValueError("face alignment failed")
    return cv2.warpAffine(image, matrix, (size, size), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101)


def _prepare_archive(job: tuple[str, list[dict], str, int, int]) -> dict:
    archive_path, rows, output_dir, size, quality = job
    written = skipped = failed = 0
    errors = []
    with ZipFile(archive_path) as archive:
        for row in rows:
            output = Path(output_dir) / f"{row['record_id']}.jpg"
            if output.is_file() and output.stat().st_size > 500:
                skipped += 1
                continue
            try:
                encoded = np.frombuffer(archive.read(row["image_member"]), dtype=np.uint8)
                image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("image decode failed")
                crop = _align(image, row, size)
                ok, result = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if not ok:
                    raise ValueError("JPEG encode failed")
                result.tofile(output)
                written += 1
            except Exception as exc:
                failed += 1
                errors.append({"record_id": row["record_id"], "error": str(exc)})
    return {"written": written, "skipped": skipped, "failed": failed, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/experiments/aihub045_full/index/manifest.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/experiments/aihub045_full/teacher_crops_224")
    parser.add_argument("--selection", type=Path, default=ROOT / "data/experiments/aihub045_full/index/teacher_selection.jsonl")
    parser.add_argument("--max-per-identity", type=int, default=30)
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    by_identity: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(args.manifest):
        by_identity[row["identity_id"]].append(row)
    selected = []
    for rows in by_identity.values():
        selected.extend(_spread(rows, args.max_per_identity))
    selected.sort(key=lambda row: (row["image_archive_path"], row["file_id"], row["identity_id"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.selection, selected)
    by_archive: dict[str, list[dict]] = defaultdict(list)
    for row in selected:
        by_archive[row["image_archive_path"]].append(row)
    totals = {"written": 0, "skipped": 0, "failed": 0, "errors": []}
    jobs = [(archive, rows, str(args.output_dir), args.size, args.quality) for archive, rows in by_archive.items()]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_prepare_archive, job) for job in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            for key in ("written", "skipped", "failed"):
                totals[key] += result[key]
            totals["errors"].extend(result["errors"])
            if index % 10 == 0:
                print(json.dumps({"archives": index, **{k: totals[k] for k in ("written", "failed")}}), flush=True)
    report = {"selected": len(selected), "identities": len(by_identity), **totals}
    (args.output_dir / "prepare_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
