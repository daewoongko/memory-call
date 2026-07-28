/**
 * 얼굴 무대.
 *
 * 명세 FR-03 — 통화 초반에 어린 시절부터 현재 얼굴까지 이동시켜
 * 노인이 기억하는 얼굴과 현재 얼굴 사이의 간극을 좁힌다.
 *
 * 단순 크로스페이드는 "사진이 바뀐다"로 읽히고 "자란다"로는 읽히지 않는다.
 * 그래서 두 가지를 겹친다.
 *
 *   1. 불투명도 교차 — 부드럽게 이어지도록 smoothstep 을 쓴다
 *   2. 연속 변형     — 머리 크기와 높이를 전체 구간에 걸쳐 단조 증가시킨다
 *
 * 2번이 핵심이다. 사진이 바뀌는 순간이 아니라 통화 내내 얼굴이 조금씩
 * 커지고 올라가므로, 디졸브 중에도 성장하고 있다는 감각이 유지된다.
 *
 * 눈코입이 실제로 이동하는 진짜 모핑은 랜드마크 워핑이 필요하다.
 * 그건 얼굴 그물을 얻은 뒤에 이 컴포넌트만 교체하면 된다.
 */

const smoothstep = (t) => t * t * (3 - 2 * t);

// 나이가 어릴수록 머리가 작고 화면에서 아래쪽에 있다.
const START = { scale: 0.86, shiftY: 3.2 };
const END = { scale: 1.06, shiftY: -1.4 };

export default function FaceStage({ faces, progress, speaking }) {
  if (!faces?.length) return <div className="stage" />;

  const last = faces.length - 1;
  const p = Math.min(Math.max(progress, 0), 1);
  const pos = p * last;
  const index = Math.min(Math.floor(pos), last);
  const frac = smoothstep(pos - index);

  const opacityOf = (i) => {
    if (i === index) return 1 - frac;
    if (i === index + 1) return frac;
    return 0;
  };

  // 전체 구간에 걸친 연속 성장. 사진 교체 시점과 무관하게 계속 이어진다.
  const grow = smoothstep(p);
  const scale = START.scale + (END.scale - START.scale) * grow;
  const shiftY = START.shiftY + (END.shiftY - START.shiftY) * grow;

  // 말할 때의 미세한 호흡. 성장 변형 위에 얹는다.
  const pulse = speaking ? 1.008 : 1;
  const transform = `translateY(${shiftY}%) scale(${(scale * pulse).toFixed(4)})`;
  const motion = { transform, transition: "transform 0.5s ease-out" };

  return (
    <div className="stage">
      {faces.map((face, i) => (
        <img key={`b-${face.url}`} className="blur" src={face.url} alt=""
             style={{ opacity: opacityOf(i) }} />
      ))}
      {faces.map((face, i) => (
        <img key={`f-${face.url}`} className="face" src={face.url} alt=""
             style={{ opacity: opacityOf(i), ...motion }} />
      ))}
      <div className="scrim" />
    </div>
  );
}
