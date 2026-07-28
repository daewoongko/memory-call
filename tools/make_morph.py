"""
얼굴 모핑 영상 생성.

정렬된 사진들을 인접한 쌍으로 묶어 키프레임 보간 모델에 넣고,
나온 클립들을 이어 붙여 data/faces/morph.mp4 를 만든다.

통화할 때마다 생성하는 것이 아니라 페르소나 등록 시 1회만 돌린다.
명세 FR-02의 "학습 결과" 단계에 해당하며, 통화 중 지연이 0이 된다.

    python tools/make_morph.py --search vidu      쓸 만한 모델 찾기
    python tools/make_morph.py --inspect <슬러그>  입력 필드 확인
    python tools/make_morph.py --dry-run          비용·계획만 보기
    python tools/make_morph.py                    실제 생성

.env 에 필요한 값:
    REPLICATE_API_TOKEN=r8_...
    REPLICATE_MODEL=<슬러그>
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

FACES = ROOT / "data" / "faces" / "aligned"
OUT = ROOT / "data" / "faces" / "morph.mp4"
MANIFEST = ROOT / "data" / "faces" / "morph.json"
CLIPS = ROOT / "data" / "faces" / "clips"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"
)

# 모델마다 필드 이름이 달라서 후보를 순서대로 찾아본다.
START_FIELDS = ["start_image", "first_frame_image", "first_frame", "image",
                "start_frame", "input_image", "image_url"]
END_FIELDS = ["end_image", "last_frame_image", "last_frame", "end_frame",
              "tail_image_url", "last_image"]

# "aging", "time-lapse" 같은 단어를 넣으면 모델이 도착 프레임을 무시하고
# 노년까지 밀어붙인다. "matures"처럼 완만한 표현만 쓴다.
PROMPT = (
    "Portrait video of the same person filmed in one continuous take. "
    "The camera is completely static. The person stays centered facing forward "
    "with a calm closed-mouth expression. Across the shot the face matures "
    "gradually and smoothly: cheeks slim down, the jawline becomes more defined, "
    "facial proportions lengthen naturally. Plain light grey studio background "
    "stays constant. Soft even frontal lighting."
)
NEGATIVE = (
    "elderly, old man, grey hair, white hair, deep wrinkles, "
    "cut, scene change, jump cut, dissolve, ghosting, double exposure, "
    "camera movement, zoom, pan, background change, distorted face, "
    "different person, extra person, text, watermark, open mouth, talking"
)


def need_token() -> str:
    token = os.getenv("REPLICATE_API_TOKEN", "")
    if not token:
        sys.exit(
            "REPLICATE_API_TOKEN 이 없습니다.\n"
            "  replicate.com → 프로필 → API tokens 에서 발급 후 .env 에 넣으세요."
        )
    return token


def load_client():
    need_token()
    try:
        import replicate
    except ImportError:
        sys.exit("pip install replicate imageio-ffmpeg 를 먼저 실행하세요.")
    return replicate


def input_schema(model) -> dict:
    """모델의 입력 필드 목록을 뽑는다."""
    version = getattr(model, "latest_version", None)
    schema = getattr(version, "openapi_schema", None) or {}
    comps = schema.get("components", {}).get("schemas", {})
    return comps.get("Input", {}).get("properties", {})


def pick_field(props: dict, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in props:
            return name
    return None


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


# ------------------------------------------------------------------ 보조 명령

def cmd_search(query: str) -> None:
    replicate = load_client()
    print(f"\n'{query}' 검색 결과\n" + "=" * 66)
    try:
        results = replicate.models.search(query)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"검색 실패: {e}")

    for m in list(results)[:12]:
        props = input_schema(m)
        start = pick_field(props, START_FIELDS)
        end = pick_field(props, END_FIELDS)
        mark = f"{GREEN}✓ 시작+끝 지원{RESET}" if start and end else f"{DIM}—{RESET}"
        print(f"{m.owner}/{m.name}  {mark}")
        if start and end:
            print(f"{DIM}    {start} / {end}{RESET}")
    print("\n✓ 표시된 슬러그를 .env 의 REPLICATE_MODEL 에 넣으세요.\n")


def cmd_inspect(slug: str) -> None:
    replicate = load_client()
    model = replicate.models.get(slug)
    props = input_schema(model)
    print(f"\n{slug} 입력 필드\n" + "=" * 66)
    for name, spec in props.items():
        print(f"  {name}  {DIM}({spec.get('type', '?')}){RESET}")
        if spec.get("description"):
            print(f"      {DIM}{spec['description']}{RESET}")
        if spec.get("enum"):
            print(f"      {DIM}선택지: {spec['enum']}{RESET}")
        if spec.get("default") is not None:
            print(f"      {DIM}기본값: {spec['default']}{RESET}")
    start = pick_field(props, START_FIELDS)
    end = pick_field(props, END_FIELDS)
    print(f"\n시작 프레임 → {start or f'{RED}못 찾음{RESET}'}")
    print(f"끝 프레임   → {end or f'{RED}못 찾음{RESET}'}\n")


# ------------------------------------------------------------------ 생성

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", metavar="QUERY", help="모델 검색")
    ap.add_argument("--inspect", metavar="SLUG", help="모델 입력 필드 확인")
    ap.add_argument("--dry-run", action="store_true", help="계획만 출력")
    ap.add_argument("--model", help=".env 의 REPLICATE_MODEL 대신 사용할 슬러그")
    # Seedance 는 5초와 10초만 받는다. 모델마다 허용값이 다르니 스키마로 확인할 것.
    ap.add_argument("--seconds", type=int, default=5, help="구간당 길이 (기본 5초)")
    ap.add_argument("--keep-clips", action="store_true", help="중간 클립 남기기")
    ap.add_argument("--only", type=int, metavar="N",
                    help="N번째 구간만 생성 (원인 좁힐 때)")
    ap.add_argument("--minimal", action="store_true",
                    help="옵션 없이 필수 필드만 보내기")
    ap.add_argument("--prompt", help="기본 프롬프트 대신 사용할 문장")
    args = ap.parse_args()

    if args.search:
        return cmd_search(args.search)
    if args.inspect:
        return cmd_inspect(args.inspect)

    faces = sorted(p for p in FACES.glob("*.png") if not p.name.startswith("_"))
    if len(faces) < 2:
        sys.exit(f"{FACES} 에 사진이 2장 이상 있어야 합니다. "
                 f"python tools/prep_faces.py 를 먼저 실행하세요.")

    pairs = list(zip(faces, faces[1:]))
    if args.only:
        if not 1 <= args.only <= len(pairs):
            sys.exit(f"--only 는 1~{len(pairs)} 사이여야 합니다.")
        pairs = [pairs[args.only - 1]]

    print(f"\n사진 {len(faces)}장 → 클립 {len(pairs)}개 "
          f"→ 영상 약 {len(pairs) * args.seconds}초")
    for a, b in pairs:
        print(f"{DIM}  {a.stem} → {b.stem}{RESET}")

    slug = args.model or os.getenv("REPLICATE_MODEL", "")
    if not slug:
        sys.exit("\nREPLICATE_MODEL 이 없습니다. "
                 "python tools/make_morph.py --search vidu 로 먼저 찾으세요.")

    if args.dry_run:
        print(f"\n모델: {slug}\n{YELLOW}--dry-run 이라 생성하지 않았습니다.{RESET}\n")
        return

    replicate = load_client()
    model = replicate.models.get(slug)
    props = input_schema(model)
    start_field = pick_field(props, START_FIELDS)
    end_field = pick_field(props, END_FIELDS)

    if not (start_field and end_field):
        sys.exit(
            f"\n{RED}{slug} 에서 시작/끝 프레임 필드를 찾지 못했습니다.{RESET}\n"
            f"python tools/make_morph.py --inspect {slug} 로 필드명을 확인하고 "
            f"알려주세요."
        )

    print(f"\n모델 {slug}")
    print(f"{DIM}  시작 {start_field} · 끝 {end_field}{RESET}\n")

    CLIPS.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    made: list[dict] = []
    failed: list[dict] = []

    for i, (a, b) in enumerate(pairs, args.only or 1):
        dest = CLIPS / f"clip_{i:02d}.mp4"
        if dest.exists():
            print(f"{DIM}[{i}/{len(pairs)}] {dest.name} 이미 있음, 건너뜀{RESET}")
            clip_paths.append(dest)
            made.append({"index": i, "from": a.stem, "to": b.stem,
                         "clip": dest.name})
            continue

        print(f"[{i}/{len(pairs)}] {a.stem} → {b.stem} 생성 중…", flush=True)
        payload = {
            start_field: open(a, "rb"),
            end_field: open(b, "rb"),
            "prompt": args.prompt or PROMPT,
        }
        # 모델이 받는 필드만 골라 넣는다.
        # camera_fixed 는 얼굴 모핑에 특히 중요하다. 카메라가 흔들리면
        # 나이가 드는 것이 아니라 장면이 바뀐 것처럼 보인다.
        if not args.minimal:
            for optional, value in (("negative_prompt", NEGATIVE),
                                    ("duration", args.seconds),
                                    ("resolution", "720p"),
                                    ("camera_fixed", True),
                                    # 모델이 프롬프트를 제멋대로 늘려 쓰면
                                    # 도착 프레임을 무시하고 폭주한다
                                    ("enable_prompt_expansion", False)):
                if optional in props:
                    payload[optional] = value

        sending = {k: (v if isinstance(v, (str, int, bool)) else f"<{Path(v.name).name}>")
                   for k, v in payload.items()}
        print(f"{DIM}      보내는 값: {sending}{RESET}")

        try:
            output = replicate.run(slug, input=payload)
        except Exception as e:  # noqa: BLE001
            # 한 구간이 막혀도 나머지는 만든다.
            # 상용 영상 모델은 미성년자 얼굴을 거부하는 경우가 있어
            # 어린 시절 구간만 실패하는 일이 흔하다.
            print(f"{RED}      실패: {str(e)[:110]}{RESET}")
            failed.append({"index": i, "from": a.stem, "to": b.stem,
                           "error": str(e)[:200]})
            continue

        data = output.read() if hasattr(output, "read") else (
            output[0].read() if isinstance(output, list) else output
        )
        dest.write_bytes(data if isinstance(data, bytes) else data.read())
        clip_paths.append(dest)
        made.append({"index": i, "from": a.stem, "to": b.stem, "clip": dest.name})
        print(f"{GREEN}      완료 {dest.stat().st_size // 1024}KB{RESET}")

    if failed:
        print(f"\n{YELLOW}실패한 구간 {len(failed)}개{RESET}")
        for f in failed:
            print(f"{DIM}  {f['from']} → {f['to']}{RESET}")
        print(f"{DIM}  이 구간은 통화 화면에서 이미지 전환으로 대체됩니다.{RESET}")

    if not clip_paths:
        MANIFEST.write_text(json.dumps(
            {"video": None, "segments": [], "failed": failed,
             "faces": [f.name for f in faces]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"\n{RED}생성된 클립이 없습니다.{RESET}")

    if args.only:
        print(f"\n{GREEN}구간 {args.only} 완료{RESET} → {clip_paths[0]}")
        print("전체를 만들려면 --only 없이 다시 실행하세요.\n")
        return

    # 클립 이어 붙이기. 클립마다 코덱이 다를 수 있어 재인코딩한다.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")
        list_file = f.name

    print(f"\n{len(clip_paths)}개 클립 이어 붙이는 중…")
    result = subprocess.run(
        [ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-r", "24",
         str(OUT)],
        capture_output=True, text=True,
    )
    os.unlink(list_file)

    if result.returncode != 0:
        sys.exit(f"{RED}ffmpeg 실패:{RESET}\n{result.stderr[-1200:]}")

    if not args.keep_clips:
        print(f"{DIM}중간 클립은 {CLIPS} 에 남겨둡니다 (재시도 시 재사용){RESET}")

    # 어느 구간이 영상이고 어느 구간이 이미지 전환인지 프론트가 알아야 한다.
    MANIFEST.write_text(json.dumps({
        "video": OUT.name,
        "seconds_per_segment": args.seconds,
        "segments": made,
        "failed": failed,
        "faces": [f.name for f in faces],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{GREEN}완료{RESET} → {OUT}  ({OUT.stat().st_size // 1024}KB)")
    print(f"{DIM}       → {MANIFEST.name}  (영상 {len(made)}구간 / 대체 {len(failed)}구간){RESET}")
    print("열어서 확인한 뒤 마음에 들면 통화 화면에 붙입니다.\n")


if __name__ == "__main__":
    main()
