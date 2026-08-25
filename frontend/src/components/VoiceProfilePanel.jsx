import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api.js";
import { assessVoiceRecording, recordingMimeType } from "../voiceQuality.js";

const INITIAL_PROMPTS = [
  {
    id: "general",
    label: "평소 이야기",
    script: "안녕하세요. 오늘은 제 목소리를 편안하게 남겨보려고 해요. 저는 아침에 일어나면 창문을 열고 바깥 날씨를 먼저 살펴봅니다. 햇빛이 좋으면 천천히 산책하고, 비가 오면 따뜻한 차를 마시며 하루를 시작해요. 가족과 함께 밥을 먹고 소소한 이야기를 나누는 시간이 참 좋습니다. 특별한 일이 없어도 서로의 목소리를 듣고 안부를 묻는 것만으로 마음이 놓일 때가 있어요. 서두르지 않아도 괜찮고, 기억이 바로 나지 않아도 괜찮아요. 오늘 있었던 일부터 하나씩 천천히 이야기하면 됩니다. 저는 늘 같은 마음으로 곁에서 듣고 있을게요.",
  },
  {
    id: "care",
    label: "안심 돌봄 이야기",
    script: "괜찮아요. 많이 놀라셨죠. 제가 여기 있으니 걱정하지 않으셔도 돼요. 지금 보이는 것을 하나씩 같이 확인해 볼까요. 익숙한 사진과 시계가 보이면 그 자리에 편하게 앉아 계세요. 물 한 잔을 천천히 드시고, 해야 할 일은 한 번에 하나씩만 하면 됩니다. 약을 드셨는지 헷갈릴 때에는 다시 드시지 말고 약통과 기록을 먼저 확인해요. 몸이 아프거나 넘어지셨다면 혼자 움직이지 말고 바로 알려주세요. 제가 목소리를 들으며 함께 기다릴게요. 오늘도 충분히 잘하고 계세요. 급하게 생각하지 말고 천천히 말씀해 주세요.",
  },
];

const PREVIEW_TEXT = "오늘도 제 목소리 들으면서 천천히 이야기해요. 제가 곁에서 함께 듣고 있을게요.";

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  return `${Math.floor(seconds / 60)}분 ${String(seconds % 60).padStart(2, "0")}초`;
}

