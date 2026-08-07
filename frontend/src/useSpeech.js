import { useCallback, useEffect, useRef, useState } from "react";
import {
  adaptiveSilenceDelay,
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

/**
 * 브라우저 음성 인식(STT)과 로컬 Chatterbox 음성 합성(TTS).
 *
 * 합성은 먼저 /api/tts 의 복제 음성을 시도한다. 브라우저 내장 음성 대체는
 * VITE_TTS_BROWSER_FALLBACK=true 로 명시한 개발 환경에서만 허용한다.
 */

const BROWSER_TTS_FALLBACK_ENABLED =
  import.meta.env.VITE_TTS_BROWSER_FALLBACK === "true";

// 립싱크는 기본으로 켜고, 긴급 롤백이 필요할 때만 명시적으로 끈다.
const LIPSYNC_ENABLED = import.meta.env.VITE_MUSETALK_LIPSYNC !== "false";

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
  silenceMs = 2000,
  // 남성 음성을 찾지 못했을 때만 음높이를 낮춘다.
  // 명세의 voice_profiles.pitch_adjustment 에 해당하는 값이다.
  fallbackPitch = 0.72,
  rate = 0.92,
  preferLipSync = false,
  onFinal,
} = {}) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [lipSyncSrc, setLipSyncSrc] = useState(null);
  const [lipSyncActive, setLipSyncActive] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");

  const recRef = useRef(null);
  const finalRef = useRef("");
  const silenceRef = useRef(null);
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const audioCancelRef = useRef(null);
  const lipSyncVideoRef = useRef(null);
  const lipSyncUrlRef = useRef(null);
  const ttsRequestRefs = useRef(new Set());
  const speechRunRef = useRef(0);
  const recognitionRunRef = useRef(0);
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
    if (lipSyncVideoRef.current) {
      lipSyncVideoRef.current.pause();
      lipSyncVideoRef.current.removeAttribute("src");
      lipSyncVideoRef.current.load();
    }
    if (lipSyncUrlRef.current) {
      URL.revokeObjectURL(lipSyncUrlRef.current);
      lipSyncUrlRef.current = null;
    }
    setLipSyncSrc(null);
    setLipSyncActive(false);
    window.speechSynthesis?.cancel();
    setPlaying(false);
    setSpeaking(false);
  }, []);

  const start = useCallback(() => {
    if (!supported) return;

    stop();
    setError("");
    setInterim("");
    finalRef.current = "";

    const rec = new Recognition();
    const recognitionId = ++recognitionRunRef.current;
    const recognitionStartedAt = speechNow();
    let lastResultAt = null;
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;

    rec.onstart = () => {
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
      if (event.error === "not-allowed") {
        setError("마이크 권한이 필요해요. 주소창 옆에서 허용해 주세요.");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        setError("소리를 잘 못 들었어요. 다시 말씀해 주세요.");
      }
    };

    rec.onend = () => {
      const endedAt = speechNow();
      clearSilence();
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
            body: JSON.stringify({ text, rate }),
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
    [rate]
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
            body: JSON.stringify({ text, rate }),
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
    [rate]
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

      const url = URL.createObjectURL(blob);
      lipSyncUrlRef.current = url;
      setLipSyncSrc(url);
      setLipSyncActive(true);
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
        if (lipSyncVideoRef.current === video) {
          video.pause();
          video.removeAttribute("src");
          video.load();
        }
        if (lipSyncUrlRef.current === url) {
          URL.revokeObjectURL(url);
          lipSyncUrlRef.current = null;
        }
        setLipSyncSrc(null);
        setLipSyncActive(false);
      }
    },
    []
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
            "[TTS] Chatterbox 실패, 명시적으로 허용된 브라우저 음성으로 전환:",
            err
          );
          const remainingText = chunks.slice(completedChunks).join(" ") || text;
          await speakInBrowser(remainingText, runId);
        } else {
          console.error("[TTS] Chatterbox 음성을 재생하지 못했습니다:", err);
          setError(TTS_UNAVAILABLE_MESSAGE);
        }
      } finally {
        if (runId === speechRunRef.current) {
          audioRef.current = null;
          if (audioUrlRef.current) {
            URL.revokeObjectURL(audioUrlRef.current);
            audioUrlRef.current = null;
          }
          if (lipSyncUrlRef.current) {
            URL.revokeObjectURL(lipSyncUrlRef.current);
            lipSyncUrlRef.current = null;
          }
          setLipSyncSrc(null);
          setLipSyncActive(false);
          setPlaying(false);
          setSpeaking(false);
        }
      }
    },
    [cancelSpeech, fetchSpeechChunk, playSpeechChunk, speakInBrowser, stop]
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
    playing,
    lipSyncSrc,
    lipSyncActive,
    lipSyncVideoRef,
    interim,
    error,
    start,
    stop,
    speak,
    cancel: cancelSpeech,
  };
}
