import { useEffect, useRef } from "react";

/**
 * MuseTalk가 만든 한 문장 영상을 기존 통화 무대 위에 잠시 덮는다.
 * 원본 영상 하나만 소리를 내고, 흐린 배경 복제본은 항상 음소거한다.
 */
export default function LipSyncStage({ src, active, videoRef }) {
  const blurRef = useRef(null);

  useEffect(() => {
    const main = videoRef.current;
    const blur = blurRef.current;
    if (!main || !blur) return undefined;

    const sync = () => {
      if (Math.abs(blur.currentTime - main.currentTime) > 0.12) {
        blur.currentTime = main.currentTime;
      }
    };
    const playBlur = () => {
      blur.currentTime = main.currentTime;
      blur.play().catch(() => {});
    };
    const pauseBlur = () => blur.pause();

    main.addEventListener("playing", playBlur);
    main.addEventListener("timeupdate", sync);
    main.addEventListener("pause", pauseBlur);
    main.addEventListener("ended", pauseBlur);
    return () => {
      main.removeEventListener("playing", playBlur);
      main.removeEventListener("timeupdate", sync);
      main.removeEventListener("pause", pauseBlur);
      main.removeEventListener("ended", pauseBlur);
      blur.pause();
    };
  }, [src, videoRef]);

  return (
    <div
      className={`stage lipsync-stage${active ? " active" : ""}`}
      aria-hidden={!active}
    >
      <video
        ref={blurRef}
        className="blur"
        src={src ?? undefined}
        muted
        playsInline
        preload="auto"
      />
      <video
        ref={videoRef}
        className="face"
        src={src ?? undefined}
        playsInline
        preload="auto"
      />
      <div className="scrim" />
    </div>
  );
}
