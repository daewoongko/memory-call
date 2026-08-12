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
    <button className="dock-banner dock-role-banner" onClick={onRole}>
      <span className="dock-banner-icon">역할</span>
      <span className="dock-banner-copy"><small>사용 화면</small><b>역할 선택</b></span>
      <i aria-hidden="true">↗</i>
    </button>

    <section className={`dock-setting ${openSetting === "size" ? "open" : ""}`}>
      <button className="dock-banner" onClick={() => toggle("size")} aria-expanded={openSetting === "size"}>
        <span className="dock-banner-icon">Aa</span>
        <span className="dock-banner-copy"><small>글자 설정</small><b>글자 크기 {size}%</b></span>
        <i aria-hidden="true">⌄</i>
      </button>
      {openSetting === "size" && <div className="dock-setting-panel dock-size-panel">
        <div><small>가</small><input type="range" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={size} onChange={(event) => onSize(Number(event.target.value))} aria-label="글자 크기" /><strong>가</strong></div>
        <p>화면 구성은 유지하고 글자만 조절합니다.</p>
      </div>}
    </section>

    <section className={`dock-setting ${openSetting === "view" ? "open" : ""}`}>
      <button className="dock-banner" onClick={() => toggle("view")} aria-expanded={openSetting === "view"}>
        <span className="dock-banner-icon">◐</span>
        <span className="dock-banner-copy"><small>화면 설정</small><b>{selectedTheme.label}</b></span>
        <i aria-hidden="true">⌄</i>
      </button>
      {openSetting === "view" && <div className="dock-setting-panel dock-view-options">
        {THEMES.map((item) => <button key={item.id} className={theme === item.id ? "on" : ""} onClick={() => onTheme(item.id)}>
          <span>{item.label}</span><small>{item.description}</small>
        </button>)}
      </div>}
    </section>
  </aside>;
}
