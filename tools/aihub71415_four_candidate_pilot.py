"""Run one leakage-safe four-candidate age-8 pilot.

The final portrait is always produced by FLUX.2.  The four recipes deliberately
separate the questions that were previously mixed together:

* direct: adult parent -> age 8 (comparison baseline, not assumed to work);
* sequential: adaptive adjacent-age chain -> age 8;
* fran_guided: the same last accepted sequential parent plus a FRAN structure hint;
* childhood_assisted: the sequential parent plus separately trained adult and
  childhood-evidence LoRAs.

The sealed real age-8 photograph is never opened by ``prepare``, ``generate``
or ``review``.  It may only be opened by a later explicit evaluation command
after a human selection has been saved.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data/experiments/aihub71415_full/two_mode_pilot_v2"
GENERATOR = ROOT / "tools/age_generate_flux2.py"
TWO_MODE_TOOL = ROOT / "tools/aihub71415_two_mode_pilot.py"
FLUX_PYTHON = ROOT / ".venv-flux2/Scripts/python.exe"
PROJECT_PYTHON = ROOT / ".venv/Scripts/python.exe"
DEFAULT_CASE = "childhood_assisted_0137"
RECIPES = ("direct", "sequential", "fran_guided", "childhood_assisted")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and run one four-candidate age-8 pilot"
    )
    parser.add_argument(
        "command", choices=("prepare", "generate", "review", "status", "run")
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--case-id", default=DEFAULT_CASE)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument(
        "--train-steps",
        type=int,
        default=300,
        help="LoRA training steps used by the all-in-one run command.",
    )
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="The run command must use already completed LoRA weights.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-untrained",
        action="store_true",
        help="Diagnostic only: allow generation before the two LoRAs exist.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_case(root: Path, case_id: str) -> dict:
    manifest_path = root / "two_mode_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Two-mode manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    match = next(
        (case for case in manifest["cases"] if case["case_id"] == case_id), None
    )
    if match is None:
        raise ValueError(f"Unknown case: {case_id}")
    return match


def pilot_dir(root: Path, case_id: str) -> Path:
    return root / "four_candidate_pilot" / case_id


def generation_path(current_age: int) -> list[int]:
    sys.path.insert(0, str(ROOT / "backend"))
    from age_policy import path_with_refinements

    return path_with_refinements(current_age, [])


def copy_identity_sources(root: Path, case: dict, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for row in case["identity_inputs"]:
        source = root / row["path"]
        if not source.is_file():
            raise FileNotFoundError(f"Prepared identity image missing: {source}")
        target = destination / source.name
        shutil.copy2(source, target)
        copied.append(target.name)
    return copied


def base_plan(case: dict, accepted_name: str) -> dict:
    current_age = int(case["accepted_parent"]["photo_age"])
    gender = str(case.get("gender") or "unspecified")
    sex = "female" if gender == "female" else "male" if gender == "male" else gender
    return {
        "version": 1,
        "experiment_only": True,
        "case_id": case["case_id"],
        "current_age": current_age,
        "current_photo": accepted_name,
        "age_source": "aihub_labeled_photo_age",
        "biological_sex": sex,
        "population_group": "Korean",
        "extra_ages": [],
        "selections": {},
    }


def prepare(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    case = get_case(root, args.case_id)
    out = pilot_dir(root, args.case_id)
    out.mkdir(parents=True, exist_ok=True)
    accepted_name = Path(case["accepted_parent"]["path"]).name

    shared_source = out / "shared/source"
    copied = copy_identity_sources(root, case, shared_source)
    if accepted_name not in copied:
        raise RuntimeError("Accepted adult parent is absent from identity inputs")

    plan = base_plan(case, accepted_name)
    write_json(out / "shared/plan.json", plan)
    direct_plan = {**plan, "generation_path_override": [plan["current_age"], 8]}
    direct_source = out / "recipes/direct/source"
    copy_identity_sources(root, case, direct_source)
    write_json(out / "recipes/direct/plan.json", direct_plan)

    setup = {
        "version": 1,
        "case_id": args.case_id,
        "mode": case["mode"],
        "current_age": plan["current_age"],
        "target_age": 8,
        "adaptive_path": generation_path(plan["current_age"]),
        "recipes": list(RECIPES),
        "identity_token": case["identity_token"],
        "identity_lora_dir": str((root / case["identity_lora_output"]).resolve()),
        "child_lora_dir": str(
            (root / case["child_evidence_lora_output"]).resolve()
        ),
        "sealed_target_record_id": case["final_evaluation_target_record_id"],
        "sealed_target_opened": False,
        "warning": (
            "Direct generation is a comparison baseline. It is not treated as "
            "a successful or preferred recipe without measured and human evidence."
        ),
    }
    write_json(out / "pilot_setup.json", setup)
    print(f"Prepared four-candidate pilot: {out}")
    print(f"Adaptive path: {' -> '.join(map(str, setup['adaptive_path']))}")
    print("Sealed age-8 evaluation photograph was not opened.")


def find_lora(directory: Path) -> Path | None:
    preferred = directory / "pytorch_lora_weights.safetensors"
    if preferred.is_file():
        return preferred
    matches = sorted(directory.glob("*.safetensors")) if directory.is_dir() else []
    return matches[-1] if matches else None


def generator_command(
    args: argparse.Namespace,
    *,
    age: int,
    plan: Path,
    source: Path,
    candidates: Path,
    debug: Path,
    case: dict,
    seed: int,
    identity_lora: Path | None,
    child_lora: Path | None = None,
    structure_guide: Path | None = None,
) -> list[str]:
    command = [
        str(FLUX_PYTHON),
        str(GENERATOR),
        "--age", str(age),
        "--count", "1",
        "--seed", str(seed),
        "--steps", str(args.steps),
        "--plan-path", str(plan),
        "--source-dir", str(source),
        "--candidate-dir", str(candidates),
        "--debug-dir", str(debug),
        "--identity-token", case["identity_token"],
    ]
    if identity_lora is not None:
        command.extend(["--lora-path", str(identity_lora), "--lora-scale", "0.85"])
    if child_lora is not None:
        command.extend(
            ["--child-lora-path", str(child_lora), "--child-lora-scale", "0.35"]
        )
    if structure_guide is not None:
        command.extend(
            [
                "--structure-guide", str(structure_guide),
                "--structure-guide-mode", "base",
            ]
        )
    return command


def run_command(command: list[str], dry_run: bool) -> None:
    print(subprocess.list2cmdline(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def output_from_summary(debug: Path, age: int) -> Path:
    summary = read_json(debug / f"age{age:02d}_flux2_summary.json")
    outputs = summary.get("outputs") or []
    if len(outputs) != 1:
        raise RuntimeError(f"Expected one age-{age} output, found {len(outputs)}")
    path = Path(outputs[0]["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def generate_stage(
    args: argparse.Namespace,
    *,
    age: int,
    plan_path: Path,
    source: Path,
    candidates: Path,
    debug: Path,
    case: dict,
    seed: int,
    identity_lora: Path | None,
    child_lora: Path | None = None,
    structure_guide: Path | None = None,
) -> Path | None:
    command = generator_command(
        args,
        age=age,
        plan=plan_path,
        source=source,
        candidates=candidates,
        debug=debug,
        case=case,
        seed=seed,
        identity_lora=identity_lora,
        child_lora=child_lora,
        structure_guide=structure_guide,
    )
    run_command(command, args.dry_run)
    if args.dry_run:
        return None
    result = output_from_summary(debug, age)
    plan = read_json(plan_path)
    plan.setdefault("selections", {})[str(age)] = result.name
    write_json(plan_path, plan)
    return result


def copy_shared_state(out: Path, recipe: str) -> tuple[Path, Path, Path, Path]:
    recipe_dir = out / "recipes" / recipe
    source = recipe_dir / "source"
    candidates = recipe_dir / "candidates"
    debug = recipe_dir / "debug"
    shutil.copytree(out / "shared/source", source, dirs_exist_ok=True)
    shared_candidates = out / "shared/candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    if shared_candidates.is_dir():
        shutil.copytree(shared_candidates, candidates, dirs_exist_ok=True)
    shutil.copy2(out / "shared/plan.json", recipe_dir / "plan.json")
    return recipe_dir, source, candidates, debug


def make_fran_guide(
    parent: Path,
    destination: Path,
    dry_run: bool,
    source_age: int,
    target_age: int = 8,
) -> Path:
    guide = destination / "fran_structure_guide.png"
    if dry_run:
        print(f"FRAN guide: {parent} -> {guide}")
        return guide
    command = [
        str(ROOT / ".venv-age/Scripts/python.exe"),
        "-c",
        (
            "from pathlib import Path; import torch; "
            "from tools.aihub71415_guided_age8_trial import fran_structure_guide; "
            f"fran_structure_guide(Path(r'{parent}'), Path(r'{destination}'), "
            "torch.device('cuda' if torch.cuda.is_available() else 'cpu'), "
            f"source_age={source_age}, target_age={target_age})"
        ),
    ]
    run_command(command, False)
    if not guide.is_file():
        raise FileNotFoundError(guide)
    return guide


def generate(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    case = get_case(root, args.case_id)
    out = pilot_dir(root, args.case_id)
    if not (out / "pilot_setup.json").is_file():
        raise FileNotFoundError("Run prepare before generate")
    if not FLUX_PYTHON.is_file() or not GENERATOR.is_file():
        raise FileNotFoundError("FLUX runtime or generator is missing")

    identity_lora = find_lora(root / case["identity_lora_output"])
    child_lora = find_lora(root / case["child_evidence_lora_output"])
    if identity_lora is None and not args.allow_untrained:
        raise FileNotFoundError(
            "Identity LoRA is not trained. Run two_mode_pilot.py train-assisted "
            "for this case, or use --allow-untrained only for a diagnostic run."
        )
    if case["mode"] == "childhood_assisted" and child_lora is None and not args.allow_untrained:
        raise FileNotFoundError(
            "Child-evidence LoRA is not trained. The assisted candidate cannot "
            "be called assisted until that separate adapter exists."
        )

    # 1) Direct comparison baseline.
    direct = out / "recipes/direct"
    generate_stage(
        args,
        age=8,
        plan_path=direct / "plan.json",
        source=direct / "source",
        candidates=direct / "candidates",
        debug=direct / "debug",
        case=case,
        seed=args.seed,
        identity_lora=identity_lora,
    )

    # 2) Shared adaptive path down to the last parent before age 8.
    shared_plan = out / "shared/plan.json"
    shared_source = out / "shared/source"
    shared_candidates = out / "shared/candidates"
    shared_debug = out / "shared/debug"
    path = generation_path(int(case["accepted_parent"]["photo_age"]))
    for index, age in enumerate(path[1:-1], start=1):
        generate_stage(
            args,
            age=age,
            plan_path=shared_plan,
            source=shared_source,
            candidates=shared_candidates,
            debug=shared_debug,
            case=case,
            seed=args.seed + index * 10,
            identity_lora=identity_lora,
        )

    # 3) Final age-8 variants all use the same last accepted parent.  The
    # adaptive policy currently inserts age 9 between age 11 and age 8 for
    # this case, so hard-coding age 11 would compare different inputs.
    parent_age = int(path[-2])
    for offset, recipe in enumerate(("sequential", "fran_guided", "childhood_assisted"), start=1):
        recipe_dir, source, candidates, debug = copy_shared_state(out, recipe)
        plan_path = recipe_dir / "plan.json"
        plan = read_json(plan_path)
        parent_name = plan.get("selections", {}).get(str(parent_age))
        if args.dry_run:
            parent = candidates / (parent_name or f"<generated-age{parent_age:02d}>.png")
        else:
            if not parent_name:
                raise RuntimeError(
                    f"Adaptive path did not select an age-{parent_age} parent"
                )
            parent = candidates / parent_name
        guide = None
        child = None
        if recipe in {"fran_guided", "childhood_assisted"}:
            guide = make_fran_guide(
                parent,
                recipe_dir,
                args.dry_run,
                source_age=parent_age,
                target_age=8,
            )
        if recipe == "childhood_assisted":
            child = child_lora
        generate_stage(
            args,
            age=8,
            plan_path=plan_path,
            source=source,
            candidates=candidates,
            debug=debug,
            case=case,
            seed=args.seed + 100 + offset,
            identity_lora=identity_lora,
            child_lora=child,
            structure_guide=guide,
        )
    if args.dry_run:
        print("Dry run complete: no model or sealed target was opened.")
    else:
        print(f"Four candidate recipes generated under {out / 'recipes'}")
        print("The sealed real age-8 evaluation photograph remains unopened.")


def recipe_candidate(recipe_dir: Path) -> Path | None:
    summary = recipe_dir / "debug/age08_flux2_summary.json"
    if not summary.is_file():
        return None
    outputs = read_json(summary).get("outputs") or []
    if not outputs:
        return None
    path = Path(outputs[-1]["path"])
    return path if path.is_file() else None


def write_review(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    case = get_case(root, args.case_id)
    out = pilot_dir(root, args.case_id)
    review = out / "review"
    images = review / "images"
    images.mkdir(parents=True, exist_ok=True)
    source = root / case["accepted_parent"]["path"]
    shutil.copy2(source, images / f"source{source.suffix.lower()}")
    cards = []
    available = []
    for index, recipe in enumerate(RECIPES, start=1):
        candidate = recipe_candidate(out / "recipes" / recipe)
        if candidate is None:
            cards.append(
                f"<article class='missing'><h2>{html.escape(recipe)}</h2>"
                "<p>아직 생성되지 않았습니다.</p></article>"
            )
            continue
        public_name = f"candidate_{index}{candidate.suffix.lower()}"
        shutil.copy2(candidate, images / public_name)
        available.append(recipe)
        cards.append(
            f"<article><img src='images/{public_name}' alt='후보 {index}'>"
            f"<h2>후보 {index}</h2><button data-recipe='{html.escape(recipe)}'>"
            "이 후보 선택</button></article>"
        )
    page = f"""<!doctype html><html lang='ko'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>8세 얼굴 4후보 검토</title><style>
