import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { BubbleChart } from "../components/Charts.jsx";

const CATEGORIES = [
  { id: "insight", label: "종합 현황" },
  { id: "talk", label: "통화 리포트" },
];

const RISK_LABEL = {
  fall: "낙상", chest_pain: "가슴 통증", breathing: "호흡 곤란",
  lost: "길 잃음", overdose: "약 과다 복용 의심",
  self_harm: "정서적 위기 표현", intrusion: "침입", fire: "화재",
  gas_leak: "가스 누출 의심",
  stroke_sign: "급성 뇌졸중 의심 신호",
};

const CARE_LABEL = {
  orientation: "지남력",
  memory: "기억",
  language: "언어",
  executive_judgment: "실행기능·판단",
  emotion: "정서",
  behavior_agitation: "행동·초조",
  daily_living: "일상생활 수행",
  safety_physical: "안전·신체",
};

const DOMAIN_COLOR = {
  orientation: "#24744f", memory: "#3e8a64", language: "#619645",
  executive_judgment: "#b27a16", emotion: "#d46b21",
  behavior_agitation: "#c34d3f", daily_living: "#859d29", safety_physical: "#a33e48",
};

function textList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [value];
  } catch {
    return [value];
  }
}

function dateParts(iso) {
  if (!iso) return { date: "-", time: "-", full: "-" };
  const date = new Date(iso);
  return {
    date: date.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" }),
    time: date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
    full: date.toLocaleString("ko-KR", {
      year: "numeric", month: "long", day: "numeric", weekday: "short",
      hour: "2-digit", minute: "2-digit",
    }),
  };
}

function dailyBubbleItems(day) {
  const observations = (day.observations || []).map((item) => ({
    label: item.label, value: item.count, color: DOMAIN_COLOR[item.domain] || "#24744f",
    kind: "관찰 상태", detail: item.evidence?.[0] || "",
  }));
  const repeats = (day.repeated_phrases || []).slice(0, 3).map((item) => ({
    label: `“${item.question}”`, value: item.count, color: "#f3b45a",
    kind: "많이 한 말", detail: `${item.call_count || 1}통의 통화에서 확인`,
  }));
  const risks = Object.entries((day.risks || []).reduce((groups, risk) => {
    groups[risk.type] = (groups[risk.type] || 0) + 1;
    return groups;
  }, {})).map(([type, value]) => ({
    label: RISK_LABEL[type] || type, value, color: "#ff777d", kind: "안전 신호",
    detail: day.risks.find((risk) => risk.type === type)?.evidence || "",
  }));
  return [...observations, ...repeats, ...risks]
    .sort((a, b) => b.value - a.value).slice(0, 9);
}

function mergeAnalysisRows(rows, rangeLabel) {
  const observationMap = new Map();
  const repeatMap = new Map();
  const actions = [];
  const risks = [];
  let heart = null;
  rows.forEach((row) => {
    (row.observations || []).forEach((item) => {
      const key = `${item.domain}:${item.signal}`;
      const current = observationMap.get(key) || { ...item, count: 0, evidence: [] };
      current.count += item.count || 0;
      (item.evidence || []).forEach((quote) => {
        if (quote && !current.evidence.includes(quote)) current.evidence.push(quote);
      });
      current.evidence = current.evidence.slice(0, 4);
      observationMap.set(key, current);
    });
    (row.repeated_phrases || []).forEach((item) => {
      const key = item.question;
      const current = repeatMap.get(key) || { ...item, count: 0, call_count: 0 };
      current.count += item.count || 0;
      current.call_count += item.call_count || 0;
      repeatMap.set(key, current);
    });
    (row.guardian_actions || []).forEach((action) => {
      if (action && !actions.includes(action)) actions.push(action);
    });
    risks.push(...(row.risks || []));
    if (row.heart_report) heart = row.heart_report;
  });
  const observations = [...observationMap.values()].sort((a, b) => b.count - a.count);
  const repeated = [...repeatMap.values()].sort((a, b) => b.count - a.count);
  return {
    date: rows.at(-1)?.date || "",
    range_label: rangeLabel,
    analysis_title: "선택 기간의 통화를 하나의 리포트로 정리했습니다",
    calls: rows.reduce((sum, row) => sum + (row.calls || 0), 0),
    seconds: rows.reduce((sum, row) => sum + (row.seconds || 0), 0),
    observation_count: observations.reduce((sum, item) => sum + item.count, 0),
    observations,
    repeated_total: repeated.reduce((sum, item) => sum + item.count, 0),
    repeated_phrases: repeated.slice(0, 6),
    risk_count: risks.length,
    risks,
    guardian_actions: actions.slice(0, 6),
    heart_report: heart,
  };
}

function DailyReportModal({ day, elderName, onClose, onAck, busy }) {
  if (!day) return null;
  const evidences = (day.observations || []).flatMap((item) =>
    (item.evidence || []).map((quote) => ({ label: item.label, quote })),
  ).slice(0, 5);
  return <div className="daily-modal-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="daily-report-modal" role="dialog" aria-modal="true" aria-label={`${day.date} 일별 통화 리포트`}>
      <header className="daily-modal-head">
        <div><p className="eyebrow">{day.range_label || `${dateParts(day.date).date} 일별 통화 리포트`}</p><h2>{elderName}님의 {day.analysis_title || "하루를 통화 기록으로 정리했습니다"}</h2></div>
        <button onClick={onClose} aria-label="일별 리포트 닫기">×</button>
      </header>

      <div className="daily-modal-metrics">
        <span><b>{day.calls}</b>통화</span><span><b>{Math.round(day.seconds / 60)}</b>분</span>
        <span><b>{day.observation_count}</b>관찰</span><span className={day.risk_count ? "risk" : ""}><b>{day.risk_count}</b>안전 신호</span>
      </div>

      <section className="daily-observation-map">
        <div><p className="eyebrow">통화 관찰 지도</p><h3>많이 나온 말과 관찰 영역</h3><p>선택한 범위의 통화를 합쳤습니다. 원이 클수록 같은 근거가 많이 확인됐습니다.</p></div>
        <BubbleChart items={dailyBubbleItems(day)} title={`${day.date} 통화 관찰 지도`} />
      </section>

      <section className="evidence-flow daily-evidence-flow" aria-label="일별 관찰 근거와 보호자 확인 사항">
        <article>
          <span className="flow-number">1</span><div><p>무엇을 관찰했는지</p><h3>하루 관찰 영역</h3></div>
          <ul>{(day.observations || []).slice(0, 5).map((item) => <li key={`${item.domain}-${item.signal}`}><b>{item.domain_label}</b>{item.label} · {item.count}회</li>)}</ul>
          {!day.observations?.length && <small>분류된 관찰이 없습니다.</small>}
        </article>
        <article>
          <span className="flow-number">2</span><div><p>어떤 발화가 근거인지</p><h3>어르신의 실제 말씀</h3></div>
          <ul className="flow-quotes">{evidences.map((item, index) => <li key={`${item.label}-${index}`}><q>{item.quote}</q></li>)}</ul>
          {!evidences.length && <small>표시할 직접 발화 근거가 없습니다.</small>}
        </article>
        <article>
          <span className="flow-number">3</span><div><p>보호자가 무엇을 해야 하는지</p><h3>직접 확인할 일</h3></div>
          <ul>{(day.guardian_actions || []).map((action, index) => <li key={index}>{action}</li>)}</ul>
          {!day.guardian_actions?.length && <small>추가 확인 항목이 없습니다.</small>}
        </article>
      </section>

      {day.risks?.length > 0 && <section className="daily-risk-list">
        <h3>이날 확인이 필요한 안전 신호</h3>
        {day.risks.map((risk) => <article key={risk.event_id} className={risk.acknowledged ? "acknowledged" : ""}>
          <div><b>{RISK_LABEL[risk.type] || risk.type}</b><q>{risk.evidence}</q></div>
          {risk.acknowledged ? <span className="tag ok">확인됨</span> : <button disabled={busy} onClick={() => onAck(risk.event_id)}>확인함</button>}
        </article>)}
      </section>}
    </section>
  </div>;
}

