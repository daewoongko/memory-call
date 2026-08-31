import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const brand = readFileSync(new URL("../src/components/BrandMark.jsx", import.meta.url), "utf8");
const main = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/storybook-theme.css", import.meta.url), "utf8");
const role = readFileSync(new URL("../src/screens/RoleScreen.jsx", import.meta.url), "utf8");
const elderHome = readFileSync(new URL("../src/screens/FamilyScreen.jsx", import.meta.url), "utf8");
const summary = readFileSync(new URL("../src/screens/SummaryScreen.jsx", import.meta.url), "utf8");
const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const call = readFileSync(new URL("../src/screens/CallScreen.jsx", import.meta.url), "utf8");
const humanCall = readFileSync(new URL("../src/screens/HumanCallScreen.jsx", import.meta.url), "utf8");
const guardianCall = readFileSync(new URL("../src/screens/GuardianCallOverlay.jsx", import.meta.url), "utf8");
const callControls = readFileSync(new URL("../src/components/CallControls.jsx", import.meta.url), "utf8");
const calling = readFileSync(new URL("../src/screens/CallingScreen.jsx", import.meta.url), "utf8");

test("새 다소니 캐릭터를 모든 화면의 공통 브랜드 자산으로 사용한다", () => {
  assert.ok(existsSync(new URL("../public/brand/dasoni-mascot.png", import.meta.url)));
  assert.match(brand, /src="\/brand\/dasoni-mascot\.png"/);
  assert.match(brand, /dasoni-mascot/);
  assert.match(role, /<BrandMark size=\{162\}/);
  assert.match(role, /className="role-gateway-wordmark" src="\/brand\/dasoni-wordmark\.png"/);
  assert.doesNotMatch(role, /<div><b>다소니<\/b>/);
  assert.match(theme, /\.role-gateway-simple \.role-gateway-wordmark \{[^}]*transform:translateX\(20px\)/);
  assert.match(theme, /\.role-gateway-simple \.role-gateway-subtitle \{ margin-top:12px; \}/);
  assert.match(role, /role-gateway-simple/);
  assert.match(role, /role-list-item/);
  assert.match(summary, /<BrandMark size=\{168\}/);
});

test("파스텔 그림책 테마는 기존 스타일 뒤에서 전체 역할에 적용된다", () => {
  assert.match(main, /@fontsource\/gaegu\/korean-400\.css/);
  assert.match(main, /@fontsource\/gowun-dodum\/korean-400\.css/);
  assert.match(main, /import "\.\/styles\.css";\s*import "\.\/storybook-theme\.css";/);
  assert.match(theme, /Gaegu/);
  assert.match(theme, /Gowun Dodum/);
  assert.match(theme, /\.role-gateway/);
  assert.match(theme, /\.reassurance-home/);
  assert.match(theme, /\.call-screen/);
  assert.match(theme, /\.app-device-family/);
  assert.match(theme, /\.guardian-dashboard/);
  assert.match(theme, /overflow-x: hidden/);
});

test("어르신 통화 종료 화면은 기술 지표 대신 이해하기 쉬운 완료 안내를 보여준다", () => {
  assert.match(summary, /통화를 잘 마쳤어요/);
  assert.match(summary, /오늘도 따뜻한 이야기를 나눠주셔서 고마워요/);
  assert.match(summary, /summary\.duration_sec/);
  assert.match(summary, /홈으로 돌아가기/);
  assert.doesNotMatch(summary, /오늘의 기록|평균 응답|avg_latency_ms|가족에게 알림/);
});

