from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from prepare_selected_morph_keyframes import remap_torso  # noqa: E402


class MorphKeyframePreparationTests(unittest.TestCase):
    def test_torso_remap_keeps_face_rows_bit_identical(self):
        height, width = 1024, 768
        image = np.zeros((height, width, 3), dtype=np.uint8)
        image[:, :, 0] = np.arange(height, dtype=np.uint16)[:, None] % 255
        image[:, :, 1] = np.arange(width, dtype=np.uint16)[None, :] % 255
        image[:, :, 2] = 127
        current = {
            "collar_x": 400.0,
            "collar_apex": 815.0,
            "shoulder_mean": 752.0,
            "shoulder_delta": 24.0,
            "collar_nose_offset": 18.0,
        }
        target = {
            "collar_apex": 764.0,
            "shoulder_mean": 723.0,
            "shoulder_delta": 22.0,
            "collar_nose_offset": 4.0,
        }

        result, shifts = remap_torso(image, current, target)

        self.assertTrue(np.array_equal(result[:621], image[:621]))
        self.assertLess(shifts["dy_body"], 0)
        self.assertLess(shifts["dx_body"], 0)


if __name__ == "__main__":
    unittest.main()
