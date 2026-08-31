"""Final presentation exposes only the elder/guardian product surface."""

import sys
import importlib.util
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402

SEED_SPEC = importlib.util.spec_from_file_location(
    "seed_gildong_demo", ROOT / "tools" / "seed_gildong_demo.py"
)
seed_gildong_demo = importlib.util.module_from_spec(SEED_SPEC)
assert SEED_SPEC.loader
SEED_SPEC.loader.exec_module(seed_gildong_demo)


def test_medication_and_care_workflow_routes_are_not_exposed():
    paths = {route.path for route in api.app.routes}
    retired_fragments = ("medications", "pending-call", "care-tasks", "handovers")

    assert not {
        path for path in paths
        if any(fragment in path for fragment in retired_fragments)
    }


def test_guardian_analysis_routes_remain_available():
    paths = {route.path for route in api.app.routes}

    assert "/api/elders/{elder_id}/reports" in paths
    assert "/api/elders/{elder_id}/summary" in paths


def test_demo_day_analytics_have_visible_variation_and_life_stage_evidence():
    demo_day = date(2026, 8, 31)
    domain_counts = Counter(row[0] for row in seed_gildong_demo.observation_plan(demo_day))
    assert domain_counts == seed_gildong_demo.DEMO_DOMAIN_COUNTS

    indexes = seed_gildong_demo.repeated_call_indexes(demo_day)
    starts = [seed_gildong_demo.start_offset_minutes(demo_day, index) for index in indexes]
    intervals = [current - previous for previous, current in zip(starts, starts[1:])]
    assert intervals == [62, 50, 40, 32, 16]

    counts = [
        seed_gildong_demo.call_count(date(2026, month, day))
        for month, days in ((8, 31), (9, 30), (10, 31))
        for day in range(1, days + 1)
    ]
    assert seed_gildong_demo.call_count(demo_day) == 40
    assert min(counts) >= 36 and max(counts) <= 44

    life_stage_lines = [line for line, _reply in seed_gildong_demo.LIFE_STAGE_DIALOGUES.values()]
    assert any("학교" in line for line in life_stage_lines)
    assert any("애들 밥" in line for line in life_stage_lines)
    assert sum("회사" in line for line in life_stage_lines) == 2
    assert any("가족을 먹여" in line for line in life_stage_lines)


def test_seeded_transcript_depth_tracks_call_duration():
    demo_day = date(2026, 8, 31)
    short = seed_gildong_demo.conversation_exchanges(demo_day, 0, 155, "대웅")
    medium = seed_gildong_demo.conversation_exchanges(demo_day, 1, 240, "정훈")
    long = seed_gildong_demo.conversation_exchanges(demo_day, 2, 352, "미영")

    assert len(short) == 4
    assert len(medium) == 7
    assert len(long) == 11
    assert short[-1] == seed_gildong_demo.CLOSING_EXCHANGE
    assert medium[-1] == seed_gildong_demo.CLOSING_EXCHANGE
    assert long[-1] == seed_gildong_demo.CLOSING_EXCHANGE
