"""Adaptive age-anchor planning and validation policy.

The planner creates a coarse path first.  A failed segment is refined by
inserting its midpoint instead of weakening the quality thresholds.
"""

from __future__ import annotations

from typing import Iterable


MIN_TARGET_AGE = 8
MIN_CURRENT_AGE = 18
MAX_CURRENT_AGE = 100


def step_for(older_age: int) -> int:
    """Return the initial backward step for the current age band."""
    if older_age >= 40:
        return 5
    if older_age >= 18:
        return 3
    return 2


def initial_path(current_age: int, minimum_age: int = MIN_TARGET_AGE) -> list[int]:
    """Return ages in generation order, from current age down to childhood."""
    if not MIN_CURRENT_AGE <= current_age <= MAX_CURRENT_AGE:
        raise ValueError(
            f"현재 나이는 {MIN_CURRENT_AGE}~{MAX_CURRENT_AGE}세로 입력해주세요."
        )
    if not 1 <= minimum_age < current_age:
        raise ValueError("최저 목표 나이는 현재 나이보다 작아야 합니다.")

    path = [current_age]
    cursor = current_age
    while cursor > minimum_age:
        next_age = max(minimum_age, cursor - step_for(cursor))
        if next_age == cursor:
            break
        path.append(next_age)
        cursor = next_age
    return path


def normalize_extra_ages(
    current_age: int,
    extra_ages: Iterable[int] | None,
    minimum_age: int = MIN_TARGET_AGE,
) -> list[int]:
    if extra_ages is None:
        return []
    return sorted(
        {
            int(age)
            for age in extra_ages
            if minimum_age < int(age) < current_age
        },
        reverse=True,
    )


def path_with_refinements(
    current_age: int,
    extra_ages: Iterable[int] | None = None,
    minimum_age: int = MIN_TARGET_AGE,
) -> list[int]:
    ages = set(initial_path(current_age, minimum_age))
    ages.update(normalize_extra_ages(current_age, extra_ages, minimum_age))
    return sorted(ages, reverse=True)


def split_segment(older_age: int, younger_age: int) -> int:
    """Split only gaps large enough to leave meaningful sub-stages."""
    if older_age <= younger_age:
        raise ValueError("older_age는 younger_age보다 커야 합니다.")
    if older_age - younger_age < 6:
        raise ValueError("2년 이하 간격은 더 나누지 않고 사람 검토로 넘깁니다.")
    return younger_age + (older_age - younger_age + 1) // 2


def age_range(target_age: int) -> dict[str, int]:
    """Allowed apparent-age range for candidate screening."""
    if target_age <= 9:
        low, high = max(1, target_age - 1), target_age + 2
    elif target_age <= 17:
        low, high = target_age - 2, target_age + 2
    else:
        low, high = target_age - 2, target_age + 2
    return {"min": low, "max": high}


def identity_thresholds(current_age: int, target_age: int) -> dict[str, float]:
    """Development-aware identity gates plus a strict adjacent-anchor check.

    Longitudinal child-face studies show nonlinear score degradation with
    elapsed time and faster change in younger faces.  Their matcher thresholds
    cannot be transferred to InsightFace cosine scores, so the values below
    are local operating points calibrated against this project's accepted
    anchor trajectory.  The adjacent parent stays strict to prevent cumulative
    identity drift while the current-adult reference gates relax with age.
    """
    gap = max(0, current_age - target_age)
    if gap <= 5:
        gap_mean, gap_primary = 0.82, 0.86
    elif gap <= 10:
        gap_mean, gap_primary = 0.78, 0.82
    elif gap <= 15:
        gap_mean, gap_primary = 0.72, 0.76
    elif gap <= 18:
        gap_mean, gap_primary = 0.68, 0.70
    elif gap <= 22:
        gap_mean, gap_primary = 0.64, 0.66
    else:
        gap_mean, gap_primary = 0.60, 0.62

    # Underlying age matters as well as elapsed time.  These ceilings encode
    # the stronger developmental change below 18 while allowing the adjacent
    # approved keyframe to carry most of the continuity evidence.
    if target_age >= 18:
        age_mean, age_primary = 1.0, 1.0
    elif target_age >= 16:
        age_mean, age_primary = 0.72, 0.76
    elif target_age >= 14:
        age_mean, age_primary = 0.68, 0.70
    elif target_age >= 10:
        age_mean, age_primary = 0.64, 0.66
    else:
        age_mean, age_primary = 0.60, 0.62

    mean_current = min(gap_mean, age_mean)
    primary_current = min(gap_primary, age_primary)
    if target_age <= 15:
        # A single designated adult portrait becomes less representative in
        # childhood.  Keep it as a floor, but do not make it stricter than the
        # aggregate five-reference gate; the adjacent anchor remains strict.
        primary_current = min(primary_current, mean_current)
    return {
        # The generated path uses 1-3 year adjacent gaps.  Keeping this fixed
        # is the safeguard against a series that gradually becomes a new face.
        "adjacent_parent": 0.88,
        "current_reference_mean": mean_current,
        "current_primary": primary_current,
        "review_margin": 0.05,
    }


def stage_policy(current_age: int, target_age: int, parent_age: int) -> dict:
    allowed_age = age_range(target_age)
    # For intervals of two years or more, an unchanged parent-age face must
    # not pass merely because the age estimator is noisy.
    if parent_age - target_age >= 2:
        allowed_age["max"] = min(allowed_age["max"], parent_age - 1)
    return {
        "target_age": target_age,
        "parent_age": parent_age,
        "year_gap": parent_age - target_age,
        "allowed_apparent_age": allowed_age,
        "identity": identity_thresholds(current_age, target_age),
        "on_failure": "split_age_gap",
    }


def planned_stages(
    current_age: int,
    extra_ages: Iterable[int] | None = None,
    minimum_age: int = MIN_TARGET_AGE,
) -> list[dict]:
    """Return chronological UI stages with per-stage validation policy."""
    descending = path_with_refinements(current_age, extra_ages, minimum_age)
    parent_by_target = {
        descending[index + 1]: descending[index]
        for index in range(len(descending) - 1)
    }
    stages = []
    for age in reversed(descending):
        if age == current_age:
            stages.append(
                {"age": age, "label": "현재", "kind": "current", "policy": None}
            )
        else:
            stages.append(
                {
                    "age": age,
                    "label": f"{age}세",
                    "kind": "generated",
                    "policy": stage_policy(current_age, age, parent_by_target[age]),
                }
            )
    return stages


def public_policy() -> dict:
    return {
        "minimum_target_age": MIN_TARGET_AGE,
        "initial_intervals": [
            {"minimum_age": 40, "years": 5},
            {"minimum_age": 18, "years": 3},
            {"minimum_age": 8, "years": 2},
        ],
        "failure_action": "split the failed segment at its midpoint",
        "selection_order": [
            "apparent_age",
            "adjacent_identity",
            "current_identity",
            "morph_continuity",
            "human_review",
        ],
    }
