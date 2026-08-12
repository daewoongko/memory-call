"""Denominator-aware rates and conservative period comparisons."""

from __future__ import annotations


MIN_CALLS_FOR_COMPARISON = 10
MIN_UTTERANCES_FOR_COMPARISON = 20


def per(numerator: int | float, denominator: int | float, scale: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator) * scale, 2)


def window_rates(*, calls: int, elder_utterances: int, observations: int,
                 repeats: int, risks: int) -> dict:
    return {
        "observation_per_100_utterances": per(observations, elder_utterances, 100),
        "repeat_per_call": per(repeats, calls, 1),
        "risk_per_100_calls": per(risks, calls, 100),
        "denominators": {"calls": calls, "elder_utterances": elder_utterances},
    }


def compare(current: float | None, previous: float | None, *, label: str,
            unit: str, current_sample: int, previous_sample: int,
            minimum_sample: int) -> dict:
    if (current is None or previous is None or current_sample < minimum_sample
            or previous_sample < minimum_sample):
        return {
            "label": label,
            "status": "insufficient_sample",
            "current": current,
            "previous": previous,
            "text": "비교에 필요한 기록이 아직 충분하지 않습니다.",
        }
    difference = round(current - previous, 2)
    direction = "same" if difference == 0 else ("up" if difference > 0 else "down")
    if direction == "same":
        text = "직전 같은 기간과 같은 수준입니다."
    else:
        text = f"직전 같은 기간보다 {abs(difference):g}{unit} {'높습니다' if difference > 0 else '낮습니다'}."
    return {
        "label": label,
        "status": "observed_difference",
        "current": current,
        "previous": previous,
        "difference": difference,
        "direction": direction,
        "text": text,
        "caution": "관찰 빈도의 차이이며 상태 악화나 호전을 의미하지 않습니다.",
    }
