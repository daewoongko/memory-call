"""
LLM 호출 단일 창구.

OpenAI와 Gemini의 OpenAI 호환 엔드포인트를 같은 코드 경로로 부른다.
.env의 엔드포인트·키·모델만 바꾸면 나머지 코드는 손대지 않는다.

공급자별 분당 요청 수 제한을 넘으면 429가 발생할 수 있다.
call_json()이 지수 백오프로 알아서 재시도한다.
"""

import json
import os
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
GENERIC_API_KEY = os.getenv("LLM_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
API_KEY = (
    OPENAI_API_KEY or GENERIC_API_KEY
    if "api.openai.com" in BASE_URL.lower()
    else GENERIC_API_KEY
)
MODEL = os.getenv("LLM_MODEL", "gpt-5.6-terra")
# 리포트·페르소나는 통화당 한 번만 돌고 지연이 상관없다. 중첩 배열과 id 인용을
# 시켜야 하므로 대화용 경량 모델보다 큰 모델을 쓴다. 비워 두면 LLM_MODEL 을 쓴다.
REPORT_MODEL = os.getenv("LLM_REPORT_MODEL", "") or MODEL
FAST_MODEL = os.getenv("LLM_FAST_MODEL", "") or MODEL
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")
FAST_MAX_TOKENS = max(160, int(os.getenv("LLM_FAST_MAX_TOKENS", "256")))
FAST_REASONING_EFFORT = os.getenv("LLM_FAST_REASONING_EFFORT", "").strip()
LLM_REQUEST_TIMEOUT_SECONDS = max(
    5.0, float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30"))
)
MAX_RETRIES = max(1, int(os.getenv("LLM_MAX_RETRIES", "3")))
FAST_WARM_TTL_SECONDS = max(
    30.0, float(os.getenv("LLM_FAST_WARM_TTL_SECONDS", "300"))
)
_fast_warm_lock = threading.Lock()
_fast_warmed_at = 0.0

if not API_KEY:
    sys.exit(
        "LLM API 키가 없습니다.\n"
        "  1) cp .env.example .env\n"
        "  2) .env 파일에 OPENAI_API_KEY 또는 선택한 공급자의 LLM_API_KEY를 넣으세요.\n"
        "     OpenAI: https://platform.openai.com/api-keys"
    )

# 대화 요청은 이 함수 아래의 지수 백오프가 직접 재시도한다. SDK의 기본
# 재시도까지 켜 두면 한 번의 사용자 발화가 중첩 재시도되어 수십 초 동안
# 멈출 수 있으므로 SDK 계층은 한 번만 호출한다.
client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    max_retries=0,
    timeout=LLM_REQUEST_TIMEOUT_SECONDS,
)

class QuotaExceeded(RuntimeError):
    """공급자 사용량 또는 요청 한도 소진."""


def _is_openai_gpt5(model: str) -> bool:
    """OpenAI GPT-5 계열의 Chat Completions 파라미터 차이를 판별한다."""
    return "api.openai.com" in BASE_URL.lower() and model.lower().startswith("gpt-5")


class FastRisk(BaseModel):
    """사용자에게 말하기 전에 확정해야 하는 즉시 위험 신호."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal[
        "stroke_sign",
        "fall",
        "breathing",
        "chest_pain",
        "overdose",
        "self_harm",
        "fire",
        "gas_leak",
        "intrusion",
        "lost",
    ]
    level: Literal["high", "medium"]
    evidence: str


class FastUnverifiedRecall(BaseModel):
    """등록된 기억으로 확인되지 않은 사용자의 새 회상."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str
    quote: str


class FastReply(BaseModel):
    """실시간 음성 응답이 허용되기 전에 필요한 최소 계약."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str
    used_memory_ids: list[str]
    used_schedule_ids: list[str]
    certainty: Literal["verified", "partial", "unverified", "none"]
    risk: FastRisk | None
    unverified_recall: FastUnverifiedRecall | None


FAST_REPLY_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "memory_call_fast_reply",
        "strict": True,
        "schema": FastReply.model_json_schema(),
    },
}


def safe_fast_reply(reply: str | None = None) -> dict:
    """모델 호출·형식 검증 실패 시에도 안전 검사를 계속할 완전한 응답."""
    return FastReply(
        reply=reply or "잠깐 연결이 원활하지 않네. 한 번만 다시 말해줄래?",
        used_memory_ids=[],
        used_schedule_ids=[],
        certainty="none",
        risk=None,
        unverified_recall=None,
    ).model_dump()


FAST_REPLY_SCHEMA_OVERRIDE = """

---

# [이번 응답 전용 출력 형식 재정의]

앞의 전체 출력 형식 대신 이번 호출에서는 아래 JSON 필드만 출력한다.
intent, medication_status, care, grounding은 넣지 않는다. 다른 텍스트나
코드펜스도 붙이지 않는다.

{
  "reply": "실제로 말할 문장. 2문장 이내.",
  "used_memory_ids": [],
  "used_schedule_ids": [],
  "certainty": "verified | partial | unverified | none",
  "risk": null,
  "unverified_recall": null
}

