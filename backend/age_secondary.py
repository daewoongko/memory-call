"""Independent secondary age-estimator orchestration and consensus policy."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Iterable


MIN_TARGET_SHARE = 0.60
MIVOLO_REPORTED_MAE_YEARS = 4.29


def summarize_continuous_age_estimates(
    estimates: Iterable[float],
    age_limits: dict[str, int],
    *,
    reported_mae_years: float = MIVOLO_REPORTED_MAE_YEARS,
) -> dict:
    """Summarize MiVOLO TTA outputs without calling them a confidence interval."""
    values = sorted(float(value) for value in estimates)
    if not values:
        raise ValueError("At least one secondary age estimate is required")
    low, high = int(age_limits["min"]), int(age_limits["max"])
    center = float(median(values))
    target_share = sum(low <= value <= high for value in values) / len(values)
    range_pass = low <= center <= high and target_share >= MIN_TARGET_SHARE
    rounded_bins = Counter(int(round(value)) for value in values)
    boundary = abs(center - low) <= 0.25 or abs(center - high) <= 0.25
    interval_outside = values[0] < low or values[-1] > high
    review_status = (
        "fail"
        if not range_pass
        else "borderline"
        if boundary or interval_outside or target_share < 0.80
        else "strong_pass"
    )
    support_low = center - float(reported_mae_years)
    support_high = center + float(reported_mae_years)
    return {
        "estimates": [round(value, 2) for value in values],
        "rounded_distribution": {
            str(age): round(count / len(values), 4)
            for age, count in sorted(rounded_bins.items())
        },
        "mean": round(mean(values), 2),
        "median": round(center, 2),
        "standard_deviation": round(pstdev(values), 2),
        "stability_interval": {
            "min": round(values[0], 2),
            "max": round(values[-1], 2),
        },
        "target_range_vote_share": round(target_share, 4),
        "range_pass": range_pass,
        "review_status": review_status,
        "reported_mae_years": round(float(reported_mae_years), 2),
        "mae_support_interval": {
            "min": round(support_low, 2),
            "max": round(support_high, 2),
        },
        "mae_interval_overlaps_target": support_high >= low and support_low <= high,
        "uncertainty_kind": "test_time_view_stability_not_calibrated_confidence",
    }


def summarize_mivolo_row(
    row: dict | None,
    age_limits: dict[str, int],
) -> dict | None:
    """Summarize raw MiVOLO outputs used by the independent hard gate."""
    if not row:
        return None
    raw_estimates = [float(value) for value in row.get("estimates") or []]
    if not raw_estimates:
        return None
    summary = summarize_continuous_age_estimates(raw_estimates, age_limits)
    summary.update(
        {
            "status": "available",
            "age_basis": "raw_model_output",
            "personal_bias_applied": False,
            "used_as_hard_gate": True,
        }
    )
    return summary


def summarize_person_offset_advisory(
    row: dict | None,
    calibration: dict | None,
    age_limits: dict[str, int],
) -> dict | None:
    """Show a current-age person offset without extrapolating it as a gate."""
    if not row or calibration is None:
        return None
    raw_estimates = [float(value) for value in row.get("estimates") or []]
    if not raw_estimates:
        return None
    bias_years = float(calibration.get("bias_years", 0.0))
    corrected = [round(value - bias_years, 2) for value in raw_estimates]
    summary = summarize_continuous_age_estimates(corrected, age_limits)
    summary.update(
        {
            "status": "advisory_only",
            "age_basis": "current_age_person_offset_extrapolation",
            "raw_estimates": [round(value, 2) for value in raw_estimates],
            "personal_bias_years": round(bias_years, 2),
            "personal_bias_applied": True,
            "used_as_hard_gate": False,
            "note": (
                "The offset was measured only from current-age portraits and is "
                "not validated as a lifespan calibration."
            ),
        }
    )
    return summary


def combine_age_evidence(
    primary: dict,
    secondary: dict | None,
    relative_evidence: dict,
) -> dict:
    """Require model agreement for auto-pass; disagreements go to a person."""
    primary_pass = bool(primary.get("range_pass"))
    if not secondary or secondary.get("status") == "unavailable":
        return {
            "primary_pass": primary_pass,
            "secondary_available": False,
            "secondary_pass": None,
            "model_agreement": None,
            "automated_pass": primary_pass,
            "review_status": primary.get("review_status", "fail"),
            "reason": "secondary_model_unavailable_primary_only_degraded_mode",
            "policy": "both_models_when_secondary_available",
        }

    secondary_pass = bool(secondary.get("range_pass"))
    agreement = primary_pass == secondary_pass
    if primary_pass and secondary_pass:
        review_status = (
            "strong_pass"
            if primary.get("review_status") == "strong_pass"
            and secondary.get("review_status") == "strong_pass"
            else "borderline"
        )
        reason = "both_independent_age_models_support_target"
        automated_pass = True
    elif primary_pass or secondary_pass:
        review_status = "human_review"
        reason = (
            "age_models_disagree_but_measured_deaging_exists"
            if relative_evidence.get("younger_direction")
            else "age_models_disagree_without_measured_deaging"
        )
        automated_pass = False
    else:
        review_status = "fail"
        reason = "both_independent_age_models_reject_target"
        automated_pass = False
    return {
        "primary_pass": primary_pass,
        "secondary_available": True,
        "secondary_pass": secondary_pass,
        "model_agreement": agreement,
        "automated_pass": automated_pass,
        "review_status": review_status,
        "reason": reason,
        "policy": "both_models_when_secondary_available",
    }


def _read_git_revision(repo: Path) -> str:
    head_path = repo / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head.removeprefix("ref: ")
        return (repo / ".git" / ref).read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def mivolo_runtime(root: Path) -> dict[str, Path | str]:
    python_default = root / ".venv-mivolo" / "Scripts" / "python.exe"
    repo_default = Path.home() / "Models" / "MiVOLO"
    repo = Path(os.getenv("MIVOLO_REPO", str(repo_default))).expanduser()
    checkpoint = Path(
        os.getenv(
            "MIVOLO_CHECKPOINT",
            str(repo / "models" / "volo_d1_age_only.pth.tar"),
        )
    ).expanduser()
    return {
        "python": Path(os.getenv("MIVOLO_PYTHON", str(python_default))).expanduser(),
        "repo": repo,
        "checkpoint": checkpoint,
        "runner": root / "tools" / "age_estimate_mivolo.py",
        "repo_revision": _read_git_revision(repo),
    }


def run_mivolo(
    root: Path,
    entries: list[dict],
    debug_dir: Path,
    target_age: int,
    *,
    timeout_seconds: int = 900,
) -> dict:
    """Run MiVOLO out of process so its pinned torch stack stays isolated."""
    runtime = mivolo_runtime(root)
    missing = [
        name
        for name in ("python", "repo", "checkpoint", "runner")
        if not Path(runtime[name]).exists()
    ]
    if missing:
        return {
            "status": "unavailable",
            "reason": "missing_runtime_components",
            "missing": missing,
        }
    if not entries:
        return {"status": "unavailable", "reason": "no_face_entries"}

    debug_dir.mkdir(parents=True, exist_ok=True)
    request_path = debug_dir / f"age{target_age:02d}_mivolo_request.json"
    output_path = debug_dir / f"age{target_age:02d}_mivolo_output.json"
    request_path.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command = [
        str(runtime["python"]),
        str(runtime["runner"]),
        "--request",
        str(request_path),
        "--output",
        str(output_path),
        "--checkpoint",
        str(runtime["checkpoint"]),
        "--repo",
        str(runtime["repo"]),
        "--repo-revision",
        str(runtime["repo_revision"]),
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
