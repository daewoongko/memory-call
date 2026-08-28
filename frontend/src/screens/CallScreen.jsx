import { useCallback, useEffect, useRef, useState } from "react";
import FaceStage from "../components/FaceStage.jsx";
import LipSyncStage from "../components/LipSyncStage.jsx";
import SelfView from "../components/SelfView.jsx";
import { CallControlButton, CallEndConfirm } from "../components/CallControls.jsx";
import { useSpeech } from "../useSpeech.js";
import { emitSpeechTiming, speechNow } from "../speechPipeline.js";

const LISTEN_RESUME_MS = 350;

const RISK_LABEL = {
  fall: "넘어지셨다고 가족에게 알렸어요",
  chest_pain: "가슴 통증을 가족에게 알렸어요",
  breathing: "호흡이 힘드시다고 가족에게 알렸어요",
  lost: "길을 잃으셨다고 가족에게 알렸어요",
  self_harm: "가족에게 바로 알렸어요",
  intrusion: "가족에게 바로 알렸어요",
  fire: "가족에게 바로 알렸어요",
  gas_leak: "가스 냄새를 가족에게 알렸어요",
};

function elapsedText(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function CallScreen({
  faces, opening, name, personaId, callId, api, onEnded,
  conversationEnabled = true, performanceStyle = "calm", anamReady = true,
  onRiskDetected,
}) {
  const [elapsed, setElapsed] = useState(0);
  const [said, setSaid] = useState("");
  const [spoken, setSpoken] = useState("");
  const [pending, setPending] = useState(false);
  const [alert, setAlert] = useState(null);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [confirmingEnd, setConfirmingEnd] = useState(false);
  const speechRef = useRef(null);
  const listenTimerRef = useRef(null);
  const turnRunRef = useRef(0);
  const mutedRef = useRef(false);
  const liveRef = useRef(true);
  mutedRef.current = muted;
  const conversationReady = conversationEnabled;

  const send = useCallback(
    async (text) => {
      const message = text.trim();
      if (!message) return;

      setSaid(message);
      setSpoken("");
      setPending(true);
      setError("");
      const turnId = ++turnRunRef.current;
      const startedAt = speechNow();
      emitSpeechTiming("turn.request", {
        turnId,
        textLength: message.length,
      });

      try {
        const res = await api.sendTurn(callId, message);
        emitSpeechTiming("turn.response", {
          turnId,
          durationMs: Math.round(speechNow() - startedAt),
          serverLlmMs: Number(res.latency_ms) || 0,
          replyLength: String(res.reply ?? "").length,
        });
        setSpoken(res.reply);
        setAlert(res.risk ? RISK_LABEL[res.risk.type] ?? "가족에게 알렸어요" : null);
        if (res.risk_invite?.invite_id) onRiskDetected?.(res.risk_invite);
        return res.reply;
      } catch (e) {
        emitSpeechTiming("turn.error", {
          turnId,
          durationMs: Math.round(speechNow() - startedAt),
        });
        setError(`연결이 잠시 끊겼어요. ${e.message}`);
      } finally {
        setPending(false);
      }
    },
    [api, callId, onRiskDetected]
  );

  // 실제 통화처럼 마이크가 계속 열려 있다.
  // 말이 끝나면 자동으로 보내고, AI 가족 답을 읽어준 뒤 다시 듣기 시작한다.
  // AI 가 말하는 동안에는 마이크를 닫아 스피커 소리가 되돌아오는 것을 막는다.
  const speech = useSpeech({
    // 기본 침묵은 0.6초, 확정된 짧은 대답은 0.5초까지 줄인다. 문장 중간의
    // 자연스러운 쉼을 발화 종료로 오인하지 않도록 0.5초 아래로는 내리지 않는다.
    silenceMs: 600,
    personaId,
    callId,
    performanceStyle,
    prepareAnam: true,
    anamReady,
    // 오프닝의 나이 모핑을 끝낸 뒤에만 현재 얼굴 립싱크로 전환한다.
    preferLipSync: conversationReady,
    onFinal: async (text) => {
      const reply = await send(text);
      if (reply) await speechRef.current?.speak(reply);
      clearTimeout(listenTimerRef.current);
      listenTimerRef.current = setTimeout(() => {
        if (liveRef.current && !mutedRef.current) speechRef.current?.start();
      }, LISTEN_RESUME_MS);
    },
  });
  speechRef.current = speech;

  const resumeListening = useCallback(() => {
    clearTimeout(listenTimerRef.current);
    listenTimerRef.current = setTimeout(() => {
      if (liveRef.current && !mutedRef.current) speechRef.current?.start();
    }, LISTEN_RESUME_MS);
  }, []);

  useEffect(() => {
    if (!conversationReady) return undefined;
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [conversationReady]);

  // 통화가 연결되면 바로 듣기 시작한다. 노인이 버튼을 누를 필요가 없다.
  // 서버가 선제 인사를 준 경우에는 먼저 재생한 뒤 사용자 발화를 듣는다.
  useEffect(() => {
    if (!speech.supported || !conversationReady) return undefined;
    // 개발 모드에서는 마운트가 두 번 일어난다. 정리 함수가 꺼둔 값을
    // 여기서 다시 켜지 않으면 두 번째 마운트에서 마이크가 열리지 않는다.
    liveRef.current = true;
    (async () => {
      if (opening) {
        setSpoken(opening);
        await speech.speak(opening);
      }
      resumeListening();
    })();
    return () => {
      liveRef.current = false;
      clearTimeout(listenTimerRef.current);
      speech.stop();
    };
    // 통화 시작 시 한 번만 실행한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationReady, speech.supported, resumeListening]);

  // 마이크 감시.
  // 음성 인식은 잡음, 권한 변화, 브라우저 사정으로 조용히 꺼질 때가 있다.
  // 통화 중에 마이크가 닫혀 있으면 노인은 이유를 알 수 없으므로 스스로 되살린다.
  useEffect(() => {
    if (!speech.supported) return undefined;
    const id = setInterval(() => {
      const idle =
        conversationReady &&
        liveRef.current &&
        !mutedRef.current &&
        !speech.active &&
        !speech.starting &&
        !speech.listening &&
        !speech.speaking &&
        !pending;
      if (idle) resumeListening();
    }, 3000);
    return () => clearInterval(id);
  }, [conversationReady, speech, pending, resumeListening]);

  function toggleMute() {
    if (muted) {
      mutedRef.current = false;
      setMuted(false);
      if (!pending && !speech.speaking) resumeListening();
      return;
    }
    mutedRef.current = true;
    setMuted(true);
    clearTimeout(listenTimerRef.current);
    speech.stop();
  }

  async function hangup() {
    liveRef.current = false;
    clearTimeout(listenTimerRef.current);
    speech.stop();
    speech.cancel();
    try {
      onEnded(await api.endCall(callId));
    } catch {
      onEnded({ duration_sec: elapsed, ai_turns: 0, avg_latency_ms: 0, risk_events: 0 });
    }
  }

  // 마이크 버튼은 상태에 따라 글과 색이 바뀐다. 노인이 지금 무엇을 해야 하는지
  // 화면만 보고 알 수 있어야 한다 (명세 NFR-02).
  const recognitionFailed = Boolean(error || speech.error);
  const status = muted
    ? "마이크 꺼짐"
    : recognitionFailed
      ? "잘 듣지 못했어요. 다시 말씀해 주세요"
    : speech.playing
      ? "말하고 있어요"
      : speech.speaking
        ? "생각하고 있어요"
        : speech.transcribing
          ? "생각하고 있어요"
          : pending
            ? "생각하고 있어요"
          : speech.listening
            ? "듣고 있어요"
            : speech.starting
              ? "마이크 연결 중"
              : speech.active
                ? "듣고 있어요"
                : "마이크 꺼짐";
  const liveCaption = speech.listening ? speech.interim.trim() : "";
  const captionText = liveCaption || (pending ? said : spoken);
  const captionSpeaker = liveCaption || pending ? "나" : name;

  return (
    <div className="call-screen">
      <FaceStage faces={faces} progress={1} speaking={speech.playing} />

      <LipSyncStage
        active={speech.lipSyncActive}
        anamActive={speech.anamActive}
        anamVideoRef={speech.anamVideoRef}
        anamVideoElementId={speech.anamVideoElementId}
      />

      {alert && <div className="alert-bar">{alert}</div>}

      <div className="topbar">
        <div className="call-meta">
          <div className="badge">
            <b>{name}</b> · {elapsedText(elapsed)}
          </div>
        </div>
        <SelfView />
      </div>

      <div className="bottom">
        {captionText && <div className={`call-caption${liveCaption ? " live" : ""}`} aria-live="polite">
          <b>{captionSpeaker}</b>
          <p>{captionText}</p>
        </div>}
        <div className={`call-state${recognitionFailed ? " failed" : ""}`} aria-live="polite">
          <p className="call-status">{status}</p>
          {speech.listening && !recognitionFailed && !muted && (
            <div className="call-voice-wave" aria-label="음성을 듣고 있어요">
              {[0.7, 1, 0.82, 1.15, 0.76].map((weight, index) => (
                <i
                  key={index}
                  style={{ height: `${Math.min(28, 7 + (speech.inputLevel || 0.05) * 105 * weight)}px` }}
                />
              ))}
            </div>
          )}
        </div>

        <div className="controls call-controls">
          <CallControlButton
            type="microphone"
            label={muted ? "소리 켜기" : "소리 끄기"}
            className={`${muted ? " muted" : ""}${speech.listening ? " listening" : ""}`}
            onClick={toggleMute}
            disabled={!speech.supported}
            aria-pressed={muted}
          />
          <CallControlButton
            type="end"
            label="전화 끊기"
            className="danger"
            onClick={() => setConfirmingEnd(true)}
          />
        </div>
      </div>
      <CallEndConfirm
        open={confirmingEnd}
        onCancel={() => setConfirmingEnd(false)}
        onConfirm={hangup}
      />
    </div>
  );
}
