import { THEMES, SIZES } from "../theme.js";

/**
 * 화면 설정.
 *
 * 노인이 직접 누를 수 있어야 하므로 항목을 세 개씩만 두고
 * 지금 무엇이 선택되어 있는지 한눈에 보이게 한다.
 */
export default function DisplaySettings({ theme, size, onTheme, onSize, onClose }) {
  return (
    <div className="sheet" role="dialog" aria-label="화면 설정">
      <div className="sheet-body">
        <h2>화면 설정</h2>

        <p className="sheet-label">글씨 크기</p>
        <div className="choice">
          {SIZES.map((s) => (
            <button
              key={s.id}
              className={size === s.id ? "on" : ""}
              onClick={() => onSize(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <p className="sheet-label">화면 밝기</p>
        <div className="choice">
          {THEMES.map((t) => (
            <button
              key={t.id}
              className={theme === t.id ? "on" : ""}
              onClick={() => onTheme(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <button className="sheet-close" onClick={onClose}>
          닫기
        </button>
      </div>
    </div>
  );
}
