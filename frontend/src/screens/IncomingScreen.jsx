/**
 * 걸려오는 전화.
 *
 * 치매 노인은 약 먹을 시간을 스스로 기억하기 어렵다. 그래서 기다리지 않고
 * 복약 시간이 되면 AI 쪽에서 먼저 전화를 건다 (명세 FR-08).
 *
 * 받는 방법은 큰 초록 버튼 하나뿐이다.
 */
export default function IncomingScreen({ profile, reason, onAnswer, onDecline }) {
  const persona = profile?.persona;
  const face = profile?.faces?.at(-1);

  return (
    <div className="screen incoming">
      {face && <img className="avatar ringing" src={face.url} alt="" />}

      <div className="who">
        {persona?.display_name ?? "가족"}
        <small>{persona?.relationship ?? ""}</small>
      </div>

      <p className="hint">
        {reason === "medication" ? "약 챙기러 전화했어요" : "전화가 왔어요"}
      </p>

      <div className="controls">
        <button className="round call-answer" onClick={onAnswer}>받기</button>
        <button className="round danger" onClick={onDecline}>나중에</button>
      </div>
    </div>
  );
}
