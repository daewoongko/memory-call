"""Build a controlled three-way face-ageing comparison report.

The comparison reuses the leakage-safe held-out subject from
``aihub71415_sequential_flux_eval`` and compares:

1. baseline sequential FLUX generation,
2. the same FLUX path with the paired age LoRA, and
3. a strong child-face generator path.

The real younger photographs remain evaluation-only.  They are never used to
rank or select generated candidates.  The strong generator does not expose a
seed control, so the report records that limitation instead of claiming an
exact same-seed comparison.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT / "tools" / "face_aging") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "face_aging"))

from age_validate_flux2 import largest_face, make_analyzer, read_rgb  # noqa: E402

TARGETS = (32, 26, 20, 15, 11, 8)
RECIPES = ("baseline", "paired_adapter", "strong_child")
DISPLAY_NAMES = {
    "baseline": "기본 FLUX 순차 생성",
    "paired_adapter": "FLUX + 연령 LoRA",
    "strong_child": "강한 아동 얼굴 생성",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def stage_for(report: dict, target_age: int) -> dict:
    return next(
        stage for stage in report["stages"] if int(stage["target_age"]) == target_age
    )


def load_generation_reports(source: Path, output: Path) -> dict[str, dict]:
    reports = {
        recipe: read_json(source / f"generation_{recipe}.json")
        for recipe in ("baseline", "paired_adapter")
    }
    strong_stages: list[dict] = []
    for target_age in TARGETS:
        stage_dir = output / "generated" / "strong_child" / f"age{target_age:02d}"
        ranking = read_json(stage_dir / "ranking.json")
        # Keep the experimental budget honest: show all four generated
        # candidates even when the adult-source identity gate rejects one.
        # The automatic next parent still comes from the valid ranking.
        visible = ranking["all_ranked"][:4]
        selected = ranking["valid_ranked"][0] if ranking["valid_ranked"] else visible[0]
        strong_stages.append(
            {
                "parent_age": 38 if target_age == 32 else TARGETS[TARGETS.index(target_age) - 1],
                "target_age": target_age,
                "generated": len(list(stage_dir.glob("candidate_*.png"))),
                "visible": visible,
                "automatic_next_parent": str(
                    (stage_dir / selected["filename"]).relative_to(output)
                ),
                "seconds": None,
            }
        )
    reports["strong_child"] = {
        "recipe": "strong_child",
        "hidden_targets_opened": False,
        "seed_control": "unavailable_for_builtin_imagegen",
        "stages": strong_stages,
    }
    write_json(output / "generation_strong_child.json", reports["strong_child"])
    return reports


def candidate_path(
    recipe: str, target_age: int, filename: str, source: Path, output: Path
) -> Path:
    root = output if recipe == "strong_child" else source
    return root / "generated" / recipe / f"age{target_age:02d}" / filename


def evaluate(
    reports: dict[str, dict], source: Path, output: Path
) -> tuple[list[dict], dict[str, dict]]:
    identity_app = make_analyzer("buffalo_l", include_age=False)
    hidden_paths = {
        age: source / "evaluation_only" / f"age{age:02d}.png" for age in TARGETS
    }
    hidden_embeddings = {
        age: largest_face(identity_app, read_rgb(path)).normed_embedding
        for age, path in hidden_paths.items()
    }

    metrics: list[dict] = []
    for recipe in RECIPES:
        for target_age in TARGETS:
            stage = stage_for(reports[recipe], target_age)
            for rank, row in enumerate(stage["visible"], start=1):
                path = candidate_path(
                    recipe, target_age, row["filename"], source, output
                )
                embedding = largest_face(identity_app, read_rgb(path)).normed_embedding
                estimated_age = float(row["estimated_age"])
                metrics.append(
                    {
                        "recipe": recipe,
                        "target_age": target_age,
                        "visible_rank": rank,
                        "filename": row["filename"],
                        "estimated_age": estimated_age,
                        "target_age_error": round(abs(estimated_age - target_age), 6),
                        "identity_to_hidden_same_age": round(
                            float(embedding @ hidden_embeddings[target_age]), 6
                        ),
                        "automatic_selected_for_next_stage": (
                            row["filename"]
                            == Path(stage["automatic_next_parent"]).name
                        ),
                    }
                )

    summary: dict[str, dict] = {}
    for recipe in RECIPES:
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
                float(np.mean([row["target_age_error"] for row in selected])), 6
            ),
            "top4_target_age_mae": round(
                float(np.mean([row["target_age_error"] for row in recipe_rows])), 6
            ),
        }
    return metrics, summary


def copy_review_asset(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.as_posix()


def write_blind_review(
    reports: dict[str, dict], source: Path, output: Path, metrics: list[dict]
) -> dict[str, str]:
    review = output / "review"
    assets = review / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True, exist_ok=True)

    shuffled = list(RECIPES)
    random.Random(20260820).shuffle(shuffled)
    mapping = {chr(ord("A") + index): recipe for index, recipe in enumerate(shuffled)}
    write_json(output / "blind_mapping.json", mapping)

    source_rel = copy_review_asset(
        source / "source" / "age38.png", assets / "source_age38.png"
    )
    sections: list[str] = []
    for target_age in TARGETS:
        arms: list[str] = []
        for label, recipe in mapping.items():
            stage = stage_for(reports[recipe], target_age)
            figures: list[str] = []
            for rank, row in enumerate(stage["visible"], start=1):
                src = candidate_path(
                    recipe, target_age, row["filename"], source, output
                )
                rel = copy_review_asset(
                    src,
                    assets / label / f"age{target_age:02d}" / f"candidate_{rank:02d}.png",
                )
                metric = next(
                    item
                    for item in metrics
                    if item["recipe"] == recipe
                    and item["target_age"] == target_age
                    and item["visible_rank"] == rank
                )
                figures.append(
                    f'<figure><button class="pick" data-age="{target_age}" '
                    f'data-arm="{label}" data-rank="{rank}">'
                    f'<img src="{html.escape(Path(rel).relative_to(review).as_posix())}" '
                    f'alt="{target_age}세 후보 {rank}"></button>'
                    f'<figcaption>후보 {rank}<span>자동 추정 {metric["estimated_age"]:.0f}세</span></figcaption>'
                    "</figure>"
                )
            arms.append(
                f'<article class="arm"><h3>경로 {label}</h3><div class="candidate-grid">'
                + "".join(figures)
                + "</div></article>"
            )
        sections.append(
            f'<section><div class="stage-head"><h2>목표 {target_age}세</h2>'
            '<p>같은 사람처럼 보이는지와 목표 연령처럼 보이는지를 함께 판단하세요.</p></div>'
            + "".join(arms)
            + "</section>"
        )

    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>세 경로 블라인드 비교</title><style>
:root{{--bg:#f4f3ec;--paper:#fffefa;--ink:#10291f;--brand:#176b48;--line:#b9c7bd;--accent:#e77a24}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,sans-serif}}
main{{max-width:1480px;margin:auto;padding:28px}}header,section{{background:var(--paper);border:1px solid var(--line);border-radius:24px;padding:24px;margin:0 0 22px}}
header{{display:grid;grid-template-columns:180px 1fr;gap:24px;align-items:center}}header img{{width:180px;aspect-ratio:1;object-fit:cover;border-radius:20px}}
h1{{font-size:34px;margin:0 0 10px}}h2{{font-size:26px;margin:0}}h3{{font-size:20px;margin:20px 0 12px}}p{{line-height:1.6;margin:6px 0}}
.notice{{border-left:5px solid var(--brand);padding:12px 16px;background:#f1f7f3}}.stage-head{{display:flex;justify-content:space-between;align-items:end;gap:18px;border-bottom:1px solid var(--line);padding-bottom:14px}}
.candidate-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}figure{{margin:0}}.pick{{display:block;border:3px solid transparent;border-radius:18px;padding:0;background:none;width:100%;cursor:pointer}}
.pick:hover,.pick.selected{{border-color:var(--accent)}}figure img{{display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:14px}}
figcaption{{font-weight:750;padding:8px 4px}}figcaption span{{display:block;color:#5b6d63;font-size:13px;font-weight:500;margin-top:3px}}
#status{{position:fixed;right:20px;bottom:20px;background:var(--ink);color:white;padding:12px 16px;border-radius:999px;box-shadow:0 12px 30px #0003}}
@media(max-width:850px){{main{{padding:12px}}header{{grid-template-columns:90px 1fr;padding:16px}}header img{{width:90px}}h1{{font-size:25px}}section{{padding:16px}}.stage-head{{display:block}}.candidate-grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main><header><img src="{html.escape(Path(source_rel).relative_to(review).as_posix())}" alt="38세 기준 사진"><div><h1>세 경로 블라인드 비교</h1>
<div class="notice">A/B/C 생성법은 숨겼습니다. 각 연령에서 가장 자연스럽고 같은 사람처럼 보이는 후보를 누르세요. 자동 연령값은 참고용이며 아동 얼굴에서 과대 추정될 수 있습니다.</div>
<p>통제: 같은 인물 · 같은 연령 단계 · 같은 후보 수 · 같은 자동 평가기. 강한 생성기는 시드를 고정할 수 없어 동일 시드 조건에서는 제외했습니다.</p></div></header>
{''.join(sections)}</main><div id="status">선택 0 / {len(TARGETS) * len(RECIPES)}</div><script>
const choices={{}};document.querySelectorAll('.pick').forEach(button=>button.addEventListener('click',()=>{{
 const key=button.dataset.age+'-'+button.dataset.arm;document.querySelectorAll(`.pick[data-age="${{button.dataset.age}}"][data-arm="${{button.dataset.arm}}"]`).forEach(item=>item.classList.remove('selected'));
 button.classList.add('selected');choices[key]=Number(button.dataset.rank);document.getElementById('status').textContent='선택 '+Object.keys(choices).length+' / {len(TARGETS) * len(RECIPES)}';
}}));</script></body></html>"""
    (review / "index.html").write_text(page, encoding="utf-8")
    return mapping


