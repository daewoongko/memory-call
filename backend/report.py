"""
통화 리포트 생성.

집계는 전부 규칙으로 한다. 반복 질문 횟수, 복약 상태, 위험 이벤트처럼
보호자가 판단 근거로 쓸 숫자를 모델이 지어내게 두어서는 안 되기 때문이다.

LLM 은 마지막에 한 번만, 이미 확정된 사실을 읽기 좋은 문장으로 바꾸는 데만 쓴다.
새로운 사실을 만들지 못하도록 집계 결과 외에는 아무것도 넘기지 않는다.
"""

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

import db
import llm
import schemas
from analysis import medication as medication_metrics
from analysis import rates as rate_metrics
from analysis.observation_catalog import (
    DOMAIN_LABELS,
    SIGNALS,
    canonical_domain,
)

# 같은 질문으로 묶을 유사도 기준. 치매 노인은 표현을 조금씩 바꿔 되묻는다.
SIMILARITY = 0.72
MIN_REPEAT = 2

RHYTHM_SIGNAL_ACTIONS = {
    "loneliness": "연락이 몰리기 30분 전에 짧은 안부 통화를 시도해 보세요.",
    "medication_uncertain": "해당 시간대 전에는 약통과 복약 기록을 먼저 확인해 주세요.",
    "meal_uncertain": "해당 시간대 전에 식사 여부를 표시해 두면 반복 확인에 도움이 됩니다.",
    "time_confusion": "시계와 오늘 날짜를 잘 보이는 곳에 함께 표시해 주세요.",
    "place_confusion": "해당 시간대에는 현재 장소를 알려주는 익숙한 사진과 표지를 확인해 주세요.",
    "schedule_support": "방문·외출 시간을 큰 글씨로 미리 표시해 주세요.",
    "item_location_uncertain": "자주 찾는 물건의 고정 위치를 해당 시간 전에 함께 확인해 주세요.",
}


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum())


def _evidence_ids(utterance_ids=None, event_ids=None) -> list[str]:
    """근거 식별자를 문자열로 만든다.

    utterance_id 와 event_id 는 서로 다른 테이블의 번호라 숫자만으로는
    구분되지 않는다. 접두사를 붙여 두면 검증 단계가 어느 쪽을 확인할지 알고,
    화면도 발화로 점프할 수 있는 근거인지 판단할 수 있다.

    발화 쪽을 우선한다. 보호자가 보고 싶은 것은 어르신이 한 말이지
    내부 이벤트 번호가 아니다. 발화 연결이 없는 옛 기록만 event 로 남는다.
    """
    uids = [i for i in (utterance_ids or []) if i is not None]
    if uids:
        return [f"utterance-{i}" for i in uids]
    return [f"event-{i}" for i in (event_ids or []) if i is not None]


def _quote(utterances: list[dict], utterance_id) -> str | None:
    """id 로 실제 발화를 찾아온다.

    모델이 신고한 근거 문장은 믿지 않는다. STT 오류를 모델이 알아서 다듬어
    보내기 때문에 DB 에 실제로 있는 문장과 다르다. 보호자에게 따옴표로
    보여줄 문장은 반드시 여기서 나와야 한다.
    """
    if utterance_id is None or not utterances:
        return None
    for u in utterances:
        if u["utterance_id"] == utterance_id:
            return u.get("transcript")
    return None


def _preceding_elder(utterances: list[dict], ai_utterance: dict):
    """AI 발화 바로 앞의 할아버지 발화 id.

    turn() 이 할아버지 → AI 순서로 기록하므로 seq - 1 이 확정적이다.
    추정이 아니다. 통화 첫 인사말처럼 앞이 없으면 None.
    """
    target = (ai_utterance.get("seq") or 0) - 1
    for u in utterances:
        if u.get("seq") == target and u["speaker"] == "elder":
            return u["utterance_id"]
    return None


def _group_repeats(utterances: list[dict]) -> list[dict]:
    """할아버지 발화를 비슷한 것끼리 묶는다.

    utterance_id 를 함께 들고 나온다. 리포트 문장에 근거를 달려면
    "몇 번 물었다"만으로는 부족하고 "어느 발화였는지"가 필요하다.
    """
    groups: list[dict] = []
    for u in utterances:
        if u["speaker"] != "elder" or not u.get("transcript"):
            continue
        norm = _normalize(u["transcript"])
        if not norm:
            continue
        for g in groups:
            if SequenceMatcher(None, g["_norm"], norm).ratio() >= SIMILARITY:
                g["count"] += 1
                g["examples"].append(u["transcript"])
                g["utterance_ids"].append(u["utterance_id"])
                break
        else:
            groups.append({"_norm": norm, "count": 1,
                           "examples": [u["transcript"]],
                           "utterance_ids": [u["utterance_id"]]})

    repeats = [
        {"question": g["examples"][0], "count": g["count"],
         "utterance_ids": g["utterance_ids"]}
        for g in groups if g["count"] >= MIN_REPEAT
    ]
    return sorted(repeats, key=lambda r: -r["count"])


def _medication(events: list[dict], meds: list[dict],
                logs: list[dict] | None = None,
                utterances: list[dict] | None = None) -> dict:
    status_label = {
        "USER_CONFIRMED": "복용했다고 답하심",
        "UNCLEAR": "복용 여부를 기억하지 못하심",
        "REFUSED": "복용을 거부하심",
        "DUPLICATE_SUSPECTED": "중복 복용이 의심됨",
    }
    # 어떤 약인지는 복약 기록에서 가져온다. 이벤트에는 약 이름이 없다.
    name_of = {m["schedule_id"]: m["medication_name"] for m in meds}
    entries = []
    for log in logs or []:
        status = log.get("status")
        name = name_of.get(log.get("schedule_id"), "약")
        entries.append({
            "medication_name": name,
            "status": status,
            "label": f"{name} — {status_label.get(status, status or '확인되지 않음')}",
            "utterance_id": log.get("utterance_id"),
            "evidence": _quote(utterances, log.get("utterance_id")),
        })
    if not entries:
        # medication_logs 가 정본이다. 여기로 오는 것은 옛 기록뿐이고,
        # 이벤트에는 약 이름이 없어 어떤 약인지 알 수 없다.
        for e in events:
            if e["event_type"] != "medication":
                continue
            status = (e.get("payload") or {}).get("status")
            entries.append({
                "medication_name": None,
                "status": status,
                "label": status_label.get(status, status or "확인되지 않음"),
                "utterance_id": e.get("utterance_id"),
                "event_id": e["event_id"],
                "evidence": _quote(utterances, e.get("utterance_id")),
            })
    return {
        "registered": [m["medication_name"] for m in meds],
        "mentioned": len(entries),
        "entries": entries,
        "needs_check": any(
            e["status"] in ("UNCLEAR", "DUPLICATE_SUSPECTED", "REFUSED")
            for e in entries
        ),
    }


def _risks(events: list[dict], utterances: list[dict]) -> list[dict]:
    label = {
        "fall": "낙상", "chest_pain": "가슴 통증", "breathing": "호흡 곤란",
        "lost": "길 잃음", "overdose": "약 과다 복용 의심",
        "self_harm": "정서적 위기 표현", "intrusion": "침입", "fire": "화재",
        "gas_leak": "가스 누출 의심",
    }
    out = []
    for e in events:
        if e["event_type"] != "risk":
            continue
        p = e.get("payload") or {}
        uid = e.get("utterance_id")
        out.append({
            "event_id": e["event_id"],
            "utterance_id": uid,                      # 할아버지 발화. 보호자용
            "ai_utterance_id": e.get("ai_utterance_id"),   # 신고한 응답. 추적용
            "type": p.get("type"),
            "label": label.get(p.get("type"), p.get("type")),
            "level": p.get("level"),
            # evidence 는 이제 DB 의 실제 발화다. 없으면 None 이고,
            # 화면은 아무것도 인용하지 않는다.
            "evidence": _quote(utterances, uid),
            # 모델이 신고한 문장. 인용이 아니라 AI 요약으로만 표시한다.
            "ai_summary": p.get("evidence"),
        })
    return out


def _unverified(utterances: list[dict]) -> list[dict]:
    """AI 가 사실로 확정하지 않고 넘긴 기억. 보호자 확인이 필요하다."""
    out = []
    for u in utterances:
        recall = u.get("unverified_recall")
        if recall:
            elder_uid = _preceding_elder(utterances, u)
            out.append({
                "utterance_id": elder_uid,          # 할아버지 발화
                "ai_utterance_id": u["utterance_id"],   # 회상이 나온 응답
                "summary": recall.get("summary"),
                "evidence": _quote(utterances, elder_uid),
                "ai_summary": recall.get("quote"),
            })
    return out


def _safety(utterances: list[dict]) -> list[dict]:
    """안전 규칙이 응답을 고친 기록. 명세 NFR-05 의 설명 가능성에 해당한다."""
    out = []
    for u in utterances:
        flags = u.get("safety_flags") or []
        if not flags:
            continue
        elder_uid = _preceding_elder(utterances, u)
        for flag in flags:
            out.append({
                "utterance_id": elder_uid,
                "ai_utterance_id": u["utterance_id"],
                "code": flag.get("code"),
                "reason": flag.get("reason"),
            })
    return out


CARE_DOMAIN_LABEL = DOMAIN_LABELS
CARE_SIGNAL_LABEL = {signal: spec.label for signal, spec in SIGNALS.items()}

MEANING_LABEL = {
    "affection": "가족을 향한 애정",
    "gratitude": "고마움",
    "apology": "미안함",
    "longing": "그리움",
    "pride": "자부심",
    "wish_for_family": "가족을 향한 바람",
    "preference": "좋아하는 것",
    "joy": "기쁨의 순간",
    "life_story": "삶의 이야기",
}

HEART_KEYWORDS = {
    "affection": ["안 잊", "이름", "사랑", "우리", "걱정"],
    "gratitude": ["고맙", "감사"],
    "apology": ["미안", "해준 것도 없"],
    "longing": ["그립", "생각난", "그때가 참 좋", "보고 싶"],
    "pride": ["자랑", "대견", "뿌듯"],
    "wish_for_family": ["잘됐으면", "건강", "바라"],
    "preference": ["좋아", "예쁘"],
    "joy": ["좋았", "기쁘", "행복", "웃"],
    "life_story": ["옛날", "고향", "그때", "살던"],
}


def _short_quote(text: str, category: str | None = None) -> str:
    """마음 리포트용으로 원문 안의 가장 관련 있는 한 문장을 고른다."""
    text = (text or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if part.strip()]
    keywords = HEART_KEYWORDS.get(category or "", [])
    for keyword in keywords:
        for part in parts:
            if keyword in part:
                return part[:220]
    return min(parts, key=len)[:220]


