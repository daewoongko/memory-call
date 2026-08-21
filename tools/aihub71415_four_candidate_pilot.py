"""Compatibility notice for the retired direct-generation experiment.

The product now uses only guardian-selected, adjacent-age generation.  Keep a
small executable shim so old notes fail with an actionable message instead of
silently running the obsolete direct/FRAN-output comparison.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "This direct-generation pilot is retired. Use tools/age_run_path.py "
        "for staged product generation, tools/aihub_face_dataset_audit.py "
        "for dataset checks, and tools/aihub71415_sequential_flux_eval.py "
        "for the held-out baseline/adapted comparison."
    )


if __name__ == "__main__":
    main()
