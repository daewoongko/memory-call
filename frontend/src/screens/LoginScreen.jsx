import { useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";

export default function LoginScreen({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ phone: "", display_name: "", pin: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const phone = form.phone.replace(/\D/g, "").slice(0, 11);
  const pin = form.pin.replace(/\D/g, "").slice(0, 6);
  const ready = /^01\d{8,9}$/.test(phone) && /^\d{6}$/.test(pin)
    && (mode === "login" || form.display_name.trim());

  async function submit(event) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      const payload = { phone, pin, ...(mode === "register" ? { display_name: form.display_name.trim() } : {}) };
      const result = mode === "register"
        ? await api.registerAccount(payload)
        : await api.loginAccount(payload);
      api.saveAuthToken(result.token);
      onAuthenticated(result.user);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="login-screen">
    <section className="login-welcome">
      <BrandMark size={150} />
      <p className="eyebrow">가족의 목소리로 이어지는 돌봄</p>
      <h1>다소니에 오신 것을<br />환영해요</h1>
      <p>한 계정으로 어르신·가족·요양 담당자 역할을 함께 사용할 수 있어요.</p>
    </section>

    <form className="login-card" onSubmit={submit}>
      <div className="login-tabs" role="tablist" aria-label="로그인 방식">
        <button type="button" className={mode === "login" ? "on" : ""} onClick={() => { setMode("login"); setError(""); }}>로그인</button>
        <button type="button" className={mode === "register" ? "on" : ""} onClick={() => { setMode("register"); setError(""); }}>처음 시작</button>
      </div>
      <header>
        <h2>{mode === "login" ? "다시 만나서 반가워요" : "내 계정을 만들게요"}</h2>
        <p>휴대전화 번호와 숫자 6자리 간편번호를 사용합니다.</p>
      </header>
      {mode === "register" && <label>
        <span>이름</span>
        <input autoComplete="name" value={form.display_name} maxLength={30} placeholder="이름을 입력해 주세요" onChange={(event) => setForm({ ...form, display_name: event.target.value })} />
      </label>}
      <label>
        <span>휴대전화 번호</span>
        <input inputMode="tel" autoComplete="tel" value={phone} placeholder="01012345678" onChange={(event) => setForm({ ...form, phone: event.target.value })} />
      </label>
      <label>
        <span>간편번호 6자리</span>
        <input type="password" inputMode="numeric" autoComplete={mode === "login" ? "current-password" : "new-password"} value={pin} placeholder="● ● ● ● ● ●" onChange={(event) => setForm({ ...form, pin: event.target.value })} />
      </label>
      {mode === "register" && <p className="login-security-note">문자 본인 인증 공급자 연결 전 내부 운영용 로그인입니다. 다른 서비스와 같은 간편번호는 사용하지 마세요.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <button className="login-submit" disabled={!ready || busy}>{busy ? "확인하는 중…" : mode === "login" ? "로그인" : "계정 만들기"}</button>
    </form>
  </main>;
}
