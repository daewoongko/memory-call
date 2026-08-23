import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

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
    <header><h2>인계</h2></header>
    {history[0] && <article className="previous-handover"><small>이전 근무에서 받은 것 · {history[0].shift_label}</small><p>{history[0].note || "남긴 메모가 없습니다."}</p><time>{new Date(history[0].closed_at).toLocaleString("ko-KR")}</time></article>}
    <div className="handover-groups">
      <section className="handover-group pending">
        <h3><span>다음 근무자가 볼 것</span><b>{incomplete.length}건</b></h3>
        <div className="handover-list">{incomplete.length ? incomplete.map((row) => <article className="handover-item" key={row.id}>
          <strong>{row.elder_name}</strong><p>{row.title}</p><small className={row.status === "missed" ? "missed" : "waiting"}>{row.status === "missed" ? "기록 대조 필요" : "확인 대기"}</small>
        </article>) : <p className="handover-empty">다음 근무자에게 넘길 내용이 없습니다.</p>}</div>
      </section>
      <section className="handover-group completed">
        <h3><span>오늘 확인한 것</span><b>{completed.length}/{rows.length}</b></h3>
        {completed.length ? <div className="handover-list">{completed.map((row) => <article className="handover-item" key={row.id}>
          <strong>{row.elder_name}</strong><p>{row.title}</p><time>{row.completed_at ? new Date(row.completed_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "완료"}</time>
        </article>)}</div> : <p className="handover-empty">아직 완료한 업무가 없습니다.</p>}
      </section>
    </div>
    <label className="handover-note"><span>인계 메모</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="다음 근무자가 알아야 할 직접 확인 결과만 남겨 주세요." /></label>
    <footer><select value={shift} onChange={(event) => setShift(event.target.value)}><option value="day">주간</option><option value="evening">저녁</option><option value="night">야간</option></select><button disabled={busy} onClick={closeShift}>인계 마감</button></footer>
  </section>;
}
