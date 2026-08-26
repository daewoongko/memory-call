"""Slice generated diary illustration atlases into optimized dated WebP assets.

This is intentionally a small, deterministic asset-build helper.  Pass atlas
specifications as ``SOURCE,YYYY-MM-DD,COUNT,COLUMNS,ROWS`` arguments.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageOps


OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "diary" / "daily"


def slice_atlas(spec: str) -> None:
    source_text, start_text, count_text, columns_text, rows_text = spec.split(",")
    source = Path(source_text)
    start = date.fromisoformat(start_text)
    count = int(count_text)
    columns = int(columns_text)
    rows = int(rows_text)
    if count > columns * rows:
        raise ValueError(f"{source}: count exceeds atlas cells")

    with Image.open(source) as atlas:
        atlas = atlas.convert("RGB")
        cell_width = atlas.width // columns
        cell_height = atlas.height // rows
        for index in range(count):
            column = index % columns
            row = index // columns
            cell = atlas.crop((
                column * cell_width,
                row * cell_height,
                (column + 1) * cell_width,
                (row + 1) * cell_height,
            ))
            # All diary art uses the same 16:10 frame to prevent date changes
            # from shifting the page layout.
            cell = ImageOps.fit(cell, (960, 600), method=Image.Resampling.LANCZOS)
            target_date = start + timedelta(days=index)
            target_dir = OUTPUT_ROOT / f"{target_date.month:02d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            cell.save(target_dir / f"{target_date.isoformat()}.webp", "WEBP", quality=84, method=6)


if __name__ == "__main__":
    for atlas_spec in sys.argv[1:]:
        slice_atlas(atlas_spec)