function HeatmapDayPreviewModal({ preview, elderName, onClose, onOpenDetail }) {
  if (!preview?.day) return null;
  const { day, cell } = preview;
  const riskQuote = (day.risks || []).find((risk) => risk.evidence)?.evidence;
  const observationQuotes = (day.observations || []).flatMap((item) => item.evidence || []);
  const observationQuote = observationQuotes.find((quote) => /모르는|보여서|무섭|두렵|넘어|아프/.test(quote))
    || observationQuotes[0];
  const repeatQuote = day.repeated_phrases?.[0]?.question;
  const quote = riskQuote || observationQuote || repeatQuote;
  const quoteKind = riskQuote ? "안전 발화" : observationQuote ? "관찰 발화" : "반복 발화";
  return <div className="daily-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="heatmap-day-preview" role="dialog" aria-modal="true" aria-label={`${day.date} 통화 미리보기`}>
      <header>
        <div><span>{dateParts(day.date).date}</span><h2>{elderName} 어르신의 통화 기록</h2>{cell?.time_label && <p>{cell.time_label} 선택 · 해당 날짜 전체 기록</p>}</div>
        <button type="button" onClick={onClose} aria-label="통화 미리보기 닫기">×</button>
      </header>
      <div className="heatmap-preview-metrics">
        <article><span>통화</span><b>{day.calls || 0}<small>통</small></b></article>
        <article><span>관찰</span><b>{day.observation_count || 0}<small>건</small></b></article>
        <article><span>반복</span><b>{day.repeated_total || 0}<small>회</small></b></article>
        <article className={day.risk_count ? "attention" : ""}><span>안전</span><b>{day.risk_count || 0}<small>건</small></b></article>
      </div>
      {quote ? <blockquote className={riskQuote ? "risk-quote" : ""}><span>{quoteKind}</span>“{quote}”</blockquote> : <p className="empty-state">이날 표시할 직접 발화 근거가 없습니다.</p>}
      <footer><button type="button" className="primary" onClick={onOpenDetail}>관찰 근거 자세히 보기 <span>→</span></button></footer>
    </section>
  </div>;
}

const SIGNAL_AXES = [
  ["time_confusion", "시간 혼동"],
  ["medication_uncertain", "복약 불확실"],
  ["meal_uncertain", "식사 불확실"],
  ["item_location_uncertain", "물건 위치"],
  ["loneliness", "외로움"],
  ["longing", "그리움"],
];

const SIGNAL_ACTIONS = {
  time_confusion: "날짜와 시간을 잘 보이는 곳에 표시하고 오전·오후를 함께 말해 주세요.",
  medication_uncertain: "예정 복약 30분 전에 약통과 기록을 먼저 확인해 주세요.",
  meal_uncertain: "식사 직후 체크표를 남겨 반복 확인에 사용할 수 있게 해 주세요.",
  item_location_uncertain: "자주 찾는 물건의 고정 위치를 확인해 주세요.",
  loneliness: "연락이 몰리기 전에 짧은 안부 통화를 먼저 시도해 보세요.",
  longing: "확인된 가족 사진이나 추억을 다음 통화 소재로 준비해 주세요.",
};

function signalCounts(source) {
  const counts = new Map();
  (source?.daily_reports || []).forEach((day) => (day.observations || []).forEach((item) => {
    counts.set(item.signal, (counts.get(item.signal) || 0) + (item.count || 0));
  }));
  return counts;
}

function domainCounts(source) {
  const counts = new Map(Object.keys(CARE_LABEL).map((key) => [key, 0]));
  (source?.daily_reports || []).forEach((day) => (day.observations || []).forEach((item) => {
    if (counts.has(item.domain)) counts.set(item.domain, counts.get(item.domain) + (item.count || 0));
  }));
  return counts;
}

