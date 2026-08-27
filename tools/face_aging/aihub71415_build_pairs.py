"""Build leakage-safe training pairs and exact-age holdout cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import build_pair_and_holdout_rows, read_jsonl, write_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-age", type=int, default=8)
    parser.add_argument("--max-sources-per-target", type=int, default=6)
    parser.add_argument("--split-salt", default="memory-call-aihub71415-v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    pairs, holdouts, summary = build_pair_and_holdout_rows(
        read_jsonl(args.manifest),
        target_age=args.target_age,
        max_sources_per_target=args.max_sources_per_target,
        salt=args.split_salt,
    )
    write_jsonl(output_dir / "train_pairs.jsonl", (row for row in pairs if row["split"] == "train"))
    write_jsonl(output_dir / "val_pairs.jsonl", (row for row in pairs if row["split"] == "val"))
    write_jsonl(output_dir / f"age{args.target_age}_holdouts.jsonl", holdouts)
    (output_dir / "split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"pairs      {summary['training_pairs']}")
    print(f"val pairs  {summary['validation_pairs']}")
    print(f"holdouts   {summary['holdout_cases']}")
    print(f"formal     {summary['formal_eval_cases']}")
    print(f"splits     {summary['split_subject_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
