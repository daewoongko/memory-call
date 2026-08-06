"""Validate and dequantize the official FLUX.2 Klein 4B FP8 transformer.

The official single-file checkpoint stores FP8 weights together with scalar
``weight_scale`` values.  Diffusers' generic FLUX.2 converter currently tries
to treat those scalar entries as QKV matrices.  This probe removes the runtime
input scales and reconstructs each FP8 weight in BF16 before handing the state
dict to Diffusers.
"""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path

import torch
from diffusers import Flux2Transformer2DModel
from safetensors import safe_open


MODELS_ROOT = Path(
    os.getenv("MEMORY_CALL_MODELS_DIR", str(Path.home() / "Models"))
).expanduser().resolve()
CHECKPOINT = Path(
    os.getenv(
        "FLUX2_FP8_CHECKPOINT",
        str(MODELS_ROOT / "FLUX2-klein-4b-fp8" / "flux-2-klein-4b-fp8.safetensors"),
    )
).expanduser().resolve()
CONFIG_REPO = os.getenv("FLUX2_CONFIG_REPO", "black-forest-labs/FLUX.2-klein-4B")


def load_dequantized_state_dict(path: Path) -> dict[str, torch.Tensor]:
    state_dict: dict[str, torch.Tensor] = {}
    dequantized = 0

    with safe_open(path, framework="pt", device="cpu") as checkpoint:
        keys = list(checkpoint.keys())
        key_set = set(keys)

        for key in keys:
            if key.endswith((".input_scale", ".weight_scale")):
                continue

            tensor = checkpoint.get_tensor(key)
            scale_key = f"{key.removesuffix('.weight')}.weight_scale"
            if key.endswith(".weight") and scale_key in key_set:
                scale = checkpoint.get_tensor(scale_key).float()
                tensor = tensor.to(torch.bfloat16).mul_(scale)
                dequantized += 1

            state_dict[key] = tensor

    if dequantized == 0:
        raise RuntimeError("No scaled FP8 weights were found in the checkpoint")

    print(f"FP8 -> BF16 dequantized weights: {dequantized}", flush=True)
    print(f"State-dict tensors after removing scales: {len(state_dict)}", flush=True)
    return state_dict


def main() -> None:
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(CHECKPOINT)

    print(f"Checkpoint: {CHECKPOINT}", flush=True)
    print("Reconstructing scaled FP8 weights on CPU...", flush=True)
    state_dict = load_dequantized_state_dict(CHECKPOINT)

    print("Mapping reconstructed weights into Diffusers...", flush=True)
    model = Flux2Transformer2DModel.from_single_file(
        state_dict,
        config=CONFIG_REPO,
        subfolder="transformer",
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )

    dtype_counts = Counter(str(parameter.dtype) for parameter in model.parameters())
    parameter_gib = sum(
        parameter.numel() * parameter.element_size() for parameter in model.parameters()
    ) / 1024**3

    print("FLUX.2 Klein FP8 reconstruction: OK", flush=True)
    print(f"Parameter dtypes: {dict(dtype_counts)}", flush=True)
    print(f"Transformer memory: {parameter_gib:.2f} GiB", flush=True)


if __name__ == "__main__":
    main()
