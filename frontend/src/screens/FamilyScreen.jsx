import { useEffect, useState } from "react";
import * as api from "../api.js";
import { useSpeech } from "../useSpeech.js";
import { familyMatchPrompt, matchFamily, readyFamilyHint } from "../familyMatch.js";
import BrandMark from "../components/BrandMark.jsx";

const PhoneIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" /></svg>;
const MicIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8" /></svg>;

export default function FamilyScreen({ elderId = "elder_001", onPick, error, media, onOpenSettings, onRole }) {
  const [personas, setPersonas] = useState([]);
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
    api.getPersonas(elderId).then((personaResult) => {
      if (!alive) return;
      setPersonas(personaResult.personas || []);
    }).catch((reason) => alive && setLoadError(reason.message));
    const clock = setInterval(() => setNow(new Date()), 30000);
    return () => { alive = false; clearInterval(clock); };
  }, [elderId]);

  const ready = personas.filter((persona) => persona.ready);

  const dateLabel = now.toLocaleDateString("ko-KR", {
    month: "long", day: "numeric", weekday: "long",
  });
  const timeLabel = now.toLocaleTimeString("ko-KR", {
    hour: "numeric", minute: "2-digit",
  });

  const toggleVoice = async () => {
    if (speech.listening) {
      speech.stop();
      return;
    }
    if (!media?.ready) {
      try {
        const prepared = await media?.prepare?.();
        if (!prepared?.ready) throw new Error("microphone unavailable");
      } catch {
        setNotice("마이크 연결이 안 됐어요. 마이크 권한과 연결 상태를 확인해 주세요.");
        return;
      }
    }
    setNotice("");
    speech.start();
  };

  return (
    <div className="screen family reassurance-home reassurance-home-simple">
      <header className="elder-topbar">
        <button type="button" className="elder-topbar-brand" onClick={onRole} aria-label="사용자 선택 화면으로 이동">
          <BrandMark size={42} />
          <span><b>다소니</b></span>
        </button>
        <div className="elder-topbar-actions">
          <time className="elder-topbar-clock" dateTime={now.toISOString()}>{dateLabel} · {timeLabel}</time>
          <button type="button" className="elder-view-button" onClick={onOpenSettings} aria-label="글자 크기와 화면 명암 설정"><span>Aa</span></button>
        </div>
      </header>

      <section className="reassurance-family">
        <header>
          <h1>누구와 이야기해 볼까요?</h1>
        </header>
        <div className="family-grid">
          {personas.map((persona) => (
            <button
              key={persona.persona_id}
              data-persona-id={persona.persona_id}
              className={`family-card${persona.ready ? "" : " waiting"}`}
              disabled={!persona.ready}
              onClick={() => onPick(persona)}
              aria-label={`${persona.display_name} ${persona.relationship}에게 전화하기`}
            >
              <span className="family-face">
                {persona.face ? <img src={persona.face} alt="" /> : <i>{persona.display_name.slice(0, 1)}</i>}
              </span>
              <span className="family-card-text"><small>{persona.ready ? persona.relationship : "등록 대기"}</small><b>{persona.display_name}</b></span>
              <span className="family-call-icon" aria-hidden="true"><PhoneIcon /></span>
            </button>
          ))}
          {!personas.length && <p className="family-empty">아직 등록된 가족이 없어요. 가족 앱에서 먼저 얼굴과 관계를 등록해 주세요.</p>}
        </div>
      </section>

      {(error || loadError) && <p className="error">일부 정보를 불러오지 못했어요. 가족 통화는 계속 이용할 수 있어요. ({error || loadError})</p>}

      {speech.supported && ready.length > 0 && <footer className="voice-call-dock">
        {(speech.listening || notice || speech.error) && <p className="hint" aria-live="polite">
          {speech.error || (speech.listening ? (speech.interim || readyFamilyHint(personas)) : notice)}
        </p>}
        <button
          type="button"
          className={`pill voice reassurance-voice${speech.listening ? " listening" : ""}`}
          onClick={toggleVoice}
        >
          <MicIcon />
          <span>{speech.listening ? "듣고 있어요" : "가족 이름 말하기"}</span>
        </button>
      </footer>}
    </div>
  );
}
