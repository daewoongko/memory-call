import assert from "node:assert/strict";
import test from "node:test";

import {
  inferNat,
  maskAddress,
  overallVerdict,
  parseCandidate,
  readAudioStats,
  readMediaStats,
} from "../src/webrtcProbe.js";

const srflx = (port, rport) => ({
  type: "srflx", protocol: "udp", address: "203.0.113.7", port,
  relatedAddress: "192.168.0.5", relatedPort: rport,
});

test("파싱: srflx 후보에서 매핑 포트와 로컬 포트를 뽑는다", () => {
  const parsed = parseCandidate(
    "candidate:2 1 udp 1686052607 203.0.113.7 54321 typ srflx " +
    "raddr 192.168.0.5 rport 51234 generation 0"
  );
  assert.equal(parsed.type, "srflx");
  assert.equal(parsed.port, 54321);
  assert.equal(parsed.relatedPort, 51234);
});

test("파싱: 후보가 아닌 줄은 버린다", () => {
  assert.equal(parseCandidate("a=mid:0"), null);
  assert.equal(parseCandidate(""), null);
  assert.equal(parseCandidate(undefined), null);
});

test("STUN 응답이 없으면 도달 실패로 본다", () => {
  const nat = inferNat([{ type: "host", port: 51234, relatedPort: null }]);
  assert.equal(nat.stunReachable, false);
  assert.equal(nat.symmetric, null);
});

test("같은 로컬 포트가 서버마다 다르게 매핑되면 대칭 NAT", () => {
  const nat = inferNat([srflx(54321, 51234), srflx(54999, 51234)]);
  assert.equal(nat.symmetric, true);
});

test("서버가 달라도 매핑이 같으면 대칭이 아니다", () => {
  const nat = inferNat([srflx(54321, 51234), srflx(54321, 51234)]);
  assert.equal(nat.symmetric, false);
});

test("로컬 포트가 다른 매핑끼리는 비교하지 않는다", () => {
  // RTCPeerConnection 두 개로 잰 것과 같은 상황이다. 로컬 포트가 다르면
  // 멀쩡한 NAT 도 포트가 달라지므로, 이것을 대칭으로 읽으면 오진이다.
  const nat = inferNat([srflx(54321, 51234), srflx(54999, 51999)]);
  assert.notEqual(nat.symmetric, true);
});

test("STUN 응답이 하나뿐이면 판별하지 않는다", () => {
  const nat = inferNat([srflx(54321, 51234)]);
  assert.equal(nat.stunReachable, true);
  assert.equal(nat.symmetric, null);
});

test("공인 주소는 가려서 보여준다", () => {
  assert.equal(maskAddress("203.0.113.7"), "203.0.×.×");
  assert.equal(maskAddress("2001:db8::1"), "2001:db8:…");
  assert.equal(maskAddress(""), "");
});

test("붙었으면 경로를 알려준다", () => {
  const ok = overallVerdict({
    nat: { stunReachable: true, symmetric: false },
    connected: true,
    pair: { localType: "srflx", remoteType: "srflx" },
  });
  assert.equal(ok.level, "ok");
  assert.match(ok.detail, /STUN/);
});

test("대칭 NAT 에서 실패하면 TURN 이 필요하다고 말한다", () => {
  const fail = overallVerdict({
    nat: { stunReachable: true, symmetric: true },
    connected: false,
    pair: null,
  });
  assert.equal(fail.level, "fail");
  assert.match(fail.detail, /TURN/);
});

test("대칭이 아닌데 실패하면 망이 막는 쪽을 의심한다", () => {
  const fail = overallVerdict({
    nat: { stunReachable: true, symmetric: false },
    connected: false,
    pair: null,
  });
  assert.equal(fail.level, "fail");
  assert.match(fail.detail, /격리/);
});

test("오디오 통계는 송신·수신 패킷과 양쪽 음량을 분리한다", async () => {
  const reports = [
    { type: "media-source", kind: "audio", audioLevel: 0.17 },
    { type: "outbound-rtp", kind: "audio", packetsSent: 31 },
    { type: "inbound-rtp", kind: "audio", packetsReceived: 27, audioLevel: 0.23 },
    { type: "outbound-rtp", kind: "video", packetsSent: 999 },
  ];
  const values = await readAudioStats({
    getStats: async () => ({ forEach: (callback) => reports.forEach(callback) }),
  });
  assert.deepEqual(values, {
    localAudioLevel: 0.17,
    packetsSent: 31,
    packetsReceived: 27,
    remoteAudioLevel: 0.23,
  });
});

test("영상 통계는 송신·수신 프레임과 해상도를 분리한다", async () => {
  const reports = [
    {
      type: "outbound-rtp", kind: "video", packetsSent: 81,
      framesEncoded: 32, frameWidth: 640, frameHeight: 480,
    },
    {
      type: "inbound-rtp", kind: "video", packetsReceived: 73,
      framesDecoded: 29, frameWidth: 320, frameHeight: 240,
    },
  ];
  const values = await readMediaStats({
    getStats: async () => ({ forEach: (callback) => reports.forEach(callback) }),
  });
  assert.equal(values.videoPacketsSent, 81);
  assert.equal(values.videoFramesEncoded, 32);
  assert.equal(values.outboundVideoSize, "640×480");
  assert.equal(values.videoPacketsReceived, 73);
  assert.equal(values.videoFramesDecoded, 29);
  assert.equal(values.inboundVideoSize, "320×240");
});
