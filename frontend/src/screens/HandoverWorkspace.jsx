import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

function HandoverRow({ row, completed = false }) {
  const context = [row.time, row.dosage_text, row.indication, ...(row.monitoring_points || [])].filter(Boolean);
  const status = completed
    ? (row.completed_at ? new Date(row.completed_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "완료")
    : row.status === "missed" ? "기록 대조 필요" : "확인 대기";
  return <details className={`handover-item${completed ? " completed" : ""}`}>
    <summary>
      <strong>{row.elder_name}</strong>
      <p>{row.title}</p>
      <small className={!completed && row.status === "missed" ? "missed" : !completed ? "waiting" : ""}>{status}</small>
      <i aria-hidden="true">⌄</i>
    </summary>
    <div className="handover-item-detail">
      {context.length > 0 && <p><b>확인 정보</b><span>{context.join(" · ")}</span></p>}
      <p><b>근거</b><span>{row.evidence ? `“${row.evidence}”` : "직접 확인해 결과를 기록해 주세요."}</span></p>
    </div>
  </details>;
}

export default function HandoverWorkspace({ date }) {
  const [tasks, setTasks] = useState(null);
  const [history, setHistory] = useState([]);
  const [shift, setShift] = useState("day");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => Promise.all([api.getCareTasks(date), api.getHandovers()]).then(([taskRows, handovers]) => { setTasks(taskRows); setHistory(handovers.handovers || []); });
  useEffect(() => { load(); }, [date]);
  const rows = useMemo(() => tasks ? [...tasks.immediate, ...tasks.timed, ...tasks.all_day] : [], [tasks]);
  const incomplete = rows.filter((row) => !row.completed);
  const completed = rows.filter((row) => row.completed);
  async function closeShift() { setBusy(true); try { await api.closeHandover({ shift, note }); setNote(""); await load(); } finally { setBusy(false); } }
  return <section className="handover-workspace">
    {history[0] && <article className="previous-handover"><small>이전 근무에서 받은 것 · {history[0].shift_label}</small><p>{history[0].note || "남긴 메모가 없습니다."}</p><time>{new Date(history[0].closed_at).toLocaleString("ko-KR")}</time></article>}
    <div className="handover-groups">
      <details className="handover-group pending">
        <summary><span>다음 근무자가 볼 것</span><b>{incomplete.length}건</b><i aria-hidden="true">⌄</i></summary>
        <div className="handover-list">{incomplete.length ? incomplete.map((row) => <HandoverRow row={row} key={row.id} />) : <p className="handover-empty">다음 근무자에게 넘길 내용이 없습니다.</p>}</div>
      </details>
      <details className="handover-group completed">
        <summary><span>오늘 확인한 것</span><b>{completed.length}/{rows.length}</b><i aria-hidden="true">⌄</i></summary>
        {completed.length ? <div className="handover-list">{completed.map((row) => <HandoverRow row={row} key={row.id} completed />)}</div> : <p className="handover-empty">아직 완료한 업무가 없습니다.</p>}
      </details>
    </div>
    <label className="handover-note"><span>인계 메모</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="다음 근무자가 알아야 할 직접 확인 결과만 남겨 주세요." /></label>
    <footer><select value={shift} onChange={(event) => setShift(event.target.value)}><option value="day">주간</option><option value="evening">저녁</option><option value="night">야간</option></select><button disabled={busy} onClick={closeShift}>인계 마감</button></footer>
  </section>;
}
