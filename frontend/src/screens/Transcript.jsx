import { useEffect, useState } from "react";
import * as api from "../api.js";

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function messageTime(value) {
  const parsed = parseDate(value);
  return parsed
    ? parsed.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : "";
}

function messageDate(value) {
  const parsed = parseDate(value);
  return parsed
    ? parsed.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" })
    : "통화한 날";
}

/**
 * 통화 전체 대화.
 *
 * 요약만으로는 보호자가 "정말 그랬나" 를 확인할 수 없다.
 * 원문을 볼 수 있어야 요약을 신뢰할 수 있다 (명세 NFR-05).
 */
export default function Transcript({ callId, personaName = "AI 가족", elderName = "어르신" }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getTranscript(callId)
      .then((r) => setRows(r.utterances))
      .catch((e) => setError(e.message));
  }, [callId]);

  if (error) return <p className="hint">대화 기록을 불러오지 못했어요.</p>;
  if (!rows) return <p className="hint">불러오는 중…</p>;
  if (!rows.length) return <p className="transcript-empty">저장된 대화 내용이 없습니다.</p>;

  return (
    <div className="transcript" tabIndex="0" role="region" aria-label="전체 통화 대화">
      <div className="transcript-day">{messageDate(rows[0]?.created_at)}</div>
      <p className="transcript-scroll-guide">
        총 {rows.length}개 발화 · 아래로 스크롤해 전체 대화를 확인하세요
      </p>
      {rows.map((u, index) => {
        const showSpeaker = index === 0 || rows[index - 1]?.speaker !== u.speaker;
        return (
          <div key={u.seq} className={`line ${u.speaker}`}>
            {showSpeaker && (
              <span className="speaker">
                {u.speaker === "elder" ? elderName : personaName}
              </span>
            )}
            <div className="transcript-message-row">
              <div className="bubble">
                {u.transcript}
                {u.was_rewritten ? (
                  <span className="fixed">안전 규칙으로 수정됨</span>
                ) : null}
              </div>
              <time dateTime={u.created_at}>{messageTime(u.created_at)}</time>
            </div>
          </div>
        );
      })}
    </div>
  );
}
