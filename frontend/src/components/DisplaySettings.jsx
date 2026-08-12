import { SIZE_MAX, SIZE_MIN, SIZE_STEP, THEMES } from "../theme.js";

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
        <div className="text-size-range">
          <div><span>작게</span><b>{size}%</b><span>크게</span></div>
          <input type="range" min={SIZE_MIN} max={SIZE_MAX} step={SIZE_STEP} value={size} onChange={(event) => onSize(Number(event.target.value))} aria-label="글씨 크기" />
        </div>

        <p className="sheet-label">화면 보기</p>
        <div className="choice display-mode-choice">
          {THEMES.map((t) => (
            <button
              key={t.id}
              className={theme === t.id ? "on" : ""}
              onClick={() => onTheme(t.id)}
            >
              <b>{t.label}</b><small>{t.description}</small>
            </button>
          ))}
        </div>
        <p className="display-hint">기기의 실제 밝기는 Windows 또는 휴대폰의 밝기 설정에서 조절해 주세요.</p>

        <button className="sheet-close" onClick={onClose}>
          닫기
        </button>
      </div>
    </div>
  );
}
