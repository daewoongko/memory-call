import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api.js";
import { deviceId, deviceLabel } from "../device.js";
import {
  STUN_SERVERS,
  maskAddress,
  overallVerdict,
  probeLocal,
  probePair,
  webrtcSupported,
} from "../webrtcProbe.js";

/**
 * 이 망에서 P2P 가 붙는가 (#nettest).
 *
 * 사람↔사람 통화를 WebRTC P2P 로 붙이기로 했지만 그 결정은 아직 추론이다
 * (docs/call_transport_decision.md §8). 붙이기 전에 재고, 붙지 않으면 TURN 을
 * 더하거나 관리형 SFU 로 갈아탄다. 발표 전에 알아야 갈아탈 시간이 있다.
 *
 * 화면은 두 층이다. 위는 이 기기 혼자서 알 수 있는 것(STUN 도달·NAT 유형),
 * 아래는 폰 두 대를 실제로 붙여 보는 것. 아래가 진짜 답이다.
 */

const SIGNAL_POLL_MS = 700;

function makeSignal(room, sender, onFailure) {
  return {
    send: (kind, payload) => api.sendSignal(room, { sender, kind, payload }),
    listen: (onMessage) => {
      let alive = true;
      let cursor = 0;
      (async () => {
        while (alive) {
          try {
            const result = await api.pollSignal(room, sender, cursor);
            cursor = result.cursor ?? cursor;
            for (const message of result.messages ?? []) {
              if (!alive) break;
              await onMessage(message);
            }
          } catch (reason) {
            onFailure?.("poll", reason);
          }
          await new Promise((resolve) => setTimeout(resolve, SIGNAL_POLL_MS));
        }
      })();
      return () => { alive = false; };
    },
  };
}

function Row({ label, value, tone }) {
  return <div className="nettest-row">
    <span>{label}</span>
    <b className={tone ? `tone-${tone}` : undefined}>{value}</b>
  </div>;
}

function trackState(stream, kind) {
  const track = stream?.getTracks?.().find((item) => item.kind === kind);
  if (!track) return { text: "없음", tone: "fail" };
  if (track.readyState !== "live") return { text: track.readyState, tone: "fail" };
  if (!track.enabled) return { text: "꺼짐", tone: "fail" };
  if (track.muted) return { text: "일시 무음", tone: "warn" };
  return { text: "정상", tone: "ok" };
}

