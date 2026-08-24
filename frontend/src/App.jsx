import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api.js";
import { deviceId, deviceLabel, setGuardianPersonaId } from "./device.js";
import DisplaySettings from "./components/DisplaySettings.jsx";
import WideDisplayDock from "./components/WideDisplayDock.jsx";
import { useTheme } from "./theme.js";
import FamilyScreen from "./screens/FamilyScreen.jsx";
import CallingScreen from "./screens/CallingScreen.jsx";
import CallScreen from "./screens/CallScreen.jsx";
import SummaryScreen from "./screens/SummaryScreen.jsx";
import CareManagerScreen from "./screens/CareManagerScreen.jsx";
import ChildScreen from "./screens/ChildScreen.jsx";
import IncomingScreen from "./screens/IncomingScreen.jsx";
import SplashScreen from "./screens/SplashScreen.jsx";
import RoleScreen from "./screens/RoleScreen.jsx";
import LinkScreen from "./screens/LinkScreen.jsx";
import GuardianOnboardingScreen from "./screens/GuardianOnboardingScreen.jsx";
import HumanCallScreen from "./screens/HumanCallScreen.jsx";
import NetTestScreen from "./screens/NetTestScreen.jsx";
import { createTransport, openCallMedia } from "./callTransport.js";
import { useCallMediaReadiness } from "./useCallMediaReadiness.js";
import { useScreenWakeLock } from "./useScreenWakeLock.js";

// The server owns the ringing deadline. Polling only mirrors that state so a
// guardian answer, decline, or timeout is never inferred from a local timer.
const RING_POLL_MS = 1500;
const PENDING_POLL_MS = 20000;  // 복약 시간이 되었는지 주기적으로 확인
const RING_COOLDOWN_MS = 300000; // 거절하거나 통화가 끝난 뒤 다시 걸기까지

const KEY_ROLE = "dasoni.role";
const KEY_LINKED = "dasoni.linked";
const KEY_GUARDIAN_ONBOARDING = "dasoni.guardianOnboarding.v1";
const KEY_MY_PERSONA = "dasoni.myPersona";

function readLocal(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLocal(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // 저장에 실패해도 이번 세션에는 동작한다
  }
}

function removeLocal(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // 저장소를 사용할 수 없어도 현재 세션은 계속 진행한다.
  }
}

const ANNOUNCE_MS = 2600; // 예약 통화 연결 안내를 보여주는 시간

