from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from prepare_selected_morph_keyframes import (  # noqa: E402
    normalize_skin_tone,
    remap_torso,
    skin_tone_statistics,
)


class MorphKeyframePreparationTests(unittest.TestCase):
    def test_skin_tone_normalization_moves_face_toward_target(self):
        image = np.full((240, 180, 3), (125, 155, 195), dtype=np.uint8)
        landmarks = np.asarray(
            [[65, 85], [115, 85], [90, 115], [75, 145], [105, 145]],
            dtype=np.float64,
        )
        before, _ = skin_tone_statistics(image, landmarks)
        target = before + np.asarray([6.0, -3.0, 4.0])

        normalized, metadata = normalize_skin_tone(image, landmarks, target)
        after, _ = skin_tone_statistics(normalized, landmarks)

        self.assertLess(np.linalg.norm(after - target), np.linalg.norm(before - target))
        self.assertEqual(metadata["target_lab"], [round(float(v), 5) for v in target])
        self.assertTrue(np.array_equal(normalized[0, 0], image[0, 0]))

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
