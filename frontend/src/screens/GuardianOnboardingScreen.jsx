import { useEffect, useState } from "react";
import * as api from "../api.js";
import { callStylePersonaPatch, getDefaultCallStyle } from "../callStyle.js";
import BrandMark from "../components/BrandMark.jsx";
import CallStyleQuiz from "../components/CallStyleQuiz.jsx";

export default function GuardianOnboardingScreen({ onDone }) {
  const [personas, setPersonas] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState({});
  const [answers, setAnswers] = useState({});
  const [step, setStep] = useState("profile");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getPersonas().then(({ personas: rows }) => {
      const available = rows.filter((persona) => persona.ready);
      setPersonas(available);
      if (available.length) selectPersona(available[0].persona_id);
    }).catch((reason) => setError(reason.message));
  }, []);

  function selectPersona(personaId) {
    setSelectedId(personaId);
    setError("");
    api.getPersona(personaId).then(({ persona }) => {
      setForm(persona || {});
      setAnswers(persona?.call_style_answers || {});
    }).catch((reason) => setError(reason.message));
  }

  async function finish(result, appliedAnswers = answers) {
    setBusy(true);
    setError("");
    try {
      await api.patchPersona({
        display_name: form.display_name,
        relationship_type: form.relationship_type,
        elder_calls_family: form.elder_calls_family,
        family_calls_elder: form.family_calls_elder,
        ...callStylePersonaPatch(result, appliedAnswers),
      }, selectedId);
      onDone({ personaId: selectedId, code: result.code });
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  function useDefaultStyle() {
    const defaults = getDefaultCallStyle();
    setAnswers(defaults.answers);
    finish(defaults.result, defaults.answers);
  }

  return <main className="guardian-onboarding">
    <header className="onboarding-brand"><BrandMark size={35} /><div><b>다소니</b><span>처음 만나는 가족 케어 설정</span></div></header>
    <nav className="onboarding-steps" aria-label="최초 설정 단계">
      <span className={step === "profile" ? "on" : "done"}><i>1</i>가족 정보</span>
      <b />
      <span className={step === "quiz" ? "on" : ""}><i>2</i>통화 MBTI</span>
      <b />
      <span><i>3</i>케어 시작</span>
    </nav>

    {step === "profile" ? <section className="onboarding-card profile-step">
      <p className="eyebrow">가족 정보</p>
      <h1>어르신과 통화하는 나는 누구인가요?</h1>
      <p>본인 프로필을 선택하고 실제로 사용하는 이름과 호칭을 확인해 주세요.</p>
      <div className="onboarding-personas">
        {personas.map((persona) => <button type="button" key={persona.persona_id} className={selectedId === persona.persona_id ? "selected" : ""} onClick={() => selectPersona(persona.persona_id)}>
          {persona.face ? <img src={persona.face} alt="" /> : <span>{persona.display_name?.slice(0, 1)}</span>}
          <b>{persona.display_name}</b><small>{persona.relationship}</small>
          {persona.call_style_code && <i>{persona.call_style_code}</i>}
        </button>)}
      </div>
      <div className="onboarding-fields">
        <label>내 이름<input value={form.display_name || ""} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label>
        <label>어르신과의 관계<input value={form.relationship_type || ""} onChange={(event) => setForm({ ...form, relationship_type: event.target.value })} /></label>
        <label>내가 어르신을 부르는 말<input value={form.family_calls_elder || ""} onChange={(event) => setForm({ ...form, family_calls_elder: event.target.value })} /></label>
        <label>어르신이 나를 부르는 말<input value={form.elder_calls_family || ""} onChange={(event) => setForm({ ...form, elder_calls_family: event.target.value })} /></label>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="onboarding-choice-actions">
        <button type="button" className="onboarding-default-start" disabled={busy || !selectedId || !form.display_name} onClick={useDefaultStyle}>기본 말투로 바로 시작</button>
        <button type="button" className="save onboarding-next" disabled={!selectedId || !form.display_name} onClick={() => setStep("quiz")}>28문항으로 맞춤 설정</button>
      </div>
    </section> : <section className="onboarding-card quiz-step">
      <button type="button" className="onboarding-back" onClick={() => setStep("profile")}>← 가족 정보로</button>
      <CallStyleQuiz answers={answers} onAnswers={setAnswers} onApply={finish} onUseDefault={useDefaultStyle} applyLabel={busy ? "저장하는 중…" : "저장하고 다소니 시작"} />
      {error && <p className="error">{error}</p>}
    </section>}
  </main>;
}
