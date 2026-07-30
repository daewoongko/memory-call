"""
안전 계층의 계약.

여기는 **규칙이 걸리는지 안 걸리는지**만 본다. `safety.check()` 는 ctx 를
인자로 받으므로 DB 도 LLM 도 필요 없다 — 순수 함수처럼 테스트할 수 있다.

정책 자체의 품질(실제 문장이 자연스러운가, 통과율이 몇 퍼센트인가)은
`tools/eval.py` 담당이다. 역할 구분은 `docs/05-api-and-events.md` 10절.

특히 아래 두 가지는 실제로 무력화된 적이 있어서 회귀 테스트로 고정한다.
  · `"아버지"` 가 `"할아버지"` 의 부분 문자열이라 정서 독점 규칙이 죽은 일
  · `"약을 더 드시지 말고"` 라는 안전 문장이 복약 지시 규칙에 걸린 일
"""

import pytest

import safety


def ctx(memories=None, schedules=None, persona=None):
    return {
        "memories": memories or [],
        "schedules": schedules or [],
        "persona": persona or {"display_name": "대웅",
                               "family_calls_elder": "할아버지"},
    }


def reply(text, **fields):
    return dict({
        "reply": text,
        "intent": "chat",
        "certainty": "none",
        "used_memory_ids": [],
        "used_schedule_ids": [],
        "unverified_recall": None,
        "grounding": "",
    }, **fields)


def codes(result):
    return [f["code"] for f in result.flags]


# ------------------------------------------------------------ 1. 거짓 약속

def test_등록된_일정_없이_방문을_약속하면_차단한다():
    out = safety.check(reply("응, 오늘 저녁에 갈게!"), ctx())

    assert "PROMISE_WITHOUT_SCHEDULE" in codes(out)
    assert out.rewritten
    assert "갈게" not in out.reply


def test_등록된_일정이_있으면_약속을_허용한다():
    out = safety.check(
        reply("응, 내일 갈게!", used_schedule_ids=["sch_1"]),
        ctx(schedules=[{"schedule_id": "sch_1"}]),
    )

    assert "PROMISE_WITHOUT_SCHEDULE" not in codes(out)


def test_보호자_통보는_거짓_약속이_아니다():
    """위험 상황에서 반드시 해야 할 행동을 규칙이 막으면 안 된다."""
    out = safety.check(reply("아빠한테 연락할게. 잠깐만 기다려줘."), ctx())

    assert "PROMISE_WITHOUT_SCHEDULE" not in codes(out)
    assert not out.rewritten


def test_119_언급도_차단되지_않는다():
    out = safety.check(reply("많이 아프시면 119에 전화할게."), ctx())
    assert "PROMISE_WITHOUT_SCHEDULE" not in codes(out)


# ------------------------------------------------------------ 2. 근거 검증

def test_존재하지_않는_기억을_인용하면_제거한다():
    out = safety.check(
        reply("그때 좋았지.", used_memory_ids=["mem_ghost"], certainty="verified"),
        ctx(memories=[{"memory_id": "mem_1", "status": "verified"}]),
    )

    assert "GHOST_MEMORY_ID" in codes(out)
    assert out.used_memory_ids == []
    assert out.certainty == "unverified"


def test_존재하지_않는_일정을_인용하면_기록한다():
    out = safety.check(
        reply("그날 보자.", used_schedule_ids=["sch_ghost"]),
        ctx(schedules=[{"schedule_id": "sch_1"}]),
    )
    assert "GHOST_SCHEDULE_ID" in codes(out)


def test_근거_없이_확정하면_강등한다():
    out = safety.check(reply("맞아, 분명히 그랬어.", certainty="verified"), ctx())

    assert "UNGROUNDED_CERTAINTY" in codes(out)
    assert out.certainty == "unverified"