function Sparkline({ values = [], label = "추이", tone = "normal" }) {
  const points = values.slice(-30).map(Number);
  if (points.length < 2) return <span className="sparkline-empty" aria-label={`${label} 데이터 수집 중`}>—</span>;
  const width = 90;
  const height = 28;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = Math.max(1, max - min);
  const path = points.map((value, index) => {
    const x = index / (points.length - 1) * width;
    const y = height - 3 - ((value - min) / range * (height - 6));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className={`mini-sparkline ${tone}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: ${points.join(", ")}`}>
    <polyline points={path} fill="none" vectorEffect="non-scaling-stroke" />
  </svg>;
}

function CareDomainRadar({ todayItems, averageItems }) {
  const centerX = 260;
  const centerY = 165;
  const radius = 108;
  const labelRadius = 145;
  const maxValue = Math.max(1, ...todayItems.map((item) => item.value), ...averageItems.map((item) => item.value));
  const point = (index, value, targetRadius = radius) => {
    const angle = -Math.PI / 2 + index * Math.PI / 4;
    const scaledRadius = targetRadius * (value / maxValue);
    return [centerX + Math.cos(angle) * scaledRadius, centerY + Math.sin(angle) * scaledRadius];
  };
  const polygon = (items) => items.map((item, index) => point(index, item.value).map((value) => value.toFixed(1)).join(",")).join(" ");
  const gridPolygon = (ratio) => todayItems.map((_, index) => point(index, ratio * maxValue).map((value) => value.toFixed(1)).join(",")).join(" ");
  const total = todayItems.reduce((sum, item) => sum + item.value, 0);
  return <section className="care-domain-radar" aria-label="오늘과 최근 30일 일평균의 8개 관찰영역 비교">
    <header><h3>오늘 발화에서 확인된 8개 영역</h3><div className="radar-legend"><span className="today">오늘</span><span className="average">최근 30일 일평균</span></div></header>
    <div className="radar-layout">
      <svg viewBox="0 0 520 340" role="img" aria-label={`8개 영역 오늘 총 ${total}건, 최근 30일 하루 평균과 비교`}>
        {[.25, .5, .75, 1].map((ratio) => <polygon key={ratio} className={`radar-grid ${ratio === 1 ? "level-100" : ""}`} points={gridPolygon(ratio)} />)}
        {todayItems.map((_, index) => { const [x, y] = point(index, maxValue); return <line key={index} className="radar-axis" x1={centerX} y1={centerY} x2={x} y2={y} />; })}
        <polygon className="radar-average" points={polygon(averageItems)} />
        <polygon className="radar-today" points={polygon(todayItems)} />
        {averageItems.map((item, index) => { const [x, y] = point(index, item.value); return <circle key={`average-${item.key}`} className="radar-average-dot" cx={x} cy={y} r="3" />; })}
        {todayItems.map((item, index) => { const [x, y] = point(index, item.value); return <circle key={`today-${item.key}`} className="radar-today-dot" cx={x} cy={y} r="4" />; })}
        {todayItems.map((item, index) => {
          const angle = -Math.PI / 2 + index * Math.PI / 4;
          const x = centerX + Math.cos(angle) * labelRadius;
          const y = centerY + Math.sin(angle) * labelRadius;
          const anchor = Math.abs(Math.cos(angle)) < .2 ? "middle" : Math.cos(angle) > 0 ? "start" : "end";
          const average = averageItems[index]?.value || 0;
          const difference = item.value - average;
          const changeClass = Math.abs(difference) < .05 ? "radar-even" : difference > 0 ? "radar-up" : "radar-down";
          return <text key={item.key} x={x} y={y} textAnchor={anchor} className="radar-label"><tspan x={x}>{item.label}</tspan><tspan x={x} dy="15">오늘 {item.value} · 평균 {average.toFixed(1)}</tspan><tspan x={x} dy="14" className={changeClass}>{Math.abs(difference) < .05 ? "평균과 동일" : `평균 대비 ${difference > 0 ? "+" : ""}${difference.toFixed(1)}`}</tspan></text>;
        })}
      </svg>
    </div>
  </section>;
}

function WeekdayTimeHeatmap({ baselineSummary, selectedDate, onSelectDate }) {
  const heatmap = baselineSummary?.rhythm?.weekday_time_heatmap;
  const weekdays = heatmap?.weekdays || [];
  const timeBlocks = heatmap?.time_blocks || [];
  const cells = heatmap?.cells || [];
  const cellMap = new Map(cells.map((cell) => [`${cell.weekday}-${cell.start_hour}`, cell]));
  const observedValues = [...new Set(cells.map((cell) => Number(cell.average_per_day || 0)).filter((value) => value > 0))].sort((a, b) => a - b);
  const selectedWeekday = selectedDate
    ? (new Date(`${selectedDate}T12:00:00`).getDay() + 6) % 7
    : -1;
  const intensity = (value) => {
    if (!value || !observedValues.length) return 0;
    const rank = observedValues.findIndex((candidate) => candidate >= value);
    if (observedValues.length === 1) return 7;
    return Math.max(1, Math.min(7, 1 + Math.round(rank / (observedValues.length - 1) * 6)));
  };
  const peakCell = cells.slice().sort((a, b) => b.average_per_day - a.average_per_day)[0];
  const selectWeekday = (weekday, cell = null) => {
    if (!selectedDate || !onSelectDate) return;
    const target = new Date(`${selectedDate}T12:00:00`);
    const currentWeekday = (target.getDay() + 6) % 7;
    target.setDate(target.getDate() - ((currentWeekday - weekday + 7) % 7));
    const localDate = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(target.getDate()).padStart(2, "0")}`;
    onSelectDate(localDate, cell);
  };
  return <figure className="weekday-time-heatmap">
    <div className="heatmap-primary-insight">{peakCell?.average_per_day > 0 ? <><span>통화 집중 시간</span><strong>{peakCell.weekday_label}요일 {String(peakCell.start_hour).padStart(2, "0")}–{String(peakCell.end_hour).padStart(2, "0")}시</strong><p>하루 평균 <b>{Number(peakCell.average_per_day).toFixed(1)}통</b>으로 가장 많이 모였습니다.</p></> : <p>최근 30일에 비교할 통화가 없습니다.</p>}</div>
    <header><b>요일 × 시간대 통화 밀도</b><div className="heatmap-legend"><span>적음</span><i className="heatmap-gradient" /><span>많음</span></div></header>
    {weekdays.length && timeBlocks.length ? <div className="heatmap-scroll"><div className="heatmap-grid" aria-label="최근 30일 요일과 시간대별 평균 통화량 히트맵">
      <span className="heatmap-corner">요일</span>
      {timeBlocks.map((block) => <span className="heatmap-hour" key={block.start_hour}>{String(block.start_hour).padStart(2, "0")}</span>)}
      {weekdays.map((weekday) => <div className={`heatmap-row ${weekday.weekday === selectedWeekday ? "selected" : ""}`} key={weekday.weekday}>
        <button type="button" className="heatmap-weekday" onClick={() => selectWeekday(weekday.weekday)} aria-pressed={weekday.weekday === selectedWeekday}>{weekday.label}<small>{weekday.weekday === selectedWeekday ? "선택일" : `${weekday.days_observed}일`}</small></button>
        {timeBlocks.map((block) => {
          const cell = cellMap.get(`${weekday.weekday}-${block.start_hour}`) || { calls: 0, average_per_day: 0, days_observed: weekday.days_observed };
          const average = Number(cell.average_per_day || 0);
          const level = intensity(average);
          const showValue = weekday.weekday === selectedWeekday || level >= 5;
          return <button type="button" className={`heatmap-cell heat-${level} ${showValue ? "show-value" : ""}`} key={block.start_hour} onClick={() => selectWeekday(weekday.weekday, { ...cell, time_label: block.label })} title={`${weekday.label}요일 ${block.label} · 총 ${cell.calls}통 / ${cell.days_observed}일 · 하루 평균 ${average.toFixed(1)}통`} aria-label={`${weekday.label}요일 ${block.label}, 하루 평균 ${average.toFixed(1)}통. 상세 미리보기`}>
            <span>{average ? average.toFixed(1) : "–"}</span>
          </button>;
        })}
      </div>)}
    </div></div> : <p className="empty-state">요일별 통화 기록을 집계하고 있습니다.</p>}
  </figure>;
}

function buildDeviations(daySummary, baselineSummary) {
  const todayCounts = signalCounts(daySummary);
  const baselineCounts = signalCounts(baselineSummary);
  const observedDays = Math.max(1, baselineSummary?.daily_reports?.length || baselineSummary?.days || 1);
  const dayReport = daySummary?.daily_reports?.[0];
  return SIGNAL_AXES.map(([signal, label]) => {
    const today = todayCounts.get(signal) || 0;
    const average = (baselineCounts.get(signal) || 0) / observedDays;
    const observation = dayReport?.observations?.find((item) => item.signal === signal);
    const trend = (baselineSummary?.daily_reports || []).slice(-30).map((day) =>
      (day.observations || []).filter((item) => item.signal === signal).reduce((sum, item) => sum + (item.count || 0), 0));
    return { signal, label, today, average, difference: today - average, ratio: average ? today / average : (today ? 3 : 0), evidence: observation?.evidence?.[0], action: SIGNAL_ACTIONS[signal], trend };
  }).filter((item) => item.today || item.average).sort((a, b) => {
    const aGroup = a.difference > 0 ? 0 : a.difference < 0 ? 1 : 2;
    const bGroup = b.difference > 0 ? 0 : b.difference < 0 ? 1 : 2;
    return aGroup - bGroup || Math.abs(b.difference) - Math.abs(a.difference);
  });
}

function buildPriorityTasks(deviations, risks = [], medication = {}) {
  const tasks = [];
  const add = (key, level, title, reason, steps) => {
    if (!tasks.some((item) => item.key === key)) tasks.push({ key, level, title, reason, steps });
  };
  if (risks.some((risk) => !risk.acknowledged)) add("safety", 1, "안전 신호부터 직접 확인", "미확인 안전 발화가 남아 있습니다.", ["발생 시각과 현재 상태 확인", "기관 응급 절차 적용 여부 판단", "확인 결과를 인계 기록에 남기기"]);
  deviations.filter((item) => item.difference > 0).forEach((item) => {
    if (item.signal === "medication_uncertain") add("medication", 1, "추가 투약 전 복약 기록 대조", `복약 불확실 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["추가 복용을 먼저 권하지 않기", "약포·약통·전자 투약 기록 대조", "확인되지 않으면 기관 지침에 따라 간호사·의료진 문의"]);
    else if (item.signal === "meal_uncertain") add("meal", 2, "식사 섭취 근거 확인", `식사 불확실 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["식사표와 잔반 확인", "섭취량·식사 시각 기록", "식욕 저하가 함께 지속되면 인계"]);
    else if (item.signal === "time_confusion") add("orientation", 2, "지남력 단서 재배치", `시간 혼동 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["시계·날짜판 가시성 확인", "같은 시간대 반복 여부 관찰", "갑작스러운 변화라면 통증·감염·수면 변화 함께 확인"]);
    else if (item.signal === "item_location_uncertain") add("item", 3, "자주 찾는 물건 위치 고정", `물건 위치 불확실 발화가 평소보다 증가했습니다.`, ["안경·지갑·리모컨 위치 확인", "고정 보관 위치 표식", "분실 불안 지속 시간 기록"]);
    else if (["loneliness", "longing"].includes(item.signal)) add("emotion", 3, "반복 연락 전 정서 활동 배치", `가족을 찾는 표현이 평소보다 증가했습니다.`, ["연락 집중 시간 전 짧은 대화 배치", "확인된 가족 사진·음악 활용", "활동 뒤 안정 여부 기록"]);
  });
  if ((medication.needs_check || 0) > 0 && !tasks.some((item) => item.key === "medication")) add("medication", 1, "복약 확인 필요 기록 처리", `복약 확인 필요 ${medication.needs_check}건이 남아 있습니다.`, ["약포와 투약 기록 대조", "중복 투약 방지", "확인 결과 기록"]);
  if (!tasks.length) add("routine", 3, "평소 루틴 유지", "월평균에서 크게 벗어난 발화가 없습니다.", ["정해진 일정 유지", "식사·수분·활동 상태 기록", "갑작스러운 변화만 인계"]);
  return tasks.sort((a, b) => a.level - b.level).slice(0, 5);
}

