import { useEffect, useRef, useState } from "react";

/**
 * Anam의 실시간 아바타를 기존 통화 무대 위에 올린다.
 * 스트림의 첫 프레임이 준비될 때까지 아래의 모핑 마지막 프레임을 유지해
 * 검은 화면이나 빈 비디오가 순간적으로 보이지 않게 한다.
 */
export default function LipSyncStage({
  active,
  anamActive = false,
  anamVideoRef,
  anamVideoElementId,
}) {
  const [mediaReady, setMediaReady] = useState(false);
  const backdropRef = useRef(null);

  useEffect(() => {
    const video = anamVideoRef?.current;
    if (!video) return undefined;

    if (!anamActive) {
      const hasLiveVideoTrack = Boolean(
        video.srcObject
          ?.getVideoTracks?.()
          .some((track) => track.readyState !== "ended")
      );
      if (!hasLiveVideoTrack) setMediaReady(false);
      return undefined;
    }

    let cancelled = false;
    const syncMediaState = () => {
      if (cancelled) return;
      const hasLiveVideoTrack = Boolean(
        video.srcObject
          ?.getVideoTracks?.()
          .some((track) => track.readyState !== "ended")
      );
      if (hasLiveVideoTrack || video.readyState >= 2) {
        setMediaReady(true);
        video.play?.().catch(() => {});
      }
    };

    syncMediaState();
    const timer = setInterval(syncMediaState, 120);
    const stopTimer = setTimeout(() => clearInterval(timer), 5000);

    return () => {
      cancelled = true;
      clearInterval(timer);
      clearTimeout(stopTimer);
    };
  }, [anamActive]);

  useEffect(() => {
    const foreground = anamVideoRef?.current;
    const backdrop = backdropRef.current;
    if (!mediaReady || !foreground || !backdrop) return undefined;

    if (foreground.srcObject) {
      backdrop.srcObject = foreground.srcObject;
    } else if (foreground.currentSrc) {
      backdrop.src = foreground.currentSrc;
    }
    backdrop.play().catch(() => {});

    return () => {
      backdrop.pause();
      backdrop.srcObject = null;
      backdrop.removeAttribute("src");
    };
  }, [anamVideoRef, mediaReady]);

  const showAnam = active && anamActive && mediaReady;
  const markReady = () => setMediaReady(true);

  return (
    <div
      className={`stage lipsync-stage${showAnam ? " active anam-active anam-ready" : ""}`}
      aria-hidden={!showAnam}
    >
      <video
        ref={backdropRef}
        className="blur anam-backdrop"
        autoPlay
        muted
        playsInline
        aria-hidden="true"
      />
      <video
        id={anamVideoElementId}
        ref={anamVideoRef}
        className="face anam-media"
        autoPlay
        playsInline
        onLoadedMetadata={markReady}
        onLoadedData={markReady}
        onCanPlay={markReady}
        onPlaying={markReady}
        onEmptied={() => setMediaReady(false)}
      />
      <div className="scrim" />
    </div>
  );
}