def _heart_report(care_summary: dict, moments: list[dict], mentions: list[dict],
                  risks: list[dict], actions: list[str], unverified: list[dict],
                  memories: list[dict], used_memory_ids: list[str],
                  artwork: dict | None = None,
                  memory_artworks: dict[str, dict] | None = None) -> dict:
    """관찰 사실을 가족이 읽을 수 있는 마음 리포트로 번역한다.

    새 감정을 추론하지 않는다. 마음 표현은 meaningful_moments의 직접 발화만,
    가족 반복은 이름 횟수만, 기억 연결은 확인된 기억만 사용한다.
    """
    domain_counts = {domain: 0 for domain in CARE_DOMAIN_LABEL}
    for supplied_domain, items in care_summary.items():
        if supplied_domain == "meaningful_moments":
            continue
        for item in items or []:
            domain = canonical_domain(item.get("signal"), supplied_domain)
            if domain in domain_counts:
                domain_counts[domain] += 1
    state_parts = [
        f"{CARE_DOMAIN_LABEL[domain]} {count}건"
        for domain, count in domain_counts.items() if count
    ]
    state_line = (
        "이번 통화에서는 " + ", ".join(state_parts) + "이 관찰되었습니다."
        if state_parts else "이번 통화에서는 분류된 인지·정서·생활 관찰이 없었습니다."
    )

    priority = {name: index for index, name in enumerate(
        ["apology", "affection", "worry_for_family", "longing", "gratitude",
         "pride", "wish_for_family", "joy", "life_story", "preference"]
    )}
    strongest = min(
        moments,
        key=lambda item: priority.get(item.get("category"), 99),
        default=None,
    )
    top_mention = mentions[0] if mentions else None
    family_line = "가족에게 전할 직접적인 마음 표현은 확인되지 않았습니다."
    if strongest:
        quote = _short_quote(strongest.get("evidence", ""), strongest.get("category"))
        family_line = f"“{quote}”라는 말씀은 {strongest['label']}으로 기록되었습니다."
        if top_mention and top_mention.get("count", 0) >= 2:
            family_line = (
                f"{top_mention['name']}님의 이름을 {top_mention['count']}번 말씀하셨습니다. "
                + family_line
            )
    elif top_mention and top_mention.get("count", 0) >= 2:
        family_line = (
            f"{top_mention['name']}님의 이름이 {top_mention['count']}번 등장했습니다. "
            "이 사실만으로 특정 감정을 단정하지는 않았습니다."
        )

    missed_word = None
    if strongest:
        missed_word = {
            "label": strongest["label"],
            "quote": _short_quote(strongest.get("evidence", ""), strongest.get("category")),
            "at": strongest.get("at"),
            "note": "가족과 관련된 직접적인 감정·삶의 표현 중 우선해서 전할 말씀입니다.",
        }

    memory_by_id = {
        memory["memory_id"]: memory for memory in memories
        if memory.get("status") == "verified" and memory.get("conversation_allowed")
    }
    related_ids = []
    for moment in moments:
        related_ids.extend(moment.get("related_memory_ids") or [])
    related_ids.extend(used_memory_ids)
    matched = next((memory_by_id[mid] for mid in related_ids if mid in memory_by_id), None)
    if not matched:
        # 모델이 memory_id를 돌려주지 않아도 실제 발화에 보호자가 확정한 기억
        # 제목이 명확히 포함돼 있으면 연결한다. 짧은 제목은 우연히 겹칠 수 있어
        # 자동 연결하지 않는다.
        matched = next((
            memory
            for moment in moments
            for memory in memory_by_id.values()
            if len(_normalize(memory.get("title", ""))) >= 4
            and _normalize(memory.get("title", "")) in _normalize(moment.get("evidence", ""))
        ), None)

    memory_bridge = None
    if matched:
        memory_bridge = {
            "mode": "verified",
            "title": matched.get("title"),
            "description": matched.get("description"),
            "date_text": matched.get("date_text"),
            "location": matched.get("location"),
            "quote": missed_word.get("quote") if missed_word else None,
            "suggestion": "확인된 사진이나 이야기가 있다면 다음 만남에서 함께 다시 꺼내보세요.",
        }
    elif strongest or unverified:
        source = unverified[0].get("evidence") if unverified else strongest.get("evidence")
        memory_bridge = {
            "mode": "confirm_first",
            "title": "다시 이어볼 수 있는 이야기",
            "description": "이 말씀과 직접 연결된 확인 완료 가족 기억은 아직 없습니다.",
            "quote": _short_quote(source, strongest.get("category") if strongest else None),
            "suggestion": "가족이 사실 관계를 확인한 뒤 가족 기억으로 등록해 다음 통화에 이어보세요.",
        }

    if not artwork and matched:
        artwork = (memory_artworks or {}).get(matched["memory_id"])

    visual_story = None
    if artwork:
        approved = artwork.get("status") == "approved"
        visual_story = {
            "status": artwork.get("status"),
            "status_label": "확인된 기억 기반" if approved else "보호자 확인 전 · 상상 이미지",
            "image_url": artwork.get("image_url"),
            "source_quote": artwork.get("source_quote"),
            "alt_text": artwork.get("alt_text"),
            "caption": artwork.get("caption"),
            "memory_id": artwork.get("memory_id"),
        }

    memory_banner = None
    if matched and artwork and artwork.get("status") == "approved":
        linked_moment = next((
            moment for moment in moments
            if matched["memory_id"] in (moment.get("related_memory_ids") or [])
        ), None) or next((
            moment for moment in moments
            if _normalize(matched.get("title", "")) in _normalize(moment.get("evidence", ""))
        ), None)
        quote = _short_quote(
            (linked_moment or {}).get("evidence", ""),
            (linked_moment or {}).get("category"),
        )
        if quote:
            category = linked_moment.get("category")
            message = {
                "longing": "그리움을 직접 표현하신 소중한 말씀입니다.",
                "joy": "기쁜 마음으로 다시 떠올리신 소중한 말씀입니다.",
                "life_story": "좋았던 시간을 다시 떠올리신 소중한 말씀입니다.",
                "gratitude": "고마운 마음을 직접 전하신 소중한 말씀입니다.",
                "affection": "가족을 향한 마음을 직접 전하신 소중한 말씀입니다.",
            }.get(category, "확인된 가족 기억과 다시 연결된 소중한 말씀입니다.")
            memory_banner = {
                "title": "이날 다시 떠오른 가족 기억",
                "memory_title": matched.get("title"),
                "image_url": artwork.get("image_url"),
                "alt_text": artwork.get("alt_text"),
                "quote": quote,
                "message": message,
                "caption": artwork.get("caption"),
                "memory_id": matched.get("memory_id"),
            }

    return {
        "priority": "safety" if any(risk.get("level") == "high" for risk in risks) else "heart",
        "day_translation": {
            "state": state_line,
            "family": family_line,
            "observation_count": sum(domain_counts.values()),
        },
        "missed_word": missed_word,
        "memory_bridge": memory_bridge,
        "visual_story": visual_story,
        "memory_banner": memory_banner,
        "guardian_actions": actions,
    }


def _care_analysis(utterances: list[dict]) -> dict:
    """검증된 care_data를 실제 환자 발화에 다시 연결한다.

    care_data 안의 evidence 문구는 분류 검증용일 뿐 보호자 인용문으로 쓰지
    않는다. 화면과 리포트에는 source_utterance_id로 DB에서 되찾은 원문만 쓴다.
    """
    by_domain = {key: [] for key in CARE_DOMAIN_LABEL}
    moments = []
    seen_observations = set()
    seen_moments = set()

    for ai in utterances:
        if ai.get("speaker") != "ai":
            continue
        data = ai.get("care_data") or {}
        source_uid = data.get("source_utterance_id") or _preceding_elder(
            utterances, ai
        )
        evidence = _quote(utterances, source_uid)
        if source_uid is None or not evidence:
            continue
        source = next(
            (u for u in utterances if u.get("utterance_id") == source_uid), {}
        )

        for obs in data.get("observations") or []:
            signal = obs.get("signal")
            domain = canonical_domain(signal, obs.get("domain"))
            if obs.get("verification") == "candidate":
                continue
            if domain not in by_domain or signal not in CARE_SIGNAL_LABEL:
                continue
            key = (source_uid, domain, signal)
            if key in seen_observations:
                continue
            seen_observations.add(key)
            by_domain[domain].append({
                "signal": signal,
                "label": CARE_SIGNAL_LABEL[signal],
                "utterance_id": source_uid,
                "evidence": evidence,
                "at": source.get("created_at"),
            })

        for moment in data.get("meaningful_moments") or []:
            category = moment.get("category")
            if category not in MEANING_LABEL:
                continue
            key = (source_uid, category)
            if key in seen_moments:
                continue
            seen_moments.add(key)
            moments.append({
                "category": category,
                "label": MEANING_LABEL[category],
                "utterance_id": source_uid,
                "evidence": evidence,
                "at": source.get("created_at"),
                "related_memory_ids": moment.get("related_memory_ids") or [],
            })

    return {**by_domain, "meaningful_moments": moments}


def _family_mentions(utterances: list[dict], family_names: list[str]) -> list[dict]:
    """등록된 가족 이름이 환자 발화에 등장한 횟수를 규칙으로 센다.

    이름이 자주 나왔다는 사실과 그 사람을 그리워한다는 해석은 다르다.
    여기서는 전자만 만들고, 그리움은 meaningful_moments의 직접 발화가 있을
    때만 별도로 보여준다.
    """
    out = []
    for name in sorted({str(n).strip() for n in family_names if str(n).strip()}):
        count = 0
        utterance_ids = []
        examples = []
        for row in utterances:
            if row.get("speaker") != "elder":
                continue
            text = row.get("transcript") or ""
            hits = text.count(name)
            if not hits:
                continue
            count += hits
            utterance_ids.append(row["utterance_id"])
            examples.append(text)
        if count:
            out.append({
                "name": name,
                "count": count,
                "utterance_ids": utterance_ids,
                "examples": examples[:3],
            })
    return sorted(out, key=lambda item: (-item["count"], item["name"]))


def _offered_ids(facts: dict) -> set[str]:
    """집계에서 모델에게 실제로 건넨 근거 id 를 모은다.

    facts 를 훑어 "근거" 배열을 전부 거둔다. 집계 항목이 늘어도 여기를
    고칠 필요가 없게 하려고 구조를 따라 내려간다.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "근거" and isinstance(value, list):
                    found.update(i for i in value if isinstance(i, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(facts)
    return found


def _existing_ids(utterances: list[dict], events: list[dict]) -> set[str]:
    """DB 에 실제로 있는 기록의 근거 id."""
    ids = {
        f"utterance-{u['utterance_id']}"
        for u in utterances if u.get("utterance_id") is not None
    }
    ids |= {
        f"event-{e['event_id']}"
        for e in events if e.get("event_id") is not None
    }
    return ids


def _verify_evidence(observations: list[dict], facts: dict,
                     utterances: list[dict],
                     events: list[dict]) -> tuple[list[dict], list[dict]]:
    """모델이 지목한 근거가 실재하는지 확인한다.

    두 가지를 본다.

    1. 그 id 가 DB 에 실제로 있는가
    2. 그 id 를 이 통화의 집계에서 모델에게 건넨 적이 있는가

    2번이 따로 필요하다. DB 에 있는 번호라도 집계에 없던 것을 끌어오면
    근거를 지어낸 것과 같기 때문이다. 번호는 연속적이라 모델이 옆 번호를
    적어도 1번만으로는 걸리지 않는다.

    근거가 하나도 남지 않은 관찰은 버린다. 근거 없는 관찰을 보호자에게
    보여주는 것은 확인되지 않은 것을 사실로 만드는 일이다.

    관찰을 버려도 위험·복약·반복질문은 리포트에 그대로 남는다. 그쪽은
    DB 집계라 모델을 거치지 않기 때문이다. 여기서 사라지는 것은 문장뿐이다.
    """
    allowed = _offered_ids(facts) & _existing_ids(utterances, events)
    kept: list[dict] = []
    dropped: list[dict] = []
    for obs in observations or []:
        ids = [i for i in (obs.get("evidence_ids") or []) if i in allowed]
        if not ids:
            dropped.append(dict(obs, reason="근거를 확인할 수 없음"))
            continue
        kept.append(dict(obs, evidence_ids=ids))
    return kept, dropped


SUMMARY_SYSTEM = """너는 치매 노인의 통화 기록을 보호자에게 전하는 역할이다.

아래 집계 결과만 사용한다. 여기에 없는 사실을 추론하거나 덧붙이지 않는다.
진단하지 않는다. "치매가 악화되었다" 같은 의학적 판단은 절대 쓰지 않는다.
관찰된 사실과 보호자가 할 수 있는 행동만 적는다.

가족에게 정서적 울림이 있는 순간은 따뜻하게 전달하되 마음을 지어내지 않는다.
- "보고 싶다", "고맙다", "미안하다"처럼 직접 표현한 감정은 그대로 설명한다.
- 가족 이름이 반복됐지만 감정을 직접 말하지 않았다면 "이름이 여러 번
  등장했다"까지만 쓴다. 그리움이나 사랑으로 단정하지 않는다.
