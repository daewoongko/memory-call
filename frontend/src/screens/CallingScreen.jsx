/**
 * 가족을 호출하는 구간.
 *
 * 명세 8.2 — 정해진 시간 동안 가족이 받지 않으면 AI 대리통화 조건을 확인한다.
 * 명세 13.1 — 연결 직전에 AI 통화임을 한 번만 안내한다.
 */

export default function CallingScreen({ name, secondsLeft, announcement, onSkip }) {
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
        <div className="dev">
          <button onClick={onSkip}>기다리지 않고 연결</button>
        </div>
      )}
    </div>
  );
}