function RecorderCard({ prompt, phase, disabled, saved, onSaved, maxSeconds = 90 }) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [capture, setCapture] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const contextRef = useRef(null);
  const animationRef = useRef(0);
  const timerRef = useRef(0);
  const startedRef = useRef(0);
  const captureUrlRef = useRef("");
  const levelsRef = useRef({ frames: 0, rms: 0, clipped: 0, samples: 0 });

  function release() {
    cancelAnimationFrame(animationRef.current);
    clearInterval(timerRef.current);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    contextRef.current?.close?.().catch(() => {});
    contextRef.current = null;
  }

  useEffect(() => () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    release();
    if (captureUrlRef.current) URL.revokeObjectURL(captureUrlRef.current);
  }, []);

  async function start() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("이 브라우저에서는 녹음을 사용할 수 없습니다. 최신 Chrome으로 열어주세요.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      streamRef.current = stream;
      const mimeType = recordingMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      const chunks = [];
      levelsRef.current = { frames: 0, rms: 0, clipped: 0, samples: 0 };

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        const context = new AudioContextClass();
        contextRef.current = context;
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        const data = new Uint8Array(analyser.fftSize);
        const sample = () => {
          analyser.getByteTimeDomainData(data);
          let squareSum = 0;
          let clipped = 0;
          for (const value of data) {
            const normalized = (value - 128) / 128;
            squareSum += normalized * normalized;
            if (Math.abs(normalized) >= 0.98) clipped += 1;
          }
          const rms = Math.sqrt(squareSum / data.length);
          levelsRef.current.frames += 1;
          levelsRef.current.rms += rms;
          levelsRef.current.clipped += clipped;
          levelsRef.current.samples += data.length;
          animationRef.current = requestAnimationFrame(sample);
        };
        sample();
      }

      recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
      recorder.onstop = () => {
        const durationSeconds = (performance.now() - startedRef.current) / 1000;
        const level = levelsRef.current;
        const quality = assessVoiceRecording({
          durationSeconds,
          averageLevel: level.frames ? level.rms / level.frames : 0,
          clippedRatio: level.samples ? level.clipped / level.samples : 0,
        });
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (captureUrlRef.current) URL.revokeObjectURL(captureUrlRef.current);
        const url = URL.createObjectURL(blob);
        captureUrlRef.current = url;
        setCapture({ blob, url, durationSeconds, quality });
        setElapsed(durationSeconds);
        setRecording(false);
        release();
      };
      startedRef.current = performance.now();
      recorder.start(500);
      if (captureUrlRef.current) URL.revokeObjectURL(captureUrlRef.current);
      captureUrlRef.current = "";
      setCapture(null);
      setElapsed(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        const next = (performance.now() - startedRef.current) / 1000;
        setElapsed(next);
        if (next >= maxSeconds && recorder.state === "recording") recorder.stop();
      }, 250);
    } catch (reason) {
      release();
      setError(reason?.name === "NotAllowedError"
        ? "마이크 권한이 필요합니다. Chrome 주소창의 권한에서 마이크를 허용해 주세요."
        : `녹음을 시작하지 못했습니다. (${reason.message})`);
    }
  }

  function stop() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  async function save() {
    if (!capture?.quality?.passed) return;
    setBusy(true);
    setError("");
    try {
      await onSaved({
        blob: capture.blob,
        phase,
        promptId: phase === "ivc" ? prompt.id : `pvc_${Date.now()}`,
        durationSeconds: capture.durationSeconds,
        quality: capture.quality,
      });
      setCapture(null);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  return <article className={`voice-recorder-card ${saved ? "is-saved" : ""}`}>
    <header>
      <div>{phase === "ivc" && <small>필수 녹음</small>}<h3>{prompt.label}</h3></div>
      <div className="voice-recorder-heading-actions">
        {(saved || recording) && <span>{saved ? "저장 완료" : formatDuration(elapsed)}</span>}
        {phase === "pvc" && !recording && <button type="button" onClick={start} disabled={disabled || busy}>녹음 시작</button>}
        {phase === "pvc" && recording && <button type="button" className="is-recording" onClick={stop}>녹음 마치기</button>}
      </div>
    </header>
    <p className="voice-script">{prompt.script}</p>
    <div className="voice-recorder-actions">
      {phase !== "pvc" && !recording && <button type="button" onClick={start} disabled={disabled || busy}>{saved ? "다시 녹음" : "녹음 시작"}</button>}
      {phase !== "pvc" && recording && <button type="button" className="is-recording" onClick={stop}>녹음 마치기</button>}
      {capture?.url && <audio controls src={capture.url} />}
      {capture?.quality?.passed && <button type="button" className="primary" onClick={save} disabled={busy}>{busy ? "저장 중…" : "이 녹음 저장"}</button>}
    </div>
    {capture?.quality && <div className={`voice-quality ${capture.quality.passed ? "passed" : "failed"}`}>
      <b>{capture.quality.passed ? "음질 확인 완료" : "다시 녹음해 주세요"}</b>
      <span>{formatDuration(capture.durationSeconds)} · 음량 {Math.round(capture.quality.average_level * 1000)}</span>
      {capture.quality.issues.map((issue) => <p key={issue}>{issue}</p>)}
    </div>}
    {error && <p className="error">{error}</p>}
  </article>;
}

export default function VoiceProfilePanel({ elderId, personaId, persona, useDefaultVoice = false, onUseDefaultVoice }) {
  const [profile, setProfile] = useState(null);
  const [quietReady, setQuietReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");

  const readyPrompts = useMemo(() => new Set(profile?.ivc_prompts_ready || []), [profile]);
  const approved = Boolean(profile?.active_voice_type);
  const pvcMinutes = Math.round((profile?.recorded_seconds || 0) / 60);
  const pvcPercent = Math.min(100, ((profile?.recorded_seconds || 0) / 3600) * 100);

  useEffect(() => {
    let alive = true;
    setProfile(null);
    setError("");
    api.getVoiceProfile(personaId, elderId)
      .then((result) => alive && setProfile(result))
      .catch((reason) => alive && setError(reason.message));
    return () => { alive = false; };
  }, [elderId, personaId]);

  useEffect(() => () => previewUrl && URL.revokeObjectURL(previewUrl), [previewUrl]);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      if (result) setProfile(result);
      return result;
    } catch (reason) {
      setError(reason.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function saveSample(sample) {
    const result = await api.uploadVoiceSample(personaId, { ...sample, elderId });
    setProfile(result);
  }

  async function preview() {
    setBusy(true);
    setError("");
    try {
      const blob = await api.previewPersonaVoice(personaId, PREVIEW_TEXT, elderId);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function restartVoiceRecording() {
    if (!window.confirm("현재 승인된 목소리를 초기화하고 다시 녹음할까요? 기존 녹음은 되돌릴 수 없습니다.")) return;
    const result = await run(() => api.deleteVoiceProfile(personaId, elderId));
    if (!result) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl("");
    setQuietReady(false);
  }

  if (!profile) return <section className="family-voice-settings"><p>{error ? `목소리 설정을 불러오지 못했습니다. (${error})` : "목소리 설정을 불러오는 중…"}</p></section>;

  return <section className="family-voice-settings">
    <header className="voice-settings-heading">
      <div><h2>AI 통화에 사용할 목소리를 등록하세요</h2></div>
      <div className="voice-heading-actions">
        {!approved && <strong>{profile.voice_status === "ivc_ready" ? "미리 듣기" : `${readyPrompts.size}/2 녹음`}</strong>}
      </div>
    </header>

    {!profile.consented && <div className="voice-consent-card">
      <h3>먼저 본인 음성 사용에 동의해 주세요</h3>
      <p>직접 녹음한 음성은 {persona?.display_name || "가족"}님의 AI 통화 목소리를 만드는 데 사용됩니다. 본인만 등록할 수 있습니다.</p>
      <button type="button" className="primary" disabled={busy} onClick={() => run(() => api.saveVoiceConsent(personaId, true, elderId))}>동의하고 시작</button>
    </div>}

    {profile.consented && !approved && <>
      <div className="voice-environment-check">
        <label><input type="checkbox" checked={quietReady} onChange={(event) => setQuietReady(event.target.checked)} /><span><b>조용한 방에서 혼자 녹음하고 있어요</b>TV·음악을 끄고, 휴대폰을 입에서 한 뼘 정도 떨어뜨려 주세요. 음성은 자동 보정하지 않습니다.</span></label>
      </div>
      <div className="voice-recorder-grid">
        {INITIAL_PROMPTS.map((prompt) => <RecorderCard
          key={prompt.id}
          prompt={prompt}
          phase="ivc"
          disabled={!quietReady}
          saved={readyPrompts.has(prompt.id)}
          onSaved={saveSample}
        />)}
      </div>
      {profile.ivc_can_create && !["ivc_ready", "pvc_collecting"].includes(profile.voice_status) && <div className="voice-create-card">
        <div><small>2개 녹음 준비 완료</small><h3>지금 목소리를 만들 수 있어요</h3><p>두 녹음을 ElevenLabs에 보내 즉시 복제 목소리를 만듭니다.</p></div>
        <button type="button" className="primary" disabled={busy} onClick={() => run(() => api.createInstantVoice(personaId, elderId))}>{busy ? "만드는 중…" : "목소리 만들기"}</button>
      </div>}
      {profile.voice_status === "ivc_ready" && <div className="voice-approval-card">
        <div><small>처음 읽지 않은 문장</small><h3>새 문장으로 목소리를 확인하세요</h3><p>“{PREVIEW_TEXT}”</p></div>
        <div className="voice-preview-actions">
          <button type="button" onClick={preview} disabled={busy}>미리 듣기</button>
          {previewUrl && <audio controls autoPlay src={previewUrl} />}
          <button type="button" className="primary" disabled={busy} onClick={() => run(() => api.approvePersonaVoice(personaId, elderId))}>이 목소리 사용</button>
        </div>
      </div>}
    </>}

    {!approved && onUseDefaultVoice && <div className="voice-default-start">
      <button type="button" className={useDefaultVoice ? "selected" : ""} aria-pressed={useDefaultVoice} onClick={onUseDefaultVoice}>
        {useDefaultVoice ? "기본 목소리로 시작할게요" : "기본 목소리로 시작하기"}
      </button>
      <small>내 목소리는 나중에 설정에서 등록할 수 있어요.</small>
    </div>}

    {approved && <div className="voice-pvc-area">
      <div className="voice-active-summary">
        <div className="voice-active-summary-copy"><h3>{persona?.display_name || "가족"}님의 승인된 목소리</h3></div>
        <div className="voice-active-actions">
          <button type="button" className="voice-headset-button" onClick={preview} disabled={busy} aria-label="다시 듣기">🎧</button>
          <button type="button" onClick={restartVoiceRecording} disabled={busy} aria-label="다시 녹음하기">다시 녹음</button>
        </div>
        {previewUrl && <div className="voice-active-preview"><audio controls autoPlay src={previewUrl} /></div>}
      </div>
      <div className="voice-progress-card">
        <header><div><h3>좋은 녹음을 천천히 더 모을 수 있어요</h3></div><strong>{pvcMinutes}분 / 권장 60분</strong></header>
        <div className="voice-progress"><i style={{ width: `${pvcPercent}%` }} /></div>
        <div className="voice-progress-marks"><span>현재</span><span className={profile.pvc_eligible ? "reached" : ""}>30분 · 신청 가능</span><span className={profile.pvc_recommended ? "reached" : ""}>60분 · 권장</span></div>
      </div>
      <RecorderCard
        prompt={{ id: "pvc", label: "추가 목소리 모으기", script: "평소처럼 가족 이야기, 하루 일과, 기억에 남는 장소를 1~5분 동안 자연스럽게 말씀해 주세요. 같은 문장을 반복하기보다 여러 내용과 억양이 담기면 좋습니다." }}
        phase="pvc"
        disabled={false}
        saved={false}
        onSaved={saveSample}
        maxSeconds={360}
      />
    </div>}
    {error && <p className="error">목소리 설정을 처리하지 못했습니다. ({error})</p>}
  </section>;
}
