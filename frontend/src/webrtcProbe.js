/**
 * 이 망에서 P2P 가 붙는가.
 *
 * WebRTC P2P 를 고른 근거와 뒤집는 조건은 docs/call_transport_decision.md 에
 * 있다. 2026-08-14 같은 와이파이의 두 기기에서 host ↔ host 연결을 확인했고,
 * 실제 통화도 이 STUN 목록만 사용한다.
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

/**
 * 두 기기를 실제로 붙여 본다.
 *
 * 미디어 대신 데이터 채널을 쓴다. ICE 경로는 똑같이 지나가면서 마이크·카메라
 * 권한을 묻지 않으므로, 붙는지만 보려는 목적에 군더더기가 없다.
 */
export async function probePair({ role, room, signal, onStage }) {
  const pc = newConnection();
  const started = Date.now();
  const stage = (text) => onStage?.(text);
  let channel = null;

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
    if (event.candidate) signal.send("ice", event.candidate.toJSON());
  };

  if (role === "caller") {
    channel = pc.createDataChannel("probe");
    stage("초대장을 만드는 중");
    await pc.setLocalDescription(await pc.createOffer());
    await signal.send("offer", pc.localDescription);
  } else {
    pc.ondatachannel = (event) => { channel = event.channel; };
  }

  const stop = signal.listen(async (message) => {
    try {
      if (message.kind === "offer" && role === "answerer") {
        stage("초대장을 받았습니다");
        await pc.setRemoteDescription(message.payload);
        await pc.setLocalDescription(await pc.createAnswer());
        await signal.send("answer", pc.localDescription);
      } else if (message.kind === "answer" && role === "caller") {
        stage("응답을 받았습니다");
        await pc.setRemoteDescription(message.payload);
      } else if (message.kind === "ice") {
        await pc.addIceCandidate(message.payload).catch(() => {});
      }
    } catch {
      // 순서가 어긋난 신호 하나로 시험 전체를 중단하지 않는다.
    }
  });

  const connected = await finished;
  const pair = await selectedPair(pc);
  stop();
  const elapsedMs = Date.now() - started;
  try { channel?.close(); } catch { /* 이미 닫혔을 수 있다 */ }
  pc.close();

  return { connected, pair, elapsedMs };
}
