"""Verify Anam audio passthrough all the way to returned media frames.

This is deliberately separate from the web UI.  It uses the same API key,
the same named custom avatar and a short slice of ``reference.wav``.  A pass
means that Anam accepted the PCM turn and returned both non-silent audio and
video frames over WebRTC; a token-only health check cannot prove that.

Run with a disposable environment containing the official ``anam`` package::

    python tools/diagnose_anam_passthrough.py

No provider token or avatar id is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from anam import AgentAudioInputConfig, AnamClient, AnamEvent, PersonaConfig
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
AVATARS_URL = "https://api.anam.ai/v1/avatars"


@dataclass
class Evidence:
    events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    video_frames: int = 0
    audio_frames: int = 0
    non_silent_audio_frames: int = 0
    max_audio_peak: int = 0
    first_video_at: float | None = None
    first_audio_at: float | None = None
    last_video_at: float | None = None
    last_audio_at: float | None = None


def _avatar_by_name(api_key: str, display_name: str) -> tuple[str, str]:
    page = 1
    while page <= 20:
        query = urllib.parse.urlencode({"page": page, "perPage": 100})
        req = urllib.request.Request(
            f"{AVATARS_URL}?{query}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for avatar in payload.get("data", []):
            name = avatar.get("displayName") or avatar.get("display_name")
            avatar_id = avatar.get("id") or avatar.get("avatarId")
            if str(name).strip().casefold() == display_name.casefold() and avatar_id:
                model = avatar.get("activeVersion") or avatar.get("avatarModel") or "cara-4"
                return str(avatar_id), str(model)
        next_page = (payload.get("meta") or {}).get("next")
        if not next_page:
            break
        page = int(next_page)
    raise RuntimeError(f"Anam avatar named {display_name!r} was not found")


def _read_pcm(path: Path, seconds: float) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise RuntimeError("reference WAV must contain 16-bit PCM")
        if source.getnchannels() != 1:
            raise RuntimeError("reference WAV must be mono")
        rate = source.getframerate()
        frames = min(source.getnframes(), int(rate * seconds))
        return source.readframes(frames), rate, frames


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _production_session_token(base_url: str) -> tuple[str, str]:
    base_url = base_url.rstrip("/")
    call = _post_json(
        f"{base_url}/api/calls",
        {"elder_id": "elder_001", "persona_id": "persona_godaewoong"},
    )
    token = _post_json(
        f"{base_url}/api/anam/session-token",
        {
            "call_id": call["call_id"],
            "persona_id": call["persona_id"],
            "performance_style": "calm",
        },
    )
    return token["session_token"], token.get("avatar_model") or "cara-4"


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("ANAM_API_KEY", "").strip()
    if not api_key and not args.production_base_url:
        raise RuntimeError("ANAM_API_KEY is not set")
    avatar_id: str | None = None
    session_token: str | None = None
    if args.production_base_url:
        session_token, avatar_model = await asyncio.to_thread(
            _production_session_token, args.production_base_url
        )
    else:
        avatar_id, avatar_model = await asyncio.to_thread(
            _avatar_by_name, api_key, args.avatar_name
        )
    pcm, sample_rate, source_frames = _read_pcm(args.wav, args.seconds)
    evidence = Evidence()
    started_at = time.monotonic()

    client = (
        AnamClient(session_token=session_token)
        if session_token
        else AnamClient(
            api_key=api_key,
            persona_config=PersonaConfig(
                name="memory-call-passthrough-diagnostic",
                avatar_id=avatar_id,
                avatar_model=avatar_model,
                enable_audio_passthrough=True,
            ),
        )
    )

    def elapsed() -> float:
        return round(time.monotonic() - started_at, 3)

    for event in (
        AnamEvent.CONNECTION_ESTABLISHED,
        AnamEvent.SESSION_READY,
        AnamEvent.CONNECTION_CLOSED,
    ):
        client.add_listener(
            event,
            lambda *unused, event=event: evidence.events.append(
                f"{elapsed():.3f}s {event.value}"
            ),
        )
    client.add_listener(
        AnamEvent.SERVER_WARNING,
        lambda message: evidence.warnings.append(str(message)[:500]),
    )
    client.add_listener(
        AnamEvent.ERROR,
        lambda error: evidence.errors.append(str(error)[:500]),
    )

    async with client.connect() as session:
        async def consume_video() -> None:
            async for frame in session.video_frames():
                now = elapsed()
                evidence.video_frames += 1
                evidence.first_video_at = evidence.first_video_at or now
                evidence.last_video_at = now

        async def consume_audio() -> None:
            async for frame in session.audio_frames():
                now = elapsed()
                values = frame.to_ndarray()
                peak = int(np.max(np.abs(values.astype(np.int32)))) if values.size else 0
                evidence.audio_frames += 1
                evidence.max_audio_peak = max(evidence.max_audio_peak, peak)
                if peak > 64:
                    evidence.non_silent_audio_frames += 1
                evidence.first_audio_at = evidence.first_audio_at or now
                evidence.last_audio_at = now

        video_task = asyncio.create_task(consume_video())
        audio_task = asyncio.create_task(consume_audio())
        try:
            await asyncio.sleep(args.settle_seconds)
            stream = session.create_agent_audio_input_stream(
                AgentAudioInputConfig(
                    encoding="pcm_s16le",
                    sample_rate=sample_rate,
                    channels=1,
                )
            )
            for offset in range(0, len(pcm), args.chunk_bytes):
                await stream.send_audio_chunk(pcm[offset : offset + args.chunk_bytes])
            await stream.end_sequence()
            evidence.events.append(
                f"{elapsed():.3f}s pcm_end bytes={len(pcm)} rate={sample_rate}"
            )
            await asyncio.sleep(args.seconds + args.tail_seconds)
        finally:
            for task in (video_task, audio_task):
                task.cancel()
            await asyncio.gather(video_task, audio_task, return_exceptions=True)

    passed = (
        evidence.video_frames >= 10
        and evidence.non_silent_audio_frames >= 3
        and not evidence.errors
    )
    return {
        "passed": passed,
        "avatar_found": True,
        "avatar_model": avatar_model,
        "source": {
            "path": str(args.wav.relative_to(ROOT)),
            "sample_rate": sample_rate,
            "frames": source_frames,
            "seconds": round(source_frames / sample_rate, 2),
            "bytes": len(pcm),
        },
        "returned_media": {
            "video_frames": evidence.video_frames,
            "audio_frames": evidence.audio_frames,
            "non_silent_audio_frames": evidence.non_silent_audio_frames,
            "max_audio_peak": evidence.max_audio_peak,
            "first_video_seconds": evidence.first_video_at,
            "last_video_seconds": evidence.last_video_at,
            "first_audio_seconds": evidence.first_audio_at,
            "last_audio_seconds": evidence.last_audio_at,
        },
        "events": evidence.events,
        "server_warnings": evidence.warnings,
        "errors": evidence.errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--avatar-name",
        default=os.getenv("ANAM_AVATAR_NAME", "").strip() or "28_daewoong",
    )
    parser.add_argument("--production-base-url")
    parser.add_argument(
        "--wav", type=Path, default=ROOT / "data" / "voice" / "reference.wav"
    )
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--tail-seconds", type=float, default=3.0)
    parser.add_argument("--chunk-bytes", type=int, default=2048)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:  # diagnostic output must stay readable in CI/PowerShell
        message = str(exc)
        code = "usage_limit_reached" if "usage_limit_reached" in message else type(exc).__name__
        print(
            json.dumps(
                {"passed": False, "failure_code": code, "detail": message[:500]},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