- 단일한 모호한 발화는 해석하지 말고 가족이 함께 봤으면 하는 순간으로 남긴다.
- 보호자가 죄책감을 느끼게 하는 문장이나 "마지막 말" 같은 표현은 쓰지 않는다.

"발화" 는 어르신이 실제로 한 말이다. 무슨 일이 있었는지 파악하는 데만 쓰고,
그 문장을 그대로 옮겨 적지 않는다. 음성 인식 오류가 섞여 있어 그대로 옮기면
어르신이 이상하게 말한 것처럼 보인다. 원문은 화면이 따로 보여주므로
너는 풀어서 설명하기만 하면 된다.

"발화" 가 없는 항목은 옛 기록이라 원문을 되찾을 수 없는 것이다.
없는 말을 지어내지 말고, 종류와 수준만 가지고 쓴다.

"근거" 는 그 사실이 어느 기록에서 나왔는지를 가리키는 식별자다. 지어내지 않는다.

반드시 아래 JSON 만 출력한다.
{
  "summary": "통화 전체 요약. 3문장 이내. 존댓말.",
  "observations": [
    {
      "text": "보호자가 알아야 할 관찰 한 문장. 존댓말.",
      "evidence_ids": ["이 문장의 근거"],
      "severity": "low 또는 medium 또는 high"
    }
  ],
  "guardian_actions": ["보호자가 오늘 확인하면 좋을 일. 최대 3개. 없으면 빈 배열"]
}

observations 규칙:
- 집계에 있는 항목에 대해서만 쓴다. 최대 5개. 없으면 빈 배열.
- evidence_ids 에는 집계의 "근거" 배열에 실제로 있는 값만 그대로 옮긴다.
  새로 만들거나 번호를 바꾸지 않는다.
- 근거가 없는 항목(통화 시간, 발화 수 같은 집계 숫자)은 observations 에 넣지
  말고 summary 에만 쓴다. 근거 없는 관찰은 보호자에게 전달되지 않는다.
- severity 는 보호자가 얼마나 급히 확인해야 하는지다.
  high 는 다치셨거나 위험한 일이 실제로 있었을 때만 쓴다."""


def _fallback_narrative(facts: dict) -> dict:
    """모델 없이 확정 집계만으로 만드는 안전한 요약."""
    care_items = facts.get("인지_정서_생활_관찰") or []
    risks = facts.get("위험이벤트") or []
    recalls = facts.get("확인이필요한_기억") or []
    domains = []
    for item in care_items:
        label = item.get("영역")
        if label and label not in domains:
            domains.append(label)
    summary_parts = [f"통화에서 관찰 근거 {len(care_items)}건이 기록되었습니다."]
    if domains:
        summary_parts.append(f"관찰 영역은 {', '.join(domains)}입니다.")
    if risks:
        summary_parts.append(f"안전 확인이 필요한 신호 {len(risks)}건이 있습니다.")
    actions = []
    if risks:
        actions.append("안전 신호의 실제 발화를 확인하고 현재 상태를 직접 확인해 주세요.")
    if recalls:
        actions.append("새로 나온 이야기는 사실 여부를 확인한 뒤 가족 기억으로 등록해 주세요.")
    return {"summary": " ".join(summary_parts),
            "observations": [], "guardian_actions": actions}


def _narrative(facts: dict) -> dict:
    """집계 결과를 보호자가 읽을 문장으로 바꾼다.

    형태 검증은 llm.call_schema() 가 한다. 여기서 나온 evidence_ids 는
    아직 검증되지 않았다. 실제로 있는 기록인지는 _verify_evidence() 가 본다.
    """
    out = llm.call_schema(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        schemas.CallNarrative,
        temperature=0.3,
        model=llm.REPORT_MODEL,
    )
    if out is None:
        # 모델 한도가 끝나도 위험을 "정상"으로 지우지 않는다. 확정 집계만으로
        # 짧은 문장을 조립하고, 보호자가 직접 확인할 항목을 남긴다.
        return _fallback_narrative(facts)
    return out.model_dump()


def build(call_id: str, regenerate: bool = False) -> dict:
    """통화 하나의 리포트를 만들어 저장하고 돌려준다.

    집계는 매번 다시 한다. DB 만 읽으므로 비용이 없고, 집계 규칙을 고쳤을 때
    예전 리포트가 낡은 채로 남아 있는 것을 막는다.
    비싼 것은 LLM 문장뿐이라 그것만 저장해 두고 재사용한다.
    """
    with db.connect() as conn:
        call_row = conn.execute(
            "SELECT * FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if call_row is None:
            raise ValueError(f"통화 {call_id} 없음")
        call = db._row(call_row)

        cached = None if regenerate else conn.execute(
            "SELECT summary, guardian_actions FROM reports WHERE call_id = ?",
            (call_id,),
        ).fetchone()

        utterances = [db._row(r) for r in conn.execute(
            "SELECT * FROM utterances WHERE call_id = ? ORDER BY seq", (call_id,)
        ).fetchall()]
        events = [db._row(r) for r in conn.execute(
            "SELECT * FROM call_events WHERE call_id = ?", (call_id,)
        ).fetchall()]
        meds = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ?", (call["elder_id"],)
        ).fetchall()]
        med_logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE call_id = ? ORDER BY log_id",
            (call_id,)
        ).fetchall()]
        elder_profile = db._row(conn.execute(
            "SELECT * FROM elder_profiles WHERE elder_id = ?", (call["elder_id"],)
        ).fetchone())
        personas = [db._row(r) for r in conn.execute(
            "SELECT * FROM personas WHERE elder_id = ?", (call["elder_id"],)
        ).fetchall()]
        registered_memories = [db._row(r) for r in conn.execute(
            "SELECT * FROM memories WHERE elder_id = ?", (call["elder_id"],)
        ).fetchall()]
        # 이미지의 출처 문장이 같은 통화의 실제 어르신 발화에 포함될 때만
        # 보호자 화면으로 보낸다. 잘못 연결된 이미지 행은 조용히 노출하지 않는다.
        artwork_row = conn.execute(
            "SELECT a.* FROM heart_artworks a "
            "JOIN utterances u ON u.utterance_id = a.source_utterance_id "
            "LEFT JOIN memories m ON m.memory_id = a.memory_id "
            "WHERE a.call_id = ? AND a.status != 'rejected' "
            "AND u.call_id = a.call_id AND u.speaker = 'elder' "
            "AND instr(u.transcript, a.source_quote) > 0 "
            "AND (a.memory_id IS NULL OR (m.status = 'verified' AND m.conversation_allowed = 1)) "
            "ORDER BY CASE a.status WHEN 'approved' THEN 0 ELSE 1 END, a.created_at DESC "
            "LIMIT 1",
            (call_id,),
        ).fetchone()
        artwork = db._row(artwork_row) if artwork_row else None
        archived_artworks = [db._row(r) for r in conn.execute(
            "SELECT a.* FROM heart_artworks a "
            "JOIN memories m ON m.memory_id = a.memory_id "
            "WHERE m.elder_id = ? AND a.status = 'approved' "
            "AND m.status = 'verified' AND m.conversation_allowed = 1 "
            "ORDER BY a.created_at DESC",
            (call["elder_id"],),
        ).fetchall()]
        memory_artworks = {}
        for archived in archived_artworks:
            memory_artworks.setdefault(archived["memory_id"], archived)

    elder_turns = [u for u in utterances if u["speaker"] == "elder"]
    ai_turns = [u for u in utterances if u["speaker"] == "ai"]
    latencies = [u["latency_ms"] for u in ai_turns if u.get("latency_ms")]

    repeats = _group_repeats(utterances)
    medication = _medication(events, meds, med_logs, utterances)
    risks = _risks(events, utterances)
    unverified = _unverified(utterances)
    safety = _safety(utterances)
    care_summary = _care_analysis(utterances)
    meaningful_moments = care_summary.pop("meaningful_moments")
    household_names = [
        row.get("name")
        for row in (elder_profile.get("household_members") or [])
        if isinstance(row, dict) and row.get("name")
    ]
    family_mentions = _family_mentions(
        utterances,
        [p.get("display_name") for p in personas]
        + household_names
        + [call.get("counterpart_name")],
    )

    topics = sorted({
        mid for u in ai_turns for mid in (u.get("used_memory_ids") or [])
    })

    # 모델에게 넘길 집계 결과. 여기에 없는 것은 리포트에 나올 수 없다.
    # 각 항목에 "근거" 를 달아 두면 모델이 문장마다 출처를 지목할 수 있고,
    # 지목한 id 가 실제로 있는지는 뒤에서 검증한다.
    facts = {
        "통화시간_초": call["duration_sec"],
        "할아버지_발화수": len(elder_turns),
        "AI_응답수": len(ai_turns),
        "반복질문": [
            {
                "질문": r["question"],
                "횟수": r["count"],
                "근거": _evidence_ids(utterance_ids=r["utterance_ids"]),
            }
            for r in repeats
        ],
        "복약": {
            "언급횟수": medication["mentioned"],
            "확인필요": medication["needs_check"],
            "상태": [
                {
                    "내용": e["label"],
                    "발화": e.get("evidence"),
                    "근거": _evidence_ids(
                        utterance_ids=[e.get("utterance_id")],
                        event_ids=[e.get("event_id")],
                    ),
                }
                for e in medication["entries"]
            ],
        },
        "위험이벤트": [
            {
                "종류": r["label"],
                "수준": r["level"],
                # 실제 발화. 연결이 없는 옛 기록은 None 이고, 그 경우 모델은
                # 종류와 수준만 가지고 쓴다. 모델이 신고한 ai_summary 는
                # 여기에 넣지 않는다. 넘기면 지어낸 문장이 리포트로 돌아온다.
                "발화": r.get("evidence"),
                "근거": _evidence_ids(
                    utterance_ids=[r.get("utterance_id")],
                    event_ids=[r.get("event_id")],
                ),
            }
            for r in risks
        ],
        "확인이필요한_기억": [
            {
                "내용": u["summary"],
                "발화": u.get("evidence"),
                "근거": _evidence_ids(utterance_ids=[u.get("utterance_id")]),
            }
            for u in unverified
        ],
        "안전규칙_개입": [
            {
                "사유": s["reason"],
                # 여기 근거는 AI 발화다. "AI 가 이 응답을 고쳤다" 가 사실이므로
                # 가리켜야 할 기록도 그 응답이다.
                "근거": _evidence_ids(utterance_ids=[s.get("ai_utterance_id")]),
            }
            for s in safety
        ],
        "인지_정서_생활_관찰": [
            {
                "영역": CARE_DOMAIN_LABEL[domain],
                "신호": item["label"],
                "발화": item["evidence"],
                "근거": _evidence_ids(
                    utterance_ids=[item.get("utterance_id")]
                ),
            }
            for domain, items in care_summary.items()
            for item in items
        ],
        "마음기록_후보": [
            {
                "종류": item["label"],
                "발화": item["evidence"],
                "연결된_확인기억": item["related_memory_ids"],
                "근거": _evidence_ids(
                    utterance_ids=[item.get("utterance_id")]
                ),
            }
            for item in meaningful_moments
        ],
        "가족이름_언급": [
            {
                "이름": item["name"],
                "횟수": item["count"],
                "발화예시": item["examples"],
                "근거": _evidence_ids(
                    utterance_ids=item["utterance_ids"]
                ),
            }
            for item in family_mentions
        ],
    }

    stale_normal_summary = (
        cached and cached["summary"] == "통화가 정상적으로 진행되었습니다."
        and (facts["인지_정서_생활_관찰"] or facts["위험이벤트"])
    )
    if cached and cached["summary"] and not stale_normal_summary:
        story = {
            "summary": cached["summary"],
            "guardian_actions": json.loads(cached["guardian_actions"] or "[]"),
        }
    elif stale_normal_summary:
        story = _fallback_narrative(facts)
    else:
        story = _narrative(facts)

    # 모델이 지목한 근거를 검증한다. 여기를 통과하지 못한 관찰은 버린다.
    observations, dropped = _verify_evidence(
        story.get("observations", []), facts, utterances, events
    )

    report = {
        "call_id": call_id,
        "call_meta": {
            "started_at": call.get("started_at"),
            "duration_sec": call.get("duration_sec") or 0,
            "counterpart_name": call.get("counterpart_name"),
            "counterpart_relation": call.get("counterpart_relation"),
            "report_title": call.get("report_title") or "인지·정서 케어 통화",
        },
        "summary": story.get("summary", ""),
        "repeated_questions": repeats,
        "medication_summary": medication,
        "new_recalls": unverified,
        "risk_summary": risks,
        "care_summary": care_summary,
        "meaningful_moments": meaningful_moments,
        "family_mentions": family_mentions,
        "guardian_actions": story.get("guardian_actions", []),
    }
    heart_report = _heart_report(
        care_summary, meaningful_moments, family_mentions, risks,
        report["guardian_actions"], unverified, registered_memories, topics,
        artwork, memory_artworks,
    )

    with db.connect() as conn:
        conn.execute("DELETE FROM reports WHERE call_id = ?", (call_id,))
        db.insert(conn, "reports", {
            key: value for key, value in report.items() if key != "call_meta"
        })
        conn.commit()

    # facts 는 DB 에 저장하지 않는다 (reports 테이블 컬럼이 아니다).
    # 응답에만 실어 보내 모델이 무엇을 보고 썼는지 확인할 수 있게 한다.
    # observations 는 아직 reports 테이블 컬럼이 아니다 (7단계에서 추가).
    # 그래서 캐시된 리포트를 읽을 때는 비어 있다. 확인할 때 regenerate=True 를 쓸 것.
    # observations_dropped 는 근거 검증에서 걸러낸 관찰이다. 숨기지 않고
    # 실어 보낸다. 무엇이 왜 빠졌는지 볼 수 없으면 검증이 조용한 손실이 된다.
    return dict(report, heart_report=heart_report, observations=observations,
                observations_dropped=dropped,
                facts=facts, stats={
        "duration_sec": call["duration_sec"],
        "elder_turns": len(elder_turns),
        "ai_turns": len(ai_turns),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "memories_used": topics,
        "safety_interventions": safety,
        "started_at": call["started_at"],
    })


def _canonical_care_groups(care_summary: dict | None) -> dict[str, list[dict]]:
    """저장 시점과 무관하게 관찰을 현재 8개 영역으로 묶는다.

    초기 데모 데이터의 ``memory_orientation``처럼 지금은 사용하지 않는
    영역명이 DB에 남아 있어도 최근 통화와 기간 리포트에서 빠지지 않게 한다.
    의미 기록은 임상 관찰 건수와 분리한다.
    """
    groups = {key: [] for key in CARE_DOMAIN_LABEL}
    for supplied_domain, items in (care_summary or {}).items():
        if supplied_domain == "meaningful_moments":
            continue
        for item in items or []:
            domain = canonical_domain(item.get("signal"), supplied_domain)
            if domain in groups:
                groups[domain].append(item)
    return groups


def recent(elder_id: str = "elder_001", limit: int = 20) -> list[dict]:
    """보호자 화면 목록용. 통화별 한 줄 요약."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT c.call_id, c.started_at, c.duration_sec, c.call_type, "
            "       c.counterpart_name, c.counterpart_relation, c.report_title, "
            "       r.summary, r.repeated_questions, r.risk_summary, "
            "       r.meaningful_moments, r.care_summary "
            "FROM calls c LEFT JOIN reports r ON r.call_id = c.call_id "
            "WHERE c.elder_id = ? AND c.status = 'ended' "
            "ORDER BY c.started_at DESC LIMIT ?",
            (elder_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        row = db._row(r)
        care = _canonical_care_groups(row.get("care_summary"))
        care_domains = [
            {
                "key": key,
                "label": CARE_DOMAIN_LABEL[key],
                "count": len(care.get(key) or []),
            }
            for key in CARE_DOMAIN_LABEL if care.get(key)
        ]
        observed_items = [
            {"domain": CARE_DOMAIN_LABEL[key], "label": item.get("label")}
            for key in CARE_DOMAIN_LABEL
            for item in (care.get(key) or [])
            if item.get("label")
        ]
        observed_items.extend({
            "domain": "안전",
            "label": risk.get("label") or risk.get("type") or "위험 신호",
        } for risk in (row.get("risk_summary") or []))
        out.append({
            "call_id": row["call_id"],
            "started_at": row["started_at"],
            "duration_sec": row["duration_sec"],
            "call_type": row.get("call_type") or "ai",
            "summary": row.get("summary"),
            "counterpart_name": row.get("counterpart_name"),
            "counterpart_relation": row.get("counterpart_relation"),
            "report_title": row.get("report_title") or "인지·정서 케어 통화",
            "repeat_count": len(row.get("repeated_questions") or []),
            "risk_count": len(row.get("risk_summary") or []),
            "meaning_count": len(row.get("meaningful_moments") or []),
            "care_domains": care_domains,
            "observed_items": observed_items[:5],
            "care_count": sum(len(care.get(key) or []) for key in CARE_DOMAIN_LABEL),
        })
    return out


# ------------------------------------------------------------------ 기간 요약

WEEKLY_SYSTEM = """너는 치매 노인의 통화 기록을 보호자에게 전하는 역할이다.

아래 집계 결과만 사용한다. 여기에 없는 사실을 추론하거나 덧붙이지 않는다.
진단하지 않는다. "치매가 악화되었다" 같은 의학적 판단은 절대 쓰지 않는다.
숫자가 늘거나 줄었다는 사실만 말하고 원인을 단정하지 않는다.

반드시 아래 JSON 만 출력한다.
{
  "summary": "기간 전체 요약. 3문장 이내. 존댓말.",
  "guardian_actions": ["보호자가 이번 주에 확인하면 좋을 일. 최대 3개"]
}"""


def _window(elder_id: str, since: str, until: str | None = None) -> dict:
    """한 구간의 숫자만 뽑는다. 이전 구간과 비교하려면 같은 방식으로 두 번 부른다."""
    upper = until or "9999-12-31"
    with db.connect() as conn:
        calls = [db._row(r) for r in conn.execute(
            "SELECT * FROM calls WHERE elder_id = ? AND status = 'ended' "
            "AND substr(started_at, 1, 10) >= ? AND substr(started_at, 1, 10) <= ?",
            (elder_id, since, upper),
        ).fetchall()]
        risks = conn.execute(
            "SELECT COUNT(*) FROM call_events e JOIN calls c ON c.call_id = e.call_id "
            "WHERE c.elder_id = ? AND e.event_type = 'risk' "
            "AND substr(c.started_at, 1, 10) >= ? AND substr(c.started_at, 1, 10) <= ?",
            (elder_id, since, upper),
        ).fetchone()[0]
        logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? "
            "AND taken_date >= ? AND taken_date <= ?",
            (elder_id, since, upper),
        ).fetchall()]
        reports = [db._row(r) for r in conn.execute(
            "SELECT r.* FROM reports r JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND substr(c.started_at, 1, 10) >= ? "
            "AND substr(c.started_at, 1, 10) <= ?",
            (elder_id, since, upper),
        ).fetchall()]
        elder_utterances = conn.execute(
            "SELECT COUNT(*) FROM utterances u JOIN calls c ON c.call_id = u.call_id "
            "WHERE c.elder_id = ? AND u.speaker = 'elder' "
            "AND substr(c.started_at, 1, 10) >= ? AND substr(c.started_at, 1, 10) <= ?",
            (elder_id, since, upper),
        ).fetchone()[0]

    repeat_total = sum(
        q.get("count", 0)
        for r in reports for q in (r.get("repeated_questions") or [])
    )
    observations = sum(
        len(items or [])
        for report_row in reports
        for domain, items in (report_row.get("care_summary") or {}).items()
        if domain != "meaningful_moments"
    )
    out = {
        "calls": len(calls),
        "elder_utterances": elder_utterances,
        "observations": observations,
        "seconds": sum(c["duration_sec"] or 0 for c in calls),
        "risks": risks,
        "med_confirmed": sum(1 for x in logs if x["status"] == "USER_CONFIRMED"),
        "med_unclear": sum(1 for x in logs if x["status"] != "USER_CONFIRMED"),
        "repeat_total": repeat_total,
    }
    out["rates"] = rate_metrics.window_rates(
        calls=out["calls"], elder_utterances=elder_utterances,
        observations=observations, repeats=repeat_total, risks=risks,
    )
    return out


