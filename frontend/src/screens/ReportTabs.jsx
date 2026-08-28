import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { BubbleChart } from "../components/Charts.jsx";

const CATEGORIES = [
  { id: "insight", label: "종합 현황" },
  { id: "talk", label: "통화 리포트" },
];

const RISK_LABEL = {
  fall: "낙상", chest_pain: "가슴 통증", breathing: "호흡 곤란",
  lost: "길 잃음",
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

function ReportDetailModal({ eyebrow, title, onClose, children, className = "" }) {
  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return <div className="report-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className={`report-detail-modal ${className}`} role="dialog" aria-modal="true" aria-label={title}>
      <header>
        <div>{eyebrow && <small>{eyebrow}</small>}<h2>{title}</h2></div>
        <button type="button" onClick={onClose} aria-label="상세 보기 닫기">×</button>
      </header>
      {children}
    </section>
  </div>;
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
  ["meal_uncertain", "식사 불확실"],
  ["item_location_uncertain", "물건 위치"],
  ["loneliness", "외로움"],
  ["longing", "그리움"],
];

const SIGNAL_ACTIONS = {
  time_confusion: "날짜와 시간을 잘 보이는 곳에 표시하고 오전·오후를 함께 말해 주세요.",
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
  const centerY = 190;
  const radius = 138;
  const labelRadius = 178;
  const observedMax = Math.max(0, ...todayItems.map((item) => item.value), ...averageItems.map((item) => item.value));
  const maxValue = observedMax > 0 ? observedMax * 1.2 : 1;
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
      <svg viewBox="0 0 520 400" role="img" aria-label={`8개 영역 오늘 총 ${total}건, 최근 30일 하루 평균과 비교`}>
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

function buildPriorityTasks(deviations, risks = []) {
  const tasks = [];
  const add = (key, level, title, reason, steps) => {
    if (!tasks.some((item) => item.key === key)) tasks.push({ key, level, title, reason, steps });
  };
  if (risks.some((risk) => !risk.acknowledged)) add("safety", 1, "안전 신호부터 직접 확인", "미확인 안전 발화가 남아 있습니다.", ["발생 시각과 현재 상태 확인", "긴급하면 119 또는 의료진에게 연락", "확인 결과를 가족끼리 공유하기"]);
  deviations.filter((item) => item.difference > 0).forEach((item) => {
    if (item.signal === "meal_uncertain") add("meal", 2, "식사 여부 확인", `식사 불확실 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["오늘 식사 여부 직접 확인", "섭취량과 식사 시각 메모", "식욕 저하가 지속되면 의료진과 상담"]);
    else if (item.signal === "time_confusion") add("orientation", 2, "시간 단서 다시 확인", `시간 혼동 발화가 월평균보다 ${item.difference.toFixed(1)}회 많았습니다.`, ["시계와 날짜판이 잘 보이는지 확인", "같은 시간대에 반복되는지 관찰", "갑작스러운 변화라면 의료진과 상담"]);
    else if (item.signal === "item_location_uncertain") add("item", 3, "자주 찾는 물건 위치 고정", `물건 위치 불확실 발화가 평소보다 증가했습니다.`, ["안경·지갑·리모컨 위치 확인", "고정 보관 위치 표식", "분실 불안 지속 시간 기록"]);
    else if (["loneliness", "longing"].includes(item.signal)) add("emotion", 3, "짧은 가족 연락 준비", `가족을 찾는 표현이 평소보다 증가했습니다.`, ["자주 찾는 시간 전에 짧게 연락", "익숙한 가족 사진이나 음악 활용", "대화 뒤 편안해졌는지 확인"]);
  });
  if (!tasks.length) add("routine", 3, "평소 생활 흐름 유지", "월평균에서 크게 벗어난 발화가 없습니다.", ["식사·수분·활동 상태 기록", "익숙한 생활 순서 유지", "갑작스러운 변화는 가족과 공유"]);
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
      <div className="priority-signal-action"><b>가족 확인</b><p>{item.action}</p></div>
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
  const current = data.current_minutes;
  const baseline = data.baseline_minutes;
  const change = data.change_minutes;
  const chartValues = [baseline, ...samples.map((item) => item.minutes)].filter(Number.isFinite);
  const rawMin = chartValues.length ? Math.min(...chartValues) : 0;
  const rawMax = chartValues.length ? Math.max(...chartValues) : 1;
  const rawSpan = Math.max(1, rawMax - rawMin);
  const scalePadding = Math.max(1, Math.ceil(rawSpan * .4));
  const scaleMin = Math.max(0, Math.floor(rawMin - scalePadding));
  const scaleMax = Math.max(scaleMin + 4, Math.ceil(rawMax + scalePadding));
  const scaleSpan = scaleMax - scaleMin;
  const hasAxisBreak = scaleMin > 0;
  const chartWidth = 620;
  const chartHeight = 250;
  const chartPadding = { top: 24, right: 22, bottom: 42, left: 54 };
  const plotWidth = chartWidth - chartPadding.left - chartPadding.right;
  const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom;
  const pointInset = Math.min(18, plotWidth / Math.max(2, samples.length * 2));
  const xAt = (index) => chartPadding.left + pointInset + (samples.length === 1 ? (plotWidth - pointInset * 2) / 2 : index * (plotWidth - pointInset * 2) / (samples.length - 1));
  const yAt = (minutes) => chartPadding.top + plotHeight - ((minutes - scaleMin) / scaleSpan * plotHeight);
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
      ? "수면·불안처럼 같은 시기에 달라진 요인이 있었는지 먼저 확인하세요."
      : "현재 흐름을 기준선으로 두고 갑작스러운 단축이 생기는지 관찰하세요.";
  return <section className="dashboard-card retention-analysis">
    <header><div><span>01</span><h2>답변 유지 시간</h2></div>{current != null && <strong>{current}<small>분</small></strong>}</header>
    {samples.length && current != null && baseline != null ? <>
      <div className="retention-layout">
        <div className="retention-chart" aria-label={`최근 반복 발화 간격 추세${hasAxisBreak ? `, 0분부터 ${scaleMin}분까지 축 생략` : ""}`}>
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img">
            {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}>
              <line className="retention-grid" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={chartPadding.top + plotHeight * ratio} y2={chartPadding.top + plotHeight * ratio} />
              {!(hasAxisBreak && ratio === 1) && <text className="retention-y-label" x={chartPadding.left - 10} y={chartPadding.top + plotHeight * ratio + 4}>{Math.round(scaleMax - scaleSpan * ratio)}</text>}
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
            {samples.map((item, index) => <g key={`point-${index}`}>
              <circle className="retention-trend-point" cx={xAt(index)} cy={yAt(item.minutes || 0)} r={index === samples.length - 1 ? 6 : 4} />
              <text className="retention-point-value" x={xAt(index)} y={Math.max(13, yAt(item.minutes || 0) - 10)}>{Math.round(item.minutes || 0)}</text>
            </g>)}
            {hasAxisBreak && <g className="retention-axis-break">
              <rect x={chartPadding.left - 15} y={chartPadding.top + plotHeight - 10} width="32" height="17" />
              <path d={`M ${chartPadding.left - 9} ${chartPadding.top + plotHeight - 2} q 4 -7 8 0 t 8 0`} />
              <text x={chartPadding.left + 20} y={chartPadding.top + plotHeight + 5}>0~{scaleMin}분 생략</text>
            </g>}
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
  const [detailOpen, setDetailOpen] = useState(false);
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
    return { x: 55 + ratio * 650, y: 124 + Math.sin(ratio * Math.PI * 3) * 48 };
  };
  const roadPoints = Array.from({ length: 91 }, (_, index) => roadPoint(index / 90 * maxAge));
  const journeyPoints = roadPoints.map((point) => `${point.x},${point.y}`).join(" ");
  const currentPoint = roadPoint(currentAge);
  const lifeMarkers = [
    { age: 5, label: "유아기", icon: "●" },
    { age: 15, label: "학창기", icon: "◆" },
    { age: 25, label: "청년기", icon: "▲" },
    { age: 45, label: "성인기", icon: "■" },
    { age: 65, label: "중년기", icon: "★" },
    { age: Math.min(82, currentAge), label: "노년기", icon: "◎" },
  ].filter((marker, index, all) => marker.age <= currentAge && all.findIndex((item) => item.age === marker.age) === index);
  const orderedStages = stages.slice().sort((left, right) => new Date(left.at || 0) - new Date(right.at || 0));
  const transitions = orderedStages.filter((stage, index) => index === 0 || stage.label !== orderedStages[index - 1].label);
  const firstSnapshot = transitions[0];
  const lastSnapshot = transitions.at(-1);
  const middlePool = transitions.slice(1, -1).filter((stage) => stage.label !== firstSnapshot?.label && stage.label !== lastSnapshot?.label);
  const middleSnapshot = middlePool[Math.floor(middlePool.length / 2)] || transitions[Math.floor(transitions.length / 2)];
  const snapshots = [firstSnapshot, middleSnapshot, lastSnapshot].filter((stage, index, all) => stage && all.indexOf(stage) === index);
  const routeStart = firstSnapshot || destination;
  const routeStartPoint = routeStart ? roadPoint(routeStart.age) : null;
  const travelledPoints = routeStart
    ? roadPoints.filter((_, index) => {
      const age = index / 90 * maxAge;
      return age >= Math.min(routeStart.age, currentAge) && age <= Math.max(routeStart.age, currentAge);
    }).map((point) => `${point.x},${point.y}`).join(" ")
    : "";
  const latestSnapshotTime = lastSnapshot?.at ? new Date(lastSnapshot.at) : null;
  const snapshotPeriod = (stage, index) => {
    if (index === snapshots.length - 1) return "지금";
    const at = stage.at ? new Date(stage.at) : null;
    if (!at || !latestSnapshotTime || Number.isNaN(at.getTime()) || Number.isNaN(latestSnapshotTime.getTime())) return index === 0 ? "관찰 초반" : "관찰 중간";
    const days = Math.max(0, Math.round((latestSnapshotTime - at) / 86_400_000));
    if (days >= 30) return `${Math.round(days / 30)}개월 전`;
    if (days >= 7) return `${Math.round(days / 7)}주 전`;
    if (days >= 1) return `${days}일 전`;
    return index === 0 ? "관찰 초반" : "최근";
  };
  const renderRoad = (expanded = false) => <svg className={`life-road${expanded ? " expanded" : ""}`} viewBox="0 0 760 250" role="img" aria-label={`${routeStart?.label || "첫 관찰 지점"}에서 현재 ${currentAge}세까지 이어지는 인생 여정`}>
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
    {routeStartPoint && <g className="life-regression-marker" transform={`translate(${routeStartPoint.x} ${routeStartPoint.y})`}><circle r="13" /><circle r="5" /><text y="-22">첫 관찰 · {routeStart.label}</text></g>}
    <g className="life-current-marker" transform={`translate(${currentPoint.x} ${currentPoint.y})`}><circle r="14" /><circle r="5" /><text y="-23">현재 {currentAge}세</text></g>
  </svg>;
  const snapshotStrip = <div className="life-stage-snapshots" aria-label="최근 시간 역행 발화 변화">
    {snapshots.map((stage, index) => <article className={index === snapshots.length - 1 ? "now" : ""} key={`${stage.label}-${stage.at}-${index}`}>
      <small>{snapshotPeriod(stage, index)}</small>
      <strong>{stage.label}</strong>
      <span>{stage.age}세 전후 발화</span>
    </article>)}
  </div>;
  return <section className="dashboard-card regression-journey">
    <header><div><span>02</span><h2>시간 역행 지점</h2></div><strong>현재 {currentAge}세</strong></header>
    <div className="life-road-wrap report-chart-preview" role="button" tabIndex="0" aria-haspopup="dialog" aria-label="시간 역행 지점 그래프 크게 보기" onClick={() => setDetailOpen(true)} onKeyDown={(event) => ["Enter", " "].includes(event.key) && setDetailOpen(true)}>
      {renderRoad()}
    </div>
    {snapshots.length > 0 && snapshotStrip}
    {lastSnapshot && <div className="life-current-position"><small>지금 발화가 머무는 시점</small><strong>{lastSnapshot.label} · {lastSnapshot.age}세 전후</strong><p>실제 나이는 {currentAge}세이며, 최근 발화 내용은 이 생애 시점과 가장 가깝습니다.</p></div>}
    {destination && <aside className="life-road-cause">
      <small>이 시점으로 이어진 말</small>
      <strong>{destination.label} · {destination.count}회 관찰</strong>
      {destination.quote && <blockquote>“{destination.quote}”</blockquote>}
    </aside>}
    {!destination && <p className="empty-state">과거 역할과 연결되는 직접 발화가 확인되지 않았습니다.</p>}
    {detailOpen && <ReportDetailModal eyebrow={`현재 ${currentAge}세`} title="시간 역행 지점 자세히 보기" className="life-road-modal" onClose={() => setDetailOpen(false)}>
      <div className="report-modal-chart life-road-modal-chart">{renderRoad(true)}</div>
      {snapshots.length > 0 && snapshotStrip}
      {lastSnapshot && <div className="life-current-position"><small>지금 발화가 머무는 시점</small><strong>{lastSnapshot.label} · {lastSnapshot.age}세 전후</strong><p>실제 나이는 {currentAge}세입니다. 과거 역할과 연결된 직접 발화의 시점 변화를 보여줍니다.</p></div>}
      {destination?.quote && <blockquote className="report-modal-quote">“{destination.quote}”</blockquote>}
    </ReportDetailModal>}
  </section>;
}

const TOPIC_STATUS = {
  now: { key: "now", label: "즉시 확인", color: "#b8332a", hint: "위험 발화가 나온 주제" },
  watch: { key: "watch", label: "지켜보기", color: "#bd7d0e", hint: "부담 표현이 잦음" },
  calm: { key: "calm", label: "편안함", color: "#0f8a70", hint: "" },
};

function topicStatus(item, medianBurden) {
  if (Number(item.risk_count || 0) > 0) return TOPIC_STATUS.now;
  if (Number(item.burden_ratio || 0) >= Math.max(.2, medianBurden)) return TOPIC_STATUS.watch;
  return TOPIC_STATUS.calm;
}

function compactDay(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : `${date.getMonth() + 1}/${date.getDate()}`;
}

function compactRiskStamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}/${date.getDate()} ${hour}:${minute}`;
}

function TopicFindings({ tendency, topics, risks }) {
  const [detail, setDetail] = useState(null);
  const findings = [];
  const riskTopic = topics.slice().sort((a, b) => Number(b.risk_count || 0) - Number(a.risk_count || 0))[0];
  const riskDates = [...new Set(risks.map((risk) => compactDay(risk.at)))].slice(0, 3).join(", ");
  const orderedRisks = risks.slice().sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0));
  const latestRisk = orderedRisks.find((risk) => !risk.acknowledged) || orderedRisks[0] || null;
  const latestRiskTopic = latestRisk
    ? topics.find((item) => (item.risk_types || []).includes(latestRisk.type))?.topic || "건강"
    : "";
  if (risks.length) {
    findings.push({
      status: TOPIC_STATUS.now,
      text: `${riskTopic?.risk_count ? riskTopic.topic : "건강"} 이야기에서 위험 발화${riskDates ? ` · ${riskDates}` : ""}`,
      metric: `${risks.length}건`,
      risk: latestRisk,
      riskTopic: latestRiskTopic,
    });
  }

  if (tendency?.sufficient_period) {
    const burden = tendency?.burden_ranking?.[0];
    if (burden?.eligible && Number(burden.burden_ratio || 0) >= .2) {
      findings.push({
        status: TOPIC_STATUS.watch,
        text: `${burden.category} 이야기 중 부담 표현 · ${burden.calls}통 중 ${burden.burden_calls}통`,
        metric: `${Math.round(Number(burden.burden_ratio) * 100)}%`,
      });
    }
    const hardest = tendency?.hardest_time;
    if (Number(hardest?.rate_per_100 || 0) >= 1) {
      const startHour = Number(hardest.start_hour || 0);
      const dayPart = startHour < 5 ? "새벽" : startHour < 12 ? "아침" : startHour < 18 ? "오후" : "저녁";
      const timeLabel = `${dayPart} ${String(hardest.label || "").replace(/:00/g, "")}시`;
      findings.push({
        status: TOPIC_STATUS.watch,
        text: `${timeLabel}에 몰림`,
        metric: `100발화당 ${hardest.rate_per_100}건`,
      });
    }
  }

  if (!findings.length) {
    const days = Number(tendency?.period_days || 30);
    findings.push({
      status: TOPIC_STATUS.calm,
      text: `지난 ${days}일 · 눈에 띄는 부담 신호 없음`,
      metric: `통화 ${Number(tendency?.total_calls || 0)}건 기준`,
    });
  }

  const watchFindings = findings.filter((finding) => finding.status.key === "watch");
  const primaryFindings = findings.filter((finding) => finding.status.key !== "watch");

  return <>
    <div className="topic-findings">
      {primaryFindings.map((finding, index) => <div className={`topic-finding-row ${finding.status.key}`} key={`${finding.status.key}-${index}`}>
        <span>{finding.status.label}</span><p>{finding.text}</p>
        {finding.risk ? <button type="button" className="topic-finding-count" onClick={() => setDetail({ type: "risk", finding })} aria-label={`${finding.metric} 자세히 보기`}>{finding.metric}</button> : <strong>{finding.metric}</strong>}
      </div>)}
      {watchFindings.length > 0 && <div className="topic-finding-row watch topic-watch-group">
        <span>지켜보기</span><p>조금 더 살펴볼 변화</p><button type="button" className="topic-finding-count" onClick={() => setDetail({ type: "watch", findings: watchFindings })} aria-label={`${watchFindings.length}건 자세히 보기`}>{watchFindings.length}건</button>
      </div>}
    </div>
    {detail?.type === "risk" && <ReportDetailModal eyebrow="즉시 확인" title={`${detail.finding.metric} 위험 발화 상세`} onClose={() => setDetail(null)}>
      <article className={`topic-modal-risk ${detail.finding.risk.level === "high" ? "high" : "medium"}`}>
        <header><span>{RISK_LABEL[detail.finding.risk.type] || detail.finding.risk.type}</span><time>{compactRiskStamp(detail.finding.risk.at)} · {detail.finding.riskTopic}</time></header>
        <blockquote>“{detail.finding.risk.quote || detail.finding.risk.evidence}”</blockquote>
        <p>{detail.finding.risk.action || detail.finding.risk.meaning || "현재 상태와 주변 환경을 직접 확인해 주세요."}</p>
      </article>
    </ReportDetailModal>}
    {detail?.type === "watch" && <ReportDetailModal eyebrow="지켜보기" title={`${detail.findings.length}건 변화 자세히 보기`} onClose={() => setDetail(null)}>
      <div className="topic-modal-watch-list">
        {detail.findings.map((finding, index) => <article key={`watch-modal-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><p>{finding.text}</p><strong>{finding.metric}</strong></article>)}
      </div>
    </ReportDetailModal>}
  </>;
}

function EmotionTopicMap({ topics = [], tendency = null, risks = [] }) {
  const [graphOpen, setGraphOpen] = useState(false);
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
  const riskTopicName = risks.length
    ? points.find((item) => (item.risk_types || []).some((type) => risks.some((risk) => risk.type === type)))?.topic
      || points.find((item) => /건강|신체/.test(item.topic))?.topic
      || points[0]?.topic
    : "";
  const medianDuration = median(points.map((item) => item.duration));
  const medianBurden = median(points.map((item) => item.burden));
  const actualDurationMin = Math.min(...points.map((item) => item.duration), medianDuration);
  const actualDurationMax = Math.max(...points.map((item) => item.duration), medianDuration);
  const durationSpan = Math.max(actualDurationMax - actualDurationMin, medianDuration * .3, 1);
  const durationCenter = (actualDurationMin + actualDurationMax) / 2;
  const durationMin = durationCenter - durationSpan / 2;
  const durationMax = durationCenter + durationSpan / 2;
  const actualBurdenMin = Math.min(...points.map((item) => item.burden), medianBurden);
  const actualBurdenMax = Math.max(...points.map((item) => item.burden), medianBurden);
  const burdenSpan = Math.max(actualBurdenMax - actualBurdenMin, .1);
  const burdenCenter = (actualBurdenMin + actualBurdenMax) / 2;
  const burdenMin = burdenCenter - burdenSpan / 2;
  const burdenMax = burdenCenter + burdenSpan / 2;
  const plot = { left: 72, right: 718, top: 54, bottom: 438, midX: 395, midY: 246 };
  const scaleAroundMedian = (value, split, min, max, low, middle, high) => {
    if (value === split) return middle;
    if (value < split) return low + (value - min) / Math.max(.001, split - min) * (middle - low) * .92;
    return middle + (high - middle) * (.08 + (value - split) / Math.max(.001, max - split) * .92);
  };
  const plotted = points.map((item, index) => {
    const radius = 15 + Math.sqrt(item.calls / maxCalls) * 38;
    const x = scaleAroundMedian(item.duration, medianDuration, durationMin, durationMax, plot.left + radius, plot.midX, plot.right - radius);
    const y = scaleAroundMedian(item.burden, medianBurden, burdenMin, burdenMax, plot.bottom - radius, plot.midY, plot.top + radius);
    return {
      ...item,
      status: item.topic === riskTopicName ? TOPIC_STATUS.now : topicStatus(item, medianBurden),
      radius,
      x,
      y,
      labelSide: x < plot.left + 130 ? 1 : x > plot.right - 130 ? -1 : x >= plot.midX ? 1 : -1,
      sourceIndex: index,
    };
  }).sort((a, b) => b.radius - a.radius);
  const labelByTopic = new Map();
  [-1, 1].forEach((side) => {
    const sidePoints = plotted.filter((item) => item.labelSide === side).sort((a, b) => b.radius - a.radius);
    const occupied = [];
    const topLimit = plot.top + 20;
    const bottomLimit = plot.bottom - 24;
    sidePoints.forEach((item) => {
      const preferredDirection = item.sourceIndex % 2 === 0 ? -1 : 1;
      const nearOffset = item.radius + 18;
      const rawCandidates = [
        item.y + preferredDirection * nearOffset,
        item.y - preferredDirection * nearOffset,
        item.y + preferredDirection * (nearOffset + 34),
        item.y - preferredDirection * (nearOffset + 34),
      ];
      const scanCandidates = Array.from({ length: 12 }, (_, index) => topLimit + index * ((bottomLimit - topLimit) / 11))
        .sort((left, right) => Math.abs(left - item.y) - Math.abs(right - item.y));
      const candidates = [...rawCandidates, ...scanCandidates]
        .map((value) => Math.max(topLimit, Math.min(bottomLimit, value)));
      const y = candidates.find((candidate) => occupied.every((taken) => Math.abs(taken - candidate) >= 34))
        ?? candidates.reduce((best, candidate) => {
          const distance = occupied.length ? Math.min(...occupied.map((taken) => Math.abs(taken - candidate))) : Infinity;
          return distance > best.distance ? { value: candidate, distance } : best;
        }, { value: Math.max(topLimit, Math.min(bottomLimit, item.y)), distance: -1 }).value;
      occupied.push(y);
      labelByTopic.set(item.topic, { y, x: item.x + side * (item.radius + 13), side });
    });
  });
  const renderScatter = (expanded = false) => <svg className={`topic-scatter${expanded ? " expanded" : ""}`} viewBox="0 0 790 525" role="img" aria-label="주제별 평균 통화 시간과 부담 표현 비율 버블 산점도">
    <rect className="topic-plot-bg" x={plot.left} y={plot.top} width={plot.right - plot.left} height={plot.bottom - plot.top} rx="8" />
    <line className="topic-median-line" x1={plot.left} x2={plot.right} y1={plot.midY} y2={plot.midY} />
    <line className="topic-median-line" y1={plot.top} y2={plot.bottom} x1={plot.midX} x2={plot.midX} />
    <text className="topic-quadrant-label right" x={plot.right - 14} y={plot.top + 22}>개입 필요</text>
    {plotted.map((item) => {
      const label = labelByTopic.get(item.topic);
      const lineStartX = item.x + label.side * item.radius * .72;
      return <g className={`topic-point ${item.status.key}`} key={item.topic} role="img" aria-label={`${item.topic}, ${item.status.label}`}>
        <title>{`${item.topic} · ${item.calls}통 · 평균 ${item.duration}분 · 부담 표현 ${Math.round(item.burden * 100)}% · ${item.emotion}`}</title>
        {item.status.key === "now" && <circle className="topic-risk-ring" cx={item.x} cy={item.y} r={item.radius + 6} />}
        <circle cx={item.x} cy={item.y} r={item.radius} fill={item.status.color} />
        <line className="topic-label-leader" x1={lineStartX} x2={label.x} y1={item.y} y2={label.y} />
        <text className={`topic-point-label outside ${label.side > 0 ? "right" : "left"}`} x={label.x + label.side * 4} y={label.y + 4}>{item.topic}</text>
      </g>;
    })}
    <text className="topic-axis-title y" transform="translate(18 246) rotate(-90)">부담 표현 비율</text>
    <text className="topic-axis-end y-top" x="53" y={plot.top + 4}>많음</text><text className="topic-axis-end y-bottom" x="53" y={plot.bottom}>적음</text>
    <text className="topic-axis-end x-left" x={plot.left} y="470">짧은 통화</text><text className="topic-axis-end x-right" x={plot.right} y="470">긴 통화</text>
    <text className="topic-axis-title" x={(plot.left + plot.right) / 2} y="490">주제가 나온 통화의 평균 시간</text>
  </svg>;
  return <section className="dashboard-card emotion-topic-analysis">
    <header><div><span>03</span><h2>정서 유발 주제</h2></div></header>
    <TopicFindings tendency={tendency} topics={points} risks={risks} />
    {topics.length ? <>
      <div className="topic-scatter-wrap report-chart-preview" role="button" tabIndex="0" aria-haspopup="dialog" aria-label="정서 유발 주제 그래프 크게 보기" onClick={() => setGraphOpen(true)} onKeyDown={(event) => ["Enter", " "].includes(event.key) && setGraphOpen(true)}>
        {renderScatter()}
      </div>
      <div className="topic-legend">
        {Object.values(TOPIC_STATUS).map((status) => <span key={status.key}><i style={{ background: status.color }} /><b>{status.label}</b>{status.hint && <small>— {status.hint}</small>}</span>)}
      </div>
      {graphOpen && <ReportDetailModal eyebrow="정서 유발 주제" title="주제별 통화 흐름 자세히 보기" className="topic-scatter-modal" onClose={() => setGraphOpen(false)}>
        <div className="report-modal-chart topic-modal-chart">{renderScatter(true)}</div>
        <div className="topic-legend modal-legend">{Object.values(TOPIC_STATUS).map((status) => <span key={status.key}><i style={{ background: status.color }} /><b>{status.label}</b>{status.hint && <small>— {status.hint}</small>}</span>)}</div>
      </ReportDetailModal>}
    </> : <p className="empty-state">주제를 비교할 통화 기록이 더 필요합니다.</p>}
  </section>;
}

export default function ReportTabs({
  elderId,
  elderName,
  patientProfile,
  summary = {
    risks: [], care_counts: {}, daily_reports: [], time_reports: [],
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
  const [expandedPrioritySignal, setExpandedPrioritySignal] = useState("");
  const [showPrioritySignals, setShowPrioritySignals] = useState(true);
  const [showDecreases, setShowDecreases] = useState(false);
  const [showUnchanged, setShowUnchanged] = useState(false);
  const profileBaselineNotes = textList(patientProfile?.care_baseline);
  const profileMedicalCautions = textList(patientProfile?.medical_cautions);

  useEffect(() => {
    setExpandedPrioritySignal("");
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
    { label: "오늘 통화", value: summary.calls, unit: "통", average: dailyReports.reduce((sum, day) => sum + (day.calls || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.calls || 0) },
    { label: "통화 시간", value: Math.round(summary.total_seconds / 60), unit: "분", average: dailyReports.reduce((sum, day) => sum + (day.seconds || 0) / 60, 0) / baselineDays, trend: dailyReports.map((day) => Math.round((day.seconds || 0) / 60)) },
    { label: "대화 중 변화 신호", value: careTotal, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.observation_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.observation_count || 0), status: `발화 100개 중 ${Math.round(summary.normalized_rates?.observation_per_100_utterances || 0)}개` },
    { label: "반복 발화", value: summary.repeat_total, unit: "회", average: dailyReports.reduce((sum, day) => sum + (day.repeated_total || day.repeat_total || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.repeated_total || day.repeat_total || 0) },
    { label: "안전 신호", value: summary.risks.length, unit: "건", average: dailyReports.reduce((sum, day) => sum + (day.risk_count || 0), 0) / baselineDays, trend: dailyReports.map((day) => day.risk_count || 0), status: unread.length ? `미확인 ${unread.length}건` : "모두 확인" },
  ];
  const priorityTasks = useMemo(() => buildPriorityTasks(deviations, summary.risks), [deviations, summary.risks]);
  return <div className="report-dashboard">
    {!hideToolbar && <div className="report-toolbar">
      <nav className="cat-tabs">
        {CATEGORIES.map((category) => <button key={category.id} className={tab === category.id ? "on" : ""} onClick={() => setTab(category.id)}>{category.label}</button>)}
      </nav>
    </div>}

    {tab === "insight" && <>
      <div className="manager-focus-layout">
        <section className="dashboard-card manager-combined-overview">
          <CareDomainRadar todayItems={careItems} averageItems={averageCareItems} />
          <section className="manager-observation-summary">
            <header><div><h2>{elderName} 어르신의 오늘 관찰 요약</h2><p>통화에서 확인된 기억·언어·정서·생활 관련 신호이며, 진단 결과가 아닙니다.</p></div></header>
            <div className="manager-stat-grid manager-stat-strip">{kpis.map((item) => { const delta = item.value - item.average; return <article key={item.label}><span>{item.label}</span><strong>{item.value}<small>{item.unit}</small></strong><em>{item.status || `평균 대비 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}</em></article>; })}</div>
          </section>
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

    </>}


    {tab === "talk" && <>
      <div className="talk-analysis-triad">
        <ResponseRetentionChart data={activeBaseline.call_analytics?.response_retention} />
        <TimeRegressionJourney data={activeBaseline.call_analytics?.time_regression} />
        <EmotionTopicMap
          topics={activeBaseline.call_analytics?.emotion_topics || []}
          tendency={activeBaseline.call_analytics?.tendency_summary}
          risks={activeBaseline.risks || []}
        />
      </div>
    </>}


    {selectedDay && <DailyReportModal
      day={selectedDay}
      elderName={elderName}
      onClose={() => setSelectedDay(null)}
      onAck={ack}
      busy={busy}
    />}

  </div>;
}
