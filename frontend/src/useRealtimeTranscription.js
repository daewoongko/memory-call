import { useCallback, useEffect, useRef, useState } from "react";
import { getRealtimeSTTToken, transcribeSpeech } from "./api.js";
import { adaptiveSilenceDelay } from "./speechPipeline.js";

const TARGET_SAMPLE_RATE = 16000;
const DEFAULT_SILENCE_MS = 700;
const MIN_VOICE_MS = 260;
const MAX_IDLE_MS = 15000;
const MAX_UTTERANCE_MS = 20000;
const MIN_START_THRESHOLD = 0.007;
const COMMIT_TIMEOUT_MS = 6000;

function recorderOptions() {
  if (typeof MediaRecorder === "undefined") return undefined;
  const choices = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = choices.find((type) => MediaRecorder.isTypeSupported?.(type));
  return mimeType ? { mimeType } : undefined;
}

export function resampleTo16k(input, inputRate) {
  if (!input?.length) return new Float32Array();
  if (inputRate === TARGET_SAMPLE_RATE) return Float32Array.from(input);
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  const length = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((index + 1) * ratio)));
    let total = 0;
    for (let cursor = start; cursor < end; cursor += 1) total += input[cursor];
    output[index] = total / (end - start);
  }
  return output;
}

export function pcm16ToBase64(samples) {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  let binary = "";
  const stride = 0x8000;
  for (let index = 0; index < bytes.length; index += stride) {
    binary += String.fromCharCode(...bytes.subarray(index, index + stride));
  }
  return btoa(binary);
}

function rms(samples) {
  if (!samples.length) return 0;
  let total = 0;
  for (const sample of samples) total += sample * sample;
  return Math.sqrt(total / samples.length);
}

/**
 * ElevenLabs Scribe v2 Realtime microphone transcription.
 *
 * Audio is sent while the person speaks, so the final one-second pause is the
 * only deliberate end-of-turn wait. MediaRecorder runs in parallel solely as
 * a fallback for the existing Gemini file-transcription endpoint.
 */
