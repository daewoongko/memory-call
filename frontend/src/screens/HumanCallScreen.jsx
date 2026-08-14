import { useEffect, useRef, useState } from "react";
import SelfView from "../components/SelfView.jsx";

/**
 * 가족이 직접 받은 통화.
 *
 * 어르신 입장에서 이 화면과 AI 통화 화면은 같은 종류의 일이어야 한다.
 * 얼굴이 보이고, 이름이 있고, 끊는 버튼이 하나 있다. 누가 받았는지에 따라
 * 화면의 구조가 달라지면 어르신이 그 차이를 눈치채고 혼란스러워한다.
 *
 * 음성·영상은 callTransport 하나가 소유한다. 붙지 않으면 이 화면에서 오류를
 * 설명하지 않고 AI 통화 화면으로 자연스럽게 넘어간다.
 */

function clock(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function HumanCallScreen({
  name, face, answeredAt, localStream, remoteStream, onEnd,
}) {
  const [seconds, setSeconds] = useState(0);
  const remoteRef = useRef(null);

  useEffect(() => {
    const started = new Date(answeredAt).getTime();
    const base = Number.isNaN(started) ? Date.now() : started;
    const tick = () =>
      setSeconds(Math.max(0, Math.floor((Date.now() - base) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [answeredAt]);

  useEffect(() => {
    if (!remoteRef.current) return undefined;
    remoteRef.current.srcObject = remoteStream || null;
    remoteRef.current.play?.().catch(() => {});
    return () => {
      if (remoteRef.current) remoteRef.current.srcObject = null;
    };
  }, [remoteStream]);

  return (
    <div className="screen human-call">
      <video
        ref={remoteRef}
        className={`human-remote-video${remoteStream ? " live" : ""}`}
        autoPlay
        playsInline
        poster={face || undefined}
      />

      <div className="who">
        {name}
        <small>지금 통화 중</small>
      </div>

      <p className="countdown">{clock(seconds)}</p>

      <SelfView stream={localStream} />

      <div className="controls">
        <button className="round danger" onClick={onEnd}>끊기</button>
      </div>
    </div>
  );
}
