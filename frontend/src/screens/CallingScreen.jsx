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
}) {
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
          <p>기억 속 얼굴을 만나고 있어요</p>
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
      <p className="hint">{announcement}</p>
    </div>
  );
}
