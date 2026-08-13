/**
 * 가족을 호출하는 구간.
 *
 * 명세 8.2 — 정해진 시간 동안 가족이 받지 않으면 AI 대리통화 조건을 확인한다.
 * 명세 13.1 — 연결 직전에 AI 통화임을 한 번만 안내한다.
 *
 * secondsLeft 는 서버가 내려보낸 값이다. 이 화면이 스스로 세지 않는다.
 * 여기서 세면 보호자가 받았는지와 무관하게 시간이 흐르고, 그것이 예전에
 * "AI 대리통화"가 대리가 아니었던 이유다.
 */

export default function CallingScreen({
  name, secondsLeft, announcement, onSkip, onStop,
}) {
  const connecting = secondsLeft <= 0;

  return (
    <div className="screen">
      <div className="ring-dots">
        <i />
        <i />
        <i />
      </div>

      <div className="who">
        {connecting ? "연결하는 중" : `${name}에게 거는 중`}
      </div>

      {connecting ? (
        <p className="hint">{announcement}</p>
      ) : (
        <>
          <p className="hint">잠시만 기다려 주세요</p>
          <p className="countdown">{secondsLeft}초</p>
        </>
      )}

      {!connecting && (
        <>
          <div className="controls">
            <button className="round danger" onClick={onStop}>그만두기</button>
          </div>
          <div className="dev">
            <button onClick={onSkip}>기다리지 않고 연결</button>
          </div>
        </>
      )}
    </div>
  );
}
