"""Run the adaptive past-age pipeline with one command.

The default mode automates generation, validation, and failed-segment
refinement, then pauses when a fully passing candidate needs human review.
Use --auto-select only when unattended metric-based selection is acceptable.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import age_timeline  # noqa: E402
from age_feedback import base_edit_strength, generation_controls  # noqa: E402


FLUX_PYTHON = ROOT / ".venv-flux2" / "Scripts" / "python.exe"
GENERATOR = ROOT / "tools" / "face_aging" / "age_generate_flux2.py"
VALIDATOR = ROOT / "tools" / "face_aging" / "age_validate_flux2.py"
CANDIDATE_DIR = ROOT / "data" / "faces" / "age_candidates"
DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help=(
            "Override the adaptive initial batch size. By default adult "
            "transitions ending at age 26 or older generate six photographs; "
            "age 20 and younger generate four."
        ),
    )
    parser.add_argument(
        "--max-generated-per-segment",
        type=int,
        default=8,
        help="Hard latency/cost budget for one age transition.",
    )
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--reference-count", type=int, default=5)
    parser.add_argument("--lora-scale", type=float, default=0.8)
    parser.add_argument("--lora-path", type=Path, default=None)
    parser.add_argument("--seed-base", type=int, default=20260900)
    parser.add_argument(
        "--attempts-per-segment",
        type=int,
        default=2,
        help=(
            "Generate an initial batch and at most one replacement batch "
            "before splitting a failed segment."
        ),
    )
    parser.add_argument("--max-refinements", type=int, default=4)
    parser.add_argument(
        "--auto-select",
        action="store_true",
        help="Select the highest-scoring full-pass candidate without review.",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Continue through every age. Requires --auto-select.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore matching prior validation feedback and start at attempt 1.",
    )
    return parser.parse_args()


def find_lora(explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    candidates = list(
        (ROOT / "data" / "faces" / "lora_runs").glob(
            "*/pytorch_lora_weights.safetensors"
        )
    )
    if not candidates:
        raise FileNotFoundError(
            "No identity LoRA found. Pass --lora-path explicitly."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def selected_by_age(plan: dict) -> dict[int, str]:
    return {
        int(stage["age"]): str(stage["selected"])
        for stage in plan.get("stages", [])
        if stage.get("kind") == "generated" and stage.get("selected")
    }


def next_stage(plan: dict) -> tuple[int, int] | None:
    path = [int(age) for age in plan.get("generation_path", [])]
    selected = selected_by_age(plan)
    if len(path) < 2:
        return None
    for index in range(1, len(path)):
        target_age = path[index]
        if target_age not in selected:
            parent_age = path[index - 1]
            if index > 1 and parent_age not in selected:
                raise RuntimeError(
                    f"Age {parent_age} must be selected before age {target_age}."
                )
            return parent_age, target_age
    return None


def run_checked(command: list[str]) -> None:
    print("\n> " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def validation_rows(target_age: int, new_names: set[str]) -> list[dict]:
    summary_path = DEBUG_DIR / f"age{target_age:02d}_flux2_validation.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return [
        row
        for row in summary.get("rows", [])
        if Path(row["path"]).name in new_names
    ]


def matching_previous_rows(plan: dict, parent_age: int, target_age: int) -> list[dict]:
    summary_path = DEBUG_DIR / f"age{target_age:02d}_flux2_validation.json"
    if not summary_path.is_file():
        return []
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if int(summary.get("parent_age", -1)) != parent_age:
        return []
    current_age = int(plan.get("current_age", -1))
    if parent_age == current_age:
        expected_parent = Path(str(plan.get("current_photo", ""))).name
    else:
        expected_parent = Path(str(selected_by_age(plan).get(parent_age, ""))).name
    actual_parent = Path(str(summary.get("parent_photo", ""))).name
    if not expected_parent or actual_parent != expected_parent:
        return []
    return [row for row in summary.get("rows") or [] if isinstance(row, dict)]


def next_free_seed(target_age: int, seed: int, count: int) -> int:
    candidate = int(seed)
    while any(
        any(
            CANDIDATE_DIR.glob(
                f"age{target_age:02d}_flux2_seed{candidate + offset}_*.png"
            )
        )
        for offset in range(count)
    ):
        candidate += count
    return candidate


def inferred_completed_attempts(
    rows: list[dict], parent_age: int, target_age: int
) -> int:
    """Recover attempt count from the strength embedded in candidate filenames."""
    base = base_edit_strength(parent_age, target_age)
    maximum = base
    for row in rows:
        name = Path(str(row.get("path", ""))).name
        match = re.search(r"_maskstr(\d+)p(\d+)", name)
        if match:
            maximum = max(maximum, float(f"{match.group(1)}.{match.group(2)}"))
    if maximum >= base + 0.21:
        return 4
    if maximum >= base + 0.13:
        return 3
    if maximum >= base + 0.07:
        return 2
    return 1


def candidate_rank(row: dict, target_age: int) -> tuple:
    age_estimation = row.get("age_estimation") or {}
    mivolo = row.get("mivolo_age_estimation") or {}
    review_status = row.get("review_status", "strong_pass")
    structure = row.get("structure_assessment") or {}
    structure_3d = row.get("structure_3d_assessment") or {}
    return (
        1 if review_status == "strong_pass" else 0,
        float(age_estimation.get("target_range_vote_share", 1.0)),
        float(mivolo.get("target_range_vote_share", 1.0)),
        -abs(int(row["estimated_age"]) - target_age),
        float(row["parent_similarity"]),
        1 if structure_3d.get("personal_structure_stable") else 0,
        float(structure_3d.get("growth_direction_score", 0.0)),
        float(structure.get("score", 0.0)),
        float(row["similarity_mean"]),
        float(row["primary_similarity"]),
    )


def main() -> None:
    args = parse_args()
    if args.run_all and not args.auto_select:
        raise ValueError("--run-all requires --auto-select")
    if args.count is not None and args.count < 1:
        raise ValueError("--count must be at least 1")
    if args.max_generated_per_segment < 4:
        raise ValueError("--max-generated-per-segment must be at least 4")
    if (
        args.count is not None
        and args.count > args.max_generated_per_segment
    ):
        raise ValueError("--count cannot exceed --max-generated-per-segment")
    if args.attempts_per_segment < 1:
        raise ValueError("--attempts-per-segment must be at least 1")
    if not FLUX_PYTHON.is_file():
        raise FileNotFoundError(FLUX_PYTHON)

    lora_path = find_lora(args.lora_path)
    refinements = 0
    attempts: dict[tuple[int, int], int] = {}
    previous_rows: dict[tuple[int, int], list[dict]] = {}

    while True:
        plan = age_timeline.get_plan()
        if not plan.get("configured"):
            raise RuntimeError("Save the current age and representative photo first.")
        stage = next_stage(plan)
        if stage is None:
            print("\nAll planned age anchors are selected.", flush=True)
            return
        parent_age, target_age = stage
        stage_key = (parent_age, target_age)
        if stage_key not in attempts and not args.fresh:
            historical_rows = matching_previous_rows(
                plan, parent_age, target_age
            )
            historical_passing = [
                row for row in historical_rows if row.get("full_pass")
            ]
            historical_passing.sort(
                key=lambda row: candidate_rank(row, target_age), reverse=True
            )
            if len(historical_passing) >= 4:
                print(
                    f"\nExisting full-pass candidates for age {target_age}:",
                    flush=True,
                )
                for row in historical_passing:
                    print(f"- {Path(row['path']).name}", flush=True)
                if not args.auto_select:
                    print(
                        "Review and select one in the guardian screen; no new "
                        "candidate was generated.",
                        flush=True,
                    )
                    return
                winner_name = Path(historical_passing[0]["path"]).name
                age_timeline.select_candidate(target_age, winner_name)
                print(f"Auto-selected existing candidate: {winner_name}", flush=True)
                if not args.run_all:
                    return
                continue
            if historical_rows:
                previous_rows[stage_key] = historical_rows
                attempts[stage_key] = inferred_completed_attempts(
                    historical_rows, parent_age, target_age
                )
                print(
                    f"\nResuming {parent_age}->{target_age} from "
                    f"{len(historical_rows)} matching validated candidates "
                    f"after attempt {attempts[stage_key]}.",
                    flush=True,
                )
                if attempts[stage_key] >= args.attempts_per_segment:
                    if historical_passing:
                        print(
                            f"Replacement budget ended with {len(historical_passing)} "
                            "validated photographs. Review those photographs rather "
                            "than exposing failed candidates.",
                            flush=True,
                        )
                        if args.auto_select:
                            winner_name = Path(historical_passing[0]["path"]).name
                            age_timeline.select_candidate(target_age, winner_name)
                            print(f"Auto-selected best available: {winner_name}", flush=True)
                        return
                    if args.dry_run:
                        if parent_age - target_age >= 3:
                            message = (
                                "Retry budget is exhausted; the next real run will "
                                "split this failed segment with an intermediate age."
                            )
                        else:
                            message = (
                                "Retry budget is exhausted and this stage is too "
                                "narrow to split; automation will pause for human "
                                "review or recipe adjustment."
                            )
                        print(message, flush=True)
                        return
                    if refinements >= args.max_refinements:
                        raise RuntimeError("Maximum automatic refinements reached.")
                    try:
                        refined = age_timeline.refine_failed_segment(
                            parent_age, target_age
                        )
                    except ValueError as exc:
                        print(
                            f"Stage {parent_age}->{target_age} has no full pass "
                            "and is too narrow to split reliably. Automation "
                            f"paused for human review or recipe adjustment: {exc}",
                            flush=True,
                        )
                        return
                    refinements += 1
                    print(
                        "Recovered an exhausted failed stage. Added midpoint age "
                        f"{refined['inserted_age']} and retrying.",
                        flush=True,
                    )
                    continue
        stage_attempt = attempts.get(stage_key, 0) + 1
        controls = generation_controls(
            parent_age=parent_age,
            target_age=target_age,
            attempt=stage_attempt,
            previous_rows=previous_rows.get(stage_key),
            base_lora_scale=args.lora_scale,
            base_reference_count=args.reference_count,
        )
        print(
            f"\nNext stage: {parent_age} -> {target_age} | "
            f"attempt {stage_attempt}/{args.attempts_per_segment} | "
            f"LoRA: {lora_path.parent.name}/{lora_path.name}",
            flush=True,
        )
        print(
            "Generation controls: "
            f"target {target_age} | control {controls['control_age']} | "
            f"strength {controls['edit_strength']:.2f} | "
            f"LoRA {controls['lora_scale']:.2f} | "
            f"refs {controls['reference_count']} | {controls['reason']}",
            flush=True,
        )
        if args.dry_run:
            if stage_attempt == 1:
                simulated_old = [
                    {"estimated_age": target_age + 3, "identity_pass": True}
                ]
                for retry_attempt in (2, 3, 4):
                    fallback = generation_controls(
                        parent_age=parent_age,
                        target_age=target_age,
                        attempt=retry_attempt,
                        previous_rows=simulated_old,
                        base_lora_scale=args.lora_scale,
                        base_reference_count=args.reference_count,
                    )
                    print(
                        f"Older-result fallback {retry_attempt - 1}: "
                        f"control {fallback['control_age']} | "
                        f"strength {fallback['edit_strength']:.2f} | "
                        f"LoRA {fallback['lora_scale']:.2f} | "
                        f"refs {fallback['reference_count']}",
                        flush=True,
                    )
            elif stage_attempt < args.attempts_per_segment:
                fallback = generation_controls(
                    parent_age=parent_age,
                    target_age=target_age,
                    attempt=stage_attempt + 1,
                    previous_rows=previous_rows.get(stage_key),
                    base_lora_scale=args.lora_scale,
                    base_reference_count=args.reference_count,
                )
                print(
                    f"If still too old, next fallback: control "
                    f"{fallback['control_age']} | strength "
                    f"{fallback['edit_strength']:.2f} | LoRA "
                    f"{fallback['lora_scale']:.2f} | refs "
                    f"{fallback['reference_count']}",
                    flush=True,
                )
            return

        before = {
            path.name
            for path in CANDIDATE_DIR.glob(f"age{target_age:02d}_flux2*.png")
        }
        existing_rows = previous_rows.get(stage_key) or []
        already_generated = len(existing_rows)
        passed_count = sum(bool(row.get("full_pass")) for row in existing_rows)
        initial_count = args.count if args.count is not None else (
            6 if target_age >= 26 else 4
        )
        generation_count = min(
            initial_count if stage_attempt == 1 else max(1, 4 - passed_count),
            args.max_generated_per_segment - already_generated,
        )
        if generation_count <= 0:
            print("Candidate budget exhausted for this age transition.", flush=True)
            return
        requested_seed = (
            args.seed_base
            + target_age * 100
            + refinements * 10000
            + already_generated
        )
        seed = next_free_seed(target_age, requested_seed, generation_count)
        if seed != requested_seed:
            print(
                f"Seed range {requested_seed}..{requested_seed + generation_count - 1} "
                f"already exists; using {seed}..{seed + generation_count - 1}.",
                flush=True,
            )
        run_checked(
            [
                str(FLUX_PYTHON),
                str(GENERATOR),
                "--age",
                str(target_age),
                "--control-age",
                str(controls["control_age"]),
                "--reference-count",
                str(controls["reference_count"]),
                "--count",
                str(generation_count),
                "--seed",
                str(seed),
                "--steps",
                str(args.steps),
                "--edit-strength",
                str(controls["edit_strength"]),
                "--lora-path",
                str(lora_path),
                "--lora-scale",
                str(controls["lora_scale"]),
            ]
        )
        after = {
            path.name
            for path in CANDIDATE_DIR.glob(f"age{target_age:02d}_flux2*.png")
        }
        new_names = after - before
        if not new_names:
            raise RuntimeError("Generator did not create a new candidate file.")

        run_checked([sys.executable, str(VALIDATOR), "--age", str(target_age)])
        rows = validation_rows(target_age, new_names)
        accumulated_rows = [*existing_rows, *rows]
        previous_rows[stage_key] = accumulated_rows
        passing = [row for row in accumulated_rows if row.get("full_pass")]
        if len(passing) >= 4:
            passing.sort(key=lambda row: candidate_rank(row, target_age), reverse=True)
            passing = passing[:4]
            print(f"\nFull-pass candidates for age {target_age}:", flush=True)
            for row in passing:
                print(
                    f"- {Path(row['path']).name} | age {row['estimated_age']} | "
                    f"review {row.get('review_status', 'legacy')} | "
                    f"parent {row['parent_similarity']:.4f} | "
                    f"current mean {row['similarity_mean']:.4f}",
                    flush=True,
                )
            if not args.auto_select:
                print(
                    "Review these images and select one in the guardian screen. "
                    "Then run this command again for the next stage.",
                    flush=True,
                )
                return

            winner = passing[0]
            winner_name = Path(winner["path"]).name
            age_timeline.select_candidate(target_age, winner_name)
            print(f"Auto-selected: {winner_name}", flush=True)
            if not args.run_all:
                return
            continue

        attempts[stage_key] = stage_attempt
        if (
            stage_attempt < args.attempts_per_segment
            and len(accumulated_rows) < args.max_generated_per_segment
        ):
            print(
                f"Only {len(passing)}/4 reviewable photographs passed. "
                "Generating replacements from validation feedback.",
                flush=True,
            )
            continue

        if passing:
            passing.sort(key=lambda row: candidate_rank(row, target_age), reverse=True)
            print(
                f"Replacement budget ended with {len(passing)} validated "
                "photographs; failed outputs remain hidden.",
                flush=True,
            )
            if not args.auto_select:
                return
            winner_name = Path(passing[0]["path"]).name
            age_timeline.select_candidate(target_age, winner_name)
            print(f"Auto-selected best available: {winner_name}", flush=True)
            if not args.run_all:
                return
            continue

        if refinements >= args.max_refinements:
            raise RuntimeError("Maximum automatic refinements reached.")
        try:
            refined = age_timeline.refine_failed_segment(parent_age, target_age)
        except ValueError as exc:
            print(
                f"Stage {parent_age}->{target_age} has no full pass and is too "
                "narrow to split reliably. Automation paused for human review "
                f"or recipe adjustment: {exc}",
                flush=True,
            )
            return
        refinements += 1
        print(
            f"No full pass. Added midpoint age {refined['inserted_age']} and retrying.",
            flush=True,
        )


if __name__ == "__main__":
    main()
