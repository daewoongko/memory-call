"""Deterministic feedback controls for age-anchor generation.

The chronological target never changes. ``control_age`` is an internal
generation set-point used to compensate when the image editor systematically
under- or over-edits age. Validation always uses ``target_age``.
"""

from __future__ import annotations

from statistics import median


MIN_CONTROL_AGE = 8
MIN_ADULT_STRENGTH = 0.34
MAX_ADULT_STRENGTH = 0.58
MIN_LORA_SCALE = 0.64
MAX_LORA_SCALE = 0.84


def base_edit_strength(parent_age: int, target_age: int) -> float:
    gap = max(1, int(parent_age) - int(target_age))
    return round(min(0.75, 0.22 + 0.06 * gap), 2)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _observed_age(row: dict) -> tuple[float | None, dict[str, float]]:
    """Use the same raw independent estimates that drive the age gate."""
    signals: dict[str, float] = {}
    insightface = row.get("insightface_age_estimation") or row.get("age_estimation") or {}
    if isinstance(insightface.get("median"), (int, float)):
        signals["insightface_raw"] = float(insightface["median"])
    elif isinstance(row.get("estimated_age"), (int, float)):
        signals["insightface_raw"] = float(row["estimated_age"])

    mivolo = row.get("mivolo_raw_age_estimation") or {}
    if not mivolo:
        compatibility = row.get("mivolo_age_estimation") or {}
        if compatibility.get("age_basis") == "raw_model_output" or (
            compatibility.get("personal_bias_applied") is False
        ):
            mivolo = compatibility
    if mivolo.get("status") == "available" and isinstance(
        mivolo.get("median"), (int, float)
    ):
        signals["mivolo_raw"] = float(mivolo["median"])
    if not signals:
        return None, {}
    return float(median(signals.values())), signals


def summarize_generation_feedback(rows: list[dict], target_age: int) -> dict:
    """Summarize the best usable candidate from the previous failed batch."""
    valid = []
    for row in rows:
        observed, signals = _observed_age(row)
        if observed is not None:
            valid.append({**row, "_observed_age": observed, "_age_signals": signals})
    if not valid:
        return {
            "direction": "unknown",
            "observed_age": None,
            "age_error": None,
            "identity_pass_rate": 0.0,
        }

    identity_rows = [row for row in valid if row.get("identity_pass")]
    usable = identity_rows or valid
    nearest_error = min(abs(float(row["_observed_age"]) - target_age) for row in usable)
    nearest = [
        row
        for row in usable
        if abs(float(row["_observed_age"]) - target_age) == nearest_error
    ]
    observed_age = float(median(row["_observed_age"] for row in nearest))
    age_error = observed_age - target_age
    direction = "too_old" if age_error > 0 else "too_young" if age_error < 0 else "on_target"
    return {
        "direction": direction,
        "observed_age": round(observed_age, 2),
        "age_error": round(age_error, 2),
        "identity_pass_rate": round(len(identity_rows) / len(valid), 4),
        "age_signals": nearest[0]["_age_signals"] if len(nearest) == 1 else {},
    }


def generation_controls(
    *,
    parent_age: int,
    target_age: int,
    attempt: int,
    previous_rows: list[dict] | None = None,
    base_lora_scale: float = 0.80,
    base_reference_count: int = 5,
) -> dict:
    """Return bounded generation controls for a 1-based segment attempt."""
    if parent_age <= target_age:
        raise ValueError("parent_age must be older than target_age")
    if attempt < 1:
        raise ValueError("attempt must be at least 1")

    strength = base_edit_strength(parent_age, target_age)
    controls = {
        "attempt": attempt,
        "target_age": target_age,
        "control_age": target_age,
        "edit_strength": strength,
        "lora_scale": round(_clamp(base_lora_scale, MIN_LORA_SCALE, MAX_LORA_SCALE), 2),
        "reference_count": max(1, min(5, int(base_reference_count))),
        "feedback": {
            "direction": "initial",
            "observed_age": None,
            "age_error": None,
            "identity_pass_rate": None,
        },
        "reason": "initial_gap_based_controls",
    }
    if attempt == 1:
        return controls

    feedback = summarize_generation_feedback(previous_rows or [], target_age)
    controls["feedback"] = feedback
    identity_rate = float(feedback.get("identity_pass_rate") or 0.0)
    error = float(feedback.get("age_error") or 0.0)

    if identity_rate < 0.5:
        controls.update(
            {
                "edit_strength": round(max(MIN_ADULT_STRENGTH, strength - 0.04), 2),
                "lora_scale": round(
                    _clamp(base_lora_scale + 0.04, MIN_LORA_SCALE, MAX_LORA_SCALE), 2
                ),
                "reference_count": min(5, max(4, base_reference_count)),
                "reason": "identity_recovery_backoff",
            }
        )
        return controls

    retry_level = min(3, attempt - 1)
    if feedback["direction"] == "too_old":
        observed_error = max(1, min(4, int(round(error))))
        control_offset = min(6, observed_error + retry_level - 1)
        strength_boost = {1: 0.08, 2: 0.14, 3: 0.22}[retry_level]
        lora_drop = {1: 0.08, 2: 0.12, 3: 0.16}[retry_level]
        controls.update(
            {
                "control_age": max(MIN_CONTROL_AGE, target_age - control_offset),
                "edit_strength": round(
                    _clamp(
                        strength + strength_boost,
                        MIN_ADULT_STRENGTH,
                        MAX_ADULT_STRENGTH,
                    ),
                    2,
                ),
                "lora_scale": round(
                    _clamp(
                        base_lora_scale - lora_drop,
                        MIN_LORA_SCALE,
                        MAX_LORA_SCALE,
                    ),
                    2,
                ),
                "reference_count": min(3, max(1, base_reference_count)),
                "reason": f"age_too_old_retry_{retry_level}",
            }
        )
    elif feedback["direction"] == "too_young":
        offset = max(1, min(4, int(round(abs(error)))))
        controls.update(
            {
                "control_age": min(parent_age - 1, target_age + offset),
                "edit_strength": round(
                    _clamp(strength - 0.04 * retry_level, MIN_ADULT_STRENGTH, MAX_ADULT_STRENGTH),
                    2,
                ),
                "lora_scale": round(
                    _clamp(base_lora_scale + 0.04, MIN_LORA_SCALE, MAX_LORA_SCALE), 2
                ),
                "reference_count": min(5, max(4, base_reference_count)),
                "reason": f"age_too_young_retry_{retry_level}",
            }
        )
    else:
        controls["reason"] = "no_directional_feedback"
    return controls
