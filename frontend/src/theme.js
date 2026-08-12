import { useCallback, useEffect, useState } from "react";

/**
 * 화면 모드와 글씨 크기.
 *
 * 노인마다 눈 상태와 사용 환경이 달라 하나로 맞출 수 없다 (명세 NFR-02).
 * 색은 전부 CSS 변수로 두고 data-theme 만 바꾼다.
 * 그래서 화면을 하나씩 손대지 않아도 모드가 전체에 적용된다.
 */

export const THEMES = [
  { id: "light", label: "밝게" },
  { id: "dark", label: "어둡게" },
  { id: "warm", label: "눈 보호" },
];

export const SIZES = [
  { id: "normal", label: "보통", scale: 1 },
  { id: "large", label: "크게", scale: 1.15 },
  { id: "xlarge", label: "아주 크게", scale: 1.32 },
];

const KEY_THEME = "dasoni.theme";
const KEY_SIZE = "dasoni.size";

function read(key, fallback) {
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

export function applyTheme(theme, size) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  const found = SIZES.find((s) => s.id === size) ?? SIZES[0];
  root.style.setProperty("--scale", String(found.scale));
}

export function useTheme() {
  const [theme, setThemeState] = useState(() => read(KEY_THEME, "light"));
  const [size, setSizeState] = useState(() => read(KEY_SIZE, "normal"));

  useEffect(() => {
    applyTheme(theme, size);
  }, [theme, size]);

  const setTheme = useCallback((next) => {
    setThemeState(next);
    try {
      window.localStorage.setItem(KEY_THEME, next);
    } catch {
      // 저장에 실패해도 이번 세션에는 적용된다
    }
  }, []);

  const setSize = useCallback((next) => {
    setSizeState(next);
    try {
      window.localStorage.setItem(KEY_SIZE, next);
    } catch {
      // 무시
    }
  }, []);

  return { theme, size, setTheme, setSize };
}
