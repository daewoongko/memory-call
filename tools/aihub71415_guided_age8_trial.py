"""Run the one-person 11->8 guided re-aging candidate trial.

The script deliberately separates generation-time evidence from evaluation-only
evidence:

* FRAN produces a structural hint, never the final portrait.
* the AI Hub 71415 age teacher is calibrated on the internal validation split;
* the AI Hub 045 family identity teacher ranks identity preservation;
* the real age-eight portrait is opened only after a winner is selected.

Image candidates themselves are generated outside this script (built-in
ImageGen in the Codex workflow) and placed in ``candidates/``.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "fran_vendor"))

from aihub71415 import read_jsonl  # noqa: E402
from face_training_teachers import load_age_teacher, load_identity_teacher  # noqa: E402
from model.models import UNet  # noqa: E402


EXPERIMENT = ROOT / "data/experiments/aihub71415_full"
TRIAL = EXPERIMENT / "one_person_trial/guided_age8_0899"
ADAPTIVE = EXPERIMENT / "one_person_trial/adaptive_path_0899"
CASE = EXPERIMENT / "full_pipeline_pilot/cases/age8_0899"
HIDDEN = EXPERIMENT / "full_pipeline_pilot/evaluation_only/age8_0899/hidden_real_age8.png"
AGE_CHECKPOINT = EXPERIMENT / "teachers/age_pilot_500/age_teacher_best.pth"
IDENTITY_CHECKPOINT = ROOT / "data/experiments/aihub045_full/teachers/identity_pilot_500/identity_teacher_best.pth"
FRAN_CHECKPOINT = EXPERIMENT / "training/revised_identity_guard_500/fran_aihub71415_step_000500.pth"
AGE_MEAN = (0.485, 0.456, 0.406)
AGE_STD = (0.229, 0.224, 0.225)


def image_read(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def image_write(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise RuntimeError(f"Could not encode {path}")
    encoded.tofile(path)


def teacher_tensor(image_bgr: np.ndarray, size: int = 224) -> torch.Tensor:
    rgb = cv2.cvtColor(cv2.resize(image_bgr, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    transform = v2.Compose(
        [
            v2.ToImage(),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(AGE_MEAN, AGE_STD),
        ]
    )
    return transform(rgb)


def fit_age_calibration(model, device: torch.device, limit: int = 1200) -> dict:
    """Fit a robust affine correction without touching the official holdout."""

    manifest = {str(row["record_id"]): row for row in read_jsonl(EXPERIMENT / "index/manifest.jsonl")}
    val_subjects = {str(row["subject_id"]) for row in read_jsonl(EXPERIMENT / "pairs/val_pairs.jsonl")}
    rows = [
        row
        for row in manifest.values()
        if str(row["subject_id"]) in val_subjects
        and row.get("dataset_partition") != "validation"
        and (EXPERIMENT / "teacher_crops_224" / f"{row['record_id']}.jpg").is_file()
    ]
    rows.sort(key=lambda row: (int(row["photo_age"]), str(row["record_id"])))
    if len(rows) > limit:
        indices = np.linspace(0, len(rows) - 1, limit).round().astype(int)
        rows = [rows[index] for index in indices]
    predicted: list[float] = []
    actual: list[float] = []
    batch: list[torch.Tensor] = []
    batch_ages: list[float] = []
    with torch.inference_mode():
        for row in rows:
            crop = image_read(EXPERIMENT / "teacher_crops_224" / f"{row['record_id']}.jpg")
            batch.append(teacher_tensor(crop))
            batch_ages.append(float(row["photo_age"]))
            if len(batch) == 64:
                values = model(torch.stack(batch).to(device))["expected_age"].cpu().numpy()
                predicted.extend(values.tolist())
                actual.extend(batch_ages)
                batch, batch_ages = [], []
        if batch:
            values = model(torch.stack(batch).to(device))["expected_age"].cpu().numpy()
            predicted.extend(values.tolist())
            actual.extend(batch_ages)
    x = np.asarray(predicted, dtype=np.float64)
    y = np.asarray(actual, dtype=np.float64)
    # Iteratively refit after trimming the largest residuals. This is enough for
    # calibration while keeping the selector dependency-free.
    keep = np.ones(len(x), dtype=bool)
    slope, intercept = 1.0, 0.0
    for _ in range(3):
        slope, intercept = np.polyfit(x[keep], y[keep], 1)
        residual = np.abs((slope * x + intercept) - y)
        cutoff = np.quantile(residual[keep], 0.90)
        keep = residual <= cutoff
    corrected = slope * x + intercept
    return {
        "samples": int(len(x)),
        "slope": float(slope),
        "intercept": float(intercept),
        "raw_mae": float(np.mean(np.abs(x - y))),
        "calibrated_mae": float(np.mean(np.abs(corrected - y))),
        "young_band_mae": float(np.mean(np.abs(corrected[(y >= 6) & (y <= 10)] - y[(y >= 6) & (y <= 10)]))),
        "source": "AI Hub 71415 internal validation subjects only",
    }


def fran_structure_guide(source_path: Path, output_dir: Path, device: torch.device) -> dict:
    source = image_read(source_path)
    source = cv2.resize(source, (512, 512), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
    image = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().div(255.0)
    source_map = torch.full((1, 512, 512), 0.11)
    target_map = torch.full((1, 512, 512), 0.08)
    model_input = torch.cat([image, source_map, target_map], dim=0).unsqueeze(0).to(device)
    model = UNet().to(device)
    model.load_state_dict(torch.load(FRAN_CHECKPOINT, map_location=device, weights_only=True), strict=True)
    model.eval()
    with torch.inference_mode():
        residual = model(model_input)[0]
        raw = torch.clamp(image.to(device) + residual, 0.0, 1.0)
    raw_bgr = cv2.cvtColor((raw.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    raw_path = output_dir / "fran_raw_not_a_candidate.png"
    image_write(raw_path, raw_bgr)

    gray = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 40, 40)
    edges = cv2.Canny(gray, 45, 110)
    mask = np.zeros_like(edges)
    cv2.ellipse(mask, (256, 274), (170, 205), 0, 0, 360, 255, -1)
    edges = cv2.bitwise_and(edges, mask)
    guide = np.full((512, 512, 3), 248, dtype=np.uint8)
    guide[edges > 0] = (65, 78, 68)
    # Stable facial proportion axes make the hint readable without carrying
    # FRAN's texture and synthesis artifacts into the final generator.
    for point in ((174, 224), (338, 224), (256, 286), (205, 348), (307, 348)):
        cv2.circle(guide, point, 5, (48, 125, 83), -1, cv2.LINE_AA)
    cv2.ellipse(guide, (256, 274), (170, 205), 0, 0, 360, (98, 117, 103), 2, cv2.LINE_AA)
    guide_path = output_dir / "fran_structure_guide.png"
    image_write(guide_path, guide)
    return {
        "checkpoint": str(FRAN_CHECKPOINT),
        "source_age": 11,
        "target_age": 8,
        "raw_output": str(raw_path),
        "structure_guide": str(guide_path),
        "warning": "FRAN raw output is not eligible for candidate selection",
    }


def prepare() -> None:
    TRIAL.mkdir(parents=True, exist_ok=True)
    (TRIAL / "candidates").mkdir(exist_ok=True)
    source_11 = ADAPTIVE / "age11.png"
    source_adult = CASE / "adult_only_lora/adult_38_05.png"
    shutil.copy2(source_11, TRIAL / "input_age11.png")
    shutil.copy2(source_adult, TRIAL / "identity_reference_age38.png")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    age_model = load_age_teacher(str(AGE_CHECKPOINT), device)
    calibration = fit_age_calibration(age_model, device)
    structure = fran_structure_guide(source_11, TRIAL, device)
    identity_result = json.loads((ROOT / "data/experiments/aihub045_full/teachers/identity_pilot_500/result.json").read_text(encoding="utf-8"))
    validation = identity_result["validation"]
    negative = max(validation["same_family_other_identity_cosine"], validation["different_family_cosine"])
    identity_threshold = (validation["same_identity_cosine"] + negative) / 2.0
    manifest = {
        "subject_id": "0899",
        "source_age": 11,
        "target_age": 8,
        "generation_inputs": ["input_age11.png", "identity_reference_age38.png", "fran_structure_guide.png"],
        "age_calibration": calibration,
        "identity_calibration": {
            "same_identity_mean": validation["same_identity_cosine"],
            "hard_negative_mean": validation["same_family_other_identity_cosine"],
            "different_family_mean": validation["different_family_cosine"],
            "selection_threshold": identity_threshold,
            "source": "AI Hub 045 validation families",
        },
        "fran": structure,
        "hidden_reference_used": False,
    }
    (TRIAL / "trial_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def fixed_crop(image_bgr: np.ndarray) -> np.ndarray:
    image = cv2.resize(image_bgr, (224, 224), interpolation=cv2.INTER_AREA)
    return image


def insightface_embedding(image_bgr: np.ndarray, recognition) -> np.ndarray:
    """Extract an ArcFace embedding with fixed canonical geometry.

    The licensed AI Hub portraits and generated candidates have already been
    centered. Fixed geometry avoids making detector confidence part of the
    hidden-reference comparison, especially for the very low-quality age-8
    photograph.
    """

    from insightface.utils import face_align

    image = cv2.resize(image_bgr, (512, 512), interpolation=cv2.INTER_AREA)
    landmarks = np.asarray(
        [[164, 195], [348, 195], [256, 287], [195, 353], [317, 353]],
        dtype=np.float32,
    )
    crop = face_align.norm_crop(image, landmark=landmarks, image_size=112)
    vector = np.asarray(recognition.get_feat(crop)[0], dtype=np.float32)
    return vector / max(float(np.linalg.norm(vector)), 1e-8)


def score() -> None:
    manifest_path = TRIAL / "trial_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = sorted((TRIAL / "candidates").glob("*.png"))
    if not candidates:
        raise FileNotFoundError(f"No PNG candidates in {TRIAL / 'candidates'}")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    age_model = load_age_teacher(str(AGE_CHECKPOINT), device)
    identity_model = load_identity_teacher(str(IDENTITY_CHECKPOINT), device)
    age11 = fixed_crop(image_read(TRIAL / "input_age11.png"))
    adult = fixed_crop(image_read(TRIAL / "identity_reference_age38.png"))
    with torch.inference_mode():
        reference_embeddings = identity_model(torch.stack([teacher_tensor(age11), teacher_tensor(adult)]).to(device)).cpu().numpy()
    slope = float(manifest["age_calibration"]["slope"])
    intercept = float(manifest["age_calibration"]["intercept"])
    with torch.inference_mode():
        age11_raw = float(age_model(teacher_tensor(age11).unsqueeze(0).to(device))["expected_age"].item())
    age11_global = slope * age11_raw + intercept
    # Synthetic portraits share a domain shift that is not present in the real
    # AI Hub calibration crops. The immediately preceding, known 11-year stage
    # supplies a local zero point. This still never observes the hidden age-8
    # portrait and measures only the requested 11->8 relative change.
    local_anchor_shift = 11.0 - age11_global
    identity_threshold = float(manifest["identity_calibration"]["selection_threshold"])
    rows = []
    for path in candidates:
        image = fixed_crop(image_read(path))
        tensor = teacher_tensor(image).unsqueeze(0).to(device)
        with torch.inference_mode():
            raw_age = float(age_model(tensor)["expected_age"].item())
            embedding = identity_model(tensor).cpu().numpy()[0]
        globally_calibrated_age = slope * raw_age + intercept
        calibrated_age = globally_calibrated_age + local_anchor_shift
        identity_11 = float(np.dot(embedding, reference_embeddings[0]))
        identity_adult = float(np.dot(embedding, reference_embeddings[1]))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        age_error = abs(calibrated_age - 8.0)
        identity_score = 0.65 * identity_11 + 0.35 * identity_adult
        # Rank only on generation-time evidence. The hidden portrait is absent.
        total = 0.55 * math.exp(-age_error / 3.0) + 0.45 * max(0.0, min(1.0, identity_score))
        rows.append(
            {
                "file": path.name,
                "raw_age": raw_age,
                "globally_calibrated_age": globally_calibrated_age,
                "calibrated_age": calibrated_age,
                "age_error": age_error,
                "identity_to_age11": identity_11,
                "identity_to_adult": identity_adult,
                "identity_score": identity_score,
                "identity_threshold": identity_threshold,
                "sharpness": sharpness,
                "age_gate": age_error <= 3.0,
                "identity_gate": identity_score >= identity_threshold,
                "naturalness_gate": sharpness >= 20.0,
                "rank_score": total,
            }
        )
    passing = [row for row in rows if row["age_gate"] and row["identity_gate"] and row["naturalness_gate"]]
    pool = passing or rows
    winner = max(pool, key=lambda row: row["rank_score"])
    winner_path = TRIAL / "candidates" / winner["file"]
    shutil.copy2(winner_path, TRIAL / "selected_age8.png")
    needs_intermediate = not bool(passing)
    selection = {
        "local_age_anchor": {
            "known_age": 11.0,
            "raw_prediction": age11_raw,
            "global_prediction": age11_global,
            "shift": local_anchor_shift,
        },
        "candidates": rows,
        "selected": winner,
        "all_hard_gates_passed": bool(passing),
        "next_action": "accept" if passing else "insert_age9_then_regenerate_age8",
        "hidden_reference_used": False,
    }
    (TRIAL / "selection_report.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Only now is the hidden real image opened and copied into the review area.
    hidden = fixed_crop(image_read(HIDDEN))
    with torch.inference_mode():
        hidden_embedding = identity_model(teacher_tensor(hidden).unsqueeze(0).to(device)).cpu().numpy()[0]
        selected_embedding = identity_model(teacher_tensor(fixed_crop(image_read(TRIAL / "selected_age8.png"))).unsqueeze(0).to(device)).cpu().numpy()[0]
    comparison_paths = {
        "selected_guided": TRIAL / "selected_age8.png",
        "previous_adaptive_path": ADAPTIVE / "age8.png",
        "previous_direct_generation": EXPERIMENT / "one_person_trial/age8_0899/imagegen_identity_baseline_v1.png",
    }
    review_copy_names = {
        "previous_adaptive_path": "previous_adaptive_age8.png",
        "previous_direct_generation": "previous_direct_age8.png",
    }
    for label, copy_name in review_copy_names.items():
        source = comparison_paths[label]
        if source.is_file():
            shutil.copy2(source, TRIAL / copy_name)
    hidden_comparison = {}
    with torch.inference_mode():
        for label, path in comparison_paths.items():
            if not path.is_file():
                continue
            value = identity_model(teacher_tensor(fixed_crop(image_read(path))).unsqueeze(0).to(device)).cpu().numpy()[0]
            hidden_comparison[label] = float(np.dot(value, hidden_embedding))
    from insightface.model_zoo import model_zoo

    recognition_path = Path.home() / ".insightface/models/buffalo_l/w600k_r50.onnx"
    recognition = model_zoo.get_model(str(recognition_path), providers=["CPUExecutionProvider"])
    recognition.prepare(ctx_id=-1)
    hidden_arcface = insightface_embedding(image_read(HIDDEN), recognition)
    arcface_comparison = {
        label: float(np.dot(insightface_embedding(image_read(path), recognition), hidden_arcface))
        for label, path in comparison_paths.items()
        if path.is_file()
    }
    final_eval = {
        "selected": winner["file"],
        "identity_to_hidden_real_age8": float(np.dot(selected_embedding, hidden_embedding)),
        "hidden_identity_comparison": hidden_comparison,
        "hidden_arcface_comparison": arcface_comparison,
        "hidden_reference_opened_after_selection": True,
        "needs_intermediate_age9": needs_intermediate,
        "warning": "Hidden-photo similarity is evaluation-only and never changes the selected candidate.",
    }
    shutil.copy2(HIDDEN, TRIAL / "evaluation_only_hidden_real_age8.png")
    (TRIAL / "final_evaluation.json").write_text(json.dumps(final_eval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_review(manifest, selection, final_eval)
    print(json.dumps({"selection": selection, "final_evaluation": final_eval}, ensure_ascii=False, indent=2))


def metric(value: float | bool) -> str:
    if isinstance(value, bool):
        return "통과" if value else "미통과"
    return f"{value:.3f}"


def write_review(manifest: dict, selection: dict, final_eval: dict) -> None:
    rows = []
    for row in selection["candidates"]:
        rows.append(
            f"<article><img src='candidates/{html.escape(row['file'])}' alt='후보'>"
            f"<h3>{html.escape(row['file'])}</h3>"
            f"<p>보정 연령 {row['calibrated_age']:.1f}세 · 목표 오차 {row['age_error']:.1f}세</p>"
            f"<p>신원 점수 {row['identity_score']:.3f} · 종합 {row['rank_score']:.3f}</p>"
            f"<p>연령 {metric(row['age_gate'])} · 신원 {metric(row['identity_gate'])}</p></article>"
        )
    selected = html.escape(final_eval["selected"])
    comparison = final_eval.get("hidden_identity_comparison", {})
    arcface = final_eval.get("hidden_arcface_comparison", {})
    page = f"""<!doctype html><html lang='ko'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>0899 가이드 후보 평가</title>
