import { useEffect, useState } from "react";
import { createTransport, openCallMedia } from "../callTransport.js";
import SelfView from "../components/SelfView.jsx";
import { useRemotePlayback } from "../useRemotePlayback.js";

/**
 * 보호자에게 걸려온 전화.
 *
 * 보호자 화면은 지금까지 전부 지난 기록을 보는 곳이었다. 전화를 받는 자리가
 * 없었으므로 어르신이 아무리 걸어도 닿을 데가 없었다. 이 화면은 어느 탭을
 * 보고 있든 그 위를 덮는다. 리포트를 읽는 중이라고 전화를 놓치면 안 된다.
 *
 * 거절은 실패가 아니다. 누르는 순간 AI 가 대신 받으므로 어르신 쪽 통화는
 * 끊기지 않는다. 버튼 아래에 그 사실을 적어 두는 이유는, 보호자가 "거절하면
 * 아버지가 혼자 남는다"고 느끼면 누르지 못하기 때문이다.
 */

function elapsed(since) {
  if (!since) return 0;
  const started = new Date(since).getTime();
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.floor((Date.now() - started) / 1000));
}

function clock(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function GuardianCallOverlay({
  invite, connected, elderName, onAnswer, onDecline, onEnd,
  onTransportFailed, busy, error,
}) {
  const call = connected || invite;
  const [seconds, setSeconds] = useState(() => elapsed(connected?.answered_at));
  const [localStream, setLocalStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const {
    mediaRef: remoteRef, blocked, playing, rendered, play,
  } = useRemotePlayback(remoteStream);

  useEffect(() => {
    if (!connected) return undefined;
    setSeconds(elapsed(connected.answered_at));
    const id = setInterval(() => setSeconds(elapsed(connected.answered_at)), 1000);
    return () => clearInterval(id);
  }, [connected]);

  useEffect(() => {
    if (!connected?.invite_id) return undefined;
    let alive = true;
    let transport = null;
    let timeout = null;

    const fail = async () => {
      if (!alive) return;
      alive = false;
      clearTimeout(timeout);
      await transport?.disconnect();
      setLocalStream(null);
      setRemoteStream(null);
      onTransportFailed?.();
    };

    openCallMedia().then(async (stream) => {
      if (!alive) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      setLocalStream(stream);
      transport = createTransport({
        inviteId: connected.invite_id,
        role: "answerer",
        localStream: stream,
      });
      transport.onRemoteStream((next) => alive && setRemoteStream(next));
      transport.onStateChange((state) => {
        if (state === "connected") clearTimeout(timeout);
        if (state === "failed") fail();
      });
      timeout = setTimeout(fail, 12000);
      await transport.connect();
    }).catch(fail);

    return () => {
      alive = false;
      clearTimeout(timeout);
      transport?.disconnect().catch(() => {});
    };
  }, [connected?.invite_id, onTransportFailed]);

  if (!call) return null;

  const who = `${elderName || "어르신"} 어르신`;

  return (
    <div className="guardian-call-scrim" role="dialog" aria-live="assertive"
         aria-label={connected ? `${who}와 통화 중` : `${who}에게서 전화`}>
      <div className={`guardian-call${connected ? " on" : ""}`}>
        <span className="guardian-call-tag">
          {connected ? "통화 중" : "지금 전화가 왔어요"}
        </span>
        <h2>{who}</h2>

        {connected ? (
          <>
            <div className="guardian-media-stage">
              <video ref={remoteRef} autoPlay playsInline />
              {remoteStream && (!playing || !rendered) && (
                <button className="remote-sound-enable" onClick={play}>
                  {blocked ? "소리·영상 재생" : "통화 연결하기"}
                </button>
              )}
              <SelfView stream={localStream} />
            </div>
            <p className="guardian-call-timer">{clock(seconds)}</p>
          </>
        ) : (
          <p className="guardian-call-note">
            받지 않으면 AI 가 대신 받아 통화를 이어갑니다.
          </p>
        )}

        {error && <p className="error">{error}</p>}

        {connected ? (
          <div className="guardian-call-actions">
            <button className="guardian-call-end" onClick={onEnd} disabled={busy}>
              통화 끝내기
            </button>
          </div>
        ) : (
          <>
            <div className="guardian-call-actions">
              <button
                className="guardian-call-answer"
                onClick={() => onAnswer(call.invite_id)}
                disabled={busy}
              >
                받기
              </button>
              <button
                className="guardian-call-decline"
                onClick={() => onDecline(call.invite_id)}
                disabled={busy}
              >
                AI 에게 맡기기
              </button>
            </div>
            <p className="guardian-call-hint">
              맡기면 기다리지 않고 바로 연결돼요. 통화 내용은 리포트로 정리됩니다.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
