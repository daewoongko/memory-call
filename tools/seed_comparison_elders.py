r"""담당자 분석 비교용 치매 환자 2명과 30일 통화·복약 데이터를 적재한다.

진단명과 약은 데모 설정값이며 서비스가 발화로 진단하지 않는다. 관찰 기준은
공공 의료기관 자료를 참고해 '의료진에게 보고할 변화'로만 기록한다.

    .\.venv\Scripts\python.exe tools\seed_comparison_elders.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import care  # noqa: E402
import db  # noqa: E402
import report  # noqa: E402
import safety  # noqa: E402


WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

PATIENTS = [
    {
        "elder_id": "elder_002", "name": "박순자", "call_name": "어머니",
        "birth_date": "1944-09-18", "diagnosis": "루이소체 치매 · 파킨슨증",
        "residence": "요양원 2층 생활실",
        "baseline": ["오후에 주의력 변동이 큼", "보행 시작이 느리고 기립 시 어지럼을 종종 호소", "구체적인 사람·동물 환시를 간헐적으로 표현"],
        "cautions": ["새로운 환시가 두려움·위험 행동으로 이어지는지", "기립 어지럼·실신·낙상", "갑작스러운 각성도 또는 보행 악화"],
        "persona": {"id": "persona_sunja_daughter", "name": "지영", "relation": "딸"},
        "medications": [
            {"id": "med_sunja_rivastigmine", "name": "리바스티그민 패치 4.6mg/24시간", "dose": "1매", "time": "09:00", "indication": "루이소체 치매의 인지 증상 관리", "monitor": ["패치 부위 발적·가려움", "메스꺼움·식욕 저하", "체중 감소·어지럼"], "days": 14, "escalate": "실신, 반복 구토, 현저한 체중 감소 또는 심한 피부 반응은 처방 의료진에게 당일 보고"},
            {"id": "med_sunja_levodopa", "name": "레보도파/카비도파 100/25mg", "dose": "1정", "time": "08:00", "indication": "파킨슨증의 느린 움직임과 경직 관리", "monitor": ["기립 시 어지럼", "갑작스러운 졸림", "환시·혼란 변화", "보행 동결"], "days": 7, "escalate": "새로운 환시, 실신, 반복 낙상 또는 급격한 움직임 악화는 의료진에게 신속히 보고"},
        ],
        "templates": [
            {"title": "사람이 보인다는 호소", "text": "방 안에 모르는 아이가 서 있는 것 같아서 무섭다.", "reply": "무섭게 느껴지셨군요. 다가가지 말고 제가 듣고 있으니 보이는 곳을 천천히 말씀해 주세요.", "action": "환시로 인한 공포와 위험 행동 여부, 조명·소음 같은 환경 요인을 확인하세요."},
            {"title": "기립 어지럼", "text": "자리에서 일어나니까 어지럽고 넘어질 것 같다.", "reply": "어지러우시군요. 혼자 걷지 말고 앉아서 담당자가 올 때까지 기다려 주세요.", "action": "기립 전후 상태와 보행 안정성을 확인하고 반복되면 의료진에게 보고하세요."},
            {"title": "보행 시작 어려움", "text": "발이 잘 안 떨어져서 혼자 움직이기 힘들다. 어떻게 해야 하냐?", "reply": "혼자 서두르지 말고 도움을 요청해 주세요. 담당자가 함께 확인하도록 남길게요.", "action": "보행 동결, 경직, 낙상 위험과 투약 전후 차이를 기록하세요."},
            {"title": "야간 꿈과 두려움", "text": "꿈에서 누가 쫓아오는 것 같아서 너무 무섭다.", "reply": "많이 무서우셨군요. 지금 안전한지 담당자가 확인하도록 남길게요.", "action": "수면 중 소리·움직임과 침상 주변 안전을 확인하세요."},
            {"title": "복약 여부 혼동", "text": "아침 약을 먹었나? 약을 먹었는지 기억이 안 난다.", "reply": "추가로 드시지 말고 약통과 기록을 담당자가 먼저 확인하도록 남길게요.", "action": "추가 투약을 보류하고 약포·투약 기록·담당자 서명을 대조하세요."},
            {"title": "외로움", "text": "딸이 보고 싶은데 혼자 있으니까 외롭다.", "reply": "보고 싶고 외로우셨군요. 그 말씀을 가족에게 전할 수 있게 남길게요.", "action": "오후의 반복 연락 시간 전에 짧은 안부 활동을 배치하세요."},
            {"title": "차분한 안부", "text": "오늘은 그냥 네 목소리가 듣고 싶어서 전화했다.", "reply": "목소리가 듣고 싶으셨군요. 오늘 이야기를 천천히 들려주세요.", "action": "추가 확인 없이 평소 상태와 비교 기록만 남기세요."},
            {"title": "실제 낙상", "text": "화장실에서 넘어져서 허리가 아프고 일어나기가 힘들다.", "reply": "움직이지 말고 그대로 계세요. 담당자가 즉시 확인하도록 알릴게요.", "action": "의식·통증·출혈·움직임을 즉시 확인하고 기관 응급 절차를 따르세요."},
        ],
        "weights": [20, 19, 15, 10, 13, 9, 13, 1],
        "peak_hours": [15, 16, 17, 19],
    },
    {
        "elder_id": "elder_003", "name": "이정호", "call_name": "아버님",
        "birth_date": "1939-02-07", "diagnosis": "혈관성 치매 · 고혈압 · 뇌경색 과거력",
        "residence": "요양원 3층 생활실",
        "baseline": ["순서가 많은 일을 시작하기 어려워함", "아침 복약 확인 질문이 잦음", "피로할 때 말 찾기와 시간 혼동이 증가"],
        "cautions": ["갑작스러운 말·얼굴·팔 움직임 변화", "멍·코피·잇몸 출혈 또는 검은 변", "혈압약 후 어지럼과 발목 부종"],
        "persona": {"id": "persona_jeongho_son", "name": "성민", "relation": "아들"},
        "medications": [
            {"id": "med_jeongho_clopidogrel", "name": "클로피도그렐 75mg", "dose": "1정", "time": "08:00", "indication": "뇌경색 재발 예방을 위한 항혈소판 치료", "monitor": ["멍·코피·잇몸 출혈", "검은 변·혈뇨", "낙상 후 출혈"], "days": 7, "escalate": "멈추지 않는 출혈, 검은 변, 혈뇨 또는 머리를 부딪힌 낙상은 즉시 의료진·응급 절차로 보고"},
            {"id": "med_jeongho_amlodipine", "name": "암로디핀 5mg", "dose": "1정", "time": "08:00", "indication": "고혈압 관리", "monitor": ["어지럼", "발목 부종", "두근거림", "보행 불안정"], "days": 14, "escalate": "실신, 흉통, 호흡곤란 또는 일상 기능을 방해하는 지속 부종은 의료진에게 신속히 보고"},
            {"id": "med_jeongho_atorvastatin", "name": "아토르바스타틴 20mg", "dose": "1정", "time": "20:00", "indication": "이상지질혈증 및 뇌혈관 위험 관리", "monitor": ["새로운 근육통", "근력 저하", "짙은 소변", "식욕 변화"], "days": 30, "escalate": "심한 근육통·근력 저하 또는 짙은 소변은 복용을 임의 변경하지 말고 처방 의료진에게 당일 보고"},
        ],
        "templates": [
            {"title": "일의 순서 혼동", "text": "옷을 입고 뭘 먼저 해야 할지 모르겠다. 혼자 하기 힘들다.", "reply": "한 번에 하나씩 해볼게요. 먼저 앉아서 담당자를 불러 주세요.", "action": "세면·옷입기 같은 순차 과제를 한 단계씩 제시하고 수행 여부를 기록하세요."},
            {"title": "현재 시각 혼동", "text": "지금 몇 시냐? 오늘이 무슨 요일인지 모르겠다.", "reply": "현재 시간과 요일을 천천히 확인해 드릴게요. 달력도 같이 보세요.", "action": "큰 시계와 날짜판을 확인하고 같은 시간대 반복 여부를 기록하세요."},
            {"title": "복약 여부 혼동", "text": "혈압약을 먹었나? 약을 먹었는지 기억이 안 난다.", "reply": "추가로 드시지 말고 투약 기록을 담당자가 확인하도록 남길게요.", "action": "추가 투약을 보류하고 투약 기록과 약포를 먼저 대조하세요."},
            {"title": "물건 위치 혼동", "text": "내 안경이 어디 갔냐? 물건을 또 못 찾겠다.", "reply": "안경이 안 보여 답답하시군요. 자주 두는 곳부터 담당자와 확인해 보세요.", "action": "안경 고정 위치와 시야 상태를 확인하세요."},
            {"title": "재산 걱정", "text": "누가 내 통장을 가져갔지? 내 돈이 없어질까 걱정된다.", "reply": "돈이 없어질까 걱정되셨군요. 담당자와 가족이 확인하도록 남길게요.", "action": "사실 논쟁 대신 보관 절차를 안내하고 불안 지속 시간을 기록하세요."},
            {"title": "식사 기억 혼동", "text": "점심을 먹었는지 모르겠다. 밥을 먹었던가?", "reply": "식사 기록을 담당자와 먼저 확인해 볼게요.", "action": "식사표·잔반·섭취량 기록을 대조하세요."},
            {"title": "차분한 안부", "text": "오늘은 그냥 아들 목소리가 듣고 싶어서 전화했다.", "reply": "목소리가 듣고 싶으셨군요. 오늘 있었던 일을 하나만 들려주세요.", "action": "추가 조치 없이 평소 상태와 비교하세요."},
            {"title": "급성 말 변화", "text": "갑자기 말이 안 나오고 한쪽 팔에 힘이 없다.", "reply": "지금은 즉시 담당자의 확인이 필요합니다. 혼자 움직이지 말고 그대로 계세요.", "action": "발생 시각을 기록하고 기관의 뇌졸중 응급 대응 절차를 즉시 따르세요."},
        ],
        "weights": [20, 22, 17, 12, 8, 10, 10, 1],
        "peak_hours": [7, 8, 9, 13],
    },
]


def choose(weighted: list[int], selector: int) -> int:
    point = selector % sum(weighted)
    running = 0
    for index, weight in enumerate(weighted):
        running += weight
        if point < running:
            return index
    return len(weighted) - 1


def delete_demo(conn, elder_id: str) -> None:
    call_ids = [row[0] for row in conn.execute(
        "SELECT call_id FROM calls WHERE elder_id = ? AND call_id LIKE 'compare_%'", (elder_id,),
    )]
    for call_id in call_ids:
        conn.execute("DELETE FROM recall_reviews WHERE utterance_id IN (SELECT utterance_id FROM utterances WHERE call_id = ?)", (call_id,))
        for table in ("heart_artworks", "reports", "call_events", "medication_logs", "utterances"):
            conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM calls WHERE call_id = ?", (call_id,))


def seed_patient(patient: dict, now: datetime) -> dict:
    elder_id = patient["elder_id"]
    call_ids: list[str] = []
    with db.connect() as conn:
        db.init_schema(conn)
        delete_demo(conn, elder_id)
        db.insert(conn, "elder_profiles", {
            "elder_id": elder_id, "name": patient["name"],
            "preferred_call_name": patient["call_name"], "birth_date": patient["birth_date"],
            "residence_type": patient["residence"], "household_members": [],
            "diagnosis_label": patient["diagnosis"], "care_baseline": patient["baseline"],
            "medical_cautions": patient["cautions"], "speech_wait_time_ms": 2400,
            "hearing_support": 1, "vision_support": 1, "anxiety_triggers": [],
            "calming_phrases": ["제가 듣고 있습니다.", "한 번에 하나씩 확인하겠습니다."],
            "frequent_questions": [], "emergency_contacts": [],
        })
        persona = patient["persona"]
        db.insert(conn, "personas", {
            "persona_id": persona["id"], "elder_id": elder_id,
            "display_name": persona["name"], "relationship_type": persona["relation"],
            "elder_calls_family": f"우리 {persona['name']}", "family_calls_elder": patient["call_name"],
            "tone": "차분하고 짧게, 감정을 먼저 인정하고 확인된 사실만 말한다.",
            "frequent_phrases": ["제가 듣고 있어요.", "하나씩 확인해 볼게요."],
            "forbidden_phrases": ["왜 또 물어봐요?", "아까 말했잖아요."],
            "sensitive_policy": "진단하거나 약 변경을 지시하지 않고 담당자 확인으로 연결한다.",
            "call_style_code": "CEML", "call_style_name": "차분한 공감 안내형",
            "call_style_scores": {}, "call_style_answers": {}, "active": 1,
        })
        for medication in patient["medications"]:
            db.insert(conn, "medications", {
                "schedule_id": medication["id"], "elder_id": elder_id,
                "medication_name": medication["name"], "dosage_text": medication["dose"],
                "scheduled_time": medication["time"], "meal_relation": "after",
                "days_of_week": WEEKDAYS, "indication": medication["indication"],
                "monitoring_points": medication["monitor"],
                "review_interval_days": medication["days"],
                "escalation_criteria": medication["escalate"], "active": 1,
            })
        conn.commit()
        ctx = db.load_context(elder_id, persona["id"])

        for days_ago in range(29, -1, -1):
            calls_today = 12 + ((days_ago * 5 + len(elder_id)) % 7)
            for index in range(calls_today):
                template_index = choose(patient["weights"], days_ago * 37 + index * 19)
                # 응급 사례는 환자별 월 1회만 남긴다.
                if days_ago == 3 and index == 2:
                    template_index = len(patient["templates"]) - 1
                elif template_index == len(patient["templates"]) - 1:
                    template_index = 0
                template = patient["templates"][template_index]
                peak = patient["peak_hours"][(index + days_ago) % len(patient["peak_hours"])]
                hour = peak if index < calls_today * 2 // 3 else (10 + index * 3 + days_ago) % 21
                minute = (index * 17 + days_ago * 11) % 60
                started = (now - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                call_id = f"compare_{elder_id}_{days_ago:02d}_{index:02d}"
                call_ids.append(call_id)
                duration = 92 + ((index * 31 + days_ago * 17) % 210)
                db.insert(conn, "calls", {
                    "call_id": call_id, "elder_id": elder_id, "persona_id": persona["id"],
                    "counterpart_name": persona["name"], "counterpart_relation": persona["relation"],
                    "report_title": template["title"], "call_type": "ai",
                    "started_at": started.isoformat(timespec="seconds"),
                    "ended_at": (started + timedelta(seconds=duration)).isoformat(timespec="seconds"),
                    "duration_sec": duration, "end_reason": "demo_seeded", "status": "ended",
                })
                repeats = 2 if template_index in {1, 2, 4} and (index + days_ago) % 4 == 0 else 1
                for turn in range(repeats):
                    elder_uid = db.insert(conn, "utterances", {
                        "call_id": call_id, "seq": turn * 2 + 1, "speaker": "elder",
                        "transcript": template["text"],
                        "created_at": (started + timedelta(seconds=12 + turn * 35)).isoformat(timespec="seconds"),
                    })
                    result = safety.apply({"reply": template["reply"], "used_memory_ids": [], "used_schedule_ids": [], "certainty": "none", "risk": None, "care": {}}, ctx, template["text"])
                    care_data = care.normalize(result.get("care"), user_text=template["text"], ctx=ctx, due_medications=[], response_rewritten=bool(result.get("_rewritten")))
                    care_data["source_utterance_id"] = elder_uid
                    ai_uid = db.insert(conn, "utterances", {
                        "call_id": call_id, "seq": turn * 2 + 2, "speaker": "ai",
                        "transcript": result["reply"], "intent": "risk" if result.get("risk") else "care",
                        "certainty": result.get("certainty"), "used_memory_ids": [], "used_schedule_ids": [],
                        "care_data": care_data, "grounding": "비교 환자 데모의 직접 발화 및 서버 규칙",
                        "safety_flags": result.get("_safety_flags") or [], "was_rewritten": int(bool(result.get("_rewritten"))),
                        "latency_ms": 0, "created_at": (started + timedelta(seconds=27 + turn * 35)).isoformat(timespec="seconds"),
                    })
                    if result.get("risk") and turn == 0:
                        db.insert(conn, "call_events", {"call_id": call_id, "utterance_id": elder_uid, "ai_utterance_id": ai_uid, "event_type": "risk", "payload": result["risk"], "acknowledged": 0, "created_at": (started + timedelta(seconds=14)).isoformat(timespec="seconds")})

                if template_index == 4:
                    medication = patient["medications"][0]
                    db.insert(conn, "medication_logs", {"elder_id": elder_id, "schedule_id": medication["id"], "call_id": call_id, "taken_date": started.date().isoformat(), "status": "UNCLEAR", "evidence_text": template["text"], "created_at": (started + timedelta(seconds=15)).isoformat(timespec="seconds")})
                db.insert(conn, "reports", {"call_id": call_id, "summary": template["title"], "repeated_questions": [], "medication_summary": {}, "new_recalls": [], "risk_summary": [], "care_summary": {}, "meaningful_moments": [], "family_mentions": [], "guardian_actions": [template["action"]]})

            for med_index, medication in enumerate(patient["medications"]):
                if (days_ago + med_index) % 5 != 0:
                    db.insert(conn, "medication_logs", {"elder_id": elder_id, "schedule_id": medication["id"], "call_id": None, "taken_date": (now - timedelta(days=days_ago)).date().isoformat(), "status": "USER_CONFIRMED", "evidence_text": "담당자 투약 기록 확인", "created_at": (now - timedelta(days=days_ago)).replace(hour=int(medication["time"][:2]), minute=int(medication["time"][3:])).isoformat(timespec="seconds")})
        conn.commit()

    for call_id in call_ids:
        report.build(call_id)
    return {"elder_id": elder_id, "name": patient["name"], "calls": len(call_ids)}


def main() -> None:
    now = datetime.now().astimezone()
    result = [seed_patient(patient, now) for patient in PATIENTS]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
