import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

const SHIFT = { day: "주간", evening: "저녁", night: "야간" };

export default function HandoverWorkspace({ date, onProgress }) {
  const [tasks, setTasks] = useState(null);
  const [history, setHistory] = useState([]);
  const [shift, setShift] = useState("day");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => Promise.all([api.getCareTasks(date), api.getHandovers()]).then(([taskRows, handovers]) => { setTasks(taskRows); setHistory(handovers.handovers || []); onProgress?.({ completed: taskRows.completed || 0, total: taskRows.total || 0 }); });
  useEffect(() => { load(); }, [date]);
  const rows = useMemo(() => tasks ? [...tasks.immediate, ...tasks.timed, ...tasks.all_day] : [], [tasks]);
  const incomplete = rows.filter((row) => !row.completed);
  const completed = rows.filter((row) => row.completed);
  async function closeShift() { setBusy(true); try { await api.closeHandover({ shift, note }); setNote(""); await load(); } finally { setBusy(false); } }
  return <section className="handover-workspace">
    <header><div><h2>인계</h2><p>{SHIFT[shift]} 근무 · {date}</p></div></header>
    {history[0] && <article className="previous-handover"><small>이전 근무에서 받은 것 · {history[0].shift_label}</small><p>{history[0].note || "남긴 메모가 없습니다."}</p><time>{new Date(history[0].closed_at).toLocaleString("ko-KR")}</time></article>}
    <div className="handover-columns"><section><h3>오늘 확인한 것 <span>{completed.length}/{rows.length}</span></h3>{completed.map((row) => <p key={row.id}><b>{row.elder_name}</b> ✓ {row.title}<time>{row.completed_at ? new Date(row.completed_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "완료"}</time></p>)}</section><section><h3>다음 근무자가 볼 것 <span>{incomplete.length}건</span></h3>{incomplete.map((row) => <p key={row.id}><b>{row.elder_name}</b> · {row.title}<small>{row.status === "missed" ? "예정 시각이 지났으며 기록 대조가 필요합니다." : "확인 대기"}</small></p>)}</section></div>
    <label className="handover-note"><span>인계 메모</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="다음 근무자가 알아야 할 직접 확인 결과만 남겨 주세요." /></label>
    <footer><select value={shift} onChange={(event) => setShift(event.target.value)}><option value="day">주간</option><option value="evening">저녁</option><option value="night">야간</option></select><button disabled={busy} onClick={closeShift}>인계 마감</button></footer>
  </section>;
}
