"""Audit exact-age-8 evaluation inputs before any model comparison is run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import read_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main(args: argparse.Namespace) -> int:
    cases = list(read_jsonl(args.holdouts))
    violations: list[str] = []
    for case in cases:
        excluded = set(case["excluded_target_record_ids"])
        for mode in ("adult_only_sources", "available_anchor_sources"):
            for source in case[mode]:
                if source["record_id"] in excluded or int(source["photo_age"]) == int(case["target_age"]):
                    violations.append(f"{case['case_id']} leaks target via {mode}")
        if any(int(source["photo_age"]) < 18 for source in case["adult_only_sources"]):
            violations.append(f"{case['case_id']} adult-only source is younger than 18")

    report = {
        "status": "ready" if cases and not violations else "blocked",
        "cases": len(cases),
        "formal_eval_cases": sum(bool(case.get("formal_eval")) for case in cases),
        "adult_only_cases": sum(bool(case["adult_only_sources"]) for case in cases),
        "available_anchor_cases": sum(bool(case["available_anchor_sources"]) for case in cases),
        "violations": violations,
        "next_outputs": [
            "current_pipeline_prediction",
            "aihub_prior_prediction",
            "hidden_true_age_8_reference",
        ],
        "required_comparison": [
            "identity_embedding_similarity",
            "target_age_absolute_error",
            "five_landmark_structure_error",
            "face_detection_failure_rate",
            "blind_human_preference",
        ],
        "warning": "This command audits the holdout. It does not invent similarity scores before predictions exist.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args))
