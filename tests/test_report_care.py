import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_API_KEY", "test-key-not-used")

import report  # noqa: E402


class CareReportAggregationTest(unittest.TestCase):
    def test_family_mentions_count_only_registered_names(self):
        utterances = [
            {"utterance_id": 1, "speaker": "elder", "transcript": "대웅이는 잘 있나?"},
            {"utterance_id": 2, "speaker": "ai", "transcript": "응."},
            {"utterance_id": 3, "speaker": "elder", "transcript": "대웅이 보고 싶네."},
            {"utterance_id": 4, "speaker": "elder", "transcript": "민수도 바쁘겠지."},
        ]
        mentions = report._family_mentions(utterances, ["대웅", "민수"])

        self.assertEqual(mentions[0]["name"], "대웅")
        self.assertEqual(mentions[0]["count"], 2)
        self.assertEqual(mentions[0]["utterance_ids"], [1, 3])
        self.assertEqual(mentions[1]["count"], 1)

    def test_care_analysis_quotes_database_utterance_not_model_evidence(self):
        utterances = [
            {
                "utterance_id": 10,
                "seq": 1,
                "speaker": "elder",
                "transcript": "우리 딸 고생 많이 했는데.",
                "created_at": "2026-08-10T15:40:00+09:00",
            },
            {
                "utterance_id": 11,
                "seq": 2,
                "speaker": "ai",
                "transcript": "딸이 걱정됐구나.",
                "care_data": {
                    "source_utterance_id": 10,
                    "observations": [{
                        "domain": "emotion",
                        "signal": "worry_for_family",
                        "evidence": "모델이 다듬은 문장",
                    }],
                    "meaningful_moments": [{
                        "category": "affection",
                        "evidence": "모델이 다듬은 문장",
                        "related_memory_ids": [],
                    }],
                },
            },
        ]
        result = report._care_analysis(utterances)

        self.assertEqual(
            result["emotion"][0]["evidence"],
            "우리 딸 고생 많이 했는데.",
        )
        self.assertEqual(
            result["meaningful_moments"][0]["evidence"],
            "우리 딸 고생 많이 했는데.",
        )

    def test_heart_report_translates_state_without_inventing_feeling(self):
        heart = report._heart_report(
            {
                "memory_orientation": [{"label": "사람 혼동"}],
                "emotion": [{"label": "가족 걱정"}],
                "daily_living": [],
            },
            [{
                "category": "affection", "label": "가족을 향한 애정",
                "evidence": "그래도 우리 정훈이 이름은 안 잊어버려.",
                "at": "2026-08-10T15:40:00+09:00", "related_memory_ids": [],
            }],
            [{"name": "정훈", "count": 3}], [], ["가족과 나눠보세요."], [], [], [],
        )
        self.assertIn("인지·지남력 1건", heart["day_translation"]["state"])
        self.assertIn("정훈님의 이름을 3번", heart["day_translation"]["family"])
        self.assertEqual(heart["missed_word"]["quote"], "그래도 우리 정훈이 이름은 안 잊어버려.")
        self.assertEqual(heart["memory_bridge"]["mode"], "confirm_first")
        self.assertIsNone(heart["visual_story"])

    def test_heart_report_marks_unapproved_artwork_as_imagined(self):
        heart = report._heart_report(
            {"memory_orientation": [], "emotion": [], "daily_living": []},
            [], [], [], [], [], [], [],
            {
                "status": "candidate",
                "image_url": "/heart-art/hometown-stream-v1.png",
                "source_quote": "고향 집 앞 냇가가 생각난다.",
                "alt_text": "고향 냇가 그림",
                "caption": "실제 장면을 재현한 사진은 아닙니다.",
                "memory_id": None,
            },
        )
        self.assertEqual(heart["visual_story"]["status"], "candidate")
        self.assertIn("상상 이미지", heart["visual_story"]["status_label"])

    def test_verified_memory_artwork_becomes_today_memory_banner(self):
        memory = {
            "memory_id": "mem_hometown", "status": "verified",
            "conversation_allowed": 1, "title": "고향 집 앞 냇가",
            "description": "정훈과 물고기를 잡던 냇가",
        }
        artwork = {
            "status": "approved", "memory_id": "mem_hometown",
            "image_url": "/heart-art/hometown.png", "alt_text": "고향 냇가",
            "source_quote": "옛날 냇가가 생각난다.", "caption": "확인된 가족 기억",
        }
        heart = report._heart_report(
            {"memory_orientation": [], "emotion": [], "daily_living": []},
            [{
                "category": "life_story", "label": "삶의 이야기",
                "evidence": "옛날 고향 집 앞 냇가가 생각난다. 그때가 참 좋았지.",
                "related_memory_ids": ["mem_hometown"],
            }],
            [], [], [], [], [memory], [], None,
            {"mem_hometown": artwork},
        )

        self.assertEqual(heart["memory_banner"]["image_url"], "/heart-art/hometown.png")
        self.assertIn("고향 집 앞 냇가", heart["memory_banner"]["quote"])
        self.assertIn("좋았던 시간", heart["memory_banner"]["message"])

    def test_verified_memory_title_in_direct_quote_links_without_model_id(self):
        memory = {
            "memory_id": "mem_hometown", "status": "verified",
            "conversation_allowed": 1, "title": "고향 집 앞 냇가",
            "description": "가족과 함께 지낸 곳",
        }
        artwork = {
            "status": "approved", "memory_id": "mem_hometown",
            "image_url": "/heart-art/hometown.png", "alt_text": "고향 냇가",
            "source_quote": "고향 냇가가 생각난다.", "caption": "확인된 가족 기억",
        }
        heart = report._heart_report(
            {"memory_orientation": [], "emotion": [], "daily_living": []},
            [{
                "category": "longing", "label": "그리움",
                "evidence": "옛날 고향 집 앞 냇가가 생각난다.",
                "related_memory_ids": [],
            }],
            [], [], [], [], [memory], [], None,
            {"mem_hometown": artwork},
        )

        self.assertEqual(heart["memory_bridge"]["mode"], "verified")
        self.assertEqual(heart["memory_banner"]["memory_id"], "mem_hometown")
        self.assertIn("그리움", heart["memory_banner"]["message"])

    def test_narrative_fallback_never_calls_risk_normal(self):
        facts = {
            "인지_정서_생활_관찰": [{"영역": "정서", "신호": "두려움"}],
            "위험이벤트": [{"종류": "낙상", "수준": "high"}],
            "확인이필요한_기억": [],
        }
        with patch.object(report.llm, "call_schema", return_value=None):
            result = report._narrative(facts)
        self.assertNotIn("정상", result["summary"])
        self.assertIn("안전 확인", result["summary"])
        self.assertTrue(result["guardian_actions"])

    def test_period_repeats_merge_same_question_across_calls(self):
        merged = report._merge_period_repeats([
            {"repeated_questions": [{
                "question": "지금 몇 시냐?", "count": 3,
                "utterance_ids": [1, 2, 3],
            }]},
            {"repeated_questions": [{
                "question": "지금 몇 시냐?", "count": 2,
                "utterance_ids": [8, 9],
            }]},
        ])
        self.assertEqual(merged[0]["count"], 5)
        self.assertEqual(merged[0]["call_count"], 2)

    def test_rhythm_finds_peak_time_from_calls_and_grounded_signals(self):
        calls = [
            {"call_id": "c1", "started_at": "2026-08-10T18:10:00+09:00"},
            {"call_id": "c2", "started_at": "2026-08-10T18:45:00+09:00"},
            {"call_id": "c3", "started_at": "2026-08-10T09:00:00+09:00"},
        ]
        reports = [{
            "call_id": "c1",
            "care_summary": {"emotion": [{
                "signal": "loneliness", "evidence": "혼자 있으니 외롭다.",
            }]},
            "repeated_questions": [],
        }, {
            "call_id": "c2",
            "care_summary": {"daily_living": [{
                "signal": "medication_uncertain", "evidence": "약을 먹었나 모르겠다.",
            }]},
            "repeated_questions": [],
        }]

        rhythm = report._rhythm_analysis(
            calls, reports, calls, reports, today=date(2026, 8, 10)
        )

        self.assertEqual(rhythm["peak_window"]["label"], "18:00~20:00")
        self.assertEqual(rhythm["peak_window"]["calls"], 2)
        self.assertIn("외로움 관련 표현", rhythm["peak_window"]["summary"])
        self.assertEqual(rhythm["peak_window"]["evidence_examples"][0], "혼자 있으니 외롭다.")

    def test_rhythm_does_not_infer_loneliness_from_call_volume(self):
        calls = [
            {"call_id": "c1", "started_at": "2026-08-10T18:10:00+09:00"},
            {"call_id": "c2", "started_at": "2026-08-10T18:45:00+09:00"},
        ]
        reports = [{
            "call_id": "c1",
            "care_summary": {"memory_orientation": [{
                "signal": "time_confusion", "evidence": "지금 몇 시냐?",
            }]},
            "repeated_questions": [],
        }]

        rhythm = report._rhythm_analysis(
            calls, reports, calls, reports, today=date(2026, 8, 10)
        )

        self.assertNotIn("외로움", rhythm["peak_window"]["summary"])
        self.assertIn("시간 혼동", rhythm["peak_window"]["summary"])

    def test_daily_analysis_merges_calls_into_evidence_action_flow(self):
        calls = [
            {"call_id": "c1", "started_at": "2026-08-10T18:10:00+09:00", "duration_sec": 90},
            {"call_id": "c2", "started_at": "2026-08-10T18:40:00+09:00", "duration_sec": 120},
        ]
        reports = [{
            "call_id": "c1",
            "care_summary": {"emotion": [{
                "signal": "loneliness", "label": "외로움",
                "evidence": "혼자 있으니까 외롭고 네가 보고 싶다.",
            }]},
            "meaningful_moments": [{
                "category": "longing", "label": "그리움",
                "evidence": "혼자 있으니까 외롭고 네가 보고 싶다.",
                "at": "2026-08-10T18:10:10+09:00",
            }],
            "repeated_questions": [],
            "guardian_actions": [],
        }, {
            "call_id": "c2",
            "care_summary": {"emotion": [{
                "signal": "loneliness", "label": "외로움",
                "evidence": "오늘도 혼자라 외롭다.",
            }]},
            "meaningful_moments": [],
            "repeated_questions": [{
                "question": "언제 오니?", "count": 3, "utterance_ids": [2, 3, 4],
            }],
            "guardian_actions": ["방문 시간을 확인해 주세요."],
        }]

        daily = report._daily_analyses(
            calls, reports, [], date(2026, 8, 10), date(2026, 8, 10)
        )[0]

        self.assertEqual(daily["calls"], 2)
        self.assertEqual(daily["observations"][0]["count"], 2)
        self.assertEqual(daily["observations"][0]["evidence"][0], "혼자 있으니까 외롭고 네가 보고 싶다.")
        self.assertEqual(daily["repeated_total"], 3)
        self.assertIn("안부 통화", daily["guardian_actions"][0])
        self.assertEqual(daily["heart_report"]["quote"], "혼자 있으니까 외롭고 네가 보고 싶다.")

    def test_period_dates_accepts_selected_day_or_month(self):
        start, end, days = report._period_dates(
            30, "2026-07-01", "2026-07-31"
        )
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))
        self.assertEqual(days, 31)

        with self.assertRaises(ValueError):
            report._period_dates(30, "2026-08-10", "2026-08-01")

    def test_time_analysis_splits_one_day_into_two_hour_reports(self):
        calls = [
            {"call_id": "morning", "started_at": "2026-08-10T08:20:00+09:00", "duration_sec": 60},
            {"call_id": "evening", "started_at": "2026-08-10T18:10:00+09:00", "duration_sec": 90},
        ]
        reports = [{
            "call_id": "morning", "care_summary": {"daily_living": [{
                "signal": "medication_uncertain", "label": "복약 여부 불확실",
                "evidence": "약을 먹었는지 모르겠다.",
            }]}, "meaningful_moments": [], "repeated_questions": [], "guardian_actions": [],
        }, {
            "call_id": "evening", "care_summary": {"emotion": [{
                "signal": "loneliness", "label": "외로움",
                "evidence": "혼자 있으니 외롭다.",
            }]}, "meaningful_moments": [], "repeated_questions": [], "guardian_actions": [],
        }]

        rows = report._time_analyses(
            calls, reports, [], date(2026, 8, 10)
        )

        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["time_label"], "00:00~02:00")
        self.assertFalse(rows[0]["has_calls"])
        self.assertEqual(rows[4]["observations"][0]["label"], "복약 여부 불확실")
        self.assertTrue(rows[4]["has_calls"])
        self.assertEqual(rows[9]["observations"][0]["label"], "외로움")


if __name__ == "__main__":
    unittest.main()
