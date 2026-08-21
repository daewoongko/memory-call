import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import {
  CALL_STYLE_DIMENSIONS,
  callStylePersonaPatch,
  getDefaultCallStyle,
} from "../callStyle.js";
import CallStyleQuiz from "../components/CallStyleQuiz.jsx";
import VoiceProfilePanel from "../components/VoiceProfilePanel.jsx";
import PersonaPanel from "./PersonaPanel.jsx";

const toLines = (value) => Array.isArray(value) ? value.join("\n") : String(value || "");
const fromLines = (value) => String(value || "").split("\n").map((line) => line.trim()).filter(Boolean);

const AVATAR_PERFORMANCE_STYLES = [
  { value: "calm", label: "차분하게", hint: "고개와 표정 움직임을 작게 유지해요." },
  { value: "natural", label: "자연스럽게", hint: "일상 대화 정도로 표정을 사용해요." },
  { value: "lively", label: "생동감 있게", hint: "반응과 표정을 조금 더 크게 보여줘요." },
];

function stylePayload(persona) {
  return {
    tone: persona.tone || "",
    frequent_phrases: fromLines(toLines(persona.frequent_phrases)),
    forbidden_phrases: fromLines(toLines(persona.forbidden_phrases)),
    call_style_code: persona.call_style_code || null,
    call_style_name: persona.call_style_name || null,
    call_style_scores: persona.call_style_scores || null,
    call_style_answers: persona.call_style_answers || {},
    avatar_performance_style: persona.avatar_performance_style || "calm",
  };
}

