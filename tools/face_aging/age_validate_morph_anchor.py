"""Convert detailed past-age validation into morph-keyframe review evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from age_morph_policy import morph_anchor_assessment  # noqa: E402


DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, required=True)
    parser.add_argument(
        "--name-contains",
        default="",
        help=(
            "Only assess candidate names containing this text. "
            "The default empty value assesses every validated recipe."
        ),
    )
    return parser.parse_args()


def rank(row: dict) -> tuple:
    assessment = row["morph_anchor_assessment"]
    trajectory = assessment["trajectory_hard_gate"]
    structure = assessment["growth_structure_evidence"]
    return (
        1 if assessment["eligible_for_human_review"] else 0,
        float(row.get("parent_similarity", 0.0)),
        float(row.get("similarity_mean", 0.0)),
        float(trajectory.get("mean_years_younger") or -99.0),
        float(structure.get("growth_direction_score") or 0.0),
    )


def main() -> None:
    args = parse_args()
    source_path = DEBUG_DIR / f"age{args.age:02d}_flux2_validation.json"
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    parent_age = int(source["parent_age"])
    rows = []
    for original in source.get("rows") or []:
        name = Path(str(original.get("path", ""))).name
        if args.name_contains and args.name_contains not in name:
            continue
        row = dict(original)
        row["morph_anchor_assessment"] = morph_anchor_assessment(
            row, parent_age, args.age
        )
        rows.append(row)
    if not rows:
        raise RuntimeError(
            f"No age-{args.age} candidates matched {args.name_contains!r}"
        )
    rows.sort(key=rank, reverse=True)
    eligible = [
        row
        for row in rows
        if row["morph_anchor_assessment"]["eligible_for_human_review"]
    ]
    payload = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_age_label": args.age,
        "parent_age_label": parent_age,
        "source_validation": str(source_path),
        "candidate_filter": args.name_contains,
        "policy": {
            "hard_gates": [
                "identity preservation",
                "relative younger trajectory",
                "morph-compatible face detection and pose",
                "visible child craniofacial direction for age 15 and below",
            ],
            "advisory": [
                "exact apparent-age estimates",
                "uncalibrated demographic growth magnitudes",
                "3D growth-direction score",
            ],
            "human_review_required": True,
        },
        "eligible_count": len(eligible),
        "rows": rows,
    }
    output_path = DEBUG_DIR / f"age{args.age:02d}_morph_validation.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nMorph-keyframe validation complete")
    print(f"Eligible for guardian review: {len(eligible)}/{len(rows)}")
    for row in rows:
        assessment = row["morph_anchor_assessment"]
        trajectory = assessment["trajectory_hard_gate"]
        visible_structure = assessment["visible_child_structure_hard_gate"]
        structure_score = visible_structure.get("growth_direction_score")
        structure_text = (
            f"{structure_score:.0%}"
            if isinstance(structure_score, (int, float))
            else "N/A"
        )
        print(
            f"- {Path(row['path']).name} | {assessment['status']} | "
            f"identity {'PASS' if assessment['identity_hard_gate'] else 'FAIL'} | "
            f"relative {trajectory['mean_years_younger']}y younger | "
            f"visible structure {structure_text} "
            f"{'PASS' if visible_structure['pass'] else 'FAIL'} | "
            "advisory exact-age evidence "
            f"{assessment['exact_age_evidence']['status']}"
        )
    print(f"Summary: {output_path}")


if __name__ == "__main__":
    main()
