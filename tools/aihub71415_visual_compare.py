"""Create private blind-review sheets for the AI Hub exact-age-8 holdout.

The sheets contain licensed faces and must stay under the ignored experiment
directory.  Candidate A/B positions are randomized per case; the answer key is
written separately so reviewers can judge identity, age and artefacts first.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import sys
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "fran_vendor"))

from aihub71415 import align_record_image, read_jsonl  # noqa: E402
from model.models import UNet  # noqa: E402


def parse_args() -> argparse.Namespace:
    experiment = ROOT / "data" / "experiments" / "aihub71415_full"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=experiment / "index" / "manifest.jsonl"
    )
    parser.add_argument(
        "--holdouts", type=Path, default=experiment / "pairs" / "age8_holdouts.jsonl"
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=20)
    parser.add_argument("--rows-per-page", type=int, default=5)
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--cell-size", type=int, default=280)
    parser.add_argument("--seed", type=int, default=20260817)
    return parser.parse_args()


def blind_assignment(case_ids: list[str], seed: int) -> dict[str, dict[str, str]]:
    """Return deterministic, independently randomized model labels."""

    rng = random.Random(seed)
    result: dict[str, dict[str, str]] = {}
    for case_id in case_ids:
        baseline_label, candidate_label = (
            ("A", "B") if rng.random() < 0.5 else ("B", "A")
        )
        result[case_id] = {
            "baseline": baseline_label,
            "candidate": candidate_label,
        }
    return result


def _aligned(records: dict[str, dict], record_id: str, size: int) -> np.ndarray:
    row = records[record_id]
    with ZipFile(row["image_archive_path"]) as archive:
        bgr, _ = align_record_image(archive, row, width=size, height=size)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _model_input(
    source: np.ndarray,
    source_age: int,
    target_age: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    rgb = torch.from_numpy(source.copy()).permute(2, 0, 1).float().div(255.0)
    height, width = source.shape[:2]
    source_map = torch.full((1, height, width), source_age / 100.0)
    target_map = torch.full((1, height, width), target_age / 100.0)
    inputs = torch.cat((rgb, source_map, target_map), dim=0).unsqueeze(0).to(device)
    return inputs, rgb.to(device)


def _load_model(path: Path, device: torch.device) -> UNet:
    model = UNet().to(device)
    state = torch.load(path, map_location=device, weights_only=True)
    model.load_state_dict(state, strict=True)
    return model.eval()


@torch.inference_mode()
def _generate(
    checkpoint: Path,
    cases: list[dict],
    sources: dict[str, np.ndarray],
    device: torch.device,
) -> dict[str, np.ndarray]:
    model = _load_model(checkpoint, device)
    outputs: dict[str, np.ndarray] = {}
    for index, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        source_ref = max(case["adult_only_sources"], key=lambda row: int(row["photo_age"]))
        inputs, source_tensor = _model_input(
            sources[case_id], int(source_ref["photo_age"]), 8, device
        )
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            generated = torch.clamp(source_tensor + model(inputs)[0], 0.0, 1.0)
        outputs[case_id] = np.rint(
            generated.float().permute(1, 2, 0).cpu().numpy() * 255.0
        ).astype(np.uint8)
        print(f"{checkpoint.name}: {index}/{len(cases)}", flush=True)
    del model
    torch.cuda.empty_cache()
    return outputs


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["malgunbd.ttf" if bold else "malgun.ttf", "arialbd.ttf" if bold else "arial.ttf"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fit(rgb: np.ndarray, size: int) -> Image.Image:
    image = Image.fromarray(rgb, mode="RGB")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), "#eef1ed")
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def _write_pages(
    output_dir: Path,
    cases: list[dict],
    sources: dict[str, np.ndarray],
    targets: dict[str, np.ndarray],
    baseline: dict[str, np.ndarray],
    candidate: dict[str, np.ndarray],
    assignments: dict[str, dict[str, str]],
    *,
    rows_per_page: int,
    cell_size: int,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    margin, gutter, header, label_height = 28, 14, 86, 42
    columns = 4
    page_width = margin * 2 + columns * cell_size + (columns - 1) * gutter
    row_height = cell_size + label_height + gutter
    title_font, label_font, small_font = _font(26, True), _font(18, True), _font(14)
    page_names: list[str] = []
    for page_index, start in enumerate(range(0, len(cases), rows_per_page), start=1):
        page_cases = cases[start : start + rows_per_page]
        page_height = header + len(page_cases) * row_height + margin
        page = Image.new("RGB", (page_width, page_height), "#faf8f2")
        draw = ImageDraw.Draw(page)
        draw.text((margin, 18), "8세 얼굴 블라인드 비교", font=title_font, fill="#10291f")
        draw.text(
            (margin, 54),
            "성인 원본과 실제 8세를 참고해 A/B만 평가하세요 · AI Hub 비공개 검수 자료",
            font=small_font,
            fill="#52635c",
        )
        for row_index, case in enumerate(page_cases):
            case_id = case["case_id"]
            assignment = assignments[case_id]
            generated_by_label = {
                assignment["baseline"]: baseline[case_id],
                assignment["candidate"]: candidate[case_id],
            }
            cells = [
                ("성인 원본", sources[case_id]),
                ("실제 8세", targets[case_id]),
                ("후보 A", generated_by_label["A"]),
                ("후보 B", generated_by_label["B"]),
            ]
            top = header + row_index * row_height
            for column, (label, rgb) in enumerate(cells):
                left = margin + column * (cell_size + gutter)
                image_top = top + label_height
                page.paste(_fit(rgb, cell_size), (left, image_top))
                display_label = f"{label} · {case_id}" if column == 0 else label
                draw.text(
                    (left + 4, top + 4),
                    display_label,
                    font=label_font,
                    fill="#10291f",
                )
                draw.rectangle(
                    (left, image_top, left + cell_size - 1, image_top + cell_size - 1),
                    outline="#83938b",
                    width=1,
                )
        page_name = f"blind_review_page_{page_index:02d}.jpg"
        page.save(output_dir / page_name, quality=94, subsampling=0)
        page_names.append(page_name)
    return page_names


def _write_review_csv(output_dir: Path, cases: list[dict]) -> None:
    with (output_dir / "review_form.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "신원이 더 닮은 후보(A/B/동일/둘다부적합)",
                "8세로 더 자연스러운 후보(A/B/동일/둘다부적합)",
                "오류가 적은 후보(A/B/동일/둘다부적합)",
                "메모",
            ]
        )
        for case in cases:
            writer.writerow([case["case_id"], "", "", "", ""])


def _write_index(output_dir: Path, pages: list[str]) -> None:
    items = "\n".join(
        f'<a href="{html.escape(name)}"><img src="{html.escape(name)}" alt="{html.escape(name)}"></a>'
        for name in pages
    )
    document = f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><title>8세 얼굴 블라인드 비교</title>
<style>
body{{margin:0;padding:24px;background:#e9ede8;color:#10291f;font-family:Arial,sans-serif}}
main{{max-width:1240px;margin:auto}}img{{display:block;width:100%;height:auto;margin:0 0 24px;border-radius:12px}}
</style><main><h1>8세 얼굴 블라인드 비교</h1><p>A/B를 먼저 평가한 뒤 answer_key.json을 확인하세요.</p>{items}</main></html>"""
    (output_dir / "index.html").write_text(document, encoding="utf-8")


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required")
    if args.cases < 1 or args.rows_per_page < 1:
        raise ValueError("cases and rows-per-page must be positive")
    records = {row["record_id"]: row for row in read_jsonl(args.manifest)}
    formal_cases = [row for row in read_jsonl(args.holdouts) if row.get("formal_eval")]
    if not formal_cases:
        raise ValueError("No formal exact-age-8 cases found")
    rng = random.Random(args.seed)
    rng.shuffle(formal_cases)
    cases = formal_cases[: min(args.cases, len(formal_cases))]
    assignments = blind_assignment([case["case_id"] for case in cases], args.seed + 1)

    sources: dict[str, np.ndarray] = {}
    targets: dict[str, np.ndarray] = {}
    source_ages: dict[str, int] = {}
    for case in cases:
        source_ref = max(case["adult_only_sources"], key=lambda row: int(row["photo_age"]))
        sources[case["case_id"]] = _aligned(records, source_ref["record_id"], args.image_size)
        targets[case["case_id"]] = _aligned(
            records, case["hidden_target"]["record_id"], args.image_size
        )
        source_ages[case["case_id"]] = int(source_ref["photo_age"])

    device = torch.device("cuda")
    baseline = _generate(args.baseline, cases, sources, device)
    candidate = _generate(args.candidate, cases, sources, device)
    pages = _write_pages(
        args.output_dir,
        cases,
        sources,
        targets,
        baseline,
        candidate,
        assignments,
        rows_per_page=args.rows_per_page,
        cell_size=args.cell_size,
    )
    answer_key = {
        "warning": "Licensed AI Hub faces. Keep this directory private and do not distribute.",
        "seed": args.seed,
        "baseline_checkpoint": str(args.baseline.resolve()),
        "candidate_checkpoint": str(args.candidate.resolve()),
        "cases": [
            {
                "case_id": case["case_id"],
                "subject_id": case["subject_id"],
                "source_age": source_ages[case["case_id"]],
                **assignments[case["case_id"]],
            }
            for case in cases
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "answer_key.json").write_text(
        json.dumps(answer_key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_review_csv(args.output_dir, cases)
    _write_index(args.output_dir, pages)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "pages": pages,
                "open": str((args.output_dir / "index.html").resolve()),
                "review_form": str((args.output_dir / "review_form.csv").resolve()),
                "answer_key": str((args.output_dir / "answer_key.json").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
