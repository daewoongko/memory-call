import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const familySettings = readFileSync(new URL("../src/screens/FamilyPersonaSettings.jsx", import.meta.url), "utf8");
const callStyleQuiz = readFileSync(new URL("../src/components/CallStyleQuiz.jsx", import.meta.url), "utf8");
const displaySettings = readFileSync(new URL("../src/components/DisplaySettings.jsx", import.meta.url), "utf8");
const analysisReport = readFileSync(new URL("../src/screens/FamilyAnalysisReport.jsx", import.meta.url), "utf8");
const reportTabs = readFileSync(new URL("../src/screens/ReportTabs.jsx", import.meta.url), "utf8");
const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
const dasoniHome = readFileSync(new URL("../src/screens/DasoniHomeTab.jsx", import.meta.url), "utf8");
const transcript = readFileSync(new URL("../src/screens/Transcript.jsx", import.meta.url), "utf8");
const seedGildongDemo = readFileSync(new URL("../../tools/seed_gildong_demo.py", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/storybook-theme.css", import.meta.url), "utf8");
const datePicker = readFileSync(new URL("../src/components/AppDatePicker.jsx", import.meta.url), "utf8");

test("가족 화면은 연결된 어르신과 본인 가족 식별자를 받는다", () => {
  assert.match(child, /ChildScreen\(\{ elderId = "elder_001", myPersonaId = "", onMyPersonaChange, onDisplaySettings \}\)/);
  assert.match(child, /rows\.find\(\(elder\) => elder\.elder_id === elderId\)/);
  assert.doesNotMatch(child, /setPicked\(rows\[0\]\)/);
  assert.match(app, /<ChildScreen elderId=\{elderId\} myPersonaId=\{myPersonaId\}/);
});

test("보호자 메인과 오늘·추억·통화·분석 리포트·설정 다섯 메뉴를 제공한다", () => {
  assert.equal((child.match(/id: "(?:today|memories|calls|analysis|settings)"/g) || []).length, 5);
  assert.match(child, /label: "오늘"/);
  assert.match(child, /label: "추억"/);
  assert.match(child, /label: "통화"/);
  assert.match(child, /label: "분석 리포트"/);
  assert.match(child, /label: "설정"/);
  assert.match(child, /useState\("home"\)/);
  assert.doesNotMatch(child, /id: "home"/);
  assert.match(child, /tab === "home" && <DasoniHomeTab/);
  assert.match(child, /다소니 메인 화면으로 이동/);
  assert.match(dasoniHome, /오늘의 통화와 확인할 소식을 한눈에 모았어요/);
  assert.match(child, /<FamilyAnalysisReport elderId=\{picked\.elder_id\}/);
  assert.match(analysisReport, /getPeriodSummary\(1, elderId/);
  assert.match(analysisReport, /getPeriodSummary\(range\.days, elderId/);
});

test("가족 화면의 날짜는 일별 조회와 통화 필터에 사용된다", () => {
  assert.match(child, /getPeriodSummary\(1, picked\.elder_id, \{ start: selectedDate, end: selectedDate \}\)/);
  assert.match(child, /getReports\(picked\.elder_id, 120, selectedDate\)/);
  assert.match(child, /slice\(0, 10\) === selectedDate/);
  assert.match(child, /<AppDatePicker className="child-date-picker" value=\{selectedDate\}/);
  assert.match(datePicker, /<input ref=\{inputRef\} type="date" value=\{value\}/);
  assert.match(datePicker, /className="app-date-value"/);
  assert.match(child, /weekday: "long"/);
  assert.match(child, /displayValue=\{shortDate\(selectedDate\)\} showValue/);
  assert.match(datePicker, /showPicker/);
  assert.match(datePicker, /else picker\.click\(\)/);
  assert.match(datePicker, /onKeyDown=\{openPickerWithKeyboard\}/);
  assert.match(datePicker, /눌러서 날짜 변경/);
  assert.match(theme, /\.app-date-picker > input \{[\s\S]*pointer-events: none/);
  assert.match(theme, /child-family-header \.child-date-picker > \.app-date-value \{[\s\S]*position: static;[\s\S]*clip-path: none/);
  assert.match(theme, /child-family-header \.child-date-picker > svg \{ display: none; \}/);
  assert.match(styles, /\.app-device-family \.child-date-picker/);
});

test("통화 화면은 직접·AI·이어받기 유형과 시간순 목록 및 대화 팝업을 제공한다", () => {
  const callModal = readFileSync(new URL("../src/screens/CallTranscriptModal.jsx", import.meta.url), "utf8");
  assert.match(child, /가족이 직접 통화/);
  assert.match(child, /다소니가 대신 통화/);
  assert.match(child, /AI 통화 후 가족이 이어받음/);
  assert.doesNotMatch(child, /CALL_PERIODS/);
  assert.doesNotMatch(child, /child-call-period-board/);
  assert.match(child, /child-call-list-item/);
  assert.match(child, /className="child-header-call-title"/);
  assert.doesNotMatch(child, /CALL STORY/);
  assert.doesNotMatch(child, /CALL_TYPE_PREVIEWS|missingCallTypePreviews|child-call-neon-preview|표시 예시/);
  assert.match(seedGildongDemo, /return "direct"/);
  assert.match(seedGildongDemo, /return "ai_to_direct"/);
  assert.match(child, /setActiveCall\(call\)/);
  assert.match(child, /<CallTranscriptModal/);
  assert.match(callModal, /<Transcript callId=\{call\.call_id\}/);
  assert.match(callModal, /event\.key === "Escape"/);
  assert.match(child, /needsAttention \? `확인 필요/);
  assert.match(callModal, /child-call-problem-badge/);
  assert.match(transcript, /총 \{rows\.length\}개 발화/);
  assert.match(transcript, /아래로 스크롤해 전체 대화를 확인하세요/);
  assert.match(transcript, /transcript-message-row/);
  assert.match(transcript, /<time dateTime=\{u\.created_at\}>/);
  assert.match(styles, /child-call-modal \{[^}]*height:min\(760px,90dvh\)/);
  assert.match(styles, /child-call-modal \.transcript \{[^}]*overflow-y:auto/);
});

test("보호자는 진행 중인 AI 통화를 보고 실제 연결 뒤 이어받는다", () => {
  assert.match(child, /getActiveCall\(picked\.elder_id, myPersona\.persona_id\)/);
  assert.match(child, /지금 AI와 통화 중/);
  assert.match(child, /지금 이어받기/);
  assert.match(child, /requestCallHandoff/);
  assert.match(app, /getCallHandoff\(call\.call_id\)/);
  assert.match(app, /humanTransportState !== "connected"/);
  assert.match(app, /markHumanConnected\(call\.call_id, invite\.invite_id\)/);
  assert.match(app, /handoffPending/);
});

test("보호자 설정은 잠금 화면 위험 알림과 시험 알림을 제공한다", () => {
  assert.match(child, /위험 알림 켜기/);
  assert.match(child, /시험 알림 보내기/);
  assert.match(child, /enableGuardianPush/);
  assert.match(child, /savePushSubscription/);
  assert.match(styles, /guardian-push-settings/);
});

test("가족 추억은 네 단계의 단일 보관 흐름과 사진 업로드를 제공한다", () => {
  assert.match(child, /label: "추억"/);
  assert.match(clothesline, /함께 보는 추억/);
  assert.match(clothesline, /memory-rope/);
  assert.match(clothesline, /memory-tape/);
  assert.match(clothesline, /memory-wall-open-button/);
  assert.match(clothesline, /memory-wall-dialog/);
  assert.match(clothesline, /MEMORY_WALL_ROW_SIZE = 5/);
  assert.match(clothesline, /가족이 확인한 사진만 걸려 있어요/);
  assert.match(styles, /\.memory-wall-row ul \{[^}]*grid-template-columns:repeat\(5/);
  assert.match(clothesline, /happened_year/);
  assert.match(clothesline, /uploadMemoryPhoto/);
  assert.match(clothesline, /아직 걸지 않은 이야기/);
  assert.match(clothesline, /금지된 이야기/);
  assert.doesNotMatch(clothesline, /빨랫줄|weekLabel/);
});

test("가족 오늘은 대표 그림과 통화 일기 및 고정 5등분 하단 탭을 사용한다", () => {
  assert.match(child, /const diaryImage = dayHeartPhoto \|\| memoryImage\(artwork\)/);
  assert.match(child, /className="child-day-diary"/);
  assert.match(child, /다소니가 전하는 오늘의 한마디/);
  assert.match(child, /heart\?\.day_translation\?\.family/);
  assert.match(child, /className="child-header-diary-note"/);
  assert.match(child, /quotedFamilyInsight/);
  assert.match(child, /className="child-header-memory-title"/);
  assert.doesNotMatch(clothesline, /FAMILY ARCHIVE|className="family-memory-title"/);
  assert.match(child, /tab === "today" \? " today-view"/);
  assert.doesNotMatch(child, /child-diary-page[\s\S]{0,800}<footer>/);
  assert.match(child, /className="child-diary-writing"/);
  assert.match(child, /className=\{letter === " " \? "blank" : ""\}/);
  assert.match(child, /completeDiaryWriting/);
  assert.match(theme, /child-diary-writing \{[\s\S]*background-color: #fffdf8/);
  assert.match(child, /const dailyDiary = latest\?\.diary \|\| heart\?\.diary \|\| null/);
  assert.doesNotMatch(child, /--insight-fit/);
  assert.match(child, /\/diary\/haeundae-family-drawing\.png/);
  assert.ok(existsSync(new URL("../public/diary/haeundae-family-drawing.png", import.meta.url)));
  assert.doesNotMatch(child, /DEMO_DIARY_BY_DATE|demoDiaryData/);
  assert.doesNotMatch(child, /className="child-diary-picker"/);
  assert.match(child, /className="child-diary-date"/);
  assert.match(child, /displayValue=\{shortDate\(selectedDate\)\}/);
  assert.ok(existsSync(new URL("../public/diary/country-market-memory.png", import.meta.url)));
  assert.ok(existsSync(new URL("../public/diary/persimmon-yard-memory.png", import.meta.url)));
  assert.ok(existsSync(new URL("../public/diary/autumn-riverside-picnic.png", import.meta.url)));
  assert.doesNotMatch(child, /diaryArtworkLabel|child-diary-art[\s\S]*figcaption/);
  assert.match(styles, /\.app-device-family \.child-tabs \{[\s\S]*grid-template-columns: repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(styles, /@media \(max-width: 430px\)[\s\S]*care-domain-radar > header[\s\S]*grid-template-columns: minmax\(0,1fr\)/);
  assert.match(styles, /@media \(max-width: 430px\)[\s\S]*care-domain-radar > header[\s\S]*grid-template-columns: minmax\(0,1fr\) max-content/);
  assert.match(styles, /@media \(max-width: 430px\)[\s\S]*radar-legend[\s\S]*grid-template-columns: max-content/);
  assert.match(styles, /\.child-diary-art/);
  assert.match(styles, /\.child-diary-page/);
  assert.doesNotMatch(child, /child-heart-collage|HEART_SLOT_COUNT/);
});

test("가족 화면의 글자·명암 설정은 설정 탭의 보기 버튼으로 연다", () => {
  assert.match(child, /\{tab === "settings"/);
  assert.match(child, /className="child-view-settings"/);
  assert.match(child, />Aa<\/span>/);
  assert.doesNotMatch(child, />보기<\/b>/);
  assert.match(app, /onDisplaySettings=\{\(\) => setSettingsOpen\(true\)\}/);
  assert.match(app, /displayDock: false, shell: "family"/);
  assert.match(displaySettings, /역할 선택으로 돌아가기/);
  assert.match(child, /className="child-header-reachable"/);
  assert.doesNotMatch(child, /className="family-reachable"/);
});

test("가족 헤더 조작과 통화 분석 그래프는 앱 프레임 폭 안에 배치된다", () => {
  assert.match(child, /tab === "analysis"[\s\S]*child-header-call-title[\s\S]*<\/div><AppDatePicker className="child-date-picker"/);
  assert.match(theme, /child-family-header \{[\s\S]*grid-template-columns: auto minmax\(0,1fr\) auto/);
  assert.match(theme, /child-family-header > :is\(\.child-view-settings,\.child-date-picker\)[\s\S]*grid-column: 3/);
  assert.match(theme, /family-analysis-report \.retention-layout \{[\s\S]*grid-template-columns: minmax\(0,1fr\)/);
  assert.match(theme, /family-analysis-report \.topic-scatter \{[\s\S]*min-width: 0/);
  assert.match(dasoniHome, /label: "대화 중 변화 신호"/);
  assert.match(dasoniHome, /기억·언어·정서·생활 관련 신호이며, 진단 결과가 아닙니다/);
  assert.doesNotMatch(reportTabs, /발화 기반 관찰/);
  assert.match(theme, /dasoni-observation-summary \{[\s\S]*border: 1px solid var\(--line\);[\s\S]*border-radius: 22px/);
  assert.match(theme, /dasoni-observation-grid article:last-child \{[\s\S]*border-bottom: 0/);
});

test("통화 분석의 작은 차이와 복잡한 그래프는 모바일에서도 자세히 볼 수 있다", () => {
  assert.match(reportTabs, /const scaleMin = Math\.max\(0, Math\.floor\(rawMin - scalePadding\)\)/);
  assert.match(reportTabs, /className="retention-axis-break"/);
  assert.match(reportTabs, />0~\{scaleMin\}분 생략</);
  assert.match(reportTabs, /className="life-stage-snapshots"/);
  assert.match(reportTabs, /지금 발화가 머무는 시점/);
  assert.match(reportTabs, /시간 역행 지점 그래프 크게 보기/);
  assert.match(reportTabs, /정서 유발 주제 그래프 크게 보기/);
  assert.match(reportTabs, /const routeStart = firstSnapshot \|\| destination/);
  assert.match(reportTabs, /className="life-road-travelled" points=\{travelledPoints\}/);
  assert.match(reportTabs, /첫 관찰 · \{routeStart\.label\}/);
  assert.doesNotMatch(reportTabs, /trajectorySegments|markerEnd|life-trajectory-marker/);
  assert.match(reportTabs, /riskTopicName/);
  assert.match(reportTabs, />짧은 통화<\/text><text[^>]+>긴 통화<\/text>/);
  assert.doesNotMatch(reportTabs, /눌러서 크게 보기|30일 중앙값|item\.calls\}통 · 부담/);
  assert.doesNotMatch(reportTabs, /위험 발화가 나온 주제|부담 표현이 잦음|status\.hint/);
  assert.match(reportTabs, /className="topic-finding-count"/);
  assert.doesNotMatch(reportTabs, /finding\.metric\}<i aria-hidden="true">⌄<\/i>/);
  assert.match(styles, /\.report-modal-backdrop \{[^}]*position:fixed/);
  assert.match(styles, /\.report-modal-chart \.life-road,\.report-modal-chart \.topic-scatter \{[^}]*min-width:780px/);
  assert.match(theme, /family-analysis-report \.report-modal-chart \.topic-scatter \{[\s\S]*min-width: 780px/);
  assert.match(theme, /child-brand-home\.on \{ background: transparent; \}/);
});

test("오늘 화면의 중복 카드 두 개가 제거됐다", () => {
  assert.doesNotMatch(child, /함께하는 AI 가족/);
  assert.doesNotMatch(child, /가족이 해볼 일 하나/);
  assert.match(child, /child-day-diary/);
  assert.match(child, /오늘의 마음 날씨/);
  assert.match(child, /diaryWeatherIcon/);
  assert.match(child, /className="child-diary-weather"/);
  assert.doesNotMatch(child, /child-today-bento-simple/);
  assert.doesNotMatch(child, /선택한 날/);
  assert.match(child, /id: "today"/);
  assert.match(child, /<TabGlyph>/);
  assert.match(child, /heart\?\.missed_word\?\.quote/);
});

test("가족 추억함의 확인 대기 바구니는 접었다 펼칠 수 있다", () => {
  const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
  assert.match(clothesline, /basketOpen/);
  assert.match(clothesline, /useState\(false\)/);
  assert.match(clothesline, /aria-expanded=\{basketOpen\}/);
  assert.match(clothesline, /접기/);
  assert.match(clothesline, /펼치기/);
  assert.match(clothesline, />확인</);
  assert.match(clothesline, />일부만</);
  assert.match(clothesline, />삭제</);
  assert.doesNotMatch(clothesline, />나중에</);
  assert.match(clothesline, /어르신과의 통화에 사용될 추억이에요/);
  assert.match(clothesline, /memory-time-field/);
  assert.match(clothesline, />잘 모르겠어요</);
  assert.equal((clothesline.match(/placeholder="일어난 연도/g) || []).length, 1);
  assert.doesNotMatch(clothesline, /recall\.created_at/);
  assert.doesNotMatch(clothesline, /<q>\{recall\.quote\}<\/q>/);
  assert.match(clothesline, /새로운 이야기/);
  assert.match(clothesline, /함께 있던 사람 이름/);
  assert.doesNotMatch(clothesline, /\{pending\.length\}건|\{drawer\.length\}건/);
  assert.match(clothesline, /memory-icon-toggle memory-basket-toggle/);
  assert.equal((clothesline.match(/<i[^>]*aria-hidden="true"[^>]*\/>/g) || []).length, 3);
  assert.match(theme, /memory-section-toggle i::before,[\s\S]*memory-section-toggle i::after/);
  assert.match(theme, /border-right: 1\.5px solid currentColor/);
  assert.match(styles, /\.memory-basket article nav button \{ min-width:0; height:24px/);
});

test("보호자 모바일은 추억함 조작 크기를 통일하고 통화 상세를 위쪽에서 보여준다", () => {
  assert.match(theme, /memory-icon-toggle,[\s\S]*width: 44px;[\s\S]*height: 44px/);
  assert.match(clothesline, /memory-drawer-header/);
  assert.match(clothesline, /memory-drawer-toggle/);
  assert.match(theme, /memory-new-fields \{ grid-template-columns: 1fr/);
  assert.match(theme, /child-call-modal \{[\s\S]*height:92dvh;[\s\S]*min-height:92dvh/);
});

test("보호자 화면은 그림일기와 다소니 발화만 손글씨로 구분한다", () => {
  assert.match(theme, /child-diary-page[\s\S]*font-family: "Dasoni Forest Letter"/);
  assert.match(theme, /child-header-diary-note span[\s\S]*font-family: "Dasoni Forest Letter"/);
  assert.match(theme, /child-header-reachable strong[\s\S]*font-family: "Dasoni Forest Letter"/);
  assert.match(theme, /child-header-memory-title strong,[\s\S]*child-header-call-title strong,[\s\S]*font-size:calc\(20px/);
  assert.match(theme, /child-header-diary-note span \{[\s\S]*white-space: pre-line;[\s\S]*overflow: visible;[\s\S]*display: block/);
  assert.doesNotMatch(child, /firstSentence\.slice\([^\n]+…/);
  assert.match(child, /가장 따뜻한 기억엔\\n/);
  assert.match(theme, /child-diary-title-row h1 \{[\s\S]*font-family: "Dasoni Forest Letter", "Gaegu", "Gowun Dodum", cursive !important/);
  assert.match(child, /compactDiaryInsight/);
});

test("오늘 관찰은 보호자 메인으로 옮기고 분석 리포트에서는 제외한다", () => {
  assert.match(dasoniHome, /dasoni-observation-summary/);
  assert.match(dasoniHome, /어르신의 오늘 관찰/);
  assert.doesNotMatch(dasoniHome, /어르신의 오늘 관찰 요약/);
  assert.match(dasoniHome, /대화 중 변화 신호/);
  assert.match(child, /baselineSummary=\{baselineSummary\}/);
  assert.doesNotMatch(reportTabs, /manager-observation-summary/);
  assert.doesNotMatch(reportTabs, /어르신의 오늘 관찰 요약/);
});

test("설정의 본인 가족 카드는 관계와 이름을 두 줄로 구분한다", () => {
  assert.match(child, /readyPersonas\.find\(\(item\) => item\.persona_id === myPersonaId\)/);
  assert.match(child, /<FamilyPersonaSettings[\s\S]*personaId=\{myPersona\?\.persona_id/);
  assert.doesNotMatch(familySettings, /child-me-badge|내 가족 프로필/);
  assert.match(familySettings, /persona\.relationship_type \|\| summary\?\.relationship/);
});

test("가족 설정은 말투 이름과 실제 표현을 간결하게 편집한다", () => {
  assert.doesNotMatch(child, /AI FAMILY|통화에 등장할 가족이에요|안전한 기본값/);
  assert.doesNotMatch(familySettings, /다시 설정하기/);
  assert.match(familySettings, /CallStyleQuiz/);
  assert.doesNotMatch(callStyleQuiz, /실제 통화에서 내가 더 자연스럽게 건넬 말을 골라주세요/);
  assert.doesNotMatch(callStyleQuiz, /첫 말투 맞추기/);
  assert.doesNotMatch(callStyleQuiz, /통화에서는 어르신 상태와 안전 규칙이 언제나 이보다 우선합니다/);
  assert.match(callStyleQuiz, /call-style-result-title/);
  assert.match(callStyleQuiz, /!showingResult && <div className="call-style-scene-progress"/);
  assert.match(callStyleQuiz, /className="call-style-complete" onClick=\{\(\) => onApply\(result\)\}/);
  assert.match(theme, /family-style-quiz-wrap \.call-style-score-grid \{ grid-template-columns: minmax\(0,1fr\)/);
  assert.match(theme, /family-style-quiz-wrap \.call-style-result-actions \{[\s\S]*grid-template-columns: repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(theme, /call-style-result-actions > button\.save \{[\s\S]*width: 100%;[\s\S]*height: 56px;[\s\S]*min-width: 0;[\s\S]*min-height: 56px;[\s\S]*max-height: 56px/);
  assert.match(familySettings, /persist\(next, "저장 완료"\)/);
  assert.match(familySettings, /window\.setTimeout\(\(\) => setNote\(""\), 1600\)/);
  assert.match(theme, /family-settings-note \{[\s\S]*position: fixed;[\s\S]*transform: translateX\(-50%\)/);
  assert.doesNotMatch(familySettings, />가족 표현</);
  assert.match(familySettings, /\{persona\.display_name \|\| "가족"\}님이 실제로 쓰는 표현을 알려주세요/);
  assert.doesNotMatch(familySettings, /설정을 한 사람으로/);
  assert.match(theme, /family-speech-settings header h2 \{[\s\S]*font-size: clamp\(14px,3\.25vw,calc\(17px \* var\(--font-scale\)\)\)/);
  assert.match(familySettings, /자주 쓰는 말/);
  assert.match(familySettings, /쓰면 안 되는 말/);
  assert.doesNotMatch(familySettings, /<small>말투 카드<\/small>/);
  assert.doesNotMatch(familySettings, /한 줄에 하나씩 입력하세요|상처나 부담이 될 표현을 적어주세요/);
  assert.doesNotMatch(familySettings, /말의 속도, 높임말과 반말/);
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
  assert.match(familySettings, /aria-label=\{`\$\{persona\.call_style_name/);
  assert.doesNotMatch(familySettings, /안심 케어 내비게이터/);
  assert.match(personaPanel, /사진 크게 보기/);
  assert.match(personaPanel, /사진 추가하기/);
  assert.match(personaPanel, /AI 영상 얼굴/);
  assert.match(personaPanel, /다시 생성/);
  assert.match(personaPanel, /syncAvatarProfile/);
  assert.doesNotMatch(personaPanel, /python tools\/make_morph\.py/);
});
