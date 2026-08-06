"""Validate generated past-age candidates with identity and age evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_biology import (  # noqa: E402
    apply_personal_age_bias,
    assess_younger_structure,
    calibrate_personal_age_bias,
    relative_age_evidence,
    structure_metrics,
    summarize_age_votes,
)
from age_policy import path_with_refinements, split_segment, stage_policy  # noqa: E402
from age_growth import (  # noqa: E402
    assess_3d_structure,
    growth_prior,
    personal_structure_profile,
    run_3ddfa,
)
from age_secondary import (  # noqa: E402
    combine_age_evidence,
    run_mivolo,
    summarize_mivolo_row,
    summarize_person_offset_advisory,
)

SOURCE_DIR = ROOT / "data" / "faces" / "source"
CANDIDATE_DIR = ROOT / "data" / "faces" / "age_candidates"
DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"
PLAN_PATH = ROOT / "data" / "faces" / "age_plan.json"
INSIGHTFACE_ROOT = Path.home() / ".insightface"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, default=16)
    return parser.parse_args()


def read_rgb(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def make_analyzer(name: str, *, include_age: bool = False) -> FaceAnalysis:
    allowed = None if include_age else ["detection", "recognition"]
    app = FaceAnalysis(
        name=name,
        root=str(INSIGHTFACE_ROOT),
        allowed_modules=allowed,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_thresh=0.5, det_size=(640, 640))
    return app


def largest_face(app: FaceAnalysis, rgb: np.ndarray):
    faces = app.get(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not faces:
        raise ValueError("No face detected")
    return max(
        faces,
        key=lambda face: float(
            (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
        ),
    )


def age_views(rgb: np.ndarray) -> list[np.ndarray]:
    """Return deterministic views for estimator-stability screening."""
    return [
        np.ascontiguousarray(rgb),
        np.ascontiguousarray(np.flip(rgb, axis=1)),
        cv2.convertScaleAbs(rgb, alpha=0.96, beta=0),
        cv2.convertScaleAbs(rgb, alpha=1.04, beta=0),
        cv2.convertScaleAbs(rgb, alpha=1.0, beta=4),
    ]


def estimate_age_votes(app: FaceAnalysis, rgb: np.ndarray) -> list[int]:
    return [int(largest_face(app, view).age) for view in age_views(rgb)]


def identity_pass(metrics: dict, thresholds: dict) -> bool:
    return (
        metrics["parent_similarity"] >= thresholds["adjacent_parent"]
        and metrics["similarity_mean"] >= thresholds["current_reference_mean"]
        and metrics["primary_similarity"] >= thresholds["current_primary"]
    )


def resolve_parent(plan: dict, target_age: int, primary_path: Path) -> tuple[int, Path]:
    current_age = int(plan.get("current_age", 0))
    generation_path = path_with_refinements(
        current_age,
        plan.get("extra_ages") or [],
    )
    if target_age not in generation_path[1:]:
        allowed = ", ".join(str(age) for age in generation_path[1:])
        raise ValueError(f"Target age must be in the saved path: {allowed}")

    index = generation_path.index(target_age)
    parent_age = generation_path[index - 1]
    if parent_age == current_age:
        return parent_age, primary_path

    selected_name = (plan.get("selections") or {}).get(str(parent_age))
    if not selected_name:
        raise ValueError(
            f"Select an approved age-{parent_age} candidate before validating "
            f"age {target_age}."
        )
    safe_name = Path(str(selected_name)).name
    if safe_name != selected_name:
        raise ValueError("Invalid selected parent filename")
    parent_path = CANDIDATE_DIR / safe_name
    if not parent_path.is_file():
        raise FileNotFoundError(f"Selected parent anchor not found: {parent_path}")
    return parent_age, parent_path


def main() -> None:
    args = parse_args()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    source_paths = sorted(
        path
        for path in SOURCE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    candidate_paths = sorted(CANDIDATE_DIR.glob(f"age{args.age:02d}_*.png"))
    if not source_paths:
        raise FileNotFoundError(f"No current photos: {SOURCE_DIR}")
    if not candidate_paths:
        raise FileNotFoundError(f"No generated age-{args.age} candidates")

    current_name = str(plan.get("current_photo", ""))
    primary_path = next((path for path in source_paths if path.name == current_name), None)
    if primary_path is None:
        raise FileNotFoundError(f"Current representative not found: {current_name}")

    current_age = int(plan.get("current_age", 0))
    parent_age, parent_path = resolve_parent(plan, args.age, primary_path)
    policy = stage_policy(current_age, args.age, parent_age)
    age_limits = policy["allowed_apparent_age"]
    identity_limits = policy["identity"]

    print("Loading identity analyzer (buffalo_l)...", flush=True)
    identity_app = make_analyzer("buffalo_l")
    print("Loading age analyzer (antelopev2)...", flush=True)
    age_app = make_analyzer("antelopev2", include_age=True)

    unique_paths = list(dict.fromkeys([*source_paths, parent_path, *candidate_paths]))
    rgb_by_path = {str(path.resolve()): read_rgb(path) for path in unique_paths}
    identity_face_by_path = {
        key: largest_face(identity_app, rgb) for key, rgb in rgb_by_path.items()
    }

    face_entries = [
        {
            "id": key,
            "path": key,
            "bbox": [round(float(value), 3) for value in face.bbox],
        }
        for key, face in identity_face_by_path.items()
    ]
    print("Running independent MiVOLO age estimator...", flush=True)
    mivolo_result = run_mivolo(ROOT, face_entries, DEBUG_DIR, args.age)
    mivolo_rows = {
        str(row["id"]): row for row in mivolo_result.get("rows") or []
    }
    if mivolo_result.get("status") != "available":
        print(
            "  MiVOLO unavailable; validator is in explicit primary-only "
            f"degraded mode: {mivolo_result.get('reason', 'unknown')}",
            flush=True,
        )

    print("Running pose-normalized 3DDFA-V2 structure extraction...", flush=True)
    structure_3d_result = run_3ddfa(ROOT, face_entries, DEBUG_DIR, args.age)
    structure_3d_rows = {
        str(row["id"]): row for row in structure_3d_result.get("rows") or []
    }
    if structure_3d_result.get("status") != "available":
        print(
            "  3DDFA-V2 unavailable; 3D structure remains advisory-unavailable: "
            f"{structure_3d_result.get('reason', 'unknown')}",
            flush=True,
        )

    source_age_estimations = []
    for path in source_paths:
        key = str(path.resolve())
        estimation = summarize_age_votes(
            estimate_age_votes(age_app, rgb_by_path[key]),
            {"min": max(1, current_age - 5), "max": current_age + 5},
        )
        source_age_estimations.append(
            {"path": str(path), "age_estimation": estimation}
        )
    personal_age_calibration = calibrate_personal_age_bias(
        [row["age_estimation"]["median"] for row in source_age_estimations],
        current_age,
    )

    source_mivolo_raw_age_estimations = []
    for path in source_paths:
        key = str(path.resolve())
        row = mivolo_rows.get(key)
        if row:
            raw_summary = summarize_mivolo_row(
                row,
                {"min": max(1, current_age - 5), "max": current_age + 5},
            )
            source_mivolo_raw_age_estimations.append(
                {"path": str(path), "age_estimation": raw_summary}
            )
    personal_mivolo_calibration = (
        {
            **calibrate_personal_age_bias(
                [
                    row["age_estimation"]["median"]
                    for row in source_mivolo_raw_age_estimations
                ],
                current_age,
            ),
            "used_as_hard_gate": False,
            "scope": "current_age_reference_portraits_only",
        }
        if len(source_mivolo_raw_age_estimations) == len(source_paths)
        else None
    )
    source_mivolo_corrected_age_estimations = []
    if personal_mivolo_calibration:
        for path in source_paths:
            key = str(path.resolve())
            source_mivolo_corrected_age_estimations.append(
                {
                    "path": str(path),
                    "age_estimation": summarize_person_offset_advisory(
                        mivolo_rows.get(key),
                        personal_mivolo_calibration,
                        {
                            "min": max(1, current_age - 5),
                            "max": current_age + 5,
                        },
                    ),
                }
            )

    source_3d_rows = [
        structure_3d_rows[str(path.resolve())]
        for path in source_paths
        if str(path.resolve()) in structure_3d_rows
    ]
    personal_3d_profile = (
        personal_structure_profile(source_3d_rows)
        if len(source_3d_rows) == len(source_paths)
        else None
    )
    stage_growth_prior = growth_prior(
        parent_age,
        args.age,
        str(plan.get("biological_sex", "unspecified")),
        str(plan.get("population_group", "unspecified")),
    )

    reference_embeddings = np.stack(
        [
            identity_face_by_path[str(path.resolve())].normed_embedding.copy()
            for path in source_paths
        ]
    )
    primary_embedding = identity_face_by_path[
        str(primary_path.resolve())
    ].normed_embedding.copy()
    parent_key = str(parent_path.resolve())
    parent_rgb = rgb_by_path[parent_key]
    parent_face = identity_face_by_path[parent_key]
    parent_embedding = parent_face.normed_embedding.copy()
    parent_structure = structure_metrics(parent_face.bbox, parent_face.kps)
    parent_age_estimation = summarize_age_votes(
        estimate_age_votes(age_app, parent_rgb),
        {"min": max(1, parent_age - 2), "max": parent_age + 2},
    )
    parent_corrected_age = apply_personal_age_bias(
        parent_age_estimation["median"], personal_age_calibration
    )
    parent_mivolo_age_estimation = summarize_mivolo_row(
        mivolo_rows.get(parent_key),
        {"min": max(1, parent_age - 2), "max": parent_age + 2},
    )
    parent_mivolo_corrected_age_estimation = summarize_person_offset_advisory(
        mivolo_rows.get(parent_key),
        personal_mivolo_calibration,
        {"min": max(1, parent_age - 2), "max": parent_age + 2},
    )
    parent_3d_structure = structure_3d_rows.get(parent_key)

    rows = []
    for path in candidate_paths:
        key = str(path.resolve())
        rgb = rgb_by_path[key]
        identity_face = identity_face_by_path[key]
        scores = reference_embeddings @ identity_face.normed_embedding
        metrics = {
            "similarity_min": round(float(scores.min()), 4),
            "similarity_mean": round(float(scores.mean()), 4),
            "similarity_max": round(float(scores.max()), 4),
            "primary_similarity": round(
                float(primary_embedding @ identity_face.normed_embedding), 4
            ),
            "parent_similarity": round(
                float(parent_embedding @ identity_face.normed_embedding), 4
            ),
            "face_detection_score": round(float(identity_face.det_score), 4),
        }
        age_estimation = summarize_age_votes(
            estimate_age_votes(age_app, rgb),
            age_limits,
        )
        estimated_age = int(round(age_estimation["median"]))
        corrected_estimated_age = apply_personal_age_bias(
            age_estimation["median"], personal_age_calibration
        )
        relative_evidence = relative_age_evidence(
            parent_corrected_age,
            corrected_estimated_age,
            parent_age,
            args.age,
        )
        mivolo_age_estimation = summarize_mivolo_row(
            mivolo_rows.get(key),
            age_limits,
        )
        mivolo_corrected_age_estimation = summarize_person_offset_advisory(
            mivolo_rows.get(key),
            personal_mivolo_calibration,
            age_limits,
        )
        mivolo_relative_evidence = (
            relative_age_evidence(
                parent_mivolo_age_estimation["median"],
                mivolo_age_estimation["median"],
                parent_age,
                args.age,
            )
            if parent_mivolo_age_estimation and mivolo_age_estimation
            else None
        )
        primary_age_pass = bool(age_estimation["range_pass"])
        age_consensus = combine_age_evidence(
            age_estimation,
            mivolo_age_estimation,
            relative_evidence,
        )
        age_pass = bool(age_consensus["automated_pass"])
        candidate_identity_pass = identity_pass(metrics, identity_limits)
        candidate_structure = structure_metrics(identity_face.bbox, identity_face.kps)
        structure_assessment = assess_younger_structure(
            parent_structure,
            candidate_structure,
            parent_age,
            args.age,
        )
        candidate_3d_structure = structure_3d_rows.get(key)
        structure_3d_assessment = (
            assess_3d_structure(
                personal_3d_profile,
                parent_3d_structure,
                candidate_3d_structure,
                stage_growth_prior,
            )
            if personal_3d_profile
            and parent_3d_structure
            and candidate_3d_structure
            else {
                "status": "unavailable",
                "used_as_hard_gate": False,
                "reason": structure_3d_result.get(
                    "reason", "incomplete_3d_reference_profile"
                ),
            }
        )
        row = {
            "path": str(path),
            "estimated_age": estimated_age,
            "corrected_estimated_age": corrected_estimated_age,
            "age_estimation": age_estimation,
            "insightface_age_estimation": age_estimation,
            "mivolo_raw_age_estimation": (
                mivolo_age_estimation
                or {
                    "status": "unavailable",
                    "reason": mivolo_result.get("reason", "missing_model_output"),
                    "used_as_hard_gate": True,
                }
            ),
            # Compatibility alias: from version 7 onward this is always raw output.
            "mivolo_age_estimation": (
                mivolo_age_estimation
                or {
                    "status": "unavailable",
                    "reason": mivolo_result.get("reason", "missing_model_output"),
                }
            ),
            "mivolo_corrected_age_estimation": (
                mivolo_corrected_age_estimation
                or {
                    "status": "unavailable",
                    "reason": "current_age_person_offset_unavailable",
                    "used_as_hard_gate": False,
                }
            ),
            "age_consensus": age_consensus,
            "relative_age_evidence": relative_evidence,
            "mivolo_relative_age_evidence": mivolo_relative_evidence,
            **metrics,
            "structure_metrics": candidate_structure,
            "structure_assessment": structure_assessment,
            "structure_3d": candidate_3d_structure,
            "structure_3d_assessment": structure_3d_assessment,
            "identity_pass": candidate_identity_pass,
            "insightface_age_range_pass": primary_age_pass,
            "mivolo_age_range_pass": (
                bool(mivolo_age_estimation["range_pass"])
                if mivolo_age_estimation
                else None
            ),
            "age_range_pass": age_pass,
            # Deprecated compatibility alias. This has never meant exact-year equality.
            "age_exact_pass": age_pass,
            "full_pass": candidate_identity_pass and age_pass,
            "review_status": (
                age_consensus["review_status"]
                if candidate_identity_pass
                else "fail"
            ),
        }
        rows.append(row)
        print(f"\n{path.name}", flush=True)
        print(f"  estimated age: {row['estimated_age']}", flush=True)
        print(
            f"  person-offset corrected age: {corrected_estimated_age:.1f} | "
            f"relative to parent {relative_evidence['observed_delta_years']:+.1f}y | "
            f"{relative_evidence['status']} (advisory)",
            flush=True,
        )
        print(
            "  age votes: "
            f"{age_estimation['votes']} | target share "
            f"{age_estimation['target_range_vote_share']:.0%} | "
            f"{age_estimation['review_status']}",
            flush=True,
        )
        if mivolo_age_estimation:
            print(
                "  MiVOLO raw estimates (legacy exact-age screen): "
                f"{mivolo_age_estimation['estimates']} | median "
                f"{mivolo_age_estimation['median']:.1f} | target share "
                f"{mivolo_age_estimation['target_range_vote_share']:.0%} | "
                f"{mivolo_age_estimation['review_status']}",
                flush=True,
            )
            if mivolo_corrected_age_estimation:
                print(
                    "  MiVOLO current-age person offset: "
                    f"median {mivolo_corrected_age_estimation['median']:.1f} | "
                    "advisory only, not used as a gate",
                    flush=True,
                )
        else:
            print("  MiVOLO: unavailable (primary-only degraded mode)", flush=True)
        print(
            "  identity similarity: "
            f"min {metrics['similarity_min']:.4f} | "
            f"mean {metrics['similarity_mean']:.4f} | "
            f"max {metrics['similarity_max']:.4f} | "
            f"primary {metrics['primary_similarity']:.4f} | "
            f"parent {metrics['parent_similarity']:.4f}",
            flush=True,
        )
        print(
            "  identity gates: "
            f"mean >= {identity_limits['current_reference_mean']:.2f} | "
            f"primary >= {identity_limits['current_primary']:.2f} | "
            f"parent >= {identity_limits['adjacent_parent']:.2f} "
            "(development-aware current reference; strict adjacent anchor)",
            flush=True,
        )
        if structure_3d_assessment.get("status") == "advisory_only":
            print(
                "  3DDFA-V2: personal shape RMSE "
                f"{structure_3d_assessment['personal_shape_rmse']:.4f} | "
                "growth direction "
                f"{structure_3d_assessment['growth_direction_score']:.0%} | "
                "advisory only",
                flush=True,
            )
        print(
            f"  strict identity: {'PASS' if row['identity_pass'] else 'FAIL'} | "
            f"InsightFace age: {'PASS' if primary_age_pass else 'FAIL'} | "
            f"MiVOLO age: "
            f"{('PASS' if mivolo_age_estimation['range_pass'] else 'FAIL') if mivolo_age_estimation else 'N/A'} | "
            f"consensus {age_limits['min']}~{age_limits['max']}: "
            f"{'PASS' if row['age_range_pass'] else age_consensus['review_status'].upper()} | "
            "legacy exact-age stage: "
            f"{'PASS' if row['full_pass'] else 'FAIL'}",
            flush=True,
        )

    summary = {
        "version": 7,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_age": current_age,
        "parent_age": parent_age,
        "parent_photo": str(parent_path),
        "parent_age_estimation": parent_age_estimation,
        "parent_corrected_age": parent_corrected_age,
        "parent_mivolo_age_estimation": parent_mivolo_age_estimation,
        "parent_mivolo_corrected_age_estimation": (
            parent_mivolo_corrected_age_estimation
        ),
        "source_age_estimations": source_age_estimations,
        "personal_age_calibration": personal_age_calibration,
        # Compatibility alias: raw MiVOLO summaries drive the independent gate.
        "source_mivolo_age_estimations": source_mivolo_raw_age_estimations,
        "source_mivolo_raw_age_estimations": source_mivolo_raw_age_estimations,
        "source_mivolo_corrected_age_estimations": (
            source_mivolo_corrected_age_estimations
        ),
        "personal_mivolo_age_calibration": personal_mivolo_calibration,
        "growth_prior": stage_growth_prior,
        "personal_3d_structure_profile": personal_3d_profile,
        "parent_3d_structure": parent_3d_structure,
        "structure_model": {
            "status": structure_3d_result.get("status", "unavailable"),
            "role": "pose_normalized_3d_structure_advisory",
            "model": structure_3d_result.get("model"),
            "pose_normalization": structure_3d_result.get("pose_normalization"),
            "reason": structure_3d_result.get("reason"),
            "request_path": structure_3d_result.get("request_path"),
            "output_path": structure_3d_result.get("output_path"),
            "used_as_hard_gate": False,
        },
        "age_models": {
            "primary": {
                "name": "InsightFace antelopev2 genderage",
                "role": "primary_age_estimator",
                "view_count": 5,
            },
            "secondary": {
                "status": mivolo_result.get("status", "unavailable"),
                "role": "independent_secondary_age_estimator",
                "model": mivolo_result.get("model"),
                "reason": mivolo_result.get("reason"),
                "request_path": mivolo_result.get("request_path"),
                "output_path": mivolo_result.get("output_path"),
                "hard_gate_age_basis": "raw_model_output",
                "person_offset_policy": "current_age_offset_advisory_only",
            },
            "consensus_policy": "both_models_when_secondary_available",
        },
        "parent_structure_metrics": parent_structure,
        "target_age": args.age,
        "thresholds": policy,
        "population_reference": {
            "biological_sex": plan.get("biological_sex", "unspecified"),
            "population_group": plan.get("population_group", "unspecified"),
            "status": "population_age_model_proxy_structure_uncalibrated",
            "note": (
                "Age likelihood comes from population-trained model views. "
                "Structure directions are advisory until a longitudinal "
                "demographic calibration cohort is installed."
            ),
        },
        "primary_photo": str(primary_path),
        "identity_pass_count": sum(row["identity_pass"] for row in rows),
        "insightface_age_pass_count": sum(
            row["insightface_age_range_pass"] for row in rows
        ),
        "mivolo_age_pass_count": sum(
            row["mivolo_age_range_pass"] is True for row in rows
        ),
        "age_model_disagreement_count": sum(
            row["age_consensus"]["model_agreement"] is False for row in rows
        ),
        "exact_age_pass_count": sum(row["age_range_pass"] for row in rows),
        "full_pass_count": sum(row["full_pass"] for row in rows),
        "borderline_pass_count": sum(
            row["full_pass"] and row["review_status"] == "borderline"
            for row in rows
        ),
        "rows": rows,
    }
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DEBUG_DIR / f"age{args.age:02d}_flux2_validation.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nPast-age candidate validation complete", flush=True)
    print(
        f"Strict identity passes: {summary['identity_pass_count']}/{len(rows)}",
        flush=True,
    )
    print(
        "InsightFace allowed-age passes: "
        f"{summary['insightface_age_pass_count']}/{len(rows)}",
        flush=True,
    )
    print(
        "MiVOLO allowed-age passes: "
        f"{summary['mivolo_age_pass_count']}/{len(rows)}",
        flush=True,
    )
    print(
        "Two-model consensus passes: "
        f"{summary['exact_age_pass_count']}/{len(rows)} | disagreements: "
        f"{summary['age_model_disagreement_count']}",
        flush=True,
    )
    print(
        "Legacy exact-age full-stage passes: "
        f"{summary['full_pass_count']}/{len(rows)}",
        flush=True,
    )
    print(
        "Morph-keyframe policy: exact-age results above are advisory; identity, "
        "relative direction, pose, and human structure review decide eligibility.",
        flush=True,
    )
    if not summary["full_pass_count"]:
        try:
            split_segment(parent_age, args.age)
        except ValueError:
            can_split = False
        else:
            can_split = True
        if can_split:
            print(
                f"Next action: keep the gates and split {parent_age}->{args.age} "
                "with POST /api/age-plan/refine.",
                flush=True,
            )
        else:
            print(
                "Next action: do not split this short stage. Keep identity strict, "
                "treat exact-age estimates as advisory, and adjust the biological "
                "structure-transfer recipe for human review.",
                flush=True,
            )
    print(f"Summary: {output_path}", flush=True)


if __name__ == "__main__":
    main()
