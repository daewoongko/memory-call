import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const login = readFileSync(new URL("../src/screens/LoginScreen.jsx", import.meta.url), "utf8");
const journey = readFileSync(new URL("../src/screens/RoleOnboardingScreen.jsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");

test("root journey requires a server session before role selection", () => {
  assert.match(app, /getCurrentAccount/);
  assert.match(app, /<LoginScreen/);
  assert.match(login, /휴대전화 번호와 숫자 6자리 간편번호/);
  assert.match(api, /Authorization: `Bearer \$\{token\}`/);
});

test("the login screen offers a session-only demo path", () => {
  assert.match(login, /onSkip/);
  assert.match(login, /일단 둘러보기/);
  assert.match(app, /const \[demoMode, setDemoMode\]/);
  assert.match(app, /setAccount\(\{ user_id: "demo", display_name: "체험 사용자" \}\)/);
  assert.match(app, /if \(demoMode\) \{\s*setRoleOnboarded\(true\)/);
});

test("every role resumes server-saved onboarding before its existing home", () => {
  assert.match(app, /getOnboarding\(role\)/);
  assert.match(app, /<RoleOnboardingScreen/);
  assert.match(journey, /elder: \["intro", "consent", "family", "comfort", "practice", "review"\]/);
  assert.match(journey, /child: \["intro", "consent", "connection", "relationship", "photo", "tone", "voice", "review"\]/);
  assert.match(journey, /care: \["intro", "organization", "consent", "assignment", "review"\]/);
  assert.match(journey, /saveOnboarding/);
});

test("consent, invite linking, photo creation and real voice status gate the family flow", () => {
  assert.match(journey, /COMMON_CONSENTS/);
  assert.match(journey, /saveConsents/);
  assert.match(journey, /verifyLinkCode/);
  assert.match(journey, /confirmAvatarPhoto/);
  assert.match(journey, /getVoiceProfile/);
  assert.match(journey, /ivc_prompts_ready/);
});

test("the elder waiting screen keeps the shared introduction honest", () => {
  const calling = readFileSync(new URL("../src/screens/CallingScreen.jsx", import.meta.url), "utf8");
  assert.match(calling, /전화벨이 울리고 있어요/);
  assert.match(calling, /24/);
  assert.match(calling, /잔잔한 음악을 들으며 잠시 기다려 주세요/);
  assert.doesNotMatch(calling, /다소니와 먼저 이야기하기/);
  assert.doesNotMatch(calling, /다른 가족 선택/);
});
