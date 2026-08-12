import { useCallback, useEffect, useState } from "react";

/**
 * 화면 모드와 글씨 크기.
 *
 * 노인마다 눈 상태와 사용 환경이 달라 하나로 맞출 수 없다 (명세 NFR-02).
 * 색은 전부 CSS 변수로 두고 data-theme 만 바꾼다.
 * 그래서 화면을 하나씩 손대지 않아도 모드가 전체에 적용된다.
 */

export const THEMES = [
  { id: "light", label: "편안하게", description: "연한 아이보리 바탕" },
  { id: "contrast", label: "선명하게", description: "글자와 경계를 더 뚜렷하게" },
  { id: "soft", label: "눈부심 줄이기", description: "밝은 흰색과 강한 색을 줄임" },
];

export const SIZE_MIN = 90;
export const SIZE_MAX = 180;
export const SIZE_STEP = 5;

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
  root.dataset.theme = normalizeTheme(theme);
  const percent = normalizeSize(size);
  root.style.setProperty("--font-scale", String(percent / 100));
}

function normalizeTheme(value) {
  return ({ dark: "contrast", warm: "soft" })[value] || (THEMES.some((item) => item.id === value) ? value : "light");
}

function normalizeSize(value) {
  const legacy = { normal: 100, large: 115, xlarge: 130 };
  const numeric = legacy[value] || Number(value) || 100;
  return Math.min(SIZE_MAX, Math.max(SIZE_MIN, Math.round(numeric / SIZE_STEP) * SIZE_STEP));
}

export function useTheme() {
  const [theme, setThemeState] = useState(() => normalizeTheme(read(KEY_THEME, "light")));
  const [size, setSizeState] = useState(() => normalizeSize(read(KEY_SIZE, "100")));

  useEffect(() => {
    applyTheme(theme, size);
  }, [theme, size]);

  const setTheme = useCallback((next) => {
    const normalized = normalizeTheme(next);
    setThemeState(normalized);
    try {
      window.localStorage.setItem(KEY_THEME, normalized);
    } catch {
      // 저장에 실패해도 이번 세션에는 적용된다
    }
  }, []);

  const setSize = useCallback((next) => {
    const normalized = normalizeSize(next);
    setSizeState(normalized);
    try {
      window.localStorage.setItem(KEY_SIZE, String(normalized));
    } catch {
      // 무시
    }
  }, []);

  return { theme, size, setTheme, setSize };
}
