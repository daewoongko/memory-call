"""Interpretable screening signals for past-age face candidates.

These measurements are pose-normalized proxies, not medical or forensic age
estimates.  Until a demographic calibration dataset is installed, structure
signals remain advisory and must not silently reject a candidate.
"""

from __future__ import annotations

from collections import Counter
from math import dist
from statistics import mean, median, pstdev
from typing import Iterable


AGE_VIEW_COUNT = 5
MIN_TARGET_VOTE_SHARE = 0.60


def calibrate_personal_age_bias(
    reference_age_centers: Iterable[float], chronological_age: int
) -> dict:
    """Estimate a local, person-specific apparent-age offset from real photos."""
    values = [float(value) for value in reference_age_centers]
    if not values:
        raise ValueError("At least one real reference age estimate is required")
    center = float(median(values))
    absolute_residuals = [abs(value - center) for value in values]
    return {
        "status": "local_person_offset_advisory",
        "chronological_age": int(chronological_age),
        "reference_count": len(values),
        "reference_centers": [round(value, 2) for value in values],
        "model_reference_median": round(center, 2),
        "bias_years": round(center - chronological_age, 2),
        "median_absolute_deviation": round(float(median(absolute_residuals)), 2),
        "calibrated_probability": False,
        "note": (
            "Local offset estimated from real current-age portraits only. "
            "It is not a lifespan growth-curve calibration."
        ),
    }


def apply_personal_age_bias(value: float, calibration: dict) -> float:
    return round(float(value) - float(calibration.get("bias_years", 0.0)), 2)


def relative_age_evidence(
    parent_estimate: float,
    candidate_estimate: float,
    parent_age: int,
    target_age: int,
) -> dict:
    """Compare measured de-aging with the chronological stage delta."""
    observed = float(candidate_estimate) - float(parent_estimate)
    expected = float(target_age - parent_age)
    error = observed - expected
    younger_direction = observed <= -1.0 if parent_age - target_age >= 2 else observed < 0
    within_tolerance = abs(error) <= 2.0
    status = (
        "expected_within_tolerance"
        if younger_direction and within_tolerance
        else "younger_but_insufficient"
        if younger_direction
        else "no_measured_deaging"
    )
    return {
        "parent_estimate": round(float(parent_estimate), 2),
        "candidate_estimate": round(float(candidate_estimate), 2),
        "expected_delta_years": round(expected, 2),
        "observed_delta_years": round(observed, 2),
        "delta_error_years": round(error, 2),
        "younger_direction": younger_direction,
        "within_two_year_tolerance": within_tolerance,
        "status": status,
        "used_as_hard_gate": False,
    }


def summarize_age_votes(votes: Iterable[int], age_limits: dict[str, int]) -> dict:
    values = sorted(int(value) for value in votes)
    if not values:
        raise ValueError("At least one age vote is required")
    low, high = int(age_limits["min"]), int(age_limits["max"])
    counts = Counter(values)
    vote_share = sum(low <= value <= high for value in values) / len(values)
    center = float(median(values))
    # With five correlated test-time views, min/max is a stability interval,
    # not a statistically calibrated confidence interval.
    stability_low, stability_high = values[0], values[-1]
    boundary = center in {low, high}
    interval_outside = stability_low < low or stability_high > high
    pass_range = low <= center <= high and vote_share >= MIN_TARGET_VOTE_SHARE
    review_status = (
        "fail"
        if not pass_range
        else "borderline"
        if boundary or interval_outside or vote_share < 0.80
        else "strong_pass"
    )
    return {
        "votes": values,
        "distribution": {
            str(age): round(count / len(values), 4) for age, count in sorted(counts.items())
        },
        "mean": round(mean(values), 2),
        "median": round(center, 2),
        "standard_deviation": round(pstdev(values), 2),
        "stability_interval": {"min": stability_low, "max": stability_high},
        "target_range_vote_share": round(vote_share, 4),
        "range_pass": pass_range,
        "review_status": review_status,
        "uncertainty_kind": "test_time_view_stability_not_calibrated_confidence",
    }


def structure_metrics(bbox, keypoints) -> dict[str, float]:
    """Measure stable ratios from a detected face box and five face keypoints."""
    left, top, right, bottom = (float(value) for value in bbox)
    width, height = right - left, bottom - top
    points = [[float(v) for v in point[:2]] for point in keypoints]
    if width <= 0 or height <= 0 or len(points) < 5:
        raise ValueError("A valid face box and five keypoints are required")
    left_eye, right_eye, nose, left_mouth, right_mouth = points[:5]
    eye_y = (left_eye[1] + right_eye[1]) / 2
    mouth_y = (left_mouth[1] + right_mouth[1]) / 2
    return {
        "face_width_height": round(width / height, 4),
        "inter_eye_ratio": round(dist(left_eye, right_eye) / width, 4),
        "mouth_width_ratio": round(dist(left_mouth, right_mouth) / width, 4),
        "eye_to_mouth_ratio": round((mouth_y - eye_y) / height, 4),
        "eye_to_chin_ratio": round((bottom - eye_y) / height, 4),
        "nose_to_mouth_ratio": round((mouth_y - nose[1]) / height, 4),
    }


def assess_younger_structure(
    parent: dict[str, float],
    candidate: dict[str, float],
    parent_age: int,
    target_age: int,
    *,
    calibration_profile: str = "uncalibrated_general_growth_direction_v1",
) -> dict:
    """Check whether relative structure moves in common younger-face directions.

    Directions are intentionally soft. Individual growth varies and the current
    project does not yet contain a Korean longitudinal calibration cohort.
    """
    if parent_age <= target_age:
        raise ValueError("parent_age must be older than target_age")
    expectations = {
        "face_width_height": 1,   # relatively rounder/wider when younger
        "inter_eye_ratio": 1,     # eyes occupy more of face width
        "eye_to_mouth_ratio": -1, # shorter mid/lower facial proportions
        "eye_to_chin_ratio": -1,
    }
    tolerance = 0.004 if target_age >= 18 else 0.002
    rows = []
    scores = []
    for name, direction in expectations.items():
        delta = round(candidate[name] - parent[name], 4)
        directed = delta * direction
        if directed > tolerance:
            status, score = "expected", 1.0
        elif directed < -tolerance:
            status, score = "opposite", 0.0
        else:
            status, score = "stable", 0.5
        scores.append(score)
        rows.append(
            {
                "metric": name,
                "parent": parent[name],
                "candidate": candidate[name],
                "delta": delta,
                "expected_direction": "increase" if direction > 0 else "decrease",
                "status": status,
            }
        )
    score = round(sum(scores) / len(scores), 4)
    return {
        "profile": calibration_profile,
        "calibrated": False,
        "score": score,
        "status": "advisory_only",
        "measurements": rows,
        "note": (
            "Relative growth-direction proxy only. It is not a demographic "
            "confidence interval and is not used as a hard acceptance gate."
        ),
    }
