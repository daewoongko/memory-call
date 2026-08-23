"""Measure the local live-call path from text turn to first TTS audio bytes.

The backend must already be running. This tool uses the same HTTP endpoints as
the browser and never reads or prints provider credentials.

    python tools/benchmark_call_pipeline.py --runs 2
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = [
    "안녕 대웅아, 잘 지냈어?",
    "우리 예전에 부산 해운대 갔던 거 기억나?",
    "내일 병원 일정이 언제였지?",
    "혈압약을 먹었는지 기억이 안 나. 하나 더 먹을까?",
    "요즘 자꾸 혼자 있는 기분이 들어.",
    "지금 너무 어지럽고 넘어질 것 같아.",
]


def post_json(url: str, payload: dict, *, stream: bool = False):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    response = request.urlopen(req, timeout=45)
    if stream:
        return response
    with response:
        return json.loads(response.read().decode("utf-8"))


def median(samples: list[dict], key: str) -> int | None:
    values = [sample[key] for sample in samples if sample.get(key) is not None]
    return round(statistics.median(values)) if values else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--elder-id", default="elder_001")
    parser.add_argument("--persona-id", default="persona_godaewoong")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--skip-prepare", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    call = post_json(
        f"{args.base_url}/api/calls",
        {"elder_id": args.elder_id, "persona_id": args.persona_id},
    )
    call_id = call["call_id"]
    prepare = None
    if not args.skip_prepare:
        prepare_started = time.perf_counter()
        prepare = post_json(
            f"{args.base_url}/api/calls/{call_id}/prepare",
            {},
        )
        prepare["request_ms"] = round(
            (time.perf_counter() - prepare_started) * 1000
        )
        print(
            f"prepare performed={prepare.get('performed')} "
            f"request={prepare['request_ms']}ms "
            f"model={prepare.get('latency_ms')}ms"
        )
    samples: list[dict] = []

    for run in range(1, args.runs + 1):
        for case_index, text in enumerate(DEFAULT_CASES, start=1):
            turn_started = time.perf_counter()
            try:
                turn = post_json(
                    f"{args.base_url}/api/calls/{call_id}/turn",
                    {"text": text},
                )
                turn_received = time.perf_counter()
                reply = str(turn.get("reply") or "")

                tts_started = time.perf_counter()
                tts_response = post_json(
                    f"{args.base_url}/api/tts/pcm-stream",
                    {
                        "text": reply,
                        "rate": 1.0,
                        "persona_id": args.persona_id,
                    },
                    stream=True,
                )
                tts_headers = time.perf_counter()
                first_pcm = tts_response.read(2048)
                first_pcm_at = time.perf_counter()
                remaining = tts_response.read()
                tts_response.close()
                completed = time.perf_counter()

                api_turn_ms = round((turn_received - turn_started) * 1000)
                server_llm_ms = int(turn.get("latency_ms") or 0)
                sample = {
                    "run": run,
                    "case": case_index,
                    "input": text,
                    "reply": reply,
                    "ok": bool(reply and first_pcm),
                    "llm_first_token_ms": turn.get("llm_first_token_ms"),
                    "server_llm_ms": server_llm_ms,
                    "api_turn_ms": api_turn_ms,
                    "api_overhead_ms": max(0, api_turn_ms - server_llm_ms),
                    "tts_headers_ms": round((tts_headers - tts_started) * 1000),
                    "tts_first_pcm_ms": round((first_pcm_at - tts_started) * 1000),
                    "tts_complete_ms": round((completed - tts_started) * 1000),
                    "tts_server_headers_ms": round(
                        float(tts_response.headers.get("X-Generation-Seconds", "0"))
                        * 1000
                    ),
                    "turn_to_first_pcm_ms": round((first_pcm_at - turn_started) * 1000),
                    "pcm_bytes": len(first_pcm) + len(remaining),
                }
            except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
                detail = ""
                if isinstance(exc, error.HTTPError):
                    try:
                        detail = exc.read().decode("utf-8")[:500]
                    except Exception:  # noqa: BLE001
                        detail = ""
                sample = {
                    "run": run,
                    "case": case_index,
                    "input": text,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc} {detail}".strip(),
                }
            samples.append(sample)
            if sample["ok"]:
                print(
                    f"{run}/{args.runs} case={case_index} "
                    f"TTFT={sample['llm_first_token_ms']}ms "
                    f"LLM={sample['server_llm_ms']}ms "
                    f"TTS-first={sample['tts_first_pcm_ms']}ms "
                    f"turn-to-audio={sample['turn_to_first_pcm_ms']}ms"
                )
            else:
                print(f"{run}/{args.runs} case={case_index} FAIL {sample['error']}")

    successful = [sample for sample in samples if sample["ok"]]
    summary = {
        "requests": len(samples),
        "successes": len(successful),
        "llm_first_token_p50_ms": median(successful, "llm_first_token_ms"),
        "server_llm_p50_ms": median(successful, "server_llm_ms"),
        "api_turn_p50_ms": median(successful, "api_turn_ms"),
        "api_overhead_p50_ms": median(successful, "api_overhead_ms"),
        "tts_first_pcm_p50_ms": median(successful, "tts_first_pcm_ms"),
        "tts_server_headers_p50_ms": median(successful, "tts_server_headers_ms"),
        "turn_to_first_pcm_p50_ms": median(successful, "turn_to_first_pcm_ms"),
    }
    report = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "persona_id": args.persona_id,
        "prepare": prepare,
        "summary": summary,
        "samples": samples,
    }

    output_dir = ROOT / "output" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"call_pipeline_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {output_path}")
    return 0 if len(successful) == len(samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
