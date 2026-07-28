import { useEffect, useState } from "react";
import * as api from "../api.js";
import Transcript from "./Transcript.jsx";
import { BarRows, DayStrip, Donut } from "../components/Charts.jsx";

/**
 * 카테고리별 리포트.
 *
 * 통화 기록만 늘어놓으면 보호자가 무엇을 봐야 할지 모른다.
 * 명세 FR-11/12 를 네 갈래로 나눠 궁금한 쪽부터 열어보게 한다.
 */

const CATEGORIES = [
  { id: "insight", label: "인사이트" },
  { id: "talk", label: "대화" },
  { id: "safety", label: "안전" },
  { id: "life", label: "생활" },
];

const RISK_LABEL = {
  fall: "낙상", chest_pain: "가슴 통증", breathing: "호흡 곤란",
  lost: "길 잃음", overdose: "약 과다 복용 의심",
  self_harm: "정서적 위기 표현", intrusion: "침입", fire: "화재",
};

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = d.toDateString() === new Date().toDateString();
  const t = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  return today ? `오늘 ${t}` : `${d.getMonth() + 1}월 ${d.getDate()}일 ${t}`;
}

export default function ReportTabs({ summary, days, onDays, onReload }) {
  const [tab, setTab] = useState("insight");
  const [calls, setCalls] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [report, setReport] = useState(null);
  const [showRaw, setShowRaw] = useState(false);
  const [meds, setMeds] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getReports().then((r) => setCalls(r.calls)).catch(() => {});
    api.getMedications().then((r) => setMeds(r.today)).catch(() => {});
    api.getSchedules().then((r) => setSchedules(r.upcoming)).catch(() => {});
  }, []);

  async function openCall(callId) {
    if (openId === callId) return setOpenId(null);
    setOpenId(callId);
    setReport(null);
    setShowRaw(false);
    try {
      setReport(await api.getReport(callId));
    } catch {
      setReport(null);
    }
  }

  async function ack(eventId) {
    setBusy(true);
    try {
      await api.acknowledgeRisk(eventId);
      await onReload();
    } finally {
      setBusy(false);
    }
  }

  const unread = summary.risks.filter((r) => !r.acknowledged);
  const medTotal = summary.medication.confirmed + summary.medication.needs_check;

  return (
    <>
      <div className="cat-tabs">
        {CATEGORIES.map((c) => (
          <button key={c.id} className={tab === c.id ? "on" : ""} onClick={() => setTab(c.id)}>
            {c.label}
          </button>
        ))}
      </div>

      {tab === "insight" && (
        <div className="panel">
          <div className="panel-head">
            <h3>최근 {days}일</h3>
            <div className="range">
              {[7, 30].map((d) => (
                <button key={d} className={days === d ? "on" : ""} onClick={() => onDays(d)}>
                  {d}일
                </button>
              ))}
            </div>
          </div>

          {summary.summary && <p className="lead">{summary.summary}</p>}

          <div className="change-list">
            {summary.changes?.length ? (
              summary.changes.map((c, i) => (
                <div key={i} className={`change ${c.good ? "good" : "bad"}`}>
                  <span>{c.label}</span>
                  <b>{c.text}</b>
                </div>
              ))
            ) : (
              <p className="hint">비교할 지난 기간 기록이 아직 없어요.</p>
            )}
          </div>

          <div className="chart-row">
            <Donut
              value={summary.medication.confirmed}
              total={medTotal}
              label="복약 확인"
            />
            <div className="stat-col">
              <div className="stat"><b>{summary.calls}</b><span>통화</span></div>
              <div className="stat"><b>{Math.round(summary.total_seconds / 60)}</b><span>분</span></div>
              <div className={`stat${summary.risks.length ? " danger" : ""}`}>
                <b>{summary.risks.length}</b><span>위험 신호</span>
              </div>
            </div>
          </div>

          <div className="chart-block">
            <h4>날짜별 통화</h4>
            <DayStrip byDay={summary.by_day} days={days} />
          </div>

          {summary.guardian_actions?.length > 0 && (
            <div className="highlight">
              <h4>이번 주 확인하면 좋을 일</h4>
              <ul>{summary.guardian_actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {tab === "talk" && (
        <div className="panel">
          {summary.top_repeats?.length > 0 && (
            <div className="chart-block">
              <h4>자주 되물으신 질문</h4>
              <BarRows
                items={summary.top_repeats.map((r) => ({
                  label: r.question,
                  value: r.count,
                }))}
              />
            </div>
          )}

          <h3>통화별 기록</h3>
          {!calls.length && <p className="hint">아직 통화 기록이 없어요.</p>}
          <ul className="call-list">
            {calls.map((c) => (
              <li key={c.call_id}>
                <button className="call-row" onClick={() => openCall(c.call_id)}>
                  <div className="row-top">
                    <span className="row-when">{when(c.started_at)}</span>
                    <span className="row-meta">{c.duration_sec ?? 0}초</span>
                  </div>
                  <div className="tags">
                    {c.risk_count > 0 && <span className="tag risk">위험 {c.risk_count}</span>}
                    {c.repeat_count > 0 && <span className="tag">반복 {c.repeat_count}</span>}
                  </div>
                </button>

                {openId === c.call_id && (
                  <div className="report">
                    {!report && <p className="hint">불러오는 중…</p>}
                    {report && (
                      <>
                        <p className="lead">{report.summary}</p>
                        {report.new_recalls?.length > 0 && (
                          <div className="highlight warn">
                            <h4>확인이 필요한 이야기</h4>
                            <ul>
                              {report.new_recalls.map((r, i) => (
                                <li key={i}>{r.summary || r.quote}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <button className="raw-toggle" onClick={() => setShowRaw((v) => !v)}>
                          {showRaw ? "전체 대화 접기" : "전체 대화 보기"}
                        </button>
                        {showRaw && <Transcript callId={c.call_id} />}
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {tab === "safety" && (
        <div className="panel">
          {unread.length > 0 ? (
            <div className="highlight danger">
              <h4>확인하지 않은 위험 알림 {unread.length}건</h4>
              <ul>
                {unread.map((r) => (
                  <li key={r.event_id} className="ack-row">
                    <div>
                      <b>{RISK_LABEL[r.type] ?? r.type}</b>
                      <span className="row-meta"> {when(r.at)}</span>
                      {r.evidence && <div className="quote">“{r.evidence}”</div>}
                    </div>
                    <button disabled={busy} onClick={() => ack(r.event_id)}>확인함</button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="hint">확인하지 않은 위험 알림이 없어요.</p>
          )}

          {summary.risks.length > 0 && (
            <>
              <h3>지난 {days}일 위험 신호</h3>
              <ul className="plain">
                {summary.risks.map((r) => (
                  <li key={r.event_id} className={r.acknowledged ? "off" : ""}>
                    <b>{RISK_LABEL[r.type] ?? r.type}</b>
                    <span className="row-meta"> {when(r.at)}</span>
                    {r.acknowledged && <span className="tag ok">확인함</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {tab === "life" && (
        <div className="panel">
          <h3>오늘 복약</h3>
          <ul className="plain">
            {meds.map((m) => (
              <li key={m.schedule_id} className={m.confirmed ? "" : "off"}>
                <b>{m.scheduled_time}</b> {m.medication_name}
                <span className={`tag ${m.confirmed ? "ok" : ""}`}>
                  {m.confirmed ? "확인됨" : "아직"}
                </span>
              </li>
            ))}
            {!meds.length && <li className="hint">등록된 복약 일정이 없어요.</li>}
          </ul>

          <h3>다가오는 일정</h3>
          <ul className="plain">
            {schedules.map((s) => (
              <li key={s.schedule_id} className={s.used_in_call ? "" : "off"}>
                <b>{s.date.slice(5)}</b> {s.title}
                <span className={`tag ${s.used_in_call ? "ok" : ""}`}>
                  {s.used_in_call ? "대화에 사용" : "미확정"}
                </span>
              </li>
            ))}
            {!schedules.length && <li className="hint">다가오는 일정이 없어요.</li>}
          </ul>
        </div>
      )}
    </>
  );
}
