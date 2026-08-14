import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeSpeech } from "./api.js";

const MAX_IDLE_MS = 15000;
const MAX_UTTERANCE_MS = 12000;
const MIN_VOICE_MS = 260;
const MIN_BLOB_BYTES = 900;
const MIN_START_THRESHOLD = 0.007;

function recorderOptions() {
  const choices = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
  ];
  const mimeType = choices.find((type) => MediaRecorder.isTypeSupported?.(type));
  return mimeType ? { mimeType } : undefined;
}

function rmsLevel(analyser, buffer) {
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for (const value of buffer) {
    const normalized = (value - 128) / 128;
    sum += normalized * normalized;
  }
  return Math.sqrt(sum / buffer.length);
}

/**
 * Android Chrome용 연속 듣기.
 *
 * MediaRecorder는 항상 한 발화만 담고, 음성이 시작된 뒤 silenceMs만큼 조용하면
 * 서버에 전사를 요청한다. 사용자는 매 턴 버튼을 누르지 않는다.
 */
export function useServerTranscription({
  enabled,
  lang = "ko-KR",
  silenceMs = 2000,
  onFinal,
} = {}) {
  const [starting, setStarting] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);

  const wantedRef = useRef(false);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const contextRef = useRef(null);
  const frameRef = useRef(null);
  const idleRef = useRef(null);
  const chunksRef = useRef([]);
  const finishWithSpeechRef = useRef(false);
  const startRef = useRef(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  const supported = Boolean(
    enabled &&
    typeof navigator !== "undefined" &&
    navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined"
  );

  const releaseMedia = useCallback(() => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    clearTimeout(idleRef.current);
    idleRef.current = null;
    for (const track of streamRef.current?.getTracks?.() ?? []) track.stop();
    streamRef.current = null;
    const context = contextRef.current;
    contextRef.current = null;
    if (context && context.state !== "closed") context.close().catch(() => {});
    recorderRef.current = null;
    setListening(false);
    setLevel(0);
  }, []);

  const stop = useCallback(() => {
    wantedRef.current = false;
    finishWithSpeechRef.current = false;
    clearTimeout(idleRef.current);
    idleRef.current = null;
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") {
      try {
        recorder.stop();
      } catch {
        releaseMedia();
      }
    } else {
      releaseMedia();
    }
    setStarting(false);
    setTranscribing(false);
  }, [releaseMedia]);

  const start = useCallback(async () => {
    if (!supported || recorderRef.current || transcribing) return;
    wantedRef.current = true;
    setStarting(true);
    setError("");
    chunksRef.current = [];
    finishWithSpeechRef.current = false;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: false,
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      if (!wantedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;
      const context = new AudioContext();
      contextRef.current = context;
      if (context.state === "suspended") await context.resume();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.2;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);

      const recorder = new MediaRecorder(stream, recorderOptions());
      recorderRef.current = recorder;
      let speechStartedAt = 0;
      let lastVoiceAt = 0;
      let voiceMs = 0;
      let lastTickAt = performance.now();
      const calibrationEndsAt = lastTickAt + 650;
      let noiseFloor = 0.003;
      let startThreshold = MIN_START_THRESHOLD;
      let releaseThreshold = MIN_START_THRESHOLD * 0.72;

      recorder.ondataavailable = (event) => {
        if (event.data?.size) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError("마이크 녹음을 시작하지 못했어요.");
      };
      recorder.onstop = async () => {
        const shouldTranscribe = finishWithSpeechRef.current;
        const mimeType = recorder.mimeType || chunksRef.current[0]?.type || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: mimeType });
        chunksRef.current = [];
        releaseMedia();

        if (!shouldTranscribe || blob.size < MIN_BLOB_BYTES) {
          if (wantedRef.current) setTimeout(() => startRef.current?.(), 250);
          return;
        }

        setTranscribing(true);
        try {
          const result = await transcribeSpeech(blob, lang);
          const text = String(result.text || "").trim();
          // 통화가 이미 끝났거나 사용자가 마이크를 끈 뒤 도착한 전사 결과는
          // 다음 AI 턴으로 넘기지 않는다.
          if (!wantedRef.current) return;
          if (text) {
            wantedRef.current = false;
            onFinalRef.current?.(text);
          } else if (wantedRef.current) {
            setTimeout(() => startRef.current?.(), 250);
          }
        } catch (cause) {
          setError(`음성을 글자로 바꾸지 못했어요. ${cause.message}`);
          if (wantedRef.current) setTimeout(() => startRef.current?.(), 900);
        } finally {
          setTranscribing(false);
        }
      };

      const sample = () => {
        if (recorder.state !== "recording") return;
        const now = performance.now();
        const levelNow = rmsLevel(analyser, samples);
        setLevel(levelNow);

        // 처음 잠깐의 방 안 소리를 기준으로 이 기기의 무음 바닥을 잡는다.
        // Galaxy의 자동 이득·소음 억제 값은 기기와 장소마다 달라 고정 임계값만
        // 쓰면 조용한 말은 버리거나, 반대로 생활 소음을 끝없는 발화로 보게 된다.
        if (!speechStartedAt && now <= calibrationEndsAt) {
          noiseFloor = Math.min(
            0.014,
            noiseFloor * 0.82 + Math.min(levelNow, 0.02) * 0.18,
          );
          startThreshold = Math.max(
            MIN_START_THRESHOLD,
            Math.min(0.026, noiseFloor * 2.15 + 0.002),
          );
          releaseThreshold = Math.max(0.005, startThreshold * 0.68);
        }

        const voiceThreshold = speechStartedAt
          ? releaseThreshold
          : startThreshold;
        if (levelNow >= voiceThreshold) {
          if (!speechStartedAt) speechStartedAt = now;
          voiceMs += now - lastTickAt;
          lastVoiceAt = now;
        }
        lastTickAt = now;
        if (
          speechStartedAt &&
          voiceMs >= MIN_VOICE_MS &&
          now - lastVoiceAt >= Math.max(900, silenceMs)
        ) {
          finishWithSpeechRef.current = true;
          recorder.stop();
          return;
        }
        // 주변 소리가 계속 임계값 위에 있어도 한 발화를 영원히 열어 두지 않는다.
        // 실제 말이 한 번이라도 감지됐다면 최대 길이에서 반드시 서버로 보낸다.
        if (
          speechStartedAt &&
          voiceMs >= MIN_VOICE_MS &&
          now - speechStartedAt >= MAX_UTTERANCE_MS
        ) {
          finishWithSpeechRef.current = true;
          recorder.stop();
          return;
        }
        frameRef.current = requestAnimationFrame(sample);
      };

      recorder.start(250);
      setStarting(false);
      setListening(true);
      frameRef.current = requestAnimationFrame(sample);
      idleRef.current = setTimeout(() => {
        if (recorder.state === "recording") {
          // 배경 소음 때문에 침묵 구간을 못 찾았더라도 감지된 발화가 있으면
          // 버리지 않고 전사한다. 이전에는 여기서 통째로 폐기됐다.
          finishWithSpeechRef.current = Boolean(
            speechStartedAt && voiceMs >= MIN_VOICE_MS,
          );
          recorder.stop();
        }
      }, MAX_IDLE_MS);
    } catch (cause) {
      releaseMedia();
      setStarting(false);
      wantedRef.current = false;
      if (cause?.name === "NotAllowedError") {
        setError("마이크 권한이 필요해요. 주소창 옆에서 허용해 주세요.");
      } else {
        setError(`마이크를 열지 못했어요. ${cause?.message || "다시 시도해 주세요."}`);
      }
    }
  }, [lang, releaseMedia, silenceMs, supported, transcribing]);
  startRef.current = start;

  useEffect(() => stop, [stop]);

  return {
    supported,
    active: wantedRef.current,
    starting,
    listening,
    transcribing,
    interim: "",
    error,
    level,
    start,
    stop,
  };
}
