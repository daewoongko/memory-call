import { useEffect } from "react";

/**
 * MuseTalk가 만든 한 문장 영상을 기존 통화 무대 위에 잠시 덮는다.
 * 원본 영상 하나만 소리를 내고, 흐린 배경 복제본은 항상 음소거한다.
 *
 * 두 영상의 src 는 useSpeech 가 직접 넣고 뺀다. React 상태로 넣으면 커밋이
 * blob 해제보다 늦어, 이미 해제된 blob 을 가리키는 영상이 남는다.
 */
export default function LipSyncStage({
  active,
  videoRef,
  blurRef,
  anamActive = false,
  anamVideoRef,
  anamVideoElementId,
}) {
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
  }, [videoRef, blurRef]);

  return (
    <div
      className={`stage lipsync-stage${active ? " active" : ""}${anamActive ? " anam-active" : ""}`}
      aria-hidden={!active}
    >
      <video ref={blurRef} className="blur musetalk-media" muted playsInline preload="auto" />
      <video ref={videoRef} className="face musetalk-media" playsInline preload="auto" />
      <video
        id={anamVideoElementId}
        ref={anamVideoRef}
        className="face anam-media"
        autoPlay
        playsInline
      />
      <div className="scrim" />
    </div>
  );
}
