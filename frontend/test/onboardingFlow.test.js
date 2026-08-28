import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const login = readFileSync(new URL("../src/screens/LoginScreen.jsx", import.meta.url), "utf8");
const journey = readFileSync(new URL("../src/screens/RoleOnboardingScreen.jsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");
const storybookTheme = readFileSync(new URL("../src/storybook-theme.css", import.meta.url), "utf8");
const roleScreen = readFileSync(new URL("../src/screens/RoleScreen.jsx", import.meta.url), "utf8");

test("root journey requires a server session before role selection", () => {
  assert.match(app, /getCurrentAccount/);
  assert.match(app, /<LoginScreen/);
  assert.match(login, /휴대전화 번호/);
  assert.match(login, /간편번호 6자리/);
  assert.doesNotMatch(login, /간편번호 찾기|login-find/);
  assert.match(api, /Authorization: `Bearer \$\{token\}`/);
});

test("the login screen offers a session-only demo path", () => {
  assert.match(login, /onSkip/);
  assert.match(login, /체험 사용자로 둘러보기/);
  assert.match(app, /const \[demoMode, setDemoMode\]/);
  assert.match(app, /setAccount\(\{ user_id: "demo", display_name: "체험 사용자" \}\)/);
  assert.match(app, /if \(demoMode\) \{\s*setRoleOnboarded\(true\)/);
});

test("elder and family resume server-saved onboarding before their existing home", () => {
  assert.match(app, /getOnboarding\(role\)/);
  assert.match(app, /<RoleOnboardingScreen/);
  assert.match(journey, /elder: \["elder_consent", "elder_display", "elder_ready"\]/);
  assert.match(journey, /child: \["family_setup", "family_avatar", "family_voice"\]/);
  assert.match(journey, /saveOnboarding/);
});

test("only elder and family are selectable roles", () => {
  assert.match(journey, /ONBOARDING_FLOW_VERSION = "2026-08-25\.v2"/);
  assert.match(app, /saved\.data\?\.onboarding_version === ONBOARDING_FLOW_VERSION/);
  assert.match(roleScreen, /id: "elder"/);
  assert.match(roleScreen, /id: "child"/);
  assert.doesNotMatch(roleScreen, /id: "care"|요양 담당자/);
  assert.match(app, /saved === "elder" \|\| saved === "child"/);
  assert.match(roleScreen, /안녕하세요! 다소니는 처음이신가요\?/);
  assert.match(roleScreen, /title: "어르신",\s*eyebrow: "가족과 이야기"/);
  assert.match(roleScreen, /title: "가족",\s*eyebrow: "어르신과 이야기"/);
  assert.match(roleScreen, /<b>\{role\.title\}<\/b>\s*<small>\{role\.eyebrow\}<\/small>/);
  assert.match(storybookTheme, /\.role-list-item \{[\s\S]*?min-height: 132px;/);
  assert.match(storybookTheme, /\.role-list-body b \{[^}]*color: #202522;[^}]*font-size: calc\(25px \* var\(--font-scale\)\);[^}]*white-space: nowrap;/);
  assert.match(storybookTheme, /\.role-gateway-simple \.role-gateway-brand \{[\s\S]*?transform: translateY\(-24px\);/);
});

test("family setup is condensed to three saved pages with optional consent details", () => {
  assert.match(journey, /child: \["family_setup", "family_avatar", "family_voice"\]/);
  assert.match(journey, /아바타 생성 중/);
  assert.match(journey, /자세히 보기/);
  assert.match(journey, /CompactFamilyConsent/);
  assert.doesNotMatch(journey, /child: \["intro"/);
  assert.doesNotMatch(journey, /step === "family_setup"[\s\S]{0,900}연결 번호 6자리/);
  assert.match(journey, /data\.elder_id \|\| elderId \|\| elders\[0\]\?\.elder_id/);
  assert.match(journey, /data\.display_name \|\| account\.display_name/);
  assert.doesNotMatch(journey, /평소 서로 부르는 말을 그대로 적어 주세요/);
  assert.doesNotMatch(journey, /통화·얼굴·목소리는 돌봄 기능에만 사용해요/);
});

test("family avatar setup restores the six-scene call-style matcher", () => {
  assert.match(journey, /import CallStyleQuiz/);
  assert.match(journey, /calculateCallStyle\(data\.call_style_answers \|\| \{\}\)/);
  assert.match(journey, /말투 질문 6개에 모두 답해 주세요/);
  assert.match(journey, /<CallStyleQuiz[\s\S]{0,240}call_style_answers/);
  assert.doesNotMatch(journey, /const TONE_CHOICES/);
});

test("Daewoong onboarding confirms the current face and walks through the selected morph path", () => {
  assert.match(journey, /DAEWOONG_DEMO_AGE_STAGES/);
  assert.match(journey, /age: 24/);
  assert.match(journey, /age: 8/);
  assert.match(journey, /recommended: "age12_corrected_v3\.png"/);
  assert.match(journey, /isDaewoongDemo/);
  assert.match(journey, /demo_age_selections/);
  assert.match(journey, /AI 추천/);
  assert.equal([...journey.matchAll(/candidates: \[[^\]]+\]/g)].length, 9);
  assert.match(journey, /DAEWOONG_DEMO_ASSET_ROOT = "\/age-candidates"/);
  assert.match(journey, /revisitDemoAgeStage/);
  assert.match(journey, /이전 연령 얼굴 보기/);
  assert.match(journey, /다음 연령 얼굴 보기/);
  assert.doesNotMatch(journey, /className="journey-age-nav"/);
  assert.doesNotMatch(journey, /stageIndex \+ 1\}\/\{DAEWOONG_DEMO_AGE_STAGES\.length/);
  assert.doesNotMatch(journey, /얼굴을 고르면 다음 연령으로 자동으로 넘어가요/);
  assert.doesNotMatch(journey, /28세에서 어린 시절로/);
  assert.doesNotMatch(journey, /선택한 얼굴로 자연스럽게 이어지는 영상을 준비했어요/);
  assert.match(journey, /face_job: complete \? "ready" : "processing"/);
  assert.match(journey, /아바타 준비 완료/);
  assert.match(journey, /className=\{data\.face_job[\s\S]{0,180}\? "ready" : "waiting"\}/);
  assert.match(storybookTheme, /\.journey-avatar-heading i\.waiting \{ animation:journey-hourglass/);
  assert.doesNotMatch(storybookTheme, /\.journey-avatar-heading i \{[^}]*animation:/);
  assert.doesNotMatch(journey, /아바타 생성 상태를 확인할 수 없어요/);
  assert.doesNotMatch(journey, /demo_avatar_url/);
});

test("family onboarding keeps one call-style surface and two horizontal recording rows", () => {
  assert.match(storybookTheme, /\.journey-card \.call-style-quiz \{ padding:0; border:0;/);
  assert.match(storybookTheme, /\.journey-card \.call-style-result \{ grid-template-columns:minmax\(0,1fr\);/);
  assert.match(storybookTheme, /\.journey-card \.voice-recorder-grid \{ grid-template-columns:minmax\(0,1fr\); gap:0;/);
  assert.match(storybookTheme, /\.journey-card \.voice-recorder-card \{ grid-template-columns:105px minmax\(0,1fr\) auto;/);
  assert.match(journey, /기본 목소리로 시작하기|onUseDefaultVoice/);
  assert.match(journey, /!data\.use_default_voice && !profile\.active_voice_type/);
  assert.doesNotMatch(journey, /필수 녹음을 마치면 가족 설정이 완료돼요/);
  assert.doesNotMatch(journey, /연결할 준비가 거의 끝났어요/);
});

test("the elder setup covers assisted setup, readable display, sound and call permissions", () => {
  assert.match(journey, /elder: \["elder_consent", "elder_display", "elder_ready"\]/);
  assert.doesNotMatch(journey, /<p className="eyebrow">함께 확인해요<\/p>/);
  assert.match(storybookTheme, /\.journey-elder-consent-title h2 \{[^}]*white-space:nowrap/);
  assert.match(storybookTheme, /\.journey-elder-compact \.journey-mode-grid\.compact \.journey-choice-check \{ grid-column:2;/);
  assert.match(journey, /setup_mode/);
  assert.match(journey, /with_family/);
  assert.match(journey, /type="range"/);
  assert.match(journey, /SIZE_MIN/);
  assert.match(journey, /journey-display-theme-options/);
  assert.doesNotMatch(journey, /누구에게 전화할지 함께 확인해요/);
  assert.doesNotMatch(journey, /가족 등록을 기다리고 있어요/);
  assert.match(journey, /elder: \{ label: "어르신", title: "함께 확인해요" \}/);
  assert.match(journey, /소리와 통화를 한번 확인해요/);
  assert.match(journey, /안내 목소리를 들어 보세요/);
  assert.match(journey, /영상통화 권한을 확인해요/);
  assert.match(journey, /가족 얼굴을 누르면 전화해요/);
  assert.doesNotMatch(journey, /카드 전체를 누르면 바로 연결을 시작합니다/);
  assert.match(journey, /onTheme/);
  assert.match(journey, /onSize/);
  assert.match(journey, /navigator\.mediaDevices\?\.getUserMedia/);
  assert.match(journey, /speechSynthesis/);
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
  assert.doesNotMatch(calling, /전화벨이 울리고 있어요/);
  assert.match(calling, /24/);
  assert.match(calling, /잔잔한 음악을 들으며 잠시 기다려 주세요/);
  assert.doesNotMatch(calling, /다소니와 먼저 이야기하기/);
  assert.doesNotMatch(calling, /다른 가족 선택/);
});