function PrioritySignalAccordion({
  item,
  summary,
  baselineNotes = [],
  medicalCautions = [],
  expanded,
  onToggle,
}) {
  const rows = (summary.time_reports || []).map((row) => {
    const observations = (row.observations || []).filter((observation) => observation.signal === item.signal);
    return {
      ...row,
      count: observations.reduce((sum, observation) => sum + observation.count, 0),
      evidence: observations.flatMap((observation) => observation.evidence || []),
    };
  }).filter((row) => row.count > 0);
  const changeLabel = item.difference > .05
    ? `증가 +${item.difference.toFixed(1)}`
    : item.difference < -.05
      ? `감소 ${item.difference.toFixed(1)}`
      : "변화 없음";
  const changeClass = item.difference > .05 ? "up" : item.difference < -.05 ? "down" : "even";
  const detailId = `priority-signal-${item.signal}`;

  return <article className={`priority-signal-item ${expanded ? "expanded" : ""}`}>
    <button
      className="priority-signal-trigger"
      type="button"
      aria-expanded={expanded}
      aria-controls={detailId}
      onClick={(event) => {
        event.preventDefault();
        onToggle(!expanded);
      }}
    >
      <span><b>{item.label}</b><small>오늘 {item.today}회 · 평균 {item.average.toFixed(1)}회</small></span>
      <strong className={changeClass}>{changeLabel}</strong>
      <em>{expanded ? "접기 ∧" : "자세히 보기 ›"}</em>
    </button>
    {expanded && <div id={detailId} className="priority-signal-detail">
      <blockquote>“{item.evidence || "선택일에 표시할 직접 발화 근거가 없습니다."}”</blockquote>
      <div className="priority-signal-time-list">
        {rows.slice(0, 4).map((row) => <div key={row.key}>
          <time>{row.time_label}</time>
          <b>{row.count}회</b>
          <span>{row.evidence[0] || "직접 발화 근거 없음"}</span>
        </div>)}
        {!rows.length && <p className="empty-state">시간대별 직접 근거가 없습니다.</p>}
      </div>
      <div className="priority-signal-action"><b>담당자 확인</b><p>{item.action}</p></div>
      <aside className="signal-baseline-note priority-baseline-note">
        <b>※ 평소 관찰 기준</b>
        <p>{baselineNotes.length ? baselineNotes.join(" · ") : `최근 30일 하루 평균 ${item.average.toFixed(1)}회를 비교 기준으로 사용했습니다.`}</p>
        {medicalCautions.length > 0 && <><b>※ 특히 보고할 변화</b><p>{medicalCautions.join(" · ")}</p></>}
      </aside>
      <button className="priority-signal-collapse" type="button" onClick={() => onToggle(false)}>상세 접기 ∧</button>
    </div>}
  </article>;
}

