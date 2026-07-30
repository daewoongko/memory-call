"""LLM 출력 형태 정의.

Azure OpenAI 의 Structured Outputs 를 쓰지 않기로 했으므로, 스키마 강제는
받은 뒤에 한다. llm.call_schema() 가 여기 정의된 모델로 검증하고,
틀리면 오류를 붙여 한 번 더 묻는다.

형태만 본다. 내용이 사실인지는 여기서 판단하지 않는다.
근거가 실제로 존재하는지 확인하는 것은 report._verify_evidence() 의 일이다.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["low", "medium", "high"]

# 모델이 한글이나 다른 표기로 낼 때를 대비한 대응표.
_SEVERITY_ALIAS = {
    "낮음": "low", "보통": "medium", "중간": "medium", "높음": "high",
    "경미": "low", "주의": "medium", "긴급": "high", "위험": "high",
    "l": "low", "m": "medium", "h": "high",
    "none": "low", "normal": "low", "warning": "medium", "critical": "high",
}


class Observation(BaseModel):
    """보호자가 알아야 할 관찰 한 문장.

    evidence_ids 는 이 문장이 어느 기록에서 나왔는지를 가리킨다.
    여기서는 "문자열 배열인가"만 본다. 그 id 가 DB 에 실제로 있는지는
    report._verify_evidence() 가 확인하고, 없으면 이 관찰을 통째로 버린다.
    """

    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Severity = "low"

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v):
        """표기가 어긋나면 low 로 떨어뜨린다.

        관찰 하나의 등급 표기가 틀렸다고 리포트 전체를 버리는 것은 과하다.
        모르면 낮게 잡는다. 없는 긴급함을 만들어내지 않기 위해서다.
        """
        if not isinstance(v, str):
            return "low"
        key = v.strip().lower()
        if key in ("low", "medium", "high"):
            return key
        return _SEVERITY_ALIAS.get(key, "low")


class CallNarrative(BaseModel):
    """통화 하나에 대한 리포트 문장."""

    summary: str = ""
    observations: list[Observation] = Field(default_factory=list)
    guardian_actions: list[str] = Field(default_factory=list)


class PeriodNarrative(BaseModel):
    """기간 요약. 관찰 단위가 아니라 추세만 말한다."""

    summary: str = ""
    guardian_actions: list[str] = Field(default_factory=list)
