"""Generate one Korean Chatterbox Multilingual V3 voice-cloning sample."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
import torchaudio
from chatterbox.mtl_tts import ChatterboxMultilingualTTS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "data" / "voice" / "reference.wav"
DEFAULT_OUTPUT = ROOT / "data" / "voice" / "chatterbox_v3_test.wav"
DEFAULT_TEXT = "할아버지, 저예요. 오늘 하루는 어떻게 보내셨어요?"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reference = args.reference.resolve()
    output = args.output.resolve()

    if not reference.is_file():
        raise FileNotFoundError(f"Reference voice not found: {reference}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is not available.")

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.cuda.reset_peak_memory_stats()

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print("Loading Chatterbox Multilingual V3...")
    started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(
        device="cuda",
        t3_model="v3",
    )
    load_seconds = time.perf_counter() - started
    print(f"Model loaded in {load_seconds:.1f}s")

    print(f"Reference: {reference}")
    print(f"Text: {args.text}")
    started = time.perf_counter()
    wav = model.generate(
        args.text,
        language_id="ko",
        audio_prompt_path=str(reference),
        exaggeration=0.5,
        cfg_weight=0.5,
    )
    generation_seconds = time.perf_counter() - started

    wav = wav.detach().cpu()
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    output.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output), wav, model.sr)

    audio_seconds = wav.shape[-1] / model.sr
    peak_vram_gb = torch.cuda.max_memory_allocated() / (1024**3)
    print(f"Saved: {output}")
    print(f"Audio duration: {audio_seconds:.2f}s")
    print(f"Generation time: {generation_seconds:.1f}s")
    print(f"Peak CUDA memory: {peak_vram_gb:.2f}GB")


if __name__ == "__main__":
    main()