<style>body{{font-family:system-ui,sans-serif;background:#f5f1e8;color:#14271f;margin:0;padding:24px}}main{{max-width:1280px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}}article,.panel{{background:#fff;border:1px solid #abc0b5;border-radius:18px;padding:16px}}img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:12px}}h1,h2{{margin:0 0 12px}}.winner{{border:4px solid #176b48;box-sizing:border-box}}.eval{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-top:24px}}small{{color:#52685d}}</style>
<main><h1>0899 · 11세에서 8세 후보 선택</h1><p>실제 8세 사진은 후보 선택이 끝난 뒤에만 열었습니다.</p>
<section class='grid'>{''.join(rows)}</section>
<section class='eval'><article><h2>새 방식 선택 후보</h2><img class='winner' src='selected_age8.png'><p>{selected}</p></article>
<article><h2>이전 순차 경로</h2><img src='previous_adaptive_age8.png'><p>기존 연령 단계 생성 결과</p></article>
<article><h2>이전 직접 생성</h2><img src='previous_direct_age8.png'><p>중간 경로 없이 생성한 기준</p></article>
<article><h2>FRAN 구조 참고</h2><img src='fran_structure_guide.png'><p>질감은 버리고 얼굴 구조선만 사용</p></article>
<article><h2>최종 평가 전용</h2><img src='evaluation_only_hidden_real_age8.png'><p>숨겨 둔 실제 8세 · 선택에는 미사용</p></article></section>
<section class='panel' style='margin-top:18px'><h2>판정</h2><p>선택 후보의 보정 연령: {selection['selected']['calibrated_age']:.1f}세 · 신원 점수: {selection['selected']['identity_score']:.3f}</p><p>가족 신원 판별기 — 선택 {comparison.get('selected_guided', float('nan')):.3f} · 이전 순차 {comparison.get('previous_adaptive_path', float('nan')):.3f} · 이전 직접 {comparison.get('previous_direct_generation', float('nan')):.3f}</p><p>ArcFace — 선택 {arcface.get('selected_guided', float('nan')):.3f} · 이전 순차 {arcface.get('previous_adaptive_path', float('nan')):.3f} · 이전 직접 {arcface.get('previous_direct_generation', float('nan')):.3f}</p><p>다음 단계: {html.escape(selection['next_action'])}</p><small>연령 보정 표본 {manifest['age_calibration']['samples']}장 · 보정 MAE {manifest['age_calibration']['calibrated_mae']:.2f}세. 실제 8세 사진이 저화질이므로 숨은 사진 유사도는 참고값이며 선택에는 사용하지 않습니다.</small></section></main></html>"""
    (TRIAL / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "score"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        score()


if __name__ == "__main__":
    main()