def _merge_period_repeats(reports: list[dict]) -> list[dict]:
    """통화별 반복 질문을 기간 전체의 같은 질문으로 다시 묶는다."""
    groups: list[dict] = []
    for report_row in reports:
        for item in report_row.get("repeated_questions") or []:
            question = str(item.get("question") or "").strip()
            norm = _normalize(question)
            if not norm:
                continue
            matched = next((
                group for group in groups
                if SequenceMatcher(None, group["_norm"], norm).ratio() >= SIMILARITY
            ), None)
            if matched is None:
                matched = {
                    "_norm": norm, "question": question, "count": 0,
                    "call_count": 0, "utterance_ids": [],
                }
                groups.append(matched)
            matched["count"] += int(item.get("count") or 0)
            matched["call_count"] += 1
            matched["utterance_ids"].extend(item.get("utterance_ids") or [])
    return [
        {key: value for key, value in group.items() if key != "_norm"}
        for group in sorted(groups, key=lambda row: (-row["count"], -row["call_count"]))[:5]
    ]


LIFE_STAGE_RULES = (
    ("학창기", 15, 19, (r"학교", r"수업", r"교실", r"선생님", r"가방[^.!?]{0,12}(?:챙|어디)")),
    ("육아기", 30, 39, (r"애들[^.!?]{0,14}(?:밥|챙|학교)", r"아이[^.!?]{0,14}(?:밥|챙|학교)", r"자식[^.!?]{0,14}(?:밥|챙|학교)")),
    ("직장기", 45, 55, (r"회사", r"직장", r"출근", r"퇴근", r"회의", r"업무")),
    ("가족부양기", 55, 64, (r"가족[^.!?]{0,14}(?:먹여|책임|챙)", r"돈 벌", r"생활비")),
)

TOPIC_RULES = (
    ("재산·돈", (r"통장", r"돈", r"재산", r"계좌", r"빼돌리")),
    ("가족", (r"가족", r"아들", r"딸", r"손자", r"손녀", r"정훈", r"미영", r"대웅", r"유진", r"지영", r"성민")),
    ("고향·추억", (r"고향", r"옛날", r"냇가", r"어릴 때", r"그때")),
    ("일·학교", (r"회사", r"직장", r"출근", r"학교", r"수업", r"선생")),
    ("식사·약", (r"밥", r"식사", r"점심", r"아침", r"저녁", r"약", r"복용")),
    ("집·물건", (r"집", r"지갑", r"안경", r"리모컨", r"가방", r"열쇠")),
    ("건강", (r"아프", r"어지", r"넘어", r"잠", r"피", r"기운")),
)

