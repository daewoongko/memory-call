"""
표정 루프 다듬기.

생성된 클립은 끝에서 원래 사진의 자세로 되돌아가느라 뒷부분이 정지한다.
그대로 반복하면 "말하다가 멈추는" 것처럼 보인다.

두 단계로 고친다.
  1. 실제로 움직이는 구간만 잘라낸다
  2. 잘라낸 구간을 되감아 뒤에 붙인다
     → 끝 프레임과 시작 프레임이 같아져 이음매가 사라지고
       움직임은 끊기지 않는다

    python tools/fix_loop.py --preview talking      어디서 움직이는지 확인
    python tools/fix_loop.py talking --start 0.3 --duration 3.0
    python tools/fix_loop.py talking                기본값으로 바로
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from storage import LOOPS_DIR  # noqa: E402

LOOPS = LOOPS_DIR

GREEN, RED, DIM, RESET = "\033[92m", "\033[91m", "\033[2m", "\033[0m"


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{RED}ffmpeg 실패:{RESET}\n{result.stderr[-1000:]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="루프 이름 (talking, concerned …)")
    ap.add_argument("--preview", action="store_true",
                    help="프레임을 펼쳐 어디서 움직이는지 확인만 한다")
    ap.add_argument("--start", type=float, default=0.3, help="잘라낼 시작 초")
    ap.add_argument("--duration", type=float, default=3.0, help="잘라낼 길이 초")
    args = ap.parse_args()

    src = LOOPS / f"{args.name}.mp4"
    if not src.exists():
        sys.exit(f"{src} 없음")

    ff = ffmpeg()

    if args.preview:
        out = Path.home() / "Desktop" / f"{args.name}_frames.png"
        run([ff, "-y", "-i", str(src),
             "-vf", "fps=4,scale=160:-1,tile=8x3", "-frames:v", "1", str(out)])
        print(f"\n{GREEN}프레임 펼침{RESET} → {out}")
        print(f"{DIM}입이 움직이는 구간의 시작·끝 초를 확인하고")
        print(f"  python tools/fix_loop.py {args.name} --start X --duration Y{RESET}\n")
        return

    backup = LOOPS / f"{args.name}_original.mp4"
    if not backup.exists():
        shutil.copy(src, backup)
        print(f"{DIM}원본 보관 → {backup.name}{RESET}")

    work = LOOPS / "_work"
    work.mkdir(exist_ok=True)
    forward = work / "fwd.mp4"
    backward = work / "bwd.mp4"
    listfile = work / "list.txt"

    print(f"[1/3] {args.start}초부터 {args.duration}초 잘라내는 중…")
    run([ff, "-y", "-ss", str(args.start), "-t", str(args.duration),
         "-i", str(backup), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(forward)])

    print("[2/3] 되감기 만드는 중…")
    run([ff, "-y", "-i", str(forward), "-vf", "reverse", "-an",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(backward)])

    print("[3/3] 이어 붙이는 중…")
    listfile.write_text(f"file '{forward.resolve()}'\nfile '{backward.resolve()}'\n")
    run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(src)])

    shutil.rmtree(work, ignore_errors=True)

    print(f"\n{GREEN}완료{RESET} → {src}  "
          f"({args.duration * 2:.1f}초, {src.stat().st_size // 1024}KB)")
    print(f"{DIM}원본으로 되돌리려면 {backup.name} 을 {src.name} 으로 복사하세요.{RESET}\n")


if __name__ == "__main__":
    main()
