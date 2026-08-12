"""지남력 사실의 원천이 등록된 값에서만 나오는지 확인한다.

AI 가 "지금 집에 있잖아" 처럼 현재 상황을 단언하면 절대 규칙 2번 위반이다.
1단계는 그 단언의 재료를 서버가 통제하는 것까지를 보장한다.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import persona  # noqa: E402


ELDER = {
    "name": "고길동",
    "preferred_call_name": "할아버지",
    "residence_type": "자택 (아들 부부와 함께)",
    "household_members": [
        {"name": "정훈", "relation": "아들"},
    ],
    "anxiety_triggers": ["가족이 오지 않는다고 느낄 때"],
    "calming_phrases": ["괜찮아, 천천히 얘기해도 돼."],
    "frequent_questions": ["오늘 누가 오니?"],
    "hearing_support": True,
}


class ResidenceBlockTests(unittest.TestCase):
    def test_registered_residence_reaches_the_prompt(self):
        block = persona._elder_block(ELDER)

        self.assertIn("평소 지내는 곳: 자택 (아들 부부와 함께)", block)
        self.assertIn("정훈(아들)", block)

    def test_missing_residence_is_labelled_not_omitted(self):
        """빼 버리면 모델이 지어낸다. 넣고 미등록이라고 말해야 한다."""
        absent = {
            key: value
            for key, value in ELDER.items()
            if key not in ("residence_type", "household_members")
        }
        blank = {**ELDER, "residence_type": "   ", "household_members": []}
        null = {**ELDER, "residence_type": None, "household_members": None}

        for case, label in ((absent, "키 없음"), (blank, "빈 값"), (null, "null")):
            with self.subTest(case=label):
                block = persona._elder_block(case)
                self.assertIn("평소 지내는 곳: 미등록", block)
                self.assertIn("평소 함께 사는 사람: 미등록", block)

    def test_partial_registration_does_not_borrow_the_other_field(self):
        block = persona._elder_block({**ELDER, "household_members": []})
        self.assertIn("평소 지내는 곳: 자택 (아들 부부와 함께)", block)
        self.assertIn("평소 함께 사는 사람: 미등록", block)

    def test_block_never_claims_the_present_moment(self):
        """'평소' 라는 한정이 빠지면 모델이 현재 위치로 읽는다."""
        block = persona._elder_block(ELDER)
        residence_lines = [
            line for line in block.splitlines()
            if "지내는 곳" in line or "함께 사는 사람" in line
        ]
        self.assertEqual(len(residence_lines), 2)
        for line in residence_lines:
            self.assertTrue(line.startswith("평소"), line)


class PromptContractTests(unittest.TestCase):
    def setUp(self):
        self.prompt = (
            ROOT / "backend" / "prompts" / "persona_system.md"
        ).read_text(encoding="utf-8")

    def test_residence_is_an_allowed_fact_source(self):
        self.assertIn("평소 지내는 곳", self.prompt)

    def test_present_location_is_explicitly_forbidden(self):
        self.assertIn("현재 위치", self.prompt)
        self.assertIn("지금 집에 있잖아", self.prompt)


class ColumnMigrationTests(unittest.TestCase):
    def test_existing_database_gains_the_new_columns(self):
        """--reset 없이도 시연 DB 가 스키마를 따라와야 한다."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # 새 컬럼이 없던 시절의 테이블을 흉내낸다.
        conn.execute(
            "CREATE TABLE elder_profiles ("
            "elder_id TEXT PRIMARY KEY, name TEXT NOT NULL)"
        )

        added = db._add_missing_columns(conn)

        columns = {r["name"] for r in conn.execute("PRAGMA table_info(elder_profiles)")}
        self.assertIn("residence_type", columns)
        self.assertIn("household_members", columns)
        self.assertCountEqual(
            added,
            [
                "elder_profiles.residence_type",
                "elder_profiles.household_members",
                "elder_profiles.diagnosis_label",
                "elder_profiles.care_baseline",
                "elder_profiles.medical_cautions",
            ],
        )

        # 두 번 돌려도 실패하지 않아야 한다.
        self.assertEqual(db._add_missing_columns(conn), [])
        conn.close()

    def test_household_members_round_trips_as_json(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE elder_profiles ("
            "elder_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "residence_type TEXT, household_members TEXT)"
        )
        db.insert(conn, "elder_profiles", {
            "elder_id": "elder_001",
            "name": "고길동",
            "residence_type": "자택",
            "household_members": ELDER["household_members"],
        })
        row = conn.execute("SELECT * FROM elder_profiles").fetchone()
        conn.close()

        self.assertEqual(db._row(row)["household_members"], ELDER["household_members"])


if __name__ == "__main__":
    unittest.main()
