"""Observation-first medication workspace API contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402


class MedicationWorkspaceApiTest(unittest.TestCase):
    def test_medication_risk_is_not_duplicated_when_dose_row_has_same_call(self):
        risk_tasks = [{
            "id": "risk-1", "kind": "risk", "risk_type": "overdose",
            "call_id": "call-1", "task_date": "2026-08-12",
        }, {
            "id": "risk-2", "kind": "risk", "risk_type": "fall",
            "call_id": "call-2", "task_date": "2026-08-12",
        }]
        dose_tasks = [{
            "id": "dose-1", "kind": "dose", "schedule_id": "med-1",
            "task_date": "2026-08-12",
        }]
        logs = [{
            "schedule_id": "med-1", "taken_date": "2026-08-12",
            "call_id": "call-1", "status": "DUPLICATE_SUSPECTED",
        }]

        result = api._remove_represented_medication_risks(risk_tasks, dose_tasks, logs)

        self.assertEqual([row["id"] for row in result], ["risk-2"])

    def test_unlinked_medication_risk_stays_in_immediate_checks(self):
        risk_tasks = [{
            "id": "risk-1", "kind": "risk", "risk_type": "overdose",
            "call_id": "call-1", "task_date": "2026-08-12",
        }]

        result = api._remove_represented_medication_risks(risk_tasks, [], [])

        self.assertEqual(result, risk_tasks)

    def test_workspace_uses_registered_links_and_calculates_review_due(self):
        rows = {
            "reviews": [api.db._row({
                "review_id": 1, "elder_id": "elder_x", "schedule_id": "med_x",
                "review_date": "2026-08-05", "severity": 0,
                "observed_flags": [], "note": "",
            })],
            "links": [api.db._row({
                "schedule_id": "med_x", "signal": "dizziness",
                "link_level": "monitoring", "criterion_text": "기립 시 어지럼",
            })],
            "reports": [api.db._row({
                "call_id": "call_x", "started_at": "2026-08-12T09:14:00",
                "care_summary": {"safety_physical": [{
                    "signal": "dizziness", "utterance_id": 10,
                    "at": "2026-08-12T09:14:12", "evidence": "일어서니까 어지럽다",
                }]},
            })],
        }

        class Result:
            def __init__(self, values): self.values = values
            def fetchall(self): return self.values

        class Connection:
            def execute(self, query, params):
                if "medication_reviews" in query: return Result(rows["reviews"])
                if "medication_signal_links" in query: return Result(rows["links"])
                if "FROM reports" in query: return Result(rows["reports"])
                raise AssertionError(query)
            def __enter__(self): return self
            def __exit__(self, *_): return False

        medication = {
            "schedule_id": "med_x", "medication_name": "등록 약", "review_interval_days": 7,
            "signal_links": rows["links"], "monitoring_points": ["기립 시 어지럼"],
        }
        with patch.object(api.db, "connect", return_value=Connection()), \
             patch.object(api.med_mod, "listing", return_value=[medication]), \
             patch.object(api.med_mod, "status_on", return_value=[]):
            result = api.list_medications("elder_x", "2026-08-12")

        self.assertTrue(result["review_status"][0]["review_due"])
        self.assertEqual(result["review_status"][0]["review_due_on"], "2026-08-12")
        self.assertEqual(result["signal_options"][0]["label"], "어지럼")
        self.assertEqual(result["signal_options"][0]["evidence"][0]["utterance_id"], 10)
        self.assertEqual(result["signal_dates"], [{"date": "2026-08-12", "count": 1}])
        self.assertIn("원인 판단", result["safety_notice"])

    def test_invalid_as_of_is_rejected(self):
        with self.assertRaises(Exception) as raised:
            api.list_medications("elder_x", "12-08-2026")
        self.assertEqual(getattr(raised.exception, "status_code", None), 400)

    def test_care_task_records_unclear_without_collapsing_it_into_confirmed(self):
        statements = []

        class Result:
            def __init__(self, row=None): self.row = row
            def fetchone(self): return self.row

        class Connection:
            def execute(self, query, params):
                statements.append((query, params))
                if "SELECT elder_id FROM medications" in query:
                    return Result({"elder_id": "elder_x"})
                if "SELECT log_id FROM medication_logs" in query:
                    return Result(None)
                raise AssertionError(query)
            def commit(self): pass
            def __enter__(self): return self
            def __exit__(self, *_): return False

        inserted = {}
        request = api.CareTaskDoseStatusRequest(as_of="2026-08-12", status="UNCLEAR")
        with patch.object(api.db, "connect", return_value=Connection()), \
             patch.object(api.db, "insert", side_effect=lambda _conn, table, data: inserted.update(table=table, data=data) or 1):
            result = api.set_dose_task_status("med_x", request)

        self.assertEqual(result["status"], "UNCLEAR")
        self.assertEqual(inserted["table"], "medication_logs")
        self.assertEqual(inserted["data"]["status"], "UNCLEAR")
        self.assertEqual(inserted["data"]["evidence_text"], "담당자 체크: 불확실")

    def test_care_task_rejects_unknown_dose_status(self):
        with self.assertRaises(Exception):
            api.CareTaskDoseStatusRequest(as_of="2026-08-12", status="DONE")


if __name__ == "__main__":
    unittest.main()
