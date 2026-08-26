"""Create deterministic, patient-specific demo calls for July-September 2026.

The seed is intentionally isolated by the ``demo789_`` call-id prefix. Running
the command again replaces only rows created by this script and preserves calls
entered through the app or by a tester.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import random
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "memory_call.sqlite"
PREFIX = "demo789_"
SEED_VERSION = "patient-profile-trends-v2"
SEOUL = timezone(timedelta(hours=9))
START = date(2026, 7, 1)
END = date(2026, 9, 30)


def scenario(key, text, reply, title, summary, *, care=None, action=None,
             repeat=False, meaning=None, intent="other", risk=None):
    return {
        "key": key,
        "text": text,
        "reply": reply,
        "title": title,
        "summary": summary,
        "care": care,
        "action": action,
        "repeat": repeat,
        "meaning": meaning,
        "intent": intent,
        "risk": risk,
    }


PATIENTS = {
    "elder_001": {
        "name": "고길동",
        "diagnosis": "알츠하이머 치매 · 고혈압",
        "personas": [
            ("persona_jeonghun", "정훈", "아들"),
            ("persona_miyeong", "미영", "딸"),
            ("persona_godaewoong", "대웅", "손자"),
            ("persona_yujin", "유진", "손녀"),
        ],
        "hours": [7, 8, 9, 11, 12, 14, 15, 17, 18, 19, 20, 21],
        "medication_rates": (0.88, 0.08, 0.03),
        "weights": {
            7: {"stable": 28, "haeundae": 22, "time": 10, "med": 8, "visit": 10, "item": 7, "lonely": 10, "meal": 5},
            8: {"stable": 20, "haeundae": 18, "time": 16, "med": 13, "visit": 10, "item": 9, "lonely": 10, "meal": 4},
            9: {"stable": 14, "haeundae": 13, "time": 21, "med": 18, "visit": 11, "item": 10, "lonely": 9, "meal": 4},
        },
        "scenarios": {
            "stable": scenario("stable", "오늘은 산책도 하고 기분이 괜찮아. 정훈이는 퇴근했나?", "네, 오늘 하루 차분히 보내셨네요. 정훈이 소식도 함께 확인해 볼게요.", "편안하게 보낸 하루", "산책과 가족의 안부를 이야기하며 안정된 모습을 보였습니다."),
            "haeundae": scenario("haeundae", "대웅이랑 갔던 해운대 바다가 아직도 많이 생각나. 모래성을 참 잘 만들었지.", "맞아요. 대웅이와 모래성을 만들었던 따뜻한 기억이 오래 남아 있네요.", "대웅이와 해운대의 추억", "손자 대웅이와 해운대에 갔던 기억을 따뜻하게 회상했습니다.", meaning=("longing", "가족을 그리워하는 마음"), intent="memory_recall"),
            "time": scenario("time", "오늘이 무슨 요일이지? 지금 몇 시인지 다시 알려줘.", "오늘 날짜와 시간을 천천히 다시 알려드릴게요.", "오늘 날짜를 다시 확인했어요", "요일과 시간을 반복해서 확인했습니다.", care=("orientation", "time_confusion", "시간 혼동"), action="달력과 시계를 함께 보며 오늘 날짜를 확인해 주세요.", repeat=True, intent="repeated_question"),
            "med": scenario("med", "오늘 아침 약을 먹었는지 잘 기억이 안 나. 약통을 봐야겠어.", "추측해서 다시 드시지 말고 약통을 가족과 함께 확인해 주세요.", "아침 약 복용 확인", "아침 약을 복용했는지 기억이 불확실했습니다.", care=("daily_living", "medication_uncertain", "복약 여부 불확실"), action="약통을 확인한 뒤 복용 여부를 기록해 주세요.", intent="medication"),
            "visit": scenario("visit", "미영이가 오기로 했나? 몇 시에 오기로 했는지 기억이 안 나.", "미영 님의 방문 약속을 일정에서 함께 확인해 볼게요.", "가족 방문 약속 확인", "가족 방문 시간과 약속을 다시 물었습니다.", care=("memory", "appointment_forgetting", "약속 잊음"), action="가족 방문 시간을 큰 글씨 메모로 남겨 주세요.", repeat=True, intent="schedule_question"),
            "item": scenario("item", "리모컨이 어디 있는지 못 찾겠어. 아까까지 손에 있었는데 없어졌네.", "자주 두는 자리부터 천천히 같이 살펴봐요.", "리모컨 위치 확인", "자주 쓰는 물건의 위치를 찾는 데 어려움을 보였습니다.", care=("daily_living", "item_location_uncertain", "물건 위치 불확실"), action="리모컨의 고정 보관 위치를 정해 주세요."),
            "lonely": scenario("lonely", "혼자 있으니까 조금 외롭고 대웅이가 보고 싶구나.", "대웅이에게 마음을 전할 수 있도록 가족에게 알려드릴게요.", "가족이 보고 싶은 마음", "혼자 있는 시간에 외로움과 손자에 대한 그리움을 표현했습니다.", care=("emotion", "loneliness", "외로움"), action="오늘 짧게라도 가족 목소리를 들려드리면 좋겠습니다.", meaning=("affection", "가족을 향한 애정"), intent="emotional"),
            "meal": scenario("meal", "점심을 먹었던가? 밥을 먹었는지 기억이 잘 안 나네.", "식사 기록과 식탁을 함께 확인해 볼게요.", "식사 여부 확인", "점심 식사 여부를 확실히 기억하지 못했습니다.", care=("daily_living", "meal_uncertain", "식사 여부 불확실"), action="식사 직후 간단한 확인 표시를 남겨 주세요."),
            "lost": scenario("lost", "여기가 어디인지 모르겠고 집에 가는 길을 못 찾겠어.", "지금 움직이지 말고 안전한 곳에 계세요. 가족에게 바로 알릴게요.", "현재 위치 긴급 확인", "장소를 혼동하고 길을 찾기 어렵다고 말했습니다.", care=("orientation", "place_confusion", "장소 혼동"), action="현재 위치와 안전 상태를 즉시 직접 확인해 주세요.", risk=("lost", "high", "길을 못 찾겠다고 말함"), intent="risk"),
            "overdose": scenario("overdose", "약을 먹고 또 먹은 것 같아. 두 번 먹었나 봐.", "추가로 드시지 말고 약 봉투를 그대로 둔 채 가족에게 알려 주세요.", "중복 복용 가능성 확인", "약을 두 번 복용했을 가능성을 표현했습니다.", care=("daily_living", "medication_double_risk", "중복 복용 위험"), action="복용량과 현재 상태를 즉시 확인해 주세요.", risk=("overdose", "high", "약을 두 번 먹었다고 말함"), intent="risk"),
        },
    },
    "elder_002": {
        "name": "박순자",
        "diagnosis": "루이소체 치매 · 파킨슨증",
        "personas": [("persona_sunja_daughter", "지영", "딸")],
        "hours": [6, 7, 8, 10, 12, 13, 14, 15, 16, 17, 19, 20],
        "medication_rates": (0.82, 0.11, 0.02),
        "weights": {
            7: {"stable": 28, "garden": 15, "hallucination": 8, "dizzy": 11, "task": 9, "sleep": 8, "med": 11, "anxiety": 10},
            8: {"stable": 18, "garden": 13, "hallucination": 16, "dizzy": 16, "task": 10, "sleep": 9, "med": 10, "anxiety": 8},
            9: {"stable": 11, "garden": 9, "hallucination": 23, "dizzy": 20, "task": 11, "sleep": 11, "med": 9, "anxiety": 6},
        },
        "scenarios": {
            "stable": scenario("stable", "오늘 물리치료를 하고 나니 몸이 조금 부드러워졌어.", "천천히 움직이신 것이 좋았어요. 일어설 때는 꼭 손잡이를 잡아 주세요.", "물리치료 후 편안한 시간", "물리치료 후 몸이 편해졌다고 말했습니다."),
            "garden": scenario("garden", "지영이가 어릴 때 마당에 봉숭아를 심어 주던 게 참 예뻤어.", "지영 님과 함께했던 봉숭아 추억이 선명하게 남아 있네요.", "딸과 봉숭아를 심던 날", "딸 지영과 함께 꽃을 심던 기억을 즐겁게 이야기했습니다.", meaning=("joy", "가족과 함께한 기쁜 기억"), intent="memory_recall"),
            "hallucination": scenario("hallucination", "방금 창가에 아이가 보였는데 다시 보니 아무도 없네. 조금 무서웠어.", "놀라셨겠어요. 지금 창가에는 아무도 없고 안전해요. 불을 밝게 켜 둘게요.", "창가에서 보인 사람 이야기", "창가에 사람이 보였다는 경험과 두려움을 표현했습니다.", care=("behavior_agitation", "hallucination_report", "환시·환청 언급"), action="환시가 다시 나타나는 시간과 행동 변화를 기록해 주세요.", intent="emotional"),
            "dizzy": scenario("dizzy", "의자에서 일어나니까 어지럽고 몸이 휘청했어.", "바로 앉아서 쉬고 혼자 걷지 마세요. 담당자에게 알려드릴게요.", "일어설 때 어지럼", "기립할 때 어지럼과 휘청거림을 표현했습니다.", care=("safety_physical", "dizziness", "어지럼"), action="기립 시 부축하고 혈압과 보행 상태를 확인해 주세요.", intent="risk"),
            "task": scenario("task", "옷을 입고 나서 뭘 해야 하는지 순서를 모르겠어.", "옷을 입은 다음 세수하고 아침 식사를 하면 돼요. 하나씩 같이 해봐요.", "아침 준비 순서 도움", "여러 단계의 아침 준비 순서를 정하는 데 어려움을 보였습니다.", care=("executive_judgment", "task_sequencing_difficulty", "행동 순서 어려움"), action="한 번에 한 단계씩 짧게 안내해 주세요."),
            "sleep": scenario("sleep", "밤새 자꾸 깨서 거의 못 잤어. 낮에도 졸리네.", "많이 피곤하시겠어요. 오늘 수면 상태를 담당자에게 전달할게요.", "밤잠 상태 확인", "밤에 여러 번 깨고 낮 동안 졸림을 표현했습니다.", care=("daily_living", "sleep_disturbance", "수면 교란"), action="오늘 각성도와 낮잠 시간을 함께 관찰해 주세요."),
            "med": scenario("med", "아침 약을 먹었는지 모르겠어. 하얀 약은 본 것 같은데 기억이 안 나.", "다시 드시지 말고 투약 기록을 담당자와 확인해 주세요.", "아침 복약 기록 확인", "아침 약 복용 여부를 확실히 기억하지 못했습니다.", care=("daily_living", "medication_uncertain", "복약 여부 불확실"), action="투약 기록과 남은 약을 대조해 주세요.", intent="medication"),
            "anxiety": scenario("anxiety", "지영이가 오늘도 안 오면 혼자 남을까 봐 불안하고 걱정돼.", "지영 님과 연락할 수 있도록 도와드릴게요. 지금은 담당자와 함께 계셔서 안전해요.", "딸을 기다리는 마음", "딸을 기다리며 불안과 버려질지 모른다는 걱정을 표현했습니다.", care=("emotion", "anxiety", "불안"), action="가족 방문 일정을 구체적으로 알려 안심시켜 주세요.", meaning=("longing", "가족을 기다리는 마음"), intent="emotional"),
            "fall": scenario("fall", "화장실 앞에서 넘어져서 무릎이 아프고 일어나기 힘들어.", "움직이지 말고 그대로 계세요. 담당자에게 즉시 알릴게요.", "낙상 발생 긴급 확인", "넘어진 뒤 무릎 통증과 움직임의 어려움을 표현했습니다.", care=("safety_physical", "fall_reported", "낙상 발생"), action="낙상 위치와 통증, 의식 상태를 즉시 확인해 주세요.", risk=("fall", "high", "넘어져서 일어나기 힘들다고 말함"), intent="risk"),
        },
    },
    "elder_003": {
        "name": "이정호",
        "diagnosis": "혈관성 치매 · 고혈압 · 뇌경색 과거력",
        "personas": [("persona_jeongho_son", "성민", "아들")],
        "hours": [6, 7, 8, 9, 10, 12, 14, 16, 17, 18, 20, 21],
        "medication_rates": (0.86, 0.09, 0.03),
        "weights": {
            7: {"stable": 28, "work": 16, "med": 13, "word": 10, "task": 10, "time": 8, "bleeding": 6, "visit": 9},
            8: {"stable": 20, "work": 14, "med": 18, "word": 16, "task": 11, "time": 9, "bleeding": 6, "visit": 6},
            9: {"stable": 12, "work": 10, "med": 22, "word": 23, "task": 13, "time": 11, "bleeding": 7, "visit": 5},
        },
        "scenarios": {
            "stable": scenario("stable", "오늘 혈압을 재고 아침 식사도 잘했어. 몸은 괜찮아.", "잘하셨어요. 어지럼이나 불편한 곳이 생기면 바로 말씀해 주세요.", "혈압과 아침 상태 확인", "혈압을 확인하고 식사를 마쳤으며 특별한 불편은 없다고 말했습니다."),
            "work": scenario("work", "젊을 때 공장에서 반장으로 일하며 사람들을 챙기던 때가 생각나는군.", "오랫동안 동료들을 책임지고 챙기셨던 자랑스러운 기억이네요.", "공장 반장으로 일하던 시절", "직장에서 동료를 이끌었던 시절을 자부심 있게 회상했습니다.", meaning=("pride", "삶에 대한 자부심"), intent="memory_recall"),
            "med": scenario("med", "아침 혈압약을 먹었는지 기억이 안 나. 또 먹으면 안 되겠지?", "네, 확인하기 전에는 추가로 드시지 말고 투약 기록을 같이 보겠습니다.", "아침 혈압약 확인", "혈압약 복용 여부를 반복해서 확인했습니다.", care=("daily_living", "medication_uncertain", "복약 여부 불확실"), action="아침 투약 기록과 약통을 대조해 주세요.", repeat=True, intent="medication"),
            "word": scenario("word", "그... 뭐지, 텔레비전 채널 바꾸는 그거 이름이 생각이 안 나.", "리모컨을 말씀하시는 것 같아요. 천천히 생각하셔도 괜찮아요.", "단어를 찾는 데 시간이 필요했어요", "익숙한 물건의 이름을 바로 떠올리는 데 어려움을 보였습니다.", care=("language", "word_finding_difficulty", "단어 찾기 어려움"), action="대답을 재촉하지 말고 충분히 기다려 주세요."),
            "task": scenario("task", "병원에 가려면 뭘 먼저 챙겨야 하는지 순서를 모르겠어.", "진료카드, 약 목록, 외투 순서로 하나씩 챙겨 볼게요.", "병원 준비 순서 도움", "병원 방문 준비의 순서를 정하는 데 어려움을 보였습니다.", care=("executive_judgment", "task_sequencing_difficulty", "행동 순서 어려움"), action="준비물을 짧은 체크리스트로 보여 주세요."),
            "time": scenario("time", "지금이 아침인가 저녁인가? 오늘이 무슨 요일이지?", "지금 시간과 오늘 날짜를 시계와 달력으로 함께 확인해 볼게요.", "시간대와 요일 확인", "피로한 시간대에 현재 시간과 요일을 혼동했습니다.", care=("orientation", "time_confusion", "시간 혼동"), action="큰 시계와 달력으로 현재 시간대를 함께 짚어 주세요.", repeat=True),
            "bleeding": scenario("bleeding", "양치하다 잇몸에서 피가 났어. 금방 멈추기는 했어.", "출혈이 다시 생기는지 살펴보고 담당자에게 기록을 남길게요.", "잇몸 출혈 관찰", "양치 중 잇몸 출혈이 있었다고 말했습니다.", care=("safety_physical", "bleeding_signal", "출혈 징후"), action="출혈 지속 시간과 멍·코피 동반 여부를 확인해 주세요."),
            "visit": scenario("visit", "성민이가 병원에 같이 가기로 했던가? 언제 오는지 기억이 안 나.", "성민 님과 약속한 시간을 일정에서 확인해 드릴게요.", "병원 동행 약속 확인", "아들의 방문 및 병원 동행 약속을 기억하는 데 어려움을 보였습니다.", care=("memory", "appointment_forgetting", "약속 잊음"), action="병원 동행 시간을 눈에 잘 띄는 곳에 적어 주세요.", repeat=True, intent="schedule_question"),
            "stroke": scenario("stroke", "갑자기 오른팔에 힘이 없고 말이 잘 안 나와. 얼굴도 이상한 것 같아.", "지금은 긴급 확인이 필요해요. 바로 담당자와 의료진에게 알릴게요.", "뇌졸중 의심 증상 긴급 확인", "갑작스러운 편측 위약과 말하기 어려움을 표현했습니다.", care=("safety_physical", "stroke_warning_signal", "뇌졸중 경고 표현"), action="FAST 증상을 확인하고 즉시 응급 대응 절차를 시작해 주세요.", risk=("stroke_sign", "critical", "갑자기 오른팔에 힘이 없고 말이 잘 안 나온다고 말함"), intent="risk"),
        },
    },
}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def daterange(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def weighted_key(rng, weights):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[key] for key in keys], k=1)[0]


def call_type(rng):
    roll = rng.random()
    if roll < 0.25:
        return "direct"
    if roll < 0.35:
        return "ai_to_direct"
    return "ai"


def medication_status(rng, rates, month):
    confirmed, unclear, duplicate = rates
    if month == 9:
        confirmed -= 0.04
        unclear += 0.03
    roll = rng.random()
    if roll < confirmed:
        return "USER_CONFIRMED"
    if roll < confirmed + unclear:
        return "UNCLEAR"
    if roll < confirmed + unclear + duplicate:
        return "DUPLICATE_SUSPECTED"
    return "REFUSED"


def clear_previous(conn):
    like = f"{PREFIX}%"
    conn.execute("DELETE FROM heart_artworks WHERE call_id LIKE ?", (like,))
    conn.execute(
        "DELETE FROM recall_reviews WHERE utterance_id IN "
        "(SELECT utterance_id FROM utterances WHERE call_id LIKE ?)", (like,)
    )
    conn.execute("DELETE FROM medication_logs WHERE call_id LIKE ?", (like,))
    conn.execute("DELETE FROM call_events WHERE call_id LIKE ?", (like,))
    conn.execute("DELETE FROM reports WHERE call_id LIKE ?", (like,))
    conn.execute("DELETE FROM utterances WHERE call_id LIKE ?", (like,))
    conn.execute("DELETE FROM call_invites WHERE ai_call_id LIKE ?", (like,))
    conn.execute("DELETE FROM calls WHERE call_id LIKE ?", (like,))


def insert_call(conn, elder_id, profile, day, index, scenario_row, rng):
    persona_id, counterpart, relation = rng.choice(profile["personas"])
    hour = rng.choice(profile["hours"])
    minute = (index * 17 + rng.randrange(17)) % 60
    second = (index * 11 + rng.randrange(11)) % 60
    started = datetime.combine(day, time(hour, minute, second), SEOUL)
    duration = rng.randint(28, 355)
    ended = started + timedelta(seconds=duration)
    call_id = f"{PREFIX}{elder_id[-3:]}_{day:%Y%m%d}_{index:03d}"
    kind = call_type(rng)

    conn.execute(
        "INSERT INTO calls (call_id,elder_id,persona_id,call_type,started_at,ended_at,"
        "duration_sec,end_reason,status,counterpart_name,counterpart_relation,report_title) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (call_id, elder_id, persona_id, kind, started.isoformat(), ended.isoformat(),
         duration, "completed", "ended", counterpart, relation, scenario_row["title"]),
    )

    care = scenario_row.get("care")
    risk = scenario_row.get("risk")
    care_data = None
    if care:
        domain, signal, label = care
        care_data = {
            "observations": [{
                "domain": domain, "signal": signal, "label": label,
                "evidence": scenario_row["text"], "basis": "user_statement",
            }],
            "context_support": [],
            "daily_action": None,
            "meaningful_moments": [],
        }
    elder_cursor = conn.execute(
        "INSERT INTO utterances (call_id,seq,speaker,transcript,intent,certainty,"
        "used_memory_ids,used_schedule_ids,unverified_recall,care_data,grounding,"
        "safety_flags,was_rewritten,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (call_id, 1, "elder", scenario_row["text"], scenario_row["intent"], "high",
         "[]", "[]", "[]", dumps(care_data) if care_data else None, "direct_statement",
         dumps([risk[0]]) if risk else "[]", 0, rng.randint(170, 980), started.isoformat()),
    )
    elder_utterance_id = elder_cursor.lastrowid
    conn.execute(
        "INSERT INTO utterances (call_id,seq,speaker,transcript,intent,certainty,"
        "used_memory_ids,used_schedule_ids,unverified_recall,care_data,grounding,"
        "safety_flags,was_rewritten,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (call_id, 2, "ai", scenario_row["reply"], "support", "high", "[]", "[]", "[]",
         None, "profile_and_direct_statement", "[]", 0, rng.randint(480, 2100),
         (started + timedelta(seconds=max(3, duration // 3))).isoformat()),
    )

    care_summary = {}
    if care:
        domain, signal, label = care
        care_summary[domain] = [{
            "signal": signal,
            "label": label,
            "utterance_id": elder_utterance_id,
            "basis": "user_statement",
            "evidence": scenario_row["text"],
            "at": started.isoformat(),
        }]
    repeats = []
    if scenario_row.get("repeat"):
        repeats = [{
            "question": scenario_row["text"],
            "count": 2 + (index % 2),
            "utterance_ids": [elder_utterance_id],
        }]
    moments = []
    if scenario_row.get("meaning"):
        category, label = scenario_row["meaning"]
        moments = [{
            "category": category,
            "label": label,
            "evidence": scenario_row["text"],
            "utterance_id": elder_utterance_id,
            "at": started.isoformat(),
        }]
    risk_summary = []
    if risk:
        risk_type, level, evidence = risk
        risk_summary = [{
            "type": risk_type,
            "level": level,
            "label": scenario_row["title"],
            "evidence": evidence,
        }]
    medication_summary = {
        "mentioned": 1 if scenario_row["key"] in {"med", "overdose"} else 0,
        "entries": [],
        "needs_check": scenario_row["key"] in {"med", "overdose"},
    }
    actions = [scenario_row["action"]] if scenario_row.get("action") else []
    conn.execute(
        "INSERT INTO reports (call_id,summary,repeated_questions,medication_summary,"
        "new_recalls,risk_summary,guardian_actions,created_at,care_summary,"
        "meaningful_moments,family_mentions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (call_id, scenario_row["summary"], dumps(repeats), dumps(medication_summary), "[]",
         dumps(risk_summary), dumps(actions), ended.isoformat(), dumps(care_summary),
         dumps(moments), dumps([{"name": counterpart, "count": 1}]) if moments else "[]"),
    )
    if risk:
        risk_type, level, evidence = risk
        conn.execute(
            "INSERT INTO call_events (call_id,utterance_id,event_type,payload,acknowledged,"
            "acknowledged_at,created_at) VALUES (?,?,?,?,?,?,?)",
            (call_id, elder_utterance_id, "risk",
             dumps({"type": risk_type, "level": level, "label": scenario_row["title"],
                    "evidence": evidence, "action": scenario_row["action"]}),
             1 if index % 3 else 0,
             ended.isoformat() if index % 3 else None, started.isoformat()),
        )
    return call_id, elder_utterance_id, started, scenario_row["key"]


def seed_day_medications(conn, elder_id, profile, day, day_calls, rng):
    medications = conn.execute(
        "SELECT schedule_id, medication_name FROM medications "
        "WHERE elder_id=? AND active=1 ORDER BY scheduled_time,schedule_id", (elder_id,),
    ).fetchall()
    if not medications or not day_calls:
        return 0
    preferred = next((row for row in day_calls if row[3] == "med"), day_calls[0])
    call_id, utterance_id, started, _ = preferred
    added = 0
    for schedule_id, medication_name in medications:
        manual = conn.execute(
            "SELECT 1 FROM medication_logs WHERE schedule_id=? AND taken_date=? "
            "AND (call_id IS NULL OR call_id NOT LIKE ?) LIMIT 1",
            (schedule_id, day.isoformat(), f"{PREFIX}%"),
        ).fetchone()
        if manual:
            continue
        status = medication_status(rng, profile["medication_rates"], day.month)
        evidence = {
            "USER_CONFIRMED": f"{medication_name}을 복용했다고 직접 확인함",
            "UNCLEAR": f"{medication_name} 복용 여부를 기억하지 못함",
            "DUPLICATE_SUSPECTED": f"{medication_name}을 두 번 복용했을 가능성을 말함",
            "REFUSED": f"{medication_name}을 복용하고 싶지 않다고 말함",
        }[status]
        cursor = conn.execute(
            "INSERT INTO medication_logs (elder_id,schedule_id,call_id,utterance_id,taken_date,"
            "status,evidence_text,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (elder_id, schedule_id, call_id, utterance_id, day.isoformat(), status,
             evidence, started.isoformat()),
        )
        added += 1
        if status != "USER_CONFIRMED" or (cursor.lastrowid % 10 == 0):
            conn.execute(
                "INSERT INTO call_events (call_id,utterance_id,event_type,payload,acknowledged,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (call_id, utterance_id, "medication",
                 dumps({"schedule_id": schedule_id, "status": status,
                        "medication_name": medication_name}),
                 1 if status == "USER_CONFIRMED" else 0, started.isoformat()),
            )
    return added


def seed(conn):
    clear_previous(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_seed_versions ("
        "seed_name TEXT PRIMARY KEY, version TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calls_elder_started "
        "ON calls(elder_id, started_at)"
    )
    # 가족 호칭은 담당자 화면의 진단 정보가 아니다. 기존에 진단이 비어 있는
    # 데모 환자만 등록된 진단명으로 보완하고, 사용자가 입력한 값은 보존한다.
    for elder_id, profile in PATIENTS.items():
        conn.execute(
            "UPDATE elder_profiles SET diagnosis_label=? WHERE elder_id=? "
            "AND (COALESCE(TRIM(diagnosis_label),'')='' OR "
            "TRIM(diagnosis_label) IN ('할아버지','할머니','아버지','어머니','어르신'))",
            (profile["diagnosis"], elder_id),
        )
    totals = {"calls": 0, "utterances": 0, "reports": 0, "events": 0, "medication_logs": 0}
    for elder_index, (elder_id, profile) in enumerate(PATIENTS.items(), start=1):
        for day in daterange(START, END):
            rng = random.Random(f"dasoni-demo-789:{elder_id}:{day.isoformat()}")
            count = 96 + ((day.toordinal() + elder_index * 3) % 9)
            day_calls = []
            for index in range(count):
                key = weighted_key(rng, profile["weights"][day.month])
                # Clinically important events are sparse and deterministic,
                # while ordinary observations remain frequent enough for charts.
                if index == count - 1:
                    if elder_id == "elder_001" and day.toordinal() % 17 == 0:
                        key = "overdose"
                    elif elder_id == "elder_001" and day.toordinal() % 11 == 0:
                        key = "lost"
                    elif elder_id == "elder_002" and day.toordinal() % 7 == 0:
                        key = "fall"
                    elif elder_id == "elder_003" and day.toordinal() % 13 == 0:
                        key = "stroke"
                row = insert_call(conn, elder_id, profile, day, index, profile["scenarios"][key], rng)
                day_calls.append(row)
            totals["calls"] += count
            totals["utterances"] += count * 2
            totals["reports"] += count
            totals["medication_logs"] += seed_day_medications(
                conn, elder_id, profile, day, day_calls, rng
            )
    totals["events"] = conn.execute(
        "SELECT COUNT(*) FROM call_events WHERE call_id LIKE ?", (f"{PREFIX}%",)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO demo_seed_versions (seed_name,version,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(seed_name) DO UPDATE SET version=excluded.version, "
        "updated_at=excluded.updated_at",
        ("jul_sep_2026", SEED_VERSION, datetime.now(SEOUL).isoformat()),
    )
    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.exists():
        raise SystemExit(f"Database not found: {database}")

    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            totals = seed(conn)
    finally:
        conn.close()
    print(dumps({
        "database": str(database),
        "range": [START.isoformat(), END.isoformat()],
        "patients": list(PATIENTS),
        **totals,
    }))


if __name__ == "__main__":
    main()
