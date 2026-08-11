import { useMemo, useState } from "react";
import {
  CALL_STYLE_DIMENSIONS,
  CALL_STYLE_TOTAL_QUESTIONS,
  calculateCallStyle,
} from "../callStyle.js";

export default function CallStyleQuiz({ answers, onAnswers, onApply, applyLabel = "이 유형 적용" }) {
  const [dimensionIndex, setDimensionIndex] = useState(0);
  const dimension = CALL_STYLE_DIMENSIONS[dimensionIndex];
  const result = useMemo(() => calculateCallStyle(answers), [answers]);
  const answered = CALL_STYLE_DIMENSIONS.flatMap((item) => item.questions)
    .filter(([id]) => answers[id]).length;
  const dimensionDone = dimension.questions.every(([id]) => answers[id]);

  return <section className="call-style-quiz">
    <header className="call-style-head">
      <div>
        <span>통화 MBTI</span>
        <h3>가족의 평소 통화 방식을 알려주세요</h3>
        <p>정답은 없습니다. 실제 어르신과 통화할 때 더 자연스러운 쪽을 선택하세요.</p>
      </div>
      <b>{answered}/{CALL_STYLE_TOTAL_QUESTIONS}</b>
    </header>
    <div className="persona-progress"><i style={{ width: `${answered / CALL_STYLE_TOTAL_QUESTIONS * 100}%` }} /></div>

    <nav className="call-style-dimensions" aria-label="통화 성향 검사 단계">
      {CALL_STYLE_DIMENSIONS.map((item, index) => {
        const count = item.questions.filter(([id]) => answers[id]).length;
        return <button type="button" key={item.id} className={dimensionIndex === index ? "on" : count === item.questions.length ? "done" : ""} onClick={() => setDimensionIndex(index)}>
          <span>{index + 1}</span><b>{item.short}</b><small>{item.left}/{item.right} · {count}/7</small>
        </button>;
      })}
    </nav>

    <div className="call-style-dimension-copy">
      <div><span>{dimension.left}</span><b>{dimension.leftName}</b></div>
      <p>{dimension.description}</p>
      <div><span>{dimension.right}</span><b>{dimension.rightName}</b></div>
    </div>

    <div className="call-style-question-list">
      {dimension.questions.map(([id, question, leftLabel, rightLabel], index) => <fieldset key={id}>
        <legend><span>{String(index + 1).padStart(2, "0")}</span>{question}</legend>
        <div>
          <button type="button" className={answers[id] === dimension.left ? "selected" : ""} onClick={() => onAnswers({ ...answers, [id]: dimension.left })}>
            <i>{dimension.left}</i>{leftLabel}
          </button>
          <button type="button" className={answers[id] === dimension.right ? "selected" : ""} onClick={() => onAnswers({ ...answers, [id]: dimension.right })}>
            <i>{dimension.right}</i>{rightLabel}
          </button>
        </div>
      </fieldset>)}
    </div>

    <div className="call-style-nav">
      <button type="button" disabled={dimensionIndex === 0} onClick={() => setDimensionIndex((index) => index - 1)}>이전</button>
      {dimensionIndex < CALL_STYLE_DIMENSIONS.length - 1 && <button type="button" className="primary" disabled={!dimensionDone} onClick={() => setDimensionIndex((index) => index + 1)}>다음 영역</button>}
    </div>

    {result ? <article className="call-style-result">
      <div className="call-style-code"><small>나의 통화 유형</small><b>{result.code}</b></div>
      <div className="call-style-result-copy"><span>{result.name}</span><h3>{result.description}</h3><p>유형은 진단이 아니라 AI 말투의 시작점입니다. 실제 통화에서는 어르신 상태와 안전 규칙이 우선됩니다.</p></div>
      <div className="call-style-score-grid">
        {CALL_STYLE_DIMENSIONS.map((item) => {
          const score = result.scores[item.id];
          return <div key={item.id}>
            <header><b>{score.left} {score.left_percent}%</b><span>{item.short}</span><b>{score.right_percent}% {score.right}</b></header>
            <i><em style={{ width: `${score.left_percent}%` }} /></i>
          </div>;
        })}
      </div>
      <button type="button" className="save" onClick={() => onApply?.(result)}>{applyLabel}</button>
    </article> : <p className="persona-result-wait">네 영역의 28문항에 모두 답하면 통화 유형과 축별 비율이 나타납니다.</p>}
  </section>;
}
