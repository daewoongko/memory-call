import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import { useIncomingCall } from "../useIncomingCall.js";
import GuardianCallOverlay from "./GuardianCallOverlay.jsx";
import FamilyMemoryClothesline from "./FamilyMemoryClothesline.jsx";
import FamilyPersonaSettings from "./FamilyPersonaSettings.jsx";
import CallTranscriptModal from "./CallTranscriptModal.jsx";

const TABS = [
  { id: "today", mark: "♥", label: "오늘" },
  { id: "memories", mark: "◇", label: "가족 추억함" },
  { id: "calls", mark: "◷", label: "통화" },
  { id: "settings", mark: "⚙", label: "설정" },
];

function localDateKey(date = new Date()) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function shortDate(value) {
  if (!value) return "날짜 미확인";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
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

const CALL_TYPES = {
  direct: { label: "내가 직접 통화", mark: "나" },
  ai: { label: "AI가 대신 통화", mark: "AI" },
  ai_to_direct: { label: "AI 통화 후 직접 연결", mark: "연결" },
};

const CALL_PERIODS = [
  { id: "morning", label: "오전", range: "00–12시", includes: (hour) => hour < 12 },
  { id: "afternoon", label: "오후", range: "12–18시", includes: (hour) => hour >= 12 && hour < 18 },
  { id: "evening", label: "저녁", range: "18–24시", includes: (hour) => hour >= 18 },
];

function periodForCall(call) {
  const date = new Date(call.started_at);
  const hour = Number.isNaN(date.getTime()) ? 0 : date.getHours();
  return CALL_PERIODS.find((period) => period.includes(hour))?.id || "morning";
}

export default function ChildScreen({ elderId = "elder_001", myPersonaId = "", onMyPersonaChange }) {
  const [picked, setPicked] = useState(null);
  const [selectedDate, setSelectedDate] = useState(() => localDateKey());
  const [summary, setSummary] = useState(null);
  const [memories, setMemories] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [calls, setCalls] = useState([]);
  const [tab, setTab] = useState("today");
  const [callFilter, setCallFilter] = useState("all");
  const [expandedCallPeriods, setExpandedCallPeriods] = useState({});
  const [activeCall, setActiveCall] = useState(null);
  const [connected, setConnected] = useState(null);
  const [callBusy, setCallBusy] = useState(false);
  const [callError, setCallError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const todayKey = localDateKey();

  useEffect(() => {
    let alive = true;
    setPicked(null);
    api.getElders().then(({ elders: rows = [] }) => {
      if (!alive) return;
      const linkedElder = rows.find((elder) => elder.elder_id === elderId);
      setPicked(linkedElder || (elderId === "elder_001" ? rows[0] : null) || null);
      if (!linkedElder && elderId !== "elder_001") setError("연결된 어르신 정보를 찾지 못했습니다. 연결 코드를 다시 확인해 주세요.");
    }).catch((reason) => alive && setError(reason.message));
    return () => { alive = false; };
  }, [elderId]);

  useEffect(() => {
    if (!picked) return;
    let alive = true;
    setLoading(true);
    setError("");
    Promise.all([
      api.getPeriodSummary(1, picked.elder_id, { start: selectedDate, end: selectedDate }),
      api.getMemories(picked.elder_id),
      api.getPersonas(picked.elder_id),
      api.getReports(picked.elder_id, 120),
    ]).then(([nextSummary, memoryData, personaData, reportData]) => {
      if (!alive) return;
      setSummary(nextSummary);
      setMemories(memoryData.memories || []);
      setPersonas(personaData.personas || []);
      setCalls((reportData.calls || []).filter((call) => String(call.started_at || "").slice(0, 10) === selectedDate));
    }).catch((reason) => alive && setError(reason.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [picked, selectedDate]);

  const latest = (summary?.daily_reports || []).find((day) => day.date === selectedDate) || null;
  const heart = latest?.heart_report;
  const verifiedMemories = useMemo(() => memories.filter((memory) => memory.status === "verified"), [memories]);
  const artwork = useMemo(() => verifiedMemories.find((memory) => memory.artwork?.status === "approved" && memoryImage(memory))
    || verifiedMemories.find((memory) => memoryImage(memory)) || verifiedMemories[0], [verifiedMemories]);
  const readyPersonas = useMemo(() => personas.filter((item) => item.ready), [personas]);
  const myPersona = useMemo(() => readyPersonas.find((item) => item.persona_id === myPersonaId)
    || (readyPersonas.length === 1 ? readyPersonas[0] : null), [readyPersonas, myPersonaId]);
  const dayHeartPhoto = heart?.memory_banner?.image_url || heart?.visual_story?.image_url || "";
  const heartLabel = heart?.missed_word?.label || "마음";
  const heartQuote = heart?.missed_word?.quote || heart?.memory_banner?.quote
    || heart?.visual_story?.source_quote || artwork?.description || "가족과 나눈 이야기가 안전하게 정리되었습니다.";
  const heartPhotos = useMemo(() => {
    const ordered = [
      ...(dayHeartPhoto ? [{ photo_url: dayHeartPhoto, title: `${shortDate(selectedDate)} 마음 기록` }] : []),
      artwork,
      ...verifiedMemories.filter((memory) => memory !== artwork),
    ]
      .map((memory) => ({ src: memoryImage(memory), alt: memory?.title || "가족 추억" }))
      .filter((item) => item.src);
    readyPersonas.forEach((persona) => {
      if (persona.face) ordered.push({ src: persona.face, alt: `${persona.display_name} 가족 사진` });
    });
    return ordered.filter((item, index, rows) => rows.findIndex((row) => row.src === item.src) === index).slice(0, 13);
  }, [dayHeartPhoto, selectedDate, artwork, verifiedMemories, readyPersonas]);
  const urgent = (latest?.risks || []).filter((risk) => !risk.acknowledged);
  const hasCalls = Boolean((summary?.calls || 0) > 0);
  const callTypeCounts = useMemo(() => calls.reduce((counts, call) => {
    const type = CALL_TYPES[call.call_type] ? call.call_type : "ai";
    counts[type] += 1;
    return counts;
  }, { direct: 0, ai: 0, ai_to_direct: 0 }), [calls]);
  const filteredCalls = useMemo(() => callFilter === "all"
    ? calls
    : calls.filter((call) => (call.call_type || "ai") === callFilter), [calls, callFilter]);
  const callPeriods = useMemo(() => CALL_PERIODS.map((period) => ({
    ...period,
    calls: filteredCalls.filter((call) => periodForCall(call) === period.id),
  })), [filteredCalls]);

  // 통화 중에는 폴링을 멈춘다. 이미 받은 벨을 다시 물고 올 이유가 없다.
  // listening 은 "지금 실제로 벨을 받을 수 있는가"다. 등록된 것과는 다르다.
  const {
    invite: incomingInvite, listening, error: ringError, answer, decline,
  } = useIncomingCall({
    elderId: picked?.elder_id || elderId,
    personaId: myPersonaId,
    enabled: Boolean(picked) && Boolean(myPersonaId) && !connected,
  });

  const connectedId = connected?.invite_id;
  useEffect(() => {
    if (!connectedId) return undefined;
    let alive = true;
    let timer = null;
    const tick = async () => {
      if (!alive) return;
      try {
        const current = await api.getInvite(connectedId);
        if (!alive) return;
        if (current.state === "ended" || current.state === "cancelled") {
          setConnected(null);
          return;
        }
      } catch {
        // 잠깐의 통신 오류로 진행 중인 통화 화면을 먼저 닫지 않는다.
      }
      if (alive) timer = setTimeout(tick, 2000);
    };
    timer = setTimeout(tick, 2000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [connectedId]);

  const handleAnswer = useCallback(async (inviteId) => {
    setCallBusy(true);
    setCallError("");
    try {
      setConnected(await answer(inviteId));
    } catch (reason) {
      setCallError(`전화를 받지 못했어요. (${reason.message})`);
    } finally {
      setCallBusy(false);
    }
  }, [answer]);

  const handleDecline = useCallback(async (inviteId) => {
    setCallBusy(true);
    setCallError("");
    try {
      await decline(inviteId);
    } catch (reason) {
      setCallError(reason.message);
    } finally {
      setCallBusy(false);
    }
  }, [decline]);

  const handleEnd = useCallback(async () => {
    if (!connected) return;
    setCallBusy(true);
    try {
      await api.endInvite(connected.invite_id);
    } catch {
      // 어르신 쪽에서 이미 종료했더라도 이 화면은 정상적으로 닫는다.
    } finally {
      setConnected(null);
      setCallBusy(false);
    }
  }, [connected]);

  if (!picked) return <main className="child-screen child-loading"><BrandMark size={42} /><p className={error ? "error" : "hint"}>{error || "연결된 어르신의 가족 소식을 불러오는 중…"}</p></main>;

  return <main className="child-screen">
    <GuardianCallOverlay
      invite={incomingInvite}
      connected={connected}
      elderName={picked.name}
      onAnswer={handleAnswer}
      onDecline={handleDecline}
      onEnd={handleEnd}
      busy={callBusy}
      error={callError || ringError}
    />
    <header className="child-header child-family-header">
      <div className="child-brand"><BrandMark size={34} /><div><b>다소니</b><span>가족 안심 소식</span></div></div>
      <div className="child-header-context">
        <strong className="child-elder-name">{picked.name} 어르신</strong>
        <label className="child-date-picker"><span>날짜</span><input type="date" value={selectedDate} max={todayKey} onChange={(event) => setSelectedDate(event.target.value)} /></label>
      </div>
    </header>

    <div className="child-app-body">
      <nav className="child-tabs" aria-label="가족 화면 메뉴">{TABS.map((item) => <button key={item.id} className={tab === item.id ? "on" : ""} onClick={() => setTab(item.id)}><span className="child-tab-mark" aria-hidden="true">{item.mark}</span><b>{item.label}</b></button>)}</nav>
      <section className="child-view">
        {loading && <div className="child-loading-bar"><i /></div>}

        {tab === "today" && <section className="child-today">
          <article className="child-heart-story">
            <header><span>{shortDate(selectedDate)}</span><h1>오늘, 마음에 남은 순간</h1></header>
            <div className={`child-heart-collage photos-${Math.min(heartPhotos.length, 13)}`} aria-label={`${heartPhotos.length}장의 사진으로 만든 추억 하트`}>
              {heartPhotos.map((photo, index) => <figure className={`heart-photo heart-photo-${index + 1}${index === 0 ? " main" : ""}`} key={`${photo.src}-${index}`}><img src={photo.src} alt={photo.alt} loading={index > 0 ? "lazy" : "eager"} /></figure>)}
              {!heartPhotos.length && <div className="child-heart-empty"><b>♡</b><span>가족 추억함에 사진을 걸면<br />오늘의 하트가 채워져요.</span></div>}
            </div>
            <div className="child-heart-quote"><span>{hasCalls ? `${heartLabel}이 담긴 한마디` : "오늘의 한마디"}</span><blockquote>“{hasCalls ? heartQuote : "이날은 아직 통화에서 남은 한마디가 없어요."}”</blockquote></div>
          </article>
          {urgent.length > 0 && <details className="child-alert"><summary><b>가족이 직접 확인할 이야기</b><span>{urgent.length}건 · 펼쳐보기</span></summary>{urgent.map((risk) => <p key={risk.event_id}>“{risk.evidence}”라는 말씀이 있었습니다. 현재 상태를 직접 확인해 주세요.</p>)}</details>}
        </section>}

        {tab === "memories" && <section className="child-memory-page">
          <FamilyMemoryClothesline elderId={picked.elder_id} elderName={picked.name} />
        </section>}

        {tab === "calls" && <section className="child-call-page">
          <header className="child-section-heading child-call-heading"><div><span>CALL STORY</span><h1>{shortDate(selectedDate)} 통화 이야기</h1><p>{calls.length}통 · {duration(calls.reduce((sum, call) => sum + (call.duration_sec || 0), 0))}</p></div></header>
          <nav className="child-call-filters" aria-label="통화 유형 필터">
            <button type="button" className={callFilter === "all" ? "on" : ""} onClick={() => setCallFilter("all")}><i aria-hidden="true">전체</i><span>모든 통화</span><b>{calls.length}</b></button>
            {Object.entries(CALL_TYPES).map(([type, meta]) => <button type="button" key={type} className={`${type} ${callFilter === type ? "on" : ""}`} onClick={() => setCallFilter(type)}><i aria-hidden="true">{meta.mark}</i><span>{meta.label}</span><b>{callTypeCounts[type]}</b></button>)}
          </nav>
          <div className="child-call-period-board">
            {callPeriods.map((period) => {
              const directCalls = period.calls.filter((call) => call.call_type === "direct");
              const otherCalls = period.calls.filter((call) => call.call_type !== "direct");
              const collapsedCalls = [...directCalls, ...otherCalls.slice(0, Math.max(0, 3 - directCalls.length))]
                .sort((left, right) => String(left.started_at).localeCompare(String(right.started_at)));
              const visibleCalls = expandedCallPeriods[period.id] ? period.calls : collapsedCalls;
              const hiddenCount = period.calls.length - visibleCalls.length;
              const seconds = period.calls.reduce((sum, call) => sum + (call.duration_sec || 0), 0);
              return <section className="child-call-period" key={period.id}>
                <header><div><span>{period.range}</span><h2>{period.label}</h2></div><p><b>{period.calls.length}</b>통 · {duration(seconds)}</p></header>
                <div className="child-call-card-grid">
                  {visibleCalls.map((call) => {
                    const type = CALL_TYPES[call.call_type] || CALL_TYPES.ai;
                    const needsAttention = Number(call.risk_count || 0) > 0;
                    return <button type="button" className={`child-call-card ${call.call_type || "ai"}${needsAttention ? " problem" : ""}`} key={call.call_id} onClick={() => setActiveCall(call)}>
                      <span className={`child-call-type-badge ${call.call_type || "ai"}`}><i aria-hidden="true">{type.mark}</i>{type.label}</span>
                      <time>{shortTime(call.started_at)}<small>{duration(call.duration_sec)}</small></time>
                      <h3>{call.report_title || call.summary || "가족과 나눈 통화"}</h3>
                      <p>{call.summary || (call.meaning_count ? `가족에게 전할 순간 ${call.meaning_count}건` : "대화 내용을 확인해 보세요.")}</p>
                      <footer>
                        <span>{call.counterpart_name || "가족"}</span>
                        <em>{needsAttention ? `확인 필요 ${call.risk_count}` : call.repeat_count ? `반복 ${call.repeat_count}` : call.meaning_count ? `마음 ${call.meaning_count}` : "대화 보기"}</em>
                      </footer>
                    </button>;
                  })}
                  {!period.calls.length && <p className="child-call-period-empty">이 시간대에는 통화가 없어요.</p>}
                </div>
                {hiddenCount > 0 && <button type="button" className="child-call-more" onClick={() => setExpandedCallPeriods((current) => ({ ...current, [period.id]: true }))}>{hiddenCount}통 더 보기 <span>↓</span></button>}
                {expandedCallPeriods[period.id] && period.calls.length > collapsedCalls.length && <button type="button" className="child-call-more" onClick={() => setExpandedCallPeriods((current) => ({ ...current, [period.id]: false }))}>간단히 보기 <span>↑</span></button>}
              </section>;
            })}
            {!calls.length && <div className="child-empty-card"><b>이날은 정리된 통화가 없어요</b><p>다른 날짜를 선택하면 그날의 통화 이야기를 확인할 수 있어요.</p></div>}
          </div>
          <CallTranscriptModal call={activeCall} elderName={picked.name} onClose={() => setActiveCall(null)} />
        </section>}

        {tab === "settings" && <section className="child-family-settings">
          {/* 이 폰이 지금 벨을 받을 수 있는지. 폴링이 곧 신고이므로 화면이
              꺼지면 함께 꺼진다. 보호자가 손에 든 폰을 두고 실제로 갖는
              질문이라 설정 맨 위에 둔다. */}
          <div className="family-reachable">
            <b className={listening ? "device-live" : "device-idle"}>
              {listening ? "지금 전화를 받을 수 있어요" : "지금은 AI 가 대신 받습니다"}
            </b>
            <p>
              {listening
                ? "화면을 켜 두면 어르신의 전화가 이 폰으로 옵니다."
                : "화면이 꺼져 있거나 가족을 고르지 않으면 벨이 오지 않습니다."}
            </p>
          </div>

          {!myPersona && readyPersonas.length > 1 ? <div className="family-legacy-picker">
            <header><span>내 프로필 선택</span><h1>통화에서 사용할 나를 선택해 주세요</h1></header>
            <div>{readyPersonas.map((persona) => <button type="button" key={persona.persona_id} onClick={() => onMyPersonaChange?.(persona.persona_id)}>{persona.face ? <img src={persona.face} alt="" /> : <i>{persona.display_name?.slice(0, 1)}</i>}<b>{persona.display_name}</b><small>{persona.relationship}</small></button>)}</div>
          </div> : <FamilyPersonaSettings elderId={picked.elder_id} personaId={myPersona?.persona_id || ""} summary={myPersona} />}
        </section>}
        {error && <p className="error">일부 정보를 불러오지 못했습니다. ({error})</p>}
      </section>
    </div>
  </main>;
}
