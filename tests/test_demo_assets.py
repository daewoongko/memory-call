import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402
import invites  # noqa: E402
from tools.demo_config import (  # noqa: E402
    DEMO_MORPH_AGES,
    DEMO_MORPH_DURATION_SECONDS,
    DEMO_TTS_RATE,
)


class DemoAssetContractTests(unittest.TestCase):
    def test_morph_metadata_points_only_to_canonical_tracked_assets(self):
        metadata = json.loads(
            (ROOT / "data" / "faces" / "morph.json").read_text(encoding="utf-8")
        )
        source_rows = metadata["source_sequence"]

        self.assertEqual(tuple(row["age"] for row in source_rows), DEMO_MORPH_AGES)
        self.assertEqual(
            metadata["video"]["duration_seconds"],
            DEMO_MORPH_DURATION_SECONDS,
        )
        self.assertEqual(
            metadata["timing"]["expected_duration_seconds"],
            DEMO_MORPH_DURATION_SECONDS,
        )
        self.assertEqual(
            metadata["source_manifest"],
            "data/faces/aligned/age_path_final/manifest.json",
        )
        video_path = ROOT / metadata["video"]["path"]
        self.assertTrue(video_path.is_file())
        self.assertEqual(video_path.stat().st_size, metadata["video"]["size_bytes"])
        self.assertEqual(
            hashlib.sha256(video_path.read_bytes()).hexdigest(),
            metadata["video"]["sha256"],
        )
        for row in source_rows:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])

    def test_onboarding_has_four_candidates_for_every_generated_age(self):
        candidate_dir = ROOT / "data" / "faces" / "age_candidates"
        for age in DEMO_MORPH_AGES[:-1]:
            self.assertEqual(
                len(list(candidate_dir.glob(f"age{age:02d}_*.png"))),
                4,
                f"age {age}",
            )

    def test_client_and_server_keep_the_approved_media_contract(self):
        onboarding = (
            ROOT / "frontend" / "src" / "screens" / "RoleOnboardingScreen.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn('DAEWOONG_DEMO_ASSET_ROOT = "/age-candidates"', onboarding)
        self.assertEqual(invites.INTRO_DURATION_SEC, DEMO_MORPH_DURATION_SECONDS)
        self.assertEqual(api.TTSRequest(text="안녕하세요").rate, DEMO_TTS_RATE)


if __name__ == "__main__":
    unittest.main()
