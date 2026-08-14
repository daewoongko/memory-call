import { useCallback, useEffect, useRef, useState } from "react";
import FaceStage from "../components/FaceStage.jsx";
import LipSyncStage from "../components/LipSyncStage.jsx";
import LoopStage from "../components/LoopStage.jsx";
import MorphStage from "../components/MorphStage.jsx";
import SelfView from "../components/SelfView.jsx";
import { useSpeech } from "../useSpeech.js";
import { emitSpeechTiming, speechNow } from "../speechPipeline.js";

// 사진이 늘어나면 구간당 시간이 짧아져 깜빡임처럼 보이므로 장당 시간을 보장한다.
const MORPH_MIN_MS = 9000;
const MORPH_PER_FACE_MS = 2200;
const LISTEN_RESUME_MS = 350;

const STAGE_LABEL = {
  child: "어릴 적", teen: "학생 때", college: "대학생 때", current: "지금",
};

function stageLabel(face) {
  if (!face) return "";
  const age = face.stage.match(/(\d+)/)?.[1];
  if (age) return Number(age) >= 30 ? "지금" : `${age}살 때`;
  return STAGE_LABEL[face.stage] ?? face.stage;
}

const RISK_LABEL = {
  fall: "넘어지셨다고 가족에게 알렸어요",
  chest_pain: "가슴 통증을 가족에게 알렸어요",
  breathing: "호흡이 힘드시다고 가족에게 알렸어요",
  lost: "길을 잃으셨다고 가족에게 알렸어요",
  overdose: "약 문제를 가족에게 알렸어요",
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
  faces, morphUrl, loops, opening, name, callId, api, onEnded,
}) {
  const [videoFailed, setVideoFailed] = useState(false);
  const useVideo = Boolean(morphUrl) && !videoFailed;

  const [progress, setProgress] = useState(0);
  const [morphDone, setMorphDone] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [said, setSaid] = useState("");
  const [spoken, setSpoken] = useState("");
  const [pending, setPending] = useState(false);
  const [alert, setAlert] = useState(null);
  const [error, setError] = useState("");
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const [muted, setMuted] = useState(false);
  const inputRef = useRef(null);
  const speechRef = useRef(null);
  const listenTimerRef = useRef(null);
  const turnRunRef = useRef(0);
  const mutedRef = useRef(false);
  const liveRef = useRef(true);
  mutedRef.current = muted;

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
    [api, callId]
  );

  // 실제 통화처럼 마이크가 계속 열려 있다.
  // 말이 끝나면 자동으로 보내고, AI 가족 답을 읽어준 뒤 다시 듣기 시작한다.
  // AI 가 말하는 동안에는 마이크를 닫아 스피커 소리가 되돌아오는 것을 막는다.
  const speech = useSpeech({
    // 모바일 AI 통화는 마지막 음성 뒤 1초를 한 발화의 끝으로 본다.
    // 기존 프로필별 2초 대기는 서버 STT와 직렬로 누적돼 체감 지연이 컸다.
    silenceMs: 1000,
    // 오프닝의 나이 모핑을 끝낸 뒤에만 현재 얼굴 립싱크로 전환한다.
    preferLipSync: useVideo ? morphDone : progress >= 1,
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

  const morphMs = Math.max(MORPH_MIN_MS, faces.length * MORPH_PER_FACE_MS);

  useEffect(() => {
    if (useVideo) return;
    const started = performance.now();
    let raf;
    const tick = (now) => {
      setProgress(Math.min((now - started) / morphMs, 1));
      if (now - started < morphMs) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [morphMs, useVideo]);

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // 통화가 연결되면 바로 듣기 시작한다. 노인이 버튼을 누를 필요가 없다.
  // 복약 시간대라면 선택한 AI 가족이 먼저 말을 꺼낸 뒤에 듣는다.
  useEffect(() => {
    if (!speech.supported) return undefined;
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
  }, [speech.supported, resumeListening]);

  useEffect(() => {
    if (typing && !pending) inputRef.current?.focus();
  }, [typing, pending]);

  // 마이크 감시.
  // 음성 인식은 잡음, 권한 변화, 브라우저 사정으로 조용히 꺼질 때가 있다.
  // 통화 중에 마이크가 닫혀 있으면 노인은 이유를 알 수 없으므로 스스로 되살린다.
  useEffect(() => {
    if (!speech.supported) return undefined;
    const id = setInterval(() => {
      const idle =
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
  }, [speech, pending, resumeListening]);

  const last = faces.length - 1;
  const stageIndex = Math.min(Math.round(progress * last), last);
  const morphing = useVideo ? !morphDone : progress < 1;

  async function sendTyped() {
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    const reply = await send(text);
    if (reply) await speech.speak(reply);
    resumeListening();
  }

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
  const status = muted
    ? "마이크 꺼짐"
    : speech.playing
      ? `${name || "AI 가족"}이 말하는 중`
      : speech.speaking
        ? "목소리를 준비하는 중"
        : speech.transcribing
          ? "말씀을 확인하는 중"
          : pending
            ? "잠시만요"
          : speech.listening
            ? "듣고 있어요"
            : speech.starting
              ? "마이크 연결 중"
              : speech.active
                ? "듣기를 다시 연결하는 중"
                : "마이크 꺼짐";
  const subtitle = speech.listening && speech.interim
    ? speech.interim
    : spoken || "편하게 말씀하세요";

  return (
    <div className="call-screen">
      {useVideo ? (
        <MorphStage
          src={morphUrl}
          speaking={speech.playing}
          onEnded={() => setMorphDone(true)}
          onFail={() => setVideoFailed(true)}
        />
      ) : (
        <FaceStage faces={faces} progress={progress} speaking={speech.playing} />
      )}

      {/* 모핑이 끝나면 그 위에 표정 루프를 덮는다.
          루프가 없으면 모핑 마지막 프레임이 그대로 남는다. */}
      {morphDone && (
        <LoopStage
          loops={loops}
          want={
            speech.playing
              ? ["talking", "idle", "concerned"]
              : ["idle", "concerned", "talking"]
          }
        />
      )}

      <LipSyncStage
        active={speech.lipSyncActive}
        videoRef={speech.lipSyncVideoRef}
        blurRef={speech.lipSyncBlurRef}
      />

      {alert && <div className="alert-bar">{alert}</div>}

      <div className="topbar">
        <div className="badge">
          <b>{name}</b> · {elapsedText(elapsed)}
          {morphing && !useVideo ? ` · ${stageLabel(faces[stageIndex])}` : ""}
        </div>
        <SelfView />
      </div>

      <div className="bottom">
        <p className="said">
          {said ? `“${said}”` : status}
        </p>
        <p className={`spoken${speech.listening ? " live" : ""}`}>
          {pending ? <span className="thinking">…</span> : subtitle}
        </p>
        {(error || speech.error) && <p className="error">{error || speech.error}</p>}

        {(speech.mode === "server" || speech.mode === "realtime") && speech.listening && (
          <div className="call-mic-meter" aria-label="마이크 입력 크기">
            <span>마이크 입력</span>
            <b>
              <i style={{ width: `${Math.min(100, (speech.inputLevel || 0) * 1800)}%` }} />
            </b>
          </div>
        )}

        {typing && (
          <div className="composer">
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendTyped()}
              placeholder="하고 싶은 말"
              disabled={pending}
            />
            <button onClick={sendTyped} disabled={pending || !draft.trim()}>
              보내기
            </button>
          </div>
        )}

        <div className="controls">
          {speech.supported ? (
            <button
              className={`round${speech.listening ? " listening" : ""}`}
              onClick={toggleMute}
            >
              {muted
                ? "마이크 켜기"
                : "마이크 끄기"}
            </button>
          ) : (
            <button
              className={`round${typing ? " active" : ""}`}
              onClick={() => setTyping((t) => !t)}
            >
              글자로 말하기
            </button>
          )}
          <button className="round danger" onClick={hangup}>끊기</button>
        </div>

        {speech.supported && (
          <div className="dev">
            <button onClick={() => setTyping((t) => !t)}>
              {typing ? "글자 입력 닫기" : "글자로 입력"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
