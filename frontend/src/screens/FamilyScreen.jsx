import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { useSpeech } from "../useSpeech.js";
import { familyMatchPrompt, matchFamily, readyFamilyHint } from "../familyMatch.js";

const dateKey = (date) => [
  date.getFullYear(),
  String(date.getMonth() + 1).padStart(2, "0"),
  String(date.getDate()).padStart(2, "0"),
].join("-");

function greeting(hour) {
  if (hour < 11) return "좋은 아침이에요";
  if (hour < 17) return "편안한 오후예요";
  return "편안한 저녁이에요";
}

export default function FamilyScreen({ elderId = "elder_001", onPick, error }) {
  const [personas, setPersonas] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [medications, setMedications] = useState([]);
  const [memories, setMemories] = useState([]);
  const [now, setNow] = useState(() => new Date());
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");

  const speech = useSpeech({
    silenceMs: 1600,
    onFinal: (text) => {
      const result = matchFamily(text, personas);
      if (result.status === "one") onPick(result.persona);
      else setNotice(result.status === "many"
        ? familyMatchPrompt(result)
        : `“${text}” — 가족의 이름을 다시 말씀해 주세요.`);
    },
  });

  useEffect(() => {
    let alive = true;
    setLoadError("");
    Promise.all([
      api.getPersonas(elderId), api.getSchedules(elderId),
      api.getMedications(elderId), api.getMemories(elderId),
    ]).then(([personaResult, scheduleResult, medicationResult, memoryResult]) => {
      if (!alive) return;
      setPersonas(personaResult.personas || []);
      setSchedules([...(scheduleResult.past || []), ...(scheduleResult.upcoming || [])]);
      setMedications(medicationResult.today || []);
      setMemories(memoryResult.memories || []);
    }).catch((reason) => alive && setLoadError(reason.message));
    const clock = setInterval(() => setNow(new Date()), 30000);
    return () => { alive = false; clearInterval(clock); };
  }, [elderId]);

  const ready = personas.filter((persona) => persona.ready);
  const today = dateKey(now);
  const todaySchedules = schedules.filter((item) => item.date === today);
  const confirmedMedicationCount = medications.filter((item) =>
    item.last_status === "USER_CONFIRMED" || item.status === "USER_CONFIRMED"
  ).length;
  const memory = useMemo(() => memories.find((item) =>
    item.status === "verified" && item.conversation_allowed && item.artwork?.image_url
  ) || memories.find((item) => item.status === "verified" && item.conversation_allowed), [memories]);

  const dateLabel = now.toLocaleDateString("ko-KR", {
    month: "long", day: "numeric", weekday: "long",
  });
  const timeLabel = now.toLocaleTimeString("ko-KR", {
    hour: "numeric", minute: "2-digit",
  });

  return (
    <div className="screen family reassurance-home">
      <header className="reassurance-header">
        <p>{dateLabel} · {timeLabel}</p>
        <h1>{greeting(now.getHours())}</h1>
        <span>오늘도 가족과 편안하게 이야기할 수 있어요.</span>
      </header>

      <section className="today-reassurance" aria-label="오늘의 안심 정보">
        <article>
          <span className="today-icon schedule" aria-hidden="true">일정</span>
          <div><small>오늘 일정</small><b>{todaySchedules[0]?.title || "등록된 일정이 없어요"}</b>
            {todaySchedules[0] && <p>{todaySchedules[0].time || "시간 미정"}{todaySchedules.length > 1 ? ` · 외 ${todaySchedules.length - 1}개` : ""}</p>}
          </div>
        </article>
        <article>
          <span className="today-icon medication" aria-hidden="true">약</span>
          <div><small>오늘 복약 일정</small><b>{medications.length ? `${medications.length}번 중 ${confirmedMedicationCount}번 확인` : "등록된 복약 일정이 없어요"}</b>
            {medications[0] && <p>다음 확인은 가족과 함께 해요.</p>}
          </div>
        </article>
      </section>

      {memory && <section className="reassurance-memory" aria-label="가족이 확인한 기억">
        {memory.artwork?.image_url
          ? <img src={memory.artwork.image_url} alt={memory.artwork.alt_text || memory.title} />
          : <span aria-hidden="true">◇</span>}
        <div><small>가족이 확인한 소중한 기억</small><b>{memory.title}</b><p>{memory.date_text || memory.location || "가족이 함께 기억하고 있어요."}</p></div>
      </section>}

      <section className="reassurance-family">
        <header><h2>누구와 이야기할까요?</h2><span>사진을 눌러 주세요</span></header>
        <div className="family-grid">
          {personas.map((persona) => (
            <button
              key={persona.persona_id}
              className={`family-card${persona.ready ? "" : " waiting"}`}
              disabled={!persona.ready}
              onClick={() => onPick(persona)}
              aria-label={`${persona.display_name} ${persona.relationship}에게 전화하기`}
            >
              <span className="family-face">
                {persona.face ? <img src={persona.face} alt="" /> : <i>{persona.display_name.slice(0, 1)}</i>}
              </span>
              <span><b>{persona.display_name}</b><small>{persona.ready ? persona.relationship : "등록 대기"}</small></span>
            </button>
          ))}
          {!personas.length && <p className="family-empty">아직 등록된 가족이 없어요. 가족 앱에서 먼저 얼굴과 관계를 등록해 주세요.</p>}
        </div>
      </section>

      {speech.supported && ready.length > 0 && <button
        className={`pill voice reassurance-voice${speech.listening ? " listening" : ""}`}
        onClick={() => (speech.listening ? speech.stop() : speech.start())}
      >
        {speech.listening ? "듣고 있어요" : "가족 이름을 말해도 돼요"}
      </button>}

      {speech.listening && <p className="hint">{speech.interim || readyFamilyHint(personas)}</p>}
      {!speech.listening && notice && <p className="hint">{notice}</p>}
      {(error || loadError) && <p className="error">일부 정보를 불러오지 못했어요. 가족 통화는 계속 이용할 수 있어요. ({error || loadError})</p>}
    </div>
  );
}
