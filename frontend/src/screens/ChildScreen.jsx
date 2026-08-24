import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import { useIncomingCall } from "../useIncomingCall.js";
import GuardianCallOverlay from "./GuardianCallOverlay.jsx";
import FamilyMemoryClothesline from "./FamilyMemoryClothesline.jsx";
import FamilyPersonaSettings from "./FamilyPersonaSettings.jsx";
import CallTranscriptModal from "./CallTranscriptModal.jsx";
import DasoniHomeTab from "./DasoniHomeTab.jsx";
import { useCallMediaReadiness } from "../useCallMediaReadiness.js";
import { useScreenWakeLock } from "../useScreenWakeLock.js";
import AppDatePicker from "../components/AppDatePicker.jsx";

function TabGlyph({ children }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
}

const TABS = [
  { id: "today", mark: <TabGlyph><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" /></TabGlyph>, label: "오늘" },
  { id: "memories", mark: <TabGlyph><path d="M12 3l9 9-9 9-9-9z" /></TabGlyph>, label: "추억함" },
  { id: "calls", mark: <TabGlyph><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" /></TabGlyph>, label: "통화" },
  { id: "settings", mark: <TabGlyph><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></TabGlyph>, label: "설정" },
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

function withTopicParticle(word = "어르신") {
  const last = [...word.trim()].at(-1) || "";
  const code = last.charCodeAt(0) - 0xAC00;
  const hasFinalConsonant = code >= 0 && code <= 11171 && code % 28 > 0;
  return `${word}${hasFinalConsonant ? "은" : "는"}`;
}

function memoryImage(memory) {
  return memory?.artwork?.image_url || memory?.image_url || memory?.photo_url || "";
}

const CALL_TYPES = {
  direct: { label: "가족이 직접 통화", filterLabel: "가족 직접", mark: "나" },
  ai: { label: "다소니가 대신 통화", filterLabel: "다소니 AI", mark: "AI" },
  ai_to_direct: { label: "AI 통화 후 가족이 이어받음", filterLabel: "이어받음", mark: "연결" },
};

const DEMO_DIARIES = [
  {
    date: "2026-07-12",
    image: "/diary/country-market-memory.png",
    title: "아버지와 걷던 장날",
    writing: "여름 장터에서 아버지와 복숭아를 골랐다. 집으로 돌아오는 길에 나란히 걷던 시간이 참 든든했다.",
    insight: "아버지는 가족과 함께 장터를 걷던 평범한 시간이 오래도록 따뜻하게 남아 있는 것 같아.",
    weather: "포근함",
  },
  {
    date: "2026-08-08",
    image: "/diary/persimmon-yard-memory.png",
    title: "감나무 아래의 오후",
    writing: "마당 감나무 아래에서 어린 정훈이에게 잘 익은 감을 건넸다. 아이가 웃는 모습을 보며 함께 웃었다.",
    insight: "아버지는 어린 정훈이에게 감을 건네주던 순간을 떠올릴 때 마음이 한결 편안해지는 것 같아.",
    weather: "따뜻함",
  },
  {
    date: "2026-08-24",
    image: "/diary/haeundae-family-drawing.png",
    title: "고향 집 앞 냇가",
    writing: "젊은 시절 살던 고향 집 앞에 냇가가 있었고, 가족과 그 시절 이야기를 나누었습니다.",
    insight: "할아버지의 가장 따뜻한 기억엔\n언제나 대웅이가 함께 있어.",
    weather: "맑음",
  },
  {
    date: "2026-09-05",
    image: "/diary/autumn-riverside-picnic.png",
    title: "가을 강가의 소풍",
    writing: "가을 강가에서 딸과 손주들과 김밥을 나누어 먹었다. 물소리를 들으며 오래 이야기를 나누었다.",
    insight: "할아버지는 온 가족이 둘러앉아 음식을 나누던 가을 소풍을 무척 소중하게 기억하시는 것 같아.",
    weather: "다정함",
  },
];

export default function ChildScreen({ elderId = "elder_001", myPersonaId = "", onMyPersonaChange, onDisplaySettings }) {
  const [picked, setPicked] = useState(null);
  const [selectedDate, setSelectedDate] = useState(() => localDateKey());
  const [summary, setSummary] = useState(null);
  const [memories, setMemories] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [calls, setCalls] = useState([]);
  const [elderCallName, setElderCallName] = useState("어르신");
  const [tab, setTab] = useState("home");
  const [callFilter, setCallFilter] = useState("all");
  const [activeCall, setActiveCall] = useState(null);
  const [connected, setConnected] = useState(null);
  const [callBusy, setCallBusy] = useState(false);
  const [callError, setCallError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const todayKey = localDateKey();
  const callMedia = useCallMediaReadiness();

  useScreenWakeLock(Boolean(picked) && Boolean(myPersonaId) && callMedia.ready);

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
      api.getReports(picked.elder_id, 120, selectedDate),
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
  const demoDiary = DEMO_DIARIES.find((entry) => entry.date === selectedDate) || null;
  const heart = latest?.heart_report;
  const verifiedMemories = useMemo(() => memories.filter((memory) => memory.status === "verified"), [memories]);
  const artwork = useMemo(() => verifiedMemories.find((memory) => memory.artwork?.status === "approved" && memoryImage(memory))
    || verifiedMemories.find((memory) => memoryImage(memory)) || verifiedMemories[0], [verifiedMemories]);
  const readyPersonas = useMemo(() => personas.filter((item) => item.ready), [personas]);
  const myPersona = useMemo(() => readyPersonas.find((item) => item.persona_id === myPersonaId)
    || (readyPersonas.length === 1 ? readyPersonas[0] : null), [readyPersonas, myPersonaId]);

  useEffect(() => {
    if (!picked) return;
    const fallback = picked.preferred_call_name || "어르신";
    setElderCallName(fallback);
    if (!myPersona?.persona_id) return;
    let alive = true;
    api.getProfile(myPersona.persona_id, picked.elder_id)
      .then((profile) => {
        if (alive) setElderCallName(profile?.elder?.call_name || fallback);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [picked, myPersona?.persona_id]);
  const dayHeartPhoto = heart?.memory_banner?.image_url || heart?.visual_story?.image_url || "";
  const heartQuote = heart?.missed_word?.quote || heart?.memory_banner?.quote
    || heart?.visual_story?.source_quote || artwork?.description || "가족과 나눈 이야기가 안전하게 정리되었습니다.";
  const hasCalls = Boolean((summary?.calls || 0) > 0);
  const diaryImage = dayHeartPhoto || memoryImage(artwork);
  const diaryImageAlt = heart?.memory_banner?.alt_text || heart?.visual_story?.alt_text
    || artwork?.title || "오늘의 대표 그림";
  const diaryTitle = heart?.memory_banner?.memory_title || heart?.memory_bridge?.title
    || artwork?.title || "오늘의 마음";
  const diaryArtworkLabel = heart?.visual_story?.status_label
    || (heart?.memory_banner ? "확인된 가족 기억 기반" : diaryImage ? "가족이 확인한 추억" : "");
  const diaryDisplayImage = demoDiary?.image || diaryImage || "/diary/haeundae-family-drawing.png";
  const diaryDisplayAlt = demoDiary ? `${demoDiary.title} 기억을 그린 그림일기 삽화` : diaryImage ? diaryImageAlt : "할아버지와 손자가 해변에서 모래성을 만드는 그림일기 삽화";
  const diaryDisplayTitle = demoDiary?.title || (hasCalls ? diaryTitle : "할아버지와 만든 모래성");
  const diaryTitleFit = Math.min(1, 9 / Math.max(diaryDisplayTitle.replace(/\s/g, "").length, 1));
  const diaryWritingText = (demoDiary?.writing || (hasCalls
    ? heartQuote
    : "2012년 여름 할아버지와 해운대에 갔다. 둘이 모래성을 만들고 파도를 보며 함께 웃었다."))
    .replace(/[“”"]/g, "").trim();
  const familyInsight = demoDiary?.insight || heart?.day_translation?.family
    || `${withTopicParticle(elderCallName)} 대웅이와 갔던 해운대 바다가 아직도 많이 생각나시는 것 같아.`;
  const quotedFamilyInsight = `“${familyInsight.replace(/[“”"]/g, "").trim()}”`;
  const urgent = (latest?.risks || []).filter((risk) => !risk.acknowledged);
  const callTypeCounts = useMemo(() => calls.reduce((counts, call) => {
    const type = CALL_TYPES[call.call_type] ? call.call_type : "ai";
    counts[type] += 1;
    return counts;
  }, { direct: 0, ai: 0, ai_to_direct: 0 }), [calls]);
  const filteredCalls = useMemo(() => callFilter === "all"
    ? calls
    : calls.filter((call) => (call.call_type || "ai") === callFilter), [calls, callFilter]);
  const visibleCalls = useMemo(() => [...filteredCalls]
    .sort((left, right) => String(right.started_at || "").localeCompare(String(left.started_at || ""))), [filteredCalls]);
  const totalCallDuration = useMemo(() => calls.reduce((sum, call) => sum + (call.duration_sec || 0), 0), [calls]);

  // 통화 중에는 폴링을 멈춘다. 이미 받은 벨을 다시 물고 올 이유가 없다.
  // listening 은 "지금 실제로 벨을 받을 수 있는가"다. 등록된 것과는 다르다.
  const {
    invite: incomingInvite, listening, error: ringError, answer, decline,
  } = useIncomingCall({
    elderId: picked?.elder_id || elderId,
    personaId: myPersonaId,
    enabled: Boolean(picked) && Boolean(myPersonaId) && callMedia.ready && !connected,
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
        if (current.state !== "answered") {
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
      if (!callMedia.ready) {
        await decline(inviteId, "media_permission_denied");
        return;
      }
      setConnected(await answer(inviteId));
    } catch (reason) {
      setCallError(`전화를 받지 못했어요. (${reason.message})`);
    } finally {
      setCallBusy(false);
    }
  }, [answer, decline, callMedia.ready]);

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

  const handleTransportFailed = useCallback(() => {
    // 어르신 쪽이 AI 인계를 확정한다. 보호자 화면은 조용히 통화창만 닫는다.
    setConnected(null);
    setCallBusy(false);
  }, []);

  if (!picked) return <main className="child-screen child-loading"><BrandMark size={42} /><p className={error ? "error" : "hint"}>{error || "연결된 어르신의 가족 소식을 불러오는 중…"}</p></main>;

  return <main className="child-screen">
    <GuardianCallOverlay
      invite={incomingInvite}
      connected={connected}
      elderName={picked.name}
      onAnswer={handleAnswer}
      onDecline={handleDecline}
      onEnd={handleEnd}
      onTransportFailed={handleTransportFailed}
      busy={callBusy}
      error={callError || ringError}
    />
    <header className="child-header child-family-header">
      <button type="button" className={`child-brand child-brand-home${tab === "home" ? " on" : ""}`} onClick={() => { setSelectedDate(todayKey); setTab("home"); }} aria-label="다소니 메인 홈으로 이동">
        <BrandMark size={34} />
      </button>
      {tab === "today" && <blockquote className="child-header-diary-note" aria-label="다소니가 전하는 오늘의 한마디"><span>{quotedFamilyInsight}</span></blockquote>}
      {tab === "memories" && <div className="child-header-memory-title"><strong>가족 추억함</strong><span>{picked.name} 어르신과 AI가 함께 이야기할 수 있는 추억을 관리해요.</span></div>}
      {tab === "calls" && <div className="child-header-call-title"><strong>{shortDate(selectedDate)} 통화 이야기</strong><span>{calls.length}통 · {duration(totalCallDuration)}</span></div>}
      {tab === "settings" && <div className="child-header-reachable"><strong className={listening ? "device-live" : "device-idle"}>“{listening ? "지금 전화를 받을 수 있어요" : "지금은 다소니가 대신 받아요"}”</strong><span>{listening ? "화면을 켜 두면 어르신의 전화가 이 폰으로 와요." : "화면을 켜고 기다리면 가족 전화가 다시 연결돼요."}</span></div>}
      {tab === "home" && <div className="child-header-context">
        <strong className="child-elder-name">{picked.name} 어르신</strong>
        <button type="button" className="child-view-settings" onClick={onDisplaySettings} aria-label="글자 크기와 화면 명암 설정">
          <span aria-hidden="true">Aa</span>
        </button>
        <AppDatePicker className="child-date-picker" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
      </div>}
    </header>

    {!callMedia.ready && <section className="media-readiness-panel child-media-readiness" aria-live="polite">
      <div><b>전화 받을 준비</b><p>{callMedia.message}</p></div>
      <button
        className="media-preflight-button"
        onClick={() => callMedia.prepare().catch(() => {})}
        disabled={callMedia.status === "checking"}
      >{callMedia.status === "checking" ? "확인 중…" : "마이크·카메라 허용"}</button>
    </section>}

    <div className="child-app-body">
      <nav className="child-tabs" aria-label="가족 화면 메뉴">{TABS.map((item) => <button key={item.id} className={tab === item.id ? "on" : ""} onClick={() => setTab(item.id)} aria-current={tab === item.id ? "page" : undefined}><span className="child-tab-mark" aria-hidden="true">{item.mark}</span><b>{item.label}</b></button>)}</nav>
      <section className={`child-view${tab === "today" ? " today-view" : ""}`}>
        {loading && <div className="child-loading-bar"><i /></div>}

        {tab === "home" && <DasoniHomeTab
          elderCallName={elderCallName}
          dateLabel={shortDate(selectedDate)}
          callCount={calls.length}
          totalDurationText={duration(totalCallDuration)}
          attentionItems={urgent.map((risk) => ({
            id: risk.event_id,
            label: risk.label || "가족 확인이 필요해요",
            evidence: risk.evidence,
            action: risk.action || "현재 상태를 직접 확인해 주세요.",
          }))}
        />}

        {tab === "today" && <section className="child-today">
          <article className="child-day-diary">
            <header className="child-diary-meta">
              <AppDatePicker
                className="child-diary-date"
                value={selectedDate}
                displayValue={shortDate(selectedDate)}
                showValue
                ariaLabel="그림일기 날짜 선택"
                onChange={(event) => setSelectedDate(event.target.value)}
              />
              <span>오늘의 마음 날씨 · {demoDiary?.weather || "맑음"}</span>
            </header>
            <figure className="child-diary-art">
              <img src={diaryDisplayImage} alt={diaryDisplayAlt} />
              {diaryImage && diaryArtworkLabel && <figcaption>{diaryArtworkLabel}</figcaption>}
            </figure>
            <section className="child-diary-page">
              <header className="child-diary-title-row"><span>제목</span><h1 style={{ "--diary-title-fit": diaryTitleFit }}>{diaryDisplayTitle}</h1></header>
              <div className="child-diary-writing" aria-label={diaryWritingText}>{[...diaryWritingText].map((letter, index) => <span className={letter === " " ? "blank" : ""} aria-hidden="true" key={`${letter}-${index}`}>{letter === " " ? "\u00a0" : letter}</span>)}</div>
            </section>
          </article>
          {urgent.length > 0 && <details className="child-alert"><summary><b>가족이 직접 확인할 이야기</b><span>{urgent.length}건 · 펼쳐보기</span></summary>{urgent.map((risk) => <p key={risk.event_id}>“{risk.evidence}”라는 말씀이 있었습니다. 현재 상태를 직접 확인해 주세요.</p>)}</details>}
        </section>}

        {tab === "memories" && <section className="child-memory-page">
          <FamilyMemoryClothesline elderId={picked.elder_id} elderName={picked.name} />
        </section>}

        {tab === "calls" && <section className="child-call-page">
          <nav className="child-call-filters" aria-label="통화 유형 필터">
            <button type="button" className={callFilter === "all" ? "on" : ""} onClick={() => setCallFilter("all")}><span>전체</span><b>{calls.length}</b></button>
            {Object.entries(CALL_TYPES).map(([type, meta]) => <button type="button" key={type} className={`${type} ${callFilter === type ? "on" : ""}`} onClick={() => setCallFilter(type)}><span>{meta.filterLabel}</span><b>{callTypeCounts[type]}</b></button>)}
          </nav>
          <div className="child-call-list">
            {visibleCalls.map((call) => {
              const type = CALL_TYPES[call.call_type] || CALL_TYPES.ai;
              const needsAttention = Number(call.risk_count || 0) > 0;
              return <button type="button" className={`child-call-list-item ${call.call_type || "ai"}${needsAttention ? " problem" : ""}`} key={call.call_id} onClick={() => setActiveCall(call)}>
                <span className={`child-call-type-badge ${call.call_type || "ai"}`}><i aria-hidden="true">{type.mark}</i>{type.filterLabel}</span>
                <span className="child-call-list-copy"><b>{call.report_title || call.summary || "가족과 나눈 통화"}</b><small>{call.summary || (call.meaning_count ? `기억에 남은 대화 ${call.meaning_count}건` : "대화 내용을 확인해 보세요.")}</small></span>
                <span className="child-call-list-meta"><time>{shortTime(call.started_at)}</time><small>{duration(call.duration_sec)}</small><em>{needsAttention ? `확인 필요 ${call.risk_count}` : "보기"}</em></span>
              </button>;
            })}
            {!visibleCalls.length && <div className="child-empty-card"><b>조건에 맞는 통화가 없어요</b><p>다른 날짜나 유형을 선택해 보세요.</p></div>}
          </div>
          <CallTranscriptModal call={activeCall} elderName={picked.name} onClose={() => setActiveCall(null)} />
        </section>}

        {tab === "settings" && <section className="child-family-settings">
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