RESPONSE_EMOTION_GROUPS = (
    ("의심·망상", {"distrust", "theft_delusion_signal"}),
    ("초조·분노", {"agitation", "anger", "verbal_aggression"}),
    ("불안·두려움", {"anxiety", "fear", "abandonment_fear"}),
    ("가라앉음", {"sadness", "apathy", "hopelessness", "loneliness"}),
    ("따뜻함", {"affection", "gratitude", "joy", "longing", "pride"}),
)
RESPONSE_CONTEXT_GROUPS = (
    ("회상·역할", (
        r"고향", r"옛날", r"그때", r"어릴 때", r"학교", r"수업",
        r"회사", r"출근", r"애들[^.!?]{0,12}(?:밥|학교|챙)",
    )),
    ("도움 요청", (
        r"어떻게 해야", r"도와", r"혼자[^.!?]{0,12}(?:힘들|못)",
        r"(?:일어나|걷|움직|입|씻)[^.!?]{0,12}(?:힘들|못)",
    )),
    ("확인·탐색", (
        r"어디", r"언제", r"몇 시", r"무슨 요일", r"먹었나",
        r"먹었던가", r"기억이 안", r"모르겠", r"못 찾", r"궁금",
    )),
)
RESPONSE_FALLBACK_GROUPS = tuple(label for label, _patterns in RESPONSE_CONTEXT_GROUPS)
RESPONSE_EMOTION_SIGNAL_NAMES = set().union(*(
    signals for _label, signals in RESPONSE_EMOTION_GROUPS
))

TENDENCY_CATEGORY_RULES = (
    ("사람·관계", (r"가족", r"아들", r"딸", r"손자", r"손녀", r"엄마", r"아빠", r"정훈", r"미영", r"대웅", r"유진", r"지영", r"성민")),
    ("시간·장소", (r"오늘", r"내일", r"어제", r"몇 시", r"요일", r"날짜", r"어디", r"집", r"고향", r"학교", r"회사", r"출근")),
    ("물건·재산", (r"통장", r"돈", r"재산", r"계좌", r"지갑", r"안경", r"리모컨", r"가방", r"열쇠", r"빼돌리")),
    ("몸 상태", (r"아프", r"어지", r"넘어", r"잠", r"피곤", r"기운", r"밥", r"식사", r"약", r"복용")),
)

TENDENCY_INWARD_SIGNALS = {
    "anxiety", "fear", "sadness", "apathy", "hopelessness",
}
TENDENCY_OUTWARD_SIGNALS = {
    "agitation", "verbal_aggression", "anger", "distrust",
}
TENDENCY_BURDEN_SIGNALS = {
    "anxiety", "fear", "sadness", "hopelessness", "worry_for_family", "guilt",
}
TENDENCY_ALL_SIGNALS = TENDENCY_INWARD_SIGNALS | TENDENCY_OUTWARD_SIGNALS
TENDENCY_MIN_CALLS = 5


def _topic_name(text: str) -> str:
    scores = [(sum(bool(re.search(pattern, text)) for pattern in patterns), label) for label, patterns in TOPIC_RULES]
    score, label = max(scores, default=(0, "일상"))
    return label if score else "일상"


def _emotion_name(text: str) -> str:
    """직접 정서 신호가 없는 발화도 대응 목적에 따라 빠짐없이 분류한다."""
    signal_names = _direct_response_signals(text)
    for label, names in RESPONSE_EMOTION_GROUPS:
        if signal_names & names:
            return label
    if re.search(r"(?:사랑|고맙|감사|반갑|행복|기쁘|좋았|그립|보고 싶|자랑|뿌듯)", text):
        return "따뜻함"
    if re.search(r"(?:슬프|서럽|외롭|아무것도 하기 싫|희망이 없|기운이 없)", text):
        return "가라앉음"
    for label, patterns in RESPONSE_CONTEXT_GROUPS:
        if any(re.search(pattern, text) for pattern in patterns):
            return label
    # 단순 안부처럼 별도 정서가 없는 말도 누락하지 않는다. 담당자는 이를
    # 정서가 있다고 오해하지 않고 평상시 상태를 확인하는 대화로 읽는다.
    return "확인·탐색"


def _direct_response_signals(text: str) -> set[str]:
    """대응 분류에 필요한 Tier A 직접 발화 신호만 규칙으로 확인한다."""
    found = set()
    for signal, spec in SIGNALS.items():
        if signal not in RESPONSE_EMOTION_SIGNAL_NAMES or spec.tier != "A" or not spec.patterns:
            continue
        if spec.negative_patterns and any(re.search(pattern, text) for pattern in spec.negative_patterns):
            continue
        if any(re.search(pattern, text) for pattern in spec.patterns):
            found.add(signal)
    return found


def _response_emotion(
    signals: Counter, warmth: Counter, fallback: Counter,
) -> tuple[str, int]:
    """정서 다섯 갈래를 우선하고, 없으면 대응 목적 세 갈래로 분류한다."""
    candidates = []
    for priority, (label, names) in enumerate(RESPONSE_EMOTION_GROUPS):
        source = warmth if label == "따뜻함" else signals
        count = sum(source.get(name, 0) for name in names)
        candidates.append((count, -priority, label))
    count, _priority, label = max(candidates)
    if count:
        return label, count
    observed_count, observed_label = max(
        ((fallback.get(name, 0), name) for name, _signals in RESPONSE_EMOTION_GROUPS),
        default=(0, "따뜻함"),
    )
    if observed_count:
        return observed_label, observed_count
    fallback_count, fallback_label = max(
        ((fallback.get(name, 0), name) for name in RESPONSE_FALLBACK_GROUPS),
        default=(0, "확인·탐색"),
    )
    return fallback_label, max(1, fallback_count)


def _has_behavior_agitation_signal(text: str) -> bool:
    """D6 Tier A 직접 발화 규칙이 함께 나타나는지만 확인한다."""
    for spec in SIGNALS.values():
        if spec.domain != "behavior_agitation" or spec.tier != "A" or not spec.patterns:
            continue
        if spec.negative_patterns and any(re.search(pattern, text) for pattern in spec.negative_patterns):
            continue
        if any(re.search(pattern, text) for pattern in spec.patterns):
            return True
    # 활용형 때문에 카탈로그의 엄격한 근거 패턴이 놓칠 수 있는 D6 표현을
    # 주제 차트의 각성도 보조 지표에서만 보완한다. 신호 저장·진단에는 쓰지 않는다.
    if re.search(r"(?:사람|아이|동물)(?:이|가)\s*보(?:이|여)", text):
        return True
    if re.search(r"(?:나가|가야|갈래|출근|수업)[^.!?]{0,16}(?:늦|빨리|지금)", text):
        return True
    return False


def _tendency_categories(text: str) -> list[str]:
    """한 발화를 7.5의 네 범주에 중복 배정한다."""
    return [
        label for label, patterns in TENDENCY_CATEGORY_RULES
        if any(re.search(pattern, text) for pattern in patterns)
    ]


