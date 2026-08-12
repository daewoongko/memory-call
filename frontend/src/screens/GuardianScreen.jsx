import { useCallback, useEffect, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import MemoryPanel from "./MemoryPanel.jsx";
import PersonaPanel from "./PersonaPanel.jsx";
import ReportTabs from "./ReportTabs.jsx";

/**
 * 보호자 화면.
 *
 * 돌볼 대상을 먼저 고르고, 그 사람의 리포트를 카테고리별로 본다.
 * 명세 FR-11/12 — 진단하지 않고 관찰된 사실만 전달한다.
 */

const MAIN_TABS = [
  { id: "report", label: "케어 리포트", icon: "▦" },
  { id: "memories", label: "가족 기억", icon: "◇" },
  { id: "setup", label: "AI 가족 설정", icon: "⚙" },
];

function localDateKey(date = new Date()) {
  return [
    date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function selectedRange(period) {
  if (period.mode === "day") {
    return { days: 1, start: period.value, end: period.value };
  }
  const [year, month] = period.value.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  const monthEnd = `${period.value}-${String(lastDay).padStart(2, "0")}`;
  const today = localDateKey();
  const end = period.value === today.slice(0, 7) ? today : monthEnd;
  return {
    days: Math.max(1, Math.round((new Date(end) - new Date(`${period.value}-01`)) / 86400000) + 1),
    start: `${period.value}-01`,
    end,
  };
}

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
  const [period, setPeriod] = useState(() => ({
    mode: "month", value: localDateKey().slice(0, 7),
  }));
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");

  const loadSummary = useCallback(
    () => {
      if (!picked) return null;
      const range = selectedRange(period);
      return api.getPeriodSummary(range.days, picked.elder_id, range)
        .then(setSummary).catch((e) => setError(e.message));
    },
    [period, picked]
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
                  placeholder="민준"
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

        <a className="text-link" href="#elder">
          어르신 화면으로
        </a>
      </div>
    );
  }

  const current = MAIN_TABS.find((item) => item.id === tab);

  return (
    <div className="guardian guardian-dashboard">
      <div className="guardian-shell">
        <aside className="guardian-sidebar">
          <div className="sidebar-brand">
            <BrandMark size={32} />
            <div><b>다소니</b><span>가족 케어 센터</span></div>
          </div>

          <button className="sidebar-elder" onClick={() => setPicked(null)}>
            <span className="elder-face sm">{picked.name?.slice(0, 1)}</span>
            <span><b>{picked.name}</b><small>{picked.preferred_call_name ?? "돌봄 대상"}</small></span>
            <i>⌄</i>
          </button>

          <nav className="sidebar-nav" aria-label="보호자 메뉴">
            {MAIN_TABS.map((item) => (
              <button key={item.id} className={tab === item.id ? "on" : ""} onClick={() => setTab(item.id)}>
                <span aria-hidden="true">{item.icon}</span>{item.label}
              </button>
            ))}
          </nav>

          <div className="sidebar-foot">
            <p>기억과 현재를 연결하는<br />AI 인지·정서 케어</p>
            <a href="#elder">어르신 화면으로</a>
          </div>
        </aside>

        <main className="guardian-workspace">
          <header className="dashboard-heading">
            <div>
              <p className="eyebrow">{picked.name} 어르신</p>
              <h1>{current?.label}</h1>
              <span>통화에서 관찰된 사실을 근거와 함께 확인합니다.</span>
            </div>
          </header>

          {error && <p className="error">{error}</p>}
          {tab === "report" &&
            (summary ? (
              <ReportTabs
                elderId={picked.elder_id}
                elderName={picked.name}
                summary={summary}
                days={summary.days}
                period={period}
                onPeriod={setPeriod}
                onReload={loadSummary}
              />
            ) : <p className="hint">리포트를 불러오는 중…</p>)}
          {tab === "memories" && <MemoryPanel elderId={picked.elder_id} elderName={picked.name} />}
          {tab === "setup" && <PersonaPanel />}
        </main>
      </div>
    </div>
  );
}
