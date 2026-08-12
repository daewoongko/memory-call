import { useMemo, useState } from "react";
import { SIZE_MAX, SIZE_MIN, SIZE_STEP, THEMES } from "../theme.js";

export default function WideDisplayDock({ theme, size, onTheme, onSize, onRole }) {
  const [openSetting, setOpenSetting] = useState(null);
  const selectedTheme = useMemo(
    () => THEMES.find((item) => item.id === theme) || THEMES[0],
    [theme],
  );

  const toggle = (name) => {
    setOpenSetting((current) => current === name ? null : name);
  };

  return <aside className="wide-display-dock" aria-label="화면과 역할 설정">
    {openSetting === "size" && <section className="dock-popover" aria-label="글자 크기 설정">
      <header><div><small>글자 설정</small><b>글자 크기 {size}%</b></div><button onClick={() => setOpenSetting(null)} aria-label="글자 설정 닫기">×</button></header>
      <div className="dock-size-control">
        <small>가</small>
        <input type="range" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={size} onChange={(event) => onSize(Number(event.target.value))} aria-label="글자 크기" />
        <strong>가</strong>
      </div>
      <p>화면 배치는 그대로 두고 글자만 조절합니다.</p>
    </section>}

    {openSetting === "view" && <section className="dock-popover dock-view-options" aria-label="화면 보기 설정">
      <header><div><small>화면 설정</small><b>{selectedTheme.label}</b></div><button onClick={() => setOpenSetting(null)} aria-label="화면 설정 닫기">×</button></header>
      <div>{THEMES.map((item) => <button key={item.id} className={theme === item.id ? "on" : ""} onClick={() => onTheme(item.id)}>
        <span>{item.label}</span><small>{item.description}</small>
      </button>)}</div>
    </section>}

    <div className="dock-icon-row">
      <button className="dock-icon-button" onClick={onRole} aria-label="역할 선택 화면으로 이동" title="역할 선택">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 19c.5-3.6 2.2-5.5 5-5.5s4.5 1.9 5 5.5M14 18.5c.4-2.7 1.6-4.1 3.7-4.1 1.7 0 2.8 1 3.3 3"/></svg>
        <span>역할</span>
      </button>
      <button className={`dock-icon-button ${openSetting === "size" ? "on" : ""}`} onClick={() => toggle("size")} aria-label={`글자 크기 설정, 현재 ${size}%`} aria-expanded={openSetting === "size"} title="글자 크기">
        <b aria-hidden="true">Aa</b><span>글자</span>
      </button>
      <button className={`dock-icon-button ${openSetting === "view" ? "on" : ""}`} onClick={() => toggle("view")} aria-label={`화면 설정, 현재 ${selectedTheme.label}`} aria-expanded={openSetting === "view"} title="화면 보기">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" className="fill"/></svg>
        <span>화면</span>
      </button>
    </div>
  </aside>;
}
