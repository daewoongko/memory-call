import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import CareCalendar from "./CareCalendar.jsx";
import MedicationToday from "./MedicationToday.jsx";

const STATUS_LABEL = { completed: "기록됨", waiting: "예정", missed: "확인 필요" };
const DOSE_STATUS = [
  { value: "USER_CONFIRMED", label: "복용 확인", tone: "confirmed" },
  { value: "UNCLEAR", label: "불확실", tone: "unclear" },
  { value: "REFUSED", label: "거부", tone: "refused" },
  { value: "DUPLICATE_SUSPECTED", label: "중복 의심", tone: "duplicate" },
];

function TaskGroup({ group, asOf, busy, onAcknowledge, onDoseStatus, onOpenMedication }) {
  const completed = group.rows.filter((row) => row.completed).length;
  return <details className={group.urgent ? "urgent" : ""} defaultOpen={group.urgent || completed < group.rows.length}>
    <summary><b>{group.label}</b><span>{completed}/{group.rows.length}</span></summary>
    {group.rows.map((item) => <TaskRow
      key={item.id}
      item={item}
      asOf={asOf}
      busy={busy === item.id}
      onAcknowledge={onAcknowledge}
      onDoseStatus={onDoseStatus}
      onOpenMedication={onOpenMedication}
    />)}
  </details>;
}

function TaskRow({ item, asOf, busy, onAcknowledge, onDoseStatus, onOpenMedication }) {
  if (item.kind === "dose") return <article className={`care-task-row dose ${item.status}`}>
    <div className={`task-kind-mark dose ${item.dose_status ? "recorded" : ""}`}>약</div>
    <div className="task-copy">
      <b>{item.elder_name} · {item.title}</b>
      <small>{[item.time, item.dosage_text, item.indication].filter(Boolean).join(" · ")}</small>
      {item.ai_observation_count > 0 && <span className="task-ai-observation">AI 관찰 {item.ai_observation_count}건{item.evidence ? ` · “${item.evidence}”` : ""}</span>}
      <div className="dose-status-actions" aria-label={`${item.elder_name} ${item.title} 복약 상태`}>
        {DOSE_STATUS.map((status) => <button
          key={status.value}
          type="button"
          className={`${status.tone} ${item.dose_status === status.value ? "on" : ""}`}
          disabled={busy}
          onClick={() => onDoseStatus(item, asOf, status.value)}
        >{status.label}</button>)}
      </div>
    </div>
    <span className={`task-status ${item.status}`}>{item.carryover ? "어제 미완료" : STATUS_LABEL[item.status]}</span>
  </article>;

  if (item.kind === "review") return <article className={`care-task-row review ${item.status}`}>
    <div className="task-kind-mark review">주기</div>
    <div className="task-copy">
      <b>{item.elder_name} · {item.title}</b>
      {item.monitoring_points?.length > 0 && <small>{item.monitoring_points.slice(0, 2).join(" · ")}</small>}
      {item.evidence && <blockquote>“{item.evidence}”</blockquote>}
    </div>
    <button className="task-open-medication" type="button" onClick={() => onOpenMedication(item)}>상세로 이동 ›</button>
  </article>;

  return <article className={`care-task-row risk ${item.status}`}>
    <button
      type="button"
      className="care-task-check"
      aria-label={`${item.elder_name} ${item.title} ${item.completed ? "확인 완료" : "확인 처리"}`}
      disabled={item.completed || busy}
      onClick={() => onAcknowledge(item)}
    >{item.completed ? "✓" : ""}</button>
    <div className="task-copy"><b>{item.elder_name} · {item.title}</b>{item.evidence && <blockquote>“{item.evidence}”</blockquote>}</div>
    <span className={`task-status ${item.status}`}>{item.carryover ? "어제 미완료" : STATUS_LABEL[item.status]}</span>
  </article>;
}

