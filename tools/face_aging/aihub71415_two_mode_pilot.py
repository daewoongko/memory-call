"""Build a leakage-safe, quality-gated age-8 two-mode pilot.

The two product modes are intentionally separated by person.

``adult_only``
    Identity training sees adult portraits only. Every exact-age-8 portrait is
    sealed until evaluation.

``childhood_assisted``
    Adult portraits train an identity adapter. A *different* child-evidence
    adapter may use quality-approved age-8 portraits, while at least one
    quality-approved age-8 portrait remains sealed for evaluation.

The script does not pretend that five landmarks can detect every bad historic
photo. Automatic acquisition checks are therefore combined with an explicit
human-review override file. Rejected/reference-only photographs never enter a
LoRA training directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import align_record_image, read_jsonl  # noqa: E402


EXPERIMENT = ROOT / "data" / "experiments" / "aihub71415_full"
DEFAULT_OUTPUT = EXPERIMENT / "two_mode_pilot_v2"
# 0899 was removed: its only hidden age-8 face was about 70 px and was not a
# defensible visual target. These defaults have large, near-frontal age-8 data.
DEFAULT_ADULT_ONLY = ("0651", "0753")
DEFAULT_ASSISTED = ("0137",)
MODELS_ROOT = Path(
    os.environ.get("MEMORY_CALL_MODELS_DIR", Path.home() / "Models")
).expanduser().resolve()
TRAINING_TOOLS_ROOT = Path(
    os.environ.get("MEMORY_CALL_TRAINING_TOOLS_DIR", ROOT.parent / "Models")
).expanduser().resolve()
TRAIN_SCRIPT = (
    TRAINING_TOOLS_ROOT
    / "diffusers-flux2-train"
    / "examples"
    / "dreambooth"
    / "train_dreambooth_lora_flux2_klein.py"
)
FLUX_MODEL = Path(os.environ.get("FLUX_MODEL_PATH", MODELS_ROOT / "FLUX2-klein-base-4B"))

# These records were visually reviewed during the pilot. They are deliberately
# scoped to this experiment instead of being presented as a general detector.
BUILTIN_HUMAN_OVERRIDES = {
    "0e322b9f": {"status": "reject", "reason": "손가락 가림과 매우 낮은 선명도"},
    "27e27018": {"status": "reference_only", "reason": "낮은 선명도"},
    "e6c3923c": {"status": "reference_only", "reason": "큰 기울기와 표정 차이"},
    "e573e1fe": {"status": "reference_only", "reason": "작은 얼굴과 낮은 선명도"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("prepare", "audit", "train-identity", "train-child-evidence", "train-assisted"),
    )
    parser.add_argument("--manifest", type=Path, default=EXPERIMENT / "index" / "manifest.jsonl")
    parser.add_argument("--holdouts", type=Path, default=EXPERIMENT / "pairs" / "age8_holdouts.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quality-overrides", type=Path)
    parser.add_argument("--adult-only-subjects", nargs="+", default=list(DEFAULT_ADULT_ONLY))
    parser.add_argument("--assisted-subjects", nargs="+", default=list(DEFAULT_ASSISTED))
    parser.add_argument("--assisted-age8-train-count", type=int, default=2)
    parser.add_argument("--adult-train-count", type=int, default=5)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument(
        "--case-id",
        help="Train only one prepared case. Omit only for an intentional batch run.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def record_digest(record: dict) -> str:
    value = f"{record['subject_id']}:{record['record_id']}:{record['photo_age']}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def select_spread(rows: list[dict], count: int) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (int(row["photo_age"]), row["record_id"]))
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[-1]]
    indexes = {round(index * (len(ordered) - 1) / (count - 1)) for index in range(count)}
    return [ordered[index] for index in sorted(indexes)]


def aligned_bgr(record: dict, size: int = 512):
    from zipfile import ZipFile

    with ZipFile(Path(record["image_archive_path"])) as archive:
        return align_record_image(archive, record, width=size, height=size)


def pose_metrics(record: dict) -> tuple[float, float]:
    landmarks = record["landmarks"]
    nose, left_eye, right_eye = landmarks[0], landmarks[1], landmarks[2]
    roll = abs(
        math.degrees(
            math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0])
        )
    )
    eye_distance = max(1.0, abs(right_eye[0] - left_eye[0]))
    yaw_proxy = abs(nose[0] - (left_eye[0] + right_eye[0]) / 2.0) / eye_distance
    return round(roll, 3), round(yaw_proxy, 4)


def automatic_quality(record: dict) -> dict:
    import cv2
    import numpy as np

    bgr, alignment = aligned_bgr(record)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    face_min_px = float(min(record["box"]["w"], record["box"]["h"]))
    roll, yaw_proxy = pose_metrics(record)

    hard_reasons: list[str] = []
    soft_reasons: list[str] = []
    if face_min_px < 110:
        hard_reasons.append("원본 얼굴이 110px보다 작음")
    if sharpness < 5:
        hard_reasons.append("심한 흐림")
    if brightness < 35 or brightness > 225:
        hard_reasons.append("심한 노출 문제")
    if contrast < 20:
        hard_reasons.append("대비가 매우 낮음")
    if roll > 20:
        hard_reasons.append("얼굴 기울기가 20도를 넘음")
    if yaw_proxy > 0.25:
        hard_reasons.append("얼굴이 크게 돌아가 있음")

    if face_min_px < 160:
        soft_reasons.append("원본 얼굴이 작음")
    if sharpness < 18:
        soft_reasons.append("선명도가 낮음")
    if brightness < 55 or brightness > 205:
        soft_reasons.append("노출 보정이 필요함")
    if contrast < 30:
        soft_reasons.append("대비가 낮음")
    if roll > 10:
        soft_reasons.append("얼굴 기울기가 큼")
    if yaw_proxy > 0.15:
        soft_reasons.append("정면성이 낮음")
    alignment_error = float(alignment.get("normalized_landmark_error") or 0.0)
    if alignment_error > 0.12:
        soft_reasons.append("랜드마크 정렬 오차가 큼")

    status = "reject" if hard_reasons else "reference_only" if soft_reasons else "train_primary"
    # Ranking only; it is not a calibrated probability or a model score.
    score = 100.0
    score -= min(35.0, max(0.0, 18.0 - sharpness) * 1.4)
    score -= min(20.0, abs(brightness - 128.0) * 0.12)
    score -= min(15.0, max(0.0, 30.0 - contrast) * 0.75)
    score -= min(15.0, roll * 0.75)
    score -= min(15.0, yaw_proxy * 60.0)
    score += min(5.0, max(0.0, face_min_px - 160.0) / 160.0)
    return {
        "status": status,
        "score": round(max(0.0, min(100.0, score)), 2),
        "hard_reasons": hard_reasons,
        "soft_reasons": soft_reasons,
        "metrics": {
            "source_face_min_px": round(face_min_px, 1),
            "aligned_sharpness": round(sharpness, 2),
            "aligned_brightness": round(brightness, 2),
            "aligned_contrast": round(contrast, 2),
            "absolute_roll_degrees": roll,
            "yaw_proxy": yaw_proxy,
            "normalized_landmark_error": round(alignment_error, 5),
        },
        "alignment": alignment,
    }


def load_overrides(path: Path | None) -> dict[str, dict]:
    overrides = dict(BUILTIN_HUMAN_OVERRIDES)
    if path and path.is_file():
        custom = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("quality override file must contain an object keyed by record_id")
        overrides.update(custom)
    return overrides


def assess(record: dict, overrides: dict[str, dict]) -> dict:
    result = automatic_quality(record)
    override = overrides.get(record["record_id"]) or overrides.get(record["record_id"][:8])
    if override:
        status = str(override.get("status") or "").strip()
        if status not in {"train_primary", "reference_only", "reject"}:
            raise ValueError(f"Invalid human quality status for {record['record_id']}: {status}")
        result["status"] = status
        result["human_review"] = {
            "applied": True,
            "reason": str(override.get("reason") or "사람 검수 결과"),
        }
    else:
        result["human_review"] = {
            "applied": False,
            "reason": "가림·표정·복잡한 배경은 별도 사람 검수가 필요함",
        }
    return result


def quality_row(record: dict, quality: dict) -> dict:
    return {
        "record_id": record["record_id"],
        "photo_age": int(record["photo_age"]),
        "status": quality["status"],
        "score": quality["score"],
        "hard_reasons": quality["hard_reasons"],
        "soft_reasons": quality["soft_reasons"],
        "human_review": quality["human_review"],
        "metrics": quality["metrics"],
        "source_digest": record_digest(record),
    }


def save_training_image(output: Path, directory: Path, record: dict, label: str, quality: dict) -> dict:
    import cv2
    from PIL import Image

    if quality["status"] != "train_primary":
        raise RuntimeError(f"Refusing to train on non-primary record {record['record_id']}")
    bgr, alignment = aligned_bgr(record)
    filename = f"{label}_age{int(record['photo_age']):02d}_{record['record_id'][:8]}.png"
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).save(path)
    row = quality_row(record, quality)
    row.update({"path": path.relative_to(output).as_posix(), "alignment": alignment})
    return row


def load_rows(args: argparse.Namespace) -> list[dict]:
    # holdouts is retained in the CLI for compatibility with older commands;
    # the v2 split is rebuilt from the full record manifest after quality gates.
    return list(read_jsonl(args.manifest))


def choose_primary(records: list[dict], qualities: dict[str, dict], count: int) -> list[dict]:
    primary = [row for row in records if qualities[row["record_id"]]["status"] == "train_primary"]
    return sorted(primary, key=lambda row: (-qualities[row["record_id"]]["score"], row["record_id"]))[:count]


def prepare(args: argparse.Namespace) -> None:
    if args.assisted_age8_train_count < 1:
        raise ValueError("--assisted-age8-train-count must be at least 1")
    adult_subjects = tuple(map(str, args.adult_only_subjects))
    assisted_subjects = tuple(map(str, args.assisted_subjects))
    overlap = sorted(set(adult_subjects).intersection(assisted_subjects))
    if overlap:
        raise ValueError(f"A person cannot be in both modes: {', '.join(overlap)}")

    records = load_rows(args)
    overrides = load_overrides(args.quality_overrides)
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_subject[str(record["subject_id"])].append(record)

    output = args.output.resolve()
    cases: list[dict] = []
    for mode, subject_ids in (("adult_only", adult_subjects), ("childhood_assisted", assisted_subjects)):
        for subject_id in subject_ids:
            rows = by_subject.get(subject_id) or []
            exact8 = [row for row in rows if int(row["photo_age"]) == 8]
            adults = [row for row in rows if int(row["photo_age"]) >= 18]
            if not rows or not adults or not exact8:
                raise ValueError(f"Subject {subject_id} lacks adult or exact-age-8 data")

            # Assess a broad age-spread adult pool and all exact-age-8 records.
            adult_pool = select_spread(adults, max(args.adult_train_count * 3, args.adult_train_count))
            assessed_records = {row["record_id"]: row for row in [*adult_pool, *exact8]}
            qualities = {rid: assess(row, overrides) for rid, row in assessed_records.items()}
            adult_training = choose_primary(adult_pool, qualities, args.adult_train_count)
            child_primary = choose_primary(exact8, qualities, len(exact8))
            if len(adult_training) < 2:
                raise ValueError(f"Subject {subject_id} has fewer than two primary adult portraits")
            if not child_primary:
                raise ValueError(f"Subject {subject_id} has no quality-approved age-8 evaluation target")

            case_id = f"{mode}_{subject_id}"
            case_dir = output / "cases" / case_id
            identity_inputs = [
                save_training_image(
                    output,
                    case_dir / "identity_inputs",
                    row,
                    "adult",
                    qualities[row["record_id"]],
                )
                for row in adult_training
            ]

            child_inputs: list[dict] = []
            if mode == "childhood_assisted":
                required = args.assisted_age8_train_count + 1
                if len(child_primary) < required:
                    raise ValueError(
                        f"Assisted subject {subject_id} needs {required} quality-approved age-8 "
                        f"portraits; found {len(child_primary)}"
                    )
                child_train = child_primary[: args.assisted_age8_train_count]
                sealed_primary = child_primary[args.assisted_age8_train_count :]
                child_inputs = [
                    save_training_image(
                        output,
                        case_dir / "child_evidence_inputs",
                        row,
                        "child",
                        qualities[row["record_id"]],
                    )
                    for row in child_train
                ]
            else:
                sealed_primary = child_primary

            sealed_ids = {row["record_id"] for row in sealed_primary}
            quality_report = [
                quality_row(row, qualities[row["record_id"]])
                for row in sorted(assessed_records.values(), key=lambda item: (int(item["photo_age"]), item["record_id"]))
            ]
            final_target = max(sealed_primary, key=lambda row: qualities[row["record_id"]]["score"])
            parent = max(identity_inputs, key=lambda row: (row["photo_age"], row["score"]))
            gender = str(next(row for row in adult_training if row["record_id"] == parent["record_id"]).get("gender") or "unspecified")
            cases.append(
                {
                    "case_id": case_id,
                    "mode": mode,
                    "subject_id": subject_id,
                    "gender": gender,
                    "target_age": 8,
                    "identity_token": f"mc{subject_id}person",
                    "identity_inputs": identity_inputs,
                    "child_evidence_inputs": child_inputs,
                    "accepted_parent": parent,
                    "sealed_evaluation_targets": [
                        {
                            **quality_row(row, qualities[row["record_id"]]),
                            "image_extracted": False,
                        }
                        for row in sealed_primary
                    ],
                    "final_evaluation_target_record_id": final_target["record_id"],
                    "quality_report": quality_report,
                    "identity_lora_output": (case_dir / "identity_lora").relative_to(output).as_posix(),
                    "child_evidence_lora_output": (case_dir / "child_evidence_lora").relative_to(output).as_posix(),
                    "quality_policy": {
                        "training_accepts": ["train_primary"],
                        "reference_only_is_trained": False,
                        "reject_is_trained": False,
                        "sealed_record_ids": sorted(sealed_ids),
                    },
                }
            )

    manifest = {
        "version": 2,
        "experiment": "quality_gated_person_disjoint_two_mode_age8_pilot",
        "target_age": 8,
        "adult_only_definition": "identity LoRA sees adult portraits only; all exact-age-8 portraits stay sealed",
        "childhood_assisted_definition": "adult identity and child evidence use separate LoRAs; different quality-approved age-8 portraits stay sealed",
        "comparison_warning": "People differ between modes, so results compare product scenarios rather than estimate a causal effect.",
        "quality_warning": "Automatic gates do not reliably detect occlusion, expression, or background leakage; human review is recorded separately.",
        "adult_only_subjects": list(adult_subjects),
        "childhood_assisted_subjects": list(assisted_subjects),
        "cases": cases,
    }
    write_json(output / "two_mode_manifest.json", manifest)
    if not args.quality_overrides:
        write_json(
            output / "quality_overrides.template.json",
            {
                "record_id": {
                    "status": "reference_only",
                    "reason": "예: 손·안경 가림, 과한 표정, 복잡한 배경",
                }
            },
        )
    audit(output / "two_mode_manifest.json")
    print(f"Prepared {len(cases)} quality-gated cases in {output}")
    for case in cases:
        print(
            f"  {case['case_id']}: identity {len(case['identity_inputs'])}, "
            f"child evidence {len(case['child_evidence_inputs'])}, "
            f"sealed {len(case['sealed_evaluation_targets'])}"
        )
    print("Sealed age-8 evaluation photographs were not extracted.")


def audit(path: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    adult_subjects = set(map(str, manifest["adult_only_subjects"]))
    assisted_subjects = set(map(str, manifest["childhood_assisted_subjects"]))
    if adult_subjects.intersection(assisted_subjects):
        raise RuntimeError("Subject leakage between product modes")
    seen_training_ids: set[str] = set()
    seen_sealed_ids: set[str] = set()
    for case in manifest["cases"]:
        identity = case["identity_inputs"]
        child = case["child_evidence_inputs"]
        training = [*identity, *child]
        sealed = case["sealed_evaluation_targets"]
        training_ids = {row["record_id"] for row in training}
        sealed_ids = {row["record_id"] for row in sealed}
        if training_ids.intersection(sealed_ids):
            raise RuntimeError(f"Target leakage in {case['case_id']}")
        if not sealed_ids:
            raise RuntimeError(f"No sealed evaluation image in {case['case_id']}")
        if any(row.get("image_extracted") for row in sealed):
            raise RuntimeError(f"Sealed image was extracted in {case['case_id']}")
        if any(row["status"] != "train_primary" for row in training):
            raise RuntimeError(f"Non-primary image entered training in {case['case_id']}")
        if any(int(row["photo_age"]) < 18 for row in identity):
            raise RuntimeError(f"Child image leaked into identity adapter in {case['case_id']}")
        if case["mode"] == "adult_only" and child:
            raise RuntimeError(f"Child evidence leaked into adult-only case {case['case_id']}")
        if case["mode"] == "childhood_assisted" and not child:
            raise RuntimeError(f"No child evidence in assisted case {case['case_id']}")
        if case["final_evaluation_target_record_id"] not in sealed_ids:
            raise RuntimeError(f"Final target is not sealed in {case['case_id']}")
        seen_training_ids.update(training_ids)
        seen_sealed_ids.update(sealed_ids)
    if seen_training_ids.intersection(seen_sealed_ids):
        raise RuntimeError("Cross-case train/evaluation leakage")
    print(f"Audit passed: {len(manifest['cases'])} cases, no quality or target leakage")


def training_command(args: argparse.Namespace, case: dict, output: Path, kind: str) -> list[str]:
    python = ROOT / ".venv-flux2" / "Scripts" / "python.exe"
    case_dir = output / "cases" / case["case_id"]
    gender = "woman" if case["gender"] == "female" else "man"
    if kind == "identity":
        input_dir = case_dir / "identity_inputs"
        lora_dir = output / case["identity_lora_output"]
        prompt = f"portrait photo of {case['identity_token']}, a Korean {gender}"
    else:
        input_dir = case_dir / "child_evidence_inputs"
        lora_dir = output / case["child_evidence_lora_output"]
        prompt = f"portrait photo of {case['identity_token']} as an 8-year-old Korean child"
    command = [
        str(python), str(TRAIN_SCRIPT),
        "--pretrained_model_name_or_path", str(FLUX_MODEL),
        "--instance_data_dir", str(input_dir),
        "--instance_prompt", prompt,
        "--output_dir", str(lora_dir),
        "--resolution", "512", "--center_crop", "--random_flip",
        "--train_batch_size", "1", "--gradient_accumulation_steps", "1",
        "--max_train_steps", str(args.steps), "--learning_rate", "0.0001",
        "--lr_scheduler", "constant", "--lr_warmup_steps", "0",
        "--rank", "16", "--lora_alpha", "16", "--mixed_precision", "bf16",
        "--do_fp8_training", "--offload", "--cache_latents",
        "--gradient_checkpointing", "--use_8bit_adam", "--allow_tf32",
        "--dataloader_num_workers", "0",
        "--checkpointing_steps", str(max(100, args.steps // 3)),
        "--checkpoints_total_limit", "2", "--seed", "20260818",
        "--report_to", "tensorboard", "--skip_final_inference",
    ]
    completed_weights = lora_dir / "pytorch_lora_weights.safetensors"
    checkpoints = list(lora_dir.glob("checkpoint-*")) if lora_dir.is_dir() else []
    if not completed_weights.is_file() and checkpoints:
        command.extend(["--resume_from_checkpoint", "latest"])
    return command


def train(args: argparse.Namespace, kind: str) -> None:
    output = args.output.resolve()
    path = output / "two_mode_manifest.json"
    audit(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    python = ROOT / ".venv-flux2" / "Scripts" / "python.exe"
    if not python.is_file() or not TRAIN_SCRIPT.is_file() or not FLUX_MODEL.is_dir():
        raise FileNotFoundError("FLUX training runtime, script, or model is missing")
    cases = manifest["cases"]
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise ValueError(f"Unknown prepared case: {args.case_id}")
    if kind == "child_evidence":
        cases = [case for case in cases if case["child_evidence_inputs"]]
        if not cases:
            raise ValueError("No child-evidence inputs matched the requested case")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    for index, case in enumerate(cases, start=1):
        command = training_command(args, case, output, kind)
        print(f"[{index}/{len(cases)}] {case['case_id']} ({kind})", flush=True)
        if args.dry_run:
            print(subprocess.list2cmdline(command))
        else:
            subprocess.run(command, check=True, cwd=ROOT, env=env)


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "audit":
        audit(args.output.resolve() / "two_mode_manifest.json")
    elif args.command == "train-identity":
        train(args, "identity")
    elif args.command == "train-child-evidence":
        train(args, "child_evidence")
    elif args.command == "train-assisted":
        train(args, "identity")
        train(args, "child_evidence")


if __name__ == "__main__":
    main()
