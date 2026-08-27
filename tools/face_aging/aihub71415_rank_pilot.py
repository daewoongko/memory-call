"""Prepare and fit a small, leakage-safe age-candidate ranking pilot.

The pilot deliberately separates three concerns:

* invalid images are removed by hard gates;
* people provide blind pairwise preferences;
* only generation-time features are allowed in the fitted ranker.

The sealed real age-8 portrait is not an input to this script.  It remains an
evaluation-only asset in the existing full-pipeline experiment.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/experiments/aihub71415_full/full_pipeline_pilot"
OUTPUT = ROOT / "data/experiments/aihub71415_full/ranking_pilot"
FEATURES = ("age_fit", "identity")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _quality_gate(row: dict) -> bool:
    """Conservative acquisition gate, not a perceptual-quality score."""
    return (
        int(row.get("face_count", 0)) == 1
        and float(row.get("sharpness", 0.0)) >= 20.0
        and 40.0 <= float(row.get("brightness", 0.0)) <= 220.0
    )


def _features(row: dict) -> dict[str, float]:
    # Age-fit is bounded and interpretable: one at the target, decaying with
    # absolute error.  Ten years is intentionally a scale, not a learned
    # scientific constant; the learned coefficient determines its influence.
    age_error = float(row["aihub_age_mae"])
    return {
        "age_fit": math.exp(-age_error / 10.0),
        "identity": max(-1.0, min(1.0, float(row["identity_to_adult_source"]))),
    }


def _choose_four(rows: list[dict]) -> list[dict]:
    """Keep method diversity, then add the strongest unused age candidate."""
    passing = [row for row in rows if _quality_gate(row)]
    by_recipe: dict[str, list[dict]] = {}
    for row in passing:
        by_recipe.setdefault(row["recipe"], []).append(row)
    chosen: list[dict] = []
    for recipe in sorted(by_recipe):
        chosen.append(max(by_recipe[recipe], key=lambda row: row["identity_to_adult_source"]))
    remaining = [row for row in passing if row not in chosen]
    if remaining and len(chosen) < 4:
        chosen.append(min(remaining, key=lambda row: row["aihub_age_mae"]))
    if len(chosen) < 4:
        raise RuntimeError("A case needs at least four quality-gated candidates")
    return chosen[:4]


def prepare() -> None:
    report = _load_json(SOURCE / "evaluation_report.json")
    manifest = _load_json(SOURCE / "pilot_manifest.json")
    rows_by_case: dict[str, list[dict]] = {}
    for row in report["rows"]:
        rows_by_case.setdefault(row["case_id"], []).append(row)
    cases_by_id = {case["case_id"]: case for case in manifest["cases"]}

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    (OUTPUT / "images").mkdir(parents=True)

    randomizer = random.Random(20260818)
    public_cases = []
    private_mapping = {}
    comparisons = []
    for case_id in sorted(rows_by_case):
        chosen = _choose_four(rows_by_case[case_id])
        labels = list("ABCD")
        randomizer.shuffle(labels)
        source_rel = cases_by_id[case_id]["accepted_parent"]["path"]
        source_path = SOURCE / source_rel
        source_name = f"{case_id}_source{source_path.suffix.lower()}"
        shutil.copy2(source_path, OUTPUT / "images" / source_name)
        candidates = []
        for label, row in zip(labels, chosen):
            original = SOURCE / row["path"]
            public_name = f"{case_id}_{label}{original.suffix.lower()}"
            shutil.copy2(original, OUTPUT / "images" / public_name)
            candidates.append({"label": label, "image": f"images/{public_name}"})
            private_mapping[f"{case_id}:{label}"] = {
                "source_path": row["path"],
                "recipe": row["recipe"],
                "seed": row["seed"],
                "quality_gate": True,
                "features": _features(row),
            }
        public_cases.append(
            {
                "case_id": case_id,
                "source": f"images/{source_name}",
                "source_age": cases_by_id[case_id]["accepted_parent"]["photo_age"],
                "target_age": cases_by_id[case_id]["target_age"],
                "candidates": candidates,
            }
        )
        labels = sorted(item["label"] for item in candidates)
        for left_index in range(len(labels)):
            for right_index in range(left_index + 1, len(labels)):
                left, right = labels[left_index], labels[right_index]
                if randomizer.random() < 0.5:
                    left, right = right, left
                comparisons.append(
                    {"case_id": case_id, "left": left, "right": right, "choice": ""}
                )

    (OUTPUT / "pilot_public.json").write_text(
        json.dumps({"cases": public_cases}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT / "feature_mapping_private.json").write_text(
        json.dumps(private_mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUTPUT / "pairwise_labels.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=("case_id", "left", "right", "choice"))
        writer.writeheader()
        writer.writerows(comparisons)

    cards = []
    case_lookup = {case["case_id"]: case for case in public_cases}
    for index, comparison in enumerate(comparisons, start=1):
        case = case_lookup[comparison["case_id"]]
        image_by_label = {item["label"]: item["image"] for item in case["candidates"]}
        pair_class = "pair active" if index == 1 else "pair"
        cards.append(
            f"""<section class='{pair_class}' data-case='{html.escape(comparison['case_id'])}' data-left='{comparison['left']}' data-right='{comparison['right']}'>
