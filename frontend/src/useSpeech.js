import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 브라우저 내장 음성 인식·합성.
 *
 * 외부 API 를 쓰지 않으므로 비용이 없고 지연이 거의 없다.
 * 대화 응답이 이미 수 초 걸리기 때문에 음성 단계에서 시간을 더 쓸 여유가 없다.
 *
 * 브라우저 음성 합성에는 오래된 버그가 몇 가지 있어 그대로 쓰면 소리가 끊긴다.
 * 아래 세 가지를 방어한다.
 *   1. 목소리 목록이 늦게 로드되면 엉뚱한 기본 음성이 나간다 → 로드를 기다린다
 *   2. cancel() 직후 speak() 하면 무음이 된다 → 짧게 쉬었다 말한다
 *   3. onend 가 유실되면 다음 동작이 영원히 오지 않는다 → 예상 시간 뒤 강제 종료
 */

// 손자 페르소나에 맞는 한국어 남성 음성을 앞에서부터 찾는다.
// 다른 목소리로 바꾸려면 이 배열의 순서만 바꾸면 된다.
const MALE_VOICES = ["Reed", "Eddy", "Rocko", "InJoon", "인준"];

// 말이 길어지면 브라우저가 스스로 멈추는 경우가 있어 주기적으로 깨운다.
const KEEPALIVE_MS = 8000;

const Recognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

export function koreanVoices() {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  return window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang?.replace("_", "-").toLowerCase().startsWith("ko"));
}

function pickVoice() {
  const voices = koreanVoices();
  for (const wanted of MALE_VOICES) {
    const hit = voices.find((v) =>
      v.name.toLowerCase().includes(wanted.toLowerCase())
    );
    if (hit) return { voice: hit, male: true };
  }
  return { voice: voices[0] ?? null, male: false };
}

/** 목소리 목록은 비동기로 채워진다. 준비될 때까지 잠깐 기다린다. */
function voicesReady() {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) return resolve();
    if (window.speechSynthesis.getVoices().length) return resolve();
    const done = () => resolve();
    window.speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1200);
  });
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

export function useSpeech({
  lang = "ko-KR",
  silenceMs = 2000,
  // 남성 음성을 찾지 못했을 때만 음높이를 낮춘다.
  // 명세의 voice_profiles.pitch_adjustment 에 해당하는 값이다.
  fallbackPitch = 0.72,
  rate = 0.92,
  onFinal,
} = {}) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");

  const recRef = useRef(null);
  const finalRef = useRef("");
  const silenceRef = useRef(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  const supported = Boolean(Recognition);

  const clearSilence = () => {
    if (silenceRef.current) {
      clearTimeout(silenceRef.current);
      silenceRef.current = null;
    }
  };

  const stop = useCallback(() => {
    clearSilence();
    try {
      recRef.current?.stop();
    } catch {
      // 이미 멈춰 있으면 무시
    }
  }, []);

  const start = useCallback(() => {
    if (!supported) return;

    stop();
    setError("");
    setInterim("");
    finalRef.current = "";

    const rec = new Recognition();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;

    rec.onstart = () => setListening(true);

    rec.onresult = (event) => {
      let live = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalRef.current += chunk;
        else live += chunk;
      }
      setInterim(live);

      // 말이 멈추고 일정 시간이 지나면 한 문장이 끝난 것으로 본다.
      // 노인은 문장 사이 침묵이 길어서 이 값을 프로필에서 받아온다 (명세 NFR-03).
      clearSilence();
      silenceRef.current = setTimeout(() => {
        try {
          rec.stop();
        } catch {
          // 무시
        }
      }, silenceMs);
    };

    rec.onerror = (event) => {
      if (event.error === "not-allowed") {
        setError("마이크 권한이 필요해요. 주소창 옆에서 허용해 주세요.");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        setError("소리를 잘 못 들었어요. 다시 말씀해 주세요.");
      }
    };

    rec.onend = () => {
      clearSilence();
      setListening(false);
      setInterim("");
      const text = finalRef.current.trim();
      finalRef.current = "";
      if (text) onFinalRef.current?.(text);
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch {
      setError("음성 인식을 시작하지 못했어요.");
    }
  }, [lang, silenceMs, stop, supported]);

  /** 가족 목소리로 문장을 읽어준다. 읽는 동안에는 마이크를 닫아 되울림을 막는다. */
  const speak = useCallback(
    async (text) => {
      const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
      if (!text || !synth) return;

      stop();
      synth.cancel();
      await voicesReady();
      // cancel 직후 곧바로 speak 하면 소리가 나지 않는 브라우저가 있다
      await wait(80);

      const { voice, male } = pickVoice();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = lang;
      utter.rate = rate; // 노인이 알아듣기 쉽도록 조금 느리게
      utter.pitch = male ? 1.0 : fallbackPitch;
      if (voice) utter.voice = voice;

      setSpeaking(true);

      await new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          clearInterval(keepalive);
          clearTimeout(guard);
          setSpeaking(false);
          resolve();
        };

        // 긴 문장에서 브라우저가 스스로 멈추는 것을 막는다
        const keepalive = setInterval(() => {
          if (synth.speaking) {
            synth.pause();
            synth.resume();
          }
        }, KEEPALIVE_MS);

        // onend 가 오지 않아도 대화가 멈추지 않도록 예상 시간 뒤에 넘어간다
        const guard = setTimeout(finish, 4000 + text.length * 160);

        utter.onend = finish;
        utter.onerror = finish;
        synth.speak(utter);
      });
    },
    [fallbackPitch, lang, rate, stop]
  );

  // 목소리 목록을 미리 받아두고, 어떤 음성이 선택되는지 한 번 알려준다
  useEffect(() => {
    voicesReady().then(() => {
      const { voice, male } = pickVoice();
      console.info(
        `[음성] ${voice?.name ?? "없음"} · ${male ? "남성" : "여성(음높이 보정)"}`,
        koreanVoices().map((v) => v.name)
      );
    });
  }, []);

  useEffect(
    () => () => {
      clearSilence();
      try {
        recRef.current?.abort();
      } catch {
        // 무시
      }
      window.speechSynthesis?.cancel();
    },
    []
  );

  return { supported, listening, speaking, interim, error, start, stop, speak };
}