export default function CareTaskWorkspace({ elderId, summary, baselineSummary, period, onReload, onOpenHandover, onOpenMedication, onSubtabChange, initialSubtab = "checklist" }) {
  const [subtab, setSubtab] = useState(initialSubtab);
  const [planVersion, setPlanVersion] = useState(0);
  const [mode, setMode] = useState("time");
  const [tasks, setTasks] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const load = () => api.getCareTasks(period.value).then((result) => {
    setTasks(result);
    setError("");
    return result;
  }).catch((reason) => setError(reason.message));
  useEffect(() => { load(); }, [period.value]);
  useEffect(() => { setSubtab(initialSubtab); }, [initialSubtab]);
  useEffect(() => { onSubtabChange?.(subtab); }, [subtab, onSubtabChange]);

  const allRows = useMemo(() => tasks
    ? [...tasks.immediate, ...tasks.timed, ...tasks.all_day, ...(tasks.carryover || [])]
    : [], [tasks]);

  async function acknowledge(item) {
    setBusy(item.id);
    try {
      await api.acknowledgeRisk(item.event_id);
      await Promise.all([load(), onReload?.()]);
    } finally { setBusy(""); }
  }

  async function setDoseStatus(item, asOf, status) {
    setBusy(item.id);
    try {
      await api.setDoseTaskStatus(item.schedule_id, item.task_date || asOf, status);
      await Promise.all([load(), onReload?.()]);
    } finally { setBusy(""); }
  }

  const groups = useMemo(() => {
    if (!tasks) return [];
    if (mode === "elder") return (tasks.elders || []).map((elder) => ({
      label: elder.name,
      rows: allRows.filter((row) => row.elder_id === elder.elder_id)
        .sort((a, b) => Number(a.completed) - Number(b.completed) || String(a.time || "99:99").localeCompare(String(b.time || "99:99"))),
    })).filter((group) => group.rows.length);
    const byTime = new Map();
    tasks.timed.forEach((row) => {
      const label = `${row.time} 투약`;
      if (!byTime.has(label)) byTime.set(label, []);
      byTime.get(label).push(row);
    });
    return [
      ...(tasks.immediate.length ? [{ label: `즉시 확인 · ${tasks.immediate.filter((row) => !row.completed).length}건`, rows: tasks.immediate, urgent: true }] : []),
      ...[...byTime.entries()].map(([label, rows]) => ({ label, rows })),
      ...(tasks.all_day.length ? [{ label: `오늘 중 · 시각 무관`, rows: tasks.all_day }] : []),
      ...((tasks.carryover || []).length ? [{ label: `어제 미완료 · ${tasks.carryover.length}건`, rows: tasks.carryover, urgent: true }] : []),
    ];
  }, [tasks, mode, allRows]);

  const handoverCount = tasks?.carryover?.length || 0;
  function openMedication(item) {
    setSubtab("medication");
    onOpenMedication?.(item);
  }

  return <div className="care-task-workspace">
    <nav className="task-subtabs">
      <button className={subtab === "checklist" ? "on" : ""} onClick={() => setSubtab("checklist")}>오늘 할 일</button>
      <button className={subtab === "medication" ? "on" : ""} onClick={() => setSubtab("medication")}>복약</button>
      <button className={subtab === "schedule" ? "on" : ""} onClick={() => setSubtab("schedule")}>일정</button>
    </nav>
    {subtab === "checklist" ? <>
      {tasks?.latest_handover && <button className="handover-banner" type="button" onClick={onOpenHandover}><span>{({ day: "주간", evening: "저녁", night: "야간" })[tasks.latest_handover.shift]} 근무 인계 {handoverCount ? `${handoverCount}건` : ""}</span><b>{tasks.latest_handover.note || "메모 없음"}</b><em>보기 ›</em></button>}
      <header className="task-heading"><div className="task-heading-summary"><h2>할 일 <span>{tasks ? `${tasks.completed}/${tasks.total}` : "-/-"}</span></h2></div><div className="task-view-toggle"><button className={mode === "time" ? "on" : ""} onClick={() => setMode("time")}>시간순</button><button className={mode === "elder" ? "on" : ""} onClick={() => setMode("elder")}>환자별</button></div></header>
      {error && <p className="error">{error}</p>}
      <div className="care-task-groups">{groups.map((group) => <TaskGroup key={`${mode}-${group.label}`} group={group} asOf={period.value} busy={busy} onAcknowledge={acknowledge} onDoseStatus={setDoseStatus} onOpenMedication={openMedication} />)}</div>
      {!allRows.length && tasks && <p className="empty-state">선택한 날짜에 확인할 항목이 없습니다.</p>}
    </> : subtab === "medication"
      ? <MedicationToday elderId={elderId} onChanged={() => { setPlanVersion((value) => value + 1); onReload?.(); }} />
      : <CareCalendar elderId={elderId} refreshKey={planVersion} dailyReports={baselineSummary?.daily_reports || summary?.daily_reports || []} onChanged={() => setPlanVersion((value) => value + 1)} />}
  </div>;
}
