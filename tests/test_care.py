import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
import db  # noqa: E402


def context():
    return {
        "elder": {
            "residence_type": "자택",
            "household_members": [{"name": "가족", "relation": "아들"}],
        },
        "memories": [
            {"memory_id": "mem_ok", "status": "verified"},
            {"memory_id": "mem_partial", "status": "partial"},
        ],
    }


class CareNormalizeTest(unittest.TestCase):
    def test_drops_observation_without_direct_quote(self):
        result = care.normalize(
            {
                "observations": [{
                    "domain": "emotion",
                    "signal": "anxiety",
                    "evidence": "걱정돼",
                }]
            },
            user_text="오늘 날씨가 좋네",
            ctx=context(),
        )
        self.assertEqual(result["observations"], [])

    def test_keeps_direct_observation_and_registered_context_only(self):
        result = care.normalize(
            {
                "observations": [{
                    "domain": "emotion",
                    "signal": "fear",
                    "evidence": "무서워",
                }],
                "context_support": [
                    {"kind": "server_time", "source_id": "server_now"},
                    {"kind": "memory", "source_id": "mem_partial"},
                ],
                "emotional_support": "acknowledge",
            },
            user_text="조금 무서워",
            ctx=context(),
        )
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(
            result["context_support"],
            [{"kind": "server_time", "source_id": "server_now"}],
        )
        self.assertEqual(result["emotional_support"], "acknowledge")

    def test_drops_emotional_strategy_without_emotion_signal(self):
        result = care.normalize(
            {"emotional_support": "validate_emotion"},
            user_text="안녕",
            ctx=context(),
        )
        self.assertEqual(result["emotional_support"], "none")

    def test_safety_rewrite_keeps_observation_but_clears_claimed_actions(self):
        result = care.normalize(
            {
                "observations": [{
                    "domain": "emotion",
                    "signal": "loneliness",
                    "evidence": "외로워",
                }],
                "context_support": [
                    {"kind": "residence", "source_id": "elder_profile.residence_type"}
                ],
                "emotional_support": "validate_emotion",
            },
            user_text="외로워",
            ctx=context(),
            response_rewritten=True,
        )
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["context_support"], [])
        self.assertEqual(result["emotional_support"], "none")

    def test_meaningful_moment_requires_quote_and_verified_memory(self):
        result = care.normalize(
            {
                "meaningful_moments": [
                    {
                        "category": "gratitude",
                        "evidence": "우리 애들이 잘 커줘서 고맙지",
                        "related_memory_ids": ["mem_ok", "mem_partial", "mem_fake"],
                    },
                    {
                        "category": "pride",
                        "evidence": "내가 평생 학교에서 아이들을 가르쳤지",
                        "related_memory_ids": [],
                    },
                ]
            },
            user_text="우리 애들이 잘 커줘서 고맙지",
            ctx=context(),
        )
        self.assertEqual(len(result["meaningful_moments"]), 1)
        self.assertEqual(
            result["meaningful_moments"][0]["related_memory_ids"],
            ["mem_ok"],
        )

    def test_explicit_signals_are_restored_and_wrong_label_is_dropped(self):
        text = "혼자 있으니까 너무 무섭고 외롭네. 넘어져서 일어나기가 힘들다."
        result = care.normalize(
            {
                "observations": [{
                    "domain": "daily_living",
                    "signal": "item_location_uncertain",
                    "evidence": "일어나기가 힘들다",
                }]
            },
            user_text=text,
            ctx=context(),
        )
        signals = {row["signal"] for row in result["observations"]}
        self.assertIn("fear", signals)
        self.assertIn("loneliness", signals)
        self.assertNotIn("item_location_uncertain", signals)

    def test_hometown_words_create_evidence_grounded_meaning(self):
        text = "옛날에 살던 고향 집 앞 냇가가 생각난다. 그때가 참 좋았는데 고맙구나."
        result = care.normalize({}, user_text=text, ctx=context())
        signals = {row["signal"] for row in result["observations"]}
        categories = {row["category"] for row in result["meaningful_moments"]}
        # 관계·정서 자산은 임상 관찰 8도메인과 분리한다.
        self.assertFalse({"longing", "gratitude"} & signals)
        self.assertTrue({"longing", "gratitude", "life_story"}.issubset(categories))

    def test_family_worry_and_remembered_name_are_kept_separately(self):
        text = (
            "우리 정훈이는 밖에서 안 추우려나? "
            "그래도 정훈이 이름은 안 잊어버려."
        )
        result = care.normalize({}, user_text=text, ctx=context())
        signals = {row["signal"] for row in result["observations"]}
        categories = {row["category"] for row in result["meaningful_moments"]}
        self.assertIn("worry_for_family", signals)
        self.assertIn("affection", categories)


class CareStorageTest(unittest.TestCase):
    def test_existing_utterance_table_gains_care_data_and_round_trips_json(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE utterances ("
            "utterance_id INTEGER PRIMARY KEY, transcript TEXT)"
        )

        added = db._add_missing_columns(conn)
        self.assertEqual(added, ["utterances.care_data"])

        payload = {
            "observations": [{
                "domain": "emotion",
                "signal": "fear",
                "evidence": "무서워",
            }],
            "context_support": [],
            "emotional_support": "acknowledge",
            "daily_action": None,
        }
        db.insert(conn, "utterances", {
            "utterance_id": 1,
            "transcript": "괜찮아, 같이 얘기하자.",
            "care_data": payload,
        })
        row = conn.execute("SELECT * FROM utterances").fetchone()
        self.assertEqual(db._row(row)["care_data"], payload)
        conn.close()


if __name__ == "__main__":
    unittest.main()