test("어르신 홈은 큰 가족 사진과 간결한 선택 안내를 사용한다", () => {
  assert.doesNotMatch(elderHome, /가족을 누르면 바로 전화를 걸어드려요/);
  assert.doesNotMatch(elderHome, /media-ready-note|media-readiness-panel/);
  assert.match(elderHome, /className="family-face"/);
  assert.match(elderHome, /마이크 연결이 안 됐어요/);
  assert.match(elderHome, /className="elder-topbar-actions"[\s\S]*?className="elder-topbar-clock"[\s\S]*?className="elder-view-button"/);
  assert.doesNotMatch(elderHome, /<p>\{dateLabel\} · \{timeLabel\}<\/p>/);
  assert.match(theme, /\.elder-topbar-clock \{[\s\S]*?white-space: nowrap/);
  assert.match(theme, /family-face \{ width: 112px; height: 112px;/);
  assert.match(theme, /family-face \{ width: 108px; height: 108px;/);
  assert.match(theme, /family-face \{ width: 96px; height: 96px;/);
  assert.match(theme, /family-grid[^}]+overflow: hidden/);
  assert.match(theme, /\.app-device-default \.reassurance-home-simple \.family-grid \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);[\s\S]*?grid-template-rows: repeat\(4, minmax\(0, 1fr\)\);/);
  assert.match(main, /window\.visualViewport\?\.height \|\| window\.innerHeight/);
  assert.match(main, /--app-height/);
});

test("모핑 연결 안내는 화면 안쪽 하단 카드로 고정된다", () => {
  assert.match(theme, /\.call-stack \.calling-morph-status \{[\s\S]*?inset: auto 16px calc\(18px \+ env\(safe-area-inset-bottom\)\);[\s\S]*?width: auto;[\s\S]*?transform: none;/);
  assert.match(theme, /\.call-stack \.calling-morph-status \.who \{[\s\S]*?overflow-wrap: anywhere/);
});

test("어르신 통화 화면은 상태별 안내와 두 개의 원형 조작만 사용한다", () => {
  assert.doesNotMatch(calling, /다른 가족 선택/);
  assert.match(call, /잘 듣지 못했어요\. 다시 말씀해 주세요/);
  assert.match(call, /말하고 있어요/);
  assert.match(call, /생각하고 있어요/);
  assert.match(call, /듣고 있어요/);
  assert.match(call, /label=\{muted \? "소리 켜기" : "소리 끄기"\}/);
  assert.doesNotMatch(call, /글자로 말하기|type="keyboard"|className="composer"/);
  assert.match(call, /label="전화 끊기"/);
  assert.match(callControls, /통화를 끝낼까요\?/);
  assert.match(humanCall, /setConfirmingEnd\(true\)/);
  assert.match(humanCall, /label=\{muted \? "소리 켜기" : "소리 끄기"\}/);
  assert.match(humanCall, /label="전화 끊기"/);
  assert.match(humanCall, /!confirmingEnd && <div className="controls human-call-controls">/);
  assert.doesNotMatch(call, /SelfView/);
  assert.doesNotMatch(humanCall, /SelfView/);
  assert.match(guardianCall, /<SelfView stream=\{localStream\} \/>/);
  assert.match(guardianCall, /label=\{muted \? "마이크 꺼짐" : "마이크"\}/);
  assert.match(guardianCall, /className="guardian-call-actions guardian-human-controls"/);
  assert.match(guardianCall, /className="guardian-call-actions guardian-intro-actions"/);
  assert.match(guardianCall, /className="guardian-call-cancel"/);
  assert.match(guardianCall, /<CallEndConfirm/);
  assert.match(theme, /\.call-controls \.call-control,[\s\S]*?border-radius: 50%/);
  assert.match(theme, /\.call-voice-wave/);
});

test("일반 실행은 스플래시 뒤 역할 선택과 실제 연동 흐름으로 이어진다", () => {
  assert.ok(app.indexOf("if (!directElder && !booted)") < app.indexOf("if (!directElder && !role)"));
  assert.match(app, /setBooted\(true\);[\s\S]*window\.location\.hash = "";/);
  assert.doesNotMatch(app, /window\.location\.hash = picked === "child"/);
});

test("role typography stays consistent throughout each screen tree", () => {
  assert.match(app, /font-role-\$\{fontRole\}/);
  assert.match(app, /const fontRole = "readable"/);
  assert.match(app, /shell: role === "child" \? "family" : "elder"/);
  assert.match(theme, /--font-readable: "Pretendard Variable", Pretendard, "Noto Sans KR", "Malgun Gothic", sans-serif/);
  assert.match(theme, /--font-family: "Dasoni Forest Letter", "Gaegu", "Gowun Dodum", "Malgun Gothic", sans-serif/);
  assert.match(theme, /@font-face[\s\S]*?font-family: "Dasoni Forest Letter"[\s\S]*?local\("숲을지나서"\)/);
  assert.match(theme, /\.font-role-readable,\s*\.font-role-readable \*\s*\{\s*font-family: var\(--font-readable\) !important;/);
  assert.match(theme, /\.font-role-family,\s*\.font-role-family \*\s*\{\s*font-family: var\(--font-family\) !important;/);
});

test("family settings removes the redundant outer box and expands the primary controls", () => {
  assert.match(theme, /\.app-device-family \.child-family-settings \{ padding: 2px 6px 28px; border: 0; border-radius: 0; background: transparent; \}/);
  assert.match(theme, /\.app-device-family \.family-legacy-picker \{ padding: 0; border: 0; background: transparent; \}/);
  assert.match(theme, /\.app-device-family \.family-profile-photo \{ width: 88px; height: 88px;/);
  assert.match(theme, /\.app-device-family \.family-voice-settings,[\s\S]*?border: 0;[\s\S]*?background: transparent;/);
});

test("the phone-sized login shell always uses a single-column layout", () => {
  assert.match(theme, /\.app-device-login \{[\s\S]*?--app-preview-width: 430px;/);
  assert.match(theme, /\.app-device-login \{[\s\S]*?border: 8px solid #0d563d/);
  assert.match(theme, /\.app-device-login \.login-brand \{[\s\S]*?justify-content: center;/);
  assert.match(theme, /\.app-device-login \.login-card \{[\s\S]*?max-width: 352px;[\s\S]*?border: 0;[\s\S]*?background: transparent;/);
  assert.match(theme, /\.app-device-login \.login-tabs \{[\s\S]*?grid-template-columns: 1fr 1fr;/);
});
