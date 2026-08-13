import { useEffect } from "react";
import Transcript from "./Transcript.jsx";

const TYPE_META = {
  direct: { label: "내가 직접 통화", mark: "나" },
  ai: { label: "AI가 대신 통화", mark: "AI" },
  ai_to_direct: { label: "AI 통화 후 직접 연결", mark: "연결" },
};

function duration(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}분 ${rest}초` : `${rest}초`;
}

function time(value) {
  if (!value) return "시간 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

export default function CallTranscriptModal({ call, elderName = "어르신", onClose }) {
  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  if (!call) return null;
  const type = TYPE_META[call.call_type] || TYPE_META.ai;
  const needsAttention = Number(call.risk_count || 0) > 0;
  const speakerName = call.call_type === "direct"
    ? (call.counterpart_name || "가족")
    : call.call_type === "ai_to_direct"
      ? "AI·가족"
      : `AI ${call.counterpart_name || "가족"}`;

  return <div className="child-call-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className={`child-call-modal ${call.call_type || "ai"}${needsAttention ? " problem" : ""}`} role="dialog" aria-modal="true" aria-labelledby="child-call-modal-title">
      <header>
        <div className="child-call-modal-title">
          <span className={`child-call-type-badge ${call.call_type || "ai"}`}><i aria-hidden="true">{type.mark}</i>{type.label}</span>
          {needsAttention && <span className="child-call-problem-badge">확인 필요 · 안전 신호 {call.risk_count}건</span>}
          <h2 id="child-call-modal-title">{call.report_title || call.summary || "가족과 나눈 통화"}</h2>
          <p>{time(call.started_at)} · {duration(call.duration_sec)} · {call.counterpart_name || "가족"}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="대화 내용 닫기">×</button>
      </header>
      {call.call_type === "ai_to_direct" && <p className="child-call-handover-note">AI가 먼저 응대한 뒤 가족이 통화를 이어받은 기록입니다.</p>}
      <Transcript callId={call.call_id} personaName={speakerName} elderName={`${elderName} 어르신`} />
    </section>
  </div>;
}
