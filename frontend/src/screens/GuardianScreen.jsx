import { useCallback, useEffect, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import MedicationForm from "./MedicationForm.jsx";
import MemoryPanel from "./MemoryPanel.jsx";
import PersonaPanel from "./PersonaPanel.jsx";
import ReportTabs from "./ReportTabs.jsx";
import ScheduleForm from "./ScheduleForm.jsx";

/**
 * 보호자 화면.
 *
 * 돌볼 대상을 먼저 고르고, 그 사람의 리포트를 카테고리별로 본다.
 * 명세 FR-11/12 — 진단하지 않고 관찰된 사실만 전달한다.
 */

const MAIN_TABS = [
  { id: "report", label: "리포트" },
  { id: "memories", label: "기억" },
  { id: "plan", label: "일정·복약" },
  { id: "setup", label: "설정" },
];

export default function GuardianScreen() {
  const [elders, setElders] = useState(null);
  const [picked, setPicked] = useState(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    name: "",
    preferred_call_name: "할아버지",
    persona_name: "",
    relationship: "손자",
  });
  const [tab, setTab] = useState("report");
  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");

  const loadSummary = useCallback(
    () => api.getPeriodSummary(days).then(setSummary).catch((e) => setError(e.message)),
    [days]
  );

  const loadElders = useCallback(
    () => api.getElders().then((r) => setElders(r.elders)).catch((e) => setError(e.message)),
    []
  );

  useEffect(() => {
    loadElders();
  }, [loadElders]);

  async function submitElder() {
    if (!form.name.trim()) return;
    try {
      await api.addElder(form);
      setForm({ ...form, name: "", persona_name: "" });
      setAdding(false);
      await loadElders();
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    if (picked) loadSummary();
  }, [picked, loadSummary]);

  if (error && !elders) return <div className="guardian"><p className="error">{error}</p></div>;
  if (!elders) return <div className="guardian"><p className="hint">불러오는 중…</p></div>;

  if (!picked) {
    return (
      <div className="guardian">
        <header className="g-head">
          <BrandMark size={34} />
          <span className="g-brand">다소니</span>
        </header>

        <h1 className="g-title">누구를 돌보고 계신가요?</h1>

        <div className="elder-cards">
          {elders.map((e) => (
            <button key={e.elder_id} className="elder-card" onClick={() => setPicked(e)}>
              <div className="elder-face">{e.name?.slice(0, 1)}</div>
              <div className="elder-info">
                <b>{e.name}</b>
                <small>{e.preferred_call_name ?? ""}</small>
              </div>
              <span className="chev">›</span>
            </button>
          ))}
        </div>

        {adding ? (
          <div className="add-elder">
            <label className="block">
              어르신 성함
              <input
                autoFocus
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && submitElder()}
              />
            </label>
            <div className="field-grid">
              <label>
                부르는 호칭
                <input
                  value={form.preferred_call_name}
                  onChange={(e) =>
                    setForm({ ...form, preferred_call_name: e.target.value })
                  }
                />
              </label>
              <label>
                통화할 가족
                <input
                  placeholder="대웅"
                  value={form.persona_name}
                  onChange={(e) => setForm({ ...form, persona_name: e.target.value })}
                />
              </label>
            </div>
            <div className="add-actions">
              <button className="save" onClick={submitElder} disabled={!form.name.trim()}>
                등록
              </button>
              <button className="text-link" onClick={() => setAdding(false)}>
                취소
              </button>
            </div>
          </div>
        ) : (
          <button className="add-card" onClick={() => setAdding(true)}>
            <span className="plus">＋</span> 돌볼 어르신 추가
          </button>
        )}

        {error && <p className="error">{error}</p>}

        <a className="text-link" href="#">
          어르신 화면으로
        </a>
      </div>
    );
  }

  return (
    <div className="guardian">
      <header className="g-head">
        <button className="back" onClick={() => setPicked(null)} aria-label="뒤로">
          ‹
        </button>
        <div className="elder-chip">
          <span className="elder-face sm">{picked.name?.slice(0, 1)}</span>
          <b>{picked.name}</b>
        </div>
        <a className="text-link" href="#">
          어르신 화면
        </a>
      </header>

      <nav className="tabs">
        {MAIN_TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "report" &&
        (summary ? (
          <ReportTabs
            summary={summary}
            days={days}
            onDays={setDays}
            onReload={loadSummary}
          />
        ) : (
          <p className="hint">불러오는 중…</p>
        ))}

      {tab === "memories" && <MemoryPanel />}
      {tab === "plan" && (
        <>
          <ScheduleForm />
          <MedicationForm />
        </>
      )}
      {tab === "setup" && <PersonaPanel />}
    </div>
  );
}
