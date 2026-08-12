import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";


const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
const DAY_CODE = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MEDICATION_COLORS = [
  "#8f96ff", "#ff9b73", "#56c6a5", "#e88bc3", "#e4bd55",
  "#55b7dc", "#b391ed", "#ef707b", "#83bd63", "#d98b5f",
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

export default function CareCalendar({ elderId = "elder_001", refreshKey = 0, onChanged }) {
  const [cursor, setCursor] = useState(() => new Date());
  const [schedules, setSchedules] = useState([]);
  const [medications, setMedications] = useState([]);
  const [todayMeds, setTodayMeds] = useState([]);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState(() => dateKey(new Date()));
  const [draft, setDraft] = useState({ type: "hospital", time: "10:00", title: "", note: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api.getSchedules(elderId), api.getMedications(elderId)])
      .then(([scheduleResult, medicationResult]) => {
        setSchedules([...(scheduleResult.past || []), ...(scheduleResult.upcoming || [])]);
        setMedications(medicationResult.medications || medicationResult.today || []);
        setTodayMeds(medicationResult.today || []);
      })
      .catch((reason) => setError(reason.message));
  }, [elderId, refreshKey]);

  const cells = useMemo(() => monthCells(cursor), [cursor]);
  const weeks = useMemo(() => [...Array(6)].map((_, index) => cells.slice(index * 7, index * 7 + 7)), [cells]);
  const todayKey = dateKey(new Date());
  const confirmedToday = new Set(todayMeds.filter((item) => item.confirmed).map((item) => item.schedule_id));
  const moveMonth = (amount) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + amount, 1));
  const todaySchedules = schedules.filter((item) => item.date === todayKey);
  const selectedSchedules = schedules.filter((item) => item.date === selectedKey);
  const selectedLabel = new Date(`${selectedKey}T00:00:00`).toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
  const nextWeek = new Date();
  nextWeek.setDate(nextWeek.getDate() + 7);
  const comingWeek = schedules.filter((item) => item.date >= todayKey && item.date <= dateKey(nextWeek));

  async function addSelectedSchedule() {
    if (!draft.title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const prefix = { hospital: "병원", visit: "방문", care: "케어" }[draft.type];
      await api.addSchedule({
        title: draft.title.trim(), date: selectedKey, time: draft.time,
        note: `[${prefix}] ${draft.note}`.trim(), confirmed: true,
      }, elderId);
      const result = await api.getSchedules(elderId);
      setSchedules([...(result.past || []), ...(result.upcoming || [])]);
      setDraft((current) => ({ ...current, title: "", note: "" }));
      onChanged?.();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  return <section className="care-calendar dashboard-card">
    <header className="calendar-head">
      <div><p className="eyebrow">생활 케어 캘린더</p><h2>{cursor.getFullYear()}년 {cursor.getMonth() + 1}월</h2></div>
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
          return <article key={key} role="button" tabIndex="0" onClick={() => setSelectedKey(key)} onKeyDown={(event) => event.key === "Enter" && setSelectedKey(key)} className={`${date.getMonth() === cursor.getMonth() ? "" : "outside"} ${key === todayKey ? "today" : ""} ${key === selectedKey ? "selected" : ""}`}>
            <time>{date.getDate()}</time>
          </article>;
        })}</div>
        <div className="calendar-week-events">{bars.map((bar) => <span
          key={bar.key}
          className={`calendar-event ${bar.kind} ${bar.confirmed ? "confirmed" : ""}`}
          style={{
            gridColumn: `${bar.start + 1} / span ${bar.span}`,
            gridRow: bar.lane + 1,
            "--event-color": bar.color,
          }}
          title={bar.label}
        >{bar.label}</span>)}</div>
      </section>;
    })}</div>
    <div className="calendar-bottom-panels">
      <section>
        <header><span className="calendar-panel-date">선택</span><h3>{selectedLabel} 일정</h3></header>
        <div className="calendar-agenda-list">{selectedSchedules.map((item) => <article key={item.schedule_id}>
          <time>{item.time || "종일"}</time><div><b>{item.title}</b><small>{item.confirmed ? "확정 일정" : "미확정"}</small></div>
        </article>)}{!selectedSchedules.length && <p>선택한 날짜에 등록된 일정이 없습니다.</p>}</div>
        <div className="calendar-quick-add">
          <select value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value })}><option value="hospital">병원</option><option value="visit">가족 방문</option><option value="care">케어 일정</option></select>
          <input type="time" value={draft.time} onChange={(event) => setDraft({ ...draft, time: event.target.value })} />
          <input placeholder="일정 내용" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} onKeyDown={(event) => event.key === "Enter" && addSelectedSchedule()} />
          <input placeholder="담당자 메모(선택)" value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} />
          <button disabled={busy || !draft.title.trim()} onClick={addSelectedSchedule}>{busy ? "저장 중" : "이 날짜에 추가"}</button>
        </div>
      </section>
      <section>
        <header><span className="calendar-panel-date medication">약</span><h3>오늘 복약 루틴</h3></header>
        <div className="calendar-routine-list">{todayMeds.map((item) => <article key={item.schedule_id} className={item.confirmed ? "done" : ""} style={{ "--medication-color": medicationColor(item, medications) }}>
          <i>{item.confirmed ? "✓" : ""}</i><div><b>{item.medication_name}</b><small>{item.scheduled_time} · {item.dosage_text}</small></div><span>{item.confirmed ? "확인됨" : "확인 전"}</span>
        </article>)}{!todayMeds.length && <p>오늘 복약 일정이 없습니다.</p>}</div>
      </section>
      <section className="calendar-week-summary">
        <header><span className="calendar-panel-date summary">7일</span><h3>이번 주 요약</h3></header>
        <div><p><b>{comingWeek.length}</b><span>예정 일정</span></p><p><b>{todayMeds.length}</b><span>오늘 복약</span></p><p><b>{todayMeds.filter((item) => item.confirmed).length}</b><span>복약 확인</span></p></div>
      </section>
    </div>
    {error && <p className="error">{error}</p>}
  </section>;
}
