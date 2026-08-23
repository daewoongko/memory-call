import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSeedContractTests(unittest.TestCase):
    def test_existing_demo_database_receives_comparison_elders(self):
        source = (ROOT / "tools" / "start.py").read_text(encoding="utf-8")

        self.assertIn("elder_002", source)
        self.assertIn("elder_003", source)
        self.assertIn("seed_comparison_elders.py", source)

    def test_public_demo_receives_emotion_topic_calls_once(self):
        source = (ROOT / "tools" / "start.py").read_text(encoding="utf-8")

        self.assertIn("demo_emotion_sunja_%", source)
        self.assertIn("seed_emotion_topic_demo.py", source)


if __name__ == "__main__":
    unittest.main()
