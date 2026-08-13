r"""최근 30일 동안 매일 30통 이상인 현실적인 고빈도 케어 데모를 적재한다.

실제 통화는 보존하고 ``demo_volume_`` 접두사만 교체한다. 반복 질문은 한 통화
안에서 동일 발화를 2~4회 실제 utterance로 저장한다. Gemini를 호출하지 않으며
care -> safety -> report 집계 경로를 그대로 사용한다. 빈번한 통화의 대부분은
안부·시간·일정 질문이며, 낙상·길 잃음·중복 복용은 한 달에 몇 번만 발생한다.

    .\.venv\Scripts\python.exe tools\seed_high_volume_demo.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import care  # noqa: E402
import db  # noqa: E402
import report  # noqa: E402
import safety  # noqa: E402
from seed_care_demo import DEMO_PERSONAS, _ensure_demo_family  # noqa: E402


PREFIX = "demo_volume_"
DAILY_CALLS = [32 + ((index * 7 + (index // 3) * 3) % 10) for index in range(30)]

TEMPLATES = [
    {
        "title": "현재 시각 반복 확인", "repeat": 4,
        "user": "{family}아, 지금 몇 시냐? 오늘이 무슨 요일이지?",
        "reply": "현재 시각과 요일을 천천히 다시 알려드릴게요. 달력도 같이 확인해요.",
        "summary": "현재 시각과 요일을 같은 표현으로 반복해서 확인하셨습니다.",
        "actions": ["잘 보이는 곳에 오늘 날짜와 시간을 표시해 주세요."],
    },
    {
        "title": "방문 일정 반복 질문", "repeat": 3,
        "user": "{family}아, 오늘 몇 시에 오냐? 언제 오는 거냐?",
        "reply": "방문 일정은 등록된 내용부터 확인해 볼게요. 다시 물으셔도 괜찮아요.",
        "summary": "가족의 방문 시각을 세 차례 같은 말로 물으셨습니다.",
        "actions": ["방문 시각을 큰 글씨로 적어 눈에 보이게 두세요."],
    },
    {
        "title": "현재 장소 반복 확인", "repeat": 3,
        "user": "{family}아, 여기가 어디냐? 내 집이 아닌 것 같다.",
        "reply": "낯설게 느껴져 걱정되셨구나. 주변에 보이는 물건 하나부터 말해 주세요.",
        "summary": "현재 장소를 낯설게 느끼며 같은 질문을 반복하셨습니다.",
        "actions": ["현재 위치와 현관 안전 상태를 직접 확인해 주세요."],
    },
    {
        "title": "식사 여부 반복 확인", "repeat": 2,
        "user": "내가 밥을 먹었는지 모르겠다. 점심을 먹었던가?",
        "reply": "식사 여부는 제가 단정하지 않을게요. 식탁과 기록을 하나씩 확인해 봐요.",
        "summary": "식사 여부를 기억하지 못해 두 차례 확인하셨습니다.",
        "actions": ["식사 기록과 남은 음식을 확인해 주세요."],
    },
    {
        "title": "복약 여부 반복 확인", "repeat": 3,
        "user": "내가 약을 먹었나? 약을 먹었는지 기억이 안 난다.",
        "reply": "약은 더 드시지 말고 복약 기록을 먼저 확인하도록 가족에게 남길게요.",
        "summary": "복약 여부를 기억하지 못해 같은 질문을 반복하셨습니다.",
        "actions": ["중복 복용을 막기 위해 약통과 복약 기록을 확인해 주세요."],
    },
    {
        "title": "분실물 반복 찾기", "repeat": 3,
        "user": "내 지갑이 어디 갔냐? 지갑을 못 찾겠다.",
        "reply": "지갑이 안 보여 걱정되셨구나. 자주 두는 곳부터 하나씩 살펴봐요.",
        "summary": "지갑 위치를 같은 표현으로 세 차례 물으셨습니다.",
        "actions": ["지갑의 고정 보관 위치를 함께 정해 주세요."],
    },
    {
        "title": "외로움과 가족 그리움", "repeat": 1,
        "user": "{family}아, 혼자 있으니까 외롭고 네가 보고 싶다.",
        "reply": "외롭고 보고 싶으셨구나. 그 말씀을 가족에게 그대로 전해드릴게요.",
        "summary": "혼자 있는 외로움과 가족을 보고 싶은 마음을 표현하셨습니다.",
        "actions": ["비슷한 시간대에 짧은 안부 연락을 해보세요."],
    },
    {
        "title": "가족에게 전한 고마움", "repeat": 1,
        "user": "우리 {family}이가 늘 챙겨줘서 참 고맙다.",
        "reply": "고맙다는 말씀을 가족이 들을 수 있도록 그대로 남겨둘게요.",
        "summary": "가족에게 느끼는 고마움을 직접 말씀하셨습니다.",
        "actions": ["직접 하신 고마운 말씀을 가족과 나눠보세요."],
    },
    {
        "title": "아들에게 전한 미안함", "repeat": 1,
        "user": "우리 {family}이가 고생이 많은데 내가 해준 게 없어 미안하다.",
        "reply": "미안하다는 마음이 드셨구나. 그 말씀을 바꾸지 않고 남길게요.",
        "summary": "가족에게 미안한 마음을 직접 표현하셨습니다.",
        "actions": ["해당 말씀을 가족과 조심스럽게 나눠보세요."],
    },
    {
        "title": "고향 냇가 회상", "repeat": 1,
        "user": "옛날 고향 집 앞 냇가가 생각난다. 그때가 참 좋았지.",
        "reply": "고향 냇가가 떠오르셨구나. 기억나는 풍경을 하나 더 들려주세요.",
        "summary": "고향 냇가와 좋았던 시절을 떠올리셨습니다.",
        "actions": ["확인된 가족 사진이 있다면 함께 보며 이야기를 이어가세요."],
    },
    {
        "title": "과거 교사 역할 혼동", "repeat": 2,
        "user": "학교 수업에 늦겠다. 빨리 가야 하는데 내 가방이 어디 있냐?",
        "reply": "수업 걱정으로 마음이 급하셨구나. 오늘 일정인지 확인할 때까지 앉아 계세요.",
        "summary": "과거 교사 역할을 현재 일정으로 여기며 외출을 서두르셨습니다.",
        "actions": ["아침 시간대에 역할 혼동이 반복되는지 살펴봐 주세요."],
    },
    {
        "title": "재산 걱정과 불신", "repeat": 2,
        "user": "누가 내 통장을 몰래 가져갔지? 내 돈을 빼돌리려는 것 같아 걱정된다.",
        "reply": "돈이 없어질까 봐 걱정되셨구나. 통장 상태는 가족이 직접 확인하도록 남길게요.",
        "summary": "통장과 재산에 대한 걱정과 불신을 표현하셨습니다.",
        "actions": ["통장 보관 위치와 최근 거래 내역을 함께 확인해 주세요."],
    },
    {
        "title": "물 마시기 도움", "repeat": 1,
        "user": "목이 마른데 물이 어디 있는지 모르겠다.",
        "reply": "목이 마르셨구나. 눈앞에 보이는 물컵이 있는지 천천히 살펴봐요.",
        "summary": "갈증과 물 위치 확인이 필요한 상황이었습니다.",
        "actions": ["손이 닿기 쉬운 곳에 물컵이 있는지 확인해 주세요."],
    },
    {
        "title": "야간 두려움", "repeat": 2,
        "user": "혼자 있으니까 너무 무섭다. 누가 집에 있는 것 같아.",
        "reply": "무섭게 느껴지셨구나. 문을 열러 가지 말고 가족이 확인하도록 남길게요.",
        "summary": "혼자 있는 두려움과 집 안 안전에 대한 걱정을 표현하셨습니다.",
        "actions": ["문 잠금과 실내 상황을 직접 확인해 주세요."],
    },
    {
        "title": "낙상과 통증", "repeat": 1,
        "user": "화장실에서 넘어져서 허리가 아프고 일어나기가 힘들다.",
        "reply": "넘어지셨군요. 무리해서 움직이지 말고 가족이 바로 확인하도록 알릴게요.",
        "summary": "낙상 후 허리 통증과 움직임 어려움을 말씀하셨습니다.",
        "actions": ["낙상 위치와 통증, 의식 상태를 즉시 확인해 주세요."],
    },
    {
        "title": "귀가·길 찾기 위험", "repeat": 2,
        "user": "집에 가야 하는데 길을 못 찾겠다. 여기가 너무 낯설다.",
        "reply": "길을 못 찾아 불안하셨구나. 혼자 이동하지 말고 보이는 표지 하나를 말해 주세요.",
        "summary": "현재 장소를 낯설게 느끼며 귀가 길을 찾지 못한다고 말씀하셨습니다.",
        "actions": ["현재 위치를 즉시 확인하고 혼자 이동하지 않도록 도와주세요."],
    },
    {
        "title": "가족 이름과 애정", "repeat": 1,
        "user": "다 잊어버려도 우리 {family}이 이름은 안 잊어버린다.",
        "reply": "그 이름은 기억하고 계시는구나. 그 말씀을 가족에게 그대로 남길게요.",
        "summary": "혼란 속에서도 가족 이름은 잊지 않는다고 말씀하셨습니다.",
        "actions": ["이름을 기억하신 말씀을 해당 가족과 나눠보세요."],
    },
    {
        "title": "차분한 안부 통화", "repeat": 1,
        "user": "오늘은 그냥 네 목소리가 듣고 싶어서 전화했다.",
        "reply": "목소리가 듣고 싶으셨구나. 오늘 하루 이야기를 천천히 들려주세요.",
        "summary": "특별한 위험 없이 가족 목소리를 듣고 싶어 통화하셨습니다.",
        "actions": [],
    },
    {
        "title": "중복 복용 여부 확인", "repeat": 1,
        "user": "약을 아까 먹고 또 먹은 것 같다. 약을 두 번 먹었나 보다.",
        "reply": "약을 더 드시지 말고 그대로 계세요. 가족이 복약 기록과 상태를 바로 확인하도록 알릴게요.",
        "summary": "약을 두 번 복용했을 가능성을 직접 말씀하셔서 즉시 확인이 필요했습니다.",
        "actions": ["복약 기록과 남은 약의 수량을 즉시 확인해 주세요."],
    },
    {
        "title": "복약 완료 안부", "repeat": 1,
        "user": "오늘 아침 혈압약은 먹었고 물도 한 잔 마셨다.",
        "reply": "아침 약과 물을 챙기셨군요. 말씀해 주신 내용을 오늘 기록에 남길게요.",
        "summary": "아침 약과 물을 챙겼다고 직접 말씀하셨습니다.",
        "actions": [],
    },
    {
        "title": "현관 침입 위험", "repeat": 1,
        "user": "모르는 사람이 현관문을 열고 집에 들어오려고 한다.",
        "reply": "문 가까이 가지 말고 안전한 곳에 계세요. 가족이 즉시 확인하도록 알릴게요.",
        "summary": "낯선 사람이 현관문을 열려고 한다고 직접 말씀하셨습니다.",
        "actions": ["현관 상황과 어르신의 안전을 즉시 확인해 주세요."],
    },
    {
        "title": "주방 화재 위험", "repeat": 1,
        "user": "부엌에 불이 났고 연기가 보여. 어떻게 해야 하냐?",
        "reply": "불 가까이 가지 말고 즉시 안전한 곳으로 이동하세요. 가족과 긴급 도움에 알릴게요.",
        "summary": "주방에서 불과 연기를 보았다고 직접 말씀하셨습니다.",
        "actions": ["화재 여부를 즉시 확인하고 필요하면 119에 신고해 주세요."],
    },
    {
        "title": "호흡 곤란", "repeat": 1,
        "user": "갑자기 숨이 차고 제대로 못 쉬겠다.",
        "reply": "움직이지 말고 편한 자세로 계세요. 가족과 긴급 도움에 바로 알릴게요.",
        "summary": "갑작스러운 호흡 곤란을 직접 말씀하셨습니다.",
        "actions": ["호흡 상태를 즉시 확인하고 필요하면 119에 신고해 주세요."],
    },
    {
        "title": "가슴 통증", "repeat": 1,
        "user": "가슴이 조이고 아프다. 아까부터 통증이 계속된다.",
        "reply": "움직이지 말고 편하게 계세요. 가족과 긴급 도움에 바로 알릴게요.",
        "summary": "지속되는 가슴 통증을 직접 말씀하셨습니다.",
        "actions": ["의식과 통증 상태를 즉시 확인하고 필요하면 119에 신고해 주세요."],
    },
    {
        "title": "가스 누출 의심", "repeat": 1,
        "user": "주방에서 가스 냄새가 계속 난다.",
        "reply": "불이나 전기 스위치를 만지지 말고 주방에서 떨어져 계세요. 가족에게 즉시 알릴게요.",
        "summary": "주방에서 지속적인 가스 냄새가 난다고 직접 말씀하셨습니다.",
        "actions": ["가스 밸브와 실내 상황을 즉시 확인해 주세요."],
    },
    {
        "title": "단어 찾기 어려움", "repeat": 1,
        "user": "그... 뭐더라, 말이 생각이 안 난다. 물 마실 때 쓰는 그거 말이다.",
        "reply": "말이 바로 떠오르지 않으셨군요. 서두르지 말고 생김새부터 천천히 말씀해 주세요.",
        "summary": "익숙한 물건의 단어를 바로 떠올리기 어렵다고 말씀하셨습니다.",
        "actions": ["단어 찾기 어려움이 평소보다 잦거나 갑자기 심해졌는지 확인해 주세요."],
    },
    {
        "title": "행동 순서 어려움", "repeat": 1,
        "user": "옷을 입고 뭐부터 해야 하는지 모르겠다. 어떻게 해야 하냐?",
        "reply": "한 번에 하나씩 해볼게요. 먼저 편하게 앉아서 겉옷을 찾아봐요.",
        "summary": "외출 준비의 순서를 정하기 어렵다고 말씀하셨습니다.",
        "actions": ["외출 준비를 한 단계씩 안내하고 어느 단계에서 막혔는지 기록해 주세요."],
    },
    {
        "title": "수면 교란", "repeat": 1,
        "user": "밤새 자꾸 깨서 못 잤다. 오늘은 기운이 없다.",
        "reply": "밤에 자주 깨서 피곤하시군요. 오늘은 무리하지 않도록 담당자에게 남길게요.",
        "summary": "밤새 자주 깨고 기운이 없다고 말씀하셨습니다.",
        "actions": ["야간 각성 횟수와 낮 시간 졸림·활동 변화를 확인해 주세요."],
    },
    {
        "title": "어지럼 표현", "repeat": 1,
        "user": "자리에서 일어나니 어지럽고 휘청거린다.",
        "reply": "어지러우시군요. 혼자 걷지 말고 앉아서 담당자가 확인할 때까지 기다려 주세요.",
        "summary": "일어선 뒤 어지럼과 휘청거림을 말씀하셨습니다.",
        "actions": ["기립 전후 상태와 보행 안정성을 확인하고 반복 여부를 기록해 주세요."],
    },
    {
        "title": "식욕 저하", "repeat": 1,
        "user": "요즘 입맛이 없어서 밥을 별로 못 먹겠다.",
        "reply": "입맛이 없어 식사가 힘드셨군요. 오늘 드신 양을 담당자가 확인하도록 남길게요.",
        "summary": "최근 입맛이 없고 식사량이 줄었다고 말씀하셨습니다.",
        "actions": ["식사 섭취량과 체중 변화를 기록하고 지속되면 의료진에게 전달해 주세요."],
    },
    {
        "title": "돌봄 방식에 대한 분노", "repeat": 1,
        "user": "거짓말 마! 왜 내 물건을 마음대로 치웠어. 정말 화가 난다.",
        "reply": "물건이 달라져 화가 나셨구나. 자극을 줄이고 보관 위치를 확인하도록 남길게요.",
        "summary": "물건 보관 방식에 대해 분노와 언어적 공격을 표현하셨습니다.",
        "actions": ["맞서 설명하지 말고 자극을 줄인 뒤 보관 위치를 확인해 주세요."],
    },
    {
        "title": "의욕 저하와 외로움", "repeat": 1,
        "user": "오늘은 아무것도 하기 싫고 기운이 없다. 혼자 있으니 외롭다.",
        "reply": "기운이 없고 외로우셨구나. 짧게 곁에서 이야기를 나눌 수 있게 남길게요.",
        "summary": "의욕 저하와 외로움을 함께 표현하셨습니다.",
        "actions": ["짧게 말을 걸고 식사·수면·활동 변화가 함께 있는지 확인해 주세요."],
    },
    {
        "title": "생활 도움 요청", "repeat": 1,
        "user": "옷을 어떻게 입어야 할지 모르겠다. 혼자 못 하겠으니 도와줘.",
        "reply": "한 번에 하나씩 도와드릴게요. 먼저 앉아서 겉옷부터 찾아봐요.",
        "summary": "옷 입기 순서에 대한 직접적인 도움을 요청하셨습니다.",
        "actions": ["옷 입기를 한 단계씩 제시하고 어느 단계에서 막히는지 기록해 주세요."],
    },
]


# 천 통이 넘는 데모 통화에 응급상황을 순환 배치하면 위험 건수가 수십 건으로
# 부풀려진다. 아래 네 건만 실제 안전 이벤트로 남겨 통화 횟수와 사건 횟수를
# 구분한다. 각 유형은 한 달에 한 번만 등장한다. key는
# (며칠 전, 그날 통화 순번), value는 TEMPLATES 인덱스다.
RARE_RISK_CALLS = {
    (25, 7): 20,   # 현관 침입 1건
    (22, 11): 21,  # 화재 1건
    (12, 14): 14,  # 낙상 1건
    (10, 8): 22,   # 호흡 곤란 1건
    (8, 17): 18,   # 중복 복용 의심 1건
    (6, 12): 23,   # 가슴 통증 1건
    (4, 23): 15,   # 길 잃음 1건
    (2, 19): 24,   # 가스 누출 의심 1건
}

MORNING_ROTATION = [0, 3, 19, 17, 0, 4, 12, 5, 17, 25, 26, 19, 3, 0, 31]
DAY_ROTATION = [17, 1, 0, 5, 17, 7, 10, 3, 17, 11, 12, 8, 9, 16, 25, 26, 28, 29, 31]
EVENING_ROTATION = [17, 6, 1, 17, 0, 6, 17, 16, 1, 17, 9, 6, 27, 30, 29]


def _delete_calls(conn, elder_id: str) -> None:
    call_ids = [row[0] for row in conn.execute(
        "SELECT call_id FROM calls WHERE call_id LIKE ? OR call_id LIKE ? OR call_id LIKE ?",
        (f"{PREFIX}%", "demo_history_%", "demo_care_%"),
    ).fetchall()]
    for call_id in call_ids:
        conn.execute(
            "DELETE FROM recall_reviews WHERE utterance_id IN "
            "(SELECT utterance_id FROM utterances WHERE call_id = ?)", (call_id,),
        )
        for table in ("heart_artworks", "reports", "call_events", "medication_logs", "utterances"):
            conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM calls WHERE call_id = ?", (call_id,))
    conn.execute(
        "DELETE FROM medication_logs WHERE elder_id = ? AND evidence_text LIKE '고빈도 데모:%'",
        (elder_id,),
    )
    conn.execute(
        "DELETE FROM medication_reviews WHERE elder_id = ? AND note = '고빈도 데모 정기 경과 관찰'",
        (elder_id,),
    )


def _ensure_demo_medications(conn, elder_id: str) -> list[dict]:
    rows = [db._row(row) for row in conn.execute(
        "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
        "ORDER BY scheduled_time, schedule_id",
        (elder_id,),
    ).fetchall()]
    if rows:
        return rows
    demo = [
        {
            "schedule_id": "demo_med_blood_pressure", "elder_id": elder_id,
            "medication_name": "아침 혈압약", "dosage_text": "1정",
            "scheduled_time": "08:00", "meal_relation": "after",
            "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
            "indication": "고혈압 관리",
            "monitoring_points": ["어지럼 표현", "낙상 또는 휘청거림"],
            "review_interval_days": 14,
            "escalation_criteria": "낙상·흉통·호흡 곤란 발생 시 담당자가 상태를 확인하고 처방 의료진에게 보고",
            "active": 1,
        },
        {
            "schedule_id": "demo_med_memory", "elder_id": elder_id,
            "medication_name": "저녁 기억건강약", "dosage_text": "1정",
            "scheduled_time": "20:00", "meal_relation": "after",
            "days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
            "indication": "인지기능 증상 관리",
            "monitoring_points": ["어지럼 표현", "식욕 변화", "수면 교란"],
            "review_interval_days": 14,
            "escalation_criteria": "새로운 실신·낙상 또는 일상 기능의 뚜렷한 변화 시 처방 의료진에게 보고",
            "active": 1,
        },
    ]
    for row in demo:
        db.insert(conn, "medications", row)
    links = [
        ("demo_med_blood_pressure", "dizziness", "monitoring", "어지럼 표현"),
        ("demo_med_blood_pressure", "fall_reported", "escalation", "낙상 발생"),
        ("demo_med_blood_pressure", "chest_pain", "escalation", "흉통 표현"),
        ("demo_med_memory", "dizziness", "monitoring", "어지럼 표현"),
        ("demo_med_memory", "appetite_change", "monitoring", "식욕 변화"),
        ("demo_med_memory", "sleep_disturbance", "monitoring", "수면 교란"),
    ]
    for schedule_id, signal, level, criterion in links:
        db.insert(conn, "medication_signal_links", {
            "schedule_id": schedule_id, "signal": signal,
            "link_level": level, "criterion_text": criterion,
        })
    return demo


def _call_time(now: datetime, days_ago: int, index: int, count: int) -> datetime:
    day = (now - timedelta(days=days_ago)).date()
    if days_ago == 0:
        start_minute = 390
        available = max(start_minute + 60, now.hour * 60 + now.minute - 20)
        minute = start_minute + int(
            index * max(1, available - start_minute) / max(1, count - 1)
        )
    else:
        selector = (index * 37 + days_ago * 11) % 100
        if selector < 28:       # 28% · 아침 07:00~10:00
            start, width = 420, 180
        elif selector < 50:     # 22% · 낮 12:00~16:30
            start, width = 720, 270
        elif selector < 92:     # 42% · 저녁 18:00~20:00
            start, width = 1080, 120
        else:                   # 8% · 늦은 저녁 20:00~21:30
            start, width = 1200, 90
        minute = start + ((index * 29 + days_ago * 17) % width)
    hour, minute = divmod(minute, 60)
    return datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(
        hour=min(hour, 23), minute=minute,
    )


def _template_index(days_ago: int, index: int, started: datetime) -> int:
    rare = RARE_RISK_CALLS.get((days_ago, index))
    if rare is not None:
        return rare

    # 최근 7일에는 저녁 외로움 표현과 아침 복약 혼동이 조금 늘도록 해
    # 이전 주와 비교했을 때 생활 리듬의 변화가 실제 집계로 드러나게 한다.
    if days_ago <= 6 and 18 <= started.hour < 20 and (index + days_ago) % 4 == 0:
        return 6
    if days_ago <= 6 and 7 <= started.hour < 10 and (index + days_ago) % 6 == 0:
        return 4

    if started.hour < 11:
        rotation = MORNING_ROTATION
    elif started.hour < 18:
        rotation = DAY_ROTATION
    else:
        rotation = EVENING_ROTATION
    return rotation[(index * 5 + days_ago * 3) % len(rotation)]


REPEAT_PROBABILITY = {
    0: 58,   # 시간 확인은 같은 통화 안에서 비교적 자주 되묻는다.
    1: 46,   # 방문 일정
    2: 34,   # 현재 장소
    3: 31,   # 식사 여부
    4: 43,   # 복약 여부
    5: 27,   # 물건 위치
    10: 18,  # 과거 역할
    11: 24,  # 재산 걱정
    13: 20,  # 야간 두려움
}


def _repeat_count(template_index: int, days_ago: int, index: int) -> int:
    """Keep most calls single-turn while preserving realistic repeated speech."""
    maximum = int(TEMPLATES[template_index]["repeat"])
    probability = REPEAT_PROBABILITY.get(template_index, 0)
    selector = (days_ago * 41 + index * 23 + template_index * 17) % 100
    if maximum <= 1 or selector >= probability:
        return 1
    if maximum >= 4 and selector < max(8, probability // 4):
        return 4
    if maximum >= 3 and selector < max(14, probability // 2):
        return 3
    return 2


def seed(elder_id: str = "elder_001") -> dict:
    now = datetime.now().astimezone()
    call_ids = []
    with db.connect() as conn:
        db.init_schema(conn)
        _delete_calls(conn, elder_id)
        _ensure_demo_family(conn, elder_id)
        medications = _ensure_demo_medications(conn, elder_id)
        conn.commit()
        contexts = {
            name: db.load_context(elder_id, persona["persona_id"])
            for name, persona in DEMO_PERSONAS.items()
        }

        for day_index, call_count in enumerate(DAILY_CALLS):
            days_ago = len(DAILY_CALLS) - 1 - day_index
            for index in range(call_count):
                name = "미영" if (index + day_index) % 2 == 0 else "정훈"
                persona_id = DEMO_PERSONAS[name]["persona_id"]
                started = _call_time(now, days_ago, index, call_count)
                template_index = (
                    9 if days_ago == 0 and index == call_count - 1
                    else _template_index(days_ago, index, started)
                )
                template = TEMPLATES[template_index]
                call_id = f"{PREFIX}d{days_ago}_{index:02d}"
                call_ids.append(call_id)
                ctx = contexts[name]
                user_text = template["user"].format(family=name)
                ai_reply = template["reply"].format(family=name)
                repeat_count = _repeat_count(template_index, days_ago, index)
                duration = max(
                    78 + ((index * 37 + day_index * 19) % 260),
                    repeat_count * 34 + 30,
                )
                # 가족 통화 목록에서 실제 통화와 AI 대리 통화가 함께 보이도록
                # 한 달 중 일부만 직접 통화/이어받기 기록으로 둔다. 대부분은
                # 여전히 AI가 대신 받은 통화이며, 실제 기록은 이 시드가 건드리지 않는다.
                type_bucket = index + day_index * 3
                call_type = (
                    "direct" if type_bucket % 17 == 0
                    else "ai_to_direct" if type_bucket % 29 == 7
                    else "ai"
                )

                db.insert(conn, "calls", {
                    "call_id": call_id, "elder_id": elder_id, "persona_id": persona_id,
                    "counterpart_name": name,
                    "counterpart_relation": DEMO_PERSONAS[name]["relationship_type"],
                    "report_title": template["title"], "call_type": call_type,
                    "started_at": started.isoformat(timespec="seconds"),
                    "ended_at": (started + timedelta(seconds=duration)).isoformat(timespec="seconds"),
                    "duration_sec": duration, "end_reason": "demo_seeded", "status": "ended",
                })

                seq = 1
                for turn in range(repeat_count):
                    elder_uid = db.insert(conn, "utterances", {
                        "call_id": call_id, "seq": seq, "speaker": "elder",
                        "transcript": user_text,
                        "created_at": (started + timedelta(seconds=10 + turn * 34)).isoformat(timespec="seconds"),
                    })
                    result = safety.apply({
                        "reply": ai_reply, "used_memory_ids": [], "used_schedule_ids": [],
                        "certainty": "none", "risk": None, "care": {},
                    }, ctx, user_text)
                    care_data = care.normalize(
                        result.get("care"), user_text=user_text, ctx=ctx,
                        due_medications=[], response_rewritten=bool(result.get("_rewritten")),
                    )
                    care_data["source_utterance_id"] = elder_uid
                    ai_uid = db.insert(conn, "utterances", {
                        "call_id": call_id, "seq": seq + 1, "speaker": "ai",
                        "transcript": result["reply"],
                        "intent": "risk" if result.get("risk") else "care",
                        "certainty": result.get("certainty"),
                        "used_memory_ids": result.get("used_memory_ids") or [],
                        "used_schedule_ids": result.get("used_schedule_ids") or [],
                        "unverified_recall": result.get("unverified_recall"),
                        "care_data": care_data,
                        "grounding": "고빈도 데모의 실제 반복 발화와 서버 검증 규칙",
                        "safety_flags": result.get("_safety_flags") or [],
                        "was_rewritten": int(bool(result.get("_rewritten"))), "latency_ms": 0,
                        "created_at": (started + timedelta(seconds=24 + turn * 34)).isoformat(timespec="seconds"),
                    })
                    if result.get("risk") and turn == 0:
                        db.insert(conn, "call_events", {
                            "call_id": call_id, "utterance_id": elder_uid,
                            "ai_utterance_id": ai_uid, "event_type": "risk",
                            "payload": result["risk"], "acknowledged": 0,
                            "created_at": (started + timedelta(seconds=12)).isoformat(timespec="seconds"),
                        })
                    seq += 2

                if template_index in {4, 18, 19}:
                    medication = medications[
                        0 if started.hour < 14 else min(1, len(medications) - 1)
                    ]
                    status = {
                        4: "UNCLEAR",
                        18: "DUPLICATE_SUSPECTED",
                        19: "USER_CONFIRMED",
                    }[template_index]
                    db.insert(conn, "medication_logs", {
                        "elder_id": elder_id,
                        "schedule_id": medication["schedule_id"],
                        "call_id": call_id,
                        "utterance_id": None,
                        "taken_date": started.date().isoformat(),
                        "status": status,
                        "evidence_text": user_text,
                        "created_at": (started + timedelta(seconds=16)).isoformat(timespec="seconds"),
                    })

                db.insert(conn, "reports", {
                    "call_id": call_id, "summary": template["summary"],
                    "repeated_questions": [], "medication_summary": {}, "new_recalls": [],
                    "risk_summary": [], "care_summary": {}, "meaningful_moments": [],
                    "family_mentions": [], "guardian_actions": template["actions"],
                })

            # 통화에서 복약 이야기가 없었던 날도 담당자의 투약 기록은 별도로 남긴다.
            # 대부분은 확인이며, 불확실·거부는 한 달에 몇 차례만 배치한다.
            taken_date = (now - timedelta(days=days_ago)).date().isoformat()
            for med_index, medication in enumerate(medications):
                already_logged = conn.execute(
                    "SELECT 1 FROM medication_logs WHERE elder_id = ? AND schedule_id = ? "
                    "AND taken_date = ? LIMIT 1",
                    (elder_id, medication["schedule_id"], taken_date),
                ).fetchone()
                if already_logged:
                    continue
                selector = (days_ago * 13 + med_index * 17) % 41
                status = (
                    "REFUSED" if selector == 7 else
                    "UNCLEAR" if selector in {11, 29} else
                    "USER_CONFIRMED"
                )
                hour, minute = map(int, str(medication["scheduled_time"]).split(":"))
                db.insert(conn, "medication_logs", {
                    "elder_id": elder_id,
                    "schedule_id": medication["schedule_id"],
                    "call_id": None,
                    "utterance_id": None,
                    "taken_date": taken_date,
                    "status": status,
                    "evidence_text": f"고빈도 데모: 담당자 투약 기록 {status}",
                    "created_at": (now - timedelta(days=days_ago)).replace(
                        hour=hour, minute=minute, second=0, microsecond=0,
                    ).isoformat(timespec="seconds"),
                })

            if days_ago in {21, 7}:
                for med_index, medication in enumerate(medications):
                    db.insert(conn, "medication_reviews", {
                        "elder_id": elder_id,
                        "schedule_id": medication["schedule_id"],
                        "review_date": taken_date,
                        "severity": (days_ago + med_index) % 3,
                        "observed_flags": [],
                        "note": "고빈도 데모 정기 경과 관찰",
                    })
        conn.commit()

    built = [report.build(call_id) for call_id in call_ids]
    daily = {
        str(days): count
        for days, count in zip(range(len(DAILY_CALLS) - 1, -1, -1), DAILY_CALLS)
    }
    risk_types = {}
    for row in built:
        for risk in row["risk_summary"]:
            risk_type = risk.get("type") or "unknown"
            risk_types[risk_type] = risk_types.get(risk_type, 0) + 1
    return {
        "calls": len(built), "daily_calls_by_days_ago": daily,
        "repeat_groups": sum(len(row["repeated_questions"]) for row in built),
        "repeat_utterances": sum(
            item["count"] for row in built for item in row["repeated_questions"]
        ),
        "risk_events": sum(len(row["risk_summary"]) for row in built),
        "risk_types": risk_types,
        "meaningful_moments": sum(len(row["meaningful_moments"]) for row in built),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elder", default="elder_001")
    args = parser.parse_args()
    print("최근 30일 고빈도 데모 적재 완료")
    print(json.dumps(seed(args.elder), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