export default function NetTestScreen() {
  const [local, setLocal] = useState(null);
  const [localError, setLocalError] = useState("");
  const [room, setRoom] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [stage, setStage] = useState("");
  const [running, setRunning] = useState(false);
  const [pairResult, setPairResult] = useState(null);
  const [label, setLabel] = useState("");
  const [saved, setSaved] = useState(false);
  const [history, setHistory] = useState([]);
  const [mode, setMode] = useState("data");
  const [mediaStats, setMediaStats] = useState(null);
  const [localMediaStream, setLocalMediaStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const [playback, setPlayback] = useState({
    paused: true, muted: false, volume: 1, error: "",
    readyState: 0, videoWidth: 0, videoHeight: 0,
  });
  const [diagnostics, setDiagnostics] = useState({
    sendFailures: 0, pollFailures: 0, signalFailures: 0, lastError: "",
  });
  const cancelled = useRef(false);
  const sessionRef = useRef(null);
  const localMediaRef = useRef(null);
  const remoteRef = useRef(null);

  const supported = webrtcSupported();

  useEffect(() => {
    cancelled.current = false;
    if (!supported) {
      setLocalError("이 브라우저는 WebRTC 를 지원하지 않습니다.");
      return () => { cancelled.current = true; };
    }
    probeLocal()
      .then((result) => !cancelled.current && setLocal(result))
      .catch((reason) => !cancelled.current && setLocalError(reason.message));
    return () => { cancelled.current = true; };
  }, [supported]);

  const loadHistory = useCallback(() => {
    api.getNetTestResults(20)
      .then(({ results }) => setHistory(results || []))
      .catch(() => {});
  }, []);
  useEffect(loadHistory, [loadHistory]);

  useEffect(() => () => sessionRef.current?.stop?.(), []);

  const refreshPlayback = useCallback(() => {
    const media = remoteRef.current;
    if (!media) return;
    setPlayback((current) => ({
      ...current,
      paused: media.paused,
      muted: media.muted,
      volume: media.volume,
      readyState: media.readyState,
      videoWidth: media.videoWidth,
      videoHeight: media.videoHeight,
    }));
  }, []);

  const playRemote = useCallback(async () => {
    const media = remoteRef.current;
    if (!media?.srcObject) {
      setPlayback((current) => ({ ...current, error: "상대 미디어가 아직 도착하지 않았습니다." }));
      return;
    }
    media.muted = false;
    media.volume = 1;
    try {
      await media.play();
      setPlayback({
        paused: media.paused,
        muted: media.muted,
        volume: media.volume,
        error: "",
        readyState: media.readyState,
        videoWidth: media.videoWidth,
        videoHeight: media.videoHeight,
      });
    } catch (reason) {
      setPlayback({
        paused: media.paused,
        muted: media.muted,
        volume: media.volume,
        error: `${reason.name || "PlaybackError"}: ${reason.message || "재생이 차단되었습니다."}`,
        readyState: media.readyState,
        videoWidth: media.videoWidth,
        videoHeight: media.videoHeight,
      });
    }
  }, []);

  useEffect(() => {
    const media = remoteRef.current;
    if (!media) return undefined;
    const update = () => refreshPlayback();
    media.addEventListener("play", update);
    media.addEventListener("pause", update);
    media.addEventListener("volumechange", update);
    media.addEventListener("loadedmetadata", update);
    media.addEventListener("loadeddata", update);
    media.addEventListener("canplay", update);
    media.addEventListener("playing", update);
    media.addEventListener("resize", update);
    media.srcObject = remoteStream || null;
    setPlayback({
      paused: true, muted: false, volume: 1, error: "",
      readyState: 0, videoWidth: 0, videoHeight: 0,
    });
    if (remoteStream) playRemote();
    // 일부 모바일 브라우저는 resize/loadedmetadata 이벤트를 놓친다. 실제 렌더링
    // 크기를 짧게 재확인해 보이는 영상에 0×0 경고가 남지 않게 한다.
    const renderTimer = remoteStream ? setInterval(update, 500) : null;
    return () => {
      if (renderTimer) clearInterval(renderTimer);
      media.removeEventListener("play", update);
      media.removeEventListener("pause", update);
      media.removeEventListener("volumechange", update);
      media.removeEventListener("loadedmetadata", update);
      media.removeEventListener("loadeddata", update);
      media.removeEventListener("canplay", update);
      media.removeEventListener("playing", update);
      media.removeEventListener("resize", update);
      if (media.srcObject === remoteStream) media.srcObject = null;
    };
  }, [remoteStream, pairResult?.connected, playRemote, refreshPlayback]);

  useEffect(() => {
    const media = localMediaRef.current;
    if (!media) return undefined;
    media.srcObject = localMediaStream || null;
    if (localMediaStream) media.play().catch(() => {});
    return () => {
      if (media.srcObject === localMediaStream) media.srcObject = null;
    };
  }, [localMediaStream, pairResult]);

  const noteFailure = useCallback((kind, reason) => {
    setDiagnostics((current) => ({
      ...current,
      [`${kind}Failures`]: (current[`${kind}Failures`] || 0) + 1,
      lastError: reason?.message ?? String(reason ?? ""),
    }));
  }, []);

  const run = useCallback(async (activeRoom, role) => {
    sessionRef.current?.stop?.();
    sessionRef.current = null;
    setRunning(true);
    setPairResult(null);
    setMediaStats(null);
    setLocalMediaStream(null);
    setRemoteStream(null);
    setDiagnostics({
      sendFailures: 0, pollFailures: 0, signalFailures: 0, lastError: "",
    });
    setSaved(false);
    setStage("상대를 기다리는 중");
    try {
      const result = await probePair({
        role,
        room: activeRoom,
        signal: makeSignal(activeRoom, deviceId(), noteFailure),
        onStage: setStage,
        media: mode === "media",
        onLocalStream: setLocalMediaStream,
        onRemoteStream: setRemoteStream,
        onStats: setMediaStats,
        onDiagnostic: (next) => setDiagnostics((current) => ({
          sendFailures: Math.max(current.sendFailures, next.sendFailures || 0),
          pollFailures: current.pollFailures,
          signalFailures: Math.max(current.signalFailures, next.signalFailures || 0),
          lastError: next.lastError || current.lastError,
        })),
      });
      sessionRef.current = result;
      setPairResult(result);
      setStage("");
    } catch (reason) {
      setStage(`시험이 끊겼습니다: ${reason.message}`);
    } finally {
      setRunning(false);
    }
  }, [mode, noteFailure]);

  const stopMedia = useCallback(() => {
    sessionRef.current?.stop?.();
    sessionRef.current = null;
    setLocalMediaStream(null);
    setRemoteStream(null);
    setMediaStats(null);
    setPairResult(null);
  }, []);

  const host = useCallback(async () => {
    const { room: created } = await api.createNetTestRoom();
    setRoom(created);
    run(created, "caller");
  }, [run]);

  const join = useCallback(() => {
    const code = joinCode.trim();
    if (!code) return;
    setRoom(code);
    run(code, "answerer");
  }, [joinCode, run]);

  const save = useCallback(async () => {
    const verdict = overallVerdict({ nat: local?.nat, ...pairResult });
    await api.saveNetTestResult({
      room: room || null,
      label: label || null,
      connected: Boolean(pairResult?.connected),
      route: verdict.level === "ok" || verdict.level === "warn"
        ? (pairResult?.pair?.localType === "relay" ? "relay"
          : pairResult?.pair?.localType ?? null)
        : null,
      symmetric: local?.nat?.symmetric ?? null,
      stun_ok: local?.nat?.stunReachable ?? null,
      elapsed_ms: pairResult?.elapsedMs ?? null,
      round_trip_ms: pairResult?.pair?.roundTripMs ?? null,
      user_agent: navigator.userAgent,
    });
    setSaved(true);
    loadHistory();
  }, [local, pairResult, room, label, loadHistory]);

  const reflexive = (local?.candidates ?? []).filter((item) => item.type === "srflx");
  const verdict = pairResult
    ? overallVerdict({ nat: local?.nat, ...pairResult })
    : null;
  const localAudioTrack = trackState(localMediaStream, "audio");
  const localVideoTrack = trackState(localMediaStream, "video");
  const remoteAudioTrack = trackState(remoteStream, "audio");
  const remoteVideoTrack = trackState(remoteStream, "video");

  return <main className="nettest">
    <header>
      <span>P2P 연결 진단</span>
      <h1>이 망에서 통화가 붙나요?</h1>
      <p>
        사람↔사람 통화는 WebRTC P2P 로 붙입니다. 붙지 않는 망이면 AI 가 대신
        받으므로 통화가 끊기지는 않지만, 발표에서 사람 통화를 보여주려면
        미리 재둬야 합니다.
      </p>
    </header>

    <section className="nettest-card">
      <h2>1. 이 기기</h2>
      {localError && <p className="error">{localError}</p>}
      {!local && !localError && <p className="hint">후보를 모으는 중…</p>}
      {local && <>
        <Row
          label="STUN 도달"
          value={local.nat.stunReachable ? "됨" : "안 됨"}
          tone={local.nat.stunReachable ? "ok" : "fail"}
        />
        <Row
          label="NAT 유형"
          value={local.nat.symmetric === null
            ? "판별 못 함"
            : local.nat.symmetric ? "대칭 (P2P 어려움)" : "대칭 아님 (P2P 가능)"}
          tone={local.nat.symmetric === null
            ? "warn" : local.nat.symmetric ? "fail" : "ok"}
        />
        <Row label="공인 주소" value={
          reflexive.length ? maskAddress(reflexive[0].address) : "없음"
        } />
        <Row label="후보 수" value={
          `${local.candidates.length}개 (STUN 경유 ${reflexive.length}개)`
        } />
        <p className="nettest-note">{local.nat.note}</p>
        <details>
          <summary>자세히</summary>
          <ul className="nettest-candidates">
            {local.candidates.map((item, index) => <li key={index}>
              <b>{item.type}</b> {item.protocol} {maskAddress(item.address)}:{item.port}
              {item.relatedPort != null && <em> ← 로컬 :{item.relatedPort}</em>}
            </li>)}
          </ul>
          <p className="nettest-note">STUN: {STUN_SERVERS.join(", ")}</p>
        </details>
      </>}
    </section>

    <section className="nettest-card">
      <h2>2. 폰 두 대로</h2>
      <p className="nettest-note">
        한쪽에서 <b>방 만들기</b>를 누르고, 나온 숫자를 다른 폰에 입력하세요.
        두 폰이 서로 다른 망일 때(하나는 와이파이, 하나는 LTE) 결과가 가장 정확합니다.
      </p>

      {room && <p className="nettest-room">방 번호 <b>{room}</b></p>}

      <div className="nettest-mode" role="group" aria-label="진단 모드">
        <button
          className={mode === "data" ? "on" : ""}
          onClick={() => setMode("data")}
          disabled={running}
        >
          연결만 확인
        </button>
        <button
          className={mode === "media" ? "on" : ""}
          onClick={() => setMode("media")}
          disabled={running}
        >
          오디오·영상 확인
        </button>
      </div>

      <div className="nettest-actions">
        <button onClick={host} disabled={running || !supported}>방 만들기</button>
        <div className="nettest-join">
          <input
            value={joinCode}
            onChange={(event) => setJoinCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            placeholder="방 번호"
            aria-label="방 번호"
          />
          <button onClick={join} disabled={running || !supported || joinCode.length < 6}>
            들어가기
          </button>
        </div>
      </div>

      {running && <p className="hint">{stage || "연결하는 중…"}</p>}

      {verdict && <div className={`nettest-verdict ${verdict.level}`}>
        <b>{verdict.headline}</b>
        <p>{verdict.detail}</p>
        <Row label="연결까지" value={`${(pairResult.elapsedMs / 1000).toFixed(1)}초`} />
        {pairResult.pair?.roundTripMs != null &&
          <Row label="왕복 시간" value={`${pairResult.pair.roundTripMs}ms`} />}
        {pairResult.pair && <Row
          label="고른 경로"
          value={`${pairResult.pair.localType ?? "?"} ↔ ${pairResult.pair.remoteType ?? "?"}`}
        />}

        <div className="nettest-save">
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="어디서 쟀나요 (예: 집 와이파이 ↔ LTE)"
            aria-label="측정 환경"
          />
          <button onClick={save} disabled={saved}>{saved ? "저장됨" : "결과 저장"}</button>
        </div>
      </div>}

      {mode === "media" && pairResult?.connected && <section className="nettest-media-diagnostic">
        <div className="nettest-media-grid">
          <div>
            <header><b>이 폰 → 상대 폰</b><small>내가 보내는 경로</small></header>
            <Row
              label="내 마이크 크기"
              value={mediaStats?.localAudioLevel == null
                ? "측정 대기" : mediaStats.localAudioLevel.toFixed(4)}
              tone={(mediaStats?.localAudioLevel ?? 0) > 0 ? "ok" : "warn"}
            />
            <Row
              label="보낸 패킷"
              value={`${mediaStats?.packetsSent ?? 0}`}
              tone={(mediaStats?.packetsSent ?? 0) > 0 ? "ok" : "fail"}
            />
            <Row label="내 마이크 트랙" value={localAudioTrack.text} tone={localAudioTrack.tone} />
            <Row label="내 카메라 트랙" value={localVideoTrack.text} tone={localVideoTrack.tone} />
            <Row
              label="보낸 영상 패킷 / 프레임"
              value={`${mediaStats?.videoPacketsSent ?? 0} / ${mediaStats?.videoFramesEncoded ?? 0}`}
              tone={(mediaStats?.videoFramesEncoded ?? 0) > 0 ? "ok" : "fail"}
            />
            <Row
              label="보낸 영상 크기"
              value={mediaStats?.outboundVideoSize ?? "측정 대기"}
              tone={mediaStats?.outboundVideoSize ? "ok" : "warn"}
            />
          </div>
          <div>
            <header><b>상대 폰 → 이 폰</b><small>내가 받는 경로</small></header>
            <Row
              label="받은 패킷"
              value={`${mediaStats?.packetsReceived ?? 0}`}
              tone={(mediaStats?.packetsReceived ?? 0) > 0 ? "ok" : "fail"}
            />
            <Row
              label="상대 소리 크기"
              value={mediaStats?.remoteAudioLevel == null
                ? "미지원/대기" : mediaStats.remoteAudioLevel.toFixed(4)}
              tone={(mediaStats?.remoteAudioLevel ?? 0) > 0 ? "ok" : "warn"}
            />
            <Row label="상대 음성 트랙" value={remoteAudioTrack.text} tone={remoteAudioTrack.tone} />
            <Row label="상대 영상 트랙" value={remoteVideoTrack.text} tone={remoteVideoTrack.tone} />
            <Row
              label="받은 영상 패킷 / 프레임"
              value={`${mediaStats?.videoPacketsReceived ?? 0} / ${mediaStats?.videoFramesDecoded ?? 0}`}
              tone={(mediaStats?.videoFramesDecoded ?? 0) > 0 ? "ok" : "fail"}
            />
            <Row
              label="받은 영상 크기"
              value={mediaStats?.inboundVideoSize ?? "측정 대기"}
              tone={mediaStats?.inboundVideoSize ? "ok" : "warn"}
            />
          </div>
          <div className="nettest-playback-state">
          <Row
            label="재생 paused"
            value={String(playback.paused)}
            tone={playback.paused ? "fail" : "ok"}
          />
          <Row
            label="재생 muted / volume"
            value={`${playback.muted} / ${playback.volume}`}
            tone={!playback.muted && playback.volume === 1 ? "ok" : "fail"}
          />
          <Row
            label="화면 렌더링 크기"
            value={playback.videoWidth > 0
              ? `${playback.videoWidth}×${playback.videoHeight}` : "0×0 (검은 화면)"}
            tone={playback.videoWidth > 0 ? "ok" : "fail"}
          />
          </div>
        </div>
        <div className="nettest-media-previews">
          <figure>
            <figcaption>내 카메라</figcaption>
            <video
              ref={localMediaRef}
              className="nettest-local-media"
              autoPlay
              playsInline
              muted
            />
            {localVideoTrack.tone !== "ok" && <span>{localVideoTrack.text}</span>}
          </figure>
          <figure>
            <figcaption>상대 영상</figcaption>
            <video ref={remoteRef} className="nettest-remote-media" autoPlay playsInline />
            {playback.videoWidth === 0 && <span>
              {(mediaStats?.videoFramesDecoded ?? 0) > 0
                ? "영상 프레임은 받았지만 화면에 표시되지 않았습니다."
                : "상대 영상 프레임을 기다리는 중입니다."}
            </span>}
            <button className="nettest-play-media" onClick={playRemote}>
              {playback.paused ? "소리·영상 재생" : "소리·영상 다시 재생"}
            </button>
          </figure>
        </div>
        {playback.error && <div className="nettest-playback-error">
          <b>재생 거부</b>
          <code>{playback.error}</code>
          <button onClick={playRemote}>소리 재생 다시 시도</button>
        </div>}
        <div className="nettest-signal-counts">
          신호 전송 실패 {diagnostics.sendFailures || 0} · 폴링 실패 {diagnostics.pollFailures || 0} · 처리 실패 {diagnostics.signalFailures || 0}
          {diagnostics.lastError && <code>{diagnostics.lastError}</code>}
        </div>
        <button className="nettest-stop" onClick={stopMedia}>미디어 진단 종료</button>
      </section>}
    </section>

    {history.length > 0 && <section className="nettest-card">
      <h2>3. 지금까지 잰 것</h2>
      <ul className="nettest-history">
        {history.map((row) => <li key={row.result_id}>
          <b className={row.connected ? "tone-ok" : "tone-fail"}>
            {row.connected ? "붙음" : "실패"}
          </b>
          <span>{row.label || "이름 없음"}</span>
          <em>
            {row.route || "경로 미상"}
            {row.symmetric === 1 ? " · 대칭 NAT" : ""}
            {row.round_trip_ms != null ? ` · ${row.round_trip_ms}ms` : ""}
          </em>
        </li>)}
      </ul>
      <p className="nettest-note">
        붙지 않는 조합이 나오면 <code>iceServers</code> 에 TURN 을 더합니다.
        근거와 뒤집는 조건은 docs/call_transport_decision.md 에 있습니다.
      </p>
    </section>}

    <p className="nettest-foot">{deviceLabel()} · {deviceId().slice(0, 12)}…</p>
  </main>;
}