risk는 위험 감지 시 기존 출력 규칙과 같은 객체를 사용한다. 기억·일정 ID는
실제로 답변에 사용한 등록 ID만 넣는다. 안전에 필요한 필드는 생략하지 않는다.
"""


FAST_REPLY_SCHEMA_OVERRIDE += """

For this live voice turn, keep `reply` to at most two short Korean sentences
and normally under 90 Korean characters. Lead with the answer or reassurance;
do not add greetings, summaries, or follow-up explanations unless needed for
safety. Return only the JSON object described above.
"""


def metadata_schema_override(final_reply: str) -> str:
    """이미 확정된 답변에 대한 리포트 메타데이터만 요청한다."""
    reply_json = json.dumps(final_reply, ensure_ascii=False)
    return f"""

---

# [백그라운드 리포트 메타데이터 전용]

이번 턴에서 실제로 말한 문장은 {reply_json} 이다. 이 문장을 바꾸거나 새 답변을
만들지 말고, 환자의 직전 발화와 이 답변을 근거로 아래 JSON만 출력한다.

{{
  "intent": "greeting | repeated_question | memory_recall | medication | schedule_question | emotional | risk | identity_question | closing | other",
  "medication_status": null,
  "care": {{
    "observations": [],
    "context_support": [],
    "emotional_support": "none | acknowledge | validate_emotion | ground_and_redirect",
    "daily_action": null,
    "meaningful_moments": []
  }},
  "grounding": "이 응답의 근거를 한 문장으로."
}}

각 하위 필드와 허용 값은 앞의 care·복약 출력 규칙을 그대로 따른다. 환자 원문에
없는 관찰 근거를 만들지 않는다. 다른 텍스트나 코드펜스는 붙이지 않는다.
"""


def _extract_json(text: str) -> dict:
    """모델이 코드펜스를 붙이거나 앞뒤로 말을 덧붙여도 JSON을 건져낸다."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 중괄호 균형을 세어 첫 완전한 객체만 잘라낸다
    start = text.find("{")
    if start == -1:
        raise ValueError(f"JSON 없음: {text[:200]}")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError(f"JSON 파싱 실패: {text[:200]}")


