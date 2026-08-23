import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const family = readFileSync(new URL("../src/screens/FamilyScreen.jsx", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../src/screens/GuardianOnboardingScreen.jsx", import.meta.url), "utf8");

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

test("통화 대기는 초 단위 벨 타이머 없이 모핑 전체를 재생한다", () => {
  assert.match(app, /connectAI\(person\?\.persona_id\)/);
  assert.doesNotMatch(app, /setSecondsLeft|secondsLeft=/);
  assert.doesNotMatch(app, /15000/);
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
