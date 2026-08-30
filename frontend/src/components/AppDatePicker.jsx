import { useRef } from "react";

function displayDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value || "날짜 선택";
  return `${match[1]}. ${Number(match[2])}. ${Number(match[3])}.`;
}

export default function AppDatePicker({
  value, onChange, className = "", ariaLabel = "날짜 선택", displayValue = "", showValue = false,
}) {
  const inputRef = useRef(null);
  const readableDate = displayValue || displayDate(value);
  const openPicker = (event) => {
    if (event.target === inputRef.current) return;
    const picker = inputRef.current;
    if (!picker) return;
    event.preventDefault();
    picker.focus();
    try {
      if (typeof picker.showPicker === "function") picker.showPicker();
      else picker.click();
    } catch {
      picker.click();
    }
  };
  const openPickerWithKeyboard = (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    openPicker(event);
  };
  return <label
    className={`app-date-picker${showValue ? " show-value" : ""} ${className}`.trim()}
    aria-label={`${ariaLabel}: ${readableDate}`}
    title={`${readableDate} · 눌러서 날짜 변경`}
    role="button"
    tabIndex={0}
    onClick={openPicker}
    onKeyDown={openPickerWithKeyboard}
  >
    <span className="app-date-value">{readableDate}</span>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3 10h18" />
    </svg>
    <input ref={inputRef} type="date" value={value} onChange={onChange} aria-label={ariaLabel} />
  </label>;
}
