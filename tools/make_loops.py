"""
표정 루프 영상 생성.

통화 중 얼굴이 정지 사진이면 통화 같지 않다. 그렇다고 응답마다 영상을
생성하면 비용과 지연이 감당되지 않는다 (한 번에 1~3분, 건당 수백 원).

그래서 짧은 루프를 미리 몇 개 만들어 두고 상황에 맞는 것을 재생한다.
어떤 루프를 틀지는 LLM 이 이미 알려주고 있다. 응답 JSON 의 intent 와
risk 필드가 그대로 선택 기준이 된다.

시작 프레임과 끝 프레임에 같은 사진을 넣어 이어 재생해도 티가 나지 않게 한다.

    python tools/make_loops.py --dry-run
    python tools/make_loops.py
    python tools/make_loops.py --only talking

.env 의 REPLICATE_API_TOKEN 을 쓴다.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

FACES = ROOT / "data" / "faces" / "aligned"
OUT = ROOT / "data" / "faces" / "loops"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"
)

COMMON = (
    " Static locked-off camera. The head stays in the same position and size. "
    "Shoulders fill the bottom of the frame. Plain grey background unchanged. "
    "Soft even frontal lighting. One continuous take."
)

LOOPS = {
    "idle": (
        "A person listening quietly to someone on a video call. "
        "Eyes blink naturally a few times, very small relaxed head movements, "
        "mouth stays closed, calm and warm expression." + COMMON
    ),
    "talking": (
        "A person speaking warmly to someone on a video call. "
        "The mouth opens and closes naturally as if talking, "
        "eyebrows move slightly with the speech, friendly expression, "
        "small natural head movements." + COMMON
    ),
    "concerned": (
        "A person listening with concern on a video call. "
        "Eyebrows drawn together slightly, attentive worried expression, "
        "leaning in a little, mouth closed, blinking naturally." + COMMON
    ),
}

NEGATIVE = (
    "cut, scene change, jump cut, camera movement, zoom, pan, "
    "background change, different person, extra person, aging, "
    "text, watermark, hands, gestures"
)

START_FIELDS = ["first_frame", "start_image", "first_frame_image", "image"]
END_FIELDS = ["last_frame", "end_image", "last_frame_image"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(LOOPS), help="한 종류만 생성")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seconds", type=int, default=5)
    ap.add_argument("--model", default=os.getenv("REPLICATE_MODEL", ""))
    ap.add_argument("--face", help="기준 사진 파일명 (기본: 가장 마지막 = 현재 얼굴)")
    args = ap.parse_args()

    faces = sorted(p for p in FACES.glob("*.png") if not p.name.startswith("_"))
    if not faces:
        sys.exit(f"{FACES} 에 사진이 없습니다. python tools/prep_faces.py 를 먼저 실행하세요.")

    face = FACES / args.face if args.face else faces[-1]
    if not face.exists():
        sys.exit(f"{face} 없음")

    wanted = [args.only] if args.only else list(LOOPS)
    print(f"\n기준 사진: {face.name}")
    print(f"루프 {len(wanted)}개 × {args.seconds}초 → {', '.join(wanted)}")

    if not args.model:
        sys.exit("\n--model 또는 .env 의 REPLICATE_MODEL 이 필요합니다.")
    if args.dry_run:
        print(f"\n모델: {args.model}\n{YELLOW}--dry-run 이라 생성하지 않았습니다.{RESET}\n")
        return

    try:
        import replicate
    except ImportError:
        sys.exit("pip install replicate 를 먼저 실행하세요.")

    model = replicate.models.get(args.model)
    version = getattr(model, "latest_version", None)
    schema = getattr(version, "openapi_schema", None) or {}
    props = (schema.get("components", {}).get("schemas", {})
             .get("Input", {}).get("properties", {}))

    start_field = next((f for f in START_FIELDS if f in props), None)
    end_field = next((f for f in END_FIELDS if f in props), None)
    if not start_field:
        sys.exit(f"{RED}{args.model} 에서 시작 프레임 필드를 찾지 못했습니다.{RESET}")

    OUT.mkdir(parents=True, exist_ok=True)
    made = {}

    for name in wanted:
        dest = OUT / f"{name}.mp4"
        if dest.exists():
            print(f"{DIM}[{name}] 이미 있음, 건너뜀{RESET}")
            made[name] = dest.name
            continue

        print(f"[{name}] 생성 중…", flush=True)
        payload = {start_field: open(face, "rb"), "prompt": LOOPS[name]}
        # 시작과 끝을 같은 사진으로 두면 반복 재생해도 이음매가 보이지 않는다
        if end_field:
            payload[end_field] = open(face, "rb")
        for opt, val in (("negative_prompt", NEGATIVE),
                         ("duration", args.seconds),
                         ("resolution", "720p"),
                         ("camera_fixed", True),
                         ("enable_prompt_expansion", False)):
            if opt in props:
                payload[opt] = val

        try:
            output = replicate.run(args.model, input=payload)
        except Exception as e:  # noqa: BLE001
            print(f"{RED}      실패: {str(e)[:120]}{RESET}")
            continue

        data = output.read() if hasattr(output, "read") else (
            output[0].read() if isinstance(output, list) else output
        )
        dest.write_bytes(data if isinstance(data, bytes) else data.read())
        made[name] = dest.name
        print(f"{GREEN}      완료 {dest.stat().st_size // 1024}KB{RESET}")

    (OUT / "loops.json").write_text(
        json.dumps({"face": face.name, "loops": made}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"\n{GREEN}{len(made)}개 완료{RESET} → {OUT}")
    print("각 mp4 를 열어 표정이 의도대로인지 확인하세요.\n")


if __name__ == "__main__":
    main()
