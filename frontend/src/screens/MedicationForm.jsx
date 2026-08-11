import { useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * 보호자가 복약 일정을 등록하는 곳.
 *
 * 노인은 아무것도 입력하지 않는다. 여기 등록된 시간이 되면
 * AI 가 전화를 걸어 말로 확인하고, 그 결과가 리포트에 쌓인다.
 */

const MEAL = { before: "식전", after: "식후", none: "" };

export default function MedicationForm({ elderId = "elder_001", onChanged }) {
  const [today, setToday] = useState([]);
  const [form, setForm] = useState({
    medication_name: "",
    dosage_text: "1정",
    scheduled_time: "20:00",
    meal_relation: "after",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    api.getMedications(elderId).then((r) => setToday(r.today)).catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function submit() {
    if (!form.medication_name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.addMedication(form, elderId);
      setToday(r.today);
      setForm({ ...form, medication_name: "" });
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(scheduleId) {
    await api.removeMedication(scheduleId);
    await load();
    onChanged?.();
  }

  return (
    <section className="meds">
      <h2>복약 일정</h2>
      <p className="hint">
        등록한 시간이 되면 대웅이가 먼저 전화해서 확인해요.
        할아버지는 따로 입력하지 않으셔도 됩니다.
      </p>

      <ul className="med-list">
        {today.map((m) => (
          <li key={m.schedule_id} className={m.confirmed ? "done" : ""}>
            <div>
              <b>{m.scheduled_time}</b> {m.medication_name}
              <span className="row-meta">
                {" "}
                {[MEAL[m.meal_relation], m.dosage_text].filter(Boolean).join(" ")}
              </span>
            </div>
            <div className="med-right">
              <span className="tag">
                {m.confirmed ? "오늘 확인됨" : "아직 확인 안 됨"}
              </span>
              <button onClick={() => remove(m.schedule_id)} aria-label="삭제">
                ✕
              </button>
            </div>
          </li>
        ))}
        {!today.length && <li className="hint">등록된 일정이 없어요.</li>}
      </ul>

      <div className="med-form">
        <input
          placeholder="약 이름"
          value={form.medication_name}
          onChange={(e) => setForm({ ...form, medication_name: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <input
          type="time"
          value={form.scheduled_time}
          onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })}
        />
        <input
          className="narrow"
          placeholder="1정"
          value={form.dosage_text}
          onChange={(e) => setForm({ ...form, dosage_text: e.target.value })}
        />
        <select
          value={form.meal_relation}
          onChange={(e) => setForm({ ...form, meal_relation: e.target.value })}
        >
          <option value="after">식후</option>
          <option value="before">식전</option>
          <option value="none">상관없음</option>
        </select>
        <button onClick={submit} disabled={busy || !form.medication_name.trim()}>
          추가
        </button>
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  );
}
