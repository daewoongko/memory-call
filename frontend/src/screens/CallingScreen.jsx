import { useEffect, useRef, useState } from "react";
import MorphStage from "../components/MorphStage.jsx";
import BrandMark from "../components/BrandMark.jsx";

/**
 * 가족을 호출하는 구간. 대웅의 연령 변화 영상은 이 대기 시간을 대신한다.
 * 가족이 중간에 받아도 24.2초 준비 재생을 마친 뒤 사람 통화로 넘어간다.
 * 받지 않은 경우에도 같은 시점에 AI가 이어받아 두 기기의 흐름이 어긋나지 않는다.
 */
export default function CallingScreen({
  name,
  announcement,
  morphUrl = null,
  introDurationSec = 24.2,
  introStartedAt = null,
  onWaitEnded,
}) {
  const [elapsed, setElapsed] = useState(0);
  const [remaining, setRemaining] = useState(() => Math.max(0, Math.ceil(introDurationSec)));
  const fallbackStartedAtRef = useRef(Date.now());
  const onWaitEndedRef = useRef(onWaitEnded);
  useEffect(() => { onWaitEndedRef.current = onWaitEnded; }, [onWaitEnded]);
  useEffect(() => {
    const rawStartedAt = String(introStartedAt || "");
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(rawStartedAt);
    const parsedStartedAt = new Date(
      rawStartedAt && !hasTimezone ? `${rawStartedAt}Z` : rawStartedAt,
    ).getTime();
    const startedAt = Number.isNaN(parsedStartedAt)
      ? fallbackStartedAtRef.current
      : parsedStartedAt;
    const durationMs = Math.max(1, Number(introDurationSec) || 0) * 1000;
    const deadline = startedAt + durationMs;
    let completed = false;
    const tick = () => {
      const now = Date.now();
      const leftMs = Math.max(0, deadline - now);
      setElapsed(Math.max(0, Math.floor((now - startedAt) / 1000)));
      setRemaining(Math.max(0, Math.ceil(leftMs / 1000)));
      if (leftMs > 0 || completed) return;
      completed = true;
      onWaitEndedRef.current?.();
    };
    tick();
    const timer = window.setInterval(tick, 250);
    return () => {
      window.clearInterval(timer);
    };
  }, [introDurationSec, introStartedAt]);
  const connectionCountdown = remaining > 0
    ? `${remaining}초 후 연결돼요`
    : "곧 연결돼요";
  const status = elapsed < 5
    ? `${name}에게 연결을 요청하고 있어요.`
    : "잔잔한 음악을 들으며 잠시 기다려 주세요.";
  if (morphUrl) {
    return (
      <div className="screen calling-screen calling-with-morph">
        <MorphStage
          src={morphUrl}
          speaking={false}
        />

        <div className="calling-morph-status">
          <div className="ring-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <div className="who">
            {`${name}과 연결하는 중`}
          </div>
          <p>{status}</p>
          <small className="calling-intro-count">{connectionCountdown}</small>
        </div>
      </div>
    );
  }

  return (
    <div className="screen calling-screen">
      <BrandMark size={170} />
      <div className="ring-dots">
        <i />
        <i />
        <i />
      </div>

      <div className="who">
        {`${name}과 연결하는 중`}
      </div>
      <p className="hint">{elapsed < 5 ? announcement : status}</p>
      <small className="calling-intro-count">{connectionCountdown}</small>
    </div>
  );
}
