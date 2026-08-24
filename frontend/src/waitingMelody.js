const NOTES = [261.63, 329.63, 392.0, 329.63, 293.66, 349.23, 440.0, 349.23];

let active = null;

/**
 * 가족에게 벨이 울리는 동안 어르신이 듣는 짧은 서비스 전용 멜로디.
 * 외부 음원이나 저작권 있는 곡을 사용하지 않고 Web Audio로 잔잔한 음을 만든다.
 * 가족 카드 클릭 안에서 호출하므로 Android Chrome의 자동재생 제한도 피한다.
 */
export function startWaitingMelody(durationMs = 24000) {
  stopWaitingMelody();
  if (typeof window === "undefined") return false;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return false;

  try {
    const context = new AudioContext();
    const master = context.createGain();
    const start = context.currentTime + 0.04;
    const end = start + durationMs / 1000;
    master.gain.setValueAtTime(0.0001, start);
    master.gain.exponentialRampToValueAtTime(0.055, start + 0.35);
    master.gain.setValueAtTime(0.055, Math.max(start + 0.36, end - 0.45));
    master.gain.exponentialRampToValueAtTime(0.0001, end);
    master.connect(context.destination);

    let cursor = start;
    let index = 0;
    while (cursor < end - 0.2) {
      const frequency = NOTES[index % NOTES.length];
      const noteEnd = Math.min(cursor + 0.72, end);
      const oscillator = context.createOscillator();
      const envelope = context.createGain();
      oscillator.type = index % 4 === 3 ? "triangle" : "sine";
      oscillator.frequency.setValueAtTime(frequency, cursor);
      envelope.gain.setValueAtTime(0.0001, cursor);
      envelope.gain.exponentialRampToValueAtTime(0.55, cursor + 0.08);
      envelope.gain.exponentialRampToValueAtTime(0.0001, noteEnd);
      oscillator.connect(envelope);
      envelope.connect(master);
      oscillator.start(cursor);
      oscillator.stop(noteEnd + 0.02);
      cursor += 0.82;
      index += 1;
    }

    const timer = window.setTimeout(stopWaitingMelody, durationMs + 250);
    active = { context, master, timer };
    context.resume().catch(() => {});
    return true;
  } catch {
    active = null;
    return false;
  }
}

export function stopWaitingMelody() {
  const current = active;
  active = null;
  if (!current) return;
  window.clearTimeout(current.timer);
  try {
    const now = current.context.currentTime;
    current.master.gain.cancelScheduledValues(now);
    current.master.gain.setValueAtTime(Math.max(current.master.gain.value, 0.0001), now);
    current.master.gain.exponentialRampToValueAtTime(0.0001, now + 0.08);
  } catch {
    // 이미 닫힌 AudioContext는 별도 정리가 필요 없다.
  }
  window.setTimeout(() => current.context.close().catch(() => {}), 100);
}
