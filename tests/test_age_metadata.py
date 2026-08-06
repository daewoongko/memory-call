from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from age_metadata import (  # noqa: E402
    age_on_date,
    prompt_demographic_description,
    resolve_reference_age,
)


class AgeMetadataTests(unittest.TestCase):
    def test_age_on_photo_date_respects_birthday(self):
        birth = date(1994, 8, 6)
        self.assertEqual(age_on_date(birth, date(2026, 8, 5)), 31)
        self.assertEqual(age_on_date(birth, date(2026, 8, 6)), 32)

    def test_dates_are_a_verified_age_anchor(self):
        result = resolve_reference_age(32, "1994-01-01", "2026-08-05")
        self.assertEqual(result, (32, "1994-01-01", "2026-08-05", "verified_dates"))

    def test_mismatched_manual_and_date_age_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "다릅니다"):
            resolve_reference_age(31, "1994-01-01", "2026-08-05")

    def test_demographic_prompt_is_bounded(self):
        self.assertEqual(
            prompt_demographic_description(
                {"population_group": "korean", "biological_sex": "male"}
            ),
            "Korean male person",
        )
        self.assertEqual(prompt_demographic_description({}), "person")


if __name__ == "__main__":
    unittest.main()
