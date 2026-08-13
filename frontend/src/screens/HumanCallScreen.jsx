import { useEffect, useState } from "react";
import SelfView from "../components/SelfView.jsx";

/**
 * 가족이 직접 받은 통화.
 *
 * 어르신 입장에서 이 화면과 AI 통화 화면은 같은 종류의 일이어야 한다.
 * 얼굴이 보이고, 이름이 있고, 끊는 버튼이 하나 있다. 누가 받았는지에 따라
 * 화면의 구조가 달라지면 어르신이 그 차이를 눈치채고 혼란스러워한다.
 *
 * 음성·영상은 다음 단계(WebRTC P2P)에서 붙는다. 지금은 호출이 실제로
 * 연결되었다는 사실만 보여준다. 붙지 않을 때 AI 로 넘기는 경로는
 * docs/call_transport_decision.md 참고.
 */

function clock(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function HumanCallScreen({ name, face, answeredAt, onEnd }) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const started = new Date(answeredAt).getTime();
    const base = Number.isNaN(started) ? Date.now() : started;
    const tick = () =>
      setSeconds(Math.max(0, Math.floor((Date.now() - base) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [answeredAt]);

  return (
    <div className="screen human-call">
      {face && <img className="avatar" src={face} alt="" />}

      <div className="who">
        {name}
        <small>지금 통화 중</small>
      </div>

      <p className="countdown">{clock(seconds)}</p>

      <SelfView />

      <div className="controls">
        <button className="round danger" onClick={onEnd}>끊기</button>
      </div>

      <div className="dev">
        <span>가족이 직접 받았습니다. 목소리 연결은 다음 단계에서 붙습니다.</span>
      </div>
    </div>
  );
}
