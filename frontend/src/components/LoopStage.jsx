/**
 * 표정 루프 무대.
 *
 * 모핑이 끝난 뒤부터 통화가 끝날 때까지 짧은 영상을 반복 재생한다.
 * 응답마다 영상을 만들면 비용과 지연이 감당되지 않으므로,
 * 미리 만들어 둔 몇 개를 상황에 맞게 고르는 방식이다.
 *
 * 어떤 루프가 있는지는 서버가 알려주고, 언제 무엇을 틀지는 여기서 정한다.
 * want 목록의 앞에서부터 있는 것을 고르므로 루프가 하나뿐이어도 동작한다.
 */
export default function LoopStage({ loops, want }) {
  const names = Object.keys(loops ?? {});
  if (!names.length) return null;

  const active = want.find((n) => names.includes(n)) ?? names[0];

  return (
    <div className="stage">
      {names.map((name) => (
        <video key={`b-${name}`} className="blur" src={loops[name]}
               autoPlay muted loop playsInline preload="auto"
               style={{ opacity: name === active ? 1 : 0 }} />
      ))}
      {names.map((name) => (
        <video key={`f-${name}`} className="face" src={loops[name]}
               autoPlay muted loop playsInline preload="auto"
               style={{ opacity: name === active ? 1 : 0 }} />
      ))}
      <div className="scrim" />
    </div>
  );
}
