import { useEffect, useRef, useState } from "react";
import MorphStage from "../components/MorphStage.jsx";
import BrandMark from "../components/BrandMark.jsx";

/**
 * 가족을 호출하는 구간. 대웅의 연령 변화 영상은 이 대기 시간을 대신한다.
 * 가족이 중간에 받아도 14.8초 준비 재생을 마친 뒤 사람 통화로 넘어간다.
 * 받지 않은 경우에도 같은 시점에 AI가 이어받아 두 기기의 흐름이 어긋나지 않는다.
 */
export default function CallingScreen({
  name,
  announcement,
  morphUrl = null,
  introDurationSec = 14.8,
  onWaitEnded,
}) {
  const [elapsed, setElapsed] = useState(0);
  const onWaitEndedRef = useRef(onWaitEnded);
  useEffect(() => { onWaitEndedRef.current = onWaitEnded; }, [onWaitEnded]);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    const done = window.setTimeout(
      () => onWaitEndedRef.current?.(), Math.max(1, introDurationSec) * 1000,
    );
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(done);
    };
  }, [introDurationSec]);
  const remaining = Math.max(0, Math.ceil(introDurationSec - elapsed));
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
          <small className="calling-intro-count">{remaining}초 후 연결돼요</small>
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
      <small className="calling-intro-count">{remaining}초 후 연결돼요</small>
    </div>
  );
}
