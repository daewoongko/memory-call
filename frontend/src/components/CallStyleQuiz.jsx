import { useEffect, useMemo, useRef, useState } from "react";
import {
  CALL_STYLE_DIMENSIONS,
  CALL_STYLE_SCENES,
  CALL_STYLE_TOTAL_SCENES,
  calculateCallStyle,
  cleanCallStyleAnswers,
} from "../callStyle.js";

const confidenceCopy = { strong: "강함", medium: "보통", weak: "약함" };

function personalizedLine(line, elderCallName) {
  return line.replaceAll("{elder}", elderCallName || "어르신");
}

export default function CallStyleQuiz({
  answers,
  onAnswers,
  onApply,
  onUseDefault,
  elderCallName = "어르신",
  applyLabel = "이 말투 적용",
}) {
  const cleanedAnswers = useMemo(() => cleanCallStyleAnswers(answers), [answers]);
  const firstIncomplete = CALL_STYLE_SCENES.findIndex((scene) => !cleanedAnswers[scene.id]);
  const [sceneIndex, setSceneIndex] = useState(firstIncomplete >= 0 ? firstIncomplete : CALL_STYLE_TOTAL_SCENES);
  const advanceTimer = useRef(null);
  const result = useMemo(() => calculateCallStyle(cleanedAnswers), [cleanedAnswers]);
  const answered = Object.keys(cleanedAnswers).length;
  const scene = CALL_STYLE_SCENES[Math.min(sceneIndex, CALL_STYLE_TOTAL_SCENES - 1)];

  useEffect(() => () => window.clearTimeout(advanceTimer.current), []);

  function choose(choiceId) {
    const next = { ...cleanedAnswers, [scene.id]: choiceId };
    onAnswers(next);
    window.clearTimeout(advanceTimer.current);
    advanceTimer.current = window.setTimeout(() => {
      setSceneIndex((current) => Math.min(current + 1, CALL_STYLE_TOTAL_SCENES));
    }, 180);
  }

  function goBack() {
    window.clearTimeout(advanceTimer.current);
    setSceneIndex((current) => Math.max(0, current - 1));
  }

  const showingResult = sceneIndex >= CALL_STYLE_TOTAL_SCENES && result;

  return <section className="call-style-quiz call-style-card-quiz">
    <header className="call-style-head">
      <div>
        <span>말투 카드</span>
      </div>
      {showingResult
        ? <button type="button" className="call-style-complete" onClick={() => onApply?.(result)}>완료</button>
        : <b>{`${Math.min(sceneIndex + 1, CALL_STYLE_TOTAL_SCENES)}/${CALL_STYLE_TOTAL_SCENES}`}</b>}
    </header>

    {onUseDefault && sceneIndex === 0 && answered === 0 && <div className="call-style-default">
      <div><b>질문 없이 시작할 수도 있어요</b><span>차분하게 상황을 알려주고, 지금 할 일 하나를 안내하는 기본 말투를 사용합니다.</span></div>
      <button type="button" onClick={onUseDefault}>기본 말투로 시작</button>
    </div>}

    {!showingResult && <div className="call-style-scene-progress" aria-label={`${answered}개 카드 선택 완료`}>
      {CALL_STYLE_SCENES.map((item, index) => <i key={item.id} className={cleanedAnswers[item.id] ? "done" : index === sceneIndex ? "current" : ""} />)}
    </div>}

    {!showingResult ? <>
      <article className="call-style-scene">
        <header>
          <span>{String(sceneIndex + 1).padStart(2, "0")}</span>
          <div><small>{scene.title}</small><h4>{scene.situation}</h4></div>
        </header>
        {scene.safety && <p className="call-style-scene-safety">{scene.safety}</p>}
        <div className="call-style-scene-choices">
          {scene.choices.map((choice) => <button
            type="button"
            key={choice.id}
            className={cleanedAnswers[scene.id] === choice.id ? "selected" : ""}
            onClick={() => choose(choice.id)}
          >
            <i>{choice.id.toUpperCase()}</i>
            <span>{personalizedLine(choice.line, elderCallName)}</span>
            <b aria-hidden="true">›</b>
          </button>)}
        </div>
      </article>
      <div className="call-style-nav">
        <button type="button" disabled={sceneIndex === 0} onClick={goBack}>← 이전 장면</button>
      </div>
    </> : <article className="call-style-result">
      <div className="call-style-result-main">
        <h3 className="call-style-result-title"><small>말투 시작점</small><span>{result.name}</span><em>{result.code}</em></h3>
        <p>{result.description}</p>
        {result.frequent[0] && <blockquote><span>첫마디는 이렇게 나갑니다</span>“{result.frequent[0]}”</blockquote>}
      </div>
      <div className="call-style-score-grid">
        {CALL_STYLE_DIMENSIONS.map((item) => {
          const score = result.scores[item.id];
          return <div key={item.id}>
            <header>
              <b>{item.leftName} {score.left_count}</b>
              <span>{item.short} · {confidenceCopy[score.confidence]}</span>
              <b>{score.right_count} {item.rightName}</b>
            </header>
            <i><em style={{ width: `${score.left_percent}%` }} /></i>
          </div>;
        })}
      </div>
      <div className="call-style-result-actions">
        <button type="button" onClick={goBack}>선택 다시 보기</button>
        <button type="button" className="save" onClick={() => onApply?.(result)}>{applyLabel}</button>
      </div>
    </article>}
  </section>;
}
