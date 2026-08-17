from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from aihub71415 import (  # noqa: E402
    align_record_image,
    assign_subject_split,
    assign_official_subject_split,
    build_balanced_sampling_weights,
    build_pair_and_holdout_rows,
    index_archive,
    prepare_aligned_record,
)
from aihub045 import archive_key  # noqa: E402


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (100, 120), "#d8b19b").save(output, "PNG")
    return output.getvalue()


def label(subject: int, age: int, filename: str) -> dict:
    return {
        "filename": filename,
        "id": subject,
        "birth": 1990,
        "age_now": 35,
        "age_past": age,
        "format": "png",
        "width": 100,
        "height": 120,
        "device": "digital",
        "gender": "female",
        "annotation": [
            {
                "box": {"x": 20, "y": 20, "w": 60, "h": 75},
                "landmark": [[50, 58], [36, 43], [64, 43], [41, 74], [59, 74]],
            }
        ],
    }


class AIHub71415Tests(unittest.TestCase):

    def test_family_archive_key_pairs_all_official_partitions(self):
        expected = "family_part_01"
        for prefix in ("TL", "TS", "VL", "VS"):
            with self.subTest(prefix=prefix):
                self.assertEqual(archive_key(Path(f"{prefix}{expected}.zip")), expected)

    def test_balanced_sampler_boosts_age8_without_single_pair_dominance(self):
        pairs = []
        for index in range(40):
            pairs.append(
                {
                    "subject_id": f"adult-{index % 4}",
                    "target_age": 30,
                    "gap_band": "small",
                }
            )
        for index in range(4):
            pairs.append(
                {
                    "subject_id": f"child-{index}",
                    "target_age": 8,
                    "gap_band": "large",
                }
            )
        weights, report = build_balanced_sampling_weights(
            pairs,
            focus_target_age=8,
            focus_radius=2,
            focus_boost=2.0,
        )
        self.assertEqual(len(weights), len(pairs))
        self.assertGreater(report["expected_focus_fraction"], 0.5)
        self.assertLessEqual(max(weights) / min(weights), 100.0)
    def make_archive(self, root: Path) -> Path:
        archive_path = root / "sample.zip"
        with ZipFile(archive_path, "w") as archive:
            for age in (8, 18, 30):
                filename = f"0001_1990_{age:02d}_sample"
                archive.writestr(f"source/0001/{filename}.png", png_bytes())
                archive.writestr(
                    f"label/0001/{filename}.json",
                    json.dumps(label(1, age, filename)),
                )
            missing = "0002_1990_05_label_only"
            archive.writestr(
                f"label/0002/{missing}.json",
                json.dumps(label(2, 5, missing)),
            )
        return archive_path

    def test_index_reports_matched_and_label_only_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            records, summary = index_archive(self.make_archive(Path(temporary)))
        self.assertEqual(summary["labels"], 4)
        self.assertEqual(summary["matched_images"], 3)
        self.assertEqual(summary["label_only"], 1)
        self.assertEqual(summary["exact_age_8_subjects"], 1)
        self.assertEqual(sum(record.has_image for record in records), 3)

    def test_index_normalizes_case_and_extension_in_label_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "naming_variants.zip"
            with ZipFile(archive_path, "w") as archive:
                source_name = "0378_1963_08_00000001_f"
                archive.writestr(f"source/{source_name}.png", png_bytes())
                archive.writestr(
                    "label/0378_1963_08_00000001_F.json",
                    json.dumps(label(378, 8, f"{source_name.upper()}.png")),
                )

            records, summary = index_archive(archive_path)

        self.assertEqual(summary["matched_images"], 1)
        self.assertTrue(records[0].has_image)

    def test_holdout_never_uses_exact_target_as_a_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            records, _ = index_archive(self.make_archive(Path(temporary)))
        rows = [record.to_dict() for record in records]
        _, holdouts, _ = build_pair_and_holdout_rows(rows, target_age=8)
        self.assertEqual(len(holdouts), 1)
        case = holdouts[0]
        sources = case["adult_only_sources"] + case["available_anchor_sources"]
        self.assertTrue(sources)
        self.assertTrue(all(source["photo_age"] > 8 for source in sources))
        self.assertTrue(
            all(source["record_id"] not in case["excluded_target_record_ids"] for source in sources)
        )

    def test_subject_split_is_stable_and_exclusive(self):
        first = assign_subject_split("0001")
        self.assertEqual(first, assign_subject_split("0001"))
        self.assertIn(first, {"train", "val", "test"})

    def test_official_validation_is_always_held_out(self):
        self.assertEqual(assign_official_subject_split("0895", "validation"), "test")
        self.assertIn(
            assign_official_subject_split("0001", "training"),
            {"train", "val"},
        )

    def test_labeled_landmarks_create_an_aligned_crop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = self.make_archive(root)
            records, _ = index_archive(archive_path)
            row = next(record.to_dict() for record in records if record.has_image)
            output = root / "aligned.png"
            with ZipFile(archive_path) as archive:
                prepared = prepare_aligned_record(
                    archive, row, output_path=output, width=96, height=128
                )
            self.assertTrue(output.is_file())
            with Image.open(output) as aligned:
                self.assertEqual(aligned.size, (96, 128))
            self.assertEqual(prepared["alignment"]["method"], "labeled_5_point_similarity")

    def test_alignment_can_stay_in_memory_for_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = self.make_archive(root)
            records, _ = index_archive(archive_path)
            row = next(record.to_dict() for record in records if record.has_image)
            with ZipFile(archive_path) as archive:
                aligned, metadata = align_record_image(
                    archive, row, width=64, height=64
                )
        self.assertEqual(aligned.shape, (64, 64, 3))
        self.assertEqual(metadata["method"], "labeled_5_point_similarity")


if __name__ == "__main__":
    unittest.main()
