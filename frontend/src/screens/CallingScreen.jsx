import { useEffect, useState } from "react";
import MorphStage from "../components/MorphStage.jsx";
import BrandMark from "../components/BrandMark.jsx";

/**
 * 가족을 호출하는 구간. 대웅의 연령 변화 영상은 이 대기 시간을 대신한다.
 * 가족이 직접 받으면 즉시 사람 통화로 넘어가고, AI가 대신 받는 경우에는
 * 모핑 마지막 프레임까지 보여준 뒤 Anam 통화 화면을 연다.
 */
export default function CallingScreen({
  name,
  announcement,
  morphUrl = null,
  onMorphEnded,
  onChooseAI,
  onCancel,
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const status = elapsed < 5
    ? `${name}에게 연결을 요청하고 있어요.`
    : elapsed < 16
      ? "전화벨이 울리고 있어요. 천천히 기다려 주세요."
      : "아직 연결을 기다리고 있어요. 원하시면 다소니와 먼저 이야기할 수 있어요.";
  const options = elapsed >= 16 && <div className="calling-wait-options">
    {onChooseAI && <button type="button" onClick={onChooseAI}>다소니와 먼저 이야기하기</button>}
    {onCancel && <button type="button" onClick={onCancel}>다른 가족 선택</button>}
  </div>;
  if (morphUrl) {
    return (
      <div className="screen calling-screen calling-with-morph">
        <MorphStage
          src={morphUrl}
          speaking={false}
          onEnded={onMorphEnded}
          onFail={onMorphEnded}
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
          {options}
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
      {options}
    </div>
  );
}
