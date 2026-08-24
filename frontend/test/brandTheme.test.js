import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const brand = readFileSync(new URL("../src/components/BrandMark.jsx", import.meta.url), "utf8");
const main = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/storybook-theme.css", import.meta.url), "utf8");
const role = readFileSync(new URL("../src/screens/RoleScreen.jsx", import.meta.url), "utf8");
const elderHome = readFileSync(new URL("../src/screens/FamilyScreen.jsx", import.meta.url), "utf8");
const summary = readFileSync(new URL("../src/screens/SummaryScreen.jsx", import.meta.url), "utf8");
const familyDashboard = readFileSync(new URL("../src/screens/DasoniHomeTab.jsx", import.meta.url), "utf8");
const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");

test("새 다소니 캐릭터를 모든 화면의 공통 브랜드 자산으로 사용한다", () => {
  assert.ok(existsSync(new URL("../public/brand/dasoni-mascot.png", import.meta.url)));
  assert.match(brand, /src="\/brand\/dasoni-mascot\.png"/);
  assert.match(brand, /dasoni-mascot/);
  assert.match(role, /<BrandMark size=\{162\}/);
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
  assert.match(theme, /family-face \{ width: 112px; height: 112px;/);
  assert.match(theme, /family-face \{ width: 108px; height: 108px;/);
  assert.match(theme, /family-face \{ width: 96px; height: 96px;/);
  assert.match(theme, /family-grid[^}]+overflow: hidden/);
});

test("일반 실행은 스플래시 뒤 역할 선택과 실제 연동 흐름으로 이어진다", () => {
  assert.ok(app.indexOf("if (!directElder && !booted)") < app.indexOf("if (!directElder && !role)"));
  assert.match(app, /setBooted\(true\);[\s\S]*window\.location\.hash = "";/);
  assert.doesNotMatch(app, /window\.location\.hash = picked === "child"/);
});

test("가족 메인 홈은 이동 카드 없이 오늘의 핵심 정보만 요약한다", () => {
  assert.match(familyDashboard, /오늘의 핵심 수치/);
  assert.match(familyDashboard, /직접 확인/);
  assert.match(familyDashboard, /표시 예시/);
  assert.match(familyDashboard, /약 복용 확인/);
  assert.doesNotMatch(familyDashboard, /오늘의 기록|최근 통화/);
  assert.doesNotMatch(familyDashboard, /<button/);
  assert.match(child, /className=\{`child-brand child-brand-home/);
  assert.doesNotMatch(child, /다소니 홈|메인으로 돌아가기/);
  assert.match(theme, /\.dasoni-home-status \{ display: grid; grid-template-columns: repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(theme, /\.dasoni-attention-item/);
  assert.match(theme, /dasoni-attention-item small[^}]+font-size: calc\(13px/);
  assert.match(theme, /dasoni-attention-item h3[^}]+font-size: calc\(21px/);
  assert.match(theme, /--home-title-fit/);
  assert.doesNotMatch(theme, /dasoni-home-copy h1[^}]+text-overflow: ellipsis/);
  assert.match(theme, /\.app-device-family \.child-screen :where\([^)]+\)[^{]+\{[\s\S]*font-family: "Gaegu"/);
});

test("role typography stays consistent throughout each screen tree", () => {
  assert.match(app, /font-role-\$\{fontRole\}/);
  assert.match(app, /shell === "family" \|\| shell === "journey-child" \? "family" : "readable"/);
  assert.match(app, /shell: role === "child" \? "family" : role === "care" \? "care" : "elder"/);
  assert.match(theme, /--font-readable: "Gowun Dodum"/);
  assert.match(theme, /--font-family: "Gaegu"/);
  assert.match(theme, /\.font-role-readable,\s*\.font-role-readable \*\s*\{\s*font-family: var\(--font-readable\) !important;/);
  assert.match(theme, /\.font-role-family,\s*\.font-role-family \*\s*\{\s*font-family: var\(--font-family\) !important;/);
});