def write_summary_review(output: Path, summary: dict[str, dict]) -> None:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(DISPLAY_NAMES[recipe])}</td>"
        f"<td>{values['selected_hidden_identity_mean']:.3f}</td>"
        f"<td>{values['top4_hidden_identity_mean']:.3f}</td>"
        f"<td>{values['selected_target_age_mae']:.2f}세</td>"
        f"<td>{values['top4_target_age_mae']:.2f}세</td>"
        "</tr>"
        for recipe, values in summary.items()
    )
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>세 경로 자동 평가</title><style>body{{font-family:system-ui;background:#f4f3ec;color:#10291f;margin:0;padding:28px}}main{{max-width:1100px;margin:auto;background:white;padding:28px;border:1px solid #b9c7bd;border-radius:24px}}table{{border-collapse:collapse;width:100%;margin:24px 0}}th,td{{padding:14px;border-bottom:1px solid #cbd5ce;text-align:right}}th:first-child,td:first-child{{text-align:left}}.warn{{padding:16px;background:#fff4e9;border-left:5px solid #e77a24;line-height:1.6}}</style><main><h1>세 경로 자동 평가</h1><table><thead><tr><th>경로</th><th>선택 후보 실제 연령 신원</th><th>상위 4장 실제 연령 신원</th><th>선택 후보 연령 MAE</th><th>상위 4장 연령 MAE</th></tr></thead><tbody>{rows}</tbody></table>
<div class="warn">신원 유사도는 높을수록, 연령 MAE는 낮을수록 좋습니다. 다만 현재 자동 연령 추정기는 한국인 아동 얼굴을 성인으로 과대 추정하는 사례가 확인되어, 아동다움의 최종 판단은 블라인드 시각 평가와 함께 해야 합니다. 강한 생성기는 시드 제어가 없어 기본 FLUX와 완전히 동일한 난수 조건 비교가 아닙니다.</div></main></html>"""
    (output / "review" / "summary.html").write_text(page, encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = load_generation_reports(args.source, args.output)
    metrics, summary = evaluate(reports, args.source, args.output)
    mapping = write_blind_review(reports, args.source, args.output, metrics)
    write_summary_review(args.output, summary)
    comparison = {
        "version": 1,
        "subject_id": read_json(args.source / "manifest.json")["subject_id"],
        "controls": {
            "source_age": 38,
            "target_ages": list(TARGETS),
            "candidate_counts": {"32": 6, "26": 6, "20": 4, "15": 4, "11": 4, "8": 4},
            "baseline_and_lora_seed_base": 971500,
            "strong_generator_seed_control": "unavailable_for_builtin_imagegen",
            "hidden_targets_used_for_generation_or_ranking": False,
        },
        "summary": summary,
        "metrics": metrics,
        "blind_mapping_file": "blind_mapping.json",
        "limitations": [
            "The strong generator does not expose deterministic seed control.",
            "The automatic age estimator overestimates several Korean child faces.",
            "Hidden same-age photographs are evaluation-only and were not used for generation or ranking.",
            "Visual blind review is required before choosing a production generator.",
        ],
    }
    write_json(args.output / "comparison_report.json", comparison)
    print(json.dumps({"summary": summary, "blind_mapping": mapping}, ensure_ascii=False, indent=2))
    print(f"Blind review: {args.output / 'review' / 'index.html'}")
    print(f"Metric summary: {args.output / 'review' / 'summary.html'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data" / "experiments" / "aihub71415_sequential_flux_eval",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "experiments" / "age_generator_three_way_compare",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
