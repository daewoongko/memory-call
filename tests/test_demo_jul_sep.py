import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import seed_demo_jul_sep_2026 as demo  # noqa: E402


class JulySeptemberDemoTest(unittest.TestCase):
    def test_three_patients_have_registered_diagnoses_and_distinct_scenarios(self):
        self.assertEqual(set(demo.PATIENTS), {"elder_001", "elder_002", "elder_003"})
        self.assertEqual(
            {profile["diagnosis"] for profile in demo.PATIENTS.values()},
            {
                "알츠하이머 치매 · 고혈압",
                "루이소체 치매 · 파킨슨증",
                "혈관성 치매 · 고혈압 · 뇌경색 과거력",
            },
        )
        self.assertIn("time", demo.PATIENTS["elder_001"]["scenarios"])
        self.assertIn("hallucination", demo.PATIENTS["elder_002"]["scenarios"])
        self.assertIn("word", demo.PATIENTS["elder_003"]["scenarios"])

    def test_september_trends_emphasize_each_patients_characteristic(self):
        gildong = demo.PATIENTS["elder_001"]["weights"]
        sunja = demo.PATIENTS["elder_002"]["weights"]
        jeongho = demo.PATIENTS["elder_003"]["weights"]

        self.assertGreater(gildong[9]["time"], gildong[7]["time"])
        self.assertGreater(gildong[9]["med"], gildong[7]["med"])
        self.assertGreater(sunja[9]["hallucination"], sunja[7]["hallucination"])
        self.assertGreater(sunja[9]["dizzy"], sunja[7]["dizzy"])
        self.assertGreater(jeongho[9]["word"], jeongho[7]["word"])
        self.assertGreater(jeongho[9]["med"], jeongho[7]["med"])

    def test_range_covers_all_of_july_august_and_september(self):
        self.assertEqual(demo.START.isoformat(), "2026-07-01")
        self.assertEqual(demo.END.isoformat(), "2026-09-30")
        self.assertEqual(len(list(demo.daterange(demo.START, demo.END))), 92)

    def test_seed_version_forces_existing_demo_data_to_refresh_once(self):
        self.assertEqual(demo.SEED_VERSION, "patient-profile-trends-v2")


if __name__ == "__main__":
    unittest.main()
