"""Benchmark the live-call LLM path locally without changing deployment config.

Runs the exact compact persona prompt and ``call_json_fast`` path used by the
application against Gemini and OpenAI. API keys are read from ``.env`` and are
never written to the report.

    python tools/benchmark_llm.py --runs 3
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
load_dotenv(ROOT / ".env")

from persona import build_fast_system_prompt, load_context  # noqa: E402


CASES = [
    {"id": "greeting", "text": "안녕 대웅아, 잘 지냈어?"},
    {"id": "memory", "text": "우리 예전에 부산 해운대 갔던 거 기억나?"},
    {"id": "schedule", "text": "내일 병원 일정이 언제였지?"},
    {"id": "medication", "text": "혈압약을 먹었는지 기억이 안 나. 하나 더 먹을까?"},
    {"id": "emotional", "text": "요즘 자꾸 혼자 있는 기분이 들어."},
    {"id": "fall_risk", "text": "지금 너무 어지럽고 넘어질 것 같아."},
]

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model_env": "BENCHMARK_GEMINI_MODEL",
        "default_model": "gemini-3.5-flash-lite",
        "reasoning_effort": "",
        "required_key": "LLM_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model_env": "BENCHMARK_OPENAI_MODEL",
        "default_model": "gpt-5.6-luna",
        "reasoning_effort": "none",
        "required_key": "OPENAI_API_KEY",
    },
}

REQUIRED_FIELDS = {
    "reply",
    "used_memory_ids",
    "used_schedule_ids",
    "certainty",
    "risk",
    "unverified_recall",
}


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def configure_provider(name: str):
    config = PROVIDERS[name]
    key = os.getenv(config["required_key"], "").strip()
    if not key:
        raise RuntimeError(f".env에 {config['required_key']}가 없습니다")

    model = os.getenv(config["model_env"], config["default_model"]).strip()
    os.environ["LLM_BASE_URL"] = config["base_url"]
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_FAST_MODEL"] = model
    os.environ["LLM_FAST_REASONING_EFFORT"] = config["reasoning_effort"]
    os.environ["LLM_MAX_RETRIES"] = "1"

    import llm  # noqa: PLC0415

    return importlib.reload(llm), model


def run_provider(name: str, runs: int, ctx: dict) -> dict:
    llm, model = configure_provider(name)
    samples: list[dict] = []

    for run in range(1, runs + 1):
        for case in CASES:
            messages = [
                {
                    "role": "system",
                    "content": build_fast_system_prompt(ctx, case["text"]),
                },
                {"role": "user", "content": case["text"]},
            ]
            started = time.perf_counter()
            try:
                result = llm.call_json_fast(messages, quiet=True)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                first_token_ms = result.pop("_stream_first_token_ms", None)
                reply = str(result.get("reply") or "")
                missing = sorted(REQUIRED_FIELDS - result.keys())
                sample = {
                    "run": run,
                    "case": case["id"],
                    "input": case["text"],
                    "ok": not missing and bool(reply),
                    "first_token_ms": first_token_ms,
                    "total_ms": elapsed_ms,
                    "reply_chars": len(reply),
                    "reply": reply,
                    "certainty": result.get("certainty"),
                    "risk": result.get("risk"),
                    "used_memory_ids": result.get("used_memory_ids") or [],
                    "missing_fields": missing,
                }
            except Exception as exc:  # noqa: BLE001
                sample = {
                    "run": run,
                    "case": case["id"],
                    "input": case["text"],
                    "ok": False,
                    "first_token_ms": None,
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            samples.append(sample)
            status = "OK" if sample["ok"] else "FAIL"
            print(
                f"{name:7} {run}/{runs} {case['id']:10} {status:4} "
                f"TTFT={str(sample.get('first_token_ms')):>5}ms "
                f"total={sample['total_ms']:>5}ms"
            )

    successful = [sample for sample in samples if sample["ok"]]
    ttft = [sample["first_token_ms"] for sample in successful if sample["first_token_ms"]]
    total = [sample["total_ms"] for sample in successful]
    summary = {
        "provider": name,
        "model": model,
        "requests": len(samples),
        "successes": len(successful),
        "success_rate": round(len(successful) / len(samples), 3),
        "ttft_p50_ms": round(statistics.median(ttft)) if ttft else None,
        "ttft_p95_ms": percentile(ttft, 0.95),
        "total_p50_ms": round(statistics.median(total)) if total else None,
        "total_p95_ms": percentile(total, 0.95),
        "reply_chars_avg": (
            round(statistics.mean(sample["reply_chars"] for sample in successful), 1)
            if successful
            else None
        ),
    }
    return {"summary": summary, "samples": samples}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--providers", nargs="+", choices=sorted(PROVIDERS), default=sorted(PROVIDERS)
    )
    parser.add_argument("--elder-id", default="elder_001")
    parser.add_argument("--persona-id", default="persona_godaewoong")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    ctx = load_context(args.elder_id, args.persona_id)
    report = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs_per_case": args.runs,
        "case_count": len(CASES),
        "persona_id": args.persona_id,
        "results": [],
    }
    for provider in args.providers:
        print(f"\n[{provider}] starting")
        report["results"].append(run_provider(provider, args.runs, ctx))

    output_dir = ROOT / "output" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"llm_ab_{stamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSummary")
    for result in report["results"]:
        item = result["summary"]
        print(
            f"- {item['provider']} / {item['model']}: "
            f"success={item['successes']}/{item['requests']}, "
            f"TTFT p50/p95={item['ttft_p50_ms']}/{item['ttft_p95_ms']}ms, "
            f"total p50/p95={item['total_p50_ms']}/{item['total_p95_ms']}ms"
        )
    print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
