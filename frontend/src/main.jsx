import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/gaegu/korean-400.css";
import "@fontsource/gaegu/korean-700.css";
import "@fontsource/gowun-dodum/korean-400.css";
import App from "./App.jsx";
import "./styles.css";
import "./storybook-theme.css";

// Android's status and navigation bars are outside the web viewport.  Keep a
// pixel-accurate height variable so installed PWAs do not lay out against the
// physical screen height and lose the fourth family card behind system UI.
function syncAppViewportHeight() {
  const height = window.visualViewport?.height || window.innerHeight;
  if (height > 0) {
    document.documentElement.style.setProperty("--app-height", `${Math.round(height)}px`);
  }
}

syncAppViewportHeight();
window.addEventListener("resize", syncAppViewportHeight, { passive: true });
window.visualViewport?.addEventListener("resize", syncAppViewportHeight, { passive: true });

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // 설치 기능이 막혀도 웹 통화 자체는 계속 사용할 수 있다.
    });
  });
}
