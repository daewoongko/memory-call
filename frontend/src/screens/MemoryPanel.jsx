import { useEffect, useMemo, useState } from "react";
import * as api from "../api.js";

const STATUS = {
  verified: { label: "확인됨", cls: "ok", icon: "✓" },
  partial: { label: "일부만 확인", cls: "warn", icon: "◐" },
  unverified: { label: "미확인", cls: "", icon: "?" },
  prohibited: { label: "대화 금지", cls: "risk", icon: "!" },
};

const FILTERS = [
  { id: "all", label: "전체" },
  { id: "verified", label: "확인됨" },
  { id: "partial", label: "일부 확인" },
  { id: "prohibited", label: "대화 금지" },
];

const EMPTY = { title: "", description: "", date_text: "", location: "", status: "verified" };

function memoryIcon(memory) {
  const text = `${memory.title} ${memory.description}`;
  if (/여행|바다|고향|낚시|시장|공원|드라이브/.test(text)) return "⌂";
  if (/생신|입학|합격|설날|잔치/.test(text)) return "☆";
  if (/음식|붕어빵|수박|핫도그/.test(text)) return "♨";
  if (/직업|학교|일|텃밭/.test(text)) return "◇";
  return "♡";
}

function lastUsed(value) {
  if (!value) return "아직 통화에 사용되지 않음";
  return `${new Date(value).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} 마지막 사용`;
}

