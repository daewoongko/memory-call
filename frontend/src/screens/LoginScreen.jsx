import { useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";

function MessageIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4.5 5.5h15v10h-9l-4.5 3v-3H4.5z" />
    <path d="m8 10 2.4 2.2L16 8.7" />
  </svg>;
}

export default function LoginScreen({ onAuthenticated, onSkip }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ phone: "", display_name: "", pin: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const phone = form.phone.replace(/\D/g, "").slice(0, 11);
  const pin = form.pin.replace(/\D/g, "").slice(0, 6);
  const ready = /^01\d{8,9}$/.test(phone) && /^\d{6}$/.test(pin)
    && (mode === "login" || form.display_name.trim());

  function changeMode(nextMode) {
    setMode(nextMode);
    setError("");
    setNotice("");
  }

  function showPendingMessage(message) {
    setError("");
    setNotice(message);
  }

  async function submit(event) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
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
    <header className="login-brand" aria-label="다소니">
      <BrandMark size={78} />
      <img className="login-wordmark" src="/brand/dasoni-wordmark.png" alt="다소니" />
    </header>

    <form className="login-card" onSubmit={submit}>
      <div className="login-tabs" role="tablist" aria-label="계정 시작 방식">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "login"}
          className={mode === "login" ? "on" : ""}
          onClick={() => changeMode("login")}
        >로그인</button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "register"}
          className={mode === "register" ? "on" : ""}
          onClick={() => changeMode("register")}
        >회원가입</button>
      </div>

      <header className="login-card-heading">
        <h1>{mode === "login" ? "오늘도 따뜻한 목소리로 연결할게요" : "소중한 가족을 위한 안심 첫걸음"}</h1>
        <p>{mode === "login" ? "휴대전화 번호와 간편번호로 로그인해 주세요." : "다소니와 함께할 계정을 만들어 주세요."}</p>
      </header>

      {mode === "register" && <label>
        <span>이름</span>
        <input
          autoComplete="name"
          value={form.display_name}
          maxLength={30}
          placeholder="이름을 입력해 주세요"
          onChange={(event) => setForm({ ...form, display_name: event.target.value })}
        />
      </label>}
      <label>
        <span>휴대전화 번호</span>
        <input
          inputMode="tel"
          autoComplete="tel"
          value={phone}
          placeholder="01012345678"
          aria-label="휴대전화 번호"
          onChange={(event) => setForm({ ...form, phone: event.target.value })}
        />
      </label>
      <label>
        <span>간편번호 6자리</span>
        <input
          type="password"
          inputMode="numeric"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={pin}
          placeholder="● ● ● ● ● ●"
          aria-label="간편번호 6자리"
          onChange={(event) => setForm({ ...form, pin: event.target.value })}
        />
      </label>

      {mode === "register" && <p className="login-security-note">휴대전화 번호와 숫자 6자리 간편번호를 사용합니다.</p>}
      {error && <p className="login-feedback error" role="alert">{error}</p>}
      {notice && <p className="login-feedback" role="status">{notice}</p>}

      <button className="login-submit" disabled={!ready || busy}>
        {busy ? "확인하는 중…" : mode === "login" ? "로그인" : "계정 만들기"}
      </button>
      {mode === "login" && <button
        type="button"
        className="login-find"
        onClick={() => showPendingMessage("간편번호 찾기는 준비 중이에요. 관리자에게 문의해 주세요.")}
      >간편번호 찾기</button>}

      <div className="login-social" aria-label="간편 로그인">
        <div className="login-social-title"><span>간편 로그인</span></div>
        <div className="login-social-buttons">
          <button type="button" className="sms" aria-label="문자 인증 로그인" onClick={() => showPendingMessage("문자 인증 로그인은 준비 중이에요.")}>
            <MessageIcon />
          </button>
          <button type="button" className="google" aria-label="Google 로그인" onClick={() => showPendingMessage("Google 로그인은 준비 중이에요.")}>G</button>
          <button type="button" className="naver" aria-label="네이버 로그인" onClick={() => showPendingMessage("네이버 로그인은 준비 중이에요.")}>N</button>
        </div>
      </div>

      {onSkip && <button type="button" className="login-skip" onClick={onSkip} disabled={busy}>
        <b>체험 사용자로 둘러보기</b>
        <small>계정 없이 데모 화면으로 시작해요</small>
      </button>}
    </form>
  </main>;
}
