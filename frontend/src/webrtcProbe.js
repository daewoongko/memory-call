/**
 * 이 망에서 P2P 가 붙는가.
 *
 * WebRTC P2P 를 고른 근거와 뒤집는 조건은 README.md §6 "사람 통화를 P2P 로
 * 붙인 이유"에 있다. 2026-08-14 같은 와이파이의 두 기기에서 host ↔ host
 * 연결을 확인했고, 실제 통화도 이 STUN 목록만 사용한다.
 *
 * 판정 규칙만 여기 둔다. 브라우저 API 를 부르는 부분은 아래쪽에 모아 두고,
 * 위쪽은 값만 보고 답을 내는 순수 함수라 시험할 수 있다.
 */

// 서로 다른 사업자의 STUN 을 쓴다. 같은 곳의 서버 둘을 쓰면 매핑이 같게
// 나올 수 있어 대칭 NAT 을 놓친다.
export const STUN_SERVERS = [
  "stun:stun.l.google.com:19302",
  "stun:stun.cloudflare.com:3478",
];

const GATHER_TIMEOUT_MS = 8000;
const CONNECT_TIMEOUT_MS = 20000;

/** "candidate:... typ srflx raddr 192.168.0.5 rport 51234" 를 뜯는다. */
export function parseCandidate(line) {
  if (typeof line !== "string" || !line.includes("candidate:")) return null;
  const parts = line.replace(/^a=/, "").trim().split(/\s+/);
  // candidate:<foundation> <component> <protocol> <priority> <ip> <port> typ <type> ...
  if (parts.length < 8 || parts[6] !== "typ") return null;
  const out = {
    protocol: parts[2]?.toLowerCase(),
    address: parts[4],
    port: Number(parts[5]),
    type: parts[7],
    relatedAddress: null,
    relatedPort: null,
  };
  for (let i = 8; i < parts.length - 1; i += 1) {
    if (parts[i] === "raddr") out.relatedAddress = parts[i + 1];
    if (parts[i] === "rport") out.relatedPort = Number(parts[i + 1]);
  }
  return out;
}

/**
 * 대칭 NAT 인가.
 *
 * **같은 로컬 포트**에서 나간 매핑끼리만 비교해야 한다. RTCPeerConnection 을
 * 두 개 만들어 비교하면 로컬 포트가 서로 달라서 멀쩡한 NAT 도 대칭으로
 * 잘못 읽는다. 그래서 하나의 연결에 STUN 서버 둘을 넣고 rport 로 묶는다.
 */
export function inferNat(candidates) {
  const reflexive = candidates.filter((item) => item?.type === "srflx");
  if (!reflexive.length) {
    return {
      stunReachable: false,
      symmetric: null,
      note: "STUN 에 닿지 못했습니다. 방화벽이 UDP 를 막고 있을 수 있어요.",
    };
  }

  const byLocalPort = new Map();
  for (const item of reflexive) {
    // rport 를 못 읽는 브라우저에서는 묶을 수 없다. 모르면 모른다고 한다.
    if (item.relatedPort == null) continue;
    const seen = byLocalPort.get(item.relatedPort) ?? new Set();
    seen.add(item.port);
    byLocalPort.set(item.relatedPort, seen);
  }

  const comparable = [...byLocalPort.values()].filter((ports) => ports.size > 0);
  const measured = comparable.some((ports) => ports.size > 1);
  const enough = comparable.length > 0 &&
    reflexive.filter((item) => item.relatedPort != null).length >= 2;

  if (measured) {
    return {
      stunReachable: true,
      symmetric: true,
      note: "같은 로컬 포트가 서버마다 다른 포트로 매핑됩니다 (대칭 NAT).",
    };
  }
  if (!enough) {
    return {
      stunReachable: true,
      symmetric: null,
      note: "STUN 응답이 하나뿐이라 대칭 여부를 가릴 수 없었습니다.",
    };
  }
  return {
    stunReachable: true,
    symmetric: false,
    note: "서버가 달라도 같은 포트로 매핑됩니다 (대칭 아님).",
  };
}

