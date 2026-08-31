import json
import unittest
from pathlib import Path

from tools.demo_config import (
    DEMO_CALL_COUNT,
    DEMO_DATE,
    DEMO_DIARY_COUNT,
    DEMO_DIARY_TITLE,
    DEMO_DURATION_MINUTES,
    DEMO_MEMORY_ID,
)


ROOT = Path(__file__).resolve().parents[1]


class DemoConfigContractTests(unittest.TestCase):
    def test_diary_payload_matches_the_single_demo_config(self):
        payload = json.loads(
            (ROOT / "data" / "gildong_diaries_2026.json").read_text(
                encoding="utf-8"
            )
        )
        diary = next(row for row in payload["diaries"] if row["date"] == DEMO_DATE)

        self.assertEqual(payload["demo_date"], DEMO_DATE)
        self.assertEqual(len(payload["diaries"]), DEMO_DIARY_COUNT)
        self.assertEqual(diary["title"], DEMO_DIARY_TITLE)
        self.assertEqual(diary["memory_id"], DEMO_MEMORY_ID)

    def test_presentation_volume_is_intentional(self):
        self.assertEqual(DEMO_CALL_COUNT, 40)
        self.assertEqual(DEMO_DURATION_MINUTES, 160)


if __name__ == "__main__":
    unittest.main()
