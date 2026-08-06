from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_timeline import (  # noqa: E402
    insert_visual_bridge_candidate,
    invalidate_refined_branch,
    invalidate_younger_selections,
)


class AgeTimelineSelectionTests(unittest.TestCase):
    def test_new_selection_invalidates_all_younger_dependants(self):
        selections = {
            "31": "age31.png",
            "29": "age29.png",
            "25": "legacy-age25-outside-path.png",
            "20": "stale-age20.png",
        }

        invalidated = invalidate_younger_selections(
            selections,
            [32, 31, 29, 26, 23, 20, 17, 15, 13, 11, 9, 8],
            26,
        )

        self.assertEqual(invalidated, [25, 20])
        self.assertEqual(
            selections,
            {"31": "age31.png", "29": "age29.png"},
        )

    def test_refinement_invalidates_midpoint_and_all_younger_selections(self):
        selections = {
            "29": "age29.png",
            "26": "age26.png",
            "25": "legacy-age25.png",
            "23": "stale-age23.png",
        }

        invalidated = invalidate_refined_branch(selections, 25)

        self.assertEqual(invalidated, [25, 23])
        self.assertEqual(selections, {"29": "age29.png", "26": "age26.png"})

    def test_older_approved_anchors_are_preserved(self):
        selections = {"31": "age31.png", "29": "age29.png"}

        invalidated = invalidate_younger_selections(
            selections,
            [32, 31, 29, 26],
            29,
        )

        self.assertEqual(invalidated, [])
        self.assertEqual(selections["31"], "age31.png")
        self.assertEqual(selections["29"], "age29.png")

    def test_visual_bridge_preserves_younger_approved_chain(self):
        saved = {
            "version": 4,
            "current_age": 32,
            "extra_ages": [31],
            "selections": {
                "17": "age17.png",
                "15": "age15.png",
                "13": "age13.png",
                "11": "age11.png",
                "9": "age09.png",
                "8": "age08.png",
            },
        }
        current_plan = {
            "generation_path": [32, 31, 29, 26, 23, 20, 17, 15, 13, 11, 9, 8]
        }
        final_plan = {"generation_path": [32, 31, 29, 26, 23, 20, 17, 16, 15, 13, 11, 9, 8]}

        with tempfile.TemporaryDirectory() as temporary:
            candidates = Path(temporary)
            (candidates / "age16_bridge.png").write_bytes(b"candidate")
            with (
                patch("age_timeline.AGE_CANDIDATES_DIR", candidates),
                patch("age_timeline._read", return_value=saved),
                patch("age_timeline._write") as write,
                patch("age_timeline.get_plan", side_effect=[current_plan, final_plan]),
            ):
                result = insert_visual_bridge_candidate(
                    17, 16, 15, "age16_bridge.png"
                )

        written = write.call_args.args[0]
        self.assertEqual(written["extra_ages"], [31, 16])
        self.assertEqual(written["selections"]["16"], "age16_bridge.png")
        self.assertEqual(written["selections"]["8"], "age08.png")
        self.assertEqual(result["invalidated_ages"], [])


if __name__ == "__main__":
    unittest.main()
