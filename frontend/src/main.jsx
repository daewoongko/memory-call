import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/gaegu/korean-400.css";
import "@fontsource/gaegu/korean-700.css";
import "@fontsource/gowun-dodum/korean-400.css";
import App from "./App.jsx";
import "./styles.css";
import "./storybook-theme.css";

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
