import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSeedContractTests(unittest.TestCase):
    def test_deployment_uses_only_the_gildong_presentation_seed(self):
        source = (ROOT / "tools" / "start.py").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("seed_gildong_demo.py", source)
        self.assertIn("from tools.demo_config import", source)
        self.assertIn("_demo_seed_is_current", source)
        self.assertIn("--preserve-from", source)
        self.assertIn("data/gildong_diaries_2026.json", dockerfile)
        self.assertNotIn("COPY tools/ ./tools/", dockerfile)
        self.assertIn("COPY tools/start.py ./tools/start.py", dockerfile)
        self.assertIn("COPY tools/demo_config.py ./tools/demo_config.py", dockerfile)
        self.assertIn("value: gildong", render)
        self.assertNotIn("elder_002", source)
        self.assertNotIn("seed_comparison", source)
        self.assertNotIn("seed_high_volume", source)

    def test_deployment_includes_the_daewoong_demo_media_bundle(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY data/faces/ ./storage/faces/", dockerfile)
        self.assertNotIn("data/personas/persona_godaewoong", dockerfile)

    def test_demo_version_check_closes_database_before_atomic_replacement(self):
        spec = importlib.util.spec_from_file_location(
            "start_for_demo_seed_test", ROOT / "tools" / "start.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class Cursor:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            closed = False

            def execute(self, sql, _params):
                if "FROM calls" in sql:
                    return Cursor((40, 160 * 60))
                if "FROM heart_artworks" in sql:
                    return Cursor((module.DEMO_DIARY_TITLE,))
                return Cursor((module.DEMO_MEMORY_TITLE, "verified", 1))

            def close(self):
                self.closed = True

        connection = Connection()
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "memory_call.sqlite"
            database.touch()
            with patch.object(module.db, "DB_PATH", database), patch.object(
                module.db, "connect", return_value=connection
            ):
                self.assertTrue(module._demo_seed_is_current())
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
