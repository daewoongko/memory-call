"""Download and verify the official FRAN face re-aging checkpoint."""

from __future__ import annotations

import os
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download


MODEL_DIR = Path(
    os.getenv(
        "REAGING_MODEL_DIR",
        str(Path.home() / "Models" / "face_reaging"),
    )
).expanduser().resolve()
REPO_ID = "timroelofs123/face_re-aging"
FILENAME = "best_unet_model.pth"


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading official FRAN checkpoint (about 124MB)...")
    path = Path(
        hf_hub_download(
            repo_id=REPO_ID,
            filename=FILENAME,
            local_dir=str(MODEL_DIR),
            local_dir_use_symlinks=False,
        )
    )
    size_mb = path.stat().st_size / (1024**2)
    print(f"Downloaded: {path}")
    print(f"Size: {size_mb:.1f}MB")

    # PyTorch 2.6's weights_only mode prevents arbitrary pickle execution.
    state = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or not state:
        raise RuntimeError("Checkpoint is not a non-empty state dictionary")
    first_key = next(iter(state))
    print(f"State dict tensors: {len(state)}")
    print(f"First key: {first_key}")
    print("FRAN checkpoint verification: OK")


if __name__ == "__main__":
    main()