function ResponseRetentionChart({ data = {} }) {
  const samples = data.samples || [];
  const maxValue = Math.max(1, data.baseline_minutes || 0, ...samples.map((item) => item.minutes || 0));
  const current = data.current_minutes;
  const baseline = data.baseline_minutes;
  const change = data.change_minutes;
  const chartWidth = 620;
  const chartHeight = 250;
  const chartPadding = { top: 24, right: 22, bottom: 42, left: 42 };
  const plotWidth = chartWidth - chartPadding.left - chartPadding.right;
  const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom;
  const xAt = (index) => chartPadding.left + (samples.length === 1 ? plotWidth / 2 : index * plotWidth / (samples.length - 1));
  const yAt = (minutes) => chartPadding.top + plotHeight - (minutes / maxValue * plotHeight);
  const linePoints = samples.map((item, index) => `${xAt(index)},${yAt(item.minutes || 0)}`).join(" ");
  const meaningfulChange = Math.abs(change || 0) >= Math.max(10, (baseline || 0) * .2);
  const interpretation = change > 0
    ? `관찰 기록상 반복 발화 간격이 평소보다 ${change}분 길어져, 같은 내용이 다시 등장한 빈도가 낮아진 변화입니다.`
    : change < 0
      ? `관찰 기록상 반복 발화 간격이 평소보다 ${Math.abs(change)}분 짧아져, 같은 내용이 더 자주 등장한 변화입니다.`
      : "최근 반복 발화 간격은 30일 기준과 비슷합니다.";
  const nextCheck = change > 0
    ? "긍정적인 변화로 단정하기보다 앞으로 3일 이상 같은 흐름이 유지되는지 확인하세요."
    : change < 0
      ? "수면·불안·복약 누락처럼 같은 시기에 달라진 요인이 있었는지 먼저 확인하세요."
      : "현재 흐름을 기준선으로 두고 갑작스러운 단축이 생기는지 관찰하세요.";
  return <section className="dashboard-card retention-analysis">
    <header><div><span>01</span><h2>답변 유지 시간</h2></div>{current != null && <strong>{current}<small>분</small></strong>}</header>
    {samples.length && current != null && baseline != null ? <>
      <div className="retention-layout">
        <div className="retention-chart" aria-label="최근 반복 발화 간격 추세">
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img">
            {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}>
              <line className="retention-grid" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={chartPadding.top + plotHeight * ratio} y2={chartPadding.top + plotHeight * ratio} />
              <text className="retention-y-label" x={chartPadding.left - 8} y={chartPadding.top + plotHeight * ratio + 4}>{Math.round(maxValue * (1 - ratio))}</text>
            </g>)}
            <line className="retention-baseline-line" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={yAt(baseline)} y2={yAt(baseline)} />
            <text className="retention-baseline-label" x={chartWidth - chartPadding.right} y={Math.max(14, yAt(baseline) - 7)}>30일 기준 {baseline}분</text>
            {samples.map((item, index) => {
              const x = xAt(index);
              const y = yAt(item.minutes || 0);
              const barWidth = Math.min(34, plotWidth / Math.max(samples.length, 1) * .52);
              return <g key={`${item.label}-${index}`}>
                <rect className="retention-column" x={x - barWidth / 2} y={y} width={barWidth} height={chartPadding.top + plotHeight - y} rx="5" />
                <text className="retention-x-label" x={x} y={chartHeight - 15}>{item.label.slice(0, 5)}</text>
              </g>;
            })}
            <polyline className="retention-trend-line" points={linePoints} />
            {samples.map((item, index) => <circle className="retention-trend-point" key={`point-${index}`} cx={xAt(index)} cy={yAt(item.minutes || 0)} r={index === samples.length - 1 ? 6 : 4} />)}
          </svg>
          <div className="retention-chart-legend"><span><i />반복 간격</span><span><i />추세선</span></div>
        </div>
        <aside className={`retention-insight ${change < 0 ? "attention" : "stable"}`}>
          <div className="retention-summary"><div><small>최근 간격</small><b>{current}분</b></div><div><small>30일 기준</small><b>{baseline}분</b></div><div><small>기준 대비</small><b>{change > 0 ? "+" : ""}{change}분</b></div></div>
          <div className="retention-conclusion"><small>{meaningfulChange ? "뚜렷한 변화" : "기준 범위 변화"}</small><strong>{change > 0 ? "반복 간격이 길어졌습니다" : change < 0 ? "반복 간격이 짧아졌습니다" : "평소와 비슷합니다"}</strong><p>{interpretation}</p></div>
          <div className="retention-next"><small>다음 확인</small><p>{nextCheck}</p></div>
        </aside>
      </div>
    </> : <p className="empty-state">서로 다른 통화에서 같은 질문이 반복된 기록이 더 필요합니다.</p>}
  </section>;
}

function TimeRegressionJourney({ data = {} }) {
  const currentAge = data.current_age || 85;
  const stages = data.stages || [];
  const groupedStages = stages.reduce((groups, stage) => {
    const previous = groups.get(stage.label);
    groups.set(stage.label, { ...stage, count: (previous?.count || 0) + 1 });
    return groups;
  }, new Map());
  const visible = [...groupedStages.values()].sort((a, b) => a.age - b.age);
  const destination = visible.find((stage) => stage.label === data.dominant_stage) || visible.at(-1);
  const maxAge = Math.max(90, currentAge);
  const roadPoint = (age) => {
    const ratio = Math.max(0, Math.min(1, age / maxAge));
    return { x: 70 + ratio * 860, y: 156 + Math.sin(ratio * Math.PI * 3) * 72 };
  };
  const roadPoints = Array.from({ length: 91 }, (_, index) => roadPoint(index / 90 * maxAge));
  const journeyPoints = roadPoints.map((point) => `${point.x},${point.y}`).join(" ");
  const travelledPoints = destination
    ? roadPoints.filter((_, index) => {
      const age = index / 90 * maxAge;
      return age >= destination.age && age <= currentAge;
    }).map((point) => `${point.x},${point.y}`).join(" ")
    : "";
  const currentPoint = roadPoint(currentAge);
  const destinationPoint = destination ? roadPoint(destination.age) : null;
  const lifeMarkers = [
    { age: 5, label: "유아기", icon: "●" },
    { age: 15, label: "학창기", icon: "◆" },
    { age: 25, label: "청년기", icon: "▲" },
    { age: 45, label: "성인기", icon: "■" },
    { age: 65, label: "중년기", icon: "★" },
    { age: Math.min(82, currentAge), label: "노년기", icon: "◎" },
  ].filter((marker, index, all) => marker.age <= currentAge && all.findIndex((item) => item.age === marker.age) === index);
  return <section className="dashboard-card regression-journey">
    <header><div><span>02</span><h2>시간 역행 지점</h2></div><strong>현재 {currentAge}세</strong></header>
    <div className="life-road-wrap">
      <svg className="life-road" viewBox="0 0 1000 320" role="img" aria-label={`현재 ${currentAge}세에서 ${destination?.label || "과거 역할"}로 이어지는 인생 여정`}>
        <polyline className="life-road-base" points={journeyPoints} />
        <polyline className="life-road-center" points={journeyPoints} />
        {travelledPoints && <polyline className="life-road-travelled" points={travelledPoints} />}
        {lifeMarkers.map((marker) => {
          const point = roadPoint(marker.age);
          return <g className="life-stage-marker" key={`${marker.label}-${marker.age}`} transform={`translate(${point.x} ${point.y})`}>
            <circle r="22" />
            <text className="life-stage-icon" y="5">{marker.icon}</text>
            <text className="life-stage-label" y="39">{marker.label}</text>
            <text className="life-stage-age" y="53">{marker.age}세 전후</text>
          </g>;
        })}
        {destinationPoint && <g className="life-regression-marker" transform={`translate(${destinationPoint.x} ${destinationPoint.y})`}><circle r="13" /><circle r="5" /><text y="-22">{destination.label} 발화</text></g>}
        <g className="life-current-marker" transform={`translate(${currentPoint.x} ${currentPoint.y})`}><circle r="14" /><circle r="5" /><text y="-23">현재 {currentAge}세</text></g>
      </svg>
      {destination && <div className="life-road-summary"><small>이번 기록에서 가장 많이 연결된 시절</small><strong>{destination.label}<em>{destination.age_from}~{destination.age_to}세 무렵</em></strong><p>현재 시점에서 인생길을 따라 약 {Math.max(0, currentAge - destination.age)}년 전 역할의 발화가 관찰됐습니다.</p></div>}
    </div>
    {destination ? <div className="journey-evidence"><b>{destination.label} 근거</b><blockquote>“{destination.quote}”</blockquote><span>{destination.count}회 관찰</span></div> : <p className="empty-state">과거 역할과 연결되는 직접 발화가 확인되지 않았습니다.</p>}
  </section>;
}

const TOPIC_EMOTION_COLOR = {
  "불안·두려움": "#e5963d",
  "초조·분노": "#d7583c",
  "의심·망상": "#8a5aa8",
  "가라앉음": "#4f78a8",
  "따뜻함": "#2f936a",
  "확인·탐색": "#2e8691",
  "도움 요청": "#b7832f",
  "회상·역할": "#66738f",
};

