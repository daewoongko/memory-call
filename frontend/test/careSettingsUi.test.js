import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const careManager = readFileSync(new URL("../src/screens/CareManagerScreen.jsx", import.meta.url), "utf8");
const careTasks = readFileSync(new URL("../src/screens/CareTaskWorkspace.jsx", import.meta.url), "utf8");
const careReports = readFileSync(new URL("../src/screens/ReportTabs.jsx", import.meta.url), "utf8");
const handover = readFileSync(new URL("../src/screens/HandoverWorkspace.jsx", import.meta.url), "utf8");
const emotionSeed = readFileSync(new URL("../../tools/seed_emotion_topic_demo.py", import.meta.url), "utf8");
const voiceProfile = readFileSync(new URL("../src/components/VoiceProfilePanel.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const theme = readFileSync(new URL("../src/storybook-theme.css", import.meta.url), "utf8");

test("care manager uses one Aa display control instead of the wide display dock", () => {
  assert.match(app, /<CareManagerScreen onDisplaySettings=\{\(\) => setSettingsOpen\(true\)\}/);
  assert.match(app, /displayDock: false, shell: "care"/);
  assert.match(careManager, /className="care-view-settings"/);
  assert.equal((careManager.match(/className="care-view-settings"/g) || []).length, 1);
  assert.match(careManager, /className="g-head care-picker-head"[\s\S]*?<h1>관리할 어르신을 선택하세요<\/h1>/);
  assert.match(theme, /\.app-device-care \.care-picker-head h1 \{[\s\S]*?white-space: nowrap/);
  assert.match(careManager, /className="sidebar-elder-copy"/);
  assert.match(careManager, /className="sidebar-elder-date"/);
  assert.doesNotMatch(careManager, /<span>날짜<\/span>/);
  assert.doesNotMatch(careManager, /className="manager-tools"/);
  assert.doesNotMatch(careManager, /className="g-title">관리할 어르신을 선택하세요/);
  assert.doesNotMatch(careManager, /<p className="eyebrow">\{picked\.name\}/);
  assert.doesNotMatch(careManager, /className="dashboard-heading manager-heading"/);
  assert.doesNotMatch(careManager, /<b>요양원 담당자<\/b>/);
  assert.match(theme, /\.care-view-settings/);
  assert.match(theme, /\.manager-stat-grid\.manager-stat-strip \{[\s\S]*?overflow: visible/);
  assert.match(theme, /grid-template-columns: repeat\(6,minmax\(0,1fr\)\)/);
});

test("voice registration heading replaces the redundant my voice label", () => {
  assert.doesNotMatch(voiceProfile, /<span>내 목소리<\/span>/);
  assert.match(voiceProfile, /<h2>AI 통화에 사용할 목소리를 등록하세요<\/h2>/);
  assert.match(theme, /\.app-device-family \.voice-settings-heading h2[\s\S]*?white-space: nowrap/);
});

test("family settings raises the small supporting text sizes", () => {
  assert.match(theme, /\.app-device-family \.family-self-identity p \{ font-size: calc\(13px/);
  assert.match(theme, /\.app-device-family \.family-speech-settings label > span \{ font-size: calc\(11px/);
  assert.match(theme, /\.app-device-family \.family-speech-settings textarea \{ font-size: calc\(12px/);
});

test("care checklist centers its count and omits the repeated date", () => {
  assert.doesNotMatch(careTasks, /const dateLabel/);
  assert.match(careTasks, /<h2>할 일 <span>\{tasks \? `\$\{tasks\.completed\}\/\$\{tasks\.total\}` : "-\/-"\}<\/span> <small>기록 완료<\/small><\/h2>/);
  assert.doesNotMatch(careManager, /taskProgress|setTaskProgress/);
  assert.doesNotMatch(careManager, /sidebar-nav[\s\S]*?<em>\{taskProgress\.completed\}/);
  assert.match(theme, /\.app-device-care \.sidebar-nav button:not\(:has\(> span\)\) \{ justify-content: center; text-align: center; \}/);
  assert.match(theme, /\.app-device-care \.task-heading-summary[\s\S]*?text-align: center/);
});

test("handover omits the repeated date and uses one readable task flow", () => {
  assert.doesNotMatch(handover, /\{SHIFT\[shift\]\} 근무 · \{date\}/);
  assert.doesNotMatch(handover, /handover-columns/);
  assert.match(handover, /className="handover-groups"/);
  assert.match(handover, /className="handover-group pending"/);
  assert.match(styles, /\.handover-item \{ display:grid; grid-template-columns:86px minmax\(0,1fr\) auto/);
  assert.match(styles, /@media \(max-width:430px\) \{ \.handover-item/);
});

test("care insight shows the eight-domain radar before the observation summary", () => {
  const overviewStart = careReports.indexOf('<section className="dashboard-card manager-combined-overview">');
  const radar = careReports.indexOf("<CareDomainRadar", overviewStart);
  const summary = careReports.indexOf('<section className="manager-observation-summary">', overviewStart);
  assert.ok(overviewStart >= 0 && radar > overviewStart && summary > radar);
  assert.match(theme, /\.manager-combined-overview > \.care-domain-radar \{[\s\S]*?margin-top: 0/);
  assert.match(theme, /\.manager-observation-summary \{[\s\S]*?border-top: 1px solid var\(--line\)/);
  assert.doesNotMatch(careReports, /통화와 발화에서 확인된 다섯 가지 핵심 지표입니다/);
  assert.match(careReports, /const observedMax = Math\.max\(0,/);
  assert.match(careReports, /const maxValue = observedMax > 0 \? observedMax \* 1\.2 : 1/);
  assert.match(careReports, /const radius = 138/);
  assert.match(theme, /\.care-domain-radar \.radar-label \{ font-size: 12px; \}/);
});

test("emotion topic analysis keeps the four summaries and responsive bubble matrix", () => {
  assert.match(careReports, /<TendencyFourSummary tendency=\{tendency\} \/>/);
  assert.match(careReports, /className="topic-scatter"/);
  assert.match(careReports, /viewBox="0 0 790 525"/);
  assert.match(careReports, /className="topic-emotion-legend"/);
  assert.match(theme, /\.emotion-topic-analysis \.topic-scatter \{ width: calc\(100% \+ 24px\); min-width: 0; margin-left: -12px; \}/);
  assert.match(theme, /\.emotion-topic-analysis \.topic-tendency-four \{[\s\S]*?grid-template-columns: repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(theme, /\.emotion-topic-analysis \.topic-emotion-legend \{[\s\S]*?grid-template-columns: repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(emotionSeed, /"calls": len\(call_ids\)/);
  assert.match(emotionSeed, /"topics": len\(analytics\["emotion_topics"\]\)/);
});
