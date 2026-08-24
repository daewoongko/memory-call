import * as api from "./api.js";
import { STUN_SERVERS } from "./webrtcProbe.js";

const SIGNAL_POLL_MS = 500;

/**
 * 사람↔사람 미디어의 단일 창구.
 *
 * 화면은 RTCPeerConnection이나 신호 순서를 알지 않는다. TURN 또는 다른
 * 전송 계층으로 바꾸더라도 이 인터페이스만 유지하면 된다.
 */
export function createTransport({ inviteId, role, localStream, iceServers }) {
  if (!inviteId) throw new Error("inviteId가 필요합니다.");
  if (!['caller', 'answerer'].includes(role)) throw new Error("role이 올바르지 않습니다.");

  const pc = new RTCPeerConnection({
    iceServers: Array.isArray(iceServers) && iceServers.length
      ? iceServers
      : [{ urls: STUN_SERVERS }],
    iceCandidatePoolSize: 2,
  });
  const sender = role;
  const stateListeners = new Set();
  const streamListeners = new Set();
  const diagnosticListeners = new Set();
  const diagnostics = { sendFailures: 0, pollFailures: 0, signalFailures: 0, lastError: "" };
  const remoteStream = new MediaStream();
  const queuedIce = [];
  let cursor = 0;
  let pollTimer = null;
  let disconnectTimer = null;
  let closed = false;
  let started = false;
  let connected = false;

  const emitState = (state) => stateListeners.forEach((cb) => cb(state));
  // React ignores setState calls that reuse the same MediaStream object. Emit a
  // fresh snapshot whenever a track arrives so audio-first/video-second WebRTC
  // delivery reliably re-attaches the complete stream on Android.
  const emitStream = () => {
    const snapshot = new MediaStream(remoteStream.getTracks());
    streamListeners.forEach((cb) => cb(snapshot));
  };
  const recordFailure = (kind, reason) => {
    const key = `${kind}Failures`;
    diagnostics[key] = (diagnostics[key] || 0) + 1;
    diagnostics.lastError = reason?.message ?? String(reason ?? "");
    diagnosticListeners.forEach((cb) => cb({ ...diagnostics }));
  };

  localStream?.getTracks().forEach((track) => {
    if (track.kind === "audio" && "contentHint" in track) track.contentHint = "speech";
    if (track.kind === "video" && "contentHint" in track) track.contentHint = "motion";
    pc.addTrack(track, localStream);
  });

  pc.ontrack = (event) => {
    const source = event.streams?.[0];
    if (source) {
      source.getTracks().forEach((track) => {
        if (!remoteStream.getTracks().some((item) => item.id === track.id)) {
          remoteStream.addTrack(track);
        }
      });
    } else if (event.track) {
      remoteStream.addTrack(event.track);
    }
    event.track?.addEventListener?.("unmute", emitStream, { once: true });
    emitStream();
  };

  pc.onicecandidate = (event) => {
    if (!event.candidate || closed) return;
    api.sendCallSignal(inviteId, {
      sender, kind: "ice", payload: event.candidate.toJSON(),
    }).catch((reason) => recordFailure("send", reason));
  };

  pc.onconnectionstatechange = () => {
    if (closed) return;
    if (pc.connectionState === "connected") {
      connected = true;
      clearTimeout(pollTimer);
      clearTimeout(disconnectTimer);
      pollTimer = null;
      disconnectTimer = null;
      emitState("connected");
    } else if (["failed", "closed"].includes(pc.connectionState)) {
      emitState("failed");
    } else if (["new", "connecting", "disconnected"].includes(pc.connectionState)) {
      emitState("connecting");
      if (pc.connectionState === "disconnected") {
        clearTimeout(disconnectTimer);
        disconnectTimer = setTimeout(() => {
          if (!closed && pc.connectionState === "disconnected") emitState("failed");
        }, 5000);
      }
    }
  };

  async function flushIce() {
    while (queuedIce.length && pc.remoteDescription && !closed) {
      await pc.addIceCandidate(queuedIce.shift());
    }
  }

  async function handleSignal(message) {
    if (closed) return;
    if (message.kind === "offer" && role === "answerer") {
      // StrictMode나 재폴링으로 같은 offer가 와도 answer를 두 번 만들지 않는다.
      if (pc.remoteDescription) return;
      await pc.setRemoteDescription(message.payload);
      await flushIce();
      await pc.setLocalDescription(await pc.createAnswer());
      try {
        await api.sendCallSignal(inviteId, {
          sender, kind: "answer", payload: pc.localDescription.toJSON(),
        });
      } catch (reason) {
        recordFailure("send", reason);
        throw reason;
      }
    } else if (message.kind === "answer" && role === "caller") {
      if (pc.remoteDescription) return;
      await pc.setRemoteDescription(message.payload);
      await flushIce();
    } else if (message.kind === "ice") {
      // ICE가 SDP보다 먼저 오는 것이 정상적으로 가능하다.
      if (!pc.remoteDescription) queuedIce.push(message.payload);
      else await pc.addIceCandidate(message.payload);
    }
  }

  async function poll() {
    if (closed || connected) return;
    try {
      const result = await api.pollCallSignal(inviteId, sender, cursor);
      cursor = result.cursor ?? cursor;
      for (const message of result.messages || []) {
        try {
          await handleSignal(message);
        } catch (reason) {
          recordFailure("signal", reason);
        }
      }
    } catch (reason) {
      // 잠깐의 HTTP 실패 한 번으로 통화를 끊지 않는다. 연결 제한 시간은
      // 호출 화면이 따로 판정한다.
      recordFailure("poll", reason);
    }
    if (!closed && !connected) pollTimer = setTimeout(poll, SIGNAL_POLL_MS);
  }

  async function connect() {
    if (started || closed) return;
    started = true;
    emitState("connecting");
    if (role === "caller") {
      await pc.setLocalDescription(await pc.createOffer());
      try {
        await api.sendCallSignal(inviteId, {
          sender, kind: "offer", payload: pc.localDescription.toJSON(),
        });
      } catch (reason) {
        recordFailure("send", reason);
        throw reason;
      }
    }
    poll();
  }

  async function disconnect() {
    if (closed) return;
    closed = true;
    clearTimeout(pollTimer);
    clearTimeout(disconnectTimer);
    pollTimer = null;
    disconnectTimer = null;
    pc.ontrack = null;
    pc.onicecandidate = null;
    pc.onconnectionstatechange = null;
    try { pc.close(); } catch { /* 이미 닫힘 */ }
    localStream?.getTracks().forEach((track) => track.stop());
    remoteStream.getTracks().forEach((track) => track.stop());
  }

  return {
    connect,
    disconnect,
    onRemoteStream(cb) {
      streamListeners.add(cb);
      if (remoteStream.getTracks().length) cb(new MediaStream(remoteStream.getTracks()));
      return () => streamListeners.delete(cb);
    },
    onStateChange(cb) {
      stateListeners.add(cb);
      return () => stateListeners.delete(cb);
    },
    onDiagnostic(cb) {
      diagnosticListeners.add(cb);
      cb({ ...diagnostics });
      return () => diagnosticListeners.delete(cb);
    },
    getDiagnostics() {
      return { ...diagnostics };
    },
  };
}

const AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: { ideal: 1 },
};

const VIDEO_CONSTRAINTS = {
  facingMode: "user",
  width: { ideal: 640 },
  height: { ideal: 480 },
};

export async function openCallMedia() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("이 브라우저에서는 카메라와 마이크를 사용할 수 없습니다.");
  }
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: AUDIO_CONSTRAINTS,
      video: VIDEO_CONSTRAINTS,
    });
  } catch (videoError) {
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS, video: false });
    } catch {
      throw videoError;
    }
  }
}

/** 벨이 울리기 전에 권한을 한 번 확보하고 즉시 장치를 놓는다. */
export async function preflightCallMedia() {
  const stream = await openCallMedia();
  const result = {
    audio: stream.getAudioTracks().some((track) => track.readyState === "live"),
    video: stream.getVideoTracks().some((track) => track.readyState === "live"),
  };
  stream.getTracks().forEach((track) => track.stop());
  if (!result.audio) {
    throw new DOMException("마이크 권한을 확보하지 못했습니다.", "NotAllowedError");
  }
  return result;
}