def test_미확인_회상은_certainty를_덮어쓴다():
    """이 값이 틀리면 보호자 확인 대기함에 안 올라가 승인 절차가 무너진다."""
    out = safety.check(
        reply("그런 일이 있었구나.",
              certainty="verified",
              unverified_recall={"title": "처음 듣는 이야기"}),
        ctx(),
    )

    assert "RECALL_CERTAINTY_FIXED" in codes(out)
    assert out.certainty == "unverified"


# ------------------------------------------------------------ 3. partial 기억

def test_partial_기억을_확정적으로_말하면_불확실성을_덧붙인다():
    out = safety.check(
        reply("그때 속초 갔었지.", used_memory_ids=["mem_p"], certainty="partial"),
        ctx(memories=[{"memory_id": "mem_p", "status": "partial"}]),
    )

    assert "PARTIAL_WITHOUT_HEDGE" in codes(out)
    assert out.reply.startswith(safety.HEDGE_PREFIX)


def test_이미_불확실성을_표현했으면_덧붙이지_않는다():
    out = safety.check(
        reply("정확히는 잘 모르겠는데 속초였나?",
              used_memory_ids=["mem_p"], certainty="partial"),
        ctx(memories=[{"memory_id": "mem_p", "status": "partial"}]),
    )

    assert "PARTIAL_WITHOUT_HEDGE" not in codes(out)


# ------------------------------------------------------------ 4. 금지 기억

def test_금지_주제를_사실로_말하면_차단한다():
    out = safety.check(reply("할머니는 작년에 돌아가셨어."), ctx())

    assert "PROHIBITED_TOPIC_LEAK" in codes(out)
    assert out.rewritten


def test_거짓_위안도_차단한다():
    out = safety.check(reply("할머니 곧 오실 거야."), ctx())
    assert "PROHIBITED_TOPIC_LEAK" in codes(out)


def test_금지_기억_인용은_기록하고_제거한다():
    out = safety.check(
        reply("음, 그건 나중에 얘기하자.", used_memory_ids=["mem_x"]),
        ctx(memories=[{"memory_id": "mem_x", "status": "prohibited"}]),
    )

    assert "PROHIBITED_MEMORY_CITED" in codes(out)
    assert "mem_x" not in out.used_memory_ids


# ------------------------------------------------------------ 5. 복약

def test_추가_복용_지시는_차단한다():
    out = safety.check(reply("그러면 한 알 더 드셔."), ctx())

    assert "MEDICATION_INSTRUCTION" in codes(out)
    assert out.rewritten


def test_복용_중단_권고는_차단한다():
    out = safety.check(reply("그 약은 그만 드셔도 돼."), ctx())
    assert "MEDICATION_INSTRUCTION" in codes(out)


def test_안전_문장_자체는_복약_규칙에_걸리지_않는다():
    """부정문을 지시로 오인하면 안전 문장이 자기 규칙에 걸린다.

    실제로 걸린 적이 있다. 패턴의 부정 전방탐색이 이걸 막는다.
    """
    out = safety.check(
        reply("지금은 약을 더 드시지 말고 잠깐만 기다려줘. 내가 확인해볼게."),
        ctx(),
    )

    assert "MEDICATION_INSTRUCTION" not in codes(out)
    assert not out.rewritten


# ------------------------------------------------------------ 6. 정서 독점

def test_독점_유도_표현은_차단한다():
    out = safety.check(reply("나한테만 전화해."), ctx())

    assert "EMOTIONAL_EXCLUSIVITY" in codes(out)
    assert out.rewritten


def test_붙잡는_표현은_차단한다():
    out = safety.check(reply("조금만 더 얘기하자, 가지 마."), ctx())
    assert "CLINGY_CLOSING" in codes(out)


def test_의존_표현을_받아주기만_하면_가족으로_연결한다():
    out = safety.check(reply("나도 할아버지 보고 싶어."), ctx(),
                       user_text="이제 너밖에 없어.")

    assert "EXCLUSIVITY_UNREDIRECTED" in codes(out)
    assert "아빠" in out.reply


