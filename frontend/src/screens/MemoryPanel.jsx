import { useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * 기억 관리.
 *
 * 명세 FR-05 — AI 는 등록된 기억만 사실로 쓴다.
 * 통화 중 처음 나온 이야기는 여기 '확인 대기'로 쌓이고,
 * 보호자가 승인해야만 다음 통화부터 사실이 된다.
 */

const STATUS = {
  verified: { label: "확인됨", cls: "ok" },
  partial: { label: "일부만 확인", cls: "warn" },
  unverified: { label: "미확인", cls: "" },
  prohibited: { label: "대화 금지", cls: "risk" },
};

const EMPTY = {
  title: "",
  description: "",
  date_text: "",
  location: "",
  status: "verified",
};

export default function MemoryPanel() {
  const [memories, setMemories] = useState([]);
  const [pending, setPending] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    api
      .getMemories()
      .then((r) => {
        setMemories(r.memories);
        setPending(r.pending_recalls);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function guard(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const add = () =>
    form.title.trim() &&
    guard(async () => {
      await api.addMemory(form);
      setForm(EMPTY);
    });

  const decide = (utteranceId, decision) =>
    guard(() => api.reviewRecall(utteranceId, { decision }));

  const setStatus = (memoryId, status) =>
    guard(() => api.patchMemory(memoryId, { status }));

  const remove = (memoryId) =>
    window.confirm("이 기억을 삭제할까요? 되돌릴 수 없어요.") &&
    guard(() => api.deleteMemory(memoryId));

  return (
    <>
      {pending.length > 0 && (
        <section className="recalls">
          <h2>확인이 필요한 이야기 {pending.length}건</h2>
          <p className="hint">
            할아버지가 통화에서 꺼내셨지만 등록되지 않은 내용이에요.
            승인해야 대웅이가 다음 통화부터 사실로 이야기해요.
          </p>
          <ul className="med-list">
            {pending.map((r) => (
              <li key={r.utterance_id} className="recall">
                <div>
                  <b>{r.summary || "새로운 이야기"}</b>
                  {r.quote && <div className="quote">“{r.quote}”</div>}
                </div>
                <div className="med-right">
                  <button
                    className="approve"
                    disabled={busy}
                    onClick={() => decide(r.utterance_id, "approved")}
                  >
                    사실이에요
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => decide(r.utterance_id, "rejected")}
                  >
                    아니에요
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="meds">
        <h2>가족 기억 {memories.length}개</h2>
        <p className="hint">
          여기 등록된 것만 대웅이가 사실로 이야기해요.
          말하면 안 되는 내용은 <b>대화 금지</b>로 바꿔 주세요.
        </p>

        <ul className="med-list">
          {memories.map((m) => {
            const badge = STATUS[m.status] ?? STATUS.unverified;
            return (
              <li key={m.memory_id} className={m.status === "prohibited" ? "off" : ""}>
                <div className="mem-body">
                  <b>{m.title}</b>
                  {m.description && <div className="quote">{m.description}</div>}
                  <div className="row-meta">
                    {[m.date_text, m.location].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <div className="med-right">
                  <span className={`tag ${badge.cls}`}>{badge.label}</span>
                  <select
                    value={m.status}
                    disabled={busy}
                    onChange={(e) => setStatus(m.memory_id, e.target.value)}
                  >
                    <option value="verified">확인됨</option>
                    <option value="partial">일부만 확인</option>
                    <option value="prohibited">대화 금지</option>
                  </select>
                  <button onClick={() => remove(m.memory_id)} aria-label="삭제">
                    ✕
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="med-form">
          <input
            placeholder="기억 제목 (예: 부산 해운대 가족여행)"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <input
            className="narrow"
            placeholder="시기"
            value={form.date_text}
            onChange={(e) => setForm({ ...form, date_text: e.target.value })}
          />
          <input
            className="narrow"
            placeholder="장소"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
          >
            <option value="verified">확인됨</option>
            <option value="partial">일부만 확인</option>
            <option value="prohibited">대화 금지</option>
          </select>
          <button onClick={add} disabled={busy || !form.title.trim()}>
            추가
          </button>
        </div>
        <textarea
          className="mem-desc"
          placeholder="어떤 일이었는지 적어 주세요. 대웅이가 이 내용으로 이야기해요."
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />

        {error && <p className="error">{error}</p>}
      </section>
    </>
  );
}
