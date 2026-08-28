"""통화 리포트가 실제 발화 근거와 보호자 행동을 지키는지 검사한다."""


def validate_report(data: dict, expected: dict, elder_text: str) -> list[str]:
    failures: list[str] = []
    care = data.get("care_summary") or {}
    observations = [item for items in care.values() for item in (items or [])]
    domains = {domain for domain, items in care.items() if items}
    signals = {item.get("signal") for item in observations}
    risks = {item.get("type") for item in (data.get("risk_summary") or [])}

    for domain in expected.get("domains") or []:
        if domain not in domains:
            failures.append(f"관찰 영역 누락: {domain}")
    for signal in expected.get("signals") or []:
        if signal not in signals:
            failures.append(f"관찰 신호 누락: {signal}")
    for risk in expected.get("risks") or []:
        if risk not in risks:
            failures.append(f"안전 신호 누락: {risk}")

    for item in observations:
        evidence = str(item.get("evidence") or "").strip()
        if evidence and evidence not in elder_text:
            failures.append(f"원문에 없는 관찰 근거: {evidence}")

    risk_text = " ".join(str(item.get("evidence") or "") for item in (data.get("risk_summary") or []))
    for fragment in expected.get("evidence_any") or []:
        if fragment not in risk_text and fragment not in elder_text:
            failures.append(f"안전 근거 누락: {fragment}")

    actions = " ".join(data.get("guardian_actions") or [])
    required_actions = expected.get("action_any") or []
    if required_actions and not any(fragment in actions for fragment in required_actions):
        failures.append("보호자 확인 행동 누락")
    return failures
