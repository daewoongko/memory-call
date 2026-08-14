import { useCallback, useEffect, useRef, useState } from "react";

/** 원격 미디어를 붙이고 자동재생 거부를 숨기지 않는다. */
export function useRemotePlayback(stream) {
  const mediaRef = useRef(null);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [rendered, setRendered] = useState(false);

  const refresh = useCallback(() => {
    const media = mediaRef.current;
    if (!media) return;
    setPlaying(Boolean(media.srcObject && !media.paused && !media.ended));
    setRendered(Boolean(
      media.srcObject
      && media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
      && (media.videoWidth || 0) > 0
      && (media.videoHeight || 0) > 0
    ));
  }, []);

  const play = useCallback(async () => {
    const media = mediaRef.current;
    if (!media?.srcObject) return false;
    media.muted = false;
    media.volume = 1;
    try {
      await media.play();
      setBlocked(false);
      setError("");
      refresh();
      return true;
    } catch (reason) {
      setBlocked(true);
      setError(`${reason?.name || "PlaybackError"}: ${reason?.message || "재생이 차단되었습니다."}`);
      refresh();
      return false;
    }
  }, [refresh]);

  useEffect(() => {
    const media = mediaRef.current;
    if (!media) return undefined;

    const onPlaying = () => {
      setPlaying(true);
      setBlocked(false);
      setError("");
      refresh();
    };
    const onStopped = () => refresh();
    const onMediaError = () => {
      setPlaying(false);
      setError(media.error?.message || "원격 미디어를 재생하지 못했습니다.");
    };
    ["loadedmetadata", "loadeddata", "canplay", "resize"].forEach((name) => {
      media.addEventListener(name, refresh);
    });
    media.addEventListener("playing", onPlaying);
    media.addEventListener("pause", onStopped);
    media.addEventListener("ended", onStopped);
    media.addEventListener("error", onMediaError);

    media.srcObject = stream || null;
    setBlocked(false);
    setError("");
    setPlaying(false);
    setRendered(false);
    if (stream) play();
    const timer = stream ? setInterval(refresh, 500) : null;

    return () => {
      if (timer) clearInterval(timer);
      ["loadedmetadata", "loadeddata", "canplay", "resize"].forEach((name) => {
        media.removeEventListener(name, refresh);
      });
      media.removeEventListener("playing", onPlaying);
      media.removeEventListener("pause", onStopped);
      media.removeEventListener("ended", onStopped);
      media.removeEventListener("error", onMediaError);
      if (media.srcObject === stream) media.srcObject = null;
    };
  }, [stream, play, refresh]);

  return { mediaRef, blocked, error, playing, rendered, play };
}