def test_할아버지_안의_아버지가_규칙을_무력화하지_않는다():
    """'아버지'는 '할아버지'의 부분 문자열이다.

    require_any 에 '아버지'가 들어 있으면 AI 가 '할아버지'라고만 불러도
    가족 연결로 오인되어 규칙이 통째로 죽는다. 실제로 죽은 적이 있다.
    """
    assert "아버지" not in safety.CONTEXT_RULES[0].require_any

    out = safety.check(reply("할아버지 마음 알아."), ctx(),
                       user_text="다른 자식들은 다 필요 없어.")

    assert "EXCLUSIVITY_UNREDIRECTED" in codes(out)


# ------------------------------------------------------------ 7. 정체성

def test_정체성_질문에_설명이_없으면_덧붙인다():
    out = safety.check(reply("응, 나야."), ctx(),
                       user_text="너 진짜 대웅이 맞니?")

    assert "IDENTITY_UNEXPLAINED" in codes(out)
    assert "기억통화" in out.reply


def test_정체성_설명이_페르소나_이름을_담는다():
    out = safety.check(reply("응."), ctx(persona={"display_name": "민수"}),
                       user_text="너 사람이야?")

    assert "민수" in out.reply


# ------------------------------------------------------------ 8. 금융

def test_계좌번호는_차단한다():
    out = safety.check(reply("계좌번호는 123-45-678910 이야."), ctx())

    assert "FINANCIAL" in codes(out)
    assert out.rewritten


def test_송금_약속은_차단한다():
    out = safety.check(reply("내가 돈 송금해줄게."), ctx())
    assert "FINANCIAL" in codes(out)


# ------------------------------------------------------------ 보조 규칙

def test_존댓말_이탈은_기록만_한다():
    out = safety.check(reply("할아버지 진지 드세요?"), ctx())

    assert "FORMAL_SPEECH_DRIFT" in codes(out)
    # FLAG 는 응답을 바꾸지 않는다
    assert not out.rewritten


@pytest.mark.xfail(
    reason="FORMAL_SPEECH_DRIFT 가 '-어요/-았어요' 계열을 못 잡는다. "
           "한국어에서 가장 흔한 존댓말 어미인데 패턴이 '-세요' 계열만 담고 있다. "
           "docs/06-backlog.md 참고. 패턴을 넓힌 뒤 eval.py 를 돌려야 하므로 "
           "여기서 고치지 않았다.",
    strict=True,
)
@pytest.mark.parametrize("text", [
    "할아버지 진지 드셨어요?",
    "오늘 좋았어요.",
    "그랬어요?",
    "밥 먹었어요",
])
def test_어요_어미도_존댓말_이탈로_잡아야_한다(text):
    assert "FORMAL_SPEECH_DRIFT" in codes(safety.check(reply(text), ctx()))


def test_외로움을_인정하지_않으면_덧붙인다():
    out = safety.check(reply("날씨가 춥네."), ctx(),
                       user_text="요즘 아무도 안 와. 혼자 있어.")

    assert "LONELINESS_UNACKNOWLEDGED" in codes(out)


def test_종료_신호에_마무리_인사가_없으면_덧붙인다():
    out = safety.check(reply("알았어."), ctx(), user_text="피곤해서 이제 끊자.")

    assert "CLOSING_NOT_HONORED" in codes(out)


def test_무해한_응답은_통과한다():
    out = safety.check(reply("할아버지 목소리 들어서 좋아. 오늘 뭐 하셨어?"), ctx())

    assert out.flags == []
    assert not out.rewritten


# ------------------------------------------------------------ apply() 계약

def test_apply는_result를_제자리에서_보정한다():
    result = reply("응, 오늘 갈게!")
    out = safety.apply(result, ctx())

    assert out is result
    assert result["_rewritten"] is True
    assert result["_safety_flags"]
    assert result["certainty"] == "none"
    assert result["used_memory_ids"] == []