export function useRealtimeTranscription({
  enabled = true,
  lang = "ko-KR",
  silenceMs = DEFAULT_SILENCE_MS,
  onFinal,
} = {}) {
  const [starting, setStarting] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);
  const [engine, setEngine] = useState("elevenlabs-realtime");

  const wantedRef = useRef(false);
  const streamRef = useRef(null);
  const contextRef = useRef(null);
  const sourceRef = useRef(null);
  const processorRef = useRef(null);
  const sinkRef = useRef(null);
  const socketRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timersRef = useRef(new Set());
  const committingRef = useRef(false);
  const fallbackRef = useRef(false);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  const endSilenceMs = Math.min(
    2000,
    Math.max(500, Number(silenceMs) || DEFAULT_SILENCE_MS),
  );

  const supported = Boolean(
    enabled &&
    typeof window !== "undefined" &&
    typeof WebSocket !== "undefined" &&
    navigator.mediaDevices?.getUserMedia &&
    (window.AudioContext || window.webkitAudioContext),
  );

  const later = useCallback((callback, delay) => {
    const timer = setTimeout(() => {
      timersRef.current.delete(timer);
      callback();
    }, delay);
    timersRef.current.add(timer);
    return timer;
  }, []);

  const clearTimers = useCallback(() => {
    for (const timer of timersRef.current) clearTimeout(timer);
    timersRef.current.clear();
  }, []);

  const release = useCallback(async () => {
    clearTimers();
    const processor = processorRef.current;
    processorRef.current = null;
    if (processor) processor.onaudioprocess = null;
    try { processor?.disconnect(); } catch { /* already disconnected */ }
    try { sourceRef.current?.disconnect(); } catch { /* already disconnected */ }
    try { sinkRef.current?.disconnect(); } catch { /* already disconnected */ }
    sourceRef.current = null;
    sinkRef.current = null;
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, "done");
    for (const track of streamRef.current?.getTracks?.() ?? []) track.stop();
    streamRef.current = null;
    const context = contextRef.current;
    contextRef.current = null;
    if (context && context.state !== "closed") await context.close().catch(() => {});
    setListening(false);
    setLevel(0);
  }, [clearTimers]);

  const finishRecorder = useCallback(() => new Promise((resolve) => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      resolve(null);
      return;
    }
    recorder.addEventListener("stop", () => {
      const mimeType = recorder.mimeType || chunksRef.current[0]?.type || "audio/webm";
      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];
      recorderRef.current = null;
      resolve(blob);
    }, { once: true });
    try { recorder.stop(); } catch { resolve(null); }
  }), []);

  const deliver = useCallback(async (text) => {
    const finalText = String(text || "").trim();
    if (!finalText || !wantedRef.current) return false;
    wantedRef.current = false;
    // Stop capture immediately, but do not hold the LLM request behind the
    // MediaRecorder stop event and AudioContext teardown.
    const cleanup = Promise.allSettled([finishRecorder(), release()]);
    setInterim("");
    setTranscribing(false);
    onFinalRef.current?.(finalText);
    await cleanup;
    return true;
  }, [finishRecorder, release]);

  const fallbackToGemini = useCallback(async (reason) => {
    if (fallbackRef.current || !wantedRef.current) return;
    fallbackRef.current = true;
    setEngine("gemini-fallback");
    setTranscribing(true);
    const blob = await finishRecorder();
    await release();
    if (!blob || blob.size < 900) {
      wantedRef.current = false;
      setTranscribing(false);
      setError(`실시간 음성 인식을 마치지 못했습니다. ${reason || ""}`.trim());
      return;
    }
    try {
      const result = await transcribeSpeech(blob, lang);
      const text = String(result.text || "").trim();
      wantedRef.current = false;
      setTranscribing(false);
      setInterim("");
      if (text) onFinalRef.current?.(text);
      else setError("말씀을 글자로 바꾸지 못했습니다. 다시 말씀해 주세요.");
    } catch (cause) {
      wantedRef.current = false;
      setTranscribing(false);
      setError(`음성 인식에 잠시 연결하지 못했습니다. ${cause?.message || ""}`.trim());
    }
  }, [finishRecorder, lang, release]);

  const stop = useCallback(() => {
    wantedRef.current = false;
    committingRef.current = false;
    fallbackRef.current = false;
    setStarting(false);
    setTranscribing(false);
    finishRecorder().finally(release);
  }, [finishRecorder, release]);

  const start = useCallback(async () => {
    if (!supported || wantedRef.current) return false;
    wantedRef.current = true;
    committingRef.current = false;
    fallbackRef.current = false;
    chunksRef.current = [];
    setStarting(true);
    setTranscribing(false);
    setInterim("");
    setError("");
    setEngine("elevenlabs-realtime");

    try {
      const [auth, stream] = await Promise.all([
        getRealtimeSTTToken(),
        navigator.mediaDevices.getUserMedia({
          video: false,
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        }),
      ]);
      if (!wantedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }
      streamRef.current = stream;

      if (typeof MediaRecorder !== "undefined") {
        const recorder = new MediaRecorder(stream, recorderOptions());
        recorder.ondataavailable = (event) => {
          if (event.data?.size) chunksRef.current.push(event.data);
        };
        recorder.start(250);
        recorderRef.current = recorder;
      }

      const params = new URLSearchParams({
        model_id: auth.model_id || "scribe_v2_realtime",
        token: auth.token,
        audio_format: "pcm_16000",
        language_code: lang.toLowerCase().startsWith("ko") ? "ko" : lang.split("-")[0],
        commit_strategy: "manual",
      });
      const socket = new WebSocket(`${auth.websocket_url}?${params}`);
      socketRef.current = socket;

      await new Promise((resolve, reject) => {
        const timeout = later(() => reject(new Error("ElevenLabs 연결 시간 초과")), 8000);
        socket.onopen = () => {
          clearTimeout(timeout);
          timersRef.current.delete(timeout);
          resolve();
        };
        socket.onerror = () => reject(new Error("ElevenLabs WebSocket 연결 실패"));
      });

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const context = new AudioContextClass();
      contextRef.current = context;
      if (context.state === "suspended") await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const sink = context.createGain();
      sink.gain.value = 0;
      source.connect(processor);
      processor.connect(sink);
      sink.connect(context.destination);
      sourceRef.current = source;
      processorRef.current = processor;
      sinkRef.current = sink;

      let speechStartedAt = 0;
      let lastVoiceAt = 0;
      let voiceMs = 0;
      let latestTranscript = "";
      let hasFinalTranscript = false;
      let lastTickAt = performance.now();
      const calibrationEndsAt = lastTickAt + 650;
      let noiseFloor = 0.003;
      let startThreshold = MIN_START_THRESHOLD;
      let releaseThreshold = MIN_START_THRESHOLD * 0.68;

      const commit = () => {
        if (committingRef.current || socket.readyState !== WebSocket.OPEN) return;
        committingRef.current = true;
        setListening(false);
        setTranscribing(true);
        socket.send(JSON.stringify({
          message_type: "input_audio_chunk",
          audio_base_64: "",
          commit: true,
        }));
        later(() => fallbackToGemini("최종 전사 시간 초과"), COMMIT_TIMEOUT_MS);
      };

      socket.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.message_type === "partial_transcript" || message.message_type === "final_transcript") {
          latestTranscript = String(message.text || "");
          hasFinalTranscript = message.message_type === "final_transcript";
          setInterim(latestTranscript);
        } else if (message.message_type === "committed_transcript") {
          deliver(message.text);
        } else if (message.message_type === "error" || message.message_type === "rate_limited") {
          fallbackToGemini(message.error || message.message_type);
        }
      };
      socket.onclose = () => {
        if (wantedRef.current && !committingRef.current) fallbackToGemini("실시간 연결 종료");
      };
      socket.onerror = () => {
        if (wantedRef.current) fallbackToGemini("실시간 연결 오류");
      };

      processor.onaudioprocess = (event) => {
        if (!wantedRef.current || committingRef.current) return;
        const now = performance.now();
        const input = event.inputBuffer.getChannelData(0);
        const levelNow = rms(input);
        setLevel(levelNow);
        if (!speechStartedAt && now <= calibrationEndsAt) {
          noiseFloor = Math.min(0.014, noiseFloor * 0.82 + Math.min(levelNow, 0.02) * 0.18);
          startThreshold = Math.max(MIN_START_THRESHOLD, Math.min(0.026, noiseFloor * 2.15 + 0.002));
          releaseThreshold = Math.max(0.005, startThreshold * 0.68);
        }
        const threshold = speechStartedAt ? releaseThreshold : startThreshold;
        if (levelNow >= threshold) {
          if (!speechStartedAt) speechStartedAt = now;
          voiceMs += now - lastTickAt;
          lastVoiceAt = now;
        }
        lastTickAt = now;

        if (socket.readyState === WebSocket.OPEN) {
          const pcm = resampleTo16k(input, context.sampleRate);
          socket.send(JSON.stringify({
            message_type: "input_audio_chunk",
            audio_base_64: pcm16ToBase64(pcm),
          }));
        }
        const currentSilenceMs = adaptiveSilenceDelay({
          configuredMs: endSilenceMs,
          finalizedText: latestTranscript,
          hasFinalResult: hasFinalTranscript,
          hasInterim: Boolean(latestTranscript.trim()) && !hasFinalTranscript,
        });
        if (speechStartedAt && voiceMs >= MIN_VOICE_MS && now - lastVoiceAt >= currentSilenceMs) commit();
        else if (speechStartedAt && now - speechStartedAt >= MAX_UTTERANCE_MS) commit();
      };

      setStarting(false);
      setListening(true);
      later(() => {
        if (!speechStartedAt && wantedRef.current) fallbackToGemini("음성이 감지되지 않음");
      }, MAX_IDLE_MS);
      return true;
    } catch (cause) {
      setStarting(false);
      if (cause?.name === "NotAllowedError") {
        wantedRef.current = false;
        await release();
        setError("마이크 권한이 필요합니다. 주소창 옆에서 허용해 주세요.");
        return false;
      }
      await fallbackToGemini(cause?.message || "실시간 STT 시작 실패");
      return false;
    }
  }, [deliver, endSilenceMs, fallbackToGemini, lang, later, release, supported]);

  useEffect(() => stop, [stop]);

  return {
    supported,
    active: wantedRef.current,
    starting,
    listening,
    transcribing,
    interim,
    error,
    level,
    engine,
    start,
    stop,
  };
}
