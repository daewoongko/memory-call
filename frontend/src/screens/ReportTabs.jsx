import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import CareCalendar from "./CareCalendar.jsx";
import { BubbleChart, LineChart } from "../components/Charts.jsx";

const CATEGORIES = [
  { id: "insight", label: "종합 현황" },
  { id: "talk", label: "통화 리포트" },
  { id: "plan", label: "일정·복약" },
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
    <header><div><h3>오늘 발화에서 확인된 8개 영역</h3><p>모든 영역을 같은 건수 축으로 비교합니다.</p></div><div className="radar-legend"><span className="today">오늘</span><span className="average">최근 30일 일평균</span></div></header>
    <div className="radar-layout">
      <svg viewBox="0 0 520 340" role="img" aria-label={`8개 영역 오늘 총 ${total}건, 최근 30일 하루 평균과 비교`}>
        {[.25, .5, .75, 1].map((ratio) => <polygon key={ratio} className="radar-grid" points={gridPolygon(ratio)} />)}
        {todayItems.map((_, index) => {
          const [x, y] = point(index, maxValue);
          return <line key={index} className="radar-axis" x1={centerX} y1={centerY} x2={x} y2={y} />;
        })}
        <polygon className="radar-average" points={polygon(averageItems)} />
        <polygon className="radar-today" points={polygon(todayItems)} />
        {todayItems.map((item, index) => {
          const angle = -Math.PI / 2 + index * Math.PI / 4;
          const x = centerX + Math.cos(angle) * labelRadius;
          const y = centerY + Math.sin(angle) * labelRadius;
          const anchor = Math.abs(Math.cos(angle)) < .2 ? "middle" : Math.cos(angle) > 0 ? "start" : "end";
          return <text key={item.key} x={x} y={y} textAnchor={anchor} className="radar-label"><tspan x={x}>{item.label}</tspan><tspan x={x} dy="15">오늘 {item.value} · 평균 {averageItems[index].value.toFixed(1)}</tspan></text>;
        })}
      </svg>
      <div className="radar-values" aria-label="영역별 비교 수치">{todayItems.map((item, index) => <div key={item.key}><span>{item.label}</span><b>{item.value}</b><small>평균 {averageItems[index].value.toFixed(1)}</small></div>)}</div>
    </div>
    <p className="care-domain-policy">진단 점수가 아니라 실제 발화 근거의 관찰 건수입니다. 축별 비율을 따로 키우지 않았습니다.</p>
  </section>;
}

