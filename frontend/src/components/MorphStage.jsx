import { useEffect, useRef, useState } from "react";

/**
 * 모핑 영상 무대.
 *
 * 페르소나 등록 시 미리 만들어 둔 영상을 한 번 재생하고 마지막 프레임에서 멈춘다.
 * 통화 중에 생성하지 않으므로 지연이 0이다 (명세 FR-02).
 *
 * 영상은 3:4 세로라 폰 화면을 거의 채우지만, 기기 비율이 다를 수 있어
 * 같은 영상을 흐리게 깔아 남는 자리를 메운다.
 */
export default function MorphStage({ src, speaking, onEnded }) {
  const mainRef = useRef(null);
  const blurRef = useRef(null);
  const [failed, setFailed] = useState(false);

  // 배경용 영상을 본 영상에 맞춰 따라가게 한다
  useEffect(() => {
    const main = mainRef.current;
    const blur = blurRef.current;
    if (!main || !blur) return;
    const sync = () => {
      if (Math.abs(blur.currentTime - main.currentTime) > 0.15) {
        blur.currentTime = main.currentTime;
      }
    };
    main.addEventListener("timeupdate", sync);
    return () => main.removeEventListener("timeupdate", sync);
  }, []);

  if (failed) return null;

  return (
    <div className={`stage${speaking ? " speaking" : ""}`}>
      <video ref={blurRef} className="blur" src={src}
             autoPlay muted playsInline preload="auto" />
      <video
        ref={mainRef}
        className="face"
        src={src}
        autoPlay
        muted
        playsInline
        preload="auto"
        onEnded={onEnded}
        onError={() => {
          setFailed(true);
          onEnded?.();
        }}
      />
      <div className="scrim" />
    </div>
  );
}
