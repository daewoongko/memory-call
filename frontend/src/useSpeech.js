import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 브라우저 음성 인식(STT)과 로컬 Chatterbox 음성 합성(TTS).
 *
 * 합성은 먼저 /api/tts 의 복제 음성을 시도한다. 로컬 GPU 서버가 꺼져 있거나
 * 합성에 실패하면 통화가 멈추지 않도록 브라우저 내장 음성으로 대체한다.
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
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const ttsRequestRef = useRef(null);
  const speechRunRef = useRef(0);
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

  const cancelSpeech = useCallback(() => {
    speechRunRef.current += 1;
    ttsRequestRef.current?.abort();
    ttsRequestRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute("src");
      audioRef.current.load();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    window.speechSynthesis?.cancel();
    setSpeaking(false);
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

  const speakInBrowser = useCallback(
    async (text, runId) => {
      const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
      if (!synth || runId !== speechRunRef.current) return;

      await voicesReady();
      await wait(80);
      if (runId !== speechRunRef.current) return;

      const { voice, male } = pickVoice();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = lang;
      utter.rate = rate;
      utter.pitch = male ? 1.0 : fallbackPitch;
      if (voice) utter.voice = voice;

      await new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          clearInterval(keepalive);
          clearTimeout(guard);
          resolve();
        };
        const keepalive = setInterval(() => {
          if (synth.speaking) {
            synth.pause();
            synth.resume();
          }
        }, KEEPALIVE_MS);
        const guard = setTimeout(finish, 4000 + text.length * 160);
        utter.onend = finish;
        utter.onerror = finish;
        synth.speak(utter);
      });
    },
    [fallbackPitch, lang, rate]
  );

  /** 복제한 가족 목소리로 읽고, 실패할 때만 브라우저 기본 음성을 쓴다. */
  const speak = useCallback(
    async (text) => {
      if (!text) return;

      stop();
      cancelSpeech();
      const runId = speechRunRef.current;
      setSpeaking(true);

      try {
        const controller = new AbortController();
        ttsRequestRef.current = controller;
        const response = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, rate }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`TTS ${response.status}`);

        const blob = await response.blob();
        if (runId !== speechRunRef.current) return;

        const url = URL.createObjectURL(blob);
        audioUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise((resolve, reject) => {
          audio.onended = resolve;
          audio.onerror = () => reject(new Error("복제 음성 재생 실패"));
          audio.play().catch(reject);
        });
      } catch (err) {
        if (err.name === "AbortError" || runId !== speechRunRef.current) return;
        console.warn("[TTS] Chatterbox 실패, 브라우저 음성으로 전환:", err);
        await speakInBrowser(text, runId);
      } finally {
        if (runId === speechRunRef.current) {
          ttsRequestRef.current = null;
          audioRef.current = null;
          if (audioUrlRef.current) {
            URL.revokeObjectURL(audioUrlRef.current);
            audioUrlRef.current = null;
          }
          setSpeaking(false);
        }
      }
    },
    [cancelSpeech, rate, speakInBrowser, stop]
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
      cancelSpeech();
    },
    [cancelSpeech]
  );

  return {
    supported,
    listening,
    speaking,
    interim,
    error,
    start,
    stop,
    speak,
    cancel: cancelSpeech,
  };
}
