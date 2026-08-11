"""
모핑용 인물 크롭.

영상 모델이 두 키프레임을 이을 때 가장 실패하는 지점은 얼굴이 아니라
'어깨 바깥 윤곽선'이다. 아이 어깨와 어른 어깨는 서로 다른 자리에 있어서
모델이 그 사이를 잇지 못하고 두 윤곽을 겹쳐 회색 유령을 만든다.

해법은 어깨를 프레임 밖으로 빼내는 것이다. 화면 아래쪽이 옷으로 가득 차면
이어붙일 경계 자체가 사라진다. 영상통화에서 가까이 앉았을 때의 구도와 같다.

출력은 3:4 세로. 폰 화면을 그대로 채운다.

    python tools/prep_faces.py

data/faces/raw/*  →  data/faces/aligned/*  +  _contact_sheet.png

crop.json 으로 사진마다 확대율과 위치를 조절한다.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from storage import ensure_persona_face_directories  # noqa: E402

WIDTH, HEIGHT = 864, 1152  # 3:4 세로

# 어릴수록 어깨가 좁아 프레임 안에 남기 쉬우므로 더 확대한다.
DEFAULT_ZOOM = {"child": 1.34, "teen": 1.14, "college": 1.06, "current": 1.0}

GREEN, DIM, RESET = "\033[92m", "\033[2m", "\033[0m"


def default_for(stem: str) -> dict:
    for key, zoom in DEFAULT_ZOOM.items():
        if key in stem.lower():
            return {"zoom": zoom, "x": 0.0, "y": 0.0}
    return {"zoom": 1.1, "x": 0.0, "y": 0.0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona-id")
    args = parser.parse_args()
    paths = ensure_persona_face_directories(args.persona_id)
    raw = paths.raw
    out = paths.aligned
    config_path = paths.root / "crop.json"

    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in raw.iterdir()
                   if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if not files:
        sys.exit(f"{raw} 에 이미지가 없습니다.")

    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    for p in files:
        config.setdefault(p.name, default_for(p.stem))
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    crops = []
    for p in files:
        cfg = config[p.name]
        img = Image.open(p).convert("RGB")
        w, h = img.size
        zoom = max(cfg.get("zoom", 1.0), 0.2)

        # 원본에서 잘라낼 3:4 영역
        box_h = h / zoom
        box_w = box_h * WIDTH / HEIGHT
        cx = w / 2 + cfg.get("x", 0.0) * w
        cy = h / 2 + cfg.get("y", 0.0) * h

        crop = img.crop((round(cx - box_w / 2), round(cy - box_h / 2),
                         round(cx + box_w / 2), round(cy + box_h / 2)))
        crop = crop.resize((WIDTH, HEIGHT), Image.LANCZOS)
        crop.save(out / f"{p.stem}.png")
        crops.append(crop)
        print(f"  OK  {p.name}  zoom {cfg['zoom']}  y {cfg['y']}")

    tw = 300
    th = round(tw * HEIGHT / WIDTH)
    sheet = Image.new("RGB", (tw * len(crops), th), "white")
    for i, c in enumerate(crops):
        sheet.paste(c.resize((tw, th), Image.LANCZOS), (i * tw, 0))

    draw = ImageDraw.Draw(sheet)
    draw.line([(0, int(th * 0.30)), (sheet.width, int(th * 0.30))],
              fill=(255, 0, 0), width=2)          # 눈
    draw.line([(0, int(th * 0.86)), (sheet.width, int(th * 0.86))],
              fill=(0, 200, 120), width=2)        # 어깨 확인선
    for i in range(len(crops)):
        draw.line([(i * tw, 0), (i * tw, th)], fill=(120, 120, 120), width=1)
    sheet.save(out / "_contact_sheet.png")

    print(f"\n{GREEN}{len(crops)}장 완료{RESET} → {out}  ({WIDTH}x{HEIGHT})")
    print("_contact_sheet.png 를 열고 두 가지만 확인하세요.")
    print(f"{DIM}  1. 빨간 선 위에 네 장 모두 눈이 놓였는가")
    print(f"  2. 초록 선 높이에서 옷이 좌우 끝까지 닿는가")
    print(f"     → 회색 배경이 보이면 그 사진의 zoom 을 올리세요{RESET}")


if __name__ == "__main__":
    main()