/** 공인 주소를 그대로 보여주지 않는다. 화면 갈무리가 그대로 공유된다. */
export function maskAddress(address) {
  if (typeof address !== "string" || !address) return "";
  if (address.includes(":")) {
    const head = address.split(":").slice(0, 2).join(":");
    return `${head}:…`;
  }
  const octets = address.split(".");
  if (octets.length !== 4) return "…";
  return `${octets[0]}.${octets[1]}.×.×`;
}

const PAIR_LABEL = {
  host: "같은 망에서 직접",
  srflx: "STUN 으로 NAT 통과",
  prflx: "STUN 으로 NAT 통과",
  relay: "TURN 릴레이 경유",
};

/** 실제로 고른 경로가 무엇이었나. */
export function describePair(pair) {
  if (!pair) return { route: null, label: "경로를 확인하지 못했습니다" };
  const kinds = [pair.localType, pair.remoteType].filter(Boolean);
  const route = kinds.includes("relay")
    ? "relay"
    : kinds.some((kind) => kind === "srflx" || kind === "prflx")
      ? "srflx"
      : kinds.length ? "host" : null;
  return { route, label: PAIR_LABEL[route] ?? "경로를 확인하지 못했습니다" };
}

/**
 * 최종 판정.
 *
 * 이 앱에서 연결 실패는 장애가 아니라 AI 가 대신 받는 정상 동작이다. 그래도
 * 발표장에서 사람 통화를 보여주려면 붙어야 하므로, 붙지 않을 때 무엇을
 * 해야 하는지까지 말해 준다.
 */
export function overallVerdict({ nat, connected, pair }) {
  if (connected) {
    const { route, label } = describePair(pair);
    if (route === "relay") {
      return { level: "warn", headline: "TURN 을 거쳐 붙었습니다",
               detail: `${label}. 직접 연결은 실패했습니다.` };
    }
    return { level: "ok", headline: "P2P 로 붙습니다",
             detail: `${label}. 이 환경에서는 TURN 없이 됩니다.` };
  }
  if (nat?.stunReachable === false) {
    return { level: "fail", headline: "STUN 에 닿지 못했습니다",
             detail: "UDP 가 막힌 망입니다. 다른 망에서 다시 재보세요." };
  }
  if (nat?.symmetric) {
    return { level: "fail", headline: "붙지 않습니다 — TURN 이 필요합니다",
             detail: "대칭 NAT 입니다. iceServers 에 TURN 을 더해야 합니다." };
  }
  return { level: "fail", headline: "붙지 않았습니다",
           detail: "대칭 NAT 은 아닙니다. 망이 기기끼리의 통신을 막고 있을 수 있어요 (와이파이 클라이언트 격리)." };
}

// ─────────────────────────────────────────── 브라우저 API 를 쓰는 부분

export function webrtcSupported() {
  return typeof globalThis.RTCPeerConnection === "function";
}

function newConnection() {
  return new RTCPeerConnection({
    iceServers: [{ urls: STUN_SERVERS }],
    iceCandidatePoolSize: 0,
  });
}

/** 이 기기 혼자서 할 수 있는 진단. 상대가 없어도 절반은 알 수 있다. */
export async function probeLocal() {
  const pc = newConnection();
  const candidates = [];
  try {
    pc.createDataChannel("probe");
    const done = new Promise((resolve) => {
      const finish = () => resolve();
      pc.onicegatheringstatechange = () => {
        if (pc.iceGatheringState === "complete") finish();
      };
      pc.onicecandidate = (event) => {
        if (!event.candidate) return finish();
        const parsed = parseCandidate(event.candidate.candidate);
        if (parsed) candidates.push({ ...parsed, url: event.candidate.url ?? null });
      };
      setTimeout(finish, GATHER_TIMEOUT_MS);
    });
    await pc.setLocalDescription(await pc.createOffer());
    await done;
  } finally {
    pc.close();
  }
  return { candidates, nat: inferNat(candidates) };
}

