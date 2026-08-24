import { useEffect, useState } from "react";
import SelfView from "../components/SelfView.jsx";
import { CallControlButton, CallEndConfirm } from "../components/CallControls.jsx";
import { useRemotePlayback } from "../useRemotePlayback.js";

/**
 * 가족이 직접 받은 통화.
 *
 * 어르신 입장에서 이 화면과 AI 통화 화면은 같은 종류의 일이어야 한다.
 * 얼굴이 보이고, 이름이 있고, 끊는 버튼이 하나 있다. 누가 받았는지에 따라
 * 화면의 구조가 달라지면 어르신이 그 차이를 눈치채고 혼란스러워한다.
 *
 * 음성·영상은 callTransport 하나가 소유한다. 붙지 않으면 이 화면에서 오류를
 * 설명하지 않고 AI 통화 화면으로 자연스럽게 넘어간다.
 */

function clock(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function HumanCallScreen({
  name, face, answeredAt, localStream, remoteStream, onEnd,
}) {
  const [seconds, setSeconds] = useState(0);
  const [muted, setMuted] = useState(false);
  const [confirmingEnd, setConfirmingEnd] = useState(false);
  const {
    mediaRef: remoteRef, blocked, playing, rendered, play,
  } = useRemotePlayback(remoteStream);
  const hasRemoteVideo = Boolean(
    remoteStream?.getVideoTracks?.().some((track) => track.readyState === "live"),
  );

  useEffect(() => {
    const rawAnsweredAt = String(answeredAt || "");
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(rawAnsweredAt);
    const started = new Date(
      rawAnsweredAt && !hasTimezone ? `${rawAnsweredAt}Z` : rawAnsweredAt,
    ).getTime();
    const base = Number.isNaN(started) ? Date.now() : started;
    const tick = () =>
      setSeconds(Math.max(0, Math.floor((Date.now() - base) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [answeredAt]);

  useEffect(() => {
    localStream?.getAudioTracks?.().forEach((track) => {
      track.enabled = !muted;
    });
  }, [localStream, muted]);

  const finishCall = () => {
    setConfirmingEnd(false);
    onEnd?.();
  };

  return (
    <div className={`screen human-call${rendered ? " remote-visible" : ""}`}>
      <video
        ref={remoteRef}
        className={`human-remote-video${hasRemoteVideo ? " live" : ""}`}
        autoPlay
        playsInline
        poster={face || undefined}
      />
      {blocked && (
        <button className="remote-sound-enable" onClick={play}>
          소리 켜기
        </button>
      )}
      {!rendered && !blocked && (
        <p className="remote-video-status">
          {hasRemoteVideo && playing ? "영상을 불러오고 있어요" : "영상 연결 중"}
        </p>
      )}

      <div className="human-call-meta">
        <strong>{name}</strong>
        <span>통화 중 · {clock(seconds)}</span>
      </div>

      <SelfView stream={localStream} />

      {!confirmingEnd && <div className="controls human-call-controls">
        <CallControlButton
          type="microphone"
          label={muted ? "마이크 꺼짐" : "마이크"}
          className={muted ? "muted" : ""}
          onClick={() => setMuted((current) => !current)}
          aria-pressed={muted}
        />
        <CallControlButton
          type="end"
          label="통화 종료"
          className="danger"
          onClick={() => setConfirmingEnd(true)}
        />
      </div>}
      <CallEndConfirm
        open={confirmingEnd}
        onCancel={() => setConfirmingEnd(false)}
        onConfirm={finishCall}
      />
    </div>
  );
}