export default function FamilyPersonaSettings({ elderId, personaId, summary }) {
  const [persona, setPersona] = useState(null);
  const [answers, setAnswers] = useState({});
  const [quizOpen, setQuizOpen] = useState(false);
  const [photoOpen, setPhotoOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!personaId) {
      setPersona(null);
      return;
    }
    let alive = true;
    setError("");
    api.getPersona(personaId, elderId).then(({ persona: next }) => {
      if (!alive) return;
      setPersona(next || {});
      setAnswers(next?.call_style_answers || {});
    }).catch((reason) => alive && setError(reason.message));
    return () => { alive = false; };
  }, [elderId, personaId]);

  const scores = useMemo(() => persona?.call_style_scores || {}, [persona]);

  useEffect(() => {
    if (!photoOpen) return undefined;
    const closeOnEscape = (event) => event.key === "Escape" && setPhotoOpen(false);
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [photoOpen]);

  async function persist(next, message) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      await api.patchPersona(stylePayload(next), personaId, elderId);
      setPersona(next);
      setAnswers(next.call_style_answers || {});
      setNote(message);
      return true;
    } catch (reason) {
      setError(reason.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function applyCallStyle(result, appliedAnswers = answers) {
    if (!result || !persona) return;
    const next = { ...persona, ...callStylePersonaPatch(result, appliedAnswers) };
    if (await persist(next, `${result.name} 말투 시작점을 저장했습니다.`)) setQuizOpen(false);
  }

  function applyDefault() {
    const defaults = getDefaultCallStyle();
    setAnswers(defaults.answers);
    applyCallStyle(defaults.result, defaults.answers);
  }

  if (!personaId) return <div className="child-empty-card family-settings-empty"><b>내 가족 프로필을 확인할 수 없어요</b><p>가족 연결을 다시 진행해 본인 프로필을 선택해 주세요.</p></div>;
  if (!persona) return <p className="hint">내 통화 설정을 불러오는 중…</p>;

  return <div className="family-persona-settings">
    <article className="family-self-card">
      <button type="button" className="family-profile-entry" onClick={() => setPhotoOpen(true)} aria-label={`${persona.display_name || "가족"} 사진 관리 열기`}>
        {summary?.face ? <img src={summary.face} alt="" /> : <span className="family-self-placeholder">{persona.display_name?.slice(0, 1)}</span>}
        <span className="family-self-identity">
        <small>내 가족 프로필</small>
        <h1>{persona.display_name}<i className="child-me-badge">나</i></h1>
        <p>{persona.relationship_type || summary?.relationship}</p>
        <em>사진 보기</em>
        </span>
      </button>
      <button type="button" className="family-style-current" onClick={() => setQuizOpen((open) => !open)} aria-expanded={quizOpen}>
        <small>말투 카드</small>
        <strong>{persona.call_style_name || "미설정"}</strong>
        <span>{quizOpen ? "설정 닫기" : persona.call_style_code ? "다시 설정하기" : "설정하기"} <b aria-hidden="true">›</b></span>
      </button>
    </article>

    {persona.call_style_code && <div className="family-style-scores" aria-label="말투 시작점 네 영역">
      {CALL_STYLE_DIMENSIONS.map((dimension) => {
        const score = scores[dimension.id];
        return <div key={dimension.id}>
          <span>{dimension.short}</span>
          <b>{score ? `${score.selected} · ${Math.max(score.left_percent, score.right_percent)}%` : "저장됨"}</b>
        </div>;
      })}
    </div>}

    {quizOpen && <div className="family-style-quiz-wrap">
      <CallStyleQuiz
        answers={answers}
        onAnswers={setAnswers}
        onApply={applyCallStyle}
        onUseDefault={applyDefault}
        elderCallName={persona.family_calls_elder || "어르신"}
        applyLabel={busy ? "저장하는 중…" : "말투 시작점 저장"}
      />
    </div>}

    <VoiceProfilePanel elderId={elderId} personaId={personaId} persona={persona} />

    <section className="family-speech-settings">
      <header><span>말투 세부 조정</span><h2>우리 가족이 실제로 쓰는 표현을 알려주세요</h2></header>
      <label>
        <b>말투</b>
        <span>말의 속도, 높임말과 반말, 평소 분위기를 적어주세요.</span>
        <textarea value={toLines(persona.tone)} onChange={(event) => setPersona({ ...persona, tone: event.target.value })} />
      </label>
      <div className="family-speech-grid">
        <label>
          <b>자주 쓰는 말</b>
          <span>한 줄에 하나씩 입력하세요.</span>
          <textarea value={toLines(persona.frequent_phrases)} onChange={(event) => setPersona({ ...persona, frequent_phrases: event.target.value.split("\n") })} />
        </label>
        <label>
          <b>쓰면 안 되는 말</b>
          <span>어르신께 상처나 부담이 될 표현을 적어주세요.</span>
          <textarea value={toLines(persona.forbidden_phrases)} onChange={(event) => setPersona({ ...persona, forbidden_phrases: event.target.value.split("\n") })} />
        </label>
      </div>
      <div className="family-speech-actions">
        <p>통화 중에는 이 설정보다 안전 규칙이 항상 우선합니다.</p>
        <button type="button" disabled={busy} onClick={() => persist(persona, "말투 세부 설정을 저장했습니다.")}>{busy ? "저장 중…" : "말투 저장"}</button>
      </div>
    </section>

    {note && <p className="family-settings-note" role="status">{note}</p>}
    {error && <p className="error">설정을 저장하지 못했습니다. ({error})</p>}

    {photoOpen && <div className="daily-modal-backdrop family-photo-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setPhotoOpen(false)}>
      <section className="family-photo-modal" role="dialog" aria-modal="true" aria-label={`${persona.display_name || "가족"} 사진 관리`}>
        <header>
          <div>
            <small>가족 얼굴 관리</small>
            <h2>{persona.display_name}님의 사진과 시간 여행</h2>
            <p>현재 얼굴을 등록하고 연령별 후보를 확정한 뒤 과거에서 현재로 이어지는 영상을 준비합니다.</p>
          </div>
          <button type="button" aria-label="사진 관리 닫기" onClick={() => setPhotoOpen(false)}>×</button>
        </header>
        <div className="family-photo-modal-body">
          <section className="family-avatar-performance">
            <div>
              <small>실시간 아바타 표정</small>
              <h3>통화할 때의 움직임을 정해주세요</h3>
              <p>사진과 나이 영상은 그대로 두고, 말할 때의 표정 강도만 바뀝니다.</p>
            </div>
            <div className="family-avatar-performance-options" role="group" aria-label="실시간 아바타 표정 강도">
              {AVATAR_PERFORMANCE_STYLES.map((style) => {
                const selected = (persona.avatar_performance_style || "calm") === style.value;
                return <button
                  type="button"
                  key={style.value}
                  className={selected ? "selected" : ""}
                  aria-pressed={selected}
                  disabled={busy}
                  onClick={() => persist(
                    { ...persona, avatar_performance_style: style.value },
                    `통화 영상 표정을 '${style.label}'로 저장했습니다.`,
                  )}
                >
                  <b>{style.label}</b>
                  <span>{style.hint}</span>
                </button>;
              })}
            </div>
          </section>
          <PersonaPanel elderId={elderId} initialPersonaId={personaId} mode="photos" />
        </div>
      </section>
    </div>}
  </div>;
}