async function selectedPair(pc) {
  try {
    const stats = await pc.getStats();
    let chosen = null;
    const byId = new Map();
    stats.forEach((report) => byId.set(report.id, report));
    stats.forEach((report) => {
      if (report.type === "candidate-pair" &&
          (report.selected || report.state === "succeeded")) {
        chosen = chosen ?? report;
      }
    });
    if (!chosen) return null;
    return {
      localType: byId.get(chosen.localCandidateId)?.candidateType ?? null,
      remoteType: byId.get(chosen.remoteCandidateId)?.candidateType ?? null,
      roundTripMs: chosen.currentRoundTripTime != null
        ? Math.round(chosen.currentRoundTripTime * 1000) : null,
    };
  } catch {
    return null;
  }
}

/** 오디오·영상 경로의 송출·수신 수치를 한 번 읽는다. */
export async function readMediaStats(pc) {
  const values = {
    localAudioLevel: null,
    packetsSent: 0,
    packetsReceived: 0,
    remoteAudioLevel: null,
    videoPacketsSent: 0,
    videoFramesEncoded: 0,
    videoPacketsReceived: 0,
    videoFramesDecoded: 0,
    outboundVideoSize: null,
    inboundVideoSize: null,
  };
  const stats = await pc.getStats();
  stats.forEach((report) => {
    const kind = report.kind ?? report.mediaType;
    if (report.type === "media-source" && kind === "audio" &&
        Number.isFinite(report.audioLevel)) {
      values.localAudioLevel = Math.max(values.localAudioLevel ?? 0, report.audioLevel);
    }
    if (report.type === "outbound-rtp" && kind === "audio" && !report.isRemote) {
      values.packetsSent += Number(report.packetsSent ?? 0);
    }
    if (report.type === "inbound-rtp" && kind === "audio" && !report.isRemote) {
      values.packetsReceived += Number(report.packetsReceived ?? 0);
      if (Number.isFinite(report.audioLevel)) {
        values.remoteAudioLevel = Math.max(
          values.remoteAudioLevel ?? 0, report.audioLevel,
        );
      }
    }
    if (report.type === "outbound-rtp" && kind === "video" && !report.isRemote) {
      values.videoPacketsSent += Number(report.packetsSent ?? 0);
      values.videoFramesEncoded += Number(report.framesEncoded ?? 0);
      if (Number.isFinite(report.frameWidth) && Number.isFinite(report.frameHeight)) {
        values.outboundVideoSize = `${report.frameWidth}×${report.frameHeight}`;
      }
    }
    if (report.type === "inbound-rtp" && kind === "video" && !report.isRemote) {
      values.videoPacketsReceived += Number(report.packetsReceived ?? 0);
      values.videoFramesDecoded += Number(report.framesDecoded ?? 0);
      if (Number.isFinite(report.frameWidth) && Number.isFinite(report.frameHeight)) {
        values.inboundVideoSize = `${report.frameWidth}×${report.frameHeight}`;
      }
    }
  });
  return values;
}

/** 기존 오디오 진단 호출부가 영상 항목에 영향받지 않도록 유지한다. */
export async function readAudioStats(pc) {
  const values = await readMediaStats(pc);
  return {
    localAudioLevel: values.localAudioLevel,
    packetsSent: values.packetsSent,
    packetsReceived: values.packetsReceived,
    remoteAudioLevel: values.remoteAudioLevel,
  };
}

/**
 * 두 기기를 실제로 붙여 본다.
 *
 * 기본값은 기존 데이터 채널 진단이다. media=true이면 마이크·카메라를 붙이고
 * 연결을 유지한 session을 돌려준다. 화면은 session.stop() 전까지 1초마다
 * 실제 송수신 수치를 받아 어느 단계가 0인지 확인할 수 있다.
 */