<header><b>{index:02d} / {len(comparisons)}</b><span>기준 사진 {case['source_age']}세 → 목표 {case['target_age']}세</span></header>
<div class='source'><img src='{case['source']}' alt='현재 기준 사진'><small>현재 기준 사진</small></div>
<div class='choices'>
<button data-choice='left'><img src='{image_by_label[comparison['left']]}' alt='왼쪽 후보'><strong>왼쪽이 더 가깝다</strong></button>
<button data-choice='tie'><strong>판단하기 어렵다</strong></button>
<button data-choice='right'><img src='{image_by_label[comparison['right']]}' alt='오른쪽 후보'><strong>오른쪽이 더 가깝다</strong></button>
</div></section>"""
        )
    page = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>8세 얼굴 후보 블라인드 순위</title><style>
:root{{--ink:#173126;--green:#176b48;--line:#cad8cf;--paper:#fbfaf5}}*{{box-sizing:border-box}}body{{margin:0;background:#edf2ed;color:var(--ink);font-family:system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:28px}}h1{{margin-bottom:8px}}.guide{{padding:16px;border-left:5px solid var(--green);background:white}}.pair{{display:none;margin-top:22px;padding:20px;border:1px solid var(--line);border-radius:18px;background:var(--paper)}}.pair.active{{display:block}}header{{display:flex;justify-content:space-between}}.source{{display:grid;place-items:center;margin:18px}}.source img{{width:140px;height:170px;object-fit:cover;border-radius:12px}}.source small{{margin-top:5px}}.choices{{display:grid;grid-template-columns:1fr 150px 1fr;gap:18px;align-items:center}}button{{border:1px solid var(--line);border-radius:14px;background:white;color:inherit;font:inherit;cursor:pointer}}button img{{display:block;width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:13px 13px 0 0}}button strong{{display:block;padding:14px}}button:hover{{outline:4px solid #9ed5b9}}#status{{margin-top:18px;font-weight:700}}#download{{display:none;margin-top:14px;padding:14px 20px;background:var(--green);color:white}}@media(max-width:700px){{main{{padding:14px}}.choices{{grid-template-columns:1fr 1fr}}.choices button:nth-child(2){{grid-column:1/-1;grid-row:2}}}}
</style><main><h1>블라인드 후보 순위 파일럿</h1><p class='guide'>기준 사진을 보고, 두 후보 중 <b>같은 사람이 실제 8세였을 모습</b>에 더 가까운 쪽을 고르세요. 생성법과 자동 점수는 숨겼습니다. 확신이 없으면 판단하기 어렵다를 선택하세요.</p>{''.join(cards)}<p id='status'></p><button id='download'>결과 CSV 저장</button></main><script>
const pairs=[...document.querySelectorAll('.pair')], answers=[];let current=0;function show(){{pairs.forEach((p,i)=>p.classList.toggle('active',i===current));document.querySelector('#status').textContent=`${{Math.min(current+1,pairs.length)}} / ${{pairs.length}}`;}}pairs.forEach(pair=>pair.querySelectorAll('[data-choice]').forEach(button=>button.onclick=()=>{{answers.push({{case_id:pair.dataset.case,left:pair.dataset.left,right:pair.dataset.right,choice:button.dataset.choice}});current++;if(current<pairs.length)show();else{{pairs.forEach(p=>p.classList.remove('active'));document.querySelector('#status').textContent='18개 비교가 끝났습니다. CSV를 저장해 주세요.';document.querySelector('#download').style.display='block';}}}}));document.querySelector('#download').onclick=()=>{{const rows=['case_id,left,right,choice',...answers.map(x=>`${{x.case_id}},${{x.left}},${{x.right}},${{x.choice}}`)];const blob=new Blob([String.fromCharCode(0xfeff)+rows.join('\\n')],{{type:'text/csv;charset=utf-8'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='pairwise_labels.csv';a.click();}};show();
</script></html>"""
    (OUTPUT / "index.html").write_text(page, encoding="utf-8")
    print(f"Prepared {len(public_cases)} subjects and {len(comparisons)} blind comparisons")
    print(OUTPUT / "index.html")


