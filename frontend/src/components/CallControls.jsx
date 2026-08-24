function ControlIcon({ type }) {
  if (type === "microphone") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="8" y="3" width="8" height="12" rx="4" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" />
      </svg>
    );
  }
  if (type === "keyboard") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M7 9h.01M11 9h.01M15 9h.01M18 9h.01M7 13h.01M11 13h.01M15 13h.01M18 13h.01M8 16h8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5.2 4.5c.8-.8 2-.9 2.8-.2l2.2 1.9c.7.6.9 1.6.4 2.4l-1.3 2a14.2 14.2 0 0 0 4.1 4.1l2-1.3c.8-.5 1.8-.3 2.4.4l1.9 2.2c.7.8.6 2-.2 2.8l-1.2 1.2c-.9.9-2.2 1.2-3.4.8A19 19 0 0 1 3.2 9.1c-.4-1.2-.1-2.5.8-3.4l1.2-1.2Z" />
      <path d="m5 19 14-14" />
    </svg>
  );
}

export function CallControlButton({ type, label, className = "", ...props }) {
  return (
    <button className={`round call-control ${className}`.trim()} type="button" {...props}>
      <ControlIcon type={type} />
      <span>{label}</span>
    </button>
  );
}

export function CallEndConfirm({ open, onCancel, onConfirm }) {
  if (!open) return null;
  return (
    <div className="call-confirm-backdrop" role="presentation" onMouseDown={onCancel}>
      <section
        className="call-confirm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="call-end-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="call-end-title">통화를 끝낼까요?</h2>
        <p>계속 이야기하려면 ‘계속 통화’를 눌러 주세요.</p>
        <div>
          <button type="button" className="keep" onClick={onCancel}>계속 통화</button>
          <button type="button" className="end" onClick={onConfirm}>통화 종료</button>
        </div>
      </section>
    </div>
  );
}
