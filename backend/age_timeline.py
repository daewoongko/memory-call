"""Manage the past-to-current age-anchor plan."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from age_metadata import (
    normalize_biological_sex,
    normalize_population_group,
    resolve_reference_age,
)
from age_policy import (
    MAX_CURRENT_AGE,
    MIN_CURRENT_AGE,
    MIN_TARGET_AGE,
    planned_stages,
    public_policy,
    split_segment,
)
from storage import (
    AGE_CANDIDATES_DIR,
    AGE_DEBUG_DIR,
    AGE_PLAN_PATH,
    ALIGNED_FACES_DIR,
    DEFAULT_FACE_PERSONA_ID,
    LOOPS_DIR,
    MORPH_PATH,
    RAW_FACES_DIR,
    SOURCE_FACES_DIR,
    PersonaFaceStorage,
    ensure_persona_face_directories,
)


ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_VISIBLE_CANDIDATES = 4
NON_PHOTO_NAME_MARKERS = (
    "fran_raw",
    "fran_line",
    "structure_guide",
    "lineart",
)


def stages_for(current_age: int, extra_ages: list[int] | None = None) -> list[dict]:
    """Return an adaptive childhood-to-current anchor path for the UI."""
    return planned_stages(current_age, extra_ages, MIN_TARGET_AGE)


def _paths(persona_id: str | None = None) -> PersonaFaceStorage:
    if persona_id is not None:
        return ensure_persona_face_directories(persona_id)
    paths = PersonaFaceStorage(
        DEFAULT_FACE_PERSONA_ID,
        AGE_PLAN_PATH.parent,
        SOURCE_FACES_DIR,
        AGE_CANDIDATES_DIR,
        AGE_PLAN_PATH.parent / "age_anchors",
        AGE_DEBUG_DIR,
        AGE_PLAN_PATH,
        RAW_FACES_DIR,
        ALIGNED_FACES_DIR,
        ALIGNED_FACES_DIR / "age_path_final",
        LOOPS_DIR,
        MORPH_PATH,
        True,
    )
    for folder in (
        paths.root, paths.source, paths.age_candidates, paths.age_anchors,
        paths.age_debug, paths.raw, paths.aligned, paths.final_age_path,
        paths.loops,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    return paths


def _read(persona_id: str | None = None) -> dict:
    plan_path = _paths(persona_id).age_plan
    if not plan_path.is_file():
        return {}
    try:
        value = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _validation_by_name(age: int, persona_id: str | None = None) -> dict[str, dict]:
    path = _paths(persona_id).age_debug / f"age{age:02d}_flux2_validation.json"
    if not path.is_file():
        return {}
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = summary.get("rows") if isinstance(summary, dict) else []
    return {
        Path(str(row.get("path", ""))).name: row
        for row in rows or []
        if isinstance(row, dict) and row.get("path")
    }


def _candidate_rank(item: dict, age: int) -> tuple:
    """Rank completed photographs; FRAN drawings are never product candidates."""
    validation = item.get("validation") or {}
    age_estimation = validation.get("age_estimation") or {}
    secondary = validation.get("mivolo_age_estimation") or {}
    status = str(validation.get("review_status") or "legacy")
    status_rank = {"strong_pass": 3, "borderline": 2, "human_review": 1}.get(status, 0)
    return (
        1 if validation.get("full_pass") else 0,
        status_rank,
        float(age_estimation.get("target_range_vote_share", 0.0)),
        float(secondary.get("target_range_vote_share", 0.0)),
        -abs(float(validation.get("estimated_age", age)) - age),
        float(validation.get("parent_similarity", 0.0)),
        float(validation.get("similarity_mean", 0.0)),
    )


def _candidate_files(
    age: int,
    persona_id: str | None = None,
    selected_name: str | None = None,
) -> list[dict]:
    prefix = f"age{age:02d}_"
    paths = _paths(persona_id)
    if not paths.age_candidates.exists():
        return []
    validation = _validation_by_name(age, persona_id)
    url_prefix = "/age-candidates" if paths.legacy else (
        f"/persona-assets/{paths.persona_id}/age_candidates"
    )
    candidates = []
    for path in paths.age_candidates.iterdir():
        if (
            not path.is_file()
            or path.suffix.lower() not in ALLOWED_SUFFIXES
            or not path.name.startswith(prefix)
            or any(
                marker in path.name.casefold()
                for marker in NON_PHOTO_NAME_MARKERS
            )
        ):
            continue
        validation_row = validation.get(path.name)
        # New candidates only enter the product after the photograph validator
        # passes them.  A previously selected legacy photograph remains visible
        # so an existing user's saved timeline is not broken by this migration.
        if (
            validation_row
            and not validation_row.get("full_pass")
            and path.name != selected_name
        ):
            continue
        candidates.append(
            {
                "name": path.name,
                "url": f"{url_prefix}/{path.name}",
                "size_kb": path.stat().st_size // 1024,
                "validation": validation_row,
                "candidate_type": "completed_photo",
            }
        )
    candidates.sort(key=lambda item: _candidate_rank(item, age), reverse=True)
    visible = candidates[:MAX_VISIBLE_CANDIDATES]
    if selected_name and selected_name not in {item["name"] for item in visible}:
        selected = next(
            (item for item in candidates if item["name"] == selected_name), None
        )
        if selected:
            visible = [*visible[: MAX_VISIBLE_CANDIDATES - 1], selected]
    return visible


def get_plan(persona_id: str | None = None) -> dict:
    paths = _paths(persona_id)
    saved = _read(persona_id)
    current_age = saved.get("current_age")
    current_photo = saved.get("current_photo")
    if not isinstance(current_age, int):
        return {
            "configured": False,
            "current_age": None,
            "current_photo": None,
            "stages": [],
        }

    try:
        extra_ages = saved.get("extra_ages") or []
        stages = stages_for(current_age, extra_ages)
    except ValueError:
        return {
            "configured": False,
            "current_age": None,
            "current_photo": None,
            "stages": [],
        }

    source = paths.source / Path(str(current_photo or "")).name
    photo_exists = bool(current_photo) and source.is_file()
    selections = saved.get("selections") or {}
    for stage in stages:
        if stage["kind"] == "current":
            stage["selected"] = current_photo if photo_exists else None
            stage["url"] = (
                f"/identity-faces/{source.name}"
                if paths.legacy
                else f"/persona-assets/{paths.persona_id}/source/{source.name}"
            ) if photo_exists else None
            stage["candidates"] = []
        else:
            selected = selections.get(str(stage["age"]))
            candidates = _candidate_files(stage["age"], persona_id, selected)
            names = {item["name"] for item in candidates}
            stage["selected"] = selected if selected in names else None
            stage["candidates"] = candidates

    return {
        "configured": photo_exists,
        "persona_id": paths.persona_id,
        "current_age": current_age,
        "current_photo": current_photo if photo_exists else None,
        "birth_date": saved.get("birth_date"),
        "current_photo_date": saved.get("current_photo_date"),
        "age_source": saved.get("age_source", "manual_age"),
        "biological_sex": saved.get("biological_sex", "unspecified"),
        "population_group": saved.get("population_group", "unspecified"),
        "stages": stages,
        "generation_path": [stage["age"] for stage in reversed(stages)],
        "extra_ages": extra_ages,
        "policy": public_policy(),
        "updated_at": saved.get("updated_at"),
    }


def save_plan(
    current_age: int | None,
    current_photo: str,
    *,
    birth_date: str | None = None,
    current_photo_date: str | None = None,
    biological_sex: str | None = None,
    population_group: str | None = None,
    persona_id: str | None = None,
) -> dict:
    resolved_age, birth_date, current_photo_date, age_source = resolve_reference_age(
        current_age,
        birth_date,
        current_photo_date,
    )
    biological_sex = normalize_biological_sex(biological_sex)
    population_group = normalize_population_group(population_group)
    paths = _paths(persona_id)
    previous = _read(persona_id)
    previous_age = previous.get("current_age")
    extra_ages = (previous.get("extra_ages") or []) if previous_age == resolved_age else []
    stages = stages_for(resolved_age, extra_ages)
    safe_name = Path(current_photo).name
    if safe_name != current_photo or not (paths.source / safe_name).is_file():
        raise ValueError("현재 기준 사진을 찾을 수 없습니다.")

    allowed_ages = {str(stage["age"]) for stage in stages if stage["kind"] == "generated"}
    selections = {
        age: name
        for age, name in (previous.get("selections") or {}).items()
        if age in allowed_ages
    }
    payload = {
        "version": 4,
        "current_age": resolved_age,
        "current_photo": safe_name,
        "birth_date": birth_date,
        "current_photo_date": current_photo_date,
        "age_source": age_source,
        "biological_sex": biological_sex,
        "population_group": population_group,
        "extra_ages": extra_ages,
        "selections": selections,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(payload, persona_id)
    return get_plan(persona_id)


def _write(payload: dict, persona_id: str | None = None) -> None:
    plan_path = _paths(persona_id).age_plan
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = plan_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(plan_path)


def invalidate_younger_selections(
    selections: dict[str, str], generation_path: list[int], selected_age: int
) -> list[int]:
    """Remove every younger selection, including legacy ages outside the path."""
    if selected_age not in generation_path:
        return []

    invalidated: list[int] = []
    for age_key in list(selections):
        try:
            candidate_age = int(age_key)
        except (TypeError, ValueError):
            continue
        if candidate_age < selected_age:
            selections.pop(age_key, None)
            invalidated.append(candidate_age)
    return sorted(invalidated, reverse=True)


def invalidate_refined_branch(
    selections: dict[str, str], inserted_age: int
) -> list[int]:
    """Force a newly inserted midpoint and its younger branch to be regenerated."""
    invalidated: list[int] = []
    for age_key in list(selections):
        try:
            candidate_age = int(age_key)
        except (TypeError, ValueError):
            continue
        if candidate_age <= inserted_age:
            selections.pop(age_key, None)
            invalidated.append(candidate_age)
    return sorted(invalidated, reverse=True)


def select_candidate(age: int, filename: str,
                     persona_id: str | None = None) -> dict:
    plan = get_plan(persona_id)
    if not plan["configured"]:
        raise ValueError("현재 나이와 현재 기준 사진을 먼저 저장해주세요.")
    allowed = {
        stage["age"]: {candidate["name"] for candidate in stage["candidates"]}
        for stage in plan["stages"]
        if stage["kind"] == "generated"
    }
    safe_name = Path(filename).name
    if age not in allowed:
        raise ValueError("현재 나이보다 어린 생성 단계만 선택할 수 있습니다.")
    if safe_name != filename or safe_name not in allowed[age]:
        raise ValueError("해당 나이의 후보 사진을 찾을 수 없습니다.")

    saved = _read(persona_id)
    selections = saved.setdefault("selections", {})
    selections[str(age)] = safe_name
    invalidate_younger_selections(selections, plan["generation_path"], age)
    saved["version"] = 4
    saved["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(saved, persona_id)
    return get_plan(persona_id)


def insert_visual_bridge_candidate(
    older_age: int,
    bridge_age: int,
    younger_age: int,
    filename: str,
    persona_id: str | None = None,
) -> dict:
    """Insert an approved visual bridge without invalidating younger anchors.

    A visual bridge is not a failed-stage refinement.  It exists only to make
    a large but plausible developmental change easier to interpolate, so the
    already-approved younger dependency chain remains valid.
    """
    if not older_age > bridge_age > younger_age:
        raise ValueError("The bridge age must be strictly between its endpoints.")

    paths = _paths(persona_id)
    saved = _read(persona_id)
    if not isinstance(saved.get("current_age"), int):
        raise ValueError("Configure the current age before inserting a bridge.")

    plan = get_plan(persona_id)
    descending = plan.get("generation_path") or []
    bridge_present = bridge_age in descending
    expected = (
        any(
            descending[index : index + 3]
            == [older_age, bridge_age, younger_age]
            for index in range(len(descending) - 2)
        )
        if bridge_present
        else any(
            descending[index : index + 2] == [older_age, younger_age]
            for index in range(len(descending) - 1)
        )
    )
    if not expected:
        raise ValueError("The requested visual bridge endpoints are not adjacent.")

    selections = saved.setdefault("selections", {})
    if not selections.get(str(older_age)) or not selections.get(str(younger_age)):
        raise ValueError("Both visual bridge endpoints must already be approved.")

    safe_name = Path(filename).name
    candidate_path = paths.age_candidates / safe_name
    if (
        safe_name != filename
        or not safe_name.startswith(f"age{bridge_age:02d}_")
        or candidate_path.suffix.lower() not in ALLOWED_SUFFIXES
        or not candidate_path.is_file()
    ):
        raise ValueError("The visual bridge candidate file is missing or unsafe.")

    extra_ages = {int(value) for value in saved.get("extra_ages") or []}
    extra_ages.add(bridge_age)
    saved["extra_ages"] = sorted(extra_ages, reverse=True)
    selections[str(bridge_age)] = safe_name
    saved["version"] = 4
    saved["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(saved, persona_id)

    result = get_plan(persona_id)
    result["inserted_age"] = bridge_age
    result["invalidated_ages"] = []
    return result


def remove_refinement(age: int, persona_id: str | None = None) -> dict:
    """Remove one experimental midpoint and invalidate its younger branch."""
    saved = _read(persona_id)
    current_age = saved.get("current_age")
    if not isinstance(current_age, int):
        raise ValueError("Configure the current age before changing refinements")
    extra_ages = [int(value) for value in saved.get("extra_ages") or []]
    if age not in extra_ages:
        result = get_plan(persona_id)
        result["removed_age"] = None
        result["invalidated_ages"] = []
        return result
    saved["extra_ages"] = sorted(
        {value for value in extra_ages if value != age}, reverse=True
    )
    invalidated = invalidate_refined_branch(
        saved.setdefault("selections", {}), age
    )
    saved["version"] = 4
    saved["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(saved, persona_id)
    result = get_plan(persona_id)
    result["removed_age"] = age
    result["invalidated_ages"] = invalidated
    return result


def refine_failed_segment(older_age: int, younger_age: int,
                          persona_id: str | None = None) -> dict:
    """Insert a midpoint anchor between two adjacent failed stages."""
    saved = _read(persona_id)
    current_age = saved.get("current_age")
    if not isinstance(current_age, int):
        raise ValueError("현재 나이와 현재 기준 사진을 먼저 저장해주세요.")

    plan = get_plan(persona_id)
    descending = plan.get("generation_path") or []
    if not any(
        descending[index] == older_age and descending[index + 1] == younger_age
        for index in range(len(descending) - 1)
    ):
        raise ValueError("현재 계획에서 서로 인접한 두 연령만 분할할 수 있습니다.")

    inserted_age = split_segment(older_age, younger_age)
    extra_ages = set(saved.get("extra_ages") or [])
    extra_ages.add(inserted_age)
    saved["extra_ages"] = sorted(extra_ages, reverse=True)
    invalidated = invalidate_refined_branch(
        saved.setdefault("selections", {}), inserted_age
    )
    saved["version"] = 4
    saved["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(saved, persona_id)
    result = get_plan(persona_id)
    result["inserted_age"] = inserted_age
    result["invalidated_ages"] = invalidated
    return result
