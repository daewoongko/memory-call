import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import MemoryPanel from "./MemoryPanel.jsx";
import PersonaPanel from "./PersonaPanel.jsx";

const TABS = [
  { id: "today", mark: "오늘", label: "오늘" },
  { id: "memories", mark: "기억", label: "가족 기억" },
  { id: "calls", mark: "통화", label: "통화" },
  { id: "settings", mark: "설정", label: "설정" },
];

function shortDate(value) {
  if (!value) return "날짜 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
}

function shortTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function duration(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}분 ${rest}초` : `${rest}초`;
}

function memoryImage(memory) {
  return memory?.artwork?.image_url || memory?.image_url || memory?.photo_url || "";
}

export default function ChildScreen() {
  const [elders, setElders] = useState([]);
  const [picked, setPicked] = useState(null);
  const [summary, setSummary] = useState(null);
  const [memories, setMemories] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [calls, setCalls] = useState([]);
  const [tab, setTab] = useState("today");
  const [advanced, setAdvanced] = useState(false);
  const [memoryManagerOpen, setMemoryManagerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getElders().then(({ elders: rows }) => {
      setElders(rows);
      if (rows.length) setPicked(rows[0]);
    }).catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!picked) return;
    let alive = true;
    setLoading(true);
    setError("");
    Promise.all([
      api.getPeriodSummary(7, picked.elder_id),
      api.getMemories(picked.elder_id),
      api.getPersonas(picked.elder_id),
      api.getReports(picked.elder_id, 30),
    ]).then(([nextSummary, memoryData, personaData, reportData]) => {
      if (!alive) return;
      setSummary(nextSummary);
      setMemories(memoryData.memories || []);
      setPersonas((personaData.personas || []).filter((item) => item.ready));
      setCalls(reportData.calls || []);
    }).catch((reason) => alive && setError(reason.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [picked]);

  const latest = [...(summary?.daily_reports || [])].reverse().find((day) => day.calls > 0)
    || summary?.daily_reports?.at(-1);
  const heart = latest?.heart_report;
  const verifiedMemories = useMemo(() => memories.filter((memory) => memory.status === "verified"), [memories]);
  const artwork = useMemo(() => verifiedMemories.find((memory) => memory.artwork?.status === "approved" && memoryImage(memory))
    || verifiedMemories.find((memory) => memoryImage(memory))
    || verifiedMemories[0], [verifiedMemories]);
  const image = memoryImage(artwork) || personas[0]?.face;
  const urgent = (latest?.risks || []).filter((risk) => !risk.acknowledged);
  const familyAction = latest?.guardian_actions?.[0] || "짧게 안부 전화를 건네보세요.";
  const todayLabel = new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "long" });

  if (!picked) return <main className="child-screen child-loading"><BrandMark size={42} /><p className={error ? "error" : "hint"}>{error || "가족 소식을 불러오는 중…"}</p></main>;

  return <main className="child-screen">
    <header className="child-header">
      <div className="child-brand"><BrandMark size={34} /><div><b>다소니</b><span>가족 안심 소식</span></div></div>
      <div className="child-header-context"><span>{todayLabel}</span>{elders.length > 1 ? <select value={picked.elder_id} onChange={(event) => setPicked(elders.find((elder) => elder.elder_id === event.target.value))}>{elders.map((elder) => <option key={elder.elder_id} value={elder.elder_id}>{elder.name} 어르신</option>)}</select> : <strong className="child-elder-name">{picked.name} 어르신</strong>}</div>
    </header>

    <div className="child-app-body">
      <nav className="child-tabs" aria-label="가족 화면 메뉴">{TABS.map((item) => <button key={item.id} className={tab === item.id ? "on" : ""} onClick={() => setTab(item.id)}><span>{item.mark}</span><b>{item.label}</b></button>)}</nav>

      <section className="child-view">
        {loading && <div className="child-loading-bar"><i /></div>}

        {tab === "today" && <section className="child-today">
          <article className="child-memory-hero">
            {image ? <img src={image} alt={artwork?.artwork?.alt_text || artwork?.title || "가족 기억"} /> : <div className="child-memory-placeholder">가족의 사진을 기다리고 있어요</div>}
            <div className="child-memory-shade" />
            <div className="child-memory-copy"><span>{shortDate(latest?.date)} · 오늘 가족에게 전한 마음</span><h1>{heart?.label ? `${heart.label}이 담긴 한마디` : "오늘 나눈 이야기를 전해드려요"}</h1><blockquote>“{heart?.quote || artwork?.description || "오늘은 편안하게 가족과 이야기를 나누셨어요."}”</blockquote></div>
          </article>

          <div className="child-today-bento">
            <article className="child-message-card"><span>오늘의 이야기</span><h2>{heart?.message || "어르신께서 직접 하신 말씀을 있는 그대로 전해드려요."}</h2><p>표현하지 않은 감정은 추측하지 않고 실제 말씀과 확인된 기억만 사용합니다.</p></article>
            <article className="child-action-card"><span>가족이 해볼 일 하나</span><h2>{familyAction}</h2><button onClick={() => setTab("memories")}>함께 볼 기억 고르기 <i>↗</i></button></article>
            <article className="child-week-card"><span>최근 7일</span><div><b>{summary?.calls || 0}<small>통화</small></b><b>{Math.round((summary?.total_seconds || 0) / 60)}<small>분</small></b><b>{summary?.meaningful_total || 0}<small>마음 기록</small></b></div></article>
          </div>

          {urgent.length > 0 && <details className="child-alert"><summary><b>가족이 직접 확인할 이야기</b><span>{urgent.length}건 · 펼쳐보기</span></summary>{urgent.map((risk) => <p key={risk.event_id}>“{risk.evidence}”라는 말씀이 있었습니다. 현재 상태를 직접 확인해 주세요.</p>)}</details>}

          <section className="child-family-row"><header><div><span>함께하는 AI 가족</span><h2>익숙한 얼굴로 곁을 지켜요</h2></div><button onClick={() => setTab("settings")}>가족 설정</button></header><div>{personas.map((persona) => <figure key={persona.persona_id}>{persona.face ? <img src={persona.face} alt="" /> : <span>{persona.display_name?.slice(0, 1)}</span>}<figcaption><b>{persona.display_name}</b><small>{persona.relationship}</small></figcaption></figure>)}</div></section>
        </section>}

        {tab === "memories" && <section className="child-memory-page">
          <header className="child-section-heading"><div><span>FAMILY MEMORY</span><h1>가족이 함께 기억하고 있어요</h1><p>확인된 사진과 이야기는 다음 통화에서 어르신의 현재와 추억을 잇는 단서가 됩니다.</p></div><button onClick={() => setMemoryManagerOpen((value) => !value)}>{memoryManagerOpen ? "간단히 보기" : "기억 추가·관리"}</button></header>
          {!memoryManagerOpen && <div className="child-memory-gallery">{verifiedMemories.slice(0, 12).map((memory, index) => <article key={memory.memory_id || index} className={index === 0 ? "featured" : ""}>{memoryImage(memory) ? <img src={memoryImage(memory)} alt={memory.artwork?.alt_text || memory.title || "가족 기억"} /> : <div className="memory-color-placeholder">기억</div>}<div><span>{memory.date_text || memory.location || "가족 기록"}</span><h2>{memory.title || "소중한 가족 이야기"}</h2><p>{memory.description || memory.story || "가족이 확인한 기억입니다."}</p></div></article>)}{!verifiedMemories.length && <div className="child-empty-card"><b>아직 확인된 가족 기억이 없어요</b><p>사진 한 장과 짧은 이야기를 등록하면 통화와 마음 리포트에 연결할 수 있어요.</p><button onClick={() => setMemoryManagerOpen(true)}>첫 기억 등록하기</button></div>}</div>}
          {memoryManagerOpen && <MemoryPanel elderId={picked.elder_id} elderName={picked.name} />}
        </section>}

        {tab === "calls" && <section className="child-call-page">
          <header className="child-section-heading"><div><span>CALL STORY</span><h1>통화에서 남은 이야기</h1><p>수치보다 어떤 말을 남겼는지 먼저 보여드려요.</p></div></header>
          <div className="child-call-summary"><article><span>최근 7일 통화</span><b>{summary?.calls || 0}회</b></article><article><span>함께 이야기한 시간</span><b>{Math.round((summary?.total_seconds || 0) / 60)}분</b></article><article><span>반복해서 나온 말</span><b>{summary?.repeat_total || 0}회</b></article></div>
          <div className="child-call-list">{calls.slice(0, 12).map((call) => <article key={call.call_id}><time><b>{shortDate(call.started_at)}</b><span>{shortTime(call.started_at)}</span></time><div><span>{call.counterpart_name || "AI 가족"} · {call.counterpart_relation || "가족"}</span><h2>{call.report_title || call.summary || "가족과 나눈 통화"}</h2><p>{call.meaning_count ? `가족에게 전할 순간 ${call.meaning_count}건` : "통화 기록이 안전하게 정리되었습니다."}</p></div><strong>{duration(call.duration_sec)}</strong></article>)}{!calls.length && <div className="child-empty-card"><b>아직 정리된 통화가 없어요</b><p>통화가 끝나면 중요한 말씀과 가족이 확인할 일이 이곳에 쌓입니다.</p></div>}</div>
        </section>}

        {tab === "settings" && <section className="child-family-settings">
          <header className="child-section-heading"><div><span>AI FAMILY</span><h1>통화에 등장할 가족이에요</h1><p>가족의 얼굴과 관계를 먼저 확인하고 필요한 경우에만 말투를 세밀하게 조정하세요.</p></div></header>
          <div className="child-family-cards">{personas.map((persona) => <article key={persona.persona_id}>{persona.face ? <img src={persona.face} alt="" /> : <span>{persona.display_name?.slice(0, 1)}</span>}<div><b>{persona.display_name}</b><small>{persona.relationship}</small><i>{persona.call_style_code || "CPOG · 기본 안심 말투"}</i></div><em>통화 준비 완료</em></article>)}</div>
          <div className="child-setting-note"><span>안전한 기본값</span><div><b>차분하고 공감하는 안내형 말투</b><p>설정을 생략해도 반박하지 않고 한 번에 한 가지씩 안내하는 기본 말투가 적용됩니다.</p></div></div>
          <button className="child-advanced-button" onClick={() => setAdvanced((value) => !value)}>{advanced ? "세부 설정 닫기" : "사진·말투 세부 설정"}</button>
          {advanced && <PersonaPanel />}
        </section>}

        {error && <p className="error">일부 정보를 불러오지 못했습니다. ({error})</p>}
      </section>
    </div>
  </main>;
}
