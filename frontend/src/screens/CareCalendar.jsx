import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

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

function scheduleType(item) {
  const note = String(item.note || "");
  if (note.startsWith("[병원]")) return "hospital";
  if (note.startsWith("[가족 방문]")) return "visit";
  return "care";
}

function weekBars(week, schedules) {
  const bars = [];
  const sameDayLane = {};
  week.forEach((date, day) => {
    schedules.filter((item) => item.date === dateKey(date)).forEach((item) => {
      const localLane = sameDayLane[day] || 0;
      sameDayLane[day] = localLane + 1;
      bars.push({
        key: `schedule-${item.schedule_id}`,
        kind: `${item.confirmed ? "schedule" : "unconfirmed"} ${scheduleType(item)}`,
        start: day,
        span: 1,
        lane: localLane,
        label: `${item.time || "종일"} ${item.title}`,
      });
    });
  });
  return bars;
}

const emptySchedule = () => ({ type: "hospital", time: "10:00", title: "", note: "" });

export default function CareCalendar({ elderId = "elder_001", refreshKey = 0, onChanged, dailyReports = [] }) {
  const [cursor, setCursor] = useState(() => new Date());
  const [schedules, setSchedules] = useState([]);
  const [reviewStatus, setReviewStatus] = useState([]);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState(() => dateKey(new Date()));
  const [editorOpen, setEditorOpen] = useState(false);
  const [scheduleDraft, setScheduleDraft] = useState(emptySchedule);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [scheduleResult, medicationResult] = await Promise.all([
      api.getSchedules(elderId),
      api.getMedications(elderId),
    ]);
    setSchedules([...(scheduleResult.past || []), ...(scheduleResult.upcoming || [])]);
    setReviewStatus(medicationResult.review_status || []);
  }

  useEffect(() => {
    load().catch((reason) => setError(reason.message));
  }, [elderId, refreshKey]);

  const cells = useMemo(() => monthCells(cursor), [cursor]);
  const weeks = useMemo(() => [...Array(6)].map((_, index) => cells.slice(index * 7, index * 7 + 7)), [cells]);
  const reportsByDate = useMemo(() => Object.fromEntries((dailyReports || []).map((row) => [row.date, row])), [dailyReports]);
  const maxObservations = Math.max(1, ...(dailyReports || []).map((row) => row.observation_count || 0));
  const reviewDates = useMemo(() => new Set((reviewStatus || []).map((row) => row.review_due_on).filter(Boolean)), [reviewStatus]);
  const todayKey = dateKey(new Date());
  const selectedDate = new Date(`${selectedKey}T00:00:00`);
  const selectedLabel = selectedDate.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" });
  const selectedSchedules = schedules.filter((item) => item.date === selectedKey);
  const moveMonth = (amount) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + amount, 1));

  function openEditor(key) {
    setSelectedKey(key);
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
        title: scheduleDraft.title.trim(),
        date: selectedKey,
        time: scheduleDraft.time,
        note: `[${prefix}] ${scheduleDraft.note}`.trim(),
        confirmed: true,
      }, elderId);
      await load();
      setScheduleDraft(emptySchedule());
      onChanged?.();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="care-calendar schedule-only-calendar dashboard-card">
    <header className="calendar-head">
      <div><p className="eyebrow">일정</p><h2>{cursor.getFullYear()}년 {cursor.getMonth() + 1}월</h2></div>
      <div className="calendar-nav">
        <button onClick={() => moveMonth(-1)} aria-label="이전 달">‹</button>
        <button onClick={() => setCursor(new Date())}>오늘</button>
        <button onClick={() => moveMonth(1)} aria-label="다음 달">›</button>
      </div>
    </header>
    <div className="calendar-legend schedule-calendar-legend">
      <span className="observation-scale"><b>관찰량</b><i /><i /><i /></span>
      <span><i className="dot safety" />안전</span>
      <span><i className="dot visit" />방문</span>
      <span><i className="dot review" />관찰 도래</span>
    </div>
    <div className="calendar-grid calendar-weekdays">{WEEKDAY.map((day) => <b key={day}>{day}</b>)}</div>
    <div className="calendar-month">{weeks.map((week, weekIndex) => {
      const bars = weekBars(week, schedules);
      const lanes = Math.max(1, ...bars.map((bar) => bar.lane + 1));
      return <section className="calendar-week" key={`week-${weekIndex}`} style={{ "--calendar-lanes": lanes }}>
        <div className="calendar-week-days">{week.map((date) => {
          const key = dateKey(date);
          const report = reportsByDate[key] || {};
          const intensity = Math.min(1, (report.observation_count || 0) / maxObservations);
          const hasSafety = (report.risk_count || 0) > 0;
          const hasVisit = schedules.some((item) => item.date === key && ["hospital", "visit"].includes(scheduleType(item)));
          const hasReview = reviewDates.has(key);
          const open = () => openEditor(key);
          return <article
            key={key}
            role="button"
            tabIndex="0"
            onClick={open}
            onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && open()}
            className={`${date.getMonth() === cursor.getMonth() ? "" : "outside"} ${key === todayKey ? "today" : ""} ${key === selectedKey ? "selected" : ""}`}
            style={{ "--observation-intensity": intensity }}
            aria-label={`${key} 일정 열기`}
          >
            <time>{date.getDate()}</time>
            <span className="calendar-cell-dots" aria-hidden="true">
              {hasSafety && <i className="safety" />}
              {hasVisit && <i className="visit" />}
              {hasReview && <i className="review" />}
            </span>
          </article>;
        })}</div>
        <div className="calendar-week-events">{bars.map((bar) => <span
          key={bar.key}
          className={`calendar-event ${bar.kind}`}
          style={{ gridColumn: `${bar.start + 1} / span ${bar.span}`, gridRow: bar.lane + 1 }}
          title={bar.label}
        >{bar.label}</span>)}</div>
      </section>;
    })}</div>
    <footer className="calendar-compact-summary">
      <span><b>{schedules.length}</b> 등록 일정</span>
      <button onClick={() => openEditor(todayKey)}>오늘 일정 추가</button>
    </footer>
    {error && !editorOpen && <p className="error">{error}</p>}

    {editorOpen && <div className="daily-modal-backdrop calendar-editor-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setEditorOpen(false)}>
      <section className="calendar-editor-modal schedule-editor-modal" role="dialog" aria-modal="true" aria-labelledby="calendar-editor-title">
        <header>
          <div><p className="eyebrow">일정 추가</p><h2 id="calendar-editor-title">{selectedLabel}</h2></div>
          <button onClick={() => setEditorOpen(false)} aria-label="닫기">×</button>
        </header>
        <section className="calendar-editor-existing single">
          <div><span>등록 일정 {selectedSchedules.length}</span>{selectedSchedules.map((item) => <article key={item.schedule_id}><time>{item.time || "종일"}</time><b>{item.title}</b></article>)}{!selectedSchedules.length && <small>등록된 일정이 없습니다.</small>}</div>
        </section>
        <div className="calendar-editor-form schedule">
          <label><span>분류</span><select value={scheduleDraft.type} onChange={(event) => setScheduleDraft({ ...scheduleDraft, type: event.target.value })}><option value="hospital">병원</option><option value="visit">가족 방문</option><option value="care">케어 일정</option></select></label>
          <label><span>시간</span><input type="time" value={scheduleDraft.time} onChange={(event) => setScheduleDraft({ ...scheduleDraft, time: event.target.value })} /></label>
          <label className="wide"><span>일정 내용</span><input placeholder="예: 신경과 정기 진료" value={scheduleDraft.title} onChange={(event) => setScheduleDraft({ ...scheduleDraft, title: event.target.value })} /></label>
          <label className="wide"><span>담당자 메모 · 선택</span><input placeholder="준비물이나 동행자를 적어주세요" value={scheduleDraft.note} onChange={(event) => setScheduleDraft({ ...scheduleDraft, note: event.target.value })} /></label>
          <button className="calendar-editor-submit" disabled={busy || !scheduleDraft.title.trim()} onClick={addSelectedSchedule}>{busy ? "저장 중" : "이 날짜에 일정 추가"}</button>
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>}
  </section>;
}
