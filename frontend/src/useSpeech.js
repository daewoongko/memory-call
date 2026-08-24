import { useCallback, useEffect, useRef, useState } from "react";
import {
  adaptiveSilenceDelay,
  detachThenRevoke,
  emitSpeechTiming,
  retryAfterDelayMs,
  runSequentialAudioQueue,
  speechNow,
  splitKoreanSpeech,
} from "./speechPipeline.js";
import {
  normalizeSpeechMediaType,
  shouldFallbackFromLipSyncStatus,
} from "./speechMedia.js";
import { useRealtimeTranscription } from "./useRealtimeTranscription.js";
import { createAnamTransport } from "./anamTransport.js";

/**
 * 브라우저 음성 인식(STT)과 ElevenLabs API 음성 합성(TTS).
 *
 * 합성은 먼저 /api/tts 의 복제 음성을 시도한다. 브라우저 내장 음성 대체는
 * VITE_TTS_BROWSER_FALLBACK=true 로 명시한 개발 환경에서만 허용한다.
 */

const BROWSER_TTS_FALLBACK_ENABLED =
  import.meta.env.VITE_TTS_BROWSER_FALLBACK === "true";

// MuseTalk은 최종 통화 흐름에서 사용하지 않는다. Anam 실패 시에는
// 같은 ElevenLabs 음성만 재생하고 얼굴 영상 생성으로 우회하지 않는다.
const LIPSYNC_ENABLED = false;
const ANAM_ENABLED = import.meta.env.VITE_ANAM_LIPSYNC !== "false";
const ANAM_VIDEO_ELEMENT_ID = "anam-persona-video";

const TTS_UNAVAILABLE_MESSAGE =
  "복제 음성에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";

// 손자 페르소나에 맞는 한국어 남성 음성을 앞에서부터 찾는다.
// 다른 목소리로 바꾸려면 이 배열의 순서만 바꾸면 된다.
const MALE_VOICES = ["Reed", "Eddy", "Rocko", "InJoon", "인준"];

// 말이 길어지면 브라우저가 스스로 멈추는 경우가 있어 주기적으로 깨운다.
const KEEPALIVE_MS = 8000;

const Recognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);
const ANDROID_BROWSER =
  typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent);

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

function abortError() {
  const error = new Error("음성 요청 취소");
  error.name = "AbortError";
  return error;
}

