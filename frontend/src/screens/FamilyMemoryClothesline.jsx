import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api.js";

const EMPTY_FORM = {
  title: "", description: "", date_text: "", happened_year: "",
  location: "", participants: "",
};

function photoOf(memory) {
  return memory?.photo_url || memory?.artwork?.image_url || "";
}

function weekStart(value) {
  const dateOnly = typeof value === "string" && /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const date = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(value || Date.now());
  if (Number.isNaN(date.getTime())) return null;
  const day = (date.getDay() + 6) % 7;
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - day);
  return date;
}

function weekKey(value) {
  const start = weekStart(value);
  if (!start) return "unknown";
  return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`;
}

function weekLabel(value) {
  const start = weekStart(value);
  if (!start) return "확인 시기 미상";
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const startText = `${start.getMonth() + 1}월 ${start.getDate()}일`;
  const endText = `${end.getMonth() + 1}월 ${end.getDate()}일`;
  return `${start.getFullYear()}년 ${startText}–${endText}`;
}

function rotation(memory) {
  const text = String(memory.memory_id || memory.title || "memory");
  const value = [...text].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return `${(value % 7) - 3}deg`;
}

function era(memory) {
  return memory.happened_year ? `${memory.happened_year}년` : (memory.date_text || "시기 미상");
}

function UseDots({ count = 0 }) {
  const visible = Math.min(5, Number(count || 0));
  return <span className="memory-use-dots" aria-label={`AI 통화에 ${count || 0}회 사용`}>
    {Array.from({ length: 5 }, (_, index) => <i className={index < visible ? "on" : ""} key={index} />)}
    <small>{count || 0}회</small>
  </span>;
}

function Polaroid({ memory, onOpen, onDrawer }) {
  const image = photoOf(memory);
  return <li className={`clothesline-memory ${memory.status}`} style={{ "--tilt": rotation(memory) }}>
    <span className="memory-peg" aria-hidden="true" />
    <button type="button" className="memory-polaroid" onClick={() => onOpen(memory)}>
      {image ? <img src={image} alt={memory.title} loading="lazy" /> : <span className="memory-polaroid-text"><small>{era(memory)}</small><b>{memory.title}</b><em>사진 올리기</em></span>}
      <strong>{memory.title}</strong>
      <small>{era(memory)}{memory.location ? ` · ${memory.location}` : ""}</small>
      {memory.status === "partial" && <em className="memory-partial-label">일부만 확인됨</em>}
    </button>
    <UseDots count={memory.used_count} />
    <button type="button" className="memory-to-drawer" onClick={() => onDrawer(memory)}>서랍에 넣기</button>
  </li>;
}

export default function FamilyMemoryClothesline({ elderId = "elder_001", elderName = "어르신" }) {
  const [memories, setMemories] = useState([]);
  const [pending, setPending] = useState([]);
  const [view, setView] = useState("line");
  const [form, setForm] = useState(EMPTY_FORM);
  const [photo, setPhoto] = useState(null);
  const [reviewing, setReviewing] = useState(null);
  const [reviewForm, setReviewForm] = useState(EMPTY_FORM);
  const [basketOpen, setBasketOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const detailFileRef = useRef(null);

  const load = () => api.getMemories(elderId).then((result) => {
    setMemories(result.memories || []);
    setPending(result.pending_recalls || []);
  });
  useEffect(() => { load().catch((reason) => setError(reason.message)); }, [elderId]);

  async function run(action) {
    setBusy(true); setError("");
    try { await action(); await load(); } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  const hung = useMemo(() => memories
    .filter((memory) => memory.conversation_allowed && ["verified", "partial"].includes(memory.status))
    .sort((left, right) => (left.happened_year ?? 9999) - (right.happened_year ?? 9999)
      || String(left.created_at).localeCompare(String(right.created_at))), [memories]);
  const drawer = useMemo(() => memories.filter((memory) => !memory.conversation_allowed || memory.status === "prohibited"), [memories]);
  const weeklyLines = useMemo(() => {
    const groups = new Map();
    hung.forEach((memory) => {
      const key = weekKey(memory.created_at);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(memory);
    });
    return [...groups.entries()].sort(([left], [right]) => right.localeCompare(left));
  }, [hung]);

  function beginReview(recall, status) {
    setReviewing({ ...recall, status });
    setReviewForm({ ...EMPTY_FORM, title: recall.summary || "확인된 기억", description: recall.quote || "" });
  }

  const approveRecall = () => reviewing && reviewForm.title.trim() && run(async () => {
    await api.reviewRecall(reviewing.utterance_id, {
      decision: "approved", status: reviewing.status,
      title: reviewForm.title.trim(), description: reviewForm.description.trim(),
      date_text: reviewForm.date_text.trim(), location: reviewForm.location.trim(),
      happened_year: reviewForm.happened_year ? Number(reviewForm.happened_year) : null,
    }, elderId);
    setReviewing(null); setReviewForm(EMPTY_FORM);
  });

  const createMemory = () => form.title.trim() && run(async () => {
    const created = await api.addMemory({
      title: form.title.trim(), description: form.description.trim(),
      date_text: form.date_text.trim(), location: form.location.trim(),
      participants: form.participants.split(",").map((item) => item.trim()).filter(Boolean),
      happened_year: form.happened_year ? Number(form.happened_year) : null,
      status: "verified", conversation_allowed: true,
    }, elderId);
    if (photo) await api.uploadMemoryPhoto(created.memory_id, photo, elderId);
    setForm(EMPTY_FORM); setPhoto(null);
    if (fileRef.current) fileRef.current.value = "";
  });

  async function uploadExistingPhoto(file) {
    if (!file || !selected) return;
    setBusy(true); setError("");
    try {
      const updated = await api.uploadMemoryPhoto(selected.memory_id, file, elderId);
      setSelected((current) => ({ ...current, photo_url: updated.photo_url }));
      await load();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
      if (detailFileRef.current) detailFileRef.current.value = "";
    }
  }

  return <div className="family-memory-clothesline">
    <header className="family-memory-title">
      <div><span>FAMILY ARCHIVE</span><h1>가족 추억함</h1><p>{elderName} 어르신의 시간을 가족이 확인하고 함께 걸어두는 곳이에요.</p></div>
      <div className="memory-view-toggle"><button className={view === "line" ? "on" : ""} onClick={() => setView("line")}>빨랫줄</button><button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")}>보관함</button></div>
    </header>

    <section className={`hung-memory-section ${view}`}>
      <header><div><small>01</small><h2>걸린 추억</h2></div><p>확인된 주마다 한 줄 · 각 줄 안에서는 추억 시대순</p></header>
      {!weeklyLines.length && <div className="empty-clothesline"><span /><b>첫 추억을 걸어보세요</b><p>사진이 없어도 이야기 카드부터 걸 수 있어요.</p></div>}
      {view === "line" ? weeklyLines.map(([key, items]) => <section className="memory-week-line" key={key}>
        <h3>{weekLabel(key)}</h3><div className="memory-rope" aria-hidden="true" />
        <ul>{items.map((memory) => <Polaroid memory={memory} key={memory.memory_id} onOpen={setSelected} onDrawer={(item) => run(() => api.patchMemory(item.memory_id, { conversation_allowed: false }))} />)}</ul>
      </section>) : <ul className="memory-vault-grid">{hung.map((memory) => <Polaroid memory={memory} key={memory.memory_id} onOpen={setSelected} onDrawer={(item) => run(() => api.patchMemory(item.memory_id, { conversation_allowed: false }))} />)}</ul>}
    </section>

    <section className="memory-basket-section">
      <header><div><small>02</small><h2>아직 걸지 않은 이야기</h2></div><button type="button" className="memory-basket-toggle" aria-expanded={basketOpen} onClick={() => setBasketOpen((value) => !value)}><b>{pending.length}건</b><span>{basketOpen ? "접기" : "펼치기"}</span><i aria-hidden="true">{basketOpen ? "⌃" : "⌄"}</i></button></header>
      {basketOpen && <div className="memory-basket">
        {pending.map((recall) => <article key={recall.utterance_id}>
          <div className="candidate-artwork">{recall.artwork?.image_url ? <img src={recall.artwork.image_url} alt={recall.artwork.alt_text || "확인 전 그림"} /> : <span>이야기</span>}<i>확인 전 그림</i></div>
          <div><time>{new Date(recall.created_at).toLocaleDateString("ko-KR")}</time><h3>{recall.summary || "새로운 이야기"}</h3>{recall.quote && <q>{recall.quote}</q>}
            <nav><button className="approve" onClick={() => beginReview(recall, "verified")}>걸기</button><button onClick={() => beginReview(recall, "partial")}>일부만</button><button onClick={() => run(() => api.reviewRecall(recall.utterance_id, { decision: "rejected" }, elderId))}>아니에요</button><button className="later">나중에</button></nav>
          </div>
        </article>)}
        {!pending.length && <p>확인을 기다리는 새 이야기가 없습니다.</p>}
      </div>}
    </section>

    <section className="memory-new-section">
      <header><div><small>03</small><h2>새로 걸기</h2></div><p>등록하면 다음 AI 통화부터 확인된 가족 추억으로 사용합니다.</p></header>
      <div className="memory-new-form">
        <button type="button" className="memory-photo-picker" onClick={() => fileRef.current?.click()}>{photo ? <><b>{photo.name}</b><span>다른 사진 선택</span></> : <><b>＋ 사진 올리기</b><span>jpg · png · webp, 최대 12MB</span></>}</button>
        <input ref={fileRef} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setPhoto(event.target.files?.[0] || null)} />
        <div className="memory-new-fields">
          <input placeholder="추억 제목" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
          <input type="number" min="1800" max="2100" placeholder="일어난 연도 (예: 1975)" value={form.happened_year} onChange={(event) => setForm({ ...form, happened_year: event.target.value })} />
          <input placeholder="시기 (예: 1975년 봄)" value={form.date_text} onChange={(event) => setForm({ ...form, date_text: event.target.value })} />
          <input placeholder="장소" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} />
          <input placeholder="함께한 사람 (쉼표로 구분)" value={form.participants} onChange={(event) => setForm({ ...form, participants: event.target.value })} />
          <textarea placeholder="어떤 추억인지 적어주세요" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
          <button className="memory-hang-button" disabled={busy || !form.title.trim()} onClick={createMemory}>추억 걸기</button>
        </div>
      </div>
    </section>

    <section className="memory-drawer-section">
      <button type="button" onClick={() => setDrawerOpen((value) => !value)}><span><small>04</small><b>서랍에 넣어둔 추억</b></span><em>보류 {drawer.filter((item) => item.status !== "prohibited").length} · 대화 금지 {drawer.filter((item) => item.status === "prohibited").length}</em><i>{drawerOpen ? "⌃" : "⌄"}</i></button>
      {drawerOpen && <div>{drawer.map((memory) => <article key={memory.memory_id}><span>{era(memory)}</span><b>{memory.title}</b><button onClick={() => run(() => api.patchMemory(memory.memory_id, { status: memory.status === "prohibited" ? "verified" : memory.status, conversation_allowed: true }))}>다시 걸기</button></article>)}{!drawer.length && <p>서랍에 넣어둔 추억이 없습니다.</p>}</div>}
    </section>
    {error && <p className="error">{error}</p>}

    {reviewing && <div className="memory-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setReviewing(null)}><section className="memory-review-modal" role="dialog" aria-modal="true"><header><div><small>{reviewing.status === "partial" ? "일부만 확인" : "걸기 전 확인"}</small><h2>이야기를 다듬어주세요</h2></div><button onClick={() => setReviewing(null)} aria-label="닫기">×</button></header><div className="memory-review-fields"><input value={reviewForm.title} onChange={(event) => setReviewForm({ ...reviewForm, title: event.target.value })} placeholder="제목" /><input type="number" min="1800" max="2100" value={reviewForm.happened_year} onChange={(event) => setReviewForm({ ...reviewForm, happened_year: event.target.value })} placeholder="일어난 연도" /><input value={reviewForm.date_text} onChange={(event) => setReviewForm({ ...reviewForm, date_text: event.target.value })} placeholder="시기" /><input value={reviewForm.location} onChange={(event) => setReviewForm({ ...reviewForm, location: event.target.value })} placeholder="장소" /><textarea value={reviewForm.description} onChange={(event) => setReviewForm({ ...reviewForm, description: event.target.value })} placeholder="이야기" /></div><button className="primary" onClick={approveRecall} disabled={busy || !reviewForm.title.trim()}>확인하고 줄에 걸기</button></section></div>}

    {selected && <div className="memory-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setSelected(null)}><section className="memory-detail-modal" role="dialog" aria-modal="true"><button className="close" onClick={() => setSelected(null)} aria-label="닫기">×</button>{photoOf(selected) ? <img src={photoOf(selected)} alt={selected.title} /> : <div className="memory-detail-placeholder">{selected.title}</div>}<div><span>{era(selected)}{selected.location ? ` · ${selected.location}` : ""}</span><h2>{selected.title}</h2><p>{selected.description || "가족이 확인한 추억입니다."}</p><UseDots count={selected.used_count} /><button type="button" className="memory-detail-photo-button" onClick={() => detailFileRef.current?.click()} disabled={busy}>{photoOf(selected) ? "사진 바꾸기" : "이 추억에 사진 올리기"}</button><input ref={detailFileRef} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => uploadExistingPhoto(event.target.files?.[0])} /></div></section></div>}
  </div>;
}
