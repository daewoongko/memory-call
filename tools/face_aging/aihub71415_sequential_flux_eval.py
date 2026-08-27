"""Evaluate the product's selected-parent FLUX age path on one held-out person.

The generation phase never opens the person's real younger photographs.  It
creates six candidates per stage, adds at most two backfill candidates when
fewer than four pass basic validation, exposes four completed photographs, and
uses the highest ranked visible candidate as the next stage's parent.

After both the baseline and paired-age-adapter paths finish, ``evaluate`` opens
the sealed same-person age photographs and reports identity similarity.  Raw
AI Hub files stay in their licensed archives and every derived artifact is
written under ``data/experiments`` (gitignored).
"""

from __future__ import annotations

import argparse
import base64
import gc
import html
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import align_record_image  # noqa: E402
from face_quality import analyze_bytes  # noqa: E402


DEFAULT_MANIFEST = (
    ROOT / "data" / "experiments" / "face_dataset_audit" / "aihub71415_clean.jsonl"
)
DEFAULT_OUTPUT = ROOT / "data" / "experiments" / "aihub71415_sequential_flux_eval"
DEFAULT_ADAPTER = (
    ROOT
    / "data"
    / "experiments"
    / "aihub71415_paired_flux_pilot"
    / "lora"
    / "pytorch_lora_weights.safetensors"
)
DEFAULT_SCORE_PYTHON = ROOT / ".venv-age" / "Scripts" / "python.exe"
ANCHORS = (38, 32, 26, 20, 15, 11, 8)
TARGETS = ANCHORS[1:]
AGE_RANGES = {
    38: (36, 42),
    32: (29, 35),
    26: (23, 28),
    20: (18, 22),
    15: (13, 17),
    11: (10, 12),
    8: (6, 9),
}


def initial_batch_size(target_age: int) -> int:
    """Match the product budget: explore more broadly before age 26."""

    return 6 if target_age >= 26 else 4


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def archive_image(record: dict, *, size: int = 512):
    with ZipFile(record["image_archive_path"]) as archive:
        image, alignment = align_record_image(
            archive, record, width=size, height=size
        )
    return image, alignment


def archive_bytes(record: dict) -> bytes:
    """Read one licensed source image without extracting the archive."""

    with ZipFile(record["image_archive_path"]) as archive:
        return archive.read(record["image_member"])


def encode_png(path: Path, image) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"Could not encode {path}")
    encoded.tofile(path)


def nearest_record(rows: list[dict], anchor: int) -> dict:
    low, high = AGE_RANGES[anchor]
    candidates = [
        row for row in rows if low <= int(row["photo_age"]) <= high and row["has_image"]
    ]
    if not candidates:
        raise RuntimeError(f"No age-{anchor} record in held-out subject")
    return min(
        candidates,
        key=lambda row: (
            abs(int(row["photo_age"]) - anchor),
            str(row["record_id"]),
        ),
    )


def _metadata_source_score(row: dict) -> float:
    """Cheaply rank adult source frames before running YuNet.

    The score deliberately uses only the age-38 source.  Younger photographs
    remain sealed and cannot affect subject selection or candidate ranking.
    """

    width = max(float(row.get("width") or 1), 1.0)
    height = max(float(row.get("height") or 1), 1.0)
    box = row.get("box") or {}
    area_ratio = (
        max(float(box.get("w") or 0), 0.0)
        * max(float(box.get("h") or 0), 0.0)
        / (width * height)
    )
    center_x = (float(box.get("x") or 0) + float(box.get("w") or 0) / 2) / width
    center_y = (float(box.get("y") or 0) + float(box.get("h") or 0) / 2) / height
    center_penalty = math.hypot(center_x - 0.5, center_y - 0.47)
    useful_face = 1.0 - min(abs(area_ratio - 0.18) / 0.18, 1.0)
    resolution = min(min(width, height) / 1440.0, 1.0)
    return 45.0 * useful_face + 25.0 * resolution - 30.0 * center_penalty