:root{{--brand:#176b48;--ink:#10271e;--line:#b8cabf;--paper:#fbfaf5}}
*{{box-sizing:border-box}}body{{margin:0;background:#edf2ed;color:var(--ink);font-family:system-ui,sans-serif}}
main{{max-width:1280px;margin:auto;padding:24px}}.source{{display:flex;align-items:center;gap:18px;background:white;padding:16px;border-radius:18px}}
.source img{{width:130px;height:160px;object-fit:cover;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:18px}}
article{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:12px}}article img{{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:12px}}
button{{width:100%;padding:12px;border:0;border-radius:10px;background:var(--brand);color:white;font-weight:700}}.missing{{min-height:260px}}#result{{margin-top:18px;padding:16px;background:white;border-left:5px solid var(--brand)}}
@media(max-width:800px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:480px){{.grid{{grid-template-columns:1fr}}}}
</style><main><h1>8세 얼굴 4후보 검토</h1><p>직접 생성은 비교 기준이며 성공으로 간주하지 않습니다. 자동 추천과 숨은 정답 사진은 아직 공개하지 않습니다.</p>
<section class='source'><img src='images/source{source.suffix.lower()}' alt='성인 기준 사진'><div><b>성인 기준 사진</b><p>{case['accepted_parent']['photo_age']}세 → 목표 8세</p></div></section>
<section class='grid'>{''.join(cards)}</section><div id='result'>선택 전</div></main><script>
document.querySelectorAll('[data-recipe]').forEach(button=>button.onclick=()=>{{
 const payload={{case_id:{json.dumps(args.case_id)},selected_recipe:button.dataset.recipe,selected_at:new Date().toISOString()}};
 localStorage.setItem('age8-four-candidate-selection',JSON.stringify(payload));
 document.querySelector('#result').textContent='선택: '+button.closest('article').querySelector('h2').textContent+' · 결과가 이 브라우저에 저장되었습니다.';
}});
</script></html>"""
    (review / "index.html").write_text(page, encoding="utf-8")
    write_json(
        review / "review_manifest.json",
        {
            "case_id": args.case_id,
            "available_recipes": available,
            "sealed_target_opened": False,
            "recipe_labels_hidden_in_html": True,
        },
    )
    print(review / "index.html")


def status(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    case = get_case(root, args.case_id)
    out = pilot_dir(root, args.case_id)
    rows = {
        "prepared": (out / "pilot_setup.json").is_file(),
        "identity_lora": str(find_lora(root / case["identity_lora_output"]) or "missing"),
        "child_lora": str(find_lora(root / case["child_evidence_lora_output"]) or "missing"),
        "candidates": {
            recipe: str(recipe_candidate(out / "recipes" / recipe) or "missing")
            for recipe in RECIPES
        },
        "review": str(out / "review/index.html"),
        "sealed_target_opened": False,
    }
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def train_required_loras(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    case = get_case(root, args.case_id)
    identity_lora = find_lora(root / case["identity_lora_output"])
    child_lora = find_lora(root / case["child_evidence_lora_output"])
    if identity_lora is not None and child_lora is not None:
        print("Both completed LoRA adapters already exist; training skipped.")
        return
    if args.skip_training:
        raise FileNotFoundError(
            "--skip-training was requested, but one or both completed LoRA weights are missing."
        )
    if identity_lora is None and child_lora is None:
        training_command = "train-assisted"
    elif identity_lora is None:
        training_command = "train-identity"
    else:
        training_command = "train-child-evidence"
    command = [
        str(PROJECT_PYTHON),
        str(TWO_MODE_TOOL),
        training_command,
        "--output",
        str(root),
        "--case-id",
        args.case_id,
        "--steps",
        str(args.train_steps),
    ]
    if args.dry_run:
        command.append("--dry-run")
    run_command(command, args.dry_run)


def run_all(args: argparse.Namespace) -> None:
    """Run preparation, adapter training, generation and review in one command."""
    prepare(args)
    train_required_loras(args)
    if args.dry_run:
        args.allow_untrained = True
    generate(args)
    if not args.dry_run:
        write_review(args)


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "generate":
        generate(args)
    elif args.command == "review":
        write_review(args)
    elif args.command == "status":
        status(args)
    else:
        run_all(args)


if __name__ == "__main__":
    main()