export default function App() {
  // 색과 글씨 크기는 앱 전체에 걸리므로 가장 바깥에서 한 번만 적용한다
  const { theme, size, setTheme, setSize } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 노인용과 보호자용은 쓰는 사람이 다르므로 주소로 나눈다.
  // 라우터를 들이지 않고 해시만 본다. #guardian 이면 보호자 화면.
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // 앱을 처음 열면 스플래시 → 역할 선택 → 연동을 거친다.
  // 한 번 고른 역할은 기기에 남아 다음부터 바로 본 화면으로 간다.
  const [booted, setBooted] = useState(false);
  const [role, setRole] = useState(() => {
    const saved = readLocal(KEY_ROLE);
    return saved === "guardian" ? "care" : saved;
  });
  const [linked, setLinked] = useState(() => readLocal(KEY_LINKED));
  const [guardianOnboarded, setGuardianOnboarded] = useState(
    () => readLocal(KEY_GUARDIAN_ONBOARDING) === "done"
  );
  const [myPersonaId, setMyPersonaId] = useState(() => readLocal(KEY_MY_PERSONA));
  const elderId = linked && linked !== "skipped" ? linked : "elder_001";

  // idle | calling | human | incall | ended
  const [phase, setPhase] = useState("idle");
  const [profile, setProfile] = useState(null);
  const [call, setCall] = useState(null);
  // 지금 울리고 있는 호출. 받았는지 여부는 서버만 안다.
  const [invite, setInvite] = useState(null);
  const [summary, setSummary] = useState(null);
  const [incomingReason, setIncomingReason] = useState(null);
  // 지금 통화하려는 가족. 대기 화면에서 고른 값이 통화 끝까지 따라간다.
  const [target, setTarget] = useState(null);
  const cooldownUntil = useRef(0);
  const [error, setError] = useState("");
  const timers = useRef([]);
  const phaseRef = useRef(phase);
  const inviteRef = useRef(invite);
  const callingMorphDoneRef = useRef(false);
  const humanTransport = useRef(null);
  const transportFailed = useRef(false);
  const takeoverInFlight = useRef(false);
  const [humanLocalStream, setHumanLocalStream] = useState(null);
  const [humanRemoteStream, setHumanRemoteStream] = useState(null);
  const [humanTransportState, setHumanTransportState] = useState("idle");
  const callMedia = useCallMediaReadiness(hash === "#elder" || role === "elder");

  useScreenWakeLock(phase === "calling" || phase === "human" || phase === "connecting" || phase === "incall");

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { inviteRef.current = invite; }, [invite]);

  useEffect(() => {
    api.getProfile(target?.persona_id, elderId).then(setProfile).catch((e) =>
      setError(`서버에 연결하지 못했어요. tools/serve.py 가 켜져 있는지 확인하세요. (${e.message})`)
    );
    return () => timers.current.forEach(clearTimeout);
  }, [target, elderId]);

  // 어르신 기기도 등록한다. 누가 걸었는지가 기록에 남아야 보호자 화면에서
  // "직접 거신 전화"와 "AI 가 먼저 건 전화"를 구분할 수 있다.
  useEffect(() => {
    api.registerDevice({
      device_id: deviceId(), elder_id: elderId,
      role: "elder", label: deviceLabel(),
    }).catch(() => {
      // 등록에 실패해도 전화는 걸 수 있어야 한다. from_device 만 비게 된다.
    });
  }, [elderId]);

  // 복약 시간이 되면 AI 쪽에서 전화를 건다.
  // 대기 화면일 때만 확인한다. 통화 중에는 세션이 알아서 약을 먼저 꺼낸다.
  useEffect(() => {
    if (phase !== "idle") return;
    let alive = true;
    const check = () => {
      if (Date.now() < cooldownUntil.current) return;
      api
        .getPendingCall(elderId)
        .then((r) => {
          if (!alive || !r.due) return;
          if (r.persona_id) {
            setTarget((current) => current?.persona_id === r.persona_id
              ? current
              : { persona_id: r.persona_id });
          }
          setIncomingReason(r.reason);
        })
        .catch(() => {});
    };
    check();
    const id = setInterval(check, PENDING_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [phase, elderId]);

  const enterCall = useCallback((res) => {
    setCall(res);
    // The fixed age-morph wait is useful preparation time. Warm only the
    // low-latency answer model here; failure is harmless because sendTurn can
    // still make the normal first request.
    api.prepareCall(res.call_id).catch(() => {});
    if (phaseRef.current === "calling") {
      if (callingMorphDoneRef.current) {
        phaseRef.current = "incall";
        setPhase("incall");
      }
      return;
    }
    timers.current.push(setTimeout(() => setPhase("incall"), ANNOUNCE_MS));
  }, []);

  const connectAI = useCallback(async (selectedPersonaId = null) => {
    try {
      enterCall(await api.startCall(selectedPersonaId ?? target?.persona_id, elderId));
    } catch (e) {
      setError(`통화를 열지 못했어요. (${e.message})`);
      setPhase("idle");
    }
  }, [target, elderId, enterCall]);

  const releaseHumanTransport = useCallback(async () => {
    const current = humanTransport.current;
    humanTransport.current = null;
    if (current) await current.disconnect().catch(() => {});
    setHumanLocalStream(null);
    setHumanRemoteStream(null);
    setHumanTransportState("idle");
  }, []);

  const fallBackFromHuman = useCallback(async (inviteId) => {
    if (!inviteId || takeoverInFlight.current) return;
    takeoverInFlight.current = true;
    // 마이크 주인을 먼저 완전히 비운 뒤 Web Speech API가 있는 AI 화면을 연다.
    await releaseHumanTransport(false);
    try {
      const res = await api.takeOverInvite(inviteId, "transport_failed");
      setInvite(res.invite);
      enterCall(res);
    } catch {
      // 연결 실패는 어르신에게 장애로 보이지 않는다. 상태 API까지 잠깐
      // 불안정하면 새 AI 세션으로라도 대화를 이어 간다.
      await connectAI();
    } finally {
      takeoverInFlight.current = false;
    }
  }, [connectAI, enterCall, releaseHumanTransport]);

  const prepareHumanTransport = useCallback(async (inviteId) => {
    transportFailed.current = false;
    setHumanTransportState("connecting");
    try {
      const stream = await openCallMedia();
      if (inviteRef.current?.invite_id !== inviteId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      setHumanLocalStream(stream);
      const transport = createTransport({
        inviteId, role: "caller", localStream: stream,
      });
      humanTransport.current = transport;
      transport.onRemoteStream(setHumanRemoteStream);
      transport.onStateChange((state) => {
        setHumanTransportState(state);
        if (state !== "failed") return;
        transportFailed.current = true;
        if (phaseRef.current === "human") fallBackFromHuman(inviteId);
      });
      await transport.connect();
    } catch {
      transportFailed.current = true;
      setHumanTransportState("failed");
      if (phaseRef.current === "human") fallBackFromHuman(inviteId);
    }
  }, [fallBackFromHuman]);

  /**
   * Follow the server-owned invite while the current morph acts as the
   * waiting screen. A direct answer wins immediately; AI is opened only after
   * decline/timeout or when the person-to-person media path cannot connect.
   */
  useEffect(() => {
    if (phase !== "calling" || !invite?.invite_id) return undefined;

    let alive = true;
    let timer = null;
    const inviteId = invite.invite_id;

    const tick = async () => {
      if (!alive) return;
      try {
        const current = await api.getInvite(inviteId);
        if (!alive) return;

        if (current.state === "answered") {
          setInvite(current);
          if (transportFailed.current) {
            fallBackFromHuman(inviteId);
          } else {
            phaseRef.current = "human";
            setPhase("human");
          }
          return;
        }

        if (current.should_take_over) {
          await releaseHumanTransport();
          const res = await api.takeOverInvite(inviteId);
          if (!alive) return;
          setInvite(res.invite);
          enterCall(res);
          return;
        }

        if (current.state === "cancelled" || current.state === "ended") {
          await releaseHumanTransport();
          phaseRef.current = "idle";
          setPhase("idle");
          setInvite(null);
          return;
        }
      } catch (reason) {
        if (!alive) return;
        await releaseHumanTransport();
        setError(`연결 상태를 확인하지 못해 AI가 이어서 받을게요. (${reason.message})`);
        connectAI(target?.persona_id);
        return;
      }

      if (alive) timer = setTimeout(tick, RING_POLL_MS);
    };

    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [
    phase, invite?.invite_id, target?.persona_id, connectAI, enterCall,
    fallBackFromHuman, releaseHumanTransport,
  ]);

  // 보호자가 받은 뒤 12초 안에 미디어가 붙지 않으면 조용히 AI로 넘긴다.
  useEffect(() => {
    if (phase !== "human" || !invite?.invite_id || humanTransportState === "connected") {
      return undefined;
    }
    const id = setTimeout(
      () => fallBackFromHuman(invite.invite_id), 12000,
    );
    return () => clearTimeout(id);
  }, [phase, invite?.invite_id, humanTransportState, fallBackFromHuman]);

  // 가족이 먼저 끊었을 때. 어르신 화면이 통화 중에 갇히면 스스로 빠져나오기
  // 어렵다. 끊는 쪽은 어느 쪽이든 될 수 있으므로 양쪽 모두 상태를 확인한다.
  useEffect(() => {
    if (phase !== "human" || !invite?.invite_id) return undefined;
    let alive = true;
    let timer = null;
    const inviteId = invite.invite_id;

    const tick = async () => {
      if (!alive) return;
      try {
        const current = await api.getInvite(inviteId);
        if (!alive) return;
        if (current.state === "ended" || current.state === "cancelled") {
          await releaseHumanTransport(false);
          setInvite(null);
          setTarget(null);
          cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
          setPhase("idle");
          return;
        }
      } catch {
        // 잠깐 끊긴 것으로 본다. 통화를 먼저 닫지 않는다.
      }
      if (alive) timer = setTimeout(tick, 2000);
    };

    timer = setTimeout(tick, 2000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [phase, invite?.invite_id, releaseHumanTransport]);

  async function startCalling(picked) {
    const person = picked ?? target;
    if (!callMedia.ready) {
      try {
        const prepared = await callMedia.prepare();
        if (!prepared?.ready) throw new Error("microphone unavailable");
      } catch {
        setError("마이크 연결이 안 됐어요. 마이크 권한과 연결 상태를 확인해 주세요.");
        return;
      }
    }
    if (picked) setTarget(picked);
    setError("");
    setCall(null);
    setSummary(null);
    setInvite(null);
    callingMorphDoneRef.current = false;
    phaseRef.current = "calling";
    setPhase("calling");

    try {
      const created = await api.ringFamily({
        elder_id: elderId,
        persona_id: person?.persona_id,
        from_device: deviceId(),
      });
      setInvite(created);
      // React state reaches the transport guard on the next render. Keep the
      // ref in sync now so early media permission resolution is not discarded.
      inviteRef.current = created;
      // Gather ICE while the family phone is ringing to shorten answer time.
      prepareHumanTransport(created.invite_id);
    } catch (reason) {
      setError(`가족에게 연결하지 못해 AI가 이어서 받을게요. (${reason.message})`);
      connectAI(person?.persona_id);
    }
  }

  function answerIncoming() {
    setIncomingReason(null);
    setError("");
    setCall(null);
    setSummary(null);
    setPhase("connecting");
    connectAI();
  }

  function reset() {
    setTarget(null);
    // 통화가 끝난 직후에 곧바로 다시 걸려오면 성가시다.
    // 약이 확인되었으면 어차피 due 가 false 가 되므로 울리지 않는다.
    cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    // 호출 기록을 닫는다. 실패해도 화면은 대기로 돌아가야 한다.
    if (invite?.invite_id) api.endInvite(invite.invite_id).catch(() => {});
    releaseHumanTransport(false);
    setInvite(null);
    setCall(null);
    setSummary(null);
    callingMorphDoneRef.current = false;
    setPhase("idle");
  }

  function finishCallingMorph() {
    callingMorphDoneRef.current = true;
    if (!call) return;
    phaseRef.current = "incall";
    setPhase("incall");
  }

  /** 사람 통화를 끝낸다. 리포트가 없으므로 대기 화면으로 곧장 돌아간다. */
  async function endHumanCall() {
    if (invite?.invite_id) await api.endInvite(invite.invite_id).catch(() => {});
    await releaseHumanTransport(false);
    cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
    setInvite(null);
    setTarget(null);
    setPhase("idle");
  }

  const wrap = (node, { gear = false, wide = false, roleSwitch = false, displayDock = true, embeddedControls = false, shell = "default" } = {}) => (
    <div className={`frame app-shell app-shell-${shell}${wide ? " guardian-frame" : ""}`}>
      <div className={`device app-device app-device-${shell}${wide ? " guardian-device" : ""}`}>
        {wide && displayDock && (roleSwitch || gear) && <WideDisplayDock
          theme={theme}
          size={size}
          onTheme={setTheme}
          onSize={setSize}
          onRole={() => { setRole(null); window.location.hash = ""; }}
        />}
        {!wide && roleSwitch && !embeddedControls && (
          <button
            className="role-switch"
            onClick={() => { setRole(null); window.location.hash = ""; }}
            aria-label="역할 선택 화면으로 돌아가기"
          >
            역할 선택
          </button>
        )}
        {!wide && gear && !embeddedControls && (
          <button
            className="gear"
            onClick={() => setSettingsOpen(true)}
            aria-label="화면 설정"
          >
            Aa
          </button>
        )}
        {node}
        {settingsOpen && (
          <DisplaySettings
            theme={theme}
            size={size}
            onTheme={setTheme}
            onSize={setSize}
            onClose={() => setSettingsOpen(false)}
            onRole={roleSwitch ? () => {
              setSettingsOpen(false);
              setRole(null);
              window.location.hash = "";
            } : null}
          />
        )}
      </div>
    </div>
  );

  const chooseRole = (picked) => {
    setRole(picked);
    setBooted(true);
    writeLocal(KEY_ROLE, picked);
    // 역할 선택 뒤에는 데모용 직행 주소가 아니라 실제 앱의 연동·온보딩
    // 흐름을 탄다. 저장된 연동이 있으면 해당 역할의 홈으로 바로 이어진다.
    window.location.hash = "";
  };

  const finishLink = (nextElderId) => {
    const nextLinked = nextElderId || "skipped";
    if (linked !== nextLinked) {
      setGuardianOnboarded(false);
      setMyPersonaId(null);
      removeLocal(KEY_GUARDIAN_ONBOARDING);
      removeLocal(KEY_MY_PERSONA);
    }
    setLinked(nextLinked);
    writeLocal(KEY_LINKED, nextLinked);
  };

  const finishGuardianOnboarding = (result) => {
    // 온보딩 첫 화면이 이미 "나는 누구인가"를 묻는다. 그 답이 곧 이 폰으로
    // 벨을 배달할 주소이므로 여기서 그대로 기억한다. 보호자에게 같은 질문을
    // 두 번 하면 두 답이 어긋날 수 있고, 어긋나면 전화가 오지 않는다.
    if (result?.personaId) {
      setGuardianPersonaId(result.personaId);
      setMyPersonaId(result.personaId);
      writeLocal(KEY_MY_PERSONA, result.personaId);
    }
    setGuardianOnboarded(true);
    writeLocal(KEY_GUARDIAN_ONBOARDING, "done");
  };

  const saveMyPersona = (personaId) => {
    if (!personaId) return;
    setGuardianPersonaId(personaId);
    setMyPersonaId(personaId);
    writeLocal(KEY_MY_PERSONA, personaId);
  };

  // P2P 가 이 망에서 붙는지 재는 화면. 통화 흐름과 무관하게 따로 연다.
  if (hash === "#nettest") return wrap(<NetTestScreen />, { wide: true, shell: "nettest" });

  // 역할 선택 주소는 개발·사용자 전환용으로 바로 연다. 일반적인 첫 실행은
  // 스플래시를 본 뒤 아래의 역할 선택으로 이어진다.
  if (hash === "#roles")
    return wrap(<RoleScreen onPick={chooseRole} />, { wide: true, shell: "roles" });

  // 주소로 직접 들어온 경우는 입구를 건너뛴다.
  // #elder는 이 브라우저에 저장된 보호자 역할과 무관하게 어르신 화면을 연다.
  const directElder = hash === "#elder";
  if (hash === "#care" || hash === "#guardian")
    return wrap(<CareManagerScreen onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "care" });
  if (hash === "#child" || hash === "#family") {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true, roleSwitch: true, shell: "family" });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "family" });
  }

  if (!directElder && !booted)
    return wrap(<SplashScreen onDone={() => setBooted(true)} />);

  if (!directElder && !role)
    return wrap(<RoleScreen onPick={chooseRole} />, { wide: true, shell: "roles" });

  if (!directElder && !linked)
    return wrap(
      <LinkScreen
        role={role}
        onLinked={finishLink}
        onSkip={() => finishLink("skipped")}
      />,
      { wide: true, roleSwitch: true, shell: role === "care" ? "care" : "family" }
    );

  if (!directElder && role === "care") {
    return wrap(<CareManagerScreen onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "care" });
  }

  if (!directElder && role === "child") {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true, shell: "family" });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "family" });
  }


  if (phase === "idle" && incomingReason)
    return wrap(
      <IncomingScreen
        profile={profile?.persona?.persona_id === target?.persona_id ? profile : null}
        reason={incomingReason}
        onAnswer={answerIncoming}
        onDecline={() => {
          cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
          setIncomingReason(null);
          setTarget(null);
        }}
      />
    );

  if (phase === "idle")
    return wrap(
      <FamilyScreen
        elderId={elderId}
        onPick={startCalling}
        error={error}
        media={callMedia}
        onOpenSettings={() => setSettingsOpen(true)}
        onRole={() => { setRole(null); window.location.hash = ""; }}
      />,
      { gear: true, roleSwitch: true, embeddedControls: true }
    );

  if (phase === "connecting")
    return wrap(
      <CallingScreen
        name={profile?.persona?.display_name ?? "가족"}
        announcement={call?.announcement ?? "연결하고 있어요"}
      />
    );

  if ((phase === "calling" || phase === "incall") && (phase === "calling" || call)) {
    const conversationEnabled = phase === "incall";
    return wrap(
      <div className="call-stack">
        {call && <CallScreen
          key={call.call_id}
          faces={call.faces?.length ? call.faces : profile?.faces ?? []}
          opening={call.opening ?? ""}
          name={profile?.persona?.display_name ?? "가족"}
          personaId={call.persona_id ?? target?.persona_id ?? null}
          callId={call.call_id}
          api={api}
          conversationEnabled={conversationEnabled}
          performanceStyle={profile?.persona?.avatar_performance_style ?? "calm"}
          onEnded={(s) => {
            setSummary(s);
            setPhase("ended");
          }}
        />}

        {phase === "calling" && <CallingScreen
          name={profile?.persona?.display_name ?? "가족"}
          announcement={call?.announcement ?? "연결하고 있어요"}
          morphUrl={profile?.morph_url ?? null}
          onMorphEnded={finishCallingMorph}
        />}
      </div>
    );
  }

  if (phase === "human" && invite)
    return wrap(
      <HumanCallScreen
        name={profile?.persona?.display_name ?? "가족"}
        face={profile?.faces?.at(-1)?.url}
        answeredAt={invite.answered_at}
        localStream={humanLocalStream}
        remoteStream={humanRemoteStream}
        onEnd={endHumanCall}
      />
    );

  if (phase === "ended" && summary)
    return wrap(<SummaryScreen summary={summary} onRestart={reset} />);

  return wrap(<div className="screen"><p className="hint">준비하는 중…</p></div>);
}