def select_heldout_subject(rows: list[dict], requested: str) -> tuple[str, dict, dict]:
    """Select a leakage-safe test identity and a clean exact-age-38 source."""

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("split") == "test" and row.get("has_image"):
            grouped[str(row["subject_id"])].append(row)

    if requested != "auto":
        subject_rows = grouped.get(str(requested), [])
        if not subject_rows:
            raise RuntimeError(f"Held-out test subject {requested!r} was not found")
        selected = {anchor: nearest_record(subject_rows, anchor) for anchor in ANCHORS}
        exact_sources = [row for row in subject_rows if int(row["photo_age"]) == 38]
        if not exact_sources:
            raise RuntimeError("The evaluation source must contain an exact age-38 photo")
        source = max(exact_sources, key=_metadata_source_score)
        return str(requested), source, {"mode": "explicit", "quality": None}

    eligible: list[tuple[float, str, dict]] = []
    for subject_id, subject_rows in grouped.items():
        try:
            for anchor in ANCHORS:
                nearest_record(subject_rows, anchor)
        except RuntimeError:
            continue
        for source in subject_rows:
            if int(source["photo_age"]) == 38:
                eligible.append((_metadata_source_score(source), subject_id, source))
    if not eligible:
        raise RuntimeError("No test subject has an exact age-38 source and every anchor range")

    # Running YuNet over every archive frame is needlessly expensive.  The
    # metadata pass narrows the pool, then the actual image decides.
    inspected: list[dict] = []
    for metadata_score, subject_id, source in sorted(eligible, reverse=True)[:80]:
        try:
            quality = analyze_bytes(archive_bytes(source))
        except Exception as exc:
            inspected.append(
                {
                    "subject_id": subject_id,
                    "record_id": source["record_id"],
                    "eligible": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        face = quality.get("face") or {}
        source_score = (
            float(quality["score"])
            + (10.0 if quality["status"] == "good" else 0.0)
            + min(float(quality["sharpness"]), 240.0) / 24.0
            - 18.0 * max(float(face.get("center_offset") or 0.0) - 0.12, 0.0)
            + 0.05 * metadata_score
        )
        inspected.append(
            {
                "subject_id": subject_id,
                "record_id": source["record_id"],
                "eligible": bool(quality["usable"] and quality["face_count"] == 1),
                "source_score": round(source_score, 4),
                "metadata_score": round(metadata_score, 4),
                "quality": quality,
                "record": source,
            }
        )
    usable = [item for item in inspected if item.get("eligible")]
    if not usable:
        raise RuntimeError("No automatically inspected age-38 source passed face quality")
    winner = max(usable, key=lambda item: (item["source_score"], item["record_id"]))
    reason = {
        "mode": "auto",
        "eligible_subjects": len({item[1] for item in eligible}),
        "adult_sources_considered": len(eligible),
        "adult_sources_visually_inspected": len(inspected),
        "source_score": winner["source_score"],
        "quality": winner["quality"],
    }
    return winner["subject_id"], winner["record"], reason


def prepare(args: argparse.Namespace) -> None:
    all_rows = read_jsonl(args.manifest)
    subject_id, source_record, selection = select_heldout_subject(
        all_rows, str(args.subject_id)
    )
    subject_rows = [
        row
        for row in all_rows
        if str(row["subject_id"]) == subject_id
        and row.get("split") == "test"
        and row.get("has_image")
    ]
    selected = {anchor: nearest_record(subject_rows, anchor) for anchor in ANCHORS}
    selected[38] = source_record

    source_image, source_alignment = archive_image(source_record)
    source_path = args.output / "source" / "age38.png"
    encode_png(source_path, source_image)
    sealed = {
        str(anchor): {
            "record": selected[anchor],
            "opened": anchor == 38,
        }
        for anchor in ANCHORS
    }
    manifest = {
        "version": 1,
        "dataset": "AI Hub 71415",
        "subject_id": subject_id,
        "split": "test",
        "heldout_source_selection": selection,
        "source": {
            "anchor": 38,
            "actual_photo_age": int(source_record["photo_age"]),
            "path": str(source_path.relative_to(args.output)),
            "alignment": source_alignment,
        },
        "sealed_targets": sealed,
        "target_opening_policy": (
            "Generation and automatic ranking may not read sealed_targets. "
            "Only the evaluate command may extract them."
        ),
        "recipes": ["baseline", "paired_adapter"],
        "initial_candidates": 6,
        "maximum_candidates": 8,
        "visible_candidates": 4,
    }
    write_json(args.output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "subject_id": subject_id,
                "source_age": 38,
                "sealed_target_ages": list(TARGETS),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def make_mask(size: int):
    from PIL import Image, ImageDraw, ImageFilter

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((65, 35, size - 65, size - 30), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=12))


def generate_candidate(
    pipeline,
    *,
    parent_path: Path,
    source_path: Path,
    parent_age: int,
    target_age: int,
    seed: int,
    output_path: Path,
):
    import torch
    from PIL import Image

    from age_generate_flux2 import (
        build_prompt,
        edit_strength_for_gap,
        prepare_image,
    )

    parent = prepare_image(parent_path, 512, 512)
    source = prepare_image(source_path, 512, 512)
    prompt = build_prompt(
        target_age,
        2,
        None,
        "Korean person",
        parent_age,
        False,
        "base",
    )
    result = pipeline(
        prompt=prompt,
        image=parent,
        image_reference=[source],
        mask_image=make_mask(512),
        strength=edit_strength_for_gap(parent_age - target_age),
        height=512,
        width=512,
        num_inference_steps=8,
        guidance_scale=1.0,
        generator=torch.Generator(device="cpu").manual_seed(seed),
    ).images[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    if not isinstance(result, Image.Image):
        raise RuntimeError("FLUX did not return a completed photograph")


def run_score_subprocess(args: argparse.Namespace, stage_dir: Path) -> dict:
    command = [
        str(args.score_python),
        str(Path(__file__).resolve()),
        "score",
        "--output",
        str(args.output),
        "--stage-dir",
        str(stage_dir),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return json.loads((stage_dir / "ranking.json").read_text(encoding="utf-8"))


def generate_recipe(args: argparse.Namespace, recipe: str) -> dict:
    import torch

    from age_generate_flux2 import build_pipeline

    manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
    source_path = args.output / manifest["source"]["path"]
    adapter = args.adapter if recipe == "paired_adapter" else None
    if adapter is not None and not adapter.is_file():
        raise FileNotFoundError(f"Paired age adapter is not ready: {adapter}")

    pipeline = build_pipeline(
        child_lora_path=adapter,
        child_lora_scale=args.adapter_scale,
    )
    adapter_target_ages = set(args.adapter_target_ages)
    parent_path = source_path
    parent_age = 38
    stage_reports: list[dict] = []
    try:
        for stage_index, target_age in enumerate(TARGETS):
            adapter_enabled = bool(adapter) and target_age in adapter_target_ages
            if adapter is not None:
                if adapter_enabled:
                    pipeline.enable_lora()
                    pipeline.set_adapters(
                        ["child_evidence"],
                        adapter_weights=[args.adapter_scale],
                    )
                else:
                    pipeline.disable_lora()
            stage_dir = args.output / "generated" / recipe / f"age{target_age:02d}"
            stage_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            initial_count = initial_batch_size(target_age)
            for index in range(initial_count):
                seed = args.seed + stage_index * 100 + index
                output_path = stage_dir / f"candidate_{index + 1:02d}_seed{seed}.png"
                if not output_path.is_file():
                    generate_candidate(
                        pipeline,
                        parent_path=parent_path,
                        source_path=source_path,
                        parent_age=parent_age,
                        target_age=target_age,
                        seed=seed,
                        output_path=output_path,
                    )

            ranking = run_score_subprocess(args, stage_dir)
            next_index = initial_count
            while len(ranking["valid_ranked"]) < 4 and next_index < 8:
                seed = args.seed + stage_index * 100 + next_index
                generate_candidate(
                    pipeline,
                    parent_path=parent_path,
                    source_path=source_path,
                    parent_age=parent_age,
                    target_age=target_age,
                    seed=seed,
                    output_path=stage_dir / f"candidate_{next_index + 1:02d}_seed{seed}.png",
                )
                next_index += 1
                ranking = run_score_subprocess(args, stage_dir)

            visible = ranking["valid_ranked"][:4]
            if not visible:
                raise RuntimeError(f"No valid completed age-{target_age} photograph")
            selected = stage_dir / visible[0]["filename"]
            stage_reports.append(
                {
                    "parent_age": parent_age,
                    "target_age": target_age,
                    "adapter_enabled": adapter_enabled,
                    "generated": next_index,
                    "visible": visible,
                    "automatic_next_parent": str(selected.relative_to(args.output)),
                    "seconds": round(time.perf_counter() - started, 2),
                }
            )
            parent_path = selected
            parent_age = target_age
            print(
                f"{recipe}: {stage_reports[-1]['parent_age']} -> {target_age}, "
                f"{len(visible)} visible, {stage_reports[-1]['seconds']}s",
                flush=True,
            )
    finally:
        del pipeline
        gc.collect()
        torch.cuda.empty_cache()
    report = {
        "recipe": recipe,
        "hidden_targets_opened": False,
        "adapter": str(adapter) if adapter else None,
        "adapter_scale": args.adapter_scale if adapter else None,
        "adapter_target_ages": sorted(adapter_target_ages, reverse=True) if adapter else [],
        "stages": stage_reports,
    }
    write_json(args.output / f"generation_{recipe}.json", report)
    return report


def score(args: argparse.Namespace) -> None:
    import cv2
    import numpy as np

    from age_validate_flux2 import (
        age_views,
        estimate_age_votes,
        largest_face,
        make_analyzer,
        read_rgb,
    )

    stage_dir = args.stage_dir.resolve()
    target_age = int(stage_dir.name.removeprefix("age"))
    recipe = stage_dir.parent.name
    generation_path = args.output / f"generation_{recipe}.json"
    source_path = args.output / "source" / "age38.png"
    if generation_path.exists():
        previous = json.loads(generation_path.read_text(encoding="utf-8"))
        stages = previous.get("stages") or []
        parent_path = (
            args.output / stages[-1]["automatic_next_parent"] if stages else source_path
        )
    else:
        previous_targets = [age for age in TARGETS if age > target_age]
        if previous_targets:
            previous_ranking = (
                args.output
                / "generated"
                / recipe
                / f"age{previous_targets[-1]:02d}"
                / "ranking.json"
            )
            if previous_ranking.exists():
                prior = json.loads(previous_ranking.read_text(encoding="utf-8"))
                parent_path = previous_ranking.parent / prior["valid_ranked"][0]["filename"]
            else:
                parent_path = source_path
        else:
            parent_path = source_path

    identity_app = make_analyzer("buffalo_l", include_age=False)
    age_app = make_analyzer("antelopev2", include_age=True)
    source_rgb = read_rgb(source_path)
    parent_rgb = read_rgb(parent_path)
    source_face = largest_face(identity_app, source_rgb)
    parent_face = largest_face(identity_app, parent_rgb)
    rows: list[dict] = []
    for path in sorted(stage_dir.glob("*.png")):
        try:
            rgb = read_rgb(path)
            face = largest_face(identity_app, rgb)
            age_votes = estimate_age_votes(age_app, rgb)
            estimated_age = float(np.median(age_votes))
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            brightness = float(gray.mean())
            source_similarity = float(
                source_face.normed_embedding @ face.normed_embedding
            )
            parent_similarity = float(
                parent_face.normed_embedding @ face.normed_embedding
            )
            age_fit = max(0.0, 1.0 - abs(estimated_age - target_age) / 20.0)
            quality_fit = min(1.0, sharpness / 120.0)
            valid = (
                35 <= brightness <= 225
                and sharpness >= 20
                and source_similarity >= 0.15
                and parent_similarity >= 0.20
            )
            rank_score = (
                0.45 * source_similarity
                + 0.25 * parent_similarity
                + 0.25 * age_fit
                + 0.05 * quality_fit
            )
            rows.append(
                {
                    "filename": path.name,
                    "valid": valid,
                    "rank_score": round(rank_score, 6),
                    "source_similarity": round(source_similarity, 5),
                    "parent_similarity": round(parent_similarity, 5),
                    "estimated_age": round(estimated_age, 2),
                    "age_error": round(abs(estimated_age - target_age), 2),
                    "sharpness": round(sharpness, 2),
                    "brightness": round(brightness, 2),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "filename": path.name,
                    "valid": False,
                    "rank_score": -1,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    ranked = sorted(rows, key=lambda row: (-float(row["rank_score"]), row["filename"]))
    valid_ranked = [row for row in ranked if row["valid"]]
    report = {
        "target_age": target_age,
        "source": str(source_path),
        "parent": str(parent_path),
        "selection_did_not_use_hidden_target": True,
        "weights": {
            "adult_source_identity": 0.45,
            "adjacent_parent_identity": 0.25,
            "target_age_fit": 0.25,
            "image_quality": 0.05,
        },
        "valid_ranked": valid_ranked,
        "all_ranked": ranked,
    }
    write_json(stage_dir / "ranking.json", report)
    print(json.dumps(report, ensure_ascii=False))


def extract_hidden_targets(args: argparse.Namespace, manifest: dict) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for target_age in TARGETS:
        sealed = manifest["sealed_targets"][str(target_age)]
        image, _alignment = archive_image(sealed["record"])
        path = args.output / "evaluation_only" / f"age{target_age:02d}.png"
        encode_png(path, image)
        paths[target_age] = path
    return paths


def image_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def evaluate(args: argparse.Namespace) -> None:
    import numpy as np

    from age_validate_flux2 import largest_face, make_analyzer, read_rgb

    manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
    reports = {
        recipe: json.loads(
            (args.output / f"generation_{recipe}.json").read_text(encoding="utf-8")
        )
        for recipe in manifest["recipes"]
    }
    hidden_paths = extract_hidden_targets(args, manifest)
    identity_app = make_analyzer("buffalo_l", include_age=False)
    hidden_embeddings = {
        age: largest_face(identity_app, read_rgb(path)).normed_embedding
        for age, path in hidden_paths.items()
    }
    metrics: list[dict] = []
    for recipe, report in reports.items():
        for stage in report["stages"]:
            age = int(stage["target_age"])
            stage_dir = args.output / "generated" / recipe / f"age{age:02d}"
            for rank, row in enumerate(stage["visible"], start=1):
                candidate_path = stage_dir / row["filename"]
                embedding = largest_face(
                    identity_app, read_rgb(candidate_path)
                ).normed_embedding
                metrics.append(
                    {
                        "recipe": recipe,
                        "target_age": age,
                        "visible_rank": rank,
                        "filename": row["filename"],
                        "estimated_age": float(row["estimated_age"]),
                        "target_age_error": round(
                            abs(float(row["estimated_age"]) - age), 6
                        ),
                        "identity_to_hidden_same_age": round(
                            float(embedding @ hidden_embeddings[age]), 6
                        ),
                        "automatic_selected_for_next_stage": rank == 1,
                    }
                )

    summary = {}
    for recipe in manifest["recipes"]:
        recipe_rows = [row for row in metrics if row["recipe"] == recipe]
        selected = [
            row for row in recipe_rows if row["automatic_selected_for_next_stage"]
        ]
        summary[recipe] = {
            "selected_hidden_identity_mean": round(
                float(np.mean([row["identity_to_hidden_same_age"] for row in selected])),
                6,
            ),
            "top4_hidden_identity_mean": round(
                float(
                    np.mean(
                        [row["identity_to_hidden_same_age"] for row in recipe_rows]
                    )
                ),
                6,
            ),
            "selected_target_age_mae": round(
                float(np.mean([row["target_age_error"] for row in selected])),
                6,
            ),
            "top4_target_age_mae": round(
                float(np.mean([row["target_age_error"] for row in recipe_rows])),
                6,
            ),
        }
    report = {
        "version": 1,
        "subject_id": manifest["subject_id"],
        "targets_opened_only_after_generation": True,
        "summary": summary,
        "metrics": metrics,
    }
    write_json(args.output / "evaluation_report.json", report)
    write_review(args, manifest, reports, hidden_paths, metrics, summary)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def write_review(
    args: argparse.Namespace,
    manifest: dict,
    reports: dict[str, dict],
    hidden_paths: dict[int, Path],
    metrics: list[dict],
    summary: dict,
) -> None:
    sections: list[str] = []
    labels = {"baseline": "기존 순차 생성", "paired_adapter": "연령 LoRA 적용"}
    for age in TARGETS:
        recipe_blocks: list[str] = []
        for recipe in manifest["recipes"]:
            stage = next(
                row for row in reports[recipe]["stages"] if int(row["target_age"]) == age
            )
            figures: list[str] = []
            stage_dir = args.output / "generated" / recipe / f"age{age:02d}"
            for rank, row in enumerate(stage["visible"], start=1):
                metric = next(
                    item
                    for item in metrics
                    if item["recipe"] == recipe
                    and item["target_age"] == age
                    and item["visible_rank"] == rank
                )
                figures.append(
                    '<figure><img src="'
                    + image_uri(stage_dir / row["filename"])
                    + f'"><figcaption>{rank}위 · 추정 {row["estimated_age"]}세'
                    + f' · 목표 오차 {metric["target_age_error"]:.1f}세'
                    + f' · 정답 신원 {metric["identity_to_hidden_same_age"]:.3f}'
                    + (" · 다음 입력" if rank == 1 else "")
                    + "</figcaption></figure>"
                )
            recipe_blocks.append(
                f'<div class="recipe"><h3>{labels[recipe]}</h3><div class="grid">'
                + "".join(figures)
                + "</div></div>"
            )
        sections.append(
            f'<section><h2>{age}세 후보</h2><div class="recipes">'
            + "".join(recipe_blocks)
            + '</div><details><summary>평가용 실제 사진 보기</summary><img class="truth" src="'
            + image_uri(hidden_paths[age])
            + '"></details></section>'
        )
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>순차 연령 생성 비교</title><style>
body{{margin:0;background:#f4f3ec;color:#10291f;font-family:system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:32px}}h1{{font-size:38px}}
.summary,section{{background:#fff;border:1px solid #b8c8be;border-radius:24px;padding:24px;margin:22px 0}}
.recipes{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}.recipe{{min-width:0}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
figure{{margin:0}}figure img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:16px;border:2px solid #d9e2dc}}
figcaption{{font-size:13px;line-height:1.4;margin-top:8px}}details{{margin-top:18px}}
.truth{{width:220px;border-radius:16px;margin-top:12px}}@media(max-width:900px){{.recipes{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style><main><h1>학습 미사용 1인 · 순차 생성 비교</h1>
<div class="summary">생성 중 실제 과거 사진은 사용하지 않았습니다. 상위 4장은 현재·직전 사진 신원, 목표 연령, 품질로만 골랐고 실제 사진은 마지막 평가에서 열었습니다.<br>
기존 선택 사진 평균 {summary['baseline']['selected_hidden_identity_mean']:.3f} · 연령 LoRA {summary['paired_adapter']['selected_hidden_identity_mean']:.3f}</div>
<div class="summary">선택 사진 목표 연령 MAE: 기존 {summary['baseline']['selected_target_age_mae']:.2f}세 · 연령 LoRA {summary['paired_adapter']['selected_target_age_mae']:.2f}세<br>
신원 유사도는 높을수록, 목표 연령 MAE는 낮을수록 좋습니다.</div>
{''.join(sections)}</main></html>"""
    review_path = args.output / "review" / "index.html"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(page, encoding="utf-8")
    print(f"Review: {review_path}")


def status(args: argparse.Namespace) -> None:
    paths = {
        "manifest": args.output / "manifest.json",
        "baseline": args.output / "generation_baseline.json",
        "paired_adapter": args.output / "generation_paired_adapter.json",
        "evaluation": args.output / "evaluation_report.json",
        "review": args.output / "review" / "index.html",
    }
    print(json.dumps({key: path.exists() for key, path in paths.items()}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("prepare", "generate-baseline", "generate-adapted", "score", "evaluate", "status"),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--adapter-scale", type=float, default=0.35)
    parser.add_argument(
        "--adapter-target-ages",
        default="15,11,8",
        help="Comma-separated target ages where the paired-age adapter is enabled.",
    )
    parser.add_argument("--score-python", type=Path, default=DEFAULT_SCORE_PYTHON)
    parser.add_argument(
        "--subject-id",
        default="auto",
        help="test subject id, or 'auto' for a clean exact-age-38 held-out source",
    )
    parser.add_argument("--seed", type=int, default=971500)
    parser.add_argument("--stage-dir", type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.manifest = args.manifest.resolve()
    args.adapter = args.adapter.resolve()
    try:
        args.adapter_target_ages = tuple(
            int(value.strip())
            for value in args.adapter_target_ages.split(",")
            if value.strip()
        )
    except ValueError as exc:
        parser.error(f"--adapter-target-ages must contain integers: {exc}")
    unknown_adapter_ages = set(args.adapter_target_ages) - set(TARGETS)
    if unknown_adapter_ages:
        parser.error(
            "--adapter-target-ages contains ages outside the evaluation path: "
            + ", ".join(str(age) for age in sorted(unknown_adapter_ages))
        )
    args.score_python = args.score_python.resolve()
    if args.command == "score" and args.stage_dir is None:
        parser.error("score requires --stage-dir")
    return args


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "generate-baseline":
        generate_recipe(args, "baseline")
    elif args.command == "generate-adapted":
        generate_recipe(args, "paired_adapter")
    elif args.command == "score":
        score(args)
    elif args.command == "evaluate":
        evaluate(args)
    else:
        status(args)


if __name__ == "__main__":
    main()
