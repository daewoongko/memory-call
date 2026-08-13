import { useEffect, useState } from "react";
import * as api from "../api.js";

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
    <div className="transcript">
      {rows.map((u) => (
        <div key={u.seq} className={`line ${u.speaker}`}>
          <span className="speaker">
            {u.speaker === "elder" ? elderName : personaName}
          </span>
          <div className="bubble">
            {u.transcript}
            {u.was_rewritten ? (
              <span className="fixed">안전 규칙으로 수정됨</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
