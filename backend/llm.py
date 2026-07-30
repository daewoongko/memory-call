"""
LLM 호출 단일 창구.

Gemini를 OpenAI 호환 엔드포인트로 부른다. 나중에 OpenAI/Claude로 갈아탈 때
.env의 세 줄만 바꾸면 되고 나머지 코드는 손대지 않는다.

무료 티어는 분당 요청 수 제한이 빡빡해서 429가 자주 뜬다.
call_json()이 지수 백오프로 알아서 재시도한다.
"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash")
# 리포트·페르소나는 통화당 한 번만 돌고 지연이 상관없다. 중첩 배열과 id 인용을
# 시켜야 하므로 대화용 경량 모델보다 큰 모델을 쓴다. 비워 두면 LLM_MODEL 을 쓴다.
REPORT_MODEL = os.getenv("LLM_REPORT_MODEL", "") or MODEL
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")

if not API_KEY:
    sys.exit(
        "LLM_API_KEY가 없습니다.\n"
        "  1) cp .env.example .env\n"
        "  2) .env 파일에 Google AI Studio에서 받은 키를 넣으세요.\n"
        "     https://aistudio.google.com/apikey"
    )

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

MAX_RETRIES = 5

class QuotaExceeded(RuntimeError):
    """무료 사용량 소진."""


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
              model: str | None = None, quiet: bool = False) -> dict:
    """JSON 응답을 요구하고 dict로 돌려준다. 429는 백오프 재시도."""
    last_err = None

    for attempt in range(MAX_RETRIES):
        try:
            kwargs = {
                "model": model or MODEL,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "max_tokens": MAX_TOKENS,
            }
            if REASONING_EFFORT:
                kwargs["reasoning_effort"] = REASONING_EFFORT
            resp = client.chat.completions.create(**kwargs)

            choice = resp.choices[0]
            content = choice.message.content or ""
            try:
                return _extract_json(content)
            except ValueError:
                raise ValueError(
                    f"JSON 잘림 (finish_reason={choice.finish_reason}, "
                    f"{len(content)}자). LLM_MAX_TOKENS를 늘리세요."
                ) from None

        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)

            # 무료 티어 분당/일일 한도
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                if attempt == MAX_RETRIES - 1:
                    raise QuotaExceeded("무료 사용량 소진") from e
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