def call_json(messages: list[dict], temperature: float = 0.7,
              model: str | None = None, quiet: bool = False,
              *, stream: bool = False, max_tokens: int | None = None,
              reasoning_effort: str | None = None,
              json_mode: bool = True,
              response_format: dict | None = None) -> dict:
    """JSON 응답을 요구하고 dict로 돌려준다. 429는 백오프 재시도."""
    last_err = None

    for attempt in range(MAX_RETRIES):
        try:
            selected_model = model or MODEL
            effort = REASONING_EFFORT if reasoning_effort is None else reasoning_effort
            kwargs = {
                "model": selected_model,
                "messages": messages,
            }
            token_limit = max_tokens or MAX_TOKENS
            if _is_openai_gpt5(selected_model):
                kwargs["max_completion_tokens"] = token_limit
                # GPT-5 계열은 reasoning 설정에 따라 sampling 파라미터 지원 범위가
                # 달라질 수 있으므로 말투는 프롬프트로 제어하고 모델 기본값을 쓴다.
            else:
                kwargs["max_tokens"] = token_limit
                kwargs["temperature"] = temperature
            if response_format is not None:
                kwargs["response_format"] = response_format
            elif json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if effort:
                kwargs["reasoning_effort"] = effort
            request_started = time.perf_counter()
            if stream:
                chunks = client.chat.completions.create(**kwargs, stream=True)
                content_parts: list[str] = []
                first_token_ms = None
                finish_reason = None
                for chunk in chunks:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    piece = choice.delta.content or ""
                    if piece:
                        if first_token_ms is None:
                            first_token_ms = int(
                                (time.perf_counter() - request_started) * 1000
                            )
                        content_parts.append(piece)
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                content = "".join(content_parts)
            else:
                resp = client.chat.completions.create(**kwargs)
                choice = resp.choices[0]
                content = choice.message.content or ""
                finish_reason = choice.finish_reason
                first_token_ms = None
            try:
                parsed = _extract_json(content)
                if first_token_ms is not None:
                    parsed["_stream_first_token_ms"] = first_token_ms
                return parsed
            except ValueError:
                raise ValueError(
                    f"JSON 잘림 (finish_reason={finish_reason}, "
                    f"{len(content)}자). LLM_MAX_TOKENS를 늘리세요."
                ) from None

        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)

            # 공급자 분당/일일 한도
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                if attempt == MAX_RETRIES - 1:
                    raise QuotaExceeded("LLM 사용량 또는 요청 한도 소진") from e
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                if not quiet:
                    print(f"    …요청 한도. {wait:.0f}초 대기 후 재시도 "
                          f"({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            # 모델명이 틀렸을 때
            if "404" in msg or "not found" in msg.lower():
                raise RuntimeError(
                    f"모델 '{model or MODEL}'을 찾을 수 없습니다.\n"
                    f"python tools/check_key.py 로 쓸 수 있는 모델을 확인하고 "
                    f".env의 LLM_MODEL을 고치세요.\n원본 오류: {msg}"
                ) from e

            raise

    raise RuntimeError(f"{MAX_RETRIES}회 재시도 실패: {last_err}")


def _with_system_override(messages: list[dict], override: str) -> list[dict]:
    """첫 system 메시지를 복사해 호출별 출력 형식만 덧붙인다."""
    if not messages or messages[0].get("role") != "system":
        raise ValueError("첫 메시지는 system이어야 합니다")
    patched = [dict(messages[0]), *(dict(message) for message in messages[1:])]
    patched[0]["content"] = str(patched[0].get("content") or "") + override
    return patched


def call_json_fast(messages: list[dict], **kwargs) -> dict:
    """실시간 통화에 필요한 답변·안전 필드만 생성한다."""
    kwargs.setdefault("model", FAST_MODEL)
    selected_model = kwargs["model"]
    raw = call_json(
        _with_system_override(messages, FAST_REPLY_SCHEMA_OVERRIDE),
        stream=True,
        # OpenAI 경로는 여섯 필드의 이름·타입·허용값을 서버 생성 단계부터
        # 강제한다. 다른 공급자는 프롬프트 출력 후 같은 Pydantic 계약으로
        # 로컬 검증한다.
        json_mode=_is_openai_gpt5(selected_model),
        response_format=(
            FAST_REPLY_RESPONSE_FORMAT
            if _is_openai_gpt5(selected_model)
            else None
        ),
        max_tokens=FAST_MAX_TOKENS,
        reasoning_effort=FAST_REASONING_EFFORT,
        **kwargs,
    )
    raw = dict(raw)
    first_token_ms = raw.pop("_stream_first_token_ms", None)
    validated = FastReply.model_validate(raw).model_dump()
    if first_token_ms is not None:
        validated["_stream_first_token_ms"] = first_token_ms
    return validated


def warm_fast_model() -> dict:
    """Warm the live model connection while the age morph is still playing.

    The result is never shown or stored. A process-wide TTL prevents several
    calls opened together from paying for duplicate warm-ups.
    """
    global _fast_warmed_at

    now = time.monotonic()
    if _fast_warmed_at > 0 and now - _fast_warmed_at < FAST_WARM_TTL_SECONDS:
        return {"performed": False, "latency_ms": 0, "first_token_ms": None}

    with _fast_warm_lock:
        now = time.monotonic()
        if _fast_warmed_at > 0 and now - _fast_warmed_at < FAST_WARM_TTL_SECONDS:
            return {"performed": False, "latency_ms": 0, "first_token_ms": None}

        started = time.perf_counter()
        # 실제 통화와 같은 모델·출력 스키마를 사용해야 연결뿐 아니라
        # Structured Outputs 스키마 준비 비용도 모핑 재생 중에 숨길 수 있다.
        result = call_json_fast(
            [
                {
                    "role": "system",
                    "content": (
                        "This is a hidden connection warm-up. Return a short "
                        "neutral Korean acknowledgement using the required schema."
                    ),
                },
                {"role": "user", "content": "연결 준비"},
            ],
            quiet=True,
        )
        _fast_warmed_at = time.monotonic()
        return {
            "performed": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "first_token_ms": result.get("_stream_first_token_ms"),
        }


def call_json_metadata(messages: list[dict], final_reply: str, **kwargs) -> dict:
    """사용자가 기다리지 않는 리포트용 필드를 별도 생성한다."""
    return call_json(
        _with_system_override(messages, metadata_schema_override(final_reply)),
        **kwargs,
    )


def call_schema(messages: list[dict], model_cls: type[BaseModel],
                retries: int = 1, **kwargs):
    """Pydantic 모델로 형태를 검증해서 돌려준다. 실패하면 None.

    Azure OpenAI 의 Structured Outputs 대신 쓴다. 스키마를 강제하는 대신
    받은 뒤에 검사하고, 틀리면 무엇이 틀렸는지 붙여 한 번 더 묻는다.

    끝내 실패해도 예외를 올리지 않는다. 모델이 형태를 못 맞췄다고 해서
    리포트가 아예 안 나오면 안 되기 때문이다. 호출한 쪽이 None 을 보고
    규칙 기반 폴백으로 간다.
    """
    msgs = list(messages)
    reason = None

    for attempt in range(retries + 1):
        try:
            raw = call_json(msgs, **kwargs)
        except Exception as e:  # noqa: BLE001
            reason = f"호출 실패: {e}"
            break

        try:
            return model_cls.model_validate(raw)
        except ValidationError as e:
            reason = f"형식 불일치: {e.error_count()}건"
            if attempt == retries:
                break
            msgs = msgs + [
                {"role": "assistant",
                 "content": json.dumps(raw, ensure_ascii=False)},
                {"role": "user",
                 "content": "출력 형식이 맞지 않습니다. 아래 오류를 고쳐서 "
                            f"JSON 만 다시 출력하세요.\n{e}"},
            ]

    print(f"    …{model_cls.__name__} 생성 실패 ({reason})", file=sys.stderr)
    return None


def list_models() -> list[str]:
    """이 키로 쓸 수 있는 모델 목록."""
    return sorted(m.id for m in client.models.list())
