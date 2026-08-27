"""Run a leakage-safe, three-person full-pipeline age-8 pilot.

The pilot intentionally separates generation and evaluation:

* ``prepare`` extracts adult-only aligned portraits for Identity LoRA training.
  It records the hidden exact-age-8 target ID, but does not extract that image.
* ``train-loras`` trains one small FLUX.2 Identity LoRA per subject using only
  the adult portraits.
* ``generate`` creates final FLUX candidates for three controlled recipes:
  no FRAN, the pre-AIHub FRAN checkpoint, and the selected tuned checkpoint.
* ``evaluate`` is the only command allowed to open the hidden age-8 images.

Raw FRAN outputs are diagnostic structure guides.  They are never presented as
the product result and never scored as final photographs in this pilot.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gc
import html
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import align_record_image, read_jsonl  # noqa: E402


EXPERIMENT = ROOT / "data" / "experiments" / "aihub71415_full"
DEFAULT_OUTPUT = EXPERIMENT / "full_pipeline_pilot"
DEFAULT_SUBJECTS = ("0895", "0899", "0910")
MODELS_ROOT = Path(os.environ.get("MEMORY_CALL_MODELS_DIR", ROOT.parent / "Models"))
BASELINE_FRAN = Path(
    os.environ.get(
        "BASELINE_FRAN_CHECKPOINT",
        MODELS_ROOT / "face_reaging/backups/best_unet_model_pre_aihub.pth",
    )
)
TUNED_FRAN = Path(
    os.environ.get(
        "TUNED_FRAN_CHECKPOINT",
        MODELS_ROOT / "face_reaging/best_unet_model.pth",
    )
)
TRAIN_SCRIPT = (
    MODELS_ROOT
    / "diffusers-flux2-train"
    / "examples"
    / "dreambooth"
    / "train_dreambooth_lora_flux2_klein.py"
)
FLUX_MODEL = Path(
    os.environ.get("FLUX_MODEL_PATH", MODELS_ROOT / "FLUX2-klein-base-4B")
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "prepare",
            "train-loras",
            "audit",
            "generate-guides",
            "generate",
            "evaluate",
        ),
    )
    parser.add_argument(
        "--manifest", type=Path, default=EXPERIMENT / "index" / "manifest.jsonl"
    )
    parser.add_argument(
        "--holdouts", type=Path, default=EXPERIMENT / "pairs" / "age8_holdouts.jsonl"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--subjects", nargs="+", default=list(DEFAULT_SUBJECTS))
    parser.add_argument("--steps", type=int, default=240)
    parser.add_argument("--inference-steps", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_inputs(args: argparse.Namespace) -> tuple[dict[str, dict], dict[str, dict]]:
    records = {row["record_id"]: row for row in read_jsonl(args.manifest)}
    cases = {
        row["subject_id"]: row
        for row in read_jsonl(args.holdouts)
        if row.get("formal_eval") and row["subject_id"] in set(args.subjects)
    }
    missing = sorted(set(args.subjects) - set(cases))
    if missing:
        raise ValueError(f"Formal evaluation subjects not found: {', '.join(missing)}")
    return records, cases


def _aligned_rgb(record: dict, *, size: int = 512):

    import cv2

    archive_path = Path(record["image_archive_path"])
    with ZipFile(archive_path) as archive:
        bgr, alignment = align_record_image(
            archive, record, width=size, height=size
        )
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), alignment


def _save_rgb(path: Path, rgb) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(path)


def prepare(args: argparse.Namespace) -> None:
    records, cases = _load_inputs(args)
    output = args.output.resolve()
    pilot_cases: list[dict] = []
    for subject_id in args.subjects:
        case = cases[subject_id]
        case_dir = output / "cases" / case["case_id"]
        lora_dir = case_dir / "adult_only_lora"
        source_rows: list[dict] = []
        adult_ids = {row["record_id"] for row in case["adult_only_sources"]}
        hidden_id = case["hidden_target"]["record_id"]
        excluded_ids = set(case.get("excluded_target_record_ids") or [])
        if hidden_id in adult_ids or adult_ids.intersection(excluded_ids):
            raise RuntimeError(f"Target leakage detected for {case['case_id']}")

        for index, source_ref in enumerate(case["adult_only_sources"], start=1):
            record = records[source_ref["record_id"]]
            rgb, alignment = _aligned_rgb(record)
            filename = f"adult_{int(source_ref['photo_age']):02d}_{index:02d}.png"
            _save_rgb(lora_dir / filename, rgb)
            source_rows.append(
                {
                    "record_id": record["record_id"],
                    "photo_age": int(source_ref["photo_age"]),
                    "path": (lora_dir / filename).relative_to(output).as_posix(),
                    "alignment": alignment,
                }
            )

        parent = max(source_rows, key=lambda row: (row["photo_age"], row["record_id"]))
        gender = str(records[parent["record_id"]].get("gender") or "unspecified")
        token = f"mc{subject_id}person"
        pilot_cases.append(
            {
                "case_id": case["case_id"],
                "subject_id": subject_id,
                "gender": gender,
                "target_age": 8,
                "identity_token": token,
                "adult_sources": source_rows,
                "accepted_parent": parent,
                "sealed_evaluation_target": {
                    "record_id": hidden_id,
                    "excluded_from_lora": True,
                    "excluded_from_generation": True,
                    "image_extracted": False,
                },
                "lora_output": (
                    case_dir / "identity_lora"
                ).relative_to(output).as_posix(),
            }
        )

    manifest = {
        "version": 1,
        "purpose": "three_person_full_pipeline_gate_before_any_additional_training",
        "generation_must_not_open_hidden_target": True,
        "subjects": list(args.subjects),
        "recipes": ["flux_lora_only", "baseline_fran_flux_lora", "tuned_fran_flux_lora"],
        "seeds": [20260817, 20260818],
        "cases": pilot_cases,
    }
    _write_json(output / "pilot_manifest.json", manifest)
    audit_manifest(output / "pilot_manifest.json")
    print(f"Prepared {len(pilot_cases)} leakage-safe pilot cases: {output}")
    print("Hidden age-8 image files were not extracted.")


def audit_manifest(path: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        adult_ids = {row["record_id"] for row in case["adult_sources"]}
        sealed = case["sealed_evaluation_target"]
        if sealed["record_id"] in adult_ids:
            raise RuntimeError(f"Target leakage in {case['case_id']}")
        if sealed.get("image_extracted"):
            raise RuntimeError(f"Target was revealed before evaluation: {case['case_id']}")
        for row in case["adult_sources"]:
            if "age8" in Path(row["path"]).name.lower():
                raise RuntimeError(f"Suspicious adult filename: {row['path']}")


def _train_command(
    *, python: Path, case: dict, output: Path, steps: int
) -> list[str]:
    case_dir = output / "cases" / case["case_id"]
    data_dir = case_dir / "adult_only_lora"
    lora_dir = output / case["lora_output"]
    gender = "woman" if case["gender"] == "female" else "man"
    prompt = f"portrait photo of {case['identity_token']}, a Korean {gender}"
    return [
        str(python),
        str(TRAIN_SCRIPT),
        "--pretrained_model_name_or_path",
        str(FLUX_MODEL),
        "--instance_data_dir",
        str(data_dir),
        "--instance_prompt",
        prompt,
        "--output_dir",
        str(lora_dir),
        "--resolution",
        "512",
        "--center_crop",
        "--train_batch_size",
        "1",
        "--gradient_accumulation_steps",
        "1",
        "--max_train_steps",
        str(steps),
        "--learning_rate",
        "0.0001",
        "--lr_scheduler",
        "constant",
        "--lr_warmup_steps",
        "0",
        "--rank",
        "16",
        "--lora_alpha",
        "16",
        "--mixed_precision",
        "bf16",
        "--do_fp8_training",
        "--offload",
        "--cache_latents",
        "--gradient_checkpointing",
        "--use_8bit_adam",
        "--allow_tf32",
        "--dataloader_num_workers",
        "0",
        "--checkpointing_steps",
        str(max(80, steps // 3)),
        "--checkpoints_total_limit",
        "2",
        "--seed",
        "20260817",
        "--report_to",
        "tensorboard",
        "--skip_final_inference",
    ]


def train_loras(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    manifest_path = output / "pilot_manifest.json"
    audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    python = ROOT / ".venv-flux2" / "Scripts" / "python.exe"
    if not python.is_file() or not TRAIN_SCRIPT.is_file() or not FLUX_MODEL.is_dir():
        raise FileNotFoundError("FLUX training runtime, script, or model is missing")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    for index, case in enumerate(manifest["cases"], start=1):
        command = _train_command(
            python=python, case=case, output=output, steps=args.steps
        )
        print(f"[{index}/{len(manifest['cases'])}] {case['case_id']}", flush=True)
        if args.dry_run:
            print(subprocess.list2cmdline(command))
            continue
        subprocess.run(command, check=True, cwd=ROOT, env=env)


def _fran_input(rgb, source_age: int, target_age: int, device):
    import numpy as np
    import torch

    image = torch.from_numpy(np.asarray(rgb).copy()).permute(2, 0, 1).float().div(255.0)
    height, width = rgb.shape[:2]
    source_map = torch.full((1, height, width), source_age / 100.0)
    target_map = torch.full((1, height, width), target_age / 100.0)
    values = torch.cat((image, source_map, target_map), dim=0).unsqueeze(0)
    return values.to(device), image.to(device)


def _make_fran_guides(manifest: dict, output: Path) -> None:
    import numpy as np
    import torch
    from PIL import Image

    sys.path.insert(0, str(ROOT / "tools" / "face_aging" / "fran_vendor"))
    from model.models import UNet

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required")
    for checkpoint_name, checkpoint in (
        ("baseline_fran", BASELINE_FRAN),
        ("tuned_fran", TUNED_FRAN),
    ):
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        model = UNet().cuda().eval()
        model.load_state_dict(
            torch.load(checkpoint, map_location="cuda", weights_only=True), strict=True
        )
        with torch.inference_mode():
            for case in manifest["cases"]:
                parent_path = output / case["accepted_parent"]["path"]
                with Image.open(parent_path) as parent_image:
                    parent = np.asarray(parent_image.convert("RGB")).copy()
                values, parent_tensor = _fran_input(
                    parent,
                    int(case["accepted_parent"]["photo_age"]),
                    int(case["target_age"]),
                    torch.device("cuda"),
                )
                # FRAN predicts a residual.  Keep it as a structural hint only;
                # FLUX receives the unmodified adult portrait as its edit base.
                guide = torch.clamp(parent_tensor + model(values)[0], 0.0, 1.0)
                guide_rgb = (
                    guide.permute(1, 2, 0).mul(255.0).round().byte().cpu().numpy()
                )
                path = output / "cases" / case["case_id"] / "guides" / f"{checkpoint_name}.png"
                _save_rgb(path, guide_rgb)
        del model
        gc.collect()
        torch.cuda.empty_cache()


def _face_mask(size: int = 512):
    from PIL import Image, ImageDraw, ImageFilter

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((58, 28, size - 58, size - 10), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=14))


def _load_pil(path: Path):
    from PIL import Image

    with Image.open(path) as image:
        return image.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)


def generate(args: argparse.Namespace) -> None:
    import torch

    sys.path.insert(0, str(ROOT / "tools" / "face_aging"))
    from age_generate_flux2 import build_pipeline, build_prompt

    output = args.output.resolve()
    manifest_path = output / "pilot_manifest.json"
    audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_loras = []
    for case in manifest["cases"]:
        path = output / case["lora_output"] / "pytorch_lora_weights.safetensors"
        if not path.is_file():
            missing_loras.append(str(path))
    if missing_loras:
        raise FileNotFoundError("Pilot LoRAs are missing:\n" + "\n".join(missing_loras))

    guide_paths = [
        output / "cases" / case["case_id"] / "guides" / f"{label}.png"
        for case in manifest["cases"]
        for label in ("baseline_fran", "tuned_fran")
    ]
    if not all(path.is_file() for path in guide_paths):
        age_python = ROOT / ".venv-age" / "Scripts" / "python.exe"
        if not age_python.is_file():
            raise FileNotFoundError("FRAN guide runtime is missing: .venv-age")
        command = [
            str(age_python),
            str(Path(__file__).resolve()),
            "generate-guides",
            "--output",
            str(output),
            "--manifest",
            str(args.manifest),
            "--holdouts",
            str(args.holdouts),
            "--subjects",
            *[str(value) for value in args.subjects],
        ]
        subprocess.run(command, check=True, cwd=ROOT)
    pipeline = build_pipeline()
    mask = _face_mask()
    generation_rows: list[dict] = []
    for case_index, case in enumerate(manifest["cases"], start=1):
        lora_path = output / case["lora_output"] / "pytorch_lora_weights.safetensors"
        pipeline.load_lora_weights(
            str(lora_path.parent),
            weight_name=lora_path.name,
            adapter_name="identity",
            local_files_only=True,
        )
        pipeline.set_adapters("identity", adapter_weights=0.85)
        parent_path = output / case["accepted_parent"]["path"]
        parent = _load_pil(parent_path)
        parent_age = int(case["accepted_parent"]["photo_age"])
        demographic = "Korean woman" if case["gender"] == "female" else "Korean man"
        recipes = (
            ("flux_lora_only", None),
            (
                "baseline_fran_flux_lora",
                output / "cases" / case["case_id"] / "guides" / "baseline_fran.png",
            ),
            (
                "tuned_fran_flux_lora",
                output / "cases" / case["case_id"] / "guides" / "tuned_fran.png",
            ),
        )
        for recipe, guide_path in recipes:
            guide = _load_pil(guide_path) if guide_path is not None else None
            prompt = build_prompt(
                int(case["target_age"]),
                1,
                case["identity_token"],
                demographic,
                parent_age,
                guide is not None,
                "reference",
            )
            for seed in manifest["seeds"]:
                started = time.perf_counter()
                result = pipeline(
                    prompt=prompt,
                    image=parent,
                    image_reference=guide,
                    mask_image=mask,
                    strength=0.75,
                    height=512,
                    width=512,
                    num_inference_steps=max(8, int(args.inference_steps)),
                    guidance_scale=1.0,
                    generator=torch.Generator(device="cpu").manual_seed(int(seed)),
                ).images[0]
                result_path = (
                    output
                    / "cases"
                    / case["case_id"]
                    / "generated"
                    / recipe
                    / f"seed_{seed}.png"
                )
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result.save(result_path)
                generation_rows.append(
                    {
                        "case_id": case["case_id"],
                        "subject_id": case["subject_id"],
                        "recipe": recipe,
                        "seed": int(seed),
                        "path": result_path.relative_to(output).as_posix(),
                        "seconds": round(time.perf_counter() - started, 2),
                        "parent_age": parent_age,
                        "hidden_target_opened": False,
                    }
                )
                print(
                    f"[{case_index}/{len(manifest['cases'])}] {case['case_id']} "
                    f"{recipe} seed {seed}: {generation_rows[-1]['seconds']}s",
                    flush=True,
                )
        pipeline.unload_lora_weights()
        gc.collect()
        torch.cuda.empty_cache()
    _write_json(
        output / "generation_report.json",
        {
            "status": "complete",
            "hidden_targets_opened": False,
            "structure_guide_mode": "reference",
            "identity_lora_scale": 0.85,
            "masked_edit_strength": 0.75,
            "rows": generation_rows,
        },
    )
    print(f"Generated {len(generation_rows)} final candidates without opening targets")


def _cosine(left, right) -> float:
    import numpy as np

    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else float("nan")


def _fixed_face_geometry(size: int = 512):
    import numpy as np

    landmarks = np.asarray(
        [
            [0.32 * size, 0.38 * size],
            [0.68 * size, 0.38 * size],
            [0.50 * size, 0.56 * size],
            [0.38 * size, 0.69 * size],
            [0.62 * size, 0.69 * size],
        ],
        dtype=np.float32,
    )
    bbox = np.asarray(
        [0.18 * size, 0.14 * size, 0.82 * size, 0.88 * size], dtype=np.float32
    )
    return landmarks, bbox


def _insight_embedding(recognition, rgb, landmarks):
    import cv2
    import numpy as np
    from insightface.utils import face_align

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    crop = face_align.norm_crop(bgr, landmark=landmarks, image_size=112)
    return np.asarray(recognition.get_feat(crop)[0], dtype=np.float32)


def _insight_age(genderage, rgb, bbox) -> int:
    import cv2
    from insightface.app.common import Face

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    face = Face(bbox=bbox)
    _, age = genderage.get(bgr, face)
    return int(age)


def _teacher_input(image, torch):
    resized = torch.nn.functional.interpolate(
        image.unsqueeze(0), size=(224, 224), mode="bilinear", align_corners=False
    )
    mean = resized.new_tensor((0.485, 0.456, 0.406))[None, :, None, None]
    std = resized.new_tensor((0.229, 0.224, 0.225))[None, :, None, None]
    return (resized - mean) / std


def _image_tensor(rgb, torch, device):
    return (
        torch.from_numpy(rgb.copy())
        .permute(2, 0, 1)
        .float()
        .div(255.0)
        .to(device)
    )


def _image_qc(rgb, detector) -> dict:
    import cv2

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    detector.setInputSize((int(rgb.shape[1]), int(rgb.shape[0])))
    _, faces = detector.detect(bgr)
    return {
        "face_count": 0 if faces is None else int(len(faces)),
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3),
        "brightness": round(float(gray.mean()), 3),
    }


def _metric_summary(rows: list[dict], recipe: str) -> dict:
    import numpy as np

    selected = [row for row in rows if row["recipe"] == recipe]

    def mean(key: str):
        values = [float(row[key]) for row in selected if row.get(key) is not None]
        return round(float(np.mean(values)), 5) if values else None

    return {
        "images": len(selected),
        "identity_to_hidden_age8_mean": mean("identity_to_hidden_age8"),
        "identity_to_adult_source_mean": mean("identity_to_adult_source"),
        "insightface_age_mae_mean": mean("insightface_age_mae"),
        "aihub_age_mae_mean": mean("aihub_age_mae"),
        "target_lpips_mean": mean("target_lpips"),
        "target_l1_mean": mean("target_l1"),
        "single_face_rate": mean("single_face"),
        "sharpness_mean": mean("sharpness"),
        "brightness_mean": mean("brightness"),
    }


def _image_data_uri(path: Path) -> str:
    """Embed review images so the report also works when opened as file://."""

    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _write_blind_review(
    *, output: Path, manifest: dict, metrics: list[dict]
) -> None:
    review_dir = output / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    recipes = list(manifest["recipes"])
    answer_key: dict[str, dict[str, str]] = {}
    sections: list[str] = []
    for case in manifest["cases"]:
        case_id = case["case_id"]
        parent = output / case["accepted_parent"]["path"]
        hidden = output / "evaluation_only" / case_id / "hidden_real_age8.png"
        seed_cards: list[str] = []
        for seed in manifest["seeds"]:
            shuffled = recipes.copy()
            random.Random(f"{case_id}:{seed}:blind").shuffle(shuffled)
            labels = {chr(65 + index): recipe for index, recipe in enumerate(shuffled)}
            answer_key[f"{case_id}:{seed}"] = labels
            candidates = []
            for label, recipe in labels.items():
                row = next(
                    item
                    for item in metrics
                    if item["case_id"] == case_id
                    and item["seed"] == seed
                    and item["recipe"] == recipe
                )
                path = output / row["path"]
                candidates.append(
                    f'<figure><img src="{_image_data_uri(path)}" '
                    f'alt="candidate {label}"><figcaption>{label}</figcaption></figure>'
                )
            seed_cards.append(
                f'<section class="seed"><h3>Seed {seed}</h3><div class="candidates">'
                + "".join(candidates)
                + "</div></section>"
            )
        sections.append(
            f'<article><h2>{html.escape(case_id)}</h2><div class="anchors">'
            f'<figure><img src="{_image_data_uri(parent)}"><figcaption>성인 입력 '
            f'{case["accepted_parent"]["photo_age"]}세</figcaption></figure>'
            f'<figure><img src="{_image_data_uri(hidden)}"><figcaption>숨겨둔 실제 8세</figcaption></figure>'
            f'</div>{"".join(seed_cards)}</article>'
        )
    page = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>전체 파이프라인 블라인드 평가</title>
