"""Policy for evaluating generated portraits as morph keyframes.

Exact apparent-age estimates are evidence only.  A keyframe must preserve
identity, remain morph-compatible with the accepted parent, and move in a
younger direction across the sequence.  Human review remains mandatory.
"""

from __future__ import annotations

from statistics import mean


MAX_ALLOWED_REVERSAL_YEARS = 1.0
MIN_FACE_DETECTION_SCORE = 0.75
MAX_ABS_YAW_DEGREES = 10.0
MAX_ABS_PITCH_DEGREES = 12.0
MAX_ABS_ROLL_DEGREES = 8.0
MIN_RELATIVE_PROGRESS_YEARS = 0.25
MIN_CHILD_STRUCTURE_DIRECTION_SCORE = 0.75


def _number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def trajectory_assessment(row: dict, parent_age: int, target_age: int) -> dict:
    """Screen relative direction without treating model age as ground truth.

    The estimators are too noisy to demand one measured year of progress for
    every chronological keyframe step.  They only reject a frozen/reversed
    direction here; biological structure and morph continuity remain a human
    review decision until the 3D growth prior is calibrated.
    """
    gap = max(1, int(parent_age) - int(target_age))
    signals: dict[str, float] = {}
    for name, key in (
        ("insightface", "relative_age_evidence"),
        ("mivolo_raw", "mivolo_relative_age_evidence"),
    ):
        evidence = row.get(key) or {}
        delta = _number(evidence.get("observed_delta_years"))
        if delta is not None:
            # Existing validation expresses candidate - parent.  Positive
            # progress therefore means the candidate measured younger.
            signals[name] = round(-delta, 3)

    required_progress = round(
        min(1.0, MIN_RELATIVE_PROGRESS_YEARS + max(0, gap - 3) * 0.1),
        3,
    )
    values = list(signals.values())
    average_progress = mean(values) if values else None
    no_large_reversal = bool(values) and all(
        value >= -MAX_ALLOWED_REVERSAL_YEARS for value in values
    )
    enough_progress = (
        average_progress is not None and average_progress >= required_progress
    )
    passed = bool(values) and no_large_reversal and enough_progress

    if passed:
        status = "younger_trajectory"
    elif not values:
        status = "unavailable"
    elif no_large_reversal:
        status = "insufficient_visible_progress"
    else:
        status = "age_reversal"

    return {
        "status": status,
        "pass": passed,
        "signals_years_younger": signals,
        "mean_years_younger": (
            round(float(average_progress), 3)
            if average_progress is not None
            else None
        ),
        "required_mean_progress": required_progress,
        "no_large_model_reversal": no_large_reversal,
        "policy": "relative_monotonicity_not_exact_age",
        "interpretation": (
            "Direction-only safeguard; not proof of chronological age or "
            "biological plausibility. Human structure review is required."
        ),
    }


def pose_assessment(row: dict) -> dict:
    structure = row.get("structure_3d") or {}
    pose = structure.get("pose_degrees") or {}
    yaw = _number(pose.get("yaw"))
    pitch = _number(pose.get("pitch"))
    roll = _number(pose.get("roll"))
    detection = _number(row.get("face_detection_score"))
    available = None not in (yaw, pitch, roll, detection)
    passed = bool(
        available
        and detection >= MIN_FACE_DETECTION_SCORE
        and abs(yaw) <= MAX_ABS_YAW_DEGREES
        and abs(pitch) <= MAX_ABS_PITCH_DEGREES
        and abs(roll) <= MAX_ABS_ROLL_DEGREES
    )
    return {
        "status": "morph_pose_ready" if passed else "pose_or_detection_review",
        "pass": passed,
        "face_detection_score": detection,
        "pose_degrees": {"yaw": yaw, "pitch": pitch, "roll": roll},
        "limits": {
            "minimum_detection": MIN_FACE_DETECTION_SCORE,
            "maximum_abs_yaw": MAX_ABS_YAW_DEGREES,
            "maximum_abs_pitch": MAX_ABS_PITCH_DEGREES,
            "maximum_abs_roll": MAX_ABS_ROLL_DEGREES,
        },
    }


def visible_child_structure_assessment(row: dict, target_age: int) -> dict:
    """Require visible younger geometry for child keyframes, not exact age."""
    required = int(target_age) <= 15
    evidence = row.get("structure_3d_assessment") or {}
    score = _number(evidence.get("growth_direction_score"))
    measurements = evidence.get("growth_direction_measurements") or []
    expected_count = sum(
        item.get("status") == "expected"
        for item in measurements
        if isinstance(item, dict)
    )
    opposite_count = sum(
        item.get("status") == "opposite"
        for item in measurements
        if isinstance(item, dict)
    )
    available = score is not None and len(measurements) >= 4
    passed = bool(
        not required
        or (
            available
            and score >= MIN_CHILD_STRUCTURE_DIRECTION_SCORE
            and expected_count >= 2
            and opposite_count == 0
        )
    )
    return {
        "status": (
            "visible_younger_structure"
            if passed
            else "insufficient_or_wrong_child_structure"
        ),
        "pass": passed,
        "required": required,
        "available": available,
        "growth_direction_score": score,
        "minimum_direction_score": MIN_CHILD_STRUCTURE_DIRECTION_SCORE,
        "expected_metric_count": expected_count,
        "opposite_metric_count": opposite_count,
        "interpretation": (
            "A morph-readiness direction gate, not proof of biological age."
        ),
    }


def morph_anchor_assessment(row: dict, parent_age: int, target_age: int) -> dict:
    """Return eligibility for guardian review, never automatic approval."""
    trajectory = trajectory_assessment(row, parent_age, target_age)
    pose = pose_assessment(row)
    visible_structure = visible_child_structure_assessment(row, target_age)
    identity_pass = bool(row.get("identity_pass"))
    eligible = (
        identity_pass
        and trajectory["pass"]
        and pose["pass"]
        and visible_structure["pass"]
    )
    age_consensus = row.get("age_consensus") or {}
    structure = row.get("structure_3d_assessment") or {}
    return {
        "status": "human_review" if eligible else "reject",
        "eligible_for_human_review": eligible,
        "automatic_approval": False,
        "identity_hard_gate": identity_pass,
        "trajectory_hard_gate": trajectory,
        "morph_pose_hard_gate": pose,
        "visible_child_structure_hard_gate": visible_structure,
        "exact_age_evidence": {
            "status": age_consensus.get("review_status", "unavailable"),
            "reason": age_consensus.get("reason"),
            "used_as_hard_gate": False,
        },
        "growth_structure_evidence": {
            "status": structure.get("status", "unavailable"),
            "growth_direction_score": structure.get("growth_direction_score"),
            "personal_structure_stable": structure.get(
                "personal_structure_stable"
            ),
            "used_as_hard_gate": False,
        },
        "note": (
            "This is a plausible morph-keyframe assessment, not proof of the "
            "person's historical appearance or exact photographed age."
        ),
    }
