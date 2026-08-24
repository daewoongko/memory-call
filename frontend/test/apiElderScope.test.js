import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const family = readFileSync(new URL("../src/screens/FamilyScreen.jsx", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../src/screens/GuardianOnboardingScreen.jsx", import.meta.url), "utf8");
const guardianCall = readFileSync(new URL("../src/screens/GuardianCallOverlay.jsx", import.meta.url), "utf8");
const calling = readFileSync(new URL("../src/screens/CallingScreen.jsx", import.meta.url), "utf8");
const melody = readFileSync(new URL("../src/waitingMelody.js", import.meta.url), "utf8");

test("프로필 조회는 elder_id와 선택한 persona_id를 함께 보낸다", () => {
  assert.match(source, /getProfile\s*=\s*\(personaId, elderId = "elder_001"\)/);
  assert.match(source, /new URLSearchParams\(\{ elder_id: elderId \}\)/);
  assert.match(source, /params\.set\("persona_id", personaId\)/);
});

test("통화 시작 body는 elder_id를 포함한다", () => {
  assert.match(source, /startCall\s*=\s*\(personaId, elderId = "elder_001"\)/);
  assert.match(source, /elder_id: elderId/);
});

test("통화 대기 중 실시간 답변 모델을 미리 준비한다", () => {
  assert.match(source, /prepareCall\s*=\s*\(callId\)/);
  assert.match(source, /\/api\/calls\/\$\{callId\}\/prepare/);
  assert.match(app, /prepareCall\(res\.call_id\)/);
});

test("앱의 프로필·예약 통화·통화 시작은 모두 연결된 어르신을 사용한다", () => {
  assert.match(app, /getProfile\(target\?\.persona_id, elderId\)/);
  assert.match(app, /getPendingCall\(elderId\)/);
  assert.match(app, /startCall\(selectedPersonaId \?\? target\?\.persona_id, elderId\)/);
  assert.match(app, /<FamilyScreen\s+elderId=\{elderId\}/);
});

test("가족 카드 통화는 호출을 만든 뒤 서버 상태에 따라 사람 또는 AI로 연결한다", () => {
  const start = app.slice(
    app.indexOf("async function startCalling"),
    app.indexOf("function answerIncoming"),
  );
  assert.match(start, /api\.ringFamily\(\{/);
  assert.match(start, /persona_id: person\?\.persona_id/);
  assert.match(start, /prepareHumanTransport\(created\.invite_id\)/);
  assert.match(app, /current\.state === "answered"/);
  assert.match(app, /current\.should_take_over/);
  assert.match(app, /api\.takeOverInvite\(inviteId\)/);
  assert.match(app, /current\.state === "ai_takeover"/);
  assert.match(app, /if \(takeoverInFlight\.current\) return/);
  assert.match(app, /setError\(""\);[\s\S]*?cooldownUntil\.current/);
  assert.doesNotMatch(app, /setSecondsLeft|secondsLeft=/);
});

test("가족이 받아도 24초 AI 영상·대기 음악 뒤에 사람 통화를 연다", () => {
  assert.match(app, /startWaitingMelody\(24000\)/);
  assert.match(app, /current\.state === "answered"[\s\S]*?!current\.intro_complete[\s\S]*?setTimeout\(tick, RING_POLL_MS\)/);
  assert.match(app, /introDurationSec=\{invite\?\.intro_duration_sec \?\? 24\}/);
  assert.match(calling, /introDurationSec = 24/);
  assert.match(calling, /onWaitEndedRef\.current\?\.\(\)/);
  assert.match(calling, /잔잔한 음악을 들으며 잠시 기다려 주세요/);
  assert.match(guardianCall, /나의 AI 영상을 재생 중/);
  assert.match(guardianCall, /재생이 끝나면 통화가 자동으로 연결됩니다/);
  assert.match(guardianCall, /remainingIntroMs \+ HUMAN_CONNECT_GRACE_MS/);
  assert.doesNotMatch(guardianCall, /setTimeout\(fail, 12000\)/);
  assert.match(app, /HUMAN_CONNECT_GRACE_MS = 20000/);
  assert.match(melody, /const NOTES = \[/);
  assert.match(melody, /export function startWaitingMelody/);
});

test("어르신 통화 대기 화면은 연결된 어르신의 가족만 조회한다", () => {
  assert.match(family, /getPersonas\(elderId\)/);
  assert.doesNotMatch(family, /getSchedules|getMedications|getMemories/);
});

test("가족 온보딩의 조회와 저장은 같은 elderId로 제한된다", () => {
  assert.match(onboarding, /getPersonas\(elderId\)/);
  assert.match(onboarding, /getPersona\(personaId, elderId\)/);
  assert.match(onboarding, /patchPersona\([\s\S]*selectedId, elderId\)/);
});