export async function probePair({
  role, room, signal, onStage, media = false, localStream = null,
  onLocalStream, onRemoteStream, onStats, onDiagnostic,
}) {
  const pc = newConnection();
  const started = Date.now();
  const stage = (text) => onStage?.(text);
  let channel = null;
  let statsTimer = null;
  let stopSignal = null;
  let ownedStream = null;
  const remoteStream = new MediaStream();
  const queuedIce = [];
  const diagnostics = { sendFailures: 0, pollFailures: 0, signalFailures: 0 };
  const reportDiagnostic = (kind, reason) => {
    const key = `${kind}Failures`;
    if (key in diagnostics) diagnostics[key] += 1;
    onDiagnostic?.({
      ...diagnostics,
      lastError: reason?.message ?? String(reason ?? ""),
    });
  };

  const close = () => {
    clearInterval(statsTimer);
    statsTimer = null;
    stopSignal?.();
    stopSignal = null;
    try { channel?.close(); } catch { /* 이미 닫힌 채널 */ }
    try { pc.close(); } catch { /* 이미 닫힌 연결 */ }
    ownedStream?.getTracks().forEach((track) => track.stop());
    remoteStream.getTracks().forEach((track) => track.stop());
  };

  if (media) {
    if (!localStream) {
      ownedStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      });
      localStream = ownedStream;
    }
    onLocalStream?.(localStream);
    localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
    pc.ontrack = (event) => {
      const tracks = event.streams?.[0]?.getTracks?.() ?? [event.track];
      tracks.filter(Boolean).forEach((track) => {
        if (!remoteStream.getTracks().some((item) => item.id === track.id)) {
          remoteStream.addTrack(track);
        }
      });
      onRemoteStream?.(remoteStream);
    };
  }

  const finished = new Promise((resolve) => {
    const settle = (ok) => resolve(ok);
    pc.onconnectionstatechange = () => {
      stage(`연결 상태: ${pc.connectionState}`);
      if (pc.connectionState === "connected") settle(true);
      if (pc.connectionState === "failed") settle(false);
    };
    setTimeout(() => settle(pc.connectionState === "connected"), CONNECT_TIMEOUT_MS);
  });

  pc.onicecandidate = (event) => {
    if (!event.candidate) return;
    signal.send("ice", event.candidate.toJSON())
      .catch((reason) => reportDiagnostic("send", reason));
  };

  if (role === "caller") {
    if (!media) channel = pc.createDataChannel("probe");
    stage("초대장을 만드는 중");
    await pc.setLocalDescription(await pc.createOffer());
    try {
      await signal.send("offer", pc.localDescription);
    } catch (reason) {
      reportDiagnostic("send", reason);
      throw reason;
    }
  } else if (!media) {
    pc.ondatachannel = (event) => { channel = event.channel; };
  }

  stopSignal = signal.listen(async (message) => {
    try {
      if (message.kind === "offer" && role === "answerer") {
        stage("초대장을 받았습니다");
        await pc.setRemoteDescription(message.payload);
        while (queuedIce.length) await pc.addIceCandidate(queuedIce.shift());
        await pc.setLocalDescription(await pc.createAnswer());
        try {
          await signal.send("answer", pc.localDescription);
        } catch (reason) {
          reportDiagnostic("send", reason);
          throw reason;
        }
      } else if (message.kind === "answer" && role === "caller") {
        stage("응답을 받았습니다");
        await pc.setRemoteDescription(message.payload);
        while (queuedIce.length) await pc.addIceCandidate(queuedIce.shift());
      } else if (message.kind === "ice") {
        if (!pc.remoteDescription) queuedIce.push(message.payload);
        else await pc.addIceCandidate(message.payload);
      }
    } catch (reason) {
      reportDiagnostic("signal", reason);
    }
  });

  const connected = await finished;
  const pair = await selectedPair(pc);
  const elapsedMs = Date.now() - started;
  if (!connected || !media) {
    close();
    return { connected, pair, elapsedMs, diagnostics };
  }

  const sample = async () => {
    try {
      onStats?.({ ...(await readMediaStats(pc)), sampledAt: Date.now() });
    } catch (reason) {
      reportDiagnostic("signal", reason);
    }
  };
  await sample();
  statsTimer = setInterval(sample, 1000);

  return {
    connected,
    pair,
    elapsedMs,
    diagnostics,
    localStream,
    remoteStream,
    stop: close,
  };
}