const TOPIC_EMOTION_ACTION = {
  "불안·두려움": "다가가 안심",
  "초조·분노": "자극 줄이고 거리 두기",
  "의심·망상": "사실 논쟁 없이 절차 안내",
  "가라앉음": "말 걸고 활성화",
  "따뜻함": "가족에게 전달",
  "확인·탐색": "사실과 현재 맥락 확인",
  "도움 요청": "한 단계씩 직접 지원",
  "회상·역할": "현재를 짧게 안내",
};

function TendencyFourSummary({ tendency }) {
  const insufficient = !tendency?.sufficient_period;
  const reason = "관찰 기간이 짧아 경향을 정리하지 않았습니다.";
  const burdens = (tendency?.burden_ranking || []).map((item) => item.category).join(" > ");
  const inward = Number(tendency?.expression?.inward_count || 0);
  const outward = Number(tendency?.expression?.outward_count || 0);
  const calming = tendency?.calming_resource;
  const hardest = tendency?.hardest_time;
  const rows = [
    ["무엇에 힘들어하시나", insufficient ? reason : (burdens || "근거가 충분한 부담 주제가 아직 없습니다.")],
    ["어떻게 나타나나", insufficient ? reason : `불안·가라앉음 ${inward}건 · 초조·분노 ${outward}건`],
    ["무엇으로 편안해지시나", insufficient ? reason : (calming ? `${calming.topic} — 평균 ${calming.average_minutes}분, 부담 표현이 적은 대화` : "편안하게 이어진 주제가 아직 확인되지 않았습니다.")],
    ["언제 힘들어하시나", insufficient ? reason : (hardest ? `${hardest.label} · 발화 100건당 ${hardest.rate_per_100}건` : "시간대별 변화가 아직 확인되지 않았습니다.")],
  ];
  return <dl className="topic-tendency-four">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

function EmotionTopicMap({ topics = [], tendency = null }) {
  const maxCalls = Math.max(1, ...topics.map((item) => item.calls || 0));
  const median = (values) => {
    const ordered = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
    if (!ordered.length) return 0;
    const middle = Math.floor(ordered.length / 2);
    return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
  };
  const points = topics.map((item) => ({
    ...item,
    duration: Number(item.average_minutes || 0),
    burden: Number(item.burden_ratio || 0),
  }));
  const medianDuration = median(points.map((item) => item.duration));
  const medianBurden = median(points.map((item) => item.burden));
  const durationMin = Math.min(...points.map((item) => item.duration), medianDuration);
  const durationMax = Math.max(...points.map((item) => item.duration), medianDuration);
  const burdenMin = Math.min(...points.map((item) => item.burden), medianBurden);
  const burdenMax = Math.max(...points.map((item) => item.burden), medianBurden);
  const plot = { left: 120, right: 830, top: 56, bottom: 410, midX: 475, midY: 233 };
  const scaleAroundMedian = (value, split, min, max, low, middle, high) => {
    if (value === split) return middle;
    if (value < split) return low + (value - min) / Math.max(.001, split - min) * (middle - low) * .92;
    return middle + (high - middle) * (.08 + (value - split) / Math.max(.001, max - split) * .92);
  };
  const plotted = points.map((item, index) => {
    const radius = 12 + Math.sqrt(item.calls / maxCalls) * 31;
    const x = scaleAroundMedian(item.duration, medianDuration, durationMin, durationMax, plot.left + radius, plot.midX, plot.right - radius);
    const y = scaleAroundMedian(item.burden, medianBurden, burdenMin, burdenMax, plot.bottom - radius, plot.midY, plot.top + radius);
    return {
      ...item,
      radius,
      x,
      y,
      labelSide: x >= plot.midX ? 1 : -1,
      sourceIndex: index,
    };
  }).sort((a, b) => b.radius - a.radius);
  const labelByTopic = new Map();
  [-1, 1].forEach((side) => {
    const sidePoints = plotted.filter((item) => item.labelSide === side).sort((a, b) => a.y - b.y);
    let nextY = plot.top + 12;
    sidePoints.forEach((item) => {
      const y = Math.min(plot.bottom - 8, Math.max(item.y, nextY));
      labelByTopic.set(item.topic, { y, x: item.x + side * (item.radius + 13), side });
      nextY = y + 29;
    });
  });
  const xTickValues = [...new Set([durationMin, medianDuration, durationMax].map((value) => Math.round(value * 10) / 10))];
  const yTickValues = [...new Set([burdenMin, medianBurden, burdenMax].map((value) => Math.round(value * 100) / 100))];
  return <section className="dashboard-card emotion-topic-analysis">
    <header><div><span>03</span><h2>정서 유발 주제</h2></div></header>
    <TendencyFourSummary tendency={tendency} />
    {topics.length ? <>
      <div className="topic-scatter-wrap">
        <svg className="topic-scatter" viewBox="0 0 950 470" role="img" aria-label="주제별 평균 통화 시간과 부담 표현 비율 버블 산점도">
          <rect className="topic-plot-bg" x={plot.left} y={plot.top} width={plot.right - plot.left} height={plot.bottom - plot.top} rx="8" />
          {[.25, .5, .75].map((ratio) => <g key={ratio}><line className="topic-grid-line" x1={plot.left} x2={plot.right} y1={plot.top + (plot.bottom - plot.top) * ratio} y2={plot.top + (plot.bottom - plot.top) * ratio} /><line className="topic-grid-line" y1={plot.top} y2={plot.bottom} x1={plot.left + (plot.right - plot.left) * ratio} x2={plot.left + (plot.right - plot.left) * ratio} /></g>)}
          <line className="topic-median-line" x1={plot.left} x2={plot.right} y1={plot.midY} y2={plot.midY} />
          <line className="topic-median-line" y1={plot.top} y2={plot.bottom} x1={plot.midX} x2={plot.midX} />
          <text className="topic-median-caption x" x={plot.midX + 8} y={plot.bottom - 7}>30일 중앙값 {medianDuration}분</text>
          <text className="topic-median-caption y" x={plot.left + 8} y={plot.midY - 8}>30일 중앙값 {Math.round(medianBurden * 100)}%</text>
          <text className="topic-quadrant-label" x={plot.left + 14} y={plot.top + 22}>③ 환경으로 해결</text>
          <text className="topic-quadrant-label right" x={plot.right - 14} y={plot.top + 22}>④ 개입 필요</text>
          <text className="topic-quadrant-label" x={plot.left + 14} y={plot.bottom - 13}>① 일상 확인</text>
          <text className="topic-quadrant-label right" x={plot.right - 14} y={plot.bottom - 13}>② 정서적 갈망</text>
          {yTickValues.map((value) => { const y = scaleAroundMedian(value, medianBurden, burdenMin, burdenMax, plot.bottom, plot.midY, plot.top); return <g key={`y-${value}`}><line className="topic-tick" x1={plot.left - 5} x2={plot.left} y1={y} y2={y} /><text className="topic-tick-label y" x={plot.left - 9} y={y + 4}>{Math.round(value * 100)}%</text></g>; })}
          {xTickValues.map((value) => { const x = scaleAroundMedian(value, medianDuration, durationMin, durationMax, plot.left, plot.midX, plot.right); return <g key={`x-${value}`}><line className="topic-tick" x1={x} x2={x} y1={plot.bottom} y2={plot.bottom + 5} /><text className="topic-tick-label" x={x} y={plot.bottom + 19}>{value}분</text></g>; })}
          {plotted.map((item) => {
            const label = labelByTopic.get(item.topic);
            const lineStartX = item.x + label.side * item.radius * .72;
            return <g className="topic-point" key={item.topic} tabIndex="0" role="img" aria-label={`${item.topic}, ${item.calls}통`}>
              <title>{`${item.topic} · ${item.calls}통 · 평균 ${item.duration}분 · 부담 표현 ${Math.round(item.burden * 100)}% · ${item.emotion}`}</title>
              <circle cx={item.x} cy={item.y} r={item.radius} fill={TOPIC_EMOTION_COLOR[item.emotion] || TOPIC_EMOTION_COLOR["확인·탐색"]} />
              <line className="topic-label-leader" x1={lineStartX} x2={label.x} y1={item.y} y2={label.y} />
              <text className={`topic-point-label outside ${label.side > 0 ? "right" : "left"}`} x={label.x + label.side * 4} y={label.y - 2}>{item.topic}</text>
              <text className={`topic-point-count outside ${label.side > 0 ? "right" : "left"}`} x={label.x + label.side * 4} y={label.y + 11}>{item.calls}통 · {item.duration}분</text>
            </g>;
          })}
          <text className="topic-axis-title y" transform="translate(27 233) rotate(-90)">부담 표현 비율</text>
          <text className="topic-axis-end y-top" x="82" y={plot.top + 4}>많음</text><text className="topic-axis-end y-bottom" x="82" y={plot.bottom}>적음</text>
          <text className="topic-axis-end" x={plot.left} y="455">짧게 이어짐</text><text className="topic-axis-end right" x={plot.right} y="455">오래 이어짐</text>
          <text className="topic-axis-title" x={(plot.left + plot.right) / 2} y="455">주제가 나온 통화의 평균 시간</text>
        </svg>
      </div>
      <div className="topic-legend"><span className="topic-size-key"><i /><b>원의 크기</b> 통화 수</span>{Object.entries(TOPIC_EMOTION_COLOR).map(([label, color]) => <span key={label}><i style={{ background: color }} /><b>{label}</b><small>{TOPIC_EMOTION_ACTION[label]}</small></span>)}</div>
    </> : <p className="empty-state">주제를 비교할 통화 기록이 더 필요합니다.</p>}
  </section>;
}

function FamilyMomentModal({ report, onClose }) {
  if (!report) return null;
  return <div className="daily-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="family-moment-modal" role="dialog" aria-modal="true" aria-label="가족에게 전할 순간 설명">
    <header><div><p className="eyebrow">가족에게 전할 순간</p><h2>{report.label ? `${report.label}이 담긴 직접 발화` : "가족에게 전할 발화 근거"}</h2></div><button onClick={onClose}>×</button></header>
    {report.quote ? <blockquote>“{report.quote}”</blockquote> : <p>선택 기간에는 가족에게 전할 직접적인 표현이 확인되지 않았습니다.</p>}
    <div className="family-moment-reason"><small>왜 가족에게 전달하나요?</small><p>{report.quote ? "가족 또는 삶의 기억과 연결된 감정 표현이 실제 발화로 확인됐기 때문입니다. 상태 수치보다 어르신이 직접 남긴 말을 가족이 이해할 수 있도록 전달합니다." : "근거가 부족한 감정은 추측해 전달하지 않습니다."}</p></div>
    {report.message && <div className="family-moment-summary"><small>전달 요점</small><p>{report.message}</p></div>}
    <p className="moment-policy">이 내용은 담당자 분석에서 선별하고, 실제 가족용 화면에는 이미지와 함께 간단히 표시됩니다.</p>
  </section></div>;
}

export default function ReportTabs({
  elderId,
  elderName,
  patientProfile,
  summary = {
    risks: [], care_counts: {}, daily_reports: [], time_reports: [], medication: {},
    calls: 0, total_seconds: 0, repeat_total: 0, meaningful_total: 0,
  },
  baselineSummary,
  comparisonDay,
  period,
  onPeriod,
  onReload,
  initialTab = "insight",
  hideToolbar = false,
}) {
  const [tab, setTab] = useState(initialTab);
  const [busy, setBusy] = useState(false);
  const [selectedDay, setSelectedDay] = useState(null);
  const [heatmapPreview, setHeatmapPreview] = useState(null);
  const [showFamilyMoment, setShowFamilyMoment] = useState(false);
  const [expandedPrioritySignal, setExpandedPrioritySignal] = useState("");
  const [showPrioritySignals, setShowPrioritySignals] = useState(true);
  const [showDecreases, setShowDecreases] = useState(false);
  const [showUnchanged, setShowUnchanged] = useState(false);
  const profileBaselineNotes = textList(patientProfile?.care_baseline);
  const profileMedicalCautions = textList(patientProfile?.medical_cautions);

  useEffect(() => {
    setExpandedPrioritySignal("");
    setHeatmapPreview(null);
  }, [elderId, summary.since, summary.until]);
  useEffect(() => { setTab(initialTab); }, [initialTab]);

  async function ack(eventId) {
    setBusy(true);
    try {
      await api.acknowledgeRisk(eventId);
      setSelectedDay((current) => current ? {
        ...current,
        risks: (current.risks || []).map((risk) => risk.id === eventId ? { ...risk, acknowledged: true } : risk),
      } : current);
      await onReload();
    } finally { setBusy(false); }
  }

  const unread = summary.risks.filter((risk) => !risk.acknowledged);
  const periodReport = useMemo(() => mergeAnalysisRows(
    summary.daily_reports || [],
    `${summary.since} ~ ${summary.until} 전체 분석`,
  ), [summary.daily_reports, summary.since, summary.until]);
  const activeDaySummary = comparisonDay || (period.mode === "day" ? summary : null);
  const activeBaseline = baselineSummary || summary;
  const activeDayDomainCounts = useMemo(() => domainCounts(activeDaySummary), [activeDaySummary]);
  const careItems = useMemo(() => Object.entries(CARE_LABEL).map(([key, label]) => ({
    key, label, value: activeDayDomainCounts.get(key) || 0,
  })), [activeDayDomainCounts]);
  const careTotal = careItems.reduce((sum, item) => sum + item.value, 0);
  const deviations = useMemo(() => buildDeviations(activeDaySummary, activeBaseline), [activeDaySummary, activeBaseline]);
  const positiveDeviations = deviations.filter((item) => item.difference > .05);
  const negativeDeviations = deviations.filter((item) => item.difference < -.05);
  const unchangedDeviations = deviations.filter((item) => Math.abs(item.difference) <= .05);
  const baselineDays = Math.max(1, activeBaseline?.daily_reports?.length || activeBaseline?.days || 1);
  const baselineDomainCounts = useMemo(() => domainCounts(activeBaseline), [activeBaseline]);
  const averageCareItems = useMemo(() => careItems.map((item) => ({
    ...item, value: (baselineDomainCounts.get(item.key) || 0) / baselineDays,
  })), [careItems, baselineDomainCounts, baselineDays]);
  const dailyReports = activeBaseline?.daily_reports || [];
  const kpis = [
    { label: "AI 케어 통화", value: summary.calls, unit: "통", average: dailyReports.reduce((sum, day) => sum + (day.calls || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.calls || 0) },
    { label: "통화 시간", value: Math.round(summary.total_seconds / 60), unit: "분", average: dailyReports.reduce((sum, day) => sum + (day.seconds || 0) / 60, 0) / baselineDays, trend: dailyReports.map((day) => Math.round((day.seconds || 0) / 60)) },
    { label: "발화 기반 관찰", value: careTotal, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.observation_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.observation_count || 0), status: `발화 100건당 ${Math.round(summary.normalized_rates?.observation_per_100_utterances || 0)}건` },
    { label: "반복 발화", value: summary.repeat_total, unit: "회", average: dailyReports.reduce((sum, day) => sum + (day.repeated_total || day.repeat_total || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.repeated_total || day.repeat_total || 0) },
    { label: "안전 신호", value: summary.risks.length, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.risk_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.risk_count || 0), status: unread.length ? `미확인 ${unread.length}건` : "모두 확인" },
  ];
  const priorityTasks = useMemo(() => buildPriorityTasks(deviations, summary.risks, summary.medication), [deviations, summary.risks, summary.medication]);
  function openHeatmapPreview(dateValue, cell = null) {
    const day = (activeBaseline.daily_reports || []).find((row) => row.date === dateValue)
      || (activeDaySummary?.daily_reports || []).find((row) => row.date === dateValue);
    if (day) setHeatmapPreview({ day, cell });
    else onPeriod?.({ mode: "day", value: dateValue });
  }

  return <div className="report-dashboard">
    {!hideToolbar && <div className="report-toolbar">
      <nav className="cat-tabs">
        {CATEGORIES.map((category) => <button key={category.id} className={tab === category.id ? "on" : ""} onClick={() => setTab(category.id)}>{category.label}</button>)}
      </nav>
    </div>}

    {tab === "insight" && <>
      <div className="manager-focus-layout">
        <section className="dashboard-card manager-combined-overview">
          <header><div><h2>{elderName} 어르신의 오늘 관찰 요약</h2></div><button className="family-moment-button" onClick={() => setShowFamilyMoment(true)}>가족에게 전할 순간 <b>{summary.meaningful_total || 0}</b><span>요점 보기 ›</span></button></header>
          <div className="manager-stat-grid">{kpis.map((item) => { const delta = item.value - item.average; return <article key={item.label}><span>{item.label}</span><strong>{item.value}<small>{item.unit}</small></strong><em>{item.status || `평균 대비 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}</em><Sparkline values={item.trend} label={`${item.label} 최근 30일 추이`} tone={item.status && unread.length ? "alert" : "normal"} /></article>; })}</div>
          <CareDomainRadar todayItems={careItems} averageItems={averageCareItems} />
        </section>
        <aside className="dashboard-card daily-priority-panel">
          <header><div><h2>확인 우선순위</h2></div></header>
          <ol>{priorityTasks.map((task, index) => <li key={task.key} className={`priority-${task.level}`}><span>{index + 1}</span><div><b>{task.title}</b><p>{task.reason}</p><ul>{task.steps.map((step) => <li key={step}>{step}</li>)}</ul></div></li>)}</ol>
          <section className="priority-signal-summary">
            <button
              className="priority-signal-section-toggle"
              type="button"
              aria-expanded={showPrioritySignals}
              aria-controls="priority-signal-list"
              onClick={() => {
                setShowPrioritySignals((current) => !current);
                setExpandedPrioritySignal("");
              }}
            >
              <span><h3>평소와 달랐던 세부 발화</h3></span>
              <b>{showPrioritySignals ? "전체 접기 ∧" : "전체 보기 ∨"}</b>
            </button>
            {showPrioritySignals && <div id="priority-signal-list">
              {positiveDeviations.slice(0, 5).map((item) => <PrioritySignalAccordion
                key={item.signal}
                item={item}
                summary={summary}
                baselineNotes={profileBaselineNotes}
                medicalCautions={profileMedicalCautions}
                expanded={expandedPrioritySignal === item.signal}
                onToggle={(nextExpanded) => setExpandedPrioritySignal(nextExpanded ? item.signal : "")}
              />)}
              {!positiveDeviations.length && <p className="empty-state">증가한 세부 발화가 없습니다.</p>}
              {negativeDeviations.length > 0 && <>
                <button className="signal-group-toggle" onClick={() => setShowDecreases((value) => !value)}>감소한 변화 {negativeDeviations.length}개 <span>{showDecreases ? "접기" : "보기"}</span></button>
                {showDecreases && negativeDeviations.map((item) => <PrioritySignalAccordion
                  key={item.signal}
                  item={item}
                  summary={summary}
                  baselineNotes={profileBaselineNotes}
                  medicalCautions={profileMedicalCautions}
                  expanded={expandedPrioritySignal === item.signal}
                  onToggle={(nextExpanded) => setExpandedPrioritySignal(nextExpanded ? item.signal : "")}
                />)}
              </>}
              {unchangedDeviations.length > 0 && <>
                <button className="signal-group-toggle quiet" onClick={() => setShowUnchanged((value) => !value)}>변화 없음 {unchangedDeviations.length}개 <span>{showUnchanged ? "접기" : "보기"}</span></button>
                {showUnchanged && unchangedDeviations.map((item) => <PrioritySignalAccordion
                  key={item.signal}
                  item={item}
                  summary={summary}
                  baselineNotes={profileBaselineNotes}
                  medicalCautions={profileMedicalCautions}
                  expanded={expandedPrioritySignal === item.signal}
                  onToggle={(nextExpanded) => setExpandedPrioritySignal(nextExpanded ? item.signal : "")}
                />)}
              </>}
            </div>}
          </section>
        </aside>
      </div>

      <section className="dashboard-card compact-rhythm-report"><header><div><h2>최근 30일 통화 습관</h2></div><button onClick={() => openHeatmapPreview(activeDaySummary?.since || summary.since)}>선택일 보기 ›</button></header><WeekdayTimeHeatmap baselineSummary={activeBaseline} selectedDate={activeDaySummary?.since} onSelectDate={openHeatmapPreview} /></section>

    </>}


    {tab === "talk" && <>
      <div className="talk-analysis-triad">
        <ResponseRetentionChart data={activeBaseline.call_analytics?.response_retention} />
        <TimeRegressionJourney data={activeBaseline.call_analytics?.time_regression} />
        <EmotionTopicMap topics={activeBaseline.call_analytics?.emotion_topics || []} tendency={activeBaseline.call_analytics?.tendency_summary} />
      </div>
    </>}


    {selectedDay && <DailyReportModal
      day={selectedDay}
      elderName={elderName}
      onClose={() => setSelectedDay(null)}
      onAck={ack}
      busy={busy}
    />}

    {heatmapPreview && <HeatmapDayPreviewModal
      preview={heatmapPreview}
      elderName={elderName}
      onClose={() => setHeatmapPreview(null)}
      onOpenDetail={() => {
        setSelectedDay(heatmapPreview.day);
        setHeatmapPreview(null);
      }}
    />}

    {showFamilyMoment && <FamilyMomentModal report={periodReport.heart_report || {}} onClose={() => setShowFamilyMoment(false)} />}

  </div>;
}
