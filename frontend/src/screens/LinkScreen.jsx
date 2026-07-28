import { useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * 기기 연동.
 *
 * 보호자가 코드를 만들고 어르신 기기에 입력한다.
 * 아이디와 비밀번호를 쓰지 않는 이유는 치매가 있는 분이 입력할 수 없기 때문이다.
 */
export default function LinkScreen({ role, onLinked, onSkip }) {
  const [code, setCode] = useState("");
  const [issued, setIssued] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (role !== "guardian") return;
    api.issueLinkCode().then(setIssued).catch((e) => setError(e.message));
  }, [role]);

  async function submit() {
    if (code.length !== 6) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.verifyLinkCode(code);
      onLinked(r.elder_id, r.name);
    } catch (e) {
      setError(e.message);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (role === "guardian") {
    return (
      <div className="screen link">
        <h1>어르신 기기에 이 번호를 넣어주세요</h1>

        {issued ? (
          <>
            <div className="code-big">{issued.code}</div>
            <p className="hint">{issued.valid_minutes}분 동안 쓸 수 있어요</p>
          </>
        ) : (
          <p className="hint">번호를 만드는 중…</p>
        )}

        {error && <p className="error">{error}</p>}

        <button className="pill" onClick={onSkip}>
          다 넣었어요
        </button>
      </div>
    );
  }

  return (
    <div className="screen link">
      <h1>보호자에게 받은 번호를 넣어주세요</h1>

      <input
        className="code-input"
        inputMode="numeric"
        maxLength={6}
        placeholder="000000"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />

      {error && <p className="error">{error}</p>}

      <button className="pill" onClick={submit} disabled={busy || code.length !== 6}>
        연결하기
      </button>
      <button className="text-link" onClick={onSkip}>
        나중에 하기
      </button>
    </div>
  );
}
