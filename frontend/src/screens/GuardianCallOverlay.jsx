import { useEffect, useState } from "react";
import { createTransport, openCallMedia } from "../callTransport.js";
import * as api from "../api.js";
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

const HUMAN_CONNECT_GRACE_MS = 20000;

export default function GuardianCallOverlay({
  invite, connected, elderName, onAnswer, onDecline, onEnd,
  onTransportFailed, busy, error,
}) {
  const call = connected || invite;
  const [seconds, setSeconds] = useState(() => elapsed(connected?.answered_at));
  const [introClock, setIntroClock] = useState({ inviteId: null, seconds: 0 });
  const [localStream, setLocalStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const {
    mediaRef: remoteRef, blocked, playing, rendered, play,
  } = useRemotePlayback(remoteStream);
  const hasRemoteVideo = Boolean(
    remoteStream?.getVideoTracks?.().some((track) => track.readyState === "live"),
  );

  useEffect(() => {
    if (!connected?.invite_id) {
      setIntroClock({ inviteId: null, seconds: 0 });
      return undefined;
    }
    const initial = Math.max(0, Number(connected.intro_seconds_left || 0));
    const deadline = Date.now() + initial * 1000;
    const tick = () => setIntroClock({
      inviteId: connected.invite_id,
      seconds: Math.max(0, Math.ceil((deadline - Date.now()) / 1000)),
    });
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [connected?.invite_id]);

  const introSeconds = introClock.inviteId === connected?.invite_id
    ? introClock.seconds
    : Math.max(0, Math.ceil(Number(connected?.intro_seconds_left || 0)));
  const introPending = Boolean(connected && introSeconds > 0);
  useEffect(() => {
    if (!connected || introPending) {
      setSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const tick = () => setSeconds(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [connected?.invite_id, introPending]);

  useEffect(() => {
    if (!connected?.invite_id) return undefined;
    let alive = true;
    let transport = null;
    let timeout = null;
    // 받기를 누른 시점부터 재면 24초 인트로가 끝나기 전에 정상 연결을
    // 실패로 닫을 수 있다. 서버가 알려 준 남은 인트로 뒤에 ICE 유예 시간을
    // 더해 두 기기가 같은 마감 시각을 사용하게 한다.
    const remainingIntroMs = Math.max(
      0, Number(connected.intro_seconds_left || 0) * 1000,
    );

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
      const mediaConfig = await api.getCallMediaConfig().catch(() => null);
      transport = createTransport({
        inviteId: connected.invite_id,
        role: "answerer",
        localStream: stream,
        iceServers: mediaConfig?.ice_servers,
      });
      transport.onRemoteStream((next) => alive && setRemoteStream(next));
      transport.onStateChange((state) => {
        if (state === "connected") clearTimeout(timeout);
        if (state === "failed") fail();
      });
      timeout = setTimeout(fail, remainingIntroMs + HUMAN_CONNECT_GRACE_MS);
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
         aria-label={introPending ? "나의 AI 영상을 재생 중" : connected ? `${who}와 통화 중` : `${who}에게서 전화`}>
      <div className={`guardian-call${connected ? " on" : ""}${introPending ? " preparing" : ""}${rendered ? " remote-visible" : ""}`}>
        {(!connected || introPending) && <span className="guardian-call-tag">
          {introPending ? "연결 준비 중" : "지금 전화가 왔어요"}
        </span>}
        {(!connected || introPending) && <h2>{introPending ? "나의 AI 영상을 재생 중" : who}</h2>}

        {introPending ? (
          <div className="guardian-ai-playback">
            <div className="ring-dots" aria-hidden="true"><i /><i /><i /></div>
            <strong>{introSeconds}초</strong>
            <p>어르신에게 대기 음악과 AI 영상이 재생되고 있어요.<br />재생이 끝나면 통화가 자동으로 연결됩니다.</p>
          </div>
        ) : connected ? (
          <>
            <div className="guardian-media-stage">
              <video
                ref={remoteRef}
                className={hasRemoteVideo ? "live" : ""}
                autoPlay
                playsInline
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
              <div className="guardian-call-meta">
                <strong>{who}</strong>
                <span>통화 중 · {clock(seconds)}</span>
              </div>
              <SelfView stream={localStream} />
            </div>
          </>
        ) : (
          <p className="guardian-call-note">
            받지 않으면 AI 가 대신 받아 통화를 이어갑니다.
          </p>
        )}

        {error && !introPending && <p className="error">{error}</p>}

        {connected ? (
          <div className="guardian-call-actions">
            <button className="guardian-call-end" onClick={onEnd} disabled={busy}>
              {introPending ? "연결 취소" : "통화 끝내기"}
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
