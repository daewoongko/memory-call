import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
const DAY_CODE = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MEDICATION_COLORS = [
  "#24744f", "#d46b21", "#859d29", "#b45a2f", "#b3801f",
  "#4f7654", "#9a6435", "#6f8538", "#c2513f", "#477660",
];

function medicationColor(medication, allMedications = []) {
  const names = [...new Set(allMedications.map((item) => item.medication_name))];
  const medicationIndex = names.indexOf(medication.medication_name);
  if (medicationIndex >= 0) return MEDICATION_COLORS[medicationIndex % MEDICATION_COLORS.length];
  const seed = `${medication.schedule_id || ""}:${medication.medication_name || ""}`;
  const hash = [...seed].reduce((total, character) => ((total * 31) + character.charCodeAt(0)) >>> 0, 0);
  return MEDICATION_COLORS[hash % MEDICATION_COLORS.length];
}

const dateKey = (date) => [
  date.getFullYear(),
  String(date.getMonth() + 1).padStart(2, "0"),
  String(date.getDate()).padStart(2, "0"),
].join("-");

function monthCells(cursor) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return [...Array(42)].map((_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function weekBars(week, medications, schedules, todayKey, confirmedToday) {
  const bars = [];
  medications.forEach((medication, lane) => {
    const enabled = medication.days_of_week || DAY_CODE;
    let start = null;
    for (let day = 0; day <= 7; day += 1) {
      const active = day < 7 && enabled.includes(DAY_CODE[week[day].getDay()]);
      if (active && start === null) start = day;
      if (!active && start !== null) {
        bars.push({
          key: `med-${medication.schedule_id}-${start}`, kind: "medication",
          start, span: day - start, lane,
          label: `${medication.scheduled_time} ${medication.medication_name}`,
          color: medicationColor(medication, medications),
          confirmed: week.slice(start, day).some((date) =>
            dateKey(date) === todayKey && confirmedToday.has(medication.schedule_id)),
        });
        start = null;
      }
    }
  });
  const sameDayLane = {};
  week.forEach((date, day) => {
    schedules.filter((item) => item.date === dateKey(date)).forEach((item) => {
      const localLane = sameDayLane[day] || 0;
      sameDayLane[day] = localLane + 1;
      bars.push({
        key: `schedule-${item.schedule_id}`, kind: item.confirmed ? "schedule" : "unconfirmed",
        start: day, span: 1, lane: medications.length + localLane,
        label: `${item.time || "종일"} ${item.title}`,
      });
    });
  });
  return bars;
}

const emptySchedule = () => ({ type: "hospital", time: "10:00", title: "", note: "" });
const emptyMedication = () => ({
  medication_name: "", dosage_text: "1정", scheduled_time: "20:00", meal_relation: "after",
  repeat: "daily", indication: "", monitoring_text: "", review_interval_days: 14,
  escalation_criteria: "",
});

export default function CareCalendar({ elderId = "elder_001", refreshKey = 0, onChanged }) {
  const [cursor, setCursor] = useState(() => new Date());
  const [schedules, setSchedules] = useState([]);
  const [medications, setMedications] = useState([]);
  const [todayMeds, setTodayMeds] = useState([]);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState(() => dateKey(new Date()));
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorTab, setEditorTab] = useState("schedule");
  const [scheduleDraft, setScheduleDraft] = useState(emptySchedule);
  const [medicationDraft, setMedicationDraft] = useState(emptyMedication);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [scheduleResult, medicationResult] = await Promise.all([
      api.getSchedules(elderId), api.getMedications(elderId),
    ]);
    setSchedules([...(scheduleResult.past || []), ...(scheduleResult.upcoming || [])]);
    setMedications(medicationResult.medications || medicationResult.today || []);
    setTodayMeds(medicationResult.today || []);
  }

  useEffect(() => {
    load().catch((reason) => setError(reason.message));
  }, [elderId, refreshKey]);

  const cells = useMemo(() => monthCells(cursor), [cursor]);
  const weeks = useMemo(() => [...Array(6)].map((_, index) => cells.slice(index * 7, index * 7 + 7)), [cells]);
  const todayKey = dateKey(new Date());
  const confirmedToday = new Set(todayMeds.filter((item) => item.confirmed).map((item) => item.schedule_id));
  const selectedDate = new Date(`${selectedKey}T00:00:00`);
  const selectedDayCode = DAY_CODE[selectedDate.getDay()];
  const selectedLabel = selectedDate.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" });
  const selectedSchedules = schedules.filter((item) => item.date === selectedKey);
  const selectedMedications = medications.filter((item) => (item.days_of_week || DAY_CODE).includes(selectedDayCode));
  const moveMonth = (amount) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + amount, 1));

  function openEditor(key, tab = "schedule") {
    setSelectedKey(key);
    setEditorTab(tab);
    setError("");
    setEditorOpen(true);
  }

  async function addSelectedSchedule() {
    if (!scheduleDraft.title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const prefix = { hospital: "병원", visit: "가족 방문", care: "케어" }[scheduleDraft.type];
      await api.addSchedule({
        title: scheduleDraft.title.trim(), date: selectedKey, time: scheduleDraft.time,
        note: `[${prefix}] ${scheduleDraft.note}`.trim(), confirmed: true,
      }, elderId);
      await load();
      setScheduleDraft(emptySchedule());
      onChanged?.();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  async function addSelectedMedication() {
    if (!medicationDraft.medication_name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const payload = {
        medication_name: medicationDraft.medication_name.trim(),
        dosage_text: medicationDraft.dosage_text,
        scheduled_time: medicationDraft.scheduled_time,
        meal_relation: medicationDraft.meal_relation,
        days_of_week: medicationDraft.repeat === "daily" ? DAY_CODE : [selectedDayCode],
        indication: medicationDraft.indication,
        monitoring_points: medicationDraft.monitoring_text.split("\n").map((item) => item.trim()).filter(Boolean),
        review_interval_days: Number(medicationDraft.review_interval_days),
        escalation_criteria: medicationDraft.escalation_criteria,
      };
      await api.addMedication(payload, elderId);
      await load();
      setMedicationDraft(emptyMedication());
      onChanged?.();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  async function removeMedication(scheduleId) {
    setBusy(true);
    try {
      await api.removeMedication(scheduleId);
      await load();
      onChanged?.();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  return <section className="care-calendar dashboard-card">
    <header className="calendar-head">
      <div><p className="eyebrow">생활 케어 캘린더</p><h2>{cursor.getFullYear()}년 {cursor.getMonth() + 1}월</h2><small>날짜를 누르면 일정과 복약을 한곳에서 확인하고 추가할 수 있습니다.</small></div>
      <div className="calendar-nav">
        <button onClick={() => moveMonth(-1)} aria-label="이전 달">‹</button>
        <button onClick={() => setCursor(new Date())}>오늘</button>
        <button onClick={() => moveMonth(1)} aria-label="다음 달">›</button>
      </div>
    </header>
    <div className="calendar-legend">
      <span><i className="schedule" />가족·병원 일정</span>
      {medications.map((medication) => <span key={medication.schedule_id}>
        <i style={{ background: medicationColor(medication, medications) }} />{medication.medication_name}
      </span>)}
      <span><i className="unconfirmed" />미확정 일정</span>
    </div>
    <div className="calendar-grid calendar-weekdays">{WEEKDAY.map((day) => <b key={day}>{day}</b>)}</div>
    <div className="calendar-month">{weeks.map((week, weekIndex) => {
      const bars = weekBars(week, medications, schedules, todayKey, confirmedToday);
      const lanes = Math.max(1, ...bars.map((bar) => bar.lane + 1));
      return <section className="calendar-week" key={`week-${weekIndex}`} style={{ "--calendar-lanes": lanes }}>
        <div className="calendar-week-days">{week.map((date) => {
          const key = dateKey(date);
          const open = () => openEditor(key);
          return <article key={key} role="button" tabIndex="0" onClick={open} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && open()} className={`${date.getMonth() === cursor.getMonth() ? "" : "outside"} ${key === todayKey ? "today" : ""} ${key === selectedKey ? "selected" : ""}`} aria-label={`${key} 일정과 복약 열기`}>
            <time>{date.getDate()}</time>
          </article>;
        })}</div>
        <div className="calendar-week-events">{bars.map((bar) => <span
          key={bar.key}
          className={`calendar-event ${bar.kind} ${bar.confirmed ? "confirmed" : ""}`}
          style={{ gridColumn: `${bar.start + 1} / span ${bar.span}`, gridRow: bar.lane + 1, "--event-color": bar.color }}
          title={bar.label}
        >{bar.label}</span>)}</div>
      </section>;
    })}</div>
    <footer className="calendar-compact-summary">
      <span><b>{schedules.length}</b> 등록 일정</span>
      <span><b>{medications.length}</b> 복약 루틴</span>
      <button onClick={() => openEditor(todayKey)}>오늘 항목 추가</button>
    </footer>
    {error && !editorOpen && <p className="error">{error}</p>}

    {editorOpen && <div className="daily-modal-backdrop calendar-editor-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setEditorOpen(false)}>
      <section className="calendar-editor-modal" role="dialog" aria-modal="true" aria-labelledby="calendar-editor-title">
        <header>
          <div><p className="eyebrow">선택한 날짜</p><h2 id="calendar-editor-title">{selectedLabel}</h2><small>등록된 내용을 확인한 뒤 필요한 항목만 추가하세요.</small></div>
          <button onClick={() => setEditorOpen(false)} aria-label="닫기">×</button>
        </header>

        <div className="calendar-editor-tabs" role="tablist">
          <button className={editorTab === "schedule" ? "on" : ""} onClick={() => setEditorTab("schedule")}>일정 추가</button>
          <button className={editorTab === "medication" ? "on" : ""} onClick={() => setEditorTab("medication")}>복약 추가</button>
        </div>

        <section className="calendar-editor-existing">
          <div><span>등록 일정 {selectedSchedules.length}</span>{selectedSchedules.map((item) => <article key={item.schedule_id}><time>{item.time || "종일"}</time><b>{item.title}</b></article>)}{!selectedSchedules.length && <small>등록된 일정이 없습니다.</small>}</div>
          <div><span>복약 루틴 {selectedMedications.length}</span>{selectedMedications.map((item) => <article key={item.schedule_id} style={{ "--medication-color": medicationColor(item, medications) }}><time>{item.scheduled_time}</time><b>{item.medication_name}</b><button onClick={() => removeMedication(item.schedule_id)} disabled={busy} aria-label={`${item.medication_name} 삭제`}>삭제</button></article>)}{!selectedMedications.length && <small>이 요일의 복약 루틴이 없습니다.</small>}</div>
        </section>

        {editorTab === "schedule" ? <div className="calendar-editor-form schedule">
          <label><span>분류</span><select value={scheduleDraft.type} onChange={(event) => setScheduleDraft({ ...scheduleDraft, type: event.target.value })}><option value="hospital">병원</option><option value="visit">가족 방문</option><option value="care">케어 일정</option></select></label>
          <label><span>시간</span><input type="time" value={scheduleDraft.time} onChange={(event) => setScheduleDraft({ ...scheduleDraft, time: event.target.value })} /></label>
          <label className="wide"><span>일정 내용</span><input placeholder="예: 신경과 정기 진료" value={scheduleDraft.title} onChange={(event) => setScheduleDraft({ ...scheduleDraft, title: event.target.value })} /></label>
          <label className="wide"><span>담당자 메모 · 선택</span><input placeholder="준비물이나 동행자를 적어주세요" value={scheduleDraft.note} onChange={(event) => setScheduleDraft({ ...scheduleDraft, note: event.target.value })} /></label>
          <button className="calendar-editor-submit" disabled={busy || !scheduleDraft.title.trim()} onClick={addSelectedSchedule}>{busy ? "저장 중" : "이 날짜에 일정 추가"}</button>
        </div> : <div className="calendar-editor-form medication">
          <label className="wide"><span>약 이름</span><input placeholder="예: 아침 당뇨약" value={medicationDraft.medication_name} onChange={(event) => setMedicationDraft({ ...medicationDraft, medication_name: event.target.value })} /></label>
          <label><span>시간</span><input type="time" value={medicationDraft.scheduled_time} onChange={(event) => setMedicationDraft({ ...medicationDraft, scheduled_time: event.target.value })} /></label>
          <label><span>복용량</span><input value={medicationDraft.dosage_text} onChange={(event) => setMedicationDraft({ ...medicationDraft, dosage_text: event.target.value })} /></label>
          <label><span>식사 관계</span><select value={medicationDraft.meal_relation} onChange={(event) => setMedicationDraft({ ...medicationDraft, meal_relation: event.target.value })}><option value="after">식후</option><option value="before">식전</option><option value="none">관계없음</option></select></label>
          <label><span>반복</span><select value={medicationDraft.repeat} onChange={(event) => setMedicationDraft({ ...medicationDraft, repeat: event.target.value })}><option value="daily">매일</option><option value="weekday">매주 {WEEKDAY[selectedDate.getDay()]}요일</option></select></label>
          <label className="wide"><span>복용 목적</span><input placeholder="예: 고혈압 관리" value={medicationDraft.indication} onChange={(event) => setMedicationDraft({ ...medicationDraft, indication: event.target.value })} /></label>
          <label><span>경과 확인 주기</span><input type="number" min="1" max="180" value={medicationDraft.review_interval_days} onChange={(event) => setMedicationDraft({ ...medicationDraft, review_interval_days: event.target.value })} /></label>
          <label className="wide"><span>담당자 관찰 항목</span><textarea placeholder={'한 줄에 하나씩 입력\n예: 어지럼\n예: 보행 불안'} value={medicationDraft.monitoring_text} onChange={(event) => setMedicationDraft({ ...medicationDraft, monitoring_text: event.target.value })} /></label>
          <label className="wide"><span>의료진에게 보고할 기준</span><textarea placeholder="담당자가 관찰 후 의료진에게 알릴 기준을 적어주세요." value={medicationDraft.escalation_criteria} onChange={(event) => setMedicationDraft({ ...medicationDraft, escalation_criteria: event.target.value })} /></label>
          <button className="calendar-editor-submit" disabled={busy || !medicationDraft.medication_name.trim()} onClick={addSelectedMedication}>{busy ? "저장 중" : "복약 루틴 추가"}</button>
        </div>}
        {error && <p className="error">{error}</p>}
      </section>
    </div>}
  </section>;
}
