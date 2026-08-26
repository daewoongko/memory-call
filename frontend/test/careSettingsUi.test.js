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
  assert.match(theme, /\.app-device-care \.sidebar-elder-panel \{[\s\S]*?grid-template-columns: minmax\(0,1fr\) 50px/);
  assert.match(theme, /\.app-device-care \.radar-average \{ fill: color-mix\(in srgb,#d98a3f 16%,transparent\); stroke: #d98a3f; stroke-width: 2\.2; stroke-dasharray: none; \}/);
  assert.match(careManager, /className="care-manager-loading" role="status"/);
  assert.match(theme, /\.app-device-care \.elder-info small \{[\s\S]*?white-space: nowrap/);
  assert.match(styles, /\.radar-average \{ fill:color-mix\(in srgb,#d98a3f 11%,transparent\); stroke:#d98a3f; stroke-dasharray:none/);
  assert.match(styles, /\.radar-legend \.average::before \{ border-top-style:solid; border-top-color:#d98a3f; \}/);
});

test("voice registration heading replaces the redundant my voice label", () => {
  assert.doesNotMatch(voiceProfile, /<span>내 목소리<\/span>/);
  assert.match(voiceProfile, /<h2>AI 통화에 사용할 목소리를 등록하세요<\/h2>/);
  assert.match(theme, /\.app-device-family \.voice-settings-heading h2[\s\S]*?white-space: nowrap/);
});

test("approved voice preview and re-recording stay inside one stable card", () => {
  assert.doesNotMatch(voiceProfile, /목소리 등록 삭제|PVC는 녹음이 충분해도 자동으로 바뀌지 않습니다/);
  assert.doesNotMatch(voiceProfile, /통화에는 승인한 IVC 목소리가 계속 사용됩니다/);
  assert.doesNotMatch(voiceProfile, /본인 최종 승인을 거친 뒤에만 녹음을 전환합니다/);
  assert.match(voiceProfile, /restartVoiceRecording/);
  assert.match(voiceProfile, /aria-label="다시 듣기">🎧/);
  assert.match(voiceProfile, /aria-label="다시 녹음하기">다시 녹음/);
  assert.match(voiceProfile, /voice-active-actions/);
  assert.match(voiceProfile, /voice-active-preview/);
  assert.match(voiceProfile, /voice-recorder-heading-actions/);
  assert.match(theme, /voice-active-summary \{[\s\S]*grid-template-columns: minmax\(0,1fr\) auto/);
});

test("family settings raises the small supporting text sizes", () => {
  assert.match(theme, /\.app-device-family \.family-self-identity h1 > span/);
  assert.match(theme, /\.app-device-family \.family-speech-settings label > span \{ font-size: calc\(11px/);
  assert.match(theme, /\.app-device-family \.family-speech-settings textarea \{ font-size: calc\(12px/);
});

test("care checklist centers its count and omits the repeated date", () => {
  assert.doesNotMatch(careTasks, /const dateLabel/);
  assert.match(careTasks, /<h2>할 일 <span>\{tasks \? `\$\{tasks\.completed\}\/\$\{tasks\.total\}` : "-\/-"\}<\/span><\/h2>/);
  assert.doesNotMatch(careTasks, /기록 완료/);
  assert.match(careTasks, /<div className="task-view-toggle"><button[\s\S]*?>시간순<\/button><button[\s\S]*?>환자별<\/button><\/div>/);
  assert.doesNotMatch(careManager, /taskProgress|setTaskProgress/);
  assert.doesNotMatch(careManager, /sidebar-nav[\s\S]*?<em>\{taskProgress\.completed\}/);
  assert.match(theme, /\.app-device-care \.sidebar-nav button:not\(:has\(> span\)\) \{ justify-content: center; text-align: center; \}/);
  assert.match(theme, /\.app-device-care \.task-heading-summary[\s\S]*?text-align: left/);
  assert.match(theme, /\.app-device-care \.care-task-workspace[\s\S]*?overflow-x: clip/);
});

test("handover omits the repeated date and uses one readable task flow", () => {
  assert.doesNotMatch(handover, /\{SHIFT\[shift\]\} 근무 · \{date\}/);
  assert.doesNotMatch(handover, /handover-columns/);
  assert.doesNotMatch(handover, /<header><h2>인계<\/h2><\/header>/);
  assert.match(handover, /className="handover-groups"/);
  assert.match(handover, /className="handover-group pending"/);
  assert.match(handover, /<details className="handover-group pending">/);
  assert.match(handover, /<summary><span>다음 근무자가 볼 것<\/span><b>\{incomplete\.length\}건<\/b>/);
  assert.match(handover, /<details className="handover-group completed">/);
  assert.match(handover, /<summary><span>오늘 확인한 것<\/span><b>\{completed\.length\}\/\{rows\.length\}<\/b>/);
  assert.match(handover, /<details className=\{`handover-item/);
  assert.match(handover, /className="handover-item-detail"/);
  assert.match(styles, /\.handover-item > summary \{ display:grid; grid-template-columns:86px minmax\(0,1fr\) auto 18px/);
  assert.match(styles, /\.handover-item-detail \{ display:grid;/);
  assert.match(styles, /\.handover-group > summary \{ display:grid;/);
  assert.match(styles, /\.handover-group\[open\] > summary i \{ transform:rotate\(180deg\); \}/);
});

test("care checklist keeps the mobile viewport width and handover has one surface", () => {
  assert.match(theme, /\.app-device-care \.guardian-workspace \{[\s\S]*?overflow-x: hidden;[\s\S]*?contain: inline-size;/);
  assert.match(styles, /\.care-task-groups details \{ width:100%; min-width:0; max-width:100%;/);
  assert.match(styles, /\.care-task-row \{ width:100%; min-width:0; max-width:100%;/);
  assert.match(styles, /\.dose-status-actions \{ min-width:0; max-width:100%;/);
  assert.match(theme, /\.app-device-care \.care-task-workspace,[\s\S]*?\.app-device-care \.handover-workspace \{[\s\S]*?border: 0;[\s\S]*?background: transparent;/);
  assert.ok(careManager.includes("care-manager-dashboard care-tab-${tab}"));
  assert.match(theme, /\.care-manager-dashboard\.care-tab-checks \.guardian-workspace,[\s\S]*?scrollbar-width: none/);
  assert.match(theme, /\.care-manager-dashboard\.care-tab-handover \.guardian-workspace::-webkit-scrollbar \{[\s\S]*?display: none/);
  assert.match(theme, /\.care-manager-dashboard\.care-tab-handover \.handover-workspace \{[\s\S]*?border: 0 !important;[\s\S]*?background: transparent !important/);
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

test("emotion topic analysis uses conditional findings, three statuses, and one grounded risk quote", () => {
  assert.match(careReports, /const TOPIC_STATUS = \{/);
  assert.match(careReports, /color: "#b8332a"/);
  assert.match(careReports, /color: "#bd7d0e"/);
  assert.match(careReports, /color: "#0f8a70"/);
  assert.match(careReports, /function TopicFindings\(\{ tendency, topics, risks \}\)/);
  assert.match(careReports, /burden\?\.eligible && Number\(burden\.burden_ratio \|\| 0\) >= \.2/);
  assert.match(careReports, /Number\(hardest\?\.rate_per_100 \|\| 0\) >= 1/);
  assert.match(careReports, /눈에 띄는 부담 신호 없음/);
  assert.doesNotMatch(careReports, /className="topic-tendency-four"/);
  assert.match(careReports, /className="topic-scatter"/);
  assert.match(careReports, /viewBox="0 0 790 525"/);
  assert.match(careReports, /className=\{`topic-quote/);
  assert.match(careReports, /finding\.risk\.quote \|\| finding\.risk\.evidence/);
  assert.match(careReports, /className=\{`topic-finding-row \$\{finding\.status\.key\} expandable`\}/);
  assert.match(careReports, /className="topic-risk-ring"/);
  assert.match(careReports, /\{item\.calls\}통 · 부담 \{Math\.round\(item\.burden \* 100\)\}%/);
  assert.doesNotMatch(careReports, /TOPIC_EMOTION_COLOR|TOPIC_EMOTION_ACTION|topic-emotion-legend/);
  assert.doesNotMatch(careReports, /topic-grid-line/);
  assert.doesNotMatch(careReports, /환경으로 해결|일상 확인|정서적 갈망/);
  assert.match(careReports, /durationSpan = Math\.max\(actualDurationMax - actualDurationMin, medianDuration \* \.3, 1\)/);
  assert.match(careReports, /burdenSpan = Math\.max\(actualBurdenMax - actualBurdenMin, \.1\)/);
  assert.match(theme, /\.emotion-topic-analysis \.topic-scatter \{ width: calc\(100% \+ 24px\); min-width: 0; margin-left: -12px; \}/);
  assert.match(styles, /\.topic-findings \{ display:grid;/);
  assert.match(styles, /\.topic-finding-row \{ display:grid; grid-template-columns:88px minmax\(0,1fr\) auto/);
  assert.match(styles, /\.topic-quote \{ display:grid;/);
  assert.match(styles, /\.topic-point \.topic-risk-ring \{ fill:none; stroke:#b8332a; stroke-width:2\.5/);
  assert.doesNotMatch(theme, /topic-tendency-four|topic-emotion-legend/);
  assert.doesNotMatch(careReports, /원의 크기/);
  assert.match(theme, /\.app-device-care \.emotion-topic-analysis \.topic-point-label \{ font-size: 17px; \}/);
  assert.doesNotMatch(careReports, /30일 중앙값 \{Math\.round\(medianBurden \* 100\)\}%/);
  assert.doesNotMatch(careReports, /①|②|③|④/);
  assert.doesNotMatch(careReports, /짧게 이어짐|오래 이어짐/);
  assert.match(careReports, /const preferredDirection = item\.sourceIndex % 2 === 0 \? -1 : 1/);
  assert.match(emotionSeed, /어제 넘어져서 일어나기가 힘들었어/);
  assert.match(emotionSeed, /가슴이 답답하고 아파/);
  assert.match(emotionSeed, /"calls": len\(call_ids\)/);
  assert.match(emotionSeed, /"topics": len\(analytics\["emotion_topics"\]\)/);
});

test("time regression road fits the card without a duplicate stage summary", () => {
  assert.match(careReports, /className="life-road" viewBox="0 0 760 250"/);
  assert.doesNotMatch(careReports, /className="life-road-summary"/);
  assert.doesNotMatch(careReports, /이번 기록에서 가장 많이 연결된 시절/);
  assert.match(styles, /\.life-road \{ display:block; width:100%; min-width:0; height:auto;/);
});

test("care report removes weekday heatmap and keeps risk detail inside the immediate finding", () => {
  assert.doesNotMatch(careReports, /<WeekdayTimeHeatmap|compact-rhythm-report|요일 × 시간대 통화 밀도/);
  assert.match(careReports, /<details className=\{`topic-finding-row/);
  assert.match(careReports, /<summary><span>\{finding\.status\.label\}<\/span>/);
  assert.doesNotMatch(careReports, /\{latestRisk && <blockquote/);
});