def _read_labels(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    valid = [row for row in rows if row.get("choice") in {"left", "right", "tie"}]
    if not valid:
        raise ValueError("No labels found. Complete the blind comparison and provide its CSV.")
    return valid


def _pair_delta(mapping: dict, row: dict) -> tuple[list[float], float] | None:
    if row["choice"] == "tie":
        return None
    left = mapping[f"{row['case_id']}:{row['left']}"]["features"]
    right = mapping[f"{row['case_id']}:{row['right']}"]["features"]
    delta = [float(left[name]) - float(right[name]) for name in FEATURES]
    target = 1.0 if row["choice"] == "left" else -1.0
    return delta, target


def _accuracy(examples: list[tuple[list[float], float]], age_weight: float) -> float:
    if not examples:
        return float("nan")
    weights = (age_weight, 1.0 - age_weight)
    correct = sum(
        1 for delta, target in examples if target * sum(w * value for w, value in zip(weights, delta)) > 0
    )
    return correct / len(examples)


def _best_weight(examples: list[tuple[list[float], float]]) -> tuple[float, float]:
    candidates = [(step / 100.0, _accuracy(examples, step / 100.0)) for step in range(101)]
    best_accuracy = max(score for _, score in candidates)
    tied = [weight for weight, score in candidates if score == best_accuracy]
    # The centre of a plateau is less brittle than its first endpoint.
    return sum(tied) / len(tied), best_accuracy


def fit(labels_path: Path) -> None:
    mapping = _load_json(OUTPUT / "feature_mapping_private.json")
    labels = _read_labels(labels_path)
    examples_by_case: dict[str, list[tuple[list[float], float]]] = {}
    for row in labels:
        example = _pair_delta(mapping, row)
        if example is not None:
            examples_by_case.setdefault(row["case_id"], []).append(example)
    examples = [item for group in examples_by_case.values() for item in group]
    age_weight, train_accuracy = _best_weight(examples)
    folds = []
    for held_out in sorted(examples_by_case):
        train = [item for case_id, group in examples_by_case.items() if case_id != held_out for item in group]
        test = examples_by_case[held_out]
        fold_weight, _ = _best_weight(train)
        folds.append(
            {
                "held_out_subject": held_out,
                "age_weight": round(fold_weight, 4),
                "identity_weight": round(1.0 - fold_weight, 4),
                "test_pairwise_accuracy": round(_accuracy(test, fold_weight), 4),
                "test_pairs": len(test),
            }
        )
    result = {
        "status": "pilot_only_not_production",
        "subjects": len(examples_by_case),
        "labeled_non_tie_pairs": len(examples),
        "weights": {
            "target_age_accuracy": round(age_weight, 4),
            "identity_preservation": round(1.0 - age_weight, 4),
        },
        "training_pairwise_accuracy": round(train_accuracy, 4),
        "leave_one_subject_out": folds,
        "hard_gate": "single face, sharpness >= 20, brightness 40..220",
        "excluded_from_weight_fit": [
            "sealed real age-8 portrait",
            "target LPIPS/L1",
            "identity similarity to sealed age-8 portrait",
            "recipe name and seed",
        ],
        "limitations": [
            "Three subjects can verify the procedure but cannot establish final weights.",
            "Naturalness still requires human preference labels until a validated FIQA model is added.",
            "Continuity is ranked separately only when adjacent age anchors exist.",
        ],
    }
    (OUTPUT / "fit_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "fit"))
    parser.add_argument("--labels", type=Path, default=OUTPUT / "pairwise_labels.csv")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        fit(args.labels)


if __name__ == "__main__":
    main()
