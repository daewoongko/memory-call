import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import ReportTabs from "./ReportTabs.jsx";

const MAIN_TABS = [
  { id: "analysis", label: "분석 리포트", icon: "분" },
  { id: "notes", label: "특이사항", icon: "특" },
];

function localDateKey(date = new Date()) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function jsonList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [value];
  } catch {
    return [value];
  }
}

function normalizePatientProfile(profile) {
  if (!profile) return null;
  return {
    ...profile,
    care_baseline: jsonList(profile.care_baseline),
    medical_cautions: jsonList(profile.medical_cautions),
  };
}

function selectedRange(period) {
  if (period.mode === "day") return { days: 1, start: period.value, end: period.value };
  const [year, month] = period.value.split("-").map(Number);
  const monthEnd = `${period.value}-${String(new Date(year, month, 0).getDate()).padStart(2, "0")}`;
  const today = localDateKey();
  const end = period.value === today.slice(0, 7) ? today : monthEnd;
  return { days: Math.max(1, Math.round((new Date(end) - new Date(`${period.value}-01`)) / 86400000) + 1), start: `${period.value}-01`, end };
}

function rollingRange(end, days = 30) {
  const endDate = new Date(`${end}T12:00:00`);
  const startDate = new Date(endDate);
  startDate.setDate(startDate.getDate() - days + 1);
  return { days, start: localDateKey(startDate), end };
}

