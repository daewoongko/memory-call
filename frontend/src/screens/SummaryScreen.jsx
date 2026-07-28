export default function SummaryScreen({ summary, onRestart }) {
  return (
    <div className="screen">
      <div className="who">통화가 끝났어요</div>

      <div className="summary">
        <div>통화 시간 <b>{summary.duration_sec}초</b></div>
        <div>주고받은 말 <b>{summary.ai_turns}번</b></div>
        <div>평균 응답 <b>{summary.avg_latency_ms}ms</b></div>
        {summary.risk_events > 0 && (
          <div>가족에게 알림 <b>{summary.risk_events}건</b></div>
        )}
      </div>

      <button className="pill" onClick={onRestart}>처음으로</button>
    </div>
  );
}
