"""Index AI Hub 045 without extracting or publishing licensed family photos."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from aihub045 import index_dataset, write_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/experiments/aihub045_full/index",
    )
    args = parser.parse_args()
    rows, report = index_dataset(args.dataset_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "manifest.jsonl", rows)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
