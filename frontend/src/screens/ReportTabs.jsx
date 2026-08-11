import { useMemo, useState } from "react";
import * as api from "../api.js";
import CareCalendar from "./CareCalendar.jsx";
import MedicationForm from "./MedicationForm.jsx";
import ScheduleForm from "./ScheduleForm.jsx";
import Transcript from "./Transcript.jsx";
import { BubbleChart, DistributionDonut, LineChart, MiniTrend, RhythmBars } from "../components/Charts.jsx";

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
};

const CARE_LABEL = {
  memory_orientation: "기억·지남력",
  emotion: "정서",
  daily_living: "생활 관련",
};

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

function duration(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}분 ${rest}초`;
}

function MetricCard({ label, value, unit, note, tone = "" }) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <div><b>{value}</b>{unit && <em>{unit}</em>}</div>
      {note && <small>{note}</small>}
    </article>
  );
}

function CallTable({ calls, openId, onOpen }) {
  if (!calls.length) return <p className="empty-state">아직 통화 기록이 없습니다.</p>;
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <thead><tr>
          <th>통화 일시</th><th>통화한 가족</th><th>리포트 주제</th><th>통화 시간</th><th>관찰 영역</th><th>관찰된 내용</th><th>상세</th>
        </tr></thead>
        <tbody>
          {calls.map((call) => {
            const at = dateParts(call.started_at);
            return (
              <tr key={call.call_id} className={openId === call.call_id ? "selected" : ""} onClick={() => onOpen(call.call_id)}>
                <td><b>{at.date}</b><small>{at.time}</small></td>
                <td><b>{call.counterpart_name || "AI 가족"}</b><small>{call.counterpart_relation || "가족"}</small></td>
                <td><b>{call.report_title || "AI 인지·정서 케어 통화"}</b><small>{call.summary || "통화 내용을 확인해 주세요."}</small></td>
                <td>{duration(call.duration_sec)}</td>
                <td><div className="domain-tags">
                  {(call.care_domains || []).map((domain) => <span key={domain.key} className={`domain-tag ${domain.key}`}>{domain.label} {domain.count}</span>)}
                  {call.risk_count > 0 && <span className="domain-tag safety">안전 {call.risk_count}</span>}
                  {!call.care_domains?.length && !call.risk_count && <span className="tag neutral">관찰 없음</span>}
                </div></td>
                <td><div className="observed-tags">
                  {(call.observed_items || []).slice(0, 3).map((item, index) => <span key={`${item.domain}-${item.label}-${index}`} className={item.domain === "안전" ? "risk" : ""}>{item.label}</span>)}
                  {(call.observed_items || []).length > 3 && <small>외 {call.observed_items.length - 3}건</small>}
                  {!call.observed_items?.length && <span className="no-observation">분류된 관찰 없음</span>}
                </div></td>
                <td><button className="detail-button" onClick={(event) => { event.stopPropagation(); onOpen(call.call_id); }}>
                  {openId === call.call_id ? "닫기" : "상세 보기"}
                </button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CompactCallCards({ calls, openId, onOpen }) {
  if (!calls.length) return <p className="empty-state">아직 통화 기록이 없습니다.</p>;
  return <div className="compact-call-grid">{calls.map((call) => {
    const at = dateParts(call.started_at);
    return <button key={call.call_id} className={openId === call.call_id ? "compact-call selected" : "compact-call"} onClick={() => onOpen(call.call_id)}>
      <div><time>{at.date}</time><span>{at.time}</span></div>
      <h3>{call.report_title || "AI 케어 통화"}</h3>
      <p>{call.counterpart_name || "AI 가족"} · {duration(call.duration_sec)}</p>
      <div className="compact-call-tags">
        {(call.care_domains || []).slice(0, 2).map((domain) => <span key={domain.key}>{domain.label} {domain.count}</span>)}
        {call.risk_count > 0 && <span className="risk">안전 {call.risk_count}</span>}
        {!call.care_domains?.length && !call.risk_count && <span>관찰 없음</span>}
      </div>
    </button>;
  })}</div>;
}

function callBubbleItems(report) {
  const grouped = new Map();
  const add = (key, label, value, color, kind, detail = "") => {
    const current = grouped.get(key);
    if (current) current.value += value;
    else grouped.set(key, { label, value, color, kind, detail });
  };

  Object.entries(CARE_LABEL).forEach(([domain, domainLabel]) => {
    const color = domain === "memory_orientation" ? "#7f8cff" : domain === "emotion" ? "#b49bec" : "#51c4a0";
    (report.care_summary?.[domain] || []).forEach((item) =>
      add(`state:${domain}:${item.label}`, item.label, 1, color, "상태", `${domainLabel} · ${item.evidence || "직접 발화 근거"}`),
    );
  });
  (report.repeated_questions || []).forEach((item) =>
    add(`speech:${item.question}`, `“${item.question}”`, item.count || 1, "#f3b45a", "많이 한 말", item.question),
  );
  (report.family_mentions || []).filter((item) => item.count >= 2).forEach((item) =>
    add(`family:${item.name}`, `${item.name} 언급`, item.count, "#55b7dc", "가족", item.examples?.[0] || ""),
  );
  (report.risk_summary || []).forEach((item) =>
    add(`risk:${item.type}`, `${RISK_LABEL[item.type] || item.type} 위험`, 1, "#ff777d", "안전", item.evidence || ""),
  );
  return [...grouped.values()].sort((a, b) => b.value - a.value).slice(0, 9);
}

function dailyBubbleItems(day) {
  const colors = {
    memory_orientation: "#7f8cff", emotion: "#b49bec", daily_living: "#51c4a0",
  };
  const observations = (day.observations || []).map((item) => ({
    label: item.label, value: item.count, color: colors[item.domain] || "#7f8cff",
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

function dailySnapshot(report, timeReports) {
  const active = (timeReports || []).filter((row) => row.calls > 0);
  const peak = active.slice().sort((a, b) => b.calls - a.calls || a.start_hour - b.start_hour)[0];
  const top = report.observations?.[0];
  const repeat = report.repeated_phrases?.[0];
  const risk = report.risks?.[0];

  if (!report.calls) return {
    title: "선택한 날에는 통화 기록이 없습니다",
    description: "분석할 실제 발화가 없어 상태나 감정을 추정하지 않았습니다.",
    peak: "통화 없음",
    observation: "관찰 근거 없음",
    action: "별도 확인 항목 없음",
  };
  return {
    title: peak ? `${peak.time_label}에 통화가 가장 많이 모였습니다` : "통화 기록을 확인했습니다",
    description: top
      ? `가장 많이 확인된 관찰은 ‘${top.label}’ ${top.count}회입니다.`
      : "통화는 있었지만 분류 기준에 해당하는 직접 발화는 없었습니다.",
    peak: peak ? `${peak.calls}회 · ${Math.round(peak.seconds / 60)}분` : `${report.calls}회`,
    observation: top ? `${top.label} ${top.count}회` : (repeat ? `반복 발화 ${repeat.count}회` : "특이 관찰 없음"),
    action: risk
      ? `${RISK_LABEL[risk.type] || risk.type} 여부를 우선 확인하세요.`
      : report.guardian_actions?.[0] || "현재 추가로 확인할 안전 항목은 없습니다.",
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

      {day.heart_report && <section className="heart-report daily-heart-report">
        <header><div><p className="eyebrow">마음 리포트</p><h2>보호자가 놓쳤을 수 있는 이날의 한마디</h2></div></header>
        <article className="daily-heart-quote">
          <span>{day.heart_report.label}</span>
          <blockquote>“{day.heart_report.quote}”</blockquote>
          <p>{day.heart_report.message}</p><small>{day.heart_report.policy}</small>
        </article>
      </section>}

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

function riskTrend(risks, type, days) {
  const totals = new Map();
  risks.filter((risk) => risk.type === type).forEach((risk) => {
    const key = (risk.at || "").slice(0, 10);
    totals.set(key, (totals.get(key) || 0) + 1);
  });
  return [...Array(days)].map((_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (days - index - 1));
    const key = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
    return totals.get(key) || 0;
  });
}

function ReportDetail({ report, loading, elderName, onClose }) {
  const [showRaw, setShowRaw] = useState(false);
  if (loading) return <section className="report-detail"><p className="hint">상세 리포트를 불러오는 중…</p></section>;
  if (!report) return null;
  const meta = report.call_meta || {};
  const observations = Object.entries(CARE_LABEL).flatMap(([key, domain]) =>
    (report.care_summary?.[key] || []).map((item) => ({ ...item, domain })),
  );
  const bubbleItems = callBubbleItems(report);
  return (
    <section className="report-detail" id="care-report-detail">
      <header className="detail-head">
        <div>
          <p className="eyebrow">{dateParts(meta.started_at).full}</p>
          <h2>{meta.report_title || "AI 인지·정서 케어 통화"}</h2>
          <span>{meta.counterpart_name || "AI 가족"} · {meta.counterpart_relation || "가족"} · {duration(meta.duration_sec)}</span>
        </div>
        <button onClick={onClose} aria-label="상세 리포트 닫기">×</button>
      </header>

      <p className="detail-summary">{report.summary}</p>

      {report.heart_report?.memory_banner && <section className="memory-alert-banner">
        <img
          src={report.heart_report.memory_banner.image_url}
          alt={report.heart_report.memory_banner.alt_text || report.heart_report.memory_banner.memory_title}
        />
        <div>
          <span>확인된 가족 기억 · {report.heart_report.memory_banner.title}</span>
          <h3>{elderName}님께서 이날 <b>{report.heart_report.memory_banner.memory_title}</b> 이야기를 다시 꺼내셨습니다.</h3>
          <blockquote>“{report.heart_report.memory_banner.quote}”</blockquote>
          <p>{report.heart_report.memory_banner.message}</p>
        </div>
      </section>}

      <div className="detail-visual">
        <div className="visual-copy">
          <p className="eyebrow">이번 통화 관찰 지도</p>
          <h3>많이 하신 말씀과 관찰된 상태를 보여줍니다</h3>
          <p>원이 클수록 같은 말이나 상태가 더 많이 확인됐고, 횟수가 많을수록 색도 진하게 표시됩니다.</p>
          <div className="visual-pills">
            <span><b>{observations.length}</b>관찰 근거</span>
            <span><b>{report.meaningful_moments?.length || 0}</b>마음 기록</span>
            <span className={report.risk_summary?.length ? "risk" : ""}><b>{report.risk_summary?.length || 0}</b>안전 신호</span>
          </div>
        </div>
        <BubbleChart items={bubbleItems} title="이번 통화 관찰 지도" />
      </div>

      <section className="evidence-flow" aria-label="관찰 근거와 보호자 확인 사항">
        <article>
          <span className="flow-number">1</span>
          <div><p>무엇을 관찰했는지</p><h3>인지·정서·생활 관찰</h3></div>
          <ul>{observations.slice(0, 4).map((item, index) => <li key={index}><b>{item.domain}</b>{item.label}</li>)}</ul>
          {observations.length > 4 && <small>외 {observations.length - 4}건</small>}
        </article>
        <article>
          <span className="flow-number">2</span>
          <div><p>어떤 발화가 근거인지</p><h3>어르신의 실제 말씀</h3></div>
          <ul className="flow-quotes">{observations.slice(0, 3).map((item, index) => <li key={index}><q>{item.evidence}</q></li>)}</ul>
          {!observations.length && <small>표시할 직접 발화 근거가 없습니다.</small>}
        </article>
        <article>
          <span className="flow-number">3</span>
          <div><p>보호자가 무엇을 확인해야 하는지</p><h3>직접 확인할 일</h3></div>
          {report.guardian_actions?.length ? <ul>{report.guardian_actions.map((action, index) => <li key={index}>{action}</li>)}</ul> : <small>추가로 확인할 항목이 없습니다.</small>}
        </article>
      </section>

      {report.heart_report && <section className={`heart-report ${report.heart_report.priority === "safety" ? "safety-first" : ""}`}>
        <header>
          <div><p className="eyebrow">마음 리포트</p><h2>오늘의 말씀을 가족의 관점으로 전합니다</h2></div>
          {report.heart_report.priority === "safety" && <span className="safety-first-badge">안전 확인 우선</span>}
        </header>
        <article className="heart-translation">
          <span className="heart-index">01</span>
          <div><p className="heart-kicker">행동과 상태 뒤에 남은 마음</p>
            <p className="state-translation">{report.heart_report.day_translation?.state}</p>
            <p className="family-translation">{report.heart_report.day_translation?.family}</p>
          </div>
        </article>
        <div className="heart-report-grid">
          <article className="missed-word-card">
            <span className="heart-index">02</span>
            <div><p className="heart-kicker">보호자가 놓친 한마디</p>
              {report.heart_report.missed_word ? <>
                <time>{dateParts(report.heart_report.missed_word.at).time}</time>
                <blockquote>“{report.heart_report.missed_word.quote}”</blockquote>
                <b>{report.heart_report.missed_word.label}</b>
                <small>{report.heart_report.missed_word.note}</small>
              </> : <p className="heart-empty">이번 통화에서는 가족에게 전할 직접적인 감정 표현이 확인되지 않았습니다.</p>}
            </div>
          </article>
          <article className="memory-bridge-card">
            <span className="heart-index">03</span>
            <div><p className="heart-kicker">다시 이어볼 수 있는 기억</p>
              {report.heart_report.memory_bridge ? <>
                <span className={`bridge-status ${report.heart_report.memory_bridge.mode}`}>
                  {report.heart_report.memory_bridge.mode === "verified" ? "확인된 가족 기억과 연결" : "가족 확인 후 연결"}
                </span>
                {report.heart_report.visual_story && !report.heart_report.memory_banner && <figure className="heart-artwork">
                  <div className="heart-artwork-frame">
                    <img
                      src={report.heart_report.visual_story.image_url}
                      alt={report.heart_report.visual_story.alt_text}
                      loading="lazy"
                    />
                    <span className={`artwork-status ${report.heart_report.visual_story.status}`}>
                      {report.heart_report.visual_story.status_label}
                    </span>
                  </div>
                  <figcaption>
                    <q>{report.heart_report.visual_story.source_quote}</q>
                    <small>{report.heart_report.visual_story.caption}</small>
                  </figcaption>
                </figure>}
                <h3>{report.heart_report.memory_bridge.title}</h3>
                {report.heart_report.memory_bridge.quote && <blockquote>“{report.heart_report.memory_bridge.quote}”</blockquote>}
                <p>{report.heart_report.memory_bridge.description}</p>
                <b>{report.heart_report.memory_bridge.suggestion}</b>
              </> : <p className="heart-empty">이번 통화에서 바로 연결할 가족 기억은 발견되지 않았습니다.</p>}
            </div>
          </article>
        </div>
        <p className="heart-policy">실제 발화를 근거로 사용합니다. 확인 전 그림은 기억에서 영감을 받은 상상 이미지이며 실제 장면으로 단정하지 않습니다.</p>
      </section>}

      <div className="detail-grid">
        <div className="detail-column">
          <section className="detail-card">
            <h3>통화에서 관찰된 내용</h3>
            <div className="observation-list">
              {Object.entries(CARE_LABEL).flatMap(([key, label]) =>
                (report.care_summary?.[key] || []).map((item, index) => (
                  <div className="observation" key={`${key}-${index}`}>
                    <span>{label}</span><b>{item.label}</b><q>{item.evidence}</q>
                  </div>
                )),
              )}
              {!Object.keys(CARE_LABEL).some((key) => report.care_summary?.[key]?.length) &&
                <p className="hint">분류된 관찰 항목이 없습니다.</p>}
            </div>
          </section>

          {report.risk_summary?.length > 0 && <section className="detail-card risk-card">
            <h3>즉시 확인이 필요한 안전 신호</h3>
            {report.risk_summary.map((risk, index) => <div className="observation" key={index}>
              <span>{RISK_LABEL[risk.type] || risk.type}</span><q>{risk.evidence}</q>
            </div>)}
          </section>}
        </div>

        <div className="detail-column">
          {report.family_mentions?.some((item) => item.count >= 2) && <section className="detail-card">
            <h3>대화에 반복해서 나온 가족</h3>
            {report.family_mentions.filter((item) => item.count >= 2).map((item) => <div className="family-mention" key={item.name}>
              <b>{item.name}</b><span>{item.count}회 언급</span>{item.examples?.[0] && <q>{item.examples[0]}</q>}
            </div>)}
          </section>}

          {report.guardian_actions?.length > 0 && <section className="detail-card action-card">
            <h3>보호자가 확인할 일</h3>
            <ul>{report.guardian_actions.map((action, index) => <li key={index}>{action}</li>)}</ul>
          </section>}
        </div>
      </div>

      <button className="raw-toggle" onClick={() => setShowRaw((value) => !value)}>
        {showRaw ? "전체 대화 접기" : "근거가 된 전체 대화 보기"}
      </button>
      {showRaw && <Transcript callId={report.call_id} elderName={elderName} personaName={meta.counterpart_name || "AI 가족"} />}
    </section>
  );
}

export default function ReportTabs({ elderId, elderName, summary, days, period, onPeriod, onReload }) {
  const [tab, setTab] = useState("insight");
  const [busy, setBusy] = useState(false);
  const [showSafetyDetails, setShowSafetyDetails] = useState(false);
  const [showAllDays, setShowAllDays] = useState(false);
  const [selectedDay, setSelectedDay] = useState(null);
  const [planVersion, setPlanVersion] = useState(0);

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
  const careItems = useMemo(() => [
    { label: "기억·지남력", value: summary.care_counts?.memory_orientation || 0 },
    { label: "정서", value: summary.care_counts?.emotion || 0 },
    { label: "생활 관련", value: summary.care_counts?.daily_living || 0 },
  ], [summary.care_counts]);
  const distributionItems = useMemo(() => [
    { label: "기억·지남력", value: summary.care_counts?.memory_orientation || 0, color: "#7f8cff" },
    { label: "정서", value: summary.care_counts?.emotion || 0, color: "#b49bec" },
    { label: "생활 관련", value: summary.care_counts?.daily_living || 0, color: "#51c4a0" },
    { label: "반복", value: summary.repeat_total || 0, color: "#f3b45a" },
    { label: "안전", value: summary.risks.length, color: "#ff8b80" },
  ], [summary.care_counts, summary.repeat_total, summary.risks.length]);
  const careTotal = careItems.reduce((sum, item) => sum + item.value, 0);
  const safetyColors = ["#55c4cf", "#f1ba58", "#f06f7c", "#9b8dea", "#63bd8e", "#e08d62"];
  const riskTypes = Object.entries(summary.risks.reduce((groups, risk) => {
    groups[risk.type] = (groups[risk.type] || 0) + 1;
    return groups;
  }, {})).sort((a, b) => b[1] - a[1]).map(([type, value], index) => ({
    type, value, label: RISK_LABEL[type] || type, color: safetyColors[index % safetyColors.length],
  }));
  const acknowledged = summary.risks.length - unread.length;
  const acknowledgementRate = summary.risks.length ? Math.round(acknowledged / summary.risks.length * 100) : 100;
  const mostFrequentRisk = riskTypes[0];
  const rhythm = summary.rhythm || {};
  const peakWindow = rhythm.peak_window || {};
  const dailyReports = (summary.daily_reports || []).filter((day) => day.calls > 0).slice().reverse();
  const detailRows = period.mode === "day"
    ? (summary.time_reports || [])
    : dailyReports;
  const visibleDetailRows = period.mode === "day"
    ? detailRows
    : (showAllDays ? dailyReports : dailyReports.slice(0, 7));
  const periodReport = useMemo(() => mergeAnalysisRows(
    summary.daily_reports || [],
    `${summary.since} ~ ${summary.until} 전체 분석`,
  ), [summary.daily_reports, summary.since, summary.until]);
  const daySnapshot = useMemo(() => dailySnapshot(
    periodReport, summary.time_reports || [],
  ), [periodReport, summary.time_reports]);
  const todayKey = new Date().toLocaleDateString("sv-SE");
  const currentMonth = todayKey.slice(0, 7);

  return <div className="report-dashboard">
    <div className="report-toolbar">
      <nav className="cat-tabs">
        {CATEGORIES.map((category) => <button key={category.id} className={tab === category.id ? "on" : ""} onClick={() => setTab(category.id)}>{category.label}</button>)}
      </nav>
      <div className="period-picker" aria-label="리포트 기간 선택">
        <div className="range">
          <button className={period.mode === "day" ? "on" : ""} onClick={() => onPeriod({ mode: "day", value: todayKey })}>일별</button>
          <button className={period.mode === "month" ? "on" : ""} onClick={() => onPeriod({ mode: "month", value: currentMonth })}>월별</button>
        </div>
        <input
          type={period.mode === "day" ? "date" : "month"}
          value={period.value}
          max={period.mode === "day" ? todayKey : currentMonth}
          onChange={(event) => event.target.value && onPeriod({ ...period, value: event.target.value })}
          aria-label={period.mode === "day" ? "조회할 날짜" : "조회할 월"}
        />
      </div>
    </div>

    {tab === "insight" && <>
      <div className="metric-grid">
        <MetricCard label="AI 케어 통화" value={summary.calls} unit="회" note={`${Math.round(summary.total_seconds / 60)}분 동안 연결`} />
        <MetricCard label="발화 기반 관찰" value={careTotal} unit="건" note="인지·정서·생활 관련 항목" />
        <MetricCard label="가족에게 전할 순간" value={summary.meaningful_total || 0} unit="건" note="마음 기록 후보" tone="heart" />
        <MetricCard label="안전 확인" value={summary.risks.length} unit="건" note={unread.length ? `${unread.length}건 미확인` : "모두 확인됨"} tone={unread.length ? "danger" : ""} />
      </div>

      <section className="dashboard-card rhythm-card">
        <header className="rhythm-head">
          <div>
            <p className="eyebrow">생활 리듬</p>
            <h2>연락이 모이는 시간과 함께 나온 말을 살펴봅니다</h2>
            <p>통화 시작 시각과 실제 발화에서 확인된 관찰 신호를 함께 분석합니다.</p>
          </div>
          <span className={`rhythm-ready ${rhythm.ready ? "ready" : ""}`}>
            {rhythm.ready ? `${rhythm.days_observed}일 · ${rhythm.calls_analyzed}통 분석` : `분석 준비 중 · ${rhythm.days_observed || 0}/${rhythm.minimum_days || 7}일`}
          </span>
        </header>

        {rhythm.ready ? <>
          <div className="rhythm-main-grid">
            <article className="rhythm-focus">
              <span>연락이 가장 많이 모인 시간</span>
              <h3>{peakWindow.label}</h3>
              <p>{peakWindow.summary}</p>
              <div className="rhythm-signal-tags">
                {(peakWindow.top_signals || []).map((item) => <span key={item.signal}>{item.label} <b>{item.count}회</b></span>)}
              </div>
              <strong>{peakWindow.guardian_action}</strong>
            </article>
            <RhythmBars blocks={rhythm.time_blocks || []} peakStart={peakWindow.start_hour} />
          </div>

          <div className="rhythm-detail-grid">
            <section className="rhythm-patterns">
              <header><h3>시간대별로 반복된 특징</h3><span>관찰 근거 기준</span></header>
              <div>{(rhythm.patterns || []).slice(0, 3).map((pattern) => <article key={pattern.signal}>
                <time>{pattern.time_label}</time>
                <div><b>{pattern.label}</b><p>{pattern.description}</p></div>
                <strong>{pattern.count}회</strong>
              </article>)}</div>
              {!rhythm.patterns?.length && <p className="empty-state">아직 시간대별로 반복된 특징이 없습니다.</p>}
            </section>
            <section className="rhythm-comparison">
              <header><h3>지난주와 달라진 점</h3><span>최근 7일 ↔ 이전 7일</span></header>
              <div>{(rhythm.week_comparison || []).map((change) => <article key={change.key} className={change.direction}>
                <span>{change.key}</span>
                <b>{change.current}</b>
                <small>{change.description}</small>
              </article>)}</div>
            </section>
          </div>
          <p className="rhythm-policy">통화가 많다는 사실만으로 감정을 단정하지 않습니다. 외로움과 불안은 실제 관련 표현이 함께 확인된 경우에만 표시합니다.</p>
        </> : <div className="rhythm-waiting">
          <b>생활 리듬을 찾는 중입니다</b>
          <p>최소 {rhythm.minimum_days || 7}일의 통화가 쌓이면 집중 시간과 주간 변화를 보여드립니다.</p>
        </div>}
      </section>

      <div className="dashboard-grid">
        <section className="dashboard-card activity-card">
          <header><div><h2>{period.mode === "day" ? "시간대별 통화" : "통화 변화"}</h2><p>{period.mode === "day" ? "선택한 날의 2시간 단위 통화 횟수" : "날짜별 AI 케어 통화 횟수"}</p></div><b>{summary.calls}회</b></header>
          {period.mode === "day"
            ? <RhythmBars blocks={rhythm.time_blocks || []} peakStart={peakWindow.start_hour} />
            : <LineChart byDay={summary.by_day} days={days} label="통화" />}
        </section>
        <section className="dashboard-card care-card">
          <header><div><h2>관찰 구성</h2><p>통화 속 직접 발화 근거 기준</p></div></header>
          <DistributionDonut items={distributionItems} label={`최근 ${days}일 관찰 구성`} />
        </section>
      </div>

      <section className="priority-strip">
        <b>보호자가 확인할 일</b>
        <div>{summary.guardian_actions?.length ? summary.guardian_actions.slice(0, 3).map((action, index) => <span key={index}>✓ {action}</span>) : <span>현재 추가 확인 항목이 없습니다.</span>}</div>
      </section>

    </>}

    {tab === "talk" && <>
      <section className="dashboard-card daily-report-overview">
        <header>
          <div><p className="eyebrow">선택 기간 통화 분석</p><h2>{period.mode === "day" ? dateParts(summary.since).date : `${period.value.replace("-", "년 ")}월`} 리포트</h2><p>통화별 기록을 날짜별로 합쳐 변화와 근거를 한 화면에 정리했습니다.</p></div>
          <span className="count-badge">{summary.since} ~ {summary.until}</span>
        </header>
        <div className="daily-overview-grid">
          <article><span>전체 통화</span><b>{summary.calls}<em>회</em></b><small>{Math.round(summary.total_seconds / 60)}분 동안 연결</small></article>
          <article><span>발화 기반 관찰</span><b>{careTotal}<em>건</em></b><small>인지·정서·생활 영역</small></article>
          <article><span>반복 발화</span><b>{summary.repeat_total}<em>회</em></b><small>하루 안의 동일·유사 질문</small></article>
          <article className={summary.risks.length ? "risk" : ""}><span>안전 확인</span><b>{summary.risks.length}<em>건</em></b><small>{unread.length ? `${unread.length}건 미확인` : "모두 확인됨"}</small></article>
        </div>
        {period.mode === "day" && <section className="day-analysis-summary" aria-label="선택한 날의 핵심 분석">
          <header><div><span>오늘의 핵심</span><h3>{daySnapshot.title}</h3></div><p>{daySnapshot.description}</p></header>
          <div>
            <article><small>가장 집중된 시간</small><b>{daySnapshot.peak}</b></article>
            <article><small>발화에서 확인된 특징</small><b>{daySnapshot.observation}</b></article>
            <article><small>보호자가 확인할 일</small><b>{daySnapshot.action}</b></article>
          </div>
        </section>}
        <div className="analysis-flow" aria-label="통화 분석 과정">
          {["통화 기록", "발화 분류", "근거 검증", "보호자 행동"].map((label, index) => <div key={label}>
            <span>{index + 1}</span><b>{label}</b>{index < 3 && <i />}
          </div>)}
        </div>
      </section>

      <section className="analysis-widget-grid" aria-label="선택 기간 전체 분석">
        <button className="analysis-widget distribution" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>관찰 구성</span><h3>어떤 영역이 많이 나타났는지</h3></div><i>전체 분석 ↗</i></header>
          <DistributionDonut items={distributionItems} label="선택 기간 관찰 구성" />
        </button>
        <button className="analysis-widget ranks" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>주요 관찰</span><h3>많이 확인된 상태</h3></div><i>상세 ↗</i></header>
          <div>{periodReport.observations.slice(0, 5).map((item) => <div className="analysis-rank-row" key={`${item.domain}-${item.signal}`}>
            <span>{item.label}</span><div><i style={{ width: `${item.count / Math.max(1, periodReport.observations[0]?.count || 1) * 100}%` }} /></div><b>{item.count}</b>
          </div>)}</div>
          {!periodReport.observations.length && <p>직접 발화로 확인된 관찰이 없습니다.</p>}
        </button>
        <button className="analysis-widget ranks repeat" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>반복 발화</span><h3>기간 안에 되풀이된 질문</h3></div><i>근거 ↗</i></header>
          <div>{periodReport.repeated_phrases.slice(0, 5).map((item) => <div className="analysis-rank-row" key={item.question}>
            <span>{item.question}</span><div><i style={{ width: `${item.count / Math.max(1, periodReport.repeated_phrases[0]?.count || 1) * 100}%` }} /></div><b>{item.count}</b>
          </div>)}</div>
          {!periodReport.repeated_phrases.length && <p>확인된 반복 발화가 없습니다.</p>}
        </button>
        <button className="analysis-widget heart" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>마음 리포트</span><h3>가족에게 전할 한마디</h3></div><i>열기 ↗</i></header>
          {periodReport.heart_report ? <><blockquote>“{periodReport.heart_report.quote}”</blockquote><b>{periodReport.heart_report.label}</b><p>{periodReport.heart_report.message}</p></> : <p>이 기간에는 직접 확인된 마음 표현이 없습니다.</p>}
        </button>
        <button className="analysis-widget safety" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>안전 구성</span><h3>확인이 필요한 신호</h3></div><i>상세 ↗</i></header>
          <DistributionDonut items={riskTypes} label="선택 기간 안전 신호 구성" />
        </button>
        <button className="analysis-widget actions" onClick={() => setSelectedDay(periodReport)}>
          <header><div><span>보호자 행동</span><h3>지금 확인하면 좋은 일</h3></div><i>전체 ↗</i></header>
          <ul>{periodReport.guardian_actions.slice(0, 4).map((action, index) => <li key={index}><span>✓</span>{action}</li>)}</ul>
          {!periodReport.guardian_actions.length && <p>추가 확인 항목이 없습니다.</p>}
        </button>
      </section>

      <section className="dashboard-card daily-report-list">
        <header><div><h2>{period.mode === "day" ? "시간대별 통화 리포트" : "날짜별 통화 리포트"}</h2><p>{period.mode === "day" ? "선택한 날을 2시간 단위로 나눠 관찰했습니다." : "월간 통화를 날짜별로 나눠 관찰했습니다."}</p></div>
          {period.mode === "month" && dailyReports.length > 7 && <button onClick={() => setShowAllDays((value) => !value)}>{showAllDays ? "간단히 보기" : `전체 보기 · ${dailyReports.length}일`}</button>}
        </header>
        <div className="daily-report-rows">
          {visibleDetailRows.map((row) => {
            const top = row.observations?.[0];
            const maxCalls = Math.max(1, ...detailRows.map((item) => item.calls));
            const rowLabel = period.mode === "day" ? row.time_label : dateParts(row.date).date;
            const popupRow = period.mode === "day" ? {
              ...row,
              range_label: `${dateParts(row.date).date} ${row.time_label}`,
              analysis_title: "해당 시간대 통화를 하나로 정리했습니다",
            } : row;
            return <article key={row.key || row.date} className={row.calls ? "" : "no-calls"}>
              <div className="daily-date"><time>{rowLabel}</time><small>{Math.round(row.seconds / 60)}분 통화</small></div>
              <div className="daily-volume"><div><i style={{ width: `${row.calls / maxCalls * 100}%` }} /></div><b>{row.calls}회</b></div>
              <div className="daily-main-observation"><span>{row.calls ? (top ? top.domain_label : "관찰") : "기록"}</span><b>{row.calls ? (top ? `${top.label} ${top.count}회` : "특이 관찰 없음") : "이 시간에는 통화가 없었습니다"}</b><small>{row.calls ? (top?.evidence?.[0] || "통화는 있었지만 분류 기준에 해당하는 발화는 없었습니다.") : "발화가 없어 상태나 감정을 추정하지 않았습니다."}</small></div>
              <div className="daily-row-counts"><span>관찰 <b>{row.observation_count}</b></span><span>반복 <b>{row.repeated_total}</b></span><span className={row.risk_count ? "risk" : ""}>안전 <b>{row.risk_count}</b></span></div>
              {row.calls ? <button onClick={() => setSelectedDay(popupRow)}>통화 관찰 지도</button> : <span className="no-call-detail">분석 없음</span>}
            </article>;
          })}
          {!visibleDetailRows.length && <p className="empty-state">선택한 기간에 통화 기록이 없습니다.</p>}
        </div>
      </section>

      <section className="dashboard-card safety-overview">
        <header><div><h2>통화에서 확인된 안전 상태</h2><p>최근 {days}일 동안 실제 발화에서 확인된 안전 신호만 함께 보여드립니다.</p></div><span className={`count-badge ${unread.length ? "danger" : ""}`}>{unread.length ? `확인 필요 ${unread.length}건` : "확인할 기록 없음"}</span></header>
        <div className="safety-visual-grid">
          <div className="safety-trend-list">
            {riskTypes.slice(0, 3).map((item) => <article key={item.type} style={{ "--risk-color": item.color }}>
              <div><small>전체 안전 신호 중 {summary.risks.length ? Math.round(item.value / summary.risks.length * 100) : 0}%</small><b>{item.label} <em>{item.value}건</em></b></div>
              <MiniTrend values={riskTrend(summary.risks, item.type, days)} color={item.color} label={`${item.label} 날짜별 추이`} />
            </article>)}
            {!riskTypes.length && <div className="safety-clear"><span>✓</span><b>확인된 안전 신호가 없습니다</b><small>위험 발화가 감지되면 이곳에 추이가 나타납니다.</small></div>}
          </div>
          <section className="safety-distribution">
            <h3>안전 신호 구성</h3>
            <DistributionDonut items={riskTypes} label={`최근 ${days}일 안전 신호 구성`} />
          </section>
        </div>
        <div className="safety-status-grid">
          <article><span>S1</span><div><small>관찰된 위험 유형</small><b>{riskTypes.length}종</b></div></article>
          <article className="needs-check"><span>S2</span><div><small>가장 많이 감지</small><b>{mostFrequentRisk ? `${mostFrequentRisk.label} ${mostFrequentRisk.value}건` : "없음"}</b></div></article>
          <article className="complete"><span>S3</span><div><small>확인 진행률</small><b>{acknowledgementRate}%</b></div></article>
        </div>
        {summary.risks.length > 0 && <button className="safety-detail-toggle" onClick={() => setShowSafetyDetails((value) => !value)}>
          {showSafetyDetails ? "개별 기록 접기" : `개별 기록 보기 · ${summary.risks.length}건`}
        </button>}
      </section>
      {showSafetyDetails && summary.risks.length > 0 && <section className="dashboard-card safety-panel">
        <header><div><h2>개별 안전 기록</h2><p>근거 발화를 확인하고 필요한 항목만 처리하세요.</p></div></header>
        <div className="safety-list">{summary.risks.map((risk) => <article key={risk.event_id} className={risk.acknowledged ? "acknowledged" : ""}>
          <div><b>{RISK_LABEL[risk.type] || risk.type}</b><span>{dateParts(risk.at).full}</span>{risk.evidence && <q>{risk.evidence}</q>}</div>
          {risk.acknowledged ? <span className="tag ok">확인됨</span> : <button disabled={busy} onClick={() => ack(risk.event_id)}>확인함</button>}
        </article>)}</div>
      </section>}
    </>}

    {tab === "plan" && <div className="plan-dashboard report-plan-dashboard">
      <CareCalendar elderId={elderId} refreshKey={planVersion} />
      <div className="plan-editor-grid">
        <ScheduleForm elderId={elderId} onChanged={() => setPlanVersion((value) => value + 1)} />
        <MedicationForm elderId={elderId} onChanged={() => setPlanVersion((value) => value + 1)} />
      </div>
    </div>}

    {selectedDay && <DailyReportModal
      day={selectedDay}
      elderName={elderName}
      onClose={() => setSelectedDay(null)}
      onAck={ack}
      busy={busy}
    />}

  </div>;
}