def _tendency_summary(
    calls: list[dict], elder_rows: list[dict], topics: list[dict],
    signals_by_call: dict[str, Counter], period_start: date | None,
    period_end: date | None,
) -> dict:
    """7.5 경향 요약을 추측이나 LLM 없이 고정 규칙으로 만든다."""
    call_by_id = {row["call_id"]: row for row in calls}
    if period_start and period_end:
        observed_days = max(0, (period_end - period_start).days + 1)
    else:
        observed_dates = sorted({
            str(row.get("started_at") or "")[:10] for row in calls
            if str(row.get("started_at") or "")[:10]
        })
        observed_days = (
            (date.fromisoformat(observed_dates[-1]) - date.fromisoformat(observed_dates[0])).days + 1
            if observed_dates else 0
        )

    category_calls: dict[str, set[str]] = {
        label: set() for label, _patterns in TENDENCY_CATEGORY_RULES
    }
    utterance_counts: Counter = Counter()
    for row in elder_rows:
        call_id = row["call_id"]
        started = _started_datetime(call_by_id.get(call_id, {}).get("started_at"))
        if started:
            block = (started.hour // 2) * 2
            utterance_counts[block] += 1
        for label in _tendency_categories(row["transcript"]):
            category_calls[label].add(call_id)

    burden_rows = []
    for label, call_ids in category_calls.items():
        burden_call_ids = {
            call_id for call_id in call_ids
            if set(signals_by_call.get(call_id, {})) & TENDENCY_BURDEN_SIGNALS
        }
        burden_rows.append({
            "category": label,
            "calls": len(call_ids),
            "burden_calls": len(burden_call_ids),
            "burden_ratio": round(len(burden_call_ids) / max(1, len(call_ids)), 3),
            "eligible": len(call_ids) >= TENDENCY_MIN_CALLS,
        })
    burden_ranking = sorted(
        (row for row in burden_rows if row["eligible"] and row["burden_calls"] > 0),
        key=lambda row: (row["burden_ratio"], row["burden_calls"], row["calls"]),
        reverse=True,
    )[:3]

    inward_count = sum(
        count for counts in signals_by_call.values()
        for signal, count in counts.items() if signal in TENDENCY_INWARD_SIGNALS
    )
    outward_count = sum(
        count for counts in signals_by_call.values()
        for signal, count in counts.items() if signal in TENDENCY_OUTWARD_SIGNALS
    )

    eligible_topics = [row for row in topics if row["calls"] >= TENDENCY_MIN_CALLS]
    calming_resource = None
    if eligible_topics:
        ordered = sorted(eligible_topics, key=lambda row: (row["burden_ratio"], -row["average_minutes"]))
        lower_half = ordered[:max(1, (len(ordered) + 1) // 2)]
        selected = max(lower_half, key=lambda row: (row["average_minutes"], row["calls"]))
        calming_resource = {
            "topic": selected["topic"],
            "calls": selected["calls"],
            "average_minutes": selected["average_minutes"],
            "burden_ratio": selected["burden_ratio"],
        }

    signal_counts_by_block: Counter = Counter()
    for call_id, counts in signals_by_call.items():
        started = _started_datetime(call_by_id.get(call_id, {}).get("started_at"))
        if not started:
            continue
        signal_counts_by_block[(started.hour // 2) * 2] += sum(
            count for signal, count in counts.items() if signal in TENDENCY_ALL_SIGNALS
        )
    time_blocks = [{
        "start_hour": block,
        "end_hour": (block + 2) % 24,
        "label": f"{block:02d}:00~{(block + 2) % 24:02d}:00",
        "signals": signal_counts_by_block[block],
        "utterances": utterance_counts[block],
        "rate_per_100": round(signal_counts_by_block[block] / max(1, utterance_counts[block]) * 100, 1),
    } for block in range(0, 24, 2) if utterance_counts[block]]
    hardest_time = max(
        time_blocks,
        key=lambda row: (row["rate_per_100"], row["signals"], row["utterances"]),
        default=None,
    )

    return {
        "period_days": observed_days,
        "sufficient_period": observed_days >= 30,
        "minimum_calls": TENDENCY_MIN_CALLS,
        "total_calls": len(calls),
        "burden_categories": burden_rows,
        "burden_ranking": burden_ranking,
        "expression": {
            "inward_count": inward_count,
            "outward_count": outward_count,
        },
        "calming_resource": calming_resource,
        "hardest_time": hardest_time,
        "time_blocks": time_blocks,
    }


def _call_analytics(
    calls: list[dict], utterances: list[dict], birth_date: str | None,
    reports: list[dict] | None = None,
    period_start: date | None = None, period_end: date | None = None,
) -> dict:
    """통화 시작 시각과 실제 발화만으로 통화 리포트의 세 지표를 만든다."""
    call_by_id = {row["call_id"]: row for row in calls}
    elder_rows = [row for row in utterances if row.get("speaker") == "elder" and row.get("transcript") and row.get("call_id") in call_by_id]

    clusters: list[dict] = []
    for row in sorted(elder_rows, key=lambda item: (call_by_id[item["call_id"]].get("started_at") or "", item.get("seq") or 0)):
        norm = _normalize(row["transcript"])
        if not norm:
            continue
        target = next((cluster for cluster in clusters if SequenceMatcher(None, cluster["norm"], norm).ratio() >= SIMILARITY), None)
        if target is None:
            target = {"norm": norm, "question": row["transcript"], "occurrences": []}
            clusters.append(target)
        started = _started_datetime(call_by_id[row["call_id"]].get("started_at"))
        if started and (not target["occurrences"] or target["occurrences"][-1]["call_id"] != row["call_id"]):
            target["occurrences"].append({"call_id": row["call_id"], "at": started, "quote": row["transcript"]})

    intervals = []
    for cluster in clusters:
        for previous, current in zip(cluster["occurrences"], cluster["occurrences"][1:]):
            minutes = max(0, (current["at"] - previous["at"]).total_seconds() / 60)
            # 날짜가 바뀐 뒤의 재등장은 '답변 유지 시간'이 아니라 장기 반복
            # 패턴에 가깝다. 한 근무일 안에서 비교 가능한 12시간 이내만 쓴다.
            if minutes <= 12 * 60:
                intervals.append({"minutes": minutes, "at": current["at"], "question": cluster["question"]})
    intervals.sort(key=lambda row: row["at"])
    recent_intervals = intervals[-8:]
    current_pool = recent_intervals[-3:]
    baseline_pool = intervals[:-3] or intervals
    def median_minutes(rows: list[dict]) -> float | None:
        values = sorted(row["minutes"] for row in rows)
        if not values:
            return None
        middle = len(values) // 2
        value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        return round(value, 1)
    current_minutes = median_minutes(current_pool)
    baseline_minutes = median_minutes(baseline_pool)

    current_age = None
    if birth_date:
        try:
            born = date.fromisoformat(birth_date)
            current_age = date.today().year - born.year - ((date.today().month, date.today().day) < (born.month, born.day))
        except ValueError:
            pass
    life_stages = []
    for row in elder_rows:
        for label, age_from, age_to, patterns in LIFE_STAGE_RULES:
            if any(re.search(pattern, row["transcript"]) for pattern in patterns):
                life_stages.append({"label": label, "age_from": age_from, "age_to": age_to, "age": round((age_from + age_to) / 2), "quote": row["transcript"], "at": call_by_id[row["call_id"]].get("started_at")})
                break

    topic_map: dict[str, dict] = {}
    utterances_by_call: dict[str, list[dict]] = {}
    for row in elder_rows:
        utterances_by_call.setdefault(row["call_id"], []).append(row)
    ordered_elder_rows = sorted(
        elder_rows,
        key=lambda item: (
            call_by_id[item["call_id"]].get("started_at") or "",
            item.get("seq") or 0,
        ),
    )
    agitation_turns: set[tuple[str, int]] = set()
    direct_agitation_turns: set[tuple[str, int]] = set()
    signals_by_call: dict[str, Counter] = {
        call_id: Counter() for call_id in call_by_id
    }
    report_signals_by_call: dict[str, Counter] = {
        call_id: Counter() for call_id in call_by_id
    }
    warmth_by_call: dict[str, Counter] = {
        call_id: Counter() for call_id in call_by_id
    }
    for row in elder_rows:
        signals_by_call[row["call_id"]].update(_direct_response_signals(row["transcript"]))
    for call_id, rows in utterances_by_call.items():
        for row in rows:
            if _has_behavior_agitation_signal(row["transcript"]):
                key = (call_id, int(row.get("seq") or 0))
                agitation_turns.add(key)
                direct_agitation_turns.add(key)
    # 보고서의 care_summary는 서버가 직접 발화 근거를 검증한 결과다. 같은
    # 통화 전체가 아니라 근거 발화 주변(±1 어르신 턴)에만 D6 동반을 인정한다.
    for report_row in reports or []:
        call_id = report_row.get("call_id")
        rows = utterances_by_call.get(call_id, [])
        if call_id not in call_by_id:
            continue
        for moment in report_row.get("meaningful_moments") or []:
            category = str(moment.get("category") or "").strip()
            if category in RESPONSE_EMOTION_SIGNAL_NAMES:
                warmth_by_call[call_id][category] += 1
        for supplied_domain, items in (report_row.get("care_summary") or {}).items():
            if supplied_domain == "meaningful_moments":
                continue
            for item in items or []:
                signal = str(item.get("signal") or "").strip()
                if signal:
                    report_signals_by_call[call_id][signal] += 1
                if canonical_domain(item.get("signal"), supplied_domain) != "behavior_agitation":
                    continue
                utterance_id = item.get("utterance_id")
                matched = next((row for row in rows if row.get("utterance_id") == utterance_id), None)
                if matched:
                    agitation_turns.add((call_id, int(matched.get("seq") or 0)))
    for call_id, report_counts in report_signals_by_call.items():
        for signal, count in report_counts.items():
            signals_by_call[call_id][signal] = max(
                signals_by_call[call_id][signal], count,
            )
    for turn_index, row in enumerate(ordered_elder_rows):
        topic = _topic_name(row["transcript"])
        emotion = _emotion_name(row["transcript"])
        slot = topic_map.setdefault(topic, {
            "topic": topic,
            "call_ids": set(),
            "agitation_call_ids": set(),
            "burden_call_ids": set(),
            "agitation_turns": 0,
            "turns": 0,
            "seconds_by_call": {},
            "emotions": Counter(),
            "response_signals": Counter(),
            "warmth_signals": Counter(),
            "quotes": [],
            "turn_positions": [],
        })
        first_topic_turn_in_call = row["call_id"] not in slot["call_ids"]
        slot["call_ids"].add(row["call_id"])
        if set(signals_by_call.get(row["call_id"], {})) & TENDENCY_BURDEN_SIGNALS:
            slot["burden_call_ids"].add(row["call_id"])
        seq = int(row.get("seq") or 0)
        if (row["call_id"], seq) in direct_agitation_turns or any(
            call_id == row["call_id"] and abs(signal_seq - seq) <= 2
            for call_id, signal_seq in agitation_turns - direct_agitation_turns
        ):
            slot["agitation_call_ids"].add(row["call_id"])
            slot["agitation_turns"] += 1
        slot["turns"] += 1
        slot["seconds_by_call"].setdefault(
            row["call_id"], call_by_id[row["call_id"]].get("duration_sec") or 0
        )
        slot["emotions"][emotion] += 1
        if first_topic_turn_in_call:
            slot["response_signals"].update(signals_by_call.get(row["call_id"], {}))
            slot["warmth_signals"].update(warmth_by_call.get(row["call_id"], {}))
        slot["quotes"].append(row["transcript"])
        slot["turn_positions"].append(turn_index)
    topics = []
    for slot in topic_map.values():
        response_emotion, response_cases = _response_emotion(
            slot["response_signals"], slot["warmth_signals"], slot["emotions"],
        )
        call_count = len(slot["call_ids"])
        return_turns = [
            current - previous
            for previous, current in zip(slot["turn_positions"], slot["turn_positions"][1:])
        ]
        median_return_turns = median_minutes([
            {"minutes": value} for value in return_turns
        ])
        agitation_calls = len(slot["agitation_call_ids"])
        burden_calls = len(slot["burden_call_ids"])
        topics.append({
            "topic": slot["topic"],
            "calls": call_count,
            "turns": slot["turns"],
            "average_minutes": round(sum(slot["seconds_by_call"].values()) / max(1, call_count) / 60, 1),
            "engagement": round(slot["turns"] / max(1, call_count), 1),
            "emotion": response_emotion,
            "emotion_cases": response_cases,
            "quote": slot["quotes"][0],
            # 설계 문서 2.2/7.1: 저장 시각(초)이 아닌 어르신 발화 턴 간격을 쓴다.
            # 값이 클수록 같은 주제가 다시 등장하기까지 더 많은 발화가 지났다.
            "return_turns": median_return_turns,
            "return_observations": len(return_turns),
            # D6 직접 발화가 같은 통화 안에 동반된 비율. 진단 점수가 아니다.
            "agitation_ratio": round(slot["agitation_turns"] / max(1, slot["turns"]), 3),
            "agitation_turns": slot["agitation_turns"],
            "agitation_calls": agitation_calls,
            "burden_calls": burden_calls,
            "burden_ratio": round(burden_calls / max(1, call_count), 3),
        })
    topics.sort(key=lambda row: (row["calls"], row["turns"]), reverse=True)

    tendency = _tendency_summary(
        calls, elder_rows, topics, signals_by_call, period_start, period_end,
    )
    return {
        "response_retention": {"current_minutes": current_minutes, "baseline_minutes": baseline_minutes, "change_minutes": round(current_minutes - baseline_minutes, 1) if current_minutes is not None and baseline_minutes is not None else None, "samples": [{"minutes": round(row["minutes"], 1), "label": row["at"].strftime("%m/%d %H:%M"), "question": row["question"]} for row in recent_intervals], "basis": "같은 발화 군집이 서로 다른 통화에서 다시 등장한 통화 시작 시각 간격"},
        "time_regression": {"current_age": current_age, "stages": life_stages[-12:], "dominant_stage": Counter(row["label"] for row in life_stages).most_common(1)[0][0] if life_stages else None},
        "emotion_topics": topics[:8],
        "tendency_summary": tendency,
    }


DAILY_HEART_PRIORITY = {
    name: index for index, name in enumerate(
        ["apology", "affection", "worry_for_family", "longing", "gratitude",
         "pride", "wish_for_family", "joy", "life_story", "preference"]
    )
}


def _daily_analyses(
    calls: list[dict], reports: list[dict], risks: list[dict],
    start: date, end: date,
) -> list[dict]:
    """Combine many calls into one evidence-backed caregiver report per day."""
    reports_by_call = {
        row["call_id"]: row for row in reports if row.get("call_id")
    }
    risks_by_call: dict[str, list[dict]] = {}
    for event in risks:
        risks_by_call.setdefault(event["call_id"], []).append(event)

    calls_by_day: dict[str, list[dict]] = {}
    for call in calls:
        day = str(call.get("started_at") or "")[:10]
        if day:
            calls_by_day.setdefault(day, []).append(call)

    rows = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        day_calls = calls_by_day.get(key, [])
        day_reports = [
            reports_by_call[call["call_id"]]
            for call in day_calls if call["call_id"] in reports_by_call
        ]
        day_risks = [
            event for call in day_calls
            for event in risks_by_call.get(call["call_id"], [])
        ]

        observation_groups: dict[tuple[str, str], dict] = {}
        for report_row in day_reports:
            for supplied_domain, items in (report_row.get("care_summary") or {}).items():
                if supplied_domain == "meaningful_moments":
                    continue
                for item in items or []:
                    signal = str(item.get("signal") or "").strip()
                    domain = canonical_domain(signal, supplied_domain)
                    label = str(item.get("label") or CARE_SIGNAL_LABEL.get(signal, signal)).strip()
                    if not signal or not label or domain not in CARE_DOMAIN_LABEL:
                        continue
                    group = observation_groups.setdefault((domain, signal), {
                        "domain": domain,
                        "domain_label": CARE_DOMAIN_LABEL.get(domain, domain),
                        "signal": signal,
                        "label": label,
                        "count": 0,
                        "evidence": [],
                    })
                    group["count"] += 1
                    evidence = str(item.get("evidence") or "").strip()
                    if evidence and evidence not in group["evidence"]:
                        group["evidence"].append(evidence)

        observations = sorted(
            observation_groups.values(), key=lambda item: (-item["count"], item["label"])
        )
        for item in observations:
            item["evidence"] = item["evidence"][:3]

        repeats = _merge_period_repeats(day_reports)
        actions = []
        for item in observations:
            action = RHYTHM_SIGNAL_ACTIONS.get(item["signal"])
            if action and action not in actions:
                actions.append(action)
        for report_row in day_reports:
            for action in report_row.get("guardian_actions") or []:
                if action and action not in actions:
                    actions.append(action)
        if day_risks:
            urgent = "안전 신호의 발생 시각과 현재 상태를 먼저 직접 확인해 주세요."
            if urgent not in actions:
                actions.insert(0, urgent)

        moments = [
            moment for report_row in day_reports
            for moment in (report_row.get("meaningful_moments") or [])
            if moment.get("evidence")
        ]
        strongest = min(
            moments,
            key=lambda item: DAILY_HEART_PRIORITY.get(item.get("category"), 99),
            default=None,
        )
        heart = None
        if strongest:
            quote = _short_quote(
                strongest.get("evidence", ""), strongest.get("category")
            )
            heart = {
                "label": strongest.get("label") or MEANING_LABEL.get(
                    strongest.get("category"), "가족에게 전할 말씀"
                ),
                "quote": quote,
                "at": strongest.get("at"),
                "message": (
                    f"어르신께서 직접 하신 말씀을 "
                    f"{strongest.get('label') or '마음 표현'}으로 기록했습니다."
                ),
                "policy": "실제 발화에 드러난 표현만 전하며 말하지 않은 감정은 추측하지 않습니다.",
            }

        rows.append({
            "date": key,
            "calls": len(day_calls),
            "seconds": sum(call.get("duration_sec") or 0 for call in day_calls),
            "observation_count": sum(item["count"] for item in observations),
            "observations": observations[:8],
            "repeated_total": sum(item.get("count") or 0 for item in repeats),
            "repeated_phrases": repeats[:4],
            "risk_count": len(day_risks),
            "risks": [
                {
                    "event_id": event["event_id"],
                    "call_id": event["call_id"],
                    "at": event.get("started_at"),
                    "acknowledged": bool(event.get("acknowledged")),
                    **(event.get("payload") or {}),
                }
                for event in day_risks
            ],
            "guardian_actions": actions[:5],
            "heart_report": heart,
        })
        cursor += timedelta(days=1)
    return rows


def _time_analyses(
    calls: list[dict], reports: list[dict], risks: list[dict], selected_day: date,
) -> list[dict]:
    """Build the same evidence/action report in two-hour blocks for one day."""
    reports_by_call = {
        row["call_id"]: row for row in reports if row.get("call_id")
    }
    rows = []
    for start_hour in range(0, 24, 2):
        block_calls = []
        for call in calls:
            started = _started_datetime(call.get("started_at"))
            if started and start_hour <= started.hour < start_hour + 2:
                block_calls.append(call)
        if block_calls:
            call_ids = {call["call_id"] for call in block_calls}
            block_reports = [
                reports_by_call[call_id] for call_id in call_ids
                if call_id in reports_by_call
            ]
            block_risks = [event for event in risks if event.get("call_id") in call_ids]
            row = _daily_analyses(
                block_calls, block_reports, block_risks, selected_day, selected_day
            )[0]
        else:
            # 빈 시간도 누락하지 않는다. 화면은 이를 '통화 없음'으로 표시하며,
            # 관찰이나 감정을 임의로 채우지 않는다.
            row = {
                "date": selected_day.isoformat(),
                "analysis_title": "이 시간에는 통화가 없었습니다",
                "calls": 0,
                "seconds": 0,
                "observation_count": 0,
                "observations": [],
                "repeated_total": 0,
                "repeated_phrases": [],
                "risk_count": 0,
                "risks": [],
                "guardian_actions": [],
                "heart_report": None,
            }
        row.update({
            "key": f"{selected_day.isoformat()}-{start_hour:02d}",
            "time_label": f"{start_hour:02d}:00~{start_hour + 2:02d}:00",
            "start_hour": start_hour,
            "has_calls": bool(block_calls),
        })
        rows.append(row)
    return rows


def _period_dates(
    days: int, start_date: str | None = None, end_date: str | None = None,
) -> tuple[date, date, int]:
    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("start_date와 end_date를 함께 입력해야 합니다.")
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        span = (end - start).days + 1
        if span > 366:
            raise ValueError("조회 기간은 최대 366일입니다.")
        return start, end, span
    end = date.today()
    return end - timedelta(days=days - 1), end, days


def _started_datetime(value: str | None) -> datetime | None:
    """Return a timezone-aware-enough datetime for locally stored call times."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _report_signal_counts(report_row: dict | None) -> Counter:
    counts: Counter = Counter()
    for domain, items in ((report_row or {}).get("care_summary") or {}).items():
        if domain == "meaningful_moments":
            continue
        for item in items or []:
            signal = str(item.get("signal") or "").strip()
            if signal:
                counts[signal] += 1
    return counts


def _rhythm_window_stats(
    calls: list[dict], reports_by_call: dict[str, dict], start: date, end: date,
) -> dict:
    selected = []
    for call in calls:
        started = _started_datetime(call.get("started_at"))
        if started and start <= started.date() <= end:
            selected.append(call)
    signals: Counter = Counter()
    repeat_total = 0
    for call in selected:
        report_row = reports_by_call.get(call["call_id"], {})
        signals.update(_report_signal_counts(report_row))
        repeat_total += sum(
            int(item.get("count") or 0)
            for item in report_row.get("repeated_questions") or []
        )
    observation_total = sum(signals.values())
    return {
        "calls": len(selected),
        "repeat_total": repeat_total,
        "repeat_per_call": rate_metrics.per(repeat_total, len(selected), 1),
        "observation_per_call": rate_metrics.per(observation_total, len(selected), 1),
        "loneliness": signals["loneliness"],
        "loneliness_per_call": rate_metrics.per(signals["loneliness"], len(selected), 1),
        "medication_uncertain": signals["medication_uncertain"],
        "medication_uncertain_per_call": rate_metrics.per(signals["medication_uncertain"], len(selected), 1),
        "time_confusion": signals["time_confusion"],
        "time_confusion_per_call": rate_metrics.per(signals["time_confusion"], len(selected), 1),
    }


def _rhythm_change(label: str, current: float | None, previous: float | None,
                   current_calls: int, previous_calls: int) -> dict:
    row = rate_metrics.compare(
        current, previous, label=label, unit="회/통화",
        current_sample=current_calls, previous_sample=previous_calls,
        minimum_sample=rate_metrics.MIN_CALLS_FOR_COMPARISON,
    )
    return {"key": label, "description": row.pop("text"), **row}


def _rhythm_analysis(
    period_calls: list[dict], period_reports: list[dict],
    comparison_calls: list[dict], comparison_reports: list[dict],
    *, today: date | None = None, period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    """Aggregate call time and observed speech without inferring a diagnosis.

    Calls are grouped into fixed two-hour blocks.  Emotional wording is only
    shown when the corresponding signal exists in a report backed by an elder
    utterance; a busy time block alone is never called a lonely time block.
    """
    today = today or date.today()
    reports_by_call = {
        row["call_id"]: row for row in period_reports if row.get("call_id")
    }
    block_calls: Counter = Counter()
    block_signals: dict[int, Counter] = {
        hour: Counter() for hour in range(0, 24, 2)
    }
    block_evidence: dict[int, list[str]] = {
        hour: [] for hour in range(0, 24, 2)
    }
    observed_days = set()
    weekday_block_calls: Counter = Counter()

    for call in period_calls:
        started = _started_datetime(call.get("started_at"))
        if not started:
            continue
        block = (started.hour // 2) * 2
        block_calls[block] += 1
        weekday_block_calls[(started.weekday(), block)] += 1
        observed_days.add(started.date().isoformat())
        report_row = reports_by_call.get(call["call_id"], {})
        block_signals[block].update(_report_signal_counts(report_row))
        for items in (report_row.get("care_summary") or {}).values():
            for item in items or []:
                evidence = str(item.get("evidence") or "").strip()
                if evidence and evidence not in block_evidence[block]:
                    block_evidence[block].append(evidence)

    total_calls = sum(block_calls.values())
    blocks = []
    for start_hour in range(0, 24, 2):
        calls = block_calls[start_hour]
        blocks.append({
            "start_hour": start_hour,
            "end_hour": start_hour + 2,
            "label": f"{start_hour:02d}:00~{start_hour + 2:02d}:00",
            "calls": calls,
            "share_percent": round(calls / total_calls * 100) if total_calls else 0,
            "observation_count": sum(block_signals[start_hour].values()),
        })

    valid_started = [
        started for call in period_calls
        if (started := _started_datetime(call.get("started_at")))
    ]
    heatmap_start = period_start or (
        min(started.date() for started in valid_started) if valid_started else today
    )
    heatmap_end = period_end or (
        max(started.date() for started in valid_started) if valid_started else today
    )
    if heatmap_start > heatmap_end:
        heatmap_start, heatmap_end = heatmap_end, heatmap_start
    weekday_days: Counter = Counter()
    cursor = heatmap_start
    while cursor <= heatmap_end:
        weekday_days[cursor.weekday()] += 1
        cursor += timedelta(days=1)
    weekday_labels = ("월", "화", "수", "목", "금", "토", "일")
    heatmap_cells = []
    for weekday in range(7):
        for start_hour in range(0, 24, 2):
            calls = weekday_block_calls[(weekday, start_hour)]
            denominator = weekday_days[weekday]
            heatmap_cells.append({
                "weekday": weekday,
                "weekday_label": weekday_labels[weekday],
                "start_hour": start_hour,
                "end_hour": start_hour + 2,
                "calls": calls,
                "days_observed": denominator,
                "average_per_day": round(calls / denominator, 2) if denominator else 0,
            })
    max_heatmap_average = max(
        (cell["average_per_day"] for cell in heatmap_cells), default=0
    )

    peak = max(blocks, key=lambda row: row["calls"], default=blocks[0])
    peak_start = peak["start_hour"]
    top_peak_signals = [
        {
            "signal": signal,
            "label": CARE_SIGNAL_LABEL.get(signal, signal),
            "count": count,
        }
        for signal, count in block_signals[peak_start].most_common(3)
    ]
    loneliness_count = block_signals[peak_start]["loneliness"]
    if loneliness_count:
        peak_summary = (
            f"통화가 가장 많이 몰린 시간대이며 외로움 관련 표현이 "
            f"{loneliness_count}회 함께 관찰되었습니다."
        )
        peak_action = RHYTHM_SIGNAL_ACTIONS["loneliness"]
    elif top_peak_signals:
        first = top_peak_signals[0]
        peak_summary = (
            f"통화가 가장 많이 몰렸고 {first['label']} 표현이 "
            f"{first['count']}회 함께 관찰되었습니다."
        )
        peak_action = RHYTHM_SIGNAL_ACTIONS.get(
            first["signal"], "이 시간대 전후의 통화 내용을 함께 살펴봐 주세요."
        )
    else:
        peak_summary = "통화가 가장 많이 몰린 시간대입니다. 함께 분류된 특이 발화는 없었습니다."
        peak_action = "통화가 몰리기 전에 짧은 안부 연락을 시도해 보세요."

    signal_blocks: dict[str, Counter] = {}
    for block, counts in block_signals.items():
        for signal, count in counts.items():
            signal_blocks.setdefault(signal, Counter())[block] += count
    patterns = []
    for signal in RHYTHM_SIGNAL_ACTIONS:
        counts = signal_blocks.get(signal)
        if not counts:
            continue
        block, count = counts.most_common(1)[0]
        patterns.append({
            "signal": signal,
            "label": CARE_SIGNAL_LABEL.get(signal, signal),
            "time_label": f"{block:02d}:00~{block + 2:02d}:00",
            "count": count,
            "description": (
                f"{CARE_SIGNAL_LABEL.get(signal, signal)} 표현이 이 시간대에 "
                f"가장 많이 관찰되었습니다."
            ),
            "guardian_action": RHYTHM_SIGNAL_ACTIONS[signal],
        })
    patterns.sort(key=lambda row: row["count"], reverse=True)

    comparison_by_call = {
        row["call_id"]: row for row in comparison_reports if row.get("call_id")
    }
    current_start = today - timedelta(days=6)
    previous_start = today - timedelta(days=13)
    previous_end = today - timedelta(days=7)
    current = _rhythm_window_stats(
        comparison_calls, comparison_by_call, current_start, today
    )
    previous = _rhythm_window_stats(
        comparison_calls, comparison_by_call, previous_start, previous_end
    )
    comparisons = [
        _rhythm_change(
            "반복 질문", current["repeat_per_call"], previous["repeat_per_call"],
            current["calls"], previous["calls"],
        ),
        _rhythm_change(
            "외로움 표현", current["loneliness_per_call"], previous["loneliness_per_call"],
            current["calls"], previous["calls"],
        ),
        _rhythm_change(
            "복약 혼동", current["medication_uncertain_per_call"],
            previous["medication_uncertain_per_call"],
            current["calls"], previous["calls"],
        ),
    ]

    return {
        "name": "생활 리듬",
        "ready": len(observed_days) >= 7 and total_calls >= 30,
        "minimum_days": 7,
        "days_observed": len(observed_days),
        "calls_analyzed": total_calls,
        "basis": "통화 시작 시각과 실제 발화에서 검증된 관찰 신호",
        "time_blocks": blocks,
        "weekday_time_heatmap": {
            "period_start": heatmap_start.isoformat(),
            "period_end": heatmap_end.isoformat(),
            "days": (heatmap_end - heatmap_start).days + 1,
            "weekdays": [
                {
                    "weekday": weekday,
                    "label": weekday_labels[weekday],
                    "days_observed": weekday_days[weekday],
                }
                for weekday in range(7)
            ],
            "time_blocks": [
                {
                    "start_hour": start_hour,
                    "end_hour": start_hour + 2,
                    "label": f"{start_hour:02d}~{start_hour + 2:02d}",
                }
                for start_hour in range(0, 24, 2)
            ],
            "cells": heatmap_cells,
            "max_average_per_day": max_heatmap_average,
        },
        "peak_window": {
            **peak,
            "summary": peak_summary,
            "top_signals": top_peak_signals,
            "evidence_examples": block_evidence[peak_start][:3],
            "guardian_action": peak_action,
        },
        "patterns": patterns[:4],
        "week_comparison": comparisons,
    }


def period(
    elder_id: str = "elder_001", days: int = 7, narrative: bool = True,
    start_date: str | None = None, end_date: str | None = None,
) -> dict:
    """며칠치를 모아서 본다.

    통화 하나짜리 리포트로는 변화가 보이지 않는다.
    반복 질문이 늘었는지, 복약을 얼마나 챙기셨는지는 기간으로 봐야 한다.
    같은 길이의 직전 구간과 비교해 늘고 줄었다는 사실만 전한다.
    """
    period_start, period_end, days = _period_dates(days, start_date, end_date)
    since = period_start.isoformat()
    until = period_end.isoformat()
    prev_until_date = period_start - timedelta(days=1)
    prev_since_date = prev_until_date - timedelta(days=days - 1)
    prev_since = prev_since_date.isoformat()
    prev_until = prev_until_date.isoformat()
    rhythm_since = min(
        since, (period_end - timedelta(days=29)).isoformat()
    )

    with db.connect() as conn:
        calls = [db._row(r) for r in conn.execute(
            "SELECT * FROM calls WHERE elder_id = ? AND status = 'ended' "
            "AND substr(started_at, 1, 10) >= ? "
            "AND substr(started_at, 1, 10) <= ? ORDER BY started_at",
            (elder_id, since, until),
        ).fetchall()]
        risks = [db._row(r) for r in conn.execute(
            "SELECT e.*, c.started_at FROM call_events e "
            "JOIN calls c ON c.call_id = e.call_id "
            "WHERE c.elder_id = ? AND e.event_type = 'risk' "
            "AND substr(c.started_at, 1, 10) >= ? "
            "AND substr(c.started_at, 1, 10) <= ? ORDER BY c.started_at DESC",
            (elder_id, since, until),
        ).fetchall()]
        med_logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? "
            "AND taken_date >= ? AND taken_date <= ?",
            (elder_id, since, until),
        ).fetchall()]
        previous_med_logs = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_logs WHERE elder_id = ? "
            "AND taken_date >= ? AND taken_date <= ?",
            (elder_id, prev_since, prev_until),
        ).fetchall()]
        medications = [db._row(r) for r in conn.execute(
            "SELECT * FROM medications WHERE elder_id = ? AND active = 1 "
            "ORDER BY scheduled_time, medication_name",
            (elder_id,),
        ).fetchall()]
        medication_reviews = [db._row(r) for r in conn.execute(
            "SELECT * FROM medication_reviews WHERE elder_id = ? "
            "AND review_date <= ? ORDER BY review_date DESC, review_id DESC",
            (elder_id, until),
        ).fetchall()]
        medication_signal_links = [db._row(r) for r in conn.execute(
            "SELECT l.* FROM medication_signal_links l JOIN medications m "
            "ON m.schedule_id = l.schedule_id WHERE m.elder_id = ? AND m.active = 1",
            (elder_id,),
        ).fetchall()]
        reports = [db._row(r) for r in conn.execute(
            "SELECT r.* FROM reports r JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND substr(c.started_at, 1, 10) >= ? "
            "AND substr(c.started_at, 1, 10) <= ?",
            (elder_id, since, until),
        ).fetchall()]
        rhythm_calls = [db._row(r) for r in conn.execute(
            "SELECT * FROM calls WHERE elder_id = ? AND status = 'ended' "
            "AND substr(started_at, 1, 10) >= ? "
            "AND substr(started_at, 1, 10) <= ? ORDER BY started_at",
            (elder_id, rhythm_since, until),
        ).fetchall()]
        rhythm_reports = [db._row(r) for r in conn.execute(
            "SELECT r.* FROM reports r JOIN calls c ON c.call_id = r.call_id "
            "WHERE c.elder_id = ? AND substr(c.started_at, 1, 10) >= ? "
            "AND substr(c.started_at, 1, 10) <= ?",
            (elder_id, rhythm_since, until),
        ).fetchall()]
        analytics_utterances = [db._row(r) for r in conn.execute(
            "SELECT u.* FROM utterances u JOIN calls c ON c.call_id = u.call_id "
            "WHERE c.elder_id = ? AND c.status = 'ended' "
            "AND substr(c.started_at, 1, 10) >= ? AND substr(c.started_at, 1, 10) <= ? "
            "ORDER BY c.started_at, u.seq",
            (elder_id, rhythm_since, until),
        ).fetchall()]
        elder_profile = db._row(conn.execute(
            "SELECT birth_date FROM elder_profiles WHERE elder_id = ?", (elder_id,)
        ).fetchone())

    by_day: dict[str, dict] = {}
    for c in calls:
        day = (c["started_at"] or "")[:10]
        slot = by_day.setdefault(day, {"date": day, "calls": 0, "seconds": 0})
        slot["calls"] += 1
        slot["seconds"] += c["duration_sec"] or 0

    top_repeats = _merge_period_repeats(reports)

    medication_analysis = medication_metrics.build(
        medications=medications,
        logs=med_logs,
        previous_logs=previous_med_logs,
        reviews=medication_reviews,
        links=medication_signal_links,
        reports=reports,
        period_start=period_start,
        period_end=period_end,
    )
    confirmed = medication_analysis["confirmed"]
    unclear = medication_analysis["needs_check"]
    medication_rows = medication_analysis["by_medication"]
    medication_analysis["vulnerable"] = next((
        row for row in medication_rows
        if row["UNCLEAR"] + row["REFUSED"] + row["DUPLICATE_SUSPECTED"]
    ), None)
    care_counts = {key: 0 for key in CARE_DOMAIN_LABEL}
    for report_row in reports:
        for supplied_domain, items in (report_row.get("care_summary") or {}).items():
            if supplied_domain == "meaningful_moments":
                continue
            for item in items or []:
                domain = canonical_domain(item.get("signal"), supplied_domain)
                if domain in care_counts:
                    care_counts[domain] += 1
    meaningful_total = sum(
        len(r.get("meaningful_moments") or []) for r in reports
    )
    rhythm = _rhythm_analysis(
        calls, reports, rhythm_calls, rhythm_reports, today=period_end,
        period_start=period_start, period_end=period_end,
    )
    daily_reports = _daily_analyses(
        calls, reports, risks, period_start, period_end
    )
    time_reports = (
        _time_analyses(calls, reports, risks, period_start)
        if days == 1 else []
    )
    call_analytics = _call_analytics(
        rhythm_calls, analytics_utterances, elder_profile.get("birth_date"),
        rhythm_reports, date.fromisoformat(rhythm_since), period_end,
    )

    facts = {
        "기간_일수": days,
        "통화_횟수": len(calls),
        "총_통화시간_초": sum(c["duration_sec"] or 0 for c in calls),
        "반복질문_상위": [{"질문": r["question"], "횟수": r["count"]} for r in top_repeats],
        "복약_확인됨": confirmed,
        "복약_불확실": unclear,
        "위험_건수": len(risks),
    }

    story = {"summary": "", "guardian_actions": []}
    if narrative and calls:
        story = _narrative_period(facts)

    this_w = _window(elder_id, since, until)
    prev_w = _window(elder_id, prev_since, prev_until)
    changes = [
        rate_metrics.compare(
            this_w["rates"]["observation_per_100_utterances"],
            prev_w["rates"]["observation_per_100_utterances"],
            label="관찰 발화 빈도", unit="회/발화 100건",
            current_sample=this_w["elder_utterances"], previous_sample=prev_w["elder_utterances"],
            minimum_sample=rate_metrics.MIN_UTTERANCES_FOR_COMPARISON,
        ),
        rate_metrics.compare(
            this_w["rates"]["repeat_per_call"], prev_w["rates"]["repeat_per_call"],
            label="되묻기 빈도", unit="회/통화",
            current_sample=this_w["calls"], previous_sample=prev_w["calls"],
            minimum_sample=rate_metrics.MIN_CALLS_FOR_COMPARISON,
        ),
        rate_metrics.compare(
            this_w["rates"]["risk_per_100_calls"], prev_w["rates"]["risk_per_100_calls"],
            label="안전 신호 빈도", unit="회/통화 100건",
            current_sample=this_w["calls"], previous_sample=prev_w["calls"],
            minimum_sample=rate_metrics.MIN_CALLS_FOR_COMPARISON,
        ),
    ]

    return {
        "days": days,
        "since": since,
        "until": until,
        "changes": changes,
        "normalized_rates": this_w["rates"],
        "repeat_total": this_w["repeat_total"],
        "calls": len(calls),
        "total_seconds": facts["총_통화시간_초"],
        "by_day": [
            {"date": row["date"], "calls": row["calls"], "seconds": row["seconds"]}
            for row in daily_reports
        ],
        "daily_reports": daily_reports,
        "time_reports": time_reports,
        "call_analytics": call_analytics,
        "top_repeats": top_repeats,
        "care_counts": care_counts,
        "meaningful_total": meaningful_total,
        "rhythm": rhythm,
        "medication": medication_analysis,
        "risks": [
            {
                "event_id": r["event_id"],
                "call_id": r["call_id"],
                "at": r["started_at"],
                "acknowledged": bool(r["acknowledged"]),
                **(r.get("payload") or {}),
            }
            for r in risks
        ],
        "summary": story.get("summary", ""),
        "guardian_actions": story.get("guardian_actions", []),
    }


def _narrative_period(facts: dict) -> dict:
    out = llm.call_schema(
        [
            {"role": "system", "content": WEEKLY_SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        schemas.PeriodNarrative,
        temperature=0.3,
        model=llm.REPORT_MODEL,
    )
    return out.model_dump() if out else {"summary": "", "guardian_actions": []}


def acknowledge(event_id: int) -> dict:
    with db.connect() as conn:
        conn.execute(
            "UPDATE call_events SET acknowledged = 1, acknowledged_at = CURRENT_TIMESTAMP WHERE event_id = ?", (event_id,)
        )
        row = conn.execute("SELECT acknowledged_at FROM call_events WHERE event_id = ?", (event_id,)).fetchone()
        conn.commit()
    return {"event_id": event_id, "acknowledged": True, "acknowledged_at": row["acknowledged_at"] if row else None}