function waitForRetry(ms, signal) {
  if (signal.aborted) return Promise.reject(abortError());
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function secondsHeaderMs(headers, name) {
  const raw = headers.get(name);
  if (raw == null || raw.trim() === "") return null;
  const seconds = Number(raw);
  return Number.isFinite(seconds) ? Math.round(seconds * 1000) : null;
}

export function useSpeech({
  lang = "ko-KR",
  silenceMs = 1000,
  // 남성 음성을 찾지 못했을 때만 음높이를 낮춘다.
  // 명세의 voice_profiles.pitch_adjustment 에 해당하는 값이다.
  fallbackPitch = 0.72,
  rate = 0.92,
  personaId = null,
  callId = null,
  performanceStyle = "calm",
  prepareAnam = false,
  anamReady = true,
  preferLipSync = false,
  onFinal,
} = {}) {
  const [listening, setListening] = useState(false);
  const [starting, setStarting] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [lipSyncActive, setLipSyncActive] = useState(false);
  const [anamActive, setAnamActive] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");

  const recRef = useRef(null);
  const recognitionWantedRef = useRef(false);
  const recognitionRetryRef = useRef(null);
  const recognitionStartRef = useRef(null);
  const finalRef = useRef("");
  const silenceRef = useRef(null);
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const audioCancelRef = useRef(null);
  const lipSyncVideoRef = useRef(null);
  const lipSyncBlurRef = useRef(null);
  const anamVideoRef = useRef(null);
  const anamTransportRef = useRef(null);
  const anamTransportKeyRef = useRef(null);
  const lipSyncUrlRef = useRef(null);
  const ttsRequestRefs = useRef(new Set());
  const speechRunRef = useRef(0);
  const recognitionRunRef = useRef(0);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  // Galaxy Chrome처럼 브라우저 음성 인식이 있는 기기에서는 기기 경로를
  // 우선 사용한다. ElevenLabs 실시간 STT는 Web Speech API가 없는 브라우저의
  // 대체 경로로 남겨, 외부 WebSocket 장애가 통화 전체를 막지 않게 한다.
  const serverStt = useRealtimeTranscription({
    enabled: true,
    lang,
    silenceMs,
    onFinal: (text) => onFinalRef.current?.(text),
  });
  // Android Chrome exposes webkitSpeechRecognition even when the backing
  // Google speech service is unavailable to an installed PWA.  In that case
  // feature detection succeeds but every recognition attempt ends with a
  // network/service error.  Galaxy devices therefore use our authenticated
  // realtime STT path first; MediaRecorder inside that hook still provides
  // the existing file-transcription fallback if its WebSocket is blocked.
  const usesServerStt = serverStt.supported && (!Recognition || ANDROID_BROWSER);
  const supported = Boolean(Recognition) || usesServerStt;

  const clearSilence = () => {
    if (silenceRef.current) {
      clearTimeout(silenceRef.current);
      silenceRef.current = null;
    }
  };

  const clearRecognitionRetry = () => {
    if (recognitionRetryRef.current) {
      clearTimeout(recognitionRetryRef.current);
      recognitionRetryRef.current = null;
    }
  };

  const stop = useCallback(() => {
    clearSilence();
    clearRecognitionRetry();
    recognitionWantedRef.current = false;
    setStarting(false);
    setListening(false);
    try {
      recRef.current?.abort();
    } catch {
      // 이미 멈춰 있으면 무시
    }
    serverStt.stop();
  }, [serverStt.stop]);

  /** 두 영상에서 blob 을 뗀 뒤에만 해제한다. 순서가 뒤집히면 아직 읽는 중인
   *  쪽이 ERR_FILE_NOT_FOUND 로 죽는다. */
  const releaseLipSyncUrl = useCallback((url) => {
    const current = lipSyncUrlRef.current;
    if (current == null) return;
    if (url != null && current !== url) return;
    detachThenRevoke(
      [lipSyncVideoRef.current, lipSyncBlurRef.current],
      () => URL.revokeObjectURL(current)
    );
    lipSyncUrlRef.current = null;
  }, []);

  const getAnamTransport = useCallback(() => {
    if (!ANAM_ENABLED || !anamReady || !callId || !personaId) return null;
    const transportKey = `${callId}:${personaId}:${performanceStyle}`;
    if (
      anamTransportRef.current &&
      anamTransportKeyRef.current !== transportKey
    ) {
      const previous = anamTransportRef.current;
      anamTransportRef.current = null;
      anamTransportKeyRef.current = null;
      setAnamActive(false);
      previous.disconnect().catch(() => {});
    }
    if (!anamTransportRef.current) {
      anamTransportKeyRef.current = transportKey;
      anamTransportRef.current = createAnamTransport({
        callId,
        personaId,
        performanceStyle,
        videoElementId: ANAM_VIDEO_ELEMENT_ID,
        onStateChange: (next) => {
          if (anamTransportKeyRef.current === transportKey) {
            setAnamActive(next === "connected");
          }
        },
      });
    }
    return anamTransportRef.current;
  }, [anamReady, callId, performanceStyle, personaId]);

  const cancelSpeech = useCallback(() => {
    speechRunRef.current += 1;
    for (const controller of ttsRequestRefs.current) controller.abort();
    ttsRequestRefs.current.clear();
    audioCancelRef.current?.();
    audioCancelRef.current = null;
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
    releaseLipSyncUrl();
    anamTransportRef.current?.interrupt();
    setLipSyncActive(false);
    window.speechSynthesis?.cancel();
    setPlaying(false);
    setSpeaking(false);
  }, [releaseLipSyncUrl]);

  const start = useCallback(() => {
    if (!supported) return;
    if (usesServerStt) {
      serverStt.start();
      return;
    }
    recognitionWantedRef.current = true;
    clearRecognitionRetry();
    // start()가 연속으로 호출되면 기존 인식을 stop한 직후 새 인식을 열어
    // 모바일 브라우저의 마이크가 `audio-capture`로 실패할 수 있다. 현재 세션이
    // 끝날 때까지는 그대로 두고 onend 이후 감시 루프가 다시 시작하게 한다.
    if (recRef.current) return;

    setError("");
    setInterim("");
    finalRef.current = "";
    setStarting(true);

    const rec = new Recognition();
    const recognitionId = ++recognitionRunRef.current;
    const recognitionStartedAt = speechNow();
    let lastResultAt = null;
    let retryDelayMs = 300;
    rec.lang = lang;
    rec.interimResults = true;
    // Android Chrome에서는 continuous 세션이 오디오 포커스 전환 뒤 조용히
    // 멎는 경우가 많다. 한 발화씩 확정하고 onend에서 자동으로 다시 여는 쪽이
    // 더 안정적이며 사용자에게는 계속 열린 마이크처럼 동작한다.
    rec.continuous = !ANDROID_BROWSER;
    rec.maxAlternatives = 1;

    rec.onstart = () => {
      setStarting(false);
      setListening(true);
      emitSpeechTiming("stt.start", { recognitionId });
    };

    rec.onresult = (event) => {
      let live = "";
      let hasFinalResult = false;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalRef.current += chunk;
          hasFinalResult = true;
        }
        else live += chunk;
      }
      setInterim(live);
      lastResultAt = speechNow();

      // 말이 멈추고 일정 시간이 지나면 한 문장이 끝난 것으로 본다.
      // 노인은 문장 사이 침묵이 길어서 이 값을 프로필에서 받아온다 (명세 NFR-03).
      clearSilence();
      const delayMs = adaptiveSilenceDelay({
        configuredMs: silenceMs,
        finalizedText: finalRef.current,
        hasFinalResult,
        hasInterim: Boolean(live.trim()),
      });
      emitSpeechTiming("stt.silence", {
        recognitionId,
        delayMs,
        hasFinalResult,
        textLength: finalRef.current.trim().length + live.trim().length,
      });
      silenceRef.current = setTimeout(() => {
        try {
          rec.stop();
        } catch {
          // 무시
        }
      }, delayMs);
    };

    rec.onerror = (event) => {
      setStarting(false);
      setListening(false);
      if (event.error === "not-allowed") {
        recognitionWantedRef.current = false;
        setError("마이크 권한이 필요해요. 주소창 옆에서 허용해 주세요.");
      } else if (event.error === "service-not-allowed") {
        recognitionWantedRef.current = false;
        setError("Chrome의 음성 인식 권한을 확인해 주세요.");
      } else if (event.error === "audio-capture") {
        retryDelayMs = 900;
        setError("마이크 연결을 다시 준비하고 있어요.");
      } else if (event.error === "network") {
        retryDelayMs = 1200;
        setError("음성 인식 연결을 다시 준비하고 있어요.");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        setError("소리를 잘 못 들었어요. 다시 말씀해 주세요.");
      }
    };

    rec.onend = () => {
      const endedAt = speechNow();
      clearSilence();
      setStarting(false);
      setListening(false);
      setInterim("");
      const text = finalRef.current.trim();
      finalRef.current = "";
      if (recRef.current === rec) recRef.current = null;
      emitSpeechTiming("stt.end", {
        recognitionId,
        durationMs: Math.round(endedAt - recognitionStartedAt),
        sinceLastResultMs:
          lastResultAt == null ? null : Math.round(endedAt - lastResultAt),
        textLength: text.length,
      });
      if (text) {
        // 답을 만드는 동안에는 STT가 스피커의 AI 음성을 다시 받아쓰지 않게 한다.
        // AI 답변 재생이 끝나면 CallScreen이 start()로 다시 활성화한다.
        recognitionWantedRef.current = false;
        onFinalRef.current?.(text);
      } else if (recognitionWantedRef.current) {
        // Android Chrome은 침묵이나 오디오 포커스 전환 뒤에 continuous 인식을
        // 자주 끝낸다. 사용자가 다시 누르게 하지 않고 짧게 쉬었다 자동 재연결한다.
        clearRecognitionRetry();
        recognitionRetryRef.current = setTimeout(() => {
          recognitionRetryRef.current = null;
          if (recognitionWantedRef.current) recognitionStartRef.current?.();
        }, retryDelayMs);
      }
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch {
      if (recRef.current === rec) recRef.current = null;
      setStarting(false);
      setListening(false);
      setError("마이크 연결을 다시 준비하고 있어요.");
      recognitionRetryRef.current = setTimeout(() => {
        recognitionRetryRef.current = null;
        if (recognitionWantedRef.current) recognitionStartRef.current?.();
      }, 900);
    }
  }, [lang, serverStt.start, silenceMs, supported, usesServerStt]);
  recognitionStartRef.current = start;

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
        let playingAt = null;
        const finish = (cancelled = false) => {
          if (settled) return;
          settled = true;
          clearInterval(keepalive);
          clearTimeout(guard);
          if (audioCancelRef.current === cancel) audioCancelRef.current = null;
          if (!cancelled && playingAt != null) {
            emitSpeechTiming("audio.onended", {
              runId,
              engine: "browser-fallback",
              durationMs: Math.round(speechNow() - playingAt),
            });
          }
          if (runId === speechRunRef.current) setPlaying(false);
          resolve();
        };
        const cancel = () => finish(true);
        audioCancelRef.current = cancel;
        const keepalive = setInterval(() => {
          if (synth.speaking) {
            synth.pause();
            synth.resume();
          }
        }, KEEPALIVE_MS);
        const guard = setTimeout(cancel, 4000 + text.length * 160);
        utter.onstart = () => {
          if (runId !== speechRunRef.current) return;
          playingAt = speechNow();
          setPlaying(true);
          emitSpeechTiming("audio.onplaying", {
            runId,
            engine: "browser-fallback",
          });
        };
        utter.onend = () => finish();
        utter.onerror = () => finish();
        synth.speak(utter);
      });
    },
    [fallbackPitch, lang, rate]
  );

  const fetchAudioChunk = useCallback(
    async (text, chunkIndex, runId, retryBudget) => {
      let attempt = 0;
      while (runId === speechRunRef.current) {
        const controller = new AbortController();
        ttsRequestRefs.current.add(controller);
        const requestStartedAt = speechNow();
        emitSpeechTiming("tts.request", {
          runId,
          chunkIndex,
          attempt,
          media: "audio",
          textLength: text.length,
        });

        try {
          const response = await fetch("/api/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, rate, ...(personaId ? { persona_id: personaId } : {}) }),
            signal: controller.signal,
          });
          const headersAt = speechNow();
          emitSpeechTiming("tts.headers", {
            runId,
            chunkIndex,
            attempt,
            media: "audio",
            status: response.status,
            durationMs: Math.round(headersAt - requestStartedAt),
            requestId: response.headers.get("X-Request-ID") ?? undefined,
            audioDurationMs: secondsHeaderMs(response.headers, "X-Audio-Duration"),
            serverTotalMs: secondsHeaderMs(
              response.headers,
              "X-Generation-Seconds"
            ),
            serverQueueMs: secondsHeaderMs(
              response.headers,
              "X-TTS-Queue-Seconds"
            ),
            serverModelMs: secondsHeaderMs(
              response.headers,
              "X-TTS-Generation-Seconds"
            ),
            serverTiming: response.headers.get("Server-Timing") ?? undefined,
          });

          if (response.status === 429 && retryBudget.remaining > 0) {
            const retryMs = retryAfterDelayMs(response.headers.get("Retry-After"));
            if (retryMs != null) {
              retryBudget.remaining -= 1;
              emitSpeechTiming("tts.retry", {
                runId,
                chunkIndex,
                retryMs,
              });
              await response.body?.cancel();
              await waitForRetry(retryMs, controller.signal);
              attempt += 1;
              continue;
            }
          }

          if (!response.ok) throw new Error(`TTS ${response.status}`);
          const blob = await response.blob();
          const blobAt = speechNow();
          if (runId !== speechRunRef.current) throw abortError();
          emitSpeechTiming("tts.blob", {
            runId,
            chunkIndex,
            attempt,
            durationMs: Math.round(blobAt - headersAt),
            totalDurationMs: Math.round(blobAt - requestStartedAt),
            bytes: blob.size,
          });
          return blob;
        } finally {
          ttsRequestRefs.current.delete(controller);
        }
      }
      throw abortError();
    },
    [rate, personaId]
  );

  const fetchLipSyncChunk = useCallback(
    async (text, chunkIndex, runId) => {
      const controller = new AbortController();
      ttsRequestRefs.current.add(controller);
      const requestStartedAt = speechNow();
      emitSpeechTiming("tts.request", {
        runId,
        chunkIndex,
        attempt: 0,
        media: "lipsync",
        textLength: text.length,
      });

      try {
        let response;
        try {
          response = await fetch("/api/tts/video", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, rate, ...(personaId ? { persona_id: personaId } : {}) }),
            signal: controller.signal,
          });
        } catch (requestError) {
          if (requestError.name === "AbortError") throw requestError;
          emitSpeechTiming("lipsync.fallback", {
            runId,
            chunkIndex,
            reason: "network",
          });
          return null;
        }

        const headersAt = speechNow();
        const mediaType = normalizeSpeechMediaType(
          response.headers.get("Content-Type")
        );
        emitSpeechTiming("tts.headers", {
          runId,
          chunkIndex,
          attempt: 0,
          media: "lipsync",
          status: response.status,
          responseMedia: mediaType ?? "invalid",
          durationMs: Math.round(headersAt - requestStartedAt),
          requestId: response.headers.get("X-Request-ID") ?? undefined,
          audioDurationMs: secondsHeaderMs(response.headers, "X-Audio-Duration"),
          serverTotalMs: secondsHeaderMs(response.headers, "X-Generation-Seconds"),
          lipsyncTotalMs: secondsHeaderMs(response.headers, "X-Lipsync-Total-Seconds"),
          serverTiming: response.headers.get("Server-Timing") ?? undefined,
        });

        if (shouldFallbackFromLipSyncStatus(response.status)) {
          await response.body?.cancel();
          emitSpeechTiming("lipsync.fallback", {
            runId,
            chunkIndex,
            reason: `status-${response.status}`,
          });
          return null;
        }
        if (!response.ok) throw new Error(`Lip-sync ${response.status}`);
        if (!mediaType) {
          await response.body?.cancel();
          emitSpeechTiming("lipsync.fallback", {
            runId,
            chunkIndex,
            reason: "invalid-media-type",
          });
          return null;
        }

        const blob = await response.blob();
        const blobAt = speechNow();
        if (runId !== speechRunRef.current) throw abortError();
        if (blob.size === 0) {
          emitSpeechTiming("lipsync.fallback", {
            runId,
            chunkIndex,
            reason: "empty-response",
          });
          return null;
        }
        emitSpeechTiming("tts.blob", {
          runId,
          chunkIndex,
          attempt: 0,
          media: mediaType === "video/mp4" ? "lipsync" : "audio-fallback",
          durationMs: Math.round(blobAt - headersAt),
          totalDurationMs: Math.round(blobAt - requestStartedAt),
          bytes: blob.size,
        });
        return {
          kind: mediaType === "video/mp4" ? "video" : "audio",
          blob,
        };
      } finally {
        ttsRequestRefs.current.delete(controller);
      }
    },
    [rate, personaId]
  );

  const fetchSpeechChunk = useCallback(
    async (text, chunkIndex, runId, retryBudget) => {
      if (LIPSYNC_ENABLED && preferLipSync) {
        const lipSyncMedia = await fetchLipSyncChunk(text, chunkIndex, runId);
        if (lipSyncMedia) return lipSyncMedia;
      }
      return {
        kind: "audio",
        blob: await fetchAudioChunk(text, chunkIndex, runId, retryBudget),
      };
    },
    [fetchAudioChunk, fetchLipSyncChunk, preferLipSync]
  );

  const speakWithAnam = useCallback(
    async (text, runId) => {
      const transport = getAnamTransport();
      if (!transport) return false;

      const controller = new AbortController();
      ttsRequestRefs.current.add(controller);
      const requestStartedAt = speechNow();
      emitSpeechTiming("anam.request", {
        runId,
        textLength: text.length,
      });

      try {
        // Do not start a paid TTS request until this family's avatar session is
        // ready. A missing avatar must fall back without leaving an unread PCM
        // stream (and the backend concurrency slot) behind.
        await transport.connect();
        const response = await fetch("/api/tts/pcm-stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            rate,
            ...(personaId ? { persona_id: personaId } : {}),
          }),
          signal: controller.signal,
        });
        const headersAt = speechNow();
        emitSpeechTiming("anam.headers", {
          runId,
          status: response.status,
          durationMs: Math.round(headersAt - requestStartedAt),
          requestId: response.headers.get("X-Request-ID") ?? undefined,
          serverTotalMs: secondsHeaderMs(
            response.headers,
            "X-Generation-Seconds"
          ),
        });
        if (!response.ok) throw new Error(`Anam PCM ${response.status}`);
        if (runId !== speechRunRef.current) throw abortError();

        let firstChunkAt = null;
        const result = await transport.speakPcmResponse(response, {
          signal: controller.signal,
          onFirstChunk: () => {
            if (runId !== speechRunRef.current) return;
            firstChunkAt = speechNow();
            setAnamActive(true);
            setPlaying(true);
            emitSpeechTiming("anam.onplaying", {
              runId,
              durationMs: Math.round(firstChunkAt - requestStartedAt),
            });
          },
        });
        emitSpeechTiming("anam.onended", {
          runId,
          bytes: result.bytes,
          audioDurationMs: Math.round(result.durationMs),
          durationMs:
            firstChunkAt == null
              ? null
              : Math.round(speechNow() - firstChunkAt),
        });
        return true;
      } catch (error) {
        if (error.name !== "AbortError") {
          emitSpeechTiming("anam.fallback", {
            runId,
            reason: error.message || "unavailable",
          });
          await transport.disconnect();
          setAnamActive(false);
        }
        throw error;
      } finally {
        ttsRequestRefs.current.delete(controller);
      }
    },
    [getAnamTransport, personaId, rate]
  );

  const playAudioChunk = useCallback(async (blob, chunkIndex, runId, onPlaying) => {
    if (runId !== speechRunRef.current) throw abortError();
    setLipSyncActive(false);
    const url = URL.createObjectURL(blob);
    audioUrlRef.current = url;
    const audio = new Audio(url);
    audioRef.current = audio;
    const createdAt = speechNow();
    let playingAt = null;

    try {
      await new Promise((resolve, reject) => {
        let settled = false;
        const finish = (playbackError) => {
          if (settled) return;
          settled = true;
          audio.onplaying = null;
          audio.onended = null;
          audio.onerror = null;
          if (audioCancelRef.current === cancel) audioCancelRef.current = null;
          if (playbackError) reject(playbackError);
          else resolve();
        };
        const cancel = () => finish();
        audioCancelRef.current = cancel;
        audio.onplaying = () => {
          if (playingAt != null || runId !== speechRunRef.current) return;
          playingAt = speechNow();
          setPlaying(true);
          emitSpeechTiming("audio.onplaying", {
            runId,
            chunkIndex,
            durationMs: Math.round(playingAt - createdAt),
          });
          onPlaying();
        };
        audio.onended = () => {
          const endedAt = speechNow();
          emitSpeechTiming("audio.onended", {
            runId,
            chunkIndex,
            durationMs:
              playingAt == null ? null : Math.round(endedAt - playingAt),
          });
          finish();
        };
        audio.onerror = () => {
          setPlaying(false);
          finish(new Error("복제 음성 재생 실패"));
        };
        audio.play().catch((playbackError) => {
          setPlaying(false);
          finish(playbackError);
        });
      });
    } finally {
      if (audioRef.current === audio) audioRef.current = null;
      if (audioUrlRef.current === url) {
        URL.revokeObjectURL(url);
        audioUrlRef.current = null;
      }
    }
  }, []);

  const playLipSyncChunk = useCallback(
    async (blob, chunkIndex, runId, onPlaying) => {
      if (runId !== speechRunRef.current) throw abortError();
      const video = lipSyncVideoRef.current;
      if (!video) throw new Error("립싱크 영상 무대가 준비되지 않았습니다");

      // src 를 React 상태로 넣으면 커밋이 늦어, 여기서 해제한 blob 을 아직
      // 가리키는 영상이 남는다. 두 요소 모두 직접 넣고 직접 뗀다.
      const url = URL.createObjectURL(blob);
      lipSyncUrlRef.current = url;
      setLipSyncActive(true);
      const blur = lipSyncBlurRef.current;
      if (blur) {
        blur.src = url;
        blur.load();
      }
      video.src = url;
      video.load();
      const createdAt = speechNow();
      let playingAt = null;

      try {
        await new Promise((resolve, reject) => {
          let settled = false;
          const finish = (playbackError) => {
            if (settled) return;
            settled = true;
            video.onplaying = null;
            video.onended = null;
            video.onerror = null;
            if (audioCancelRef.current === cancel) audioCancelRef.current = null;
            if (playbackError) reject(playbackError);
            else resolve();
          };
          const cancel = () => finish();
          audioCancelRef.current = cancel;
          video.onplaying = () => {
            if (playingAt != null || runId !== speechRunRef.current) return;
            playingAt = speechNow();
            setPlaying(true);
            emitSpeechTiming("video.onplaying", {
              runId,
              chunkIndex,
              durationMs: Math.round(playingAt - createdAt),
            });
            onPlaying();
          };
          video.onended = () => {
            const endedAt = speechNow();
            emitSpeechTiming("video.onended", {
              runId,
              chunkIndex,
              durationMs:
                playingAt == null ? null : Math.round(endedAt - playingAt),
            });
            finish();
          };
          video.onerror = () => finish(new Error("립싱크 영상 재생 실패"));
          video.play().catch((playbackError) => finish(playbackError));
        });
      } finally {
        releaseLipSyncUrl(url);
        setLipSyncActive(false);
      }
    },
    [releaseLipSyncUrl]
  );

  const playSpeechChunk = useCallback(
    async (
      media,
      text,
      chunkIndex,
      runId,
      retryBudget,
      onPlaying
    ) => {
      if (media.kind !== "video") {
        return playAudioChunk(media.blob, chunkIndex, runId, onPlaying);
      }

      try {
        return await playLipSyncChunk(
          media.blob,
          chunkIndex,
          runId,
          onPlaying
        );
      } catch (playbackError) {
        if (
          playbackError.name === "AbortError" ||
          runId !== speechRunRef.current
        ) {
          throw playbackError;
        }
        emitSpeechTiming("lipsync.fallback", {
          runId,
          chunkIndex,
          reason: "playback",
        });
        const audioBlob = await fetchAudioChunk(
          text,
          chunkIndex,
          runId,
          retryBudget
        );
        return playAudioChunk(audioBlob, chunkIndex, runId, onPlaying);
      }
    },
    [fetchAudioChunk, playAudioChunk, playLipSyncChunk]
  );

  /** 복제한 가족 목소리로 읽는다. 브라우저 음성은 명시적으로 허용할 때만 쓴다. */
  const speak = useCallback(
    async (text) => {
      if (!text) return;

      stop();
      cancelSpeech();
      const runId = speechRunRef.current;
      setError("");
      setSpeaking(true);
      setPlaying(false);
      const chunks = splitKoreanSpeech(text);
      const retryBudget = { remaining: 1 };
      let completedChunks = 0;

      try {
        if (ANAM_ENABLED && anamReady && preferLipSync && callId && personaId) {
          try {
            const handled = await speakWithAnam(text, runId);
            if (handled) return;
          } catch (anamError) {
            if (
              anamError.name === "AbortError" ||
              runId !== speechRunRef.current
            ) {
              return;
            }
            console.warn(
              "[Anam] 실시간 립싱크를 사용할 수 없어 기존 재생으로 전환합니다.",
              anamError
            );
          }
        }

        await runSequentialAudioQueue(chunks, {
          fetchChunk: (chunk, chunkIndex) =>
            fetchSpeechChunk(chunk, chunkIndex, runId, retryBudget),
          playChunk: (media, chunkIndex, prefetchNext) =>
            playSpeechChunk(
              media,
              chunks[chunkIndex],
              chunkIndex,
              runId,
              retryBudget,
              prefetchNext
            ),
          shouldContinue: () => runId === speechRunRef.current,
          onChunkComplete: (chunkIndex) => {
            completedChunks = chunkIndex + 1;
          },
        });
      } catch (err) {
        if (err.name === "AbortError" || runId !== speechRunRef.current) return;
        if (BROWSER_TTS_FALLBACK_ENABLED) {
          console.warn(
            "[TTS] ElevenLabs 실패, 명시적으로 허용된 브라우저 음성으로 전환:",
            err
          );
          const remainingText = chunks.slice(completedChunks).join(" ") || text;
          await speakInBrowser(remainingText, runId);
        } else {
          console.error("[TTS] ElevenLabs 음성을 재생하지 못했습니다:", err);
          setError(TTS_UNAVAILABLE_MESSAGE);
        }
      } finally {
        if (runId === speechRunRef.current) {
          const audioUrl = audioUrlRef.current;
          if (audioUrl) {
            detachThenRevoke([audioRef.current], () =>
              URL.revokeObjectURL(audioUrl)
            );
            audioUrlRef.current = null;
          }
          audioRef.current = null;
          releaseLipSyncUrl();
          setLipSyncActive(false);
          setPlaying(false);
          setSpeaking(false);
        }
      }
    },
    [
      cancelSpeech,
      anamReady,
      callId,
      fetchSpeechChunk,
      personaId,
      playSpeechChunk,
      preferLipSync,
      releaseLipSyncUrl,
      speakWithAnam,
      speakInBrowser,
      stop,
    ]
  );

  // Prepare Anam behind the age morph. Visibility remains controlled by
  // preferLipSync, so a ready WebRTC stream never replaces the morph early.
  useEffect(() => {
    if (!ANAM_ENABLED || !anamReady || !prepareAnam) return undefined;
    const transport = getAnamTransport();
    if (!transport) return undefined;
    let cancelled = false;
    let retryTimer = null;
    let attempt = 0;

    const connect = async () => {
      attempt += 1;
      try {
        await transport.connect();
      } catch {
        if (cancelled) return;
        setAnamActive(false);
        if (attempt < 3) {
          retryTimer = setTimeout(connect, attempt === 1 ? 900 : 2200);
        }
      }
    };

    connect();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, [anamReady, getAnamTransport, prepareAnam]);

  useEffect(
    () => () => {
      const transport = anamTransportRef.current;
      anamTransportRef.current = null;
      anamTransportKeyRef.current = null;
      transport?.disconnect();
    },
    [callId, performanceStyle, personaId]
  );

  // 명시적인 폴백 환경에서만 브라우저 목소리를 미리 불러온다.
  useEffect(() => {
    if (!BROWSER_TTS_FALLBACK_ENABLED) return undefined;

    voicesReady().then(() => {
      const { voice, male } = pickVoice();
      console.info(
        `[음성] ${voice?.name ?? "없음"} · ${male ? "남성" : "여성(음높이 보정)"}`,
        koreanVoices().map((v) => v.name)
      );
    });

    return undefined;
  }, []);

  useEffect(
    () => () => {
      clearSilence();
      clearRecognitionRetry();
      recognitionWantedRef.current = false;
      try {
        recRef.current?.abort();
      } catch {
        // 무시
      }
      cancelSpeech();
    },
    [cancelSpeech]
  );

  const anamVisible = anamActive && preferLipSync;

  return {
    supported,
    mode: usesServerStt ? "realtime" : "browser",
    active: usesServerStt ? serverStt.active : recognitionWantedRef.current,
    starting: usesServerStt ? serverStt.starting : starting,
    listening: usesServerStt ? serverStt.listening : listening,
    transcribing: usesServerStt ? serverStt.transcribing : false,
    inputLevel: usesServerStt ? serverStt.level : null,
    speaking,
    playing,
    lipSyncActive: anamVisible,
    anamActive: anamVisible,
    anamVideoRef,
    anamVideoElementId: ANAM_VIDEO_ELEMENT_ID,
    lipSyncVideoRef,
    lipSyncBlurRef,
    interim: usesServerStt ? serverStt.interim : interim,
    error: usesServerStt ? serverStt.error : error,
    start,
    stop,
    speak,
    cancel: cancelSpeech,
  };
}
