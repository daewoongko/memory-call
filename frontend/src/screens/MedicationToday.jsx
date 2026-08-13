import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

const DAY_CODE = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

function localDateKey(date = new Date()) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

const emptyMedication = () => ({
  medication_name: "",
  dosage_text: "1정",
  scheduled_time: "20:00",
  meal_relation: "after",
  repeat: "daily",
  indication: "",
  monitoring_text: "",
  review_interval_days: 14,
  escalation_criteria: "",
});

function doseStatus(item) {
  if (!item) return { label: "오늘 일정 없음", tone: "quiet" };
  if (item.confirmed) return { label: `${item.scheduled_time} 복용 확인`, tone: "done" };
  const labels = {
    UNCLEAR: "복용 여부 불확실",
    REFUSED: "복용 거부",
    DUPLICATE_SUSPECTED: "중복 복용 의심",
  };
  if (labels[item.last_status]) return { label: labels[item.last_status], tone: "attention" };
  return { label: `${item.scheduled_time} 예정`, tone: "waiting" };
}

export default function MedicationToday({ elderId = "elder_001", onChanged }) {
  const today = localDateKey();
  const [data, setData] = useState({ medications: [], reviews: [], review_status: [], signal_options: [], today: [] });
  const [selectedSignal, setSelectedSignal] = useState("");
  const [openCard, setOpenCard] = useState("");
  const [checks, setChecks] = useState({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showRegistration, setShowRegistration] = useState(false);
  const [draft, setDraft] = useState(emptyMedication);

  async function load() {
    const result = await api.getMedications(elderId, today);
    setData(result);
  }

  useEffect(() => {
    setOpenCard("");
    setSelectedSignal("");
    load().catch((reason) => setError(reason.message));
  }, [elderId]);

  useEffect(() => {
    if (!showRegistration) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setShowRegistration(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showRegistration]);

  const statusById = useMemo(() => Object.fromEntries((data.review_status || []).map((item) => [item.schedule_id, item])), [data.review_status]);
  const todayById = useMemo(() => Object.fromEntries((data.today || []).map((item) => [item.schedule_id, item])), [data.today]);
  const evidenceBySignal = useMemo(() => Object.fromEntries((data.signal_options || []).map((item) => [item.signal, item.evidence || []])), [data.signal_options]);
  const rows = useMemo(() => (data.medications || []).map((item) => {
    const review = statusById[item.schedule_id] || {};
    const links = (item.signal_links || []).map((link) => ({ ...link, evidence: evidenceBySignal[link.signal] || [] }));
    const latestReviews = (data.reviews || []).filter((row) => row.schedule_id === item.schedule_id).slice(0, 3);
    return { ...item, ...review, links, latestReviews, dose: todayById[item.schedule_id] };
  }).filter((item) => !selectedSignal || item.links.some((link) => link.signal === selectedSignal)), [data, statusById, todayById, evidenceBySignal, selectedSignal]);
  const confirmed = (data.today || []).filter((item) => item.confirmed).length;

  function toggleReview(item) {
    if (openCard === item.schedule_id) {
      setOpenCard("");
      return;
    }
    const seeded = {};
    (item.monitoring_points || []).forEach((point) => {
      const linked = item.links.find((link) => link.criterion_text === point || point.includes(link.criterion_text) || link.criterion_text.includes(point));
      seeded[point] = linked?.evidence?.length ? "present" : "unknown";
    });
    setChecks(seeded);
    setNote("");
    setOpenCard(item.schedule_id);
  }

  async function saveReview(item, reportToClinician = false) {
    const observed_flags = (item.monitoring_points || []).map((label) => ({ label, status: checks[label] || "unknown" }));
    const presentCount = observed_flags.filter((entry) => entry.status === "present").length;
    setBusy(true);
    setError("");
    try {
      await api.addMedicationReview(item.schedule_id, {
        review_date: today,
        severity: reportToClinician ? 2 : presentCount ? 1 : 0,
        observed_flags,
        note: `${reportToClinician ? "[의료진 보고 예정] " : ""}${note}`.trim(),
      }, elderId);
      await load();
      setOpenCard("");
      onChanged?.();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function addMedication() {
    if (!draft.medication_name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.addMedication({
        medication_name: draft.medication_name.trim(),
        dosage_text: draft.dosage_text,
        scheduled_time: draft.scheduled_time,
        meal_relation: draft.meal_relation,
        days_of_week: draft.repeat === "daily" ? DAY_CODE : [DAY_CODE[new Date().getDay()]],
        indication: draft.indication,
        monitoring_points: draft.monitoring_text.split("\n").map((item) => item.trim()).filter(Boolean),
        review_interval_days: Number(draft.review_interval_days),
        escalation_criteria: draft.escalation_criteria,
      }, elderId);
      await load();
      setDraft(emptyMedication());
      setShowRegistration(false);
      onChanged?.();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeMedication(scheduleId) {
    setBusy(true);
    setError("");
    try {
      await api.removeMedication(scheduleId);
      await load();
      onChanged?.();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="medication-today-screen">
    <header className="medication-today-head">
      <div><p className="eyebrow">오늘 복약</p><h2>투약 {confirmed}/{(data.today || []).length}</h2></div>
      <button onClick={() => setShowRegistration(true)} aria-haspopup="dialog">약 등록·관리</button>
    </header>

    <div className="medication-filter-row" aria-label="관찰 증상 필터">
      <button className={!selectedSignal ? "on" : ""} onClick={() => setSelectedSignal("")}>전체</button>
      {(data.signal_options || []).map((item) => <button key={item.signal} className={selectedSignal === item.signal ? "on" : ""} onClick={() => setSelectedSignal(item.signal)}>{item.label}{item.evidence?.length > 0 && <span>{item.evidence.length}</span>}</button>)}
    </div>

    <div className="medication-card-list">
      {rows.map((item) => {
        const status = doseStatus(item.dose);
        const isOpen = openCard === item.schedule_id;
        const evidence = item.links.flatMap((link) => link.evidence.map((row) => ({ ...row, signal: link.signal, criterion: link.criterion_text })));
        return <article className={`medication-today-card ${status.tone} ${item.review_due ? "review-due" : ""}`} key={item.schedule_id}>
          <header>
            <div><h3>{item.medication_name} <small>{item.dosage_text}</small></h3><p>{item.scheduled_time} · {item.indication || "처방 목적 미등록"}</p></div>
            <div className="medication-card-status"><b className={status.tone}>{status.label}</b>{item.review_due && <span>관찰 주기 오늘 도래</span>}</div>
          </header>
          <div className="medication-card-body">
            <section><h4>관찰 항목</h4><ul>{(item.monitoring_points || []).map((point) => <li key={point}>{point}</li>)}{!item.monitoring_points?.length && <li>등록된 관찰 항목이 없습니다.</li>}</ul></section>
            <section className="medication-report-rule"><h4>보고 기준</h4><p>{item.escalation_criteria || "등록된 보고 기준이 없습니다."}</p></section>
          </div>
          {evidence.length > 0 && <section className="medication-card-evidence"><h4>오늘 AI 관찰 {evidence.length}건</h4>{evidence.slice(0, 4).map((row, index) => <blockquote key={`${row.call_id}-${index}`}><span>{row.criterion}</span>“{row.evidence}” <time>{String(row.at || "").slice(11, 16)}</time></blockquote>)}</section>}
          <footer>
            <span>{item.latestReviews?.[0] ? `최근 경과 ${item.latestReviews[0].review_date} · ${item.latestReviews[0].note || "메모 없음"}` : "최근 경과 기록 없음"}</span>
            <button onClick={() => toggleReview(item)}>관찰 항목 {(item.monitoring_points || []).length}개 확인하기 {isOpen ? "⌃" : "⌄"}</button>
          </footer>
          {isOpen && <section className="medication-inline-review">
            <div className="medication-check-items">{(item.monitoring_points || []).map((point) => <article key={point}><b>{point}</b><div className="medication-segmented">{[["present", "있음"], ["absent", "없음"], ["unknown", "확인 못함"]].map(([value, label]) => <button key={value} className={checks[point] === value ? `on ${value}` : ""} onClick={() => setChecks({ ...checks, [point]: value })}>{label}</button>)}</div></article>)}</div>
            <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="관찰 시각과 변화를 기록하세요." />
            {item.latestReviews?.length > 0 && <details className="medication-history-inline"><summary>최근 경과 {item.latestReviews.length}건</summary>{item.latestReviews.map((review) => <p key={review.review_id}><time>{review.review_date}</time><span>{review.note || "메모 없음"}</span></p>)}</details>}
            <div className="medication-check-actions"><button disabled={busy} onClick={() => saveReview(item, false)}>관찰 기록 저장</button><button className="primary" disabled={busy} onClick={() => saveReview(item, true)}>기록하고 의료진 보고</button></div>
          </section>}
        </article>;
      })}
      {!rows.length && <p className="empty-state">선택한 증상에 등록된 약이 없습니다.</p>}
    </div>

    {showRegistration && <div className="daily-modal-backdrop medication-registration-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setShowRegistration(false)}>
      <section className="calendar-editor-modal medication-registration-modal" role="dialog" aria-modal="true" aria-labelledby="medication-registration-title">
        <header>
          <div><p className="eyebrow">복약 관리</p><h2 id="medication-registration-title">약 등록·관리</h2></div>
          <button type="button" onClick={() => setShowRegistration(false)} aria-label="약 등록·관리 닫기">×</button>
        </header>
        <div className="medication-registration-list">{(data.medications || []).map((item) => <article key={item.schedule_id}><span><b>{item.medication_name}</b><small>{item.dosage_text} · {item.scheduled_time}</small></span><button disabled={busy} onClick={() => removeMedication(item.schedule_id)}>삭제</button></article>)}</div>
        <div className="calendar-editor-form medication">
          <label className="wide"><span>약 이름</span><input value={draft.medication_name} onChange={(event) => setDraft({ ...draft, medication_name: event.target.value })} /></label>
          <label><span>시간</span><input type="time" value={draft.scheduled_time} onChange={(event) => setDraft({ ...draft, scheduled_time: event.target.value })} /></label>
          <label><span>복용량</span><input value={draft.dosage_text} onChange={(event) => setDraft({ ...draft, dosage_text: event.target.value })} /></label>
          <label><span>식사 관계</span><select value={draft.meal_relation} onChange={(event) => setDraft({ ...draft, meal_relation: event.target.value })}><option value="after">식후</option><option value="before">식전</option><option value="none">관계없음</option></select></label>
          <label><span>반복</span><select value={draft.repeat} onChange={(event) => setDraft({ ...draft, repeat: event.target.value })}><option value="daily">매일</option><option value="weekday">매주 오늘 요일</option></select></label>
          <label className="wide"><span>처방 목적</span><input value={draft.indication} onChange={(event) => setDraft({ ...draft, indication: event.target.value })} /></label>
          <label><span>관찰 주기</span><input type="number" min="1" max="180" value={draft.review_interval_days} onChange={(event) => setDraft({ ...draft, review_interval_days: event.target.value })} /></label>
          <label className="wide"><span>관찰 항목</span><textarea value={draft.monitoring_text} onChange={(event) => setDraft({ ...draft, monitoring_text: event.target.value })} placeholder="한 줄에 하나씩 입력" /></label>
          <label className="wide"><span>의료진 보고 기준</span><textarea value={draft.escalation_criteria} onChange={(event) => setDraft({ ...draft, escalation_criteria: event.target.value })} /></label>
          <button className="calendar-editor-submit" disabled={busy || !draft.medication_name.trim()} onClick={addMedication}>{busy ? "저장 중" : "약 등록"}</button>
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>}
    {error && !showRegistration && <p className="error">{error}</p>}
  </section>;
}
