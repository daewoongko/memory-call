import { useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * 방문·병원 일정.
 *
 * 명세 FR-04 — AI 는 여기 등록된 일정만 이야기한다.
 * 없는 약속을 하려 하면 안전 규칙이 응답을 막는다.
 *
 * 확정 여부가 중요하다. 미확정 일정은 대화에 쓰이지 않으므로
 * 화면에서 그 차이가 바로 보여야 한다.
 */

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

function label(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  const base = `${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAY[d.getDay()]})`;
  if (diff === 0) return `${base} · 오늘`;
  if (diff === 1) return `${base} · 내일`;
  if (diff > 1 && diff <= 14) return `${base} · ${diff}일 뒤`;
  return base;
}

const today = () => new Date().toISOString().slice(0, 10);

export default function ScheduleForm() {
  const [upcoming, setUpcoming] = useState([]);
  const [past, setPast] = useState([]);
  const [form, setForm] = useState({
    title: "",
    date: today(),
    time: "14:00",
    note: "",
    confirmed: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    api
      .getSchedules()
      .then((r) => {
        setUpcoming(r.upcoming);
        setPast(r.past);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function guard(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const add = () =>
    form.title.trim() &&
    guard(async () => {
      await api.addSchedule(form);
      setForm({ ...form, title: "", note: "" });
    });

  return (
    <section className="meds">
      <h2>방문·병원 일정</h2>
      <p className="hint">
        대웅이는 <b>확정된 다가오는 일정만</b> 이야기해요.
        등록되지 않은 방문을 약속하려 하면 자동으로 막힙니다.
      </p>

      <ul className="med-list">
        {upcoming.map((s) => (
          <li key={s.schedule_id} className={s.used_in_call ? "" : "off"}>
            <div className="mem-body">
              <b>{label(s.date)}</b>
              <span className="row-meta"> {s.time}</span>
              <div>{s.title}</div>
              {s.note && <div className="quote">{s.note}</div>}
            </div>
            <div className="med-right">
              <span className={`tag ${s.used_in_call ? "ok" : ""}`}>
                {s.used_in_call ? "대화에 사용" : "미확정"}
              </span>
              <button
                disabled={busy}
                onClick={() =>
                  guard(() =>
                    api.patchSchedule(s.schedule_id, { confirmed: !s.confirmed })
                  )
                }
              >
                {s.confirmed ? "보류" : "확정"}
              </button>
              <button
                disabled={busy}
                onClick={() => guard(() => api.deleteSchedule(s.schedule_id))}
                aria-label="삭제"
              >
                ✕
              </button>
            </div>
          </li>
        ))}
        {!upcoming.length && (
          <li className="hint">
            다가오는 일정이 없어요. 이 상태에서는 대웅이가 어떤 방문도 약속하지 않아요.
          </li>
        )}
      </ul>

      <div className="med-form">
        <input
          placeholder="일정 (예: 대웅이 방문)"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <input
          type="date"
          value={form.date}
          onChange={(e) => setForm({ ...form, date: e.target.value })}
        />
        <input
          type="time"
          value={form.time}
          onChange={(e) => setForm({ ...form, time: e.target.value })}
        />
        <button onClick={add} disabled={busy || !form.title.trim()}>
          추가
        </button>
      </div>
      <input
        className="wide"
        placeholder="메모 (예: 아버지가 모시고 감)"
        value={form.note}
        onChange={(e) => setForm({ ...form, note: e.target.value })}
      />

      {past.length > 0 && (
        <>
          <h2 className="section-title">지난 일정</h2>
          <p className="hint">지난 일정은 대화에 쓰이지 않아요.</p>
          <ul className="med-list">
            {past.slice(0, 5).map((s) => (
              <li key={s.schedule_id} className="off">
                <div>
                  <b>{label(s.date)}</b> {s.title}
                </div>
                <div className="med-right">
                  <button
                    disabled={busy}
                    onClick={() => guard(() => api.deleteSchedule(s.schedule_id))}
                    aria-label="삭제"
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  );
}