function WeekdayTimeHeatmap({ baselineSummary, selectedDate, onSelectDate }) {
  const heatmap = baselineSummary?.rhythm?.weekday_time_heatmap;
  const weekdays = heatmap?.weekdays || [];
  const timeBlocks = heatmap?.time_blocks || [];
  const cells = heatmap?.cells || [];
  const maxAverage = Math.max(Number(heatmap?.max_average_per_day || 0), 0);
  const cellMap = new Map(cells.map((cell) => [`${cell.weekday}-${cell.start_hour}`, cell]));
  const selectedWeekday = selectedDate
    ? (new Date(`${selectedDate}T12:00:00`).getDay() + 6) % 7
    : -1;
  const intensity = (value) => {
    if (!value || !maxAverage) return 0;
    return Math.max(1, Math.min(5, Math.ceil(value / maxAverage * 5)));
  };
  const peakCell = cells.slice().sort((a, b) => b.average_per_day - a.average_per_day)[0];
  const selectWeekday = (weekday) => {
    if (!selectedDate || !onSelectDate) return;
    const target = new Date(`${selectedDate}T12:00:00`);
    const currentWeekday = (target.getDay() + 6) % 7;
    target.setDate(target.getDate() - ((currentWeekday - weekday + 7) % 7));
    const localDate = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(target.getDate()).padStart(2, "0")}`;
    onSelectDate(localDate);
  };
  return <figure className="weekday-time-heatmap">
    <header><div><b>요일 × 시간대 통화 밀도</b><span>최근 {heatmap?.days || 30}일 · 같은 요일 하루당 평균 통화</span></div><div className="heatmap-legend"><span>적음</span>{[1, 2, 3, 4, 5].map((level) => <i key={level} className={`heat-${level}`} />)}<span>많음</span></div></header>
    {weekdays.length && timeBlocks.length ? <div className="heatmap-scroll"><div className="heatmap-grid" aria-label="최근 30일 요일과 시간대별 평균 통화량 히트맵">
      <span className="heatmap-corner">요일</span>
      {timeBlocks.map((block) => <span className="heatmap-hour" key={block.start_hour}>{String(block.start_hour).padStart(2, "0")}</span>)}
      {weekdays.map((weekday) => <div className={`heatmap-row ${weekday.weekday === selectedWeekday ? "selected" : ""}`} key={weekday.weekday}>
        <button type="button" className="heatmap-weekday" onClick={() => selectWeekday(weekday.weekday)} aria-pressed={weekday.weekday === selectedWeekday}>{weekday.label}<small>{weekday.weekday === selectedWeekday ? "선택일" : `${weekday.days_observed}일`}</small></button>
        {timeBlocks.map((block) => {
          const cell = cellMap.get(`${weekday.weekday}-${block.start_hour}`) || { calls: 0, average_per_day: 0, days_observed: weekday.days_observed };
          const average = Number(cell.average_per_day || 0);
          return <button type="button" className={`heatmap-cell heat-${intensity(average)}`} key={block.start_hour} onClick={() => selectWeekday(weekday.weekday)} title={`${weekday.label}요일 ${block.label} · 총 ${cell.calls}통 / ${cell.days_observed}일 · 하루 평균 ${average.toFixed(1)}통`} aria-label={`${weekday.label}요일 ${block.label}, 하루 평균 ${average.toFixed(1)}통. 이 요일 선택`}>
            {average ? average.toFixed(1) : "–"}
          </button>;
        })}
      </div>)}
    </div></div> : <p className="empty-state">요일별 통화 기록을 집계하고 있습니다.</p>}
    <figcaption>{peakCell?.average_per_day > 0 ? `${peakCell.weekday_label}요일 ${String(peakCell.start_hour).padStart(2, "0")}~${String(peakCell.end_hour).padStart(2, "0")}시에 하루 평균 ${Number(peakCell.average_per_day).toFixed(1)}통으로 가장 많이 모였습니다.` : "최근 30일에 비교할 통화가 없습니다."}</figcaption>
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
    else if (item.signal === "time_confusion") add("orientation", 2, "지남력 단서 재배치", `시간 혼동 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["시계·날짜판 가시성 확인", "같은 시간대 반복 여부 관찰", "갑작스러운 악화라면 통증·감염·수면 변화 함께 확인"]);
    else if (item.signal === "item_location_uncertain") add("item", 3, "자주 찾는 물건 위치 고정", `물건 위치 불확실 발화가 평소보다 증가했습니다.`, ["안경·지갑·리모컨 위치 확인", "고정 보관 위치 표식", "분실 불안 지속 시간 기록"]);
    else if (["loneliness", "longing"].includes(item.signal)) add("emotion", 3, "반복 연락 전 정서 활동 배치", `가족을 찾는 표현이 평소보다 증가했습니다.`, ["연락 집중 시간 전 짧은 대화 배치", "확인된 가족 사진·음악 활용", "활동 뒤 안정 여부 기록"]);
  });
  if ((medication.needs_check || 0) > 0 && !tasks.some((item) => item.key === "medication")) add("medication", 1, "복약 확인 필요 기록 처리", `복약 확인 필요 ${medication.needs_check}건이 남아 있습니다.`, ["약포와 투약 기록 대조", "중복 투약 방지", "확인 결과 기록"]);
  if (!tasks.length) add("routine", 3, "평소 루틴 유지", "월평균에서 크게 벗어난 발화가 없습니다.", ["정해진 일정 유지", "식사·수분·활동 상태 기록", "갑작스러운 변화만 인계"]);
  return tasks.sort((a, b) => a.level - b.level).slice(0, 5);
}