function SpecialNotes({ summary, onReload }) {
  const [busy, setBusy] = useState(0);
  const rows = useMemo(() => (summary.daily_reports || []).slice().reverse(), [summary]);

  async function acknowledge(eventId) {
    setBusy(eventId);
    try { await api.acknowledgeRisk(eventId); await onReload(); } finally { setBusy(0); }
  }

  return <section className="special-notes">
    <header className="special-notes-head">
      <div><p className="eyebrow">담당자 확인함</p><h2>근거가 있는 특이사항만 모았습니다</h2><span>관찰 내용 → 실제 발화 → 담당자가 확인할 일을 한 줄에서 이어 봅니다.</span></div>
      <b>{rows.reduce((sum, row) => sum + (row.risk_count || 0), 0)}<small>안전 신호</small></b>
    </header>
    <div className="special-day-list">
      {rows.map((day) => {
        const observations = (day.observations || []).slice(0, 4);
        return <article className="special-day" key={day.date}>
          <header><time>{day.date}</time><span>통화 {day.calls}건 · 관찰 {day.observation_count}건</span>{day.risk_count > 0 && <strong>안전 {day.risk_count}건</strong>}</header>
          <div className="special-observation-grid">
            {observations.map((item) => <div className="special-observation" key={`${day.date}-${item.domain}-${item.signal}`}>
              <span className={`domain-dot ${item.domain}`} />
              <div><small>무엇을 관찰했는지</small><b>{item.label} {item.count}회</b></div>
              <blockquote><small>어떤 발화가 근거인지</small>“{item.evidence?.[0] || "직접 발화 근거 없음"}”</blockquote>
            </div>)}
          </div>
          {(day.risks || []).map((risk) => <div className="special-risk" key={risk.event_id}>
            <div><small>안전 특이사항</small><b>{risk.evidence}</b><span>{new Date(risk.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</span></div>
            <button disabled={risk.acknowledged || busy === risk.event_id} onClick={() => acknowledge(risk.event_id)}>{risk.acknowledged ? "확인 완료" : "상태 확인 완료"}</button>
          </div>)}
          <div className="special-action"><small>담당자가 무엇을 확인해야 하는지</small><p>{day.guardian_actions?.[0] || "추가로 직접 확인할 항목은 없습니다."}</p></div>
        </article>;
      })}
      {!rows.length && <p className="empty-state">선택한 기간에 분석할 통화가 없습니다.</p>}
    </div>
  </section>;
}

export default function CareManagerScreen() {
  const [elders, setElders] = useState(null);
  const [picked, setPicked] = useState(null);
  const [tab, setTab] = useState("analysis");
  const [period, setPeriod] = useState(() => ({ mode: "day", value: localDateKey() }));
  const [patientProfile, setPatientProfile] = useState(null);
  const [summary, setSummary] = useState(null);
  const [baselineSummary, setBaselineSummary] = useState(null);
  const [comparisonDay, setComparisonDay] = useState(null);
  const [error, setError] = useState("");
  const [baselineLoading, setBaselineLoading] = useState(false);

  useEffect(() => { api.getElders().then(({ elders: rows }) => { setElders(rows); if (rows.length === 1) setPicked(rows[0]); }).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    if (!picked) return;
    api.getPersona(undefined, picked.elder_id)
      .then((result) => setPatientProfile(normalizePatientProfile(result.elder)))
      .catch(() => setPatientProfile(null));
  }, [picked]);
  const loadSummary = useCallback(() => {
    if (!picked) return Promise.resolve();
    const range = selectedRange(period);
    const comparisonDate = period.mode === "day" ? period.value : range.end;
    const baselineRange = rollingRange(comparisonDate, 30);
    setError("");
    setSummary(null);
    setBaselineSummary(null);
    setComparisonDay(null);

    // 선택 기간을 먼저 보여주고, 비교 기준선은 뒤에서 한 번만 계산한다.
    // 일별 화면에서는 선택 요약 자체가 비교일이므로 같은 API를 중복 호출하지 않는다.
    return api.getPeriodSummary(range.days, picked.elder_id, range).then((selected) => {
      setSummary(selected);
      setComparisonDay(period.mode === "day" ? selected : null);
      setBaselineLoading(true);
      return api.getPeriodSummary(baselineRange.days, picked.elder_id, baselineRange)
        .then((baseline) => {
          setBaselineSummary(baseline);
          if (period.mode !== "day") {
            return api.getPeriodSummary(1, picked.elder_id, { start: comparisonDate, end: comparisonDate })
              .then(setComparisonDay);
          }
          return null;
        })
        .catch((e) => setError(`최근 30일 비교 기준은 잠시 뒤 다시 불러옵니다. (${e.message})`))
        .finally(() => setBaselineLoading(false));
    }).catch((e) => setError(`분석을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요. (${e.message})`));
  }, [period, picked]);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  if (!elders) return <main className="guardian"><p className={error ? "error" : "hint"}>{error || "어르신 정보를 불러오는 중…"}</p></main>;
  if (!picked) return <main className="guardian role-picker"><header className="g-head"><BrandMark size={34} /><b>요양원 담당자</b></header><h1 className="g-title">관리할 어르신을 선택하세요</h1><div className="elder-cards">{elders.map((elder) => <button className="elder-card" key={elder.elder_id} onClick={() => setPicked(elder)}><span className="elder-face">{elder.name?.slice(0, 1)}</span><span className="elder-info"><b>{elder.name}</b><small>{elder.diagnosis_label || elder.preferred_call_name}</small><em>{elder.residence_type || "생활 정보 미등록"}</em></span><span className="chev">›</span></button>)}</div></main>;

  const current = MAIN_TABS.find((item) => item.id === tab);
  return <main className="guardian guardian-dashboard care-manager-dashboard">
    <div className="guardian-shell">
      <aside className="guardian-sidebar">
        <div className="sidebar-brand"><BrandMark size={32} /><div><b>다소니</b><span>요양원 케어 분석</span></div></div>
        <button className="sidebar-elder" onClick={() => elders.length > 1 && setPicked(null)}><span className="elder-face sm">{picked.name?.slice(0, 1)}</span><span><b>{picked.name}</b><small>{picked.preferred_call_name}</small></span><i>⌄</i></button>
        <nav className="sidebar-nav" aria-label="담당자 메뉴">{MAIN_TABS.map((item) => <button key={item.id} className={tab === item.id ? "on" : ""} onClick={() => setTab(item.id)}><span>{item.icon}</span>{item.label}</button>)}</nav>
      </aside>
      <section className="guardian-workspace">
        <header className="dashboard-heading manager-heading"><div><p className="eyebrow">{picked.name} 어르신 · {patientProfile?.diagnosis_label || picked.diagnosis_label || "진단 정보 미등록"}</p><h1>{new Date(`${period.value}T00:00:00`).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} 분석 리포트</h1><span>{tab === "analysis" ? "발화 변화에서 오늘의 확인 우선순위를 정리합니다." : "담당자가 직접 확인해야 할 근거와 행동을 모았습니다."}</span></div><label className="manager-date-picker"><span>분석 날짜</span><input type="date" value={period.value} max={localDateKey()} onChange={(event) => event.target.value && setPeriod({ mode: "day", value: event.target.value })} /></label></header>
        {error && <p className="error">{error}</p>}
        {!summary ? <p className="hint">분석 데이터를 불러오는 중…</p> : tab === "analysis" ? <><ReportTabs elderId={picked.elder_id} elderName={picked.name} patientProfile={patientProfile} summary={summary} baselineSummary={baselineSummary || summary} comparisonDay={comparisonDay || summary} days={summary.days} period={period} onPeriod={setPeriod} onReload={loadSummary} />{baselineLoading && <p className="manager-baseline-loading">최근 30일 비교 기준을 이어서 계산하고 있습니다.</p>}</> : <SpecialNotes summary={summary} onReload={loadSummary} />}
      </section>
    </div>
  </main>;
}
