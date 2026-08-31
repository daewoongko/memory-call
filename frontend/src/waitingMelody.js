import waitingAudioUrl from "./assets/waiting-nature-guide-24.2s.mp3";

let active = null;

/**
 * 가족에게 연결되는 동안 재생하는 24.2초 대기 음원.
 * 사용자가 선택한 자연 소리에 안내 음성을 앞뒤로 두 번 넣은 완성본이다.
 * 가족 카드 클릭 흐름 안에서 호출해 모바일 브라우저의 자동재생 제한을 피한다.
 */
export function startWaitingMelody(durationMs = 24200) {
  stopWaitingMelody();
  if (typeof window === "undefined" || !window.Audio) return false;

  try {
    const audio = new window.Audio(waitingAudioUrl);
    audio.preload = "auto";
    audio.loop = false;
    audio.volume = 1;
    audio.currentTime = 0;

    const timer = window.setTimeout(stopWaitingMelody, durationMs + 250);
    active = { audio, timer };
    audio.play().catch(() => {
      if (active?.audio !== audio) return;
      window.clearTimeout(timer);
      active = null;
    });
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
    current.audio.pause();
    current.audio.currentTime = 0;
  } catch {
    // 이미 해제된 오디오 요소는 별도 정리가 필요 없다.
  }
}