function SignalDetailModal({ signal, summary, baselineNotes = [], medicalCautions = [], onClose }) {
  if (!signal) return null;
  const rows = (summary.time_reports || []).map((row) => {
    const observations = (row.observations || []).filter((item) => item.signal === signal.signal);
    return { ...row, count: observations.reduce((sum, item) => sum + item.count, 0), evidence: observations.flatMap((item) => item.evidence || []) };
  }).filter((row) => row.count > 0);
  const scaleMax = Math.max(1, signal.scaleMax || Math.abs(signal.difference));
  const width = Math.abs(signal.difference) / scaleMax * 50;
  return <div className="daily-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="signal-detail-modal" role="dialog" aria-modal="true">
    <header><div><h2>{signal.label} 상세</h2><p>오늘의 발화 근거와 최근 30일 하루 평균을 함께 봅니다.</p></div><button onClick={onClose} aria-label="상세 닫기">×</button></header>
    <section className={`signal-detail-comparison ${signal.difference > 0 ? "up" : signal.difference < 0 ? "down" : "even"}`}>
      <div className="signal-detail-values"><span>오늘 <b>{signal.today}회</b></span><span>30일 일평균 <b>{signal.average.toFixed(1)}회</b></span><strong>{signal.difference > 0 ? "증가" : signal.difference < 0 ? "감소" : "동일"} {signal.difference >= 0 ? "+" : ""}{signal.difference.toFixed(1)}</strong></div>
      <div className="signal-detail-chart"><span className="signal-diverging-inline" aria-label={`평균 대비 ${signal.difference >= 0 ? "증가" : "감소"} ${Math.abs(signal.difference).toFixed(1)}회`}><i style={{ left: signal.difference < 0 ? `${50 - width}%` : "50%", width: `${Math.max(signal.difference ? 2 : 0, width)}%` }} /></span><Sparkline values={signal.trend} label={`${signal.label} 최근 30일 추이`} tone={signal.difference > 0 ? "alert" : "normal"} /></div>
      <blockquote>“{signal.evidence || "선택일에 표시할 직접 발화 근거가 없습니다."}”</blockquote>
    </section>
    <div className="signal-time-list">{rows.map((row) => <article key={row.key}><time>{row.time_label}</time><b>{row.count}회</b><blockquote>“{row.evidence[0]}”</blockquote></article>)}{!rows.length && <p className="empty-state">시간대별 직접 근거가 없습니다.</p>}</div>
    <div className="signal-solution"><small>담당자 확인 방법</small><p>{signal.action}</p></div>
    <aside className="signal-baseline-note"><b>※ 평소 관찰 기준</b><p>{baselineNotes.length ? baselineNotes.join(" · ") : `최근 30일 하루 평균 ${signal.average.toFixed(1)}회를 비교 기준으로 사용했습니다.`}</p>{medicalCautions.length > 0 && <><b>※ 특히 보고할 변화</b><p>{medicalCautions.join(" · ")}</p></>}</aside>
  </section></div>;
}

function TimeDetailModal({ summary, onOpenRow, onClose }) {
  const rows = (summary.time_reports || []).filter((row) => row.calls > 0);
  const max = Math.max(1, ...rows.map((row) => row.calls));
  return <div className="daily-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="time-detail-modal" role="dialog" aria-modal="true">
    <header><div><p className="eyebrow">시간대별 통화 상세</p><h2>통화량과 주요 발화를 함께 확인합니다</h2></div><button onClick={onClose}>×</button></header>
    <div className="time-detail-list">{rows.map((row) => <button key={row.key} onClick={() => onOpenRow(row)}><time>{row.time_label}</time><div><i style={{ width: `${row.calls / max * 100}%` }} /></div><b>{row.calls}회</b><span>{row.observations?.[0]?.label || "특이 관찰 없음"}</span><em>발화 근거 보기 ›</em></button>)}</div>
  </section></div>;
}

