"""
계약 테스트 공용 설비.

두 가지를 반드시 지킨다.

1. **실제 DB 를 건드리지 않는다.** `STORAGE_DIR` 을 임시 폴더로 바꿔치기한다.
   `backend/storage.py` 가 import 시점에 이 환경변수를 읽으므로, backend 모듈을
   import 하기 전에 세팅해야 한다.

2. **LLM 을 호출하지 않는다.** `llm.call_json` 을 대역으로 바꾼다. 무료 티어
   쿼터를 쓰지 않고 오프라인에서 즉시 돌아야 커밋마다 실행할 수 있다.

안전 정책 자체의 검증은 여기가 아니라 `tools/eval.py` 담당이다. 역할 구분은
`docs/05-api-and-events.md` 10절.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ★ backend import 보다 먼저 와야 한다. storage.py 가 import 시점에 읽는다.
_TMP = tempfile.mkdtemp(prefix="memory_call_test_")
os.environ["STORAGE_DIR"] = _TMP

# llm.py 는 키가 없으면 import 시점에 sys.exit 한다. 실제로 호출하지는 않으므로
# 자리만 채운다. 이 값으로 네트워크에 나가는 일이 없도록 call_json 을 대역으로
# 바꾸는 것이 stub_llm 픽스처의 역할이다.
os.environ.setdefault("LLM_API_KEY", "test-key-never-used")

sys.path.insert(0, str(ROOT / "backend"))

import conversation  # noqa: E402
import db  # noqa: E402
import llm  # noqa: E402

SEED_PATH = ROOT / "data" / "seed.json"


def _seed(conn) -> str:
    """seed.json 을 임시 DB 에 넣는다. init_db.py 와 같은 순서."""
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    elder_id = seed["elder"]["elder_id"]

    db.insert(conn, "elder_profiles", seed["elder"])
    for p in seed.get("personas") or [seed.get("persona")]:
        db.insert(conn, "personas", dict(p, elder_id=elder_id))
    for m in seed["memories"]:
        db.insert(conn, "memories", dict(m, elder_id=elder_id))
    for s in seed["schedules"]:
        db.insert(conn, "schedules", dict(s, elder_id=elder_id))
    for m in seed["medications"]:
        db.insert(conn, "medications", dict(m, elder_id=elder_id))
    conn.commit()
    return elder_id


@pytest.fixture()
def fresh_db():
    """테스트마다 스키마 + 시드를 새로 만든다."""
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    conn = db.connect()
    db.init_schema(conn)
    elder_id = _seed(conn)
    conn.close()
    return elder_id


@pytest.fixture()
def stub_llm(monkeypatch):
    """`llm.call_json` 을 대역으로 바꾼다.

    돌려주는 함수에 dict 를 넘기면 다음 호출의 응답이 된다. 안전 규칙에 걸리지
    않는 무해한 응답이 기본값이다.
    """
    state = {"reply": {
        "reply": "할아버지 목소리 들어서 좋아.",
        "intent": "greeting",
        "certainty": "none",
        "used_memory_ids": [],
        "used_schedule_ids": [],
        "risk": None,
        "medication_status": None,
        "unverified_recall": None,
        "grounding": "일반 안부",
    }}
    calls: list[list[dict]] = []

    def fake_call_json(messages, **kwargs):
        calls.append(messages)
        return dict(state["reply"])

    monkeypatch.setattr(llm, "call_json", fake_call_json)
    # conversation 모듈이 `import llm` 로 참조하므로 같은 객체를 patch 하면 된다.

    def set_reply(**fields):
        state["reply"] = dict(state["reply"], **fields)

    return type("StubLLM", (), {
        "set_reply": staticmethod(set_reply),
        "calls": calls,
    })


@pytest.fixture()
def client(fresh_db, stub_llm):
    """FastAPI 테스트 클라이언트. DB 와 LLM 이 모두 격리된 상태."""
    from fastapi.testclient import TestClient

    import api

    # 세션은 메모리에 있다. 테스트 사이에 새지 않도록 비운다.
    api.SESSIONS.clear()
    with TestClient(api.app) as c:
        c.elder_id = fresh_db
        c.llm = stub_llm
        yield c
    api.SESSIONS.clear()


@pytest.fixture()
def open_call(client):
    """고지까지 끝내서 대화할 수 있는 상태의 통화를 연다."""
    res = client.post("/api/calls", json={})
    assert res.status_code == 200, res.text
    call = res.json()
    assert client.post(f"/api/calls/{call['call_id']}/disclosed").status_code == 200
    return call


@pytest.fixture()
def session(fresh_db, stub_llm):
    """API 를 거치지 않는 Session 직접 테스트용."""
    return conversation.Session(elder_id=fresh_db)