export default function MemoryPanel({ elderId = "elder_001", elderName = "어르신" }) {
  const [memories, setMemories] = useState([]);
  const [pending, setPending] = useState([]);
  const [filter, setFilter] = useState("all");
  const [form, setForm] = useState(EMPTY);
  const [pendingOpen, setPendingOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.getMemories(elderId).then((result) => {
    setMemories(result.memories);
    setPending(result.pending_recalls);
  }).catch((e) => setError(e.message));

  useEffect(() => { load(); }, [elderId]);

  async function guard(fn) {
    setBusy(true); setError("");
    try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const add = () => form.title.trim() && guard(async () => {
    await api.addMemory(form, elderId);
    setForm(EMPTY);
  });
  const decide = (utteranceId, decision) => guard(() => api.reviewRecall(utteranceId, { decision }, elderId));
  const setStatus = (memoryId, status) => guard(() => api.patchMemory(memoryId, { status }));
  const remove = (memoryId) => window.confirm("이 기억을 삭제할까요? 되돌릴 수 없어요.") && guard(() => api.deleteMemory(memoryId));

  const counts = useMemo(() => Object.keys(STATUS).reduce((out, status) => {
    out[status] = memories.filter((memory) => memory.status === status).length;
    return out;
  }, {}), [memories]);
  const usable = memories.filter((memory) => memory.conversation_allowed && memory.status !== "prohibited").length;
  const verifiedRate = memories.length ? Math.round((counts.verified || 0) / memories.length * 100) : 0;
  const shown = filter === "all" ? memories : memories.filter((memory) => memory.status === filter);

  const people = useMemo(() => {
    const byName = {};
    memories.filter((memory) => memory.status !== "prohibited").forEach((memory) => {
      (memory.participants || []).forEach((name) => {
        if (!name || [elderName, "할아버지", "할머니", "어르신", "가족", "온 가족"].includes(name)) return;
        const slot = byName[name] || { name, memories: 0, verified: 0 };
        slot.memories += 1;
        if (memory.status === "verified") slot.verified += 1;
        byName[name] = slot;
      });
    });
    return Object.values(byName).sort((a, b) => b.memories - a.memories).slice(0, 6);
  }, [memories, elderName]);

  return <div className="memory-dashboard">
    <section className="memory-hero dashboard-card">
      <div className="memory-ring" style={{ "--memory-rate": `${verifiedRate * 3.6}deg` }}>
        <div><b>{verifiedRate}%</b><span>사실 확인</span></div>
      </div>
      <div className="memory-hero-copy">
        <p className="eyebrow">기억 연결 현황</p>
        <h2>{elderName} 어르신과 가족의 기억 {memories.length}개</h2>
        <p>확인된 기억만 AI가 현재 대화의 사실로 사용합니다. 불확실하거나 민감한 기억은 별도로 구분합니다.</p>
        <div className="memory-metrics">
          <span><b>{usable}</b>대화 가능</span><span><b>{counts.partial || 0}</b>추가 확인</span><span className="risk"><b>{counts.prohibited || 0}</b>대화 금지</span><span><b>{pending.length}</b>승인 대기</span>
        </div>
      </div>
      <div className="memory-status-map" aria-label="기억 확인 상태 분포">
        {Object.entries(STATUS).map(([status, info]) => <div key={status}>
          <span><i className={info.cls}>{info.icon}</i>{info.label}</span><b>{counts[status] || 0}</b>
          <div><em style={{ width: `${memories.length ? (counts[status] || 0) / memories.length * 100 : 0}%` }} /></div>
        </div>)}
      </div>
    </section>

    <section className="dashboard-card people-card">
      <header><div><h2>기억으로 연결된 가족</h2><p>등록된 추억에 함께 등장하는 가족 기준입니다.</p></div></header>
      <div className="memory-people">
        {people.map((person) => <article key={person.name}>
          <div className="person-initial">{person.name.slice(0, 1)}</div>
          <b>{person.name}</b><span>{person.memories}개의 기억</span><small>확인됨 {person.verified}</small>
        </article>)}
        {!people.length && <p className="empty-state">기억에 참여한 가족을 등록하면 여기에 연결 관계가 표시됩니다.</p>}
      </div>
    </section>

    {pending.length > 0 && <section className={`dashboard-card pending-memory ${pendingOpen ? "" : "collapsed"}`}>
      <header><div><h2>확인이 필요한 이야기</h2><p>{pendingOpen ? "통화에서 처음 나왔으며 아직 가족이 사실 여부를 확인하지 않은 내용입니다." : `${pending[0]?.summary || "새로운 이야기"}${pending.length > 1 ? ` 외 ${pending.length - 1}건` : ""}`}</p></div>
        <div className="pending-head-actions"><span className="count-badge danger">{pending.length}건</span><button onClick={() => setPendingOpen((value) => !value)}>{pendingOpen ? "접기" : "확인하기"}<i>{pendingOpen ? "⌃" : "⌄"}</i></button></div>
      </header>
      {pendingOpen && <div className="pending-grid">{pending.map((recall) => <article key={recall.utterance_id}>
        <div><b>{recall.summary || "새로운 이야기"}</b>{recall.quote && <q>{recall.quote}</q>}</div>
        <div><button className="approve" disabled={busy} onClick={() => decide(recall.utterance_id, "approved")}>사실이에요</button><button disabled={busy} onClick={() => decide(recall.utterance_id, "rejected")}>아니에요</button></div>
      </article>)}</div>}
    </section>}

    <section className="memory-library dashboard-card">
      <header><div><h2>가족 기억 보관함</h2><p>카드를 눌러 상태를 바꾸거나 민감한 기억을 대화에서 제외할 수 있습니다.</p></div>
        <div className="memory-filters">{FILTERS.map((item) => <button key={item.id} className={filter === item.id ? "on" : ""} onClick={() => setFilter(item.id)}>{item.label}</button>)}</div>
      </header>
      <div className="memory-card-grid">{shown.map((memory) => {
        const badge = STATUS[memory.status] || STATUS.unverified;
        return <article className={`memory-card ${memory.status}`} key={memory.memory_id}>
          {memory.artwork && <figure className="memory-artwork">
            <img src={memory.artwork.image_url} alt={memory.artwork.alt_text} loading="lazy" />
            <figcaption>확인된 가족 기억을 바탕으로 만든 이미지</figcaption>
          </figure>}
          <div className="memory-card-top"><span className="memory-icon">{memoryIcon(memory)}</span><span className={`tag ${badge.cls}`}>{badge.label}</span></div>
          <h3>{memory.title}</h3>
          <p>{memory.description || "상세 이야기가 아직 등록되지 않았습니다."}</p>
          <div className="memory-meta">
            {memory.date_text && <span>◷ {memory.date_text}</span>}{memory.location && <span>⌖ {memory.location}</span>}
          </div>
          {memory.participants?.length > 0 && <div className="participant-tags">{memory.participants.map((name) => <span key={name}>{name}</span>)}</div>}
          <div className="memory-use"><b>통화 사용 {memory.used_count || 0}회</b><span>{lastUsed(memory.last_used_at)}</span></div>
          <div className="memory-actions"><select value={memory.status} disabled={busy} onChange={(event) => setStatus(memory.memory_id, event.target.value)}>
            <option value="verified">확인됨</option><option value="partial">일부만 확인</option><option value="prohibited">대화 금지</option>
          </select><button onClick={() => remove(memory.memory_id)} aria-label={`${memory.title} 삭제`}>삭제</button></div>
        </article>;
      })}</div>
      {!shown.length && <p className="empty-state">이 상태의 기억이 없습니다.</p>}
    </section>

    <section className="memory-add dashboard-card">
      <header><div><h2>새 가족 기억 등록</h2><p>확실한 사실과 아직 불확실한 부분을 구분해서 적어 주세요.</p></div></header>
      <div className="memory-form-grid">
        <input placeholder="기억 제목 (예: 부산 해운대 가족여행)" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
        <input placeholder="시기" value={form.date_text} onChange={(event) => setForm({ ...form, date_text: event.target.value })} />
        <input placeholder="장소" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} />
        <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="verified">확인됨</option><option value="partial">일부만 확인</option><option value="prohibited">대화 금지</option></select>
        <textarea placeholder="어떤 일이었는지 적어 주세요. AI 가족이 이 내용으로 이야기합니다." value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
        <button onClick={add} disabled={busy || !form.title.trim()}>기억 추가</button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  </div>;
}
