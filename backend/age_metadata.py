"""Validated metadata for biologically informed past-age generation."""

from __future__ import annotations

from datetime import date


BIOLOGICAL_SEXES = {"unspecified", "female", "male"}
POPULATION_GROUPS = {"unspecified", "korean", "east_asian", "other"}


def parse_iso_date(value: str | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name}은 YYYY-MM-DD 형식이어야 합니다.") from exc


def age_on_date(birth_date: date, photo_date: date) -> int:
    """Return completed years of age on the date a photo was taken."""
    if photo_date < birth_date:
        raise ValueError("사진 촬영일은 생년월일보다 늦어야 합니다.")
    return photo_date.year - birth_date.year - (
        (photo_date.month, photo_date.day) < (birth_date.month, birth_date.day)
    )


def resolve_reference_age(
    current_age: int | None,
    birth_date_value: str | None = None,
    photo_date_value: str | None = None,
) -> tuple[int, str | None, str | None, str]:
    """Resolve the age anchor and record whether it came from dates or manual input."""
    birth_date = parse_iso_date(birth_date_value, "생년월일")
    photo_date = parse_iso_date(photo_date_value, "사진 촬영일")
    if (birth_date is None) != (photo_date is None):
        raise ValueError("생년월일과 사진 촬영일은 함께 입력해 주세요.")

    if birth_date is not None and photo_date is not None:
        derived_age = age_on_date(birth_date, photo_date)
        if current_age is not None and int(current_age) != derived_age:
            raise ValueError(
                f"입력한 나이({current_age})와 촬영일 기준 나이({derived_age})가 다릅니다."
            )
        return derived_age, birth_date.isoformat(), photo_date.isoformat(), "verified_dates"

    if current_age is None:
        raise ValueError("현재 나이 또는 생년월일과 사진 촬영일을 입력해 주세요.")
    return int(current_age), None, None, "manual_age"


def normalize_biological_sex(value: str | None) -> str:
    normalized = str(value or "unspecified").strip().lower()
    if normalized not in BIOLOGICAL_SEXES:
        raise ValueError("성장 통계 기준 성별 값이 올바르지 않습니다.")
    return normalized


def normalize_population_group(value: str | None) -> str:
    normalized = str(value or "unspecified").strip().lower()
    if normalized not in POPULATION_GROUPS:
        raise ValueError("인구집단 기준 값이 올바르지 않습니다.")
    return normalized


def prompt_demographic_description(plan: dict) -> str:
    """Return a bounded prompt phrase; never interpolate arbitrary user text."""
    population = {
        "korean": "Korean",
        "east_asian": "East Asian",
        "other": "",
        "unspecified": "",
    }.get(str(plan.get("population_group", "unspecified")), "")
    sex = {
        "male": "male",
        "female": "female",
        "unspecified": "person",
    }.get(str(plan.get("biological_sex", "unspecified")), "person")
    if sex == "person":
        return f"{population} person".strip()
    return f"{population} {sex} person".strip()
