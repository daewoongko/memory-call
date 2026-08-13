import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const familySettings = readFileSync(new URL("../src/screens/FamilyPersonaSettings.jsx", import.meta.url), "utf8");

test("가족 화면은 연결된 어르신과 본인 가족 식별자를 받는다", () => {
  assert.match(child, /ChildScreen\(\{ elderId = "elder_001", myPersonaId = "", onMyPersonaChange \}\)/);
  assert.match(child, /rows\.find\(\(elder\) => elder\.elder_id === elderId\)/);
  assert.doesNotMatch(child, /setPicked\(rows\[0\]\)/);
  assert.match(app, /<ChildScreen elderId=\{elderId\} myPersonaId=\{myPersonaId\}/);
});

test("가족 화면의 날짜는 일별 조회와 통화 필터에 사용된다", () => {
  assert.match(child, /getPeriodSummary\(1, picked\.elder_id, \{ start: selectedDate, end: selectedDate \}\)/);
  assert.match(child, /slice\(0, 10\) === selectedDate/);
  assert.match(child, /type="date" value=\{selectedDate\}/);
});

test("통화 화면은 직접·AI·이어받기 유형과 시간대 보드 및 대화 팝업을 제공한다", () => {
  const callModal = readFileSync(new URL("../src/screens/CallTranscriptModal.jsx", import.meta.url), "utf8");
  assert.match(child, /내가 직접 통화/);
  assert.match(child, /AI가 대신 통화/);
  assert.match(child, /AI 통화 후 직접 연결/);
  assert.match(child, /CALL_PERIODS/);
  assert.match(child, /child-call-period-board/);
  assert.match(child, /setActiveCall\(call\)/);
  assert.match(child, /<CallTranscriptModal/);
  assert.match(callModal, /<Transcript callId=\{call\.call_id\}/);
  assert.match(callModal, /event\.key === "Escape"/);
  assert.match(child, /needsAttention \? `확인 필요/);
  assert.match(callModal, /child-call-problem-badge/);
});

test("가족 추억함은 주별 빨랫줄과 시대순·사진 업로드 흐름을 제공한다", () => {
  const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
  assert.match(child, /label: "가족 추억함"/);
  assert.match(clothesline, /확인된 주마다 한 줄/);
  assert.match(clothesline, /happened_year/);
  assert.match(clothesline, /uploadMemoryPhoto/);
  assert.match(clothesline, /아직 걸지 않은 이야기/);
  assert.match(clothesline, /서랍에 넣어둔 추억/);
});

test("오늘 화면의 중복 카드 두 개가 제거됐다", () => {
  assert.doesNotMatch(child, /함께하는 AI 가족/);
  assert.doesNotMatch(child, /가족이 해볼 일 하나/);
  assert.match(child, /child-heart-collage/);
  assert.match(child, /오늘, 마음에 남은 순간/);
  assert.doesNotMatch(child, /child-today-bento-simple/);
  assert.doesNotMatch(child, /선택한 날/);
  assert.match(child, /id: "today", mark: "♥"/);
  assert.match(child, /heart\?\.missed_word\?\.quote/);
});

test("가족 추억함의 확인 대기 바구니는 접었다 펼칠 수 있다", () => {
  const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
  assert.match(clothesline, /basketOpen/);
  assert.match(clothesline, /useState\(false\)/);
  assert.match(clothesline, /aria-expanded=\{basketOpen\}/);
  assert.match(clothesline, /접기/);
  assert.match(clothesline, /펼치기/);
});

test("설정의 본인 가족 카드에는 나 배지가 표시된다", () => {
  assert.match(child, /readyPersonas\.find\(\(item\) => item\.persona_id === myPersonaId\)/);
  assert.match(child, /<FamilyPersonaSettings[\s\S]*personaId=\{myPersona\?\.persona_id/);
  assert.match(familySettings, /child-me-badge/);
});

test("가족 설정은 본인 한 명의 MBTI와 말투만 인라인으로 편집한다", () => {
  assert.doesNotMatch(child, /AI FAMILY|통화에 등장할 가족이에요|안전한 기본값/);
  assert.match(familySettings, /다시 설정하기/);
  assert.match(familySettings, /CallStyleQuiz/);
  assert.match(familySettings, /말투 세부 조정/);
  assert.match(familySettings, /자주 쓰는 말/);
  assert.match(familySettings, /쓰면 안 되는 말/);
  assert.doesNotMatch(child, /id: "settings", mark: "설정", label: "설정"/);
  assert.match(child, /onMyPersonaChange\?\.\(persona\.persona_id\)/);
});

test("가족 사진 관리는 기존 연령 후보와 모핑 기능을 팝업으로 연다", () => {
  const personaPanel = readFileSync(new URL("../src/screens/PersonaPanel.jsx", import.meta.url), "utf8");
  assert.match(familySettings, /사진 관리/);
  assert.match(familySettings, /role="dialog"/);
  assert.match(familySettings, /<PersonaPanel elderId=\{elderId\} initialPersonaId=\{personaId\} mode="photos"/);
  assert.match(personaPanel, /const photoOnly = mode === "photos"/);
  assert.match(personaPanel, /연령별 후보|과거 얼굴 순서 저장/);
  assert.match(personaPanel, /모핑 영상/);
  assert.match(familySettings, /family-profile-entry/);
  assert.match(familySettings, /className="family-style-current"/);
  assert.doesNotMatch(familySettings, /안심 케어 내비게이터/);
  assert.match(personaPanel, /사진 크게 보기/);
  assert.match(personaPanel, /사진 추가하기/);
  assert.doesNotMatch(personaPanel, /python tools\/make_morph\.py/);
});