<style>body{font-family:system-ui,sans-serif;background:#f5f1e8;color:#14271f;margin:0;padding:24px}main{max-width:1280px;margin:auto}article{background:#fffdf8;border:1px solid #8b9b91;border-radius:22px;padding:24px;margin:24px 0}.anchors,.candidates{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}.anchors{max-width:520px}.seed{border-top:1px solid #cad2cd;margin-top:24px;padding-top:12px}figure{margin:0}img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:14px;background:#dde3df}figcaption{font-weight:700;text-align:center;padding:8px}p{color:#52625a}</style>
<main><h1>8세 얼굴 전체 파이프라인 블라인드 평가</h1><p>A/B/C의 정체를 보기 전에 신원 유사성, 자연스러움, 8세다움을 각각 평가하세요. 실제 8세 사진은 생성·LoRA 학습에서 제외됐습니다.</p>""" + "".join(sections) + "</main></html>"
    (review_dir / "index.html").write_text(page, encoding="utf-8")
    _write_json(review_dir / "answer_key.json", answer_key)
    with (review_dir / "review_scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["case_id", "seed", "candidate", "identity_1_5", "naturalness_1_5", "age8_1_5", "notes"]
        )
        for key, labels in answer_key.items():
            case_id, seed = key.split(":")
            for label in labels:
                writer.writerow([case_id, seed, label, "", "", "", ""])


def _write_diagnostics(*, output: Path, manifest: dict) -> None:
    cards = []
    for case in manifest["cases"]:
        base = output / "cases" / case["case_id"] / "guides"
        parent = output / case["accepted_parent"]["path"]
        cards.append(
            f'<article><h2>{html.escape(case["case_id"])}</h2><div>'
            f'<figure><img src="{_image_data_uri(parent)}"><figcaption>성인 입력</figcaption></figure>'
            f'<figure><img src="{_image_data_uri(base / "baseline_fran.png")}"><figcaption>기존 FRAN 원시 가이드</figcaption></figure>'
            f'<figure><img src="{_image_data_uri(base / "tuned_fran.png")}"><figcaption>튜닝 FRAN 원시 가이드</figcaption></figure>'
            "</div></article>"
        )
    page = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>FRAN 구조 가이드 진단</title>
<style>body{font-family:system-ui;background:#f5f1e8;padding:24px}article{background:white;padding:20px;margin:20px auto;max-width:1000px;border-radius:18px}article div{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}figure{margin:0}img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:12px}figcaption{text-align:center;font-weight:700;padding:8px}</style><h1>FRAN 원시 구조 가이드 — 최종 사진 아님</h1>""" + "".join(cards) + "</html>"
    (output / "review" / "fran_diagnostics.html").write_text(page, encoding="utf-8")


def evaluate(args: argparse.Namespace) -> None:
    import cv2
    import lpips
    import numpy as np
    import torch
    from insightface.model_zoo import model_zoo

    from face_training_teachers import load_age_teacher

    output = args.output.resolve()
    manifest = json.loads((output / "pilot_manifest.json").read_text(encoding="utf-8"))
    generation = json.loads((output / "generation_report.json").read_text(encoding="utf-8"))
    if generation.get("hidden_targets_opened") or len(generation.get("rows") or []) != 18:
        raise RuntimeError("Generation must finish all 18 images without opening hidden targets")
    records, _ = _load_inputs(args)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    insightface_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    recognition = model_zoo.get_model(
        str(insightface_dir / "w600k_r50.onnx"), providers=["CPUExecutionProvider"]
    )
    genderage = model_zoo.get_model(
        str(insightface_dir / "genderage.onnx"), providers=["CPUExecutionProvider"]
    )
    recognition.prepare(ctx_id=-1)
    genderage.prepare(ctx_id=-1)
    detector = cv2.FaceDetectorYN.create(
        str(ROOT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"),
        "",
        (512, 512),
        score_threshold=0.6,
        nms_threshold=0.3,
        top_k=5000,
    )
    teacher_path = EXPERIMENT / "teachers" / "age_pilot_500" / "age_teacher_best.pth"
    age_teacher = load_age_teacher(str(teacher_path), device)
    perceptual = lpips.LPIPS(net="alex", verbose=False).to(device).eval()
    landmarks, bbox = _fixed_face_geometry()
    case_context: dict[str, dict] = {}
    for case in manifest["cases"]:
        hidden_id = case["sealed_evaluation_target"]["record_id"]
        hidden_rgb, alignment = _aligned_rgb(records[hidden_id])
        hidden_path = output / "evaluation_only" / case["case_id"] / "hidden_real_age8.png"
        _save_rgb(hidden_path, hidden_rgb)
        parent_rgb = np.asarray(_load_pil(output / case["accepted_parent"]["path"]))
        case_context[case["case_id"]] = {
            "hidden": hidden_rgb,
            "hidden_tensor": _image_tensor(hidden_rgb, torch, device),
            "hidden_embedding": _insight_embedding(recognition, hidden_rgb, landmarks),
            "parent_embedding": _insight_embedding(recognition, parent_rgb, landmarks),
            "target_alignment": alignment,
        }
    metric_rows: list[dict] = []
    with torch.inference_mode():
        for index, generated_row in enumerate(generation["rows"], start=1):
            rgb = np.asarray(_load_pil(output / generated_row["path"]))
            tensor = _image_tensor(rgb, torch, device)
            context = case_context[generated_row["case_id"]]
            embedding = _insight_embedding(recognition, rgb, landmarks)
            estimated_age = _insight_age(genderage, rgb, bbox)
            teacher_age = float(age_teacher(_teacher_input(tensor, torch))["expected_age"].item())
            qc = _image_qc(rgb, detector)
            row = dict(generated_row)
            row.update(
                {
                    "identity_to_hidden_age8": _cosine(embedding, context["hidden_embedding"]),
                    "identity_to_adult_source": _cosine(embedding, context["parent_embedding"]),
                    "insightface_estimated_age": estimated_age,
                    "insightface_age_mae": abs(estimated_age - 8),
                    "aihub_age_estimate": round(teacher_age, 4),
                    "aihub_age_mae": round(abs(teacher_age - 8.0), 4),
                    "target_l1": float(torch.nn.functional.l1_loss(tensor, context["hidden_tensor"])),
                    "target_lpips": float(
                        perceptual(
                            tensor.unsqueeze(0) * 2.0 - 1.0,
                            context["hidden_tensor"].unsqueeze(0) * 2.0 - 1.0,
                        ).mean()
                    ),
                    "single_face": 1.0 if qc["face_count"] == 1 else 0.0,
                    **qc,
                }
            )
            metric_rows.append(row)
            print(f"[{index}/18] evaluated {row['case_id']} {row['recipe']} {row['seed']}", flush=True)
    summaries = {
        recipe: _metric_summary(metric_rows, recipe) for recipe in manifest["recipes"]
    }
    baseline = summaries["flux_lora_only"]
    tuned = summaries["tuned_fran_flux_lora"]
    gate = {
        "tuned_identity_drop_vs_no_fran": round(
            float(tuned["identity_to_hidden_age8_mean"] - baseline["identity_to_hidden_age8_mean"]), 5
        ),
        "tuned_age_mae_change_vs_no_fran": round(
            float(tuned["aihub_age_mae_mean"] - baseline["aihub_age_mae_mean"]), 5
        ),
        "tuned_lpips_change_vs_no_fran": round(
            float(tuned["target_lpips_mean"] - baseline["target_lpips_mean"]), 5
        ),
        "automatic_recommendation": (
            "retain_tuned_fran_for_blind_review"
            if tuned["identity_to_hidden_age8_mean"] >= baseline["identity_to_hidden_age8_mean"] - 0.02
            and tuned["aihub_age_mae_mean"] < baseline["aihub_age_mae_mean"]
            and tuned["single_face_rate"] >= 0.95
            else "do_not_connect_tuned_fran_to_runtime"
        ),
        "warning": "This is a three-person pilot gate, not a production-quality claim.",
    }
    report = {
        "status": "complete",
        "evaluation_only_targets_opened_after_generation": True,
        "generation_target_leakage": False,
        "summaries": summaries,
        "gate": gate,
        "rows": metric_rows,
    }
    _write_json(output / "evaluation_report.json", report)
    _write_blind_review(output=output, manifest=manifest, metrics=metric_rows)
    _write_diagnostics(output=output, manifest=manifest)
    print(json.dumps({"summaries": summaries, "gate": gate}, ensure_ascii=False, indent=2))
    print(f"Blind review: {(output / 'review' / 'index.html').resolve()}")


def main() -> None:
    args = _parser().parse_args()
    args.output = args.output.resolve()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "train-loras":
        train_loras(args)
    elif args.command == "audit":
        audit_manifest(args.output / "pilot_manifest.json")
        print("Leakage audit passed")
    elif args.command == "generate-guides":
        manifest = json.loads(
            (args.output / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        audit_manifest(args.output / "pilot_manifest.json")
        _make_fran_guides(manifest, args.output)
        print("FRAN diagnostic structure guides generated")
    elif args.command == "generate":
        generate(args)
    elif args.command == "evaluate":
        evaluate(args)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
