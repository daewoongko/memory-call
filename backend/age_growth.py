"""Advisory growth prior and personal 3D structure residuals.

The current profile has no licensed, longitudinal Korean calibration cohort.
Consequently these outputs explain and guide generation but never auto-reject.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from math import sqrt
from pathlib import Path
from statistics import median


METRIC_DIRECTIONS = {
    "face_width_height": 1,
    "jaw_width_ratio": -1,
    "lower_face_ratio": -1,
    "midface_ratio": -1,
}


def growth_prior(
    parent_age: int,
    target_age: int,
    biological_sex: str = "unspecified",
    population_group: str = "unspecified",
) -> dict:
    if parent_age <= target_age:
        raise ValueError("parent_age must be older than target_age")
    if target_age >= 25:
        stage, weight = "younger_adult_subtle", 0.15
    elif target_age >= 20:
        stage, weight = "young_adult", 0.25
    elif target_age >= 15:
        stage, weight = "adolescent", 0.50
    elif target_age >= 11:
        stage, weight = "early_adolescent", 0.65
    else:
        stage, weight = "child", 0.80
    return {
        "profile": "general_backward_craniofacial_growth_direction_v1",
        "stage": stage,
        "parent_age": int(parent_age),
        "target_age": int(target_age),
        "guidance_weight": weight,
        "biological_sex": biological_sex,
        "population_group": population_group,
        "demographic_match_status": "requested_but_not_cohort_calibrated",
        "calibrated": False,
        "used_as_hard_gate": False,
        "expected_metric_directions": {
            name: "increase" if direction > 0 else "decrease"
            for name, direction in METRIC_DIRECTIONS.items()
        },
        "note": (
            "General population growth direction only. Magnitudes are not used "
            "until a consented longitudinal demographic cohort is calibrated."
        ),
    }


def personal_structure_profile(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("At least one real current-age 3D structure is required")
    coefficients = [row["shape_coefficients"] for row in rows]
    width = len(coefficients[0])
    if width == 0 or any(len(values) != width for values in coefficients):
        raise ValueError("Inconsistent 3DDFA shape coefficient dimensions")
    center = [median(values[index] for values in coefficients) for index in range(width)]
    deviations = [
        median(abs(values[index] - center[index]) for values in coefficients)
        for index in range(width)
    ]
    metric_names = sorted(rows[0]["pose_normalized_metrics"])
    metric_center = {
        name: round(
            median(row["pose_normalized_metrics"][name] for row in rows), 6
        )
        for name in metric_names
    }
    pair_rmse = []
    for left in range(len(coefficients)):
        for right in range(left + 1, len(coefficients)):
            pair_rmse.append(_rmse(coefficients[left], coefficients[right]))
    return {
        "status": "personal_current_age_residual",
        "reference_count": len(rows),
        "shape_dimensions": width,
        "shape_coefficient_median": [round(float(value), 6) for value in center],
        "shape_coefficient_mad": [round(float(value), 6) for value in deviations],
        "source_pair_rmse_median": round(median(pair_rmse), 6) if pair_rmse else 0.0,
        "source_pair_rmse_max": round(max(pair_rmse), 6) if pair_rmse else 0.0,
        "metric_median": metric_center,
        "calibrated_growth_curve": False,
    }


def _rmse(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        raise ValueError("Shape vectors must be non-empty and equal length")
    return sqrt(sum((a - b) ** 2 for a, b in zip(first, second)) / len(first))


def assess_3d_structure(
    profile: dict,
    parent: dict,
    candidate: dict,
    prior: dict,
) -> dict:
    personal_center = profile["shape_coefficient_median"]
    candidate_coeff = candidate["shape_coefficients"]
    parent_coeff = parent["shape_coefficients"]
    source_limit = max(0.25, float(profile.get("source_pair_rmse_max", 0.0)) * 1.5)
    personal_rmse = _rmse(candidate_coeff, personal_center)
    parent_rmse = _rmse(candidate_coeff, parent_coeff)
    direction_rows = []
    scores = []
    for name, direction in METRIC_DIRECTIONS.items():
        delta = float(candidate["pose_normalized_metrics"][name]) - float(
            parent["pose_normalized_metrics"][name]
        )
        tolerance = 0.003
        directed = delta * direction
        if directed > tolerance:
            status, score = "expected", 1.0
        elif directed < -tolerance:
            status, score = "opposite", 0.0
        else:
            status, score = "stable", 0.5
        scores.append(score)
        direction_rows.append(
            {
                "metric": name,
                "parent": parent["pose_normalized_metrics"][name],
                "candidate": candidate["pose_normalized_metrics"][name],
                "delta": round(delta, 6),
                "expected_direction": prior["expected_metric_directions"][name],
                "status": status,
            }
        )
    pose = candidate.get("pose_degrees") or {}
    pose_reliable = all(abs(float(pose.get(name, 0.0))) <= 25 for name in ("yaw", "pitch", "roll"))
    return {
        "status": "advisory_only",
        "used_as_hard_gate": False,
        "personal_shape_rmse": round(personal_rmse, 6),
        "parent_shape_rmse": round(parent_rmse, 6),
        "personal_preservation_reference_limit": round(source_limit, 6),
        "personal_structure_stable": personal_rmse <= source_limit,
        "growth_direction_score": round(sum(scores) / len(scores), 4),
        "growth_direction_measurements": direction_rows,
        "pose_reliable": pose_reliable,
        "pose_degrees": pose,
        "prior_profile": prior["profile"],
        "calibrated": False,
        "note": (
            "Pose-normalized 3D shape is a preservation and direction signal, "
            "not a biological age certificate or automatic rejection gate."
        ),
    }


def _read_git_revision(repo: Path) -> str:
    try:
        head = (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        return (repo / ".git" / head.removeprefix("ref: ")).read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return "unknown"


def run_3ddfa(
    root: Path,
    entries: list[dict],
    debug_dir: Path,
    target_age: int,
    *,
    timeout_seconds: int = 900,
) -> dict:
    repo = Path(
        os.getenv("THREEDDFA_REPO", str(Path.home() / "Models" / "3DDFA_V2"))
    ).expanduser()
    runner = root / "tools" / "age_estimate_3ddfa.py"
    missing = [
        name
        for name, path in (("repo", repo), ("runner", runner))
        if not path.exists()
    ]
    if missing:
        return {
            "status": "unavailable",
            "reason": "missing_runtime_components",
            "missing": missing,
        }
    debug_dir.mkdir(parents=True, exist_ok=True)
    request_path = debug_dir / f"age{target_age:02d}_3ddfa_request.json"
    output_path = debug_dir / f"age{target_age:02d}_3ddfa_output.json"
    request_path.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(runner),
        "--request",
        str(request_path),
        "--output",
        str(output_path),
        "--repo",
        str(repo),
        "--repo-revision",
        _read_git_revision(repo),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=True,
        )
        result = json.loads(output_path.read_text(encoding="utf-8"))
        result["request_path"] = str(request_path)
        result["output_path"] = str(output_path)
        if completed.stderr.strip():
            result["runner_stderr_tail"] = completed.stderr.strip()[-2000:]
        return result
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "unavailable",
            "reason": "runner_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "request_path": str(request_path),
            "output_path": str(output_path),
        }
