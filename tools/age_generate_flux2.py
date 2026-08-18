"""Generate plausible past-age portraits with local FLUX.2 Klein.

Only the current user-uploaded portraits in ``data/faces/source`` are used as
image references.  Existing experimental age anchors are deliberately ignored.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from diffusers import (
    Flux2KleinInpaintPipeline,
    Flux2Transformer2DModel,
)
from PIL import Image, ImageFilter, ImageOps

from flux2_fp8_probe import CHECKPOINT, CONFIG_REPO, load_dequantized_state_dict


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_feedback import base_edit_strength  # noqa: E402
from age_growth import growth_prior  # noqa: E402
from age_metadata import prompt_demographic_description  # noqa: E402
from age_policy import path_with_refinements  # noqa: E402

SOURCE_DIR = ROOT / "data" / "faces" / "source"
CANDIDATE_DIR = ROOT / "data" / "faces" / "age_candidates"
DEBUG_DIR = ROOT / "data" / "faces" / "age_debug"
PLAN_PATH = ROOT / "data" / "faces" / "age_plan.json"
DEFAULT_MASK_PATH = ROOT / "data" / "faces" / "age_mask" / "current_change_mask.png"
MODELS_ROOT = Path(
    os.getenv("MEMORY_CALL_MODELS_DIR", str(Path.home() / "Models"))
).expanduser().resolve()
COMPONENTS = Path(
    os.getenv("FLUX2_COMPONENTS_DIR", str(MODELS_ROOT / "FLUX2-klein-4B-components"))
).expanduser().resolve()
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, default=16)
    parser.add_argument(
        "--control-age",
        "--conditioning-age",
        dest="control_age",
        type=int,
        default=None,
        help=(
            "Internal prompt set-point used to compensate editor age bias. "
            "Validation and filenames still retain --age as the real target."
        ),
    )
    parser.add_argument(
        "--reference-count",
        type=int,
        choices=range(1, 6),
        default=5,
        help="Use the primary current photo plus this many total references.",
    )
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument(
        "--edit-strength",
        type=float,
        default=None,
        help="Masked edit strength. By default it is derived from the age gap.",
    )
    parser.add_argument(
        "--mask-path",
        type=Path,
        default=DEFAULT_MASK_PATH,
        help="White pixels are age-edited; black pixels remain unchanged.",
    )
    parser.add_argument(
        "--structure-guide",
        type=Path,
        default=None,
        help="Optional FRAN/SAM geometry guide. It is not an identity reference.",
    )
    parser.add_argument(
        "--structure-guide-mode",
        choices=("base", "reference"),
        default="base",
        help=(
            "Use the structure guide as the inpaint base (recommended), or keep "
            "the legacy behavior that supplies it only as an auxiliary reference."
        ),
    )
    parser.add_argument(
        "--relative-passage-mode",
        action="store_true",
        help=(
            "Treat --age as an ordered morph-keyframe label and allow a younger "
            "--control-age with a structure guide. Exact apparent age remains "
            "advisory; identity, visible younger direction, and morph continuity "
            "remain required."
        ),
    )
    parser.add_argument(
        "--lora-path",
        type=Path,
        default=None,
        help="Optional identity LoRA safetensors file trained for this person.",
    )
    parser.add_argument(
        "--lora-scale",
        type=float,
        default=1.0,
        help="Identity LoRA strength. The practical test range is 0.6 to 1.0.",
    )
    parser.add_argument(
        "--identity-token",
        type=str,
        default="pj02person",
        help="Trigger token used in the identity LoRA training prompt.",
    )
    parser.add_argument(
        "--child-lora-path",
        type=Path,
        default=None,
        help=(
            "Optional childhood-evidence LoRA. It is kept separate from the "
            "adult identity LoRA so adult-only and assisted modes cannot leak."
        ),
    )
    parser.add_argument(
        "--child-lora-scale",
        type=float,
        default=0.35,
        help="Child-evidence adapter strength; identity remains the primary adapter.",
    )
    parser.add_argument("--plan-path", type=Path, default=PLAN_PATH)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--candidate-dir", type=Path, default=CANDIDATE_DIR)
    parser.add_argument("--debug-dir", type=Path, default=DEBUG_DIR)
    return parser.parse_args()


def load_plan(plan_path: Path = PLAN_PATH) -> dict:
    if not plan_path.is_file():
        raise FileNotFoundError(f"Age plan not found: {plan_path}")
    return json.loads(plan_path.read_text(encoding="utf-8"))


def generation_path_for_plan(plan: dict) -> list[int]:
    """Return the saved adaptive path or an isolated experiment override.

    Production plans continue to use ``path_with_refinements``.  The override
    exists only so a leakage-safe experiment can compare a direct 26->8 edit
    with the unchanged adaptive sequential path without copying production
    photos into ``data/faces``.
    """
    current_age = int(plan.get("current_age", 0))
    override = plan.get("generation_path_override")
    if override is None:
        return path_with_refinements(current_age, plan.get("extra_ages") or [])
    if not isinstance(override, list) or len(override) < 2:
        raise ValueError("generation_path_override must contain at least two ages")
    path = [int(age) for age in override]
    if path[0] != current_age or path[-1] != 8:
        raise ValueError(
            "generation_path_override must start at current_age and end at age 8"
        )
    if any(younger >= older for older, younger in zip(path, path[1:])):
        raise ValueError("generation_path_override must be strictly descending")
    if len(path) != len(set(path)):
        raise ValueError("generation_path_override must not repeat an age")
    return path


def resolve_current_reference_paths(
    plan: dict, source_dir: Path = SOURCE_DIR
) -> list[Path]:
    paths = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not paths:
        raise FileNotFoundError(f"No current photos found: {source_dir}")

    current_name = str(plan.get("current_photo", ""))
    primary = next((path for path in paths if path.name == current_name), None)
    if primary is None:
        raise FileNotFoundError(
            "The current representative photo in age_plan.json was not found: "
            f"{current_name}"
        )

    return [primary, *(path for path in paths if path != primary)]


def resolve_stage_reference_paths(
    plan: dict,
    target_age: int,
    reference_count: int,
    source_dir: Path = SOURCE_DIR,
    candidate_dir: Path = CANDIDATE_DIR,
) -> tuple[int, list[Path]]:
    """Use the accepted adjacent older anchor as composition reference.

    The real uploaded portraits remain identity references. Generated images
    are never added to the identity-training set and only the explicitly
    selected adjacent anchor may become the next stage's base image.
    """
    current_age = int(plan.get("current_age", 0))
    generation_path = generation_path_for_plan(plan)
    if target_age not in generation_path[1:]:
        allowed = ", ".join(str(age) for age in generation_path[1:])
        raise ValueError(f"Target age must be in the saved path: {allowed}")

    target_index = generation_path.index(target_age)
    parent_age = generation_path[target_index - 1]
    current_paths = resolve_current_reference_paths(plan, source_dir)
    if parent_age == current_age:
        references = current_paths
    else:
        selected_name = (plan.get("selections") or {}).get(str(parent_age))
        if not selected_name:
            raise ValueError(
                f"Select an approved age-{parent_age} candidate before "
                f"generating age {target_age}."
            )
        safe_name = Path(str(selected_name)).name
        if safe_name != selected_name:
            raise ValueError("Invalid selected parent filename")
        parent_path = candidate_dir / safe_name
        if not parent_path.is_file():
            raise FileNotFoundError(f"Selected parent anchor not found: {parent_path}")
        references = [parent_path, *current_paths]

    unique: list[Path] = []
    for path in references:
        if path not in unique:
            unique.append(path)
    return parent_age, unique[:reference_count]


def prepare_image(path: Path, width: int, height: int) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return ImageOps.fit(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def prepare_mask(path: Path, width: int, height: int) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(f"Age edit mask not found: {path}")
    with Image.open(path) as source:
        mask = ImageOps.exif_transpose(source).convert("L")
    mask = ImageOps.fit(
        mask,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    return mask.filter(ImageFilter.GaussianBlur(radius=10))


def edit_strength_for_gap(year_gap: int) -> float:
    """Keep subtle adult edits close to the accepted parent image."""
    return base_edit_strength(year_gap, 0)


def relative_growth_guidance(parent_age: int, target_age: int) -> str:
    """Describe common backward growth directions without erasing individuality."""
    if target_age >= 22:
        return (
            f"Relative to the accepted age-{parent_age} base, make only a subtle "
            "younger structural shift: a slightly softer jaw and lower face, while "
            "preserving this person's individual proportions."
        )
    if target_age >= 18:
        return (
            f"Relative to the accepted age-{parent_age} base, modestly shorten and "
            "soften the lower face, reduce mature jaw definition, and restore "
            "youthful cheek volume without turning the subject into a generic face."
        )
    if target_age >= 13:
        return (
            f"Regress the accepted age-{parent_age} facial growth coherently: a "
            "shorter and softer lower face, less developed jaw and chin, fuller "
            "cheeks, and relatively more prominent eyes, preserving identity."
        )
    return (
        f"Regress the accepted age-{parent_age} craniofacial growth coherently: a "
        "clearly shorter lower face, small undeveloped jaw and chin, rounder cheek "
        "contours, and childlike feature-to-face proportions. Preserve individual "
        "eye, nose, mouth, and ear identity rather than averaging the face."
    )


def build_prompt(
    target_age: int,
    reference_count: int,
    identity_token: str | None = None,
    demographic_description: str = "person",
    parent_age: int | None = None,
    uses_structure_guide: bool = False,
    structure_guide_mode: str = "base",
) -> str:
    if reference_count == 1:
        reference_instruction = (
            "Image 1 is both the base composition and the identity reference. "
        )
    else:
        reference_instruction = (
            f"Image 1 is the base composition. Images 2 through {reference_count} "
            "are identity-only references of the same person. "
        )
    if uses_structure_guide:
        if structure_guide_mode == "base":
            reference_instruction = (
                "Image 1 is a low-frequency younger-structure guide derived from "
                "the accepted parent portrait. Preserve its pose, crop, jaw, "
                "lower-face length, and cheek-volume direction. The auxiliary "
                "reference images and identity LoRA identify the person; restore "
                "their distinctive identity and realistic texture without "
                "reverting Image 1 to the older parent geometry. "
            )
        else:
            reference_instruction = (
                "Image 1 is the accepted parent portrait and fixes composition. "
                "The auxiliary image is a low-frequency target-age structure guide: "
                "follow its jaw, lower-face, and cheek-volume direction, but do not "
                "copy its texture or treat it as a different person's identity. "
            )
    identity_phrase = (
        f"{identity_token}, the exact same {demographic_description}"
        if identity_token
        else f"the exact same {demographic_description}"
    )
    if target_age <= 9:
        age_instruction = (
            f"clearly and unmistakably {target_age} years old, an elementary-school "
            "child with natural child proportions, not a teenager and not an adult"
        )
        anatomy_instruction = (
            "a short childlike lower face, a small undeveloped jaw and chin, fuller "
            "childhood cheeks, age-appropriate nose and ear proportions, and smooth "
            "natural child skin"
        )
    elif target_age <= 12:
        age_instruction = (
            f"clearly and unmistakably {target_age} years old, a child in early "
            "adolescence, not an older teenager and not an adult"
        )
        anatomy_instruction = (
            "early-adolescent proportions, a shorter lower face, a small soft jaw "
            "and chin, fuller youthful cheeks, and smooth natural young skin"
        )
    elif target_age <= 17:
        age_instruction = (
            f"clearly and unmistakably {target_age} years old, visibly a teenager "
            "in mid-adolescence, not a university-age adult and not a person in "
            "their twenties"
        )
        anatomy_instruction = (
            "mid-teen proportions, a slightly shorter lower face, a softer less "
            "developed jaw and chin, subtly fuller youthful cheeks, youthful "
            "under-eye anatomy, and smooth natural teenage skin"
        )
    elif target_age <= 21:
        age_instruction = (
            f"exactly {target_age} years old, a young adult who has only just "
            "finished adolescence, not a mature person in their late twenties"
        )
        anatomy_instruction = (
            "young-adult proportions, a mildly softer jaw and lower face, youthful "
            "cheeks, and smooth natural skin"
        )
    else:
        age_instruction = f"exactly {target_age} years old"
        anatomy_instruction = "realistic anatomy appropriate for that exact age"
    relative_guidance = (
        relative_growth_guidance(parent_age, target_age)
        if parent_age is not None
        else ""
    )
    return (
        f"Edit image 1 into a photorealistic studio portrait of {identity_phrase} "
        f"who is {age_instruction}. "
        f"{reference_instruction}Create a plausible younger version of "
        "this person, not another person. Preserve their distinctive eyes, eyelids, "
        "nose, lips, ears, facial symmetry, and overall identity. Preserve image "
        "1's straight-on head pose, camera distance, crop, dark navy crew-neck "
        "knit sweater, gray studio background, soft lighting, hair color, and "
        "hairstyle silhouette. Keep a neutral expression with closed relaxed lips; "
        "show no teeth and no dark mouth interior. Preserve the accepted parent's "
        "skin hue, exposure, and fine natural texture. Change only age-related "
        f"facial anatomy: {anatomy_instruction}. Remove age-inappropriate facial "
        "hair. Keep realistic anatomy consistent with the saved demographic profile. "
        "Do not merely smooth the adult face; make the bone and soft-tissue "
        f"proportions visibly younger for this stage. {relative_guidance} "
        "No smile, no open mouth, no makeup, no jewelry, no text, no illustration, "
        "no beauty-filter gloss, no skin-color shift, no wardrobe change, no "
        "background change, and no camera-angle change."
    )


def build_pipeline(
    lora_path: Path | None = None,
    lora_scale: float = 1.0,
    child_lora_path: Path | None = None,
    child_lora_scale: float = 0.35,
) -> Flux2KleinInpaintPipeline:
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(CHECKPOINT)
    if not COMPONENTS.joinpath("model_index.json").is_file():
        raise FileNotFoundError(COMPONENTS / "model_index.json")

    print("1/3 FP8 transformer reconstruction...", flush=True)
    state_dict = load_dequantized_state_dict(CHECKPOINT)
    transformer = Flux2Transformer2DModel.from_single_file(
        state_dict,
        config=CONFIG_REPO,
        subfolder="transformer",
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    del state_dict
    gc.collect()

    print("2/3 Loading local FLUX.2 components...", flush=True)
    pipeline = Flux2KleinInpaintPipeline.from_pretrained(
        COMPONENTS,
        transformer=transformer,
        dtype=torch.bfloat16,
        local_files_only=True,
    )
    adapter_names: list[str] = []
    adapter_weights: list[float] = []
    if lora_path is not None:
        pipeline.load_lora_weights(
            str(lora_path.parent),
            weight_name=lora_path.name,
            adapter_name="identity",
            local_files_only=True,
        )
        adapter_names.append("identity")
        adapter_weights.append(lora_scale)
        print(
            f"Identity LoRA loaded: {lora_path} (scale={lora_scale:.2f})",
            flush=True,
        )
    if child_lora_path is not None:
        pipeline.load_lora_weights(
            str(child_lora_path.parent),
            weight_name=child_lora_path.name,
            adapter_name="child_evidence",
            local_files_only=True,
        )
        adapter_names.append("child_evidence")
        adapter_weights.append(child_lora_scale)
        print(
            "Child-evidence LoRA loaded: "
            f"{child_lora_path} (scale={child_lora_scale:.2f})",
            flush=True,
        )
    if adapter_names:
        pipeline.set_adapters(adapter_names, adapter_weights=adapter_weights)
    pipeline.enable_model_cpu_offload()
    print("3/3 Pipeline ready with CPU/GPU offload", flush=True)
    return pipeline


def main() -> None:
    args = parse_args()
    plan_path = args.plan_path.resolve()
    source_dir = args.source_dir.resolve()
    candidate_dir = args.candidate_dir.resolve()
    debug_dir = args.debug_dir.resolve()
    plan = load_plan(plan_path)
    current_age = int(plan.get("current_age", 0))
    if args.relative_passage_mode and args.structure_guide is None:
        raise ValueError("--relative-passage-mode requires --structure-guide")
    if args.structure_guide is not None:
        if (
            args.control_age not in (None, args.age)
            and not args.relative_passage_mode
        ):
            raise ValueError(
                "A structure guide uses the real target age; "
                "use --relative-passage-mode for an ordered visual keyframe "
                "whose control age intentionally differs from its label."
            )
        control_age = (
            args.control_age
            if args.relative_passage_mode and args.control_age is not None
            else args.age
        )
    else:
        control_age = args.control_age if args.control_age is not None else args.age
    if args.relative_passage_mode and control_age >= args.age:
        raise ValueError(
            "Relative-passage control age must be younger than the keyframe label"
        )
    if not 8 <= args.age < current_age:
        raise ValueError(f"Target age must be between 8 and {current_age - 1}")
    if args.count < 1:
        raise ValueError("--count must be at least 1")
    if args.width % 16 or args.height % 16:
        raise ValueError("--width and --height must be divisible by 16")
    if not 0 < args.lora_scale <= 2.0:
        raise ValueError("--lora-scale must be greater than 0 and at most 2.0")
    if not 0 < args.child_lora_scale <= 2.0:
        raise ValueError("--child-lora-scale must be greater than 0 and at most 2.0")
    if args.edit_strength is not None and not 0 < args.edit_strength <= 1.0:
        raise ValueError("--edit-strength must be greater than 0 and at most 1.0")

    lora_path = args.lora_path.resolve() if args.lora_path is not None else None
    if lora_path is not None and not lora_path.is_file():
        raise FileNotFoundError(f"Identity LoRA not found: {lora_path}")
    child_lora_path = (
        args.child_lora_path.resolve()
        if args.child_lora_path is not None
        else None
    )
    if child_lora_path is not None and not child_lora_path.is_file():
        raise FileNotFoundError(f"Child-evidence LoRA not found: {child_lora_path}")
    structure_guide_path = (
        args.structure_guide.resolve() if args.structure_guide is not None else None
    )
    if structure_guide_path is not None and not structure_guide_path.is_file():
        raise FileNotFoundError(
            f"Age structure guide not found: {structure_guide_path}"
        )

    parent_age, reference_paths = resolve_stage_reference_paths(
        plan,
        args.age,
        args.reference_count,
        source_dir,
        candidate_dir,
    )
    if not 8 <= control_age < parent_age:
        raise ValueError(
            f"Control age must be between 8 and parent age {parent_age - 1}"
        )
    reference_images = [
        prepare_image(path, args.width, args.height) for path in reference_paths
    ]
    structure_guide_image = (
        prepare_image(structure_guide_path, args.width, args.height)
        if structure_guide_path is not None
        else None
    )
    mask_path = args.mask_path.resolve()
    mask_image = prepare_mask(mask_path, args.width, args.height)
    year_gap = parent_age - args.age
    edit_strength = (
        args.edit_strength
        if args.edit_strength is not None
        else edit_strength_for_gap(year_gap)
    )
    stage_growth_prior = growth_prior(
        parent_age,
        args.age,
        str(plan.get("biological_sex", "unspecified")),
        str(plan.get("population_group", "unspecified")),
    )
    inference_steps = max(args.steps, 8)
    prompt = build_prompt(
        control_age,
        len(reference_images),
        args.identity_token if lora_path is not None else None,
        prompt_demographic_description(plan),
        parent_age,
        structure_guide_image is not None,
        args.structure_guide_mode,
    )

    guide_as_base = bool(
        structure_guide_image is not None and args.structure_guide_mode == "base"
    )
    base_image = structure_guide_image if guide_as_base else reference_images[0]
    if guide_as_base:
        auxiliary_references = reference_images
    elif structure_guide_image is not None:
        auxiliary_references = structure_guide_image
    else:
        auxiliary_references = reference_images[1:] or None

    candidate_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print(
        f"Current age: {current_age} | stage: {parent_age} -> {args.age}",
        flush=True,
    )
    print(
        f"Chronological target: {args.age} | FLUX control age: {control_age}",
        flush=True,
    )
    if args.relative_passage_mode:
        print(
            "Relative-passage mode: the chronological age is an ordered keyframe "
            f"label; control age {control_age} supplies a visibly younger phase.",
            flush=True,
        )
    elif control_age != args.age:
        print(
            "Control age compensates measured editor bias; validation remains "
            f"anchored to age {args.age}.",
            flush=True,
        )
    print(f"Stage references: {len(reference_paths)}", flush=True)
    if guide_as_base:
        print(f"Inpaint base: {structure_guide_path.name}", flush=True)
        print(f"Accepted parent reference: {reference_paths[0].name}", flush=True)
    else:
        print(f"Base photo: {reference_paths[0].name}", flush=True)
    print(
        f"Output: {args.width}x{args.height}, {inference_steps} steps | "
        f"masked strength {edit_strength:.2f}",
        flush=True,
    )
    print(f"Age mask: {mask_path}", flush=True)
    if structure_guide_path is not None:
        print(f"Age structure guide: {structure_guide_path}", flush=True)
        print(f"Structure-guide mode: {args.structure_guide_mode}", flush=True)
        print(
            "Exact apparent age is advisory; identity and younger trajectory "
            "remain strict.",
            flush=True,
        )
    print(
        "Structural guide: "
        f"{stage_growth_prior['stage']} | weight "
        f"{stage_growth_prior['guidance_weight']:.2f} | advisory prior, "
        "validated with 3DDFA-V2",
        flush=True,
    )
    if lora_path is not None:
        print(f"Identity LoRA: {lora_path}", flush=True)
        print(f"Identity LoRA scale: {args.lora_scale:.2f}", flush=True)
    if child_lora_path is not None:
        print(f"Child-evidence LoRA: {child_lora_path}", flush=True)
        print(
            f"Child-evidence LoRA scale: {args.child_lora_scale:.2f}",
            flush=True,
        )

    pipeline = build_pipeline(
        lora_path=lora_path,
        lora_scale=args.lora_scale,
        child_lora_path=child_lora_path,
        child_lora_scale=args.child_lora_scale,
    )
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    outputs: list[dict] = []

    for index in range(args.count):
        seed = args.seed + index
        print(f"\n[{index + 1}/{args.count}] Generating seed {seed}...", flush=True)
        candidate_started = time.perf_counter()
        result = pipeline(
            prompt=prompt,
            image=base_image,
            image_reference=auxiliary_references,
            mask_image=mask_image,
            strength=edit_strength,
            height=args.height,
            width=args.width,
            num_inference_steps=inference_steps,
            guidance_scale=1.0,
            generator=torch.Generator(device="cpu").manual_seed(seed),
        ).images[0]
        lora_suffix = (
            f"_lora{args.lora_scale:.2f}".replace(".", "p")
            if lora_path is not None
            else ""
        )
        strength_suffix = f"_maskstr{edit_strength:.2f}".replace(".", "p")
        guide_suffix = (
            f"_guide{args.structure_guide_mode}_{structure_guide_path.stem}"
            if structure_guide_path is not None
            else ""
        )
        output_path = candidate_dir / (
            f"age{args.age:02d}_flux2_seed{seed}_"
            f"ctrl{control_age:02d}_refs{len(reference_paths)}"
            f"{lora_suffix}{strength_suffix}{guide_suffix}.png"
        )
        result.save(output_path)
        duration = time.perf_counter() - candidate_started
        print(f"Saved: {output_path}", flush=True)
        print(f"Candidate time: {duration:.1f}s", flush=True)
        outputs.append(
            {"seed": seed, "path": str(output_path), "seconds": round(duration, 2)}
        )

    total_seconds = time.perf_counter() - started
    peak_gib = torch.cuda.max_memory_allocated() / 1024**3
    summary = {
        "version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": "black-forest-labs/FLUX.2-klein-4B",
        "transformer": str(CHECKPOINT),
        "current_age": current_age,
        "age_source": plan.get("age_source", "manual_age"),
        "birth_date": plan.get("birth_date"),
        "current_photo_date": plan.get("current_photo_date"),
        "biological_sex": plan.get("biological_sex", "unspecified"),
        "population_group": plan.get("population_group", "unspecified"),
        "parent_age": parent_age,
        "target_age": args.age,
        "target_interpretation": (
            "ordered_visual_passage_keyframe"
            if args.relative_passage_mode
            else "chronological_age"
        ),
        "relative_passage_mode": bool(args.relative_passage_mode),
        "control_age": control_age,
        "conditioning_age": control_age,
        "control_age_is_internal_setpoint": control_age != args.age,
        "references": [str(path) for path in reference_paths],
        "base_photo": str(structure_guide_path if guide_as_base else reference_paths[0]),
        "accepted_parent_photo": str(reference_paths[0]),
        "prompt": prompt,
        "structural_guidance": {
            "mode": (
                f"fran_structure_guide_{args.structure_guide_mode}_masked_inpaint_with_3d_post_validation"
                if structure_guide_path is not None
                else "masked_inpaint_growth_prompt_with_3d_post_validation"
            ),
            "structure_guide": (
                str(structure_guide_path) if structure_guide_path else None
            ),
            "structure_guide_mode": (
                args.structure_guide_mode if structure_guide_path else None
            ),
            "growth_prior": stage_growth_prior,
            "prompt_guidance": relative_growth_guidance(parent_age, control_age),
            "direct_3d_vertex_warp": False,
            "note": (
                "3D statistics guide the prompt and post-validation. Direct "
                "vertex warping is disabled until demographic magnitudes are "
                "calibrated."
            ),
        },
        "width": args.width,
        "height": args.height,
        "steps": inference_steps,
        "guidance_scale": 1.0,
        "edit_mode": "masked_inpaint",
        "edit_strength": edit_strength,
        "mask_path": str(mask_path),
        "identity_lora": str(lora_path) if lora_path is not None else None,
        "child_evidence_lora": (
            str(child_lora_path) if child_lora_path is not None else None
        ),
        "identity_token": args.identity_token if lora_path is not None else None,
        "lora_scale": args.lora_scale if lora_path is not None else None,
        "child_lora_scale": (
            args.child_lora_scale if child_lora_path is not None else None
        ),
        "outputs": outputs,
        "total_seconds": round(total_seconds, 2),
        "peak_cuda_gib": round(peak_gib, 2),
    }
    summary_path = debug_dir / f"age{args.age:02d}_flux2_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nFLUX.2 past-age generation complete", flush=True)
    print(f"Candidates: {len(outputs)}/{args.count}", flush=True)
    print(f"Total time: {total_seconds:.1f}s", flush=True)
    print(f"Peak CUDA memory: {peak_gib:.2f} GiB", flush=True)
    print(f"Summary: {summary_path}", flush=True)


if __name__ == "__main__":
    main()