function SafetyChecklist({ elderId, date, risks, priorityTasks }) {
  const key = `care-safety-checks:${elderId}:${date}`;
  const initial = () => { try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; } };
  const [checks, setChecks] = useState(initial);
  useEffect(() => setChecks(initial()), [key]);
  const items = [
    ...(risks || []).map((risk) => ({ id: `risk-${risk.event_id}`, label: `${RISK_LABEL[risk.type] || risk.type} 현재 상태 확인`, detail: risk.evidence })),
    ...priorityTasks.slice(0, 3).map((task) => ({ id: `task-${task.key}`, label: task.title, detail: task.steps[0] })),
    { id: "handover", label: "확인 결과를 근무 인계에 기록", detail: "조치 시각·현재 상태·다음 확인자를 남깁니다." },
  ].filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index);
  const done = items.filter((item) => checks[item.id]).length;
  function toggle(id) { const next = { ...checks, [id]: !checks[id] }; setChecks(next); localStorage.setItem(key, JSON.stringify(next)); }
  return <section className="dashboard-card safety-checklist"><header><div><p className="eyebrow">안전 상태 확인</p><h2>담당자 체크 진행률</h2><p>통화 신호를 실제 상태 확인으로 끝내야 완료됩니다.</p></div><strong>{items.length ? Math.round(done / items.length * 100) : 100}%<small>{done}/{items.length} 완료</small></strong></header><div className="check-progress"><i style={{ width: `${items.length ? done / items.length * 100 : 100}%` }} /></div><div className="care-check-list">{items.map((item) => <label key={item.id} className={checks[item.id] ? "done" : ""}><input type="checkbox" checked={Boolean(checks[item.id])} onChange={() => toggle(item.id)} /><span><b>{item.label}</b><small>{item.detail}</small></span></label>)}</div></section>;
}

