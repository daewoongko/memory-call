import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSeedContractTests(unittest.TestCase):
    def test_deployment_uses_only_the_gildong_presentation_seed(self):
        source = (ROOT / "tools" / "start.py").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("seed_gildong_demo.py", source)
        self.assertIn("data/gildong_diaries_2026.json", dockerfile)
        self.assertIn("value: gildong", render)
        self.assertNotIn("elder_002", source)
        self.assertNotIn("seed_comparison", source)
        self.assertNotIn("seed_high_volume", source)


if __name__ == "__main__":
    unittest.main()