function buildOperationalInsight(daySummary, baselineSummary) {
  const deviations = buildDeviations(daySummary, baselineSummary);
  const top = deviations[0];
  const blocks = daySummary?.rhythm?.time_blocks || [];
  const peak = blocks.slice().sort((a, b) => (b.calls || 0) - (a.calls || 0))[0];
  if (!top) return { title: "특이 변화가 확인되지 않았습니다", meaning: "월평균과 비교할 발화 근거가 충분하지 않습니다.", next: "통화 기록이 더 쌓이면 시간과 발화를 함께 비교합니다.", basis: "근거 부족" };
  const nextBySignal = {
    medication_uncertain: "다음 복약 시간 전후에 복용 여부를 다시 묻는 발화가 반복될 가능성이 있습니다.",
    time_confusion: "같은 시간대에 날짜·방문 시각을 다시 확인하는 발화가 이어질 가능성이 있습니다.",
    loneliness: "연락이 몰리는 시간 전에 안부가 없으면 가족을 찾는 표현이 다시 나타날 가능성이 있습니다.",
    meal_uncertain: "식사 직후 기록이 없으면 식사 여부를 다시 묻는 발화가 이어질 가능성이 있습니다.",
  };
  return {
    title: `${top.label}, 월 일평균보다 ${Math.abs(top.difference).toFixed(1)}회 ${top.difference >= 0 ? "많음" : "적음"}`,
    meaning: `${peak?.label || "선택 시간"}에 통화가 집중됐고, “${top.evidence || "직접 발화 근거 없음"}”이 함께 확인됐습니다.`,
    next: nextBySignal[top.signal] || `${top.label} 관련 표현이 같은 생활 시간대에 다시 나타나는지 관찰이 필요합니다.`,
    action: top.action,
    basis: `월 ${baselineSummary?.daily_reports?.length || baselineSummary?.days || 0}일 기준선 · 선택일 ${daySummary?.calls || 0}통 · 규칙 기반 변화 탐지`,
  };
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

const FALLBACK_MED_GUIDANCE = {
  "아침 당뇨약": { indication: "당뇨병 혈당 관리", monitoring_points: ["식사량 변화", "식은땀·떨림·의식 변화", "복용 여부 중복 확인"], review_interval_days: 14, escalation_criteria: "의식 변화, 반복되는 저혈당 의심 증상 또는 식사 불가 시 의료진에게 즉시 보고" },
  "저녁 혈압약": { indication: "고혈압 관리", monitoring_points: ["어지럼·실신", "보행 불안정", "부종"], review_interval_days: 14, escalation_criteria: "실신, 흉통, 호흡곤란 또는 지속되는 심한 어지럼은 의료진에게 신속히 보고" },
};

function MedicationAnalytics({ elderId, medication = {}, selectedDate }) {
  const [catalog, setCatalog] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState({ severity: 0, note: "", observed_flags: [] });
  const [busy, setBusy] = useState(false);
  const load = () => api.getMedications(elderId).then((result) => {
    setCatalog(result.medications || []); setReviews(result.reviews || []);
    setSelectedId((current) => current || result.medications?.[0]?.schedule_id || "");
  });
  useEffect(() => { load().catch(() => { setCatalog([]); setReviews([]); }); }, [elderId]);
  const active = catalog.find((item) => item.schedule_id === selectedId) || catalog[0];
  const guidance = active ? { ...(FALLBACK_MED_GUIDANCE[active.medication_name] || {}), ...active } : null;
  const activeReviews = reviews.filter((item) => item.schedule_id === active?.schedule_id);
  const latest = activeReviews[0];
  const reviewDue = guidance ? (() => { const base = latest?.review_date || selectedDate; const due = new Date(`${base}T00:00:00`); due.setDate(due.getDate() + (guidance.review_interval_days || 14)); return due.toLocaleDateString("ko-KR", { month: "long", day: "numeric" }); })() : "-";
  const nextJudgement = draft.severity >= 3 ? "중증 변화입니다. 임의로 약을 바꾸지 말고 기관 응급·의료진 보고 절차를 우선하세요." : draft.severity === 2 ? "오늘 근무 안에 재확인하고, 지속되거나 기능 저하가 동반되면 처방 의료진에게 보고하세요." : draft.severity === 1 ? `기록 후 ${guidance?.review_interval_days || 14}일 경과 추이를 비교하세요.` : "현재는 기준 상태로 기록하고 예정된 재평가일까지 관찰하세요.";
  async function saveReview() {
    if (!active) return;
    setBusy(true);
    try { await api.addMedicationReview(active.schedule_id, { review_date: selectedDate, severity: Number(draft.severity), observed_flags: draft.observed_flags, note: draft.note }, elderId); await load(); setDraft({ severity: 0, note: "", observed_flags: [] }); } finally { setBusy(false); }
  }
  const total = (medication.confirmed || 0) + (medication.needs_check || 0);
  return <section className="dashboard-card medication-workspace">
    <header><div><p className="eyebrow">환자별 복약 판단 지원</p><h2>약의 목적·주의사항·경과 기록을 함께 봅니다</h2><p>약 변경이나 중단을 지시하지 않으며, 관찰한 변화를 의료진에게 전달할 수 있게 정리합니다.</p></div><div className="medication-summary-chip"><b>{medication.confirmation_rate ?? "-"}%</b><span>발화 기반 확인률 · {total}건</span></div></header>
    <div className="medication-selector">{catalog.map((item) => <button key={item.schedule_id} className={item.schedule_id === active?.schedule_id ? "on" : ""} onClick={() => setSelectedId(item.schedule_id)}><span>{item.scheduled_time}</span><b>{item.medication_name}</b><small>{item.indication || FALLBACK_MED_GUIDANCE[item.medication_name]?.indication || "처방 목적 미등록"}</small></button>)}</div>
    {guidance ? <div className="medication-care-grid">
      <section className="medication-profile-card"><span>현재 복용 정보</span><h3>{guidance.medication_name}</h3><p>{guidance.scheduled_time} · {guidance.dosage_text} · {guidance.indication || "처방 목적 미등록"}</p><dl><div><dt>담당자 관찰 항목</dt><dd>{(guidance.monitoring_points || []).map((point) => <em key={point}>{point}</em>)}</dd></div><div><dt>다음 정기 검토</dt><dd>{reviewDue}</dd></div><div className="escalation"><dt>의료진 보고 기준</dt><dd>{guidance.escalation_criteria || "환자별 보고 기준을 등록해 주세요."}</dd></div></dl></section>
      <section className="medication-review-form"><span>{selectedDate} 경과 기록</span><div className="severity-picker">{[0, 1, 2, 3].map((value) => <button key={value} className={Number(draft.severity) === value ? `on level-${value}` : ""} onClick={() => setDraft({ ...draft, severity: value })}>{["변화 없음", "경미", "주의", "중증"][value]}</button>)}</div><div className="monitor-checks">{(guidance.monitoring_points || []).map((point) => <label key={point}><input type="checkbox" checked={draft.observed_flags.includes(point)} onChange={() => setDraft({ ...draft, observed_flags: draft.observed_flags.includes(point) ? draft.observed_flags.filter((item) => item !== point) : [...draft.observed_flags, point] })} />{point}</label>)}</div><textarea placeholder="관찰 시각, 지속 시간, 기능 변화 등을 기록하세요." value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} /><div className="next-judgement"><small>입력에 따른 다음 판단</small><p>{nextJudgement}</p></div><button className="primary" disabled={busy} onClick={saveReview}>{busy ? "저장 중" : "경과 기록 저장"}</button></section>
      <section className="medication-history"><span>최근 경과</span>{activeReviews.slice(0, 5).map((review) => <article key={review.review_id}><time>{review.review_date}</time><b className={`severity-${review.severity}`}>{["변화 없음", "경미", "주의", "중증"][review.severity]}</b><p>{review.note || review.observed_flags?.join(" · ") || "메모 없음"}</p></article>)}{!activeReviews.length && <p className="empty-state">아직 담당자 경과 기록이 없습니다.</p>}</section>
    </div> : <p className="empty-state">등록된 복약 일정이 없습니다.</p>}
    <div className="medication-aggregate"><article><span>확인 필요</span><b>{medication.needs_check || 0}건</b></article><article><span>중복 의심</span><b>{medication.duplicate_suspected || 0}건</b></article><article><span>거부</span><b>{medication.refused || 0}건</b></article><article><span>직전 기간 대비</span><b>{medication.needs_check_change > 0 ? "+" : ""}{medication.needs_check_change || 0}건</b></article></div>
    {(medication.registered_signal_matches || []).length > 0 && <section className="medication-signal-links"><header><div><span>등록 기준과 일치한 발화</span><h3>약별 관찰 연결</h3></div><small>담당자가 등록한 기준만 표시합니다.</small></header><div>{medication.registered_signal_matches.map((item) => <article key={`${item.schedule_id}-${item.signal}-${item.link_level}`}><span className={item.link_level === "escalation" ? "escalation" : "monitoring"}>{item.link_level === "escalation" ? "보고 기준" : "관찰 기준"}</span><div><b>{item.medication_name} · {item.signal_label}</b><p>{item.criterion_text}</p><blockquote>“{item.evidence?.[0]?.evidence || "직접 발화 근거를 확인하세요."}”</blockquote></div><strong>{item.count}건</strong></article>)}</div></section>}
  </section>;
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
}) {
  const [tab, setTab] = useState("insight");
  const [busy, setBusy] = useState(false);
  const [selectedDay, setSelectedDay] = useState(null);
  const [showFamilyMoment, setShowFamilyMoment] = useState(false);
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [showTimeDetails, setShowTimeDetails] = useState(false);
  const [showDecreases, setShowDecreases] = useState(false);
  const [showUnchanged, setShowUnchanged] = useState(false);
  const [planVersion, setPlanVersion] = useState(0);
  const profileBaselineNotes = textList(patientProfile?.care_baseline);
  const profileMedicalCautions = textList(patientProfile?.medical_cautions);

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
    { label: "발화 기반 관찰", value: careTotal, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.observation_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.observation_count || 0) },
    { label: "반복 발화", value: summary.repeat_total, unit: "회", average: dailyReports.reduce((sum, day) => sum + (day.repeated_total || day.repeat_total || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.repeated_total || day.repeat_total || 0) },
    { label: "안전 신호", value: summary.risks.length, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.risk_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.risk_count || 0), status: unread.length ? `미확인 ${unread.length}건` : "모두 확인" },
  ];
  const priorityTasks = useMemo(() => buildPriorityTasks(deviations, summary.risks, summary.medication), [deviations, summary.risks, summary.medication]);
  const operationalInsight = useMemo(() => buildOperationalInsight(activeDaySummary, activeBaseline), [activeDaySummary, activeBaseline]);

  return <div className="report-dashboard">
    <div className="report-toolbar">
      <nav className="cat-tabs">
        {CATEGORIES.map((category) => <button key={category.id} className={tab === category.id ? "on" : ""} onClick={() => setTab(category.id)}>{category.label}</button>)}
      </nav>
    </div>

    {tab === "insight" && <>
      <div className="manager-focus-layout">
        <section className="dashboard-card manager-combined-overview">
          <header><div><h2>{elderName} 어르신의 오늘 관찰 요약</h2><p>{patientProfile?.diagnosis_label || "등록된 진단 정보 없음"} · 오늘과 최근 30일 하루 평균을 비교합니다.</p></div><button className="family-moment-button" onClick={() => setShowFamilyMoment(true)}>가족에게 전할 순간 <b>{summary.meaningful_total || 0}</b><span>요점 보기 ›</span></button></header>
          <div className="manager-stat-grid">{kpis.map((item) => { const delta = item.value - item.average; return <article key={item.label}><span>{item.label}</span><strong>{item.value}<small>{item.unit}</small></strong><em>{item.status || `평균 대비 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}</em><Sparkline values={item.trend} label={`${item.label} 최근 30일 추이`} tone={item.status && unread.length ? "alert" : "normal"} /></article>; })}</div>
          <CareDomainRadar todayItems={careItems} averageItems={averageCareItems} />
        </section>
        <aside className="dashboard-card daily-priority-panel"><header><div><h2>확인 우선순위</h2><p>이상 발화와 안전·복약 기록을 함께 반영했습니다.</p></div></header><ol>{priorityTasks.map((task, index) => <li key={task.key} className={`priority-${task.level}`}><span>{index + 1}</span><div><b>{task.title}</b><p>{task.reason}</p><ul>{task.steps.map((step) => <li key={step}>{step}</li>)}</ul></div></li>)}</ol><section className="priority-signal-summary"><header><h3>평소와 달랐던 세부 발화</h3><p>증가한 항목부터 확인합니다.</p></header><div>{positiveDeviations.slice(0, 5).map((item) => <button key={item.signal} onClick={() => setSelectedSignal({ ...item, scaleMax: Math.max(1, ...deviations.map((row) => Math.abs(row.difference))) })}><span><b>{item.label}</b><small>오늘 {item.today}회 · 평균 {item.average.toFixed(1)}회</small></span><strong>증가 +{item.difference.toFixed(1)}</strong><em>자세히 보기 ›</em></button>)}{!positiveDeviations.length && <p className="empty-state">증가한 세부 발화가 없습니다.</p>}{negativeDeviations.length > 0 && <><button className="signal-group-toggle" onClick={() => setShowDecreases((value) => !value)}>감소한 변화 {negativeDeviations.length}개 <span>{showDecreases ? "접기" : "보기"}</span></button>{showDecreases && negativeDeviations.map((item) => <button key={item.signal} onClick={() => setSelectedSignal({ ...item, scaleMax: Math.max(1, ...deviations.map((row) => Math.abs(row.difference))) })}><span><b>{item.label}</b><small>오늘 {item.today}회 · 평균 {item.average.toFixed(1)}회</small></span><strong className="down">감소 {item.difference.toFixed(1)}</strong><em>자세히 보기 ›</em></button>)}</>}{unchangedDeviations.length > 0 && <><button className="signal-group-toggle quiet" onClick={() => setShowUnchanged((value) => !value)}>변화 없음 {unchangedDeviations.length}개 <span>{showUnchanged ? "접기" : "보기"}</span></button>{showUnchanged && unchangedDeviations.map((item) => <button key={item.signal} onClick={() => setSelectedSignal({ ...item, scaleMax: Math.max(1, ...deviations.map((row) => Math.abs(row.difference))) })}><span><b>{item.label}</b><small>오늘 {item.today}회 · 평균 {item.average.toFixed(1)}회</small></span><strong className="even">변화 없음</strong><em>자세히 보기 ›</em></button>)}</>}</div></section>{(profileBaselineNotes.length || profileMedicalCautions.length) > 0 && <div className="patient-baseline"><div><small>평소 관찰 기준</small><p>{profileBaselineNotes.join(" · ")}</p></div><div><small>특히 보고할 변화</small><p>{profileMedicalCautions.join(" · ")}</p></div></div>}</aside>
      </div>

      <section className="dashboard-card compact-rhythm-report"><header><div><h2>최근 30일 통화 습관</h2><p>요일·시간대 통화 밀도를 선택해 해당 날짜의 발화를 확인합니다.</p></div><button onClick={() => setShowTimeDetails(true)}>선택일 상세보기 ›</button></header><WeekdayTimeHeatmap baselineSummary={activeBaseline} selectedDate={activeDaySummary?.since} onSelectDate={(value) => onPeriod?.({ mode: "day", value })} /></section>

      <SafetyChecklist elderId={elderId} date={summary.since} risks={summary.risks} priorityTasks={priorityTasks} />
    </>}


    {tab === "talk" && <>
      <section className="dashboard-card talk-brief">
        <header><div><p className="eyebrow">선택일 통화 분석</p><h2>전체 {summary.calls}회 · 총 {Math.round(summary.total_seconds / 60)}분</h2><p>날짜는 화면 상단에서 변경합니다. 이 페이지에서는 통화 패턴과 근거만 확인합니다.</p></div><button onClick={() => setShowTimeDetails(true)}>전체 시간대 상세 ›</button></header>
        <div className="talk-brief-stats"><span>발화 관찰 <b>{careTotal}건</b></span><span>반복 발화 <b>{summary.repeat_total}회</b></span><span>안전 신호 <b>{summary.risks.length}건</b></span><span>가족 전달 <b>{summary.meaningful_total || 0}건</b></span></div>
        <section className="operational-forecast" aria-label="선택한 날의 패턴 기반 주의 예측"><header><div><span>월평균 대비 해석</span><h3>{operationalInsight.title}</h3></div><b>{operationalInsight.basis}</b></header><div className="forecast-grid"><article><small>오늘 확인된 의미</small><p>{operationalInsight.meaning}</p></article><article><small>다음 근무 주의점</small><p>{operationalInsight.next}</p></article><article><small>선제 행동</small><p>{operationalInsight.action || "추가 행동 근거가 없습니다."}</p></article></div></section>
      </section>
      <section className="dashboard-card compact-time-report"><header><div><h2>요일과 시간대가 만나는 지점에서 집중 구간을 확인하세요</h2></div><button onClick={() => setShowTimeDetails(true)}>선택일 발화 보기 ›</button></header><WeekdayTimeHeatmap baselineSummary={activeBaseline} selectedDate={activeDaySummary?.since} onSelectDate={(value) => onPeriod?.({ mode: "day", value })} /></section>
      <section className="dashboard-card evidence-shortlist"><header><div><p className="eyebrow">발화 근거 바로가기</p><h2>변화가 큰 항목</h2></div></header><div>{deviations.slice(0, 5).map((item) => <button key={item.signal} onClick={() => setSelectedSignal(item)}><span>{item.label}</span><b>{item.today}회</b><small>{item.difference >= 0 ? "+" : ""}{item.difference.toFixed(1)} · 발생 시각 보기 ›</small></button>)}</div></section>
    </>}


    {tab === "plan" && <div className="plan-dashboard report-plan-dashboard">
      <MedicationAnalytics elderId={elderId} medication={summary.medication} selectedDate={summary.since} />
      <CareCalendar elderId={elderId} refreshKey={planVersion} onChanged={() => setPlanVersion((value) => value + 1)} />
    </div>}

    {selectedDay && <DailyReportModal
      day={selectedDay}
      elderName={elderName}
      onClose={() => setSelectedDay(null)}
      onAck={ack}
      busy={busy}
    />}

    {showFamilyMoment && <FamilyMomentModal report={periodReport.heart_report || {}} onClose={() => setShowFamilyMoment(false)} />}
    {selectedSignal && <SignalDetailModal signal={selectedSignal} summary={summary} baselineNotes={profileBaselineNotes} medicalCautions={profileMedicalCautions} onClose={() => setSelectedSignal(null)} />}
    {showTimeDetails && <TimeDetailModal summary={summary} onClose={() => setShowTimeDetails(false)} onOpenRow={(row) => { setShowTimeDetails(false); setSelectedDay({ ...row, range_label: `${dateParts(row.date).date} ${row.time_label}`, analysis_title: "해당 시간대의 발화 근거와 담당자 행동" }); }} />}

  </div>;
}
