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
import ChildScreen from "./screens/ChildScreen.jsx";
import SplashScreen from "./screens/SplashScreen.jsx";
import RoleScreen from "./screens/RoleScreen.jsx";
import LinkScreen from "./screens/LinkScreen.jsx";
import GuardianOnboardingScreen from "./screens/GuardianOnboardingScreen.jsx";
import LoginScreen from "./screens/LoginScreen.jsx";
import RoleOnboardingScreen, { ONBOARDING_FLOW_VERSION } from "./screens/RoleOnboardingScreen.jsx";
import HumanCallScreen from "./screens/HumanCallScreen.jsx";
import NetTestScreen from "./screens/NetTestScreen.jsx";
import { createTransport, openCallMedia } from "./callTransport.js";
import { useCallMediaReadiness } from "./useCallMediaReadiness.js";
import { useScreenWakeLock } from "./useScreenWakeLock.js";
import { startWaitingMelody, stopWaitingMelody } from "./waitingMelody.js";

// The server owns the ringing deadline. Polling only mirrors that state so a
// guardian answer, decline, or timeout is never inferred from a local timer.
const RING_POLL_MS = 1500;
const RING_COOLDOWN_MS = 300000; // 통화가 끝난 뒤 중복 상태 전환을 막는 유예
// 모바일 WebRTC의 ICE 연결은 같은 와이파이에서도 수 초 이상 걸릴 수 있다.
// 24초 인트로가 끝난 뒤에만 이 유예 시간을 적용해 정상적인 받기를 인트로
// 도중에 실패로 닫지 않는다.
const HUMAN_CONNECT_GRACE_MS = 20000;

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
  const [account, setAccount] = useState(null);
  const [demoMode, setDemoMode] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [role, setRole] = useState(() => {
    const saved = readLocal(KEY_ROLE);
    if (saved === "guardian") return "child";
    return saved === "elder" || saved === "child" ? saved : null;
  });
  const [linked, setLinked] = useState(() => readLocal(KEY_LINKED));
  const [guardianOnboarded, setGuardianOnboarded] = useState(
    () => readLocal(KEY_GUARDIAN_ONBOARDING) === "done"
  );
  const [roleOnboarded, setRoleOnboarded] = useState(null);
  const [myPersonaId, setMyPersonaId] = useState(() => readLocal(KEY_MY_PERSONA));
  const elderId = linked && linked !== "skipped" ? linked : "elder_001";

  // idle | calling | human | incall | ended
  const [phase, setPhase] = useState("idle");
  const [profile, setProfile] = useState(null);
  const [call, setCall] = useState(null);
  // 지금 울리고 있는 호출. 받았는지 여부는 서버만 안다.
  const [invite, setInvite] = useState(null);
  const [summary, setSummary] = useState(null);
  // 지금 통화하려는 가족. 대기 화면에서 고른 값이 통화 끝까지 따라간다.
  const [target, setTarget] = useState(null);
  const cooldownUntil = useRef(0);
  const [error, setError] = useState("");
  const timers = useRef([]);
  const phaseRef = useRef(phase);
  const inviteRef = useRef(invite);
  const callingIntroDoneRef = useRef(false);
  const humanTransport = useRef(null);
  const transportFailed = useRef(false);
  const takeoverInFlight = useRef(false);
  const [humanLocalStream, setHumanLocalStream] = useState(null);
  const [humanRemoteStream, setHumanRemoteStream] = useState(null);
  const [humanTransportState, setHumanTransportState] = useState("idle");
  const callMedia = useCallMediaReadiness(hash === "#elder" || role === "elder");
  const elderAccessReady = Boolean(
    (import.meta.env.DEV && hash === "#elder")
    || (account && role === "elder" && roleOnboarded)
  );

  useEffect(() => {
    if (!api.authToken()) {
      setAuthChecked(true);
      return;
    }
    api.getCurrentAccount()
      .then(({ user }) => setAccount(user))
      .catch(() => api.saveAuthToken(""))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!account || !role) {
      setRoleOnboarded(null);
      return;
    }
    if (demoMode) {
      setRoleOnboarded(true);
      setLinked("elder_001");
      return;
    }
    let alive = true;
    api.getOnboarding(role).then((saved) => {
      if (!alive) return;
      const currentFlowComplete = Boolean(
        saved.complete && saved.data?.onboarding_version === ONBOARDING_FLOW_VERSION
      );
      setRoleOnboarded(currentFlowComplete);
      const savedElder = saved.data?.elder_id;
      if (saved.complete && savedElder) {
        setLinked(savedElder);
        writeLocal(KEY_LINKED, savedElder);
      }
      const savedPersona = saved.data?.persona_id;
      if (saved.complete && role === "child" && savedPersona) {
        setGuardianPersonaId(savedPersona);
        setMyPersonaId(savedPersona);
        writeLocal(KEY_MY_PERSONA, savedPersona);
        setGuardianOnboarded(true);
        writeLocal(KEY_GUARDIAN_ONBOARDING, "done");
      }
    }).catch(() => setRoleOnboarded(false));
    return () => { alive = false; };
  }, [account, role, demoMode]);

  useScreenWakeLock(phase === "calling" || phase === "human" || phase === "connecting" || phase === "incall");

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { inviteRef.current = invite; }, [invite]);
  useEffect(() => {
    if (phase !== "calling") stopWaitingMelody();
  }, [phase]);
  useEffect(() => () => stopWaitingMelody(), []);

  useEffect(() => {
    if (!elderAccessReady) {
      setProfile(null);
      return undefined;
    }
    api.getProfile(target?.persona_id, elderId).then(setProfile).catch((e) =>
      setError(`서버에 연결하지 못했어요. tools/serve.py 가 켜져 있는지 확인하세요. (${e.message})`)
    );
    return () => timers.current.forEach(clearTimeout);
  }, [target, elderId, elderAccessReady]);

  // 어르신 기기도 등록한다. 누가 걸었는지가 기록에 남아야 보호자 화면에서
  // "직접 거신 전화"와 "AI 가 먼저 건 전화"를 구분할 수 있다.
  useEffect(() => {
    if (!elderAccessReady) return undefined;
    api.registerDevice({
      device_id: deviceId(), elder_id: elderId,
      role: "elder", label: deviceLabel(),
    }).catch(() => {
      // 등록에 실패해도 전화는 걸 수 있어야 한다. from_device 만 비게 된다.
    });
  }, [elderId, elderAccessReady]);

  const enterCall = useCallback((res) => {
    setCall(res);
    // The fixed age-morph wait is useful preparation time. Warm only the
    // low-latency answer model here; failure is harmless because sendTurn can
    // still make the normal first request.
    api.prepareCall(res.call_id).then((prepared) => {
      if (typeof prepared?.anam_ready !== "boolean") return;
      setCall((current) => current?.call_id === res.call_id
        ? { ...current, anam_ready: prepared.anam_ready }
        : current);
    }).catch(() => {});
    if (phaseRef.current === "calling") {
      if (callingIntroDoneRef.current) {
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

  const resumeRiskAi = useCallback(async () => {
    await releaseHumanTransport(false);
    setInvite(null);
    inviteRef.current = null;
    transportFailed.current = false;
    setError("");
    phaseRef.current = "incall";
    setPhase("incall");
  }, [releaseHumanTransport]);

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
      const mediaConfig = await api.getCallMediaConfig().catch(() => null);
      const transport = createTransport({
        inviteId, role: "caller", localStream: stream,
        iceServers: mediaConfig?.ice_servers,
      });
      humanTransport.current = transport;
      transport.onRemoteStream(setHumanRemoteStream);
      transport.onStateChange((state) => {
        setHumanTransportState(state);
        if (state !== "failed") return;
        transportFailed.current = true;
        if (phaseRef.current === "human") {
          if (inviteRef.current?.purpose === "risk") resumeRiskAi();
          else fallBackFromHuman(inviteId);
        }
      });
      await transport.connect();
    } catch {
      transportFailed.current = true;
      setHumanTransportState("failed");
      if (phaseRef.current === "human") {
        if (inviteRef.current?.purpose === "risk") resumeRiskAi();
        else fallBackFromHuman(inviteId);
      }
    }
  }, [fallBackFromHuman, resumeRiskAi]);

  const handleRiskDetected = useCallback((riskInvite) => {
    if (!riskInvite?.invite_id || inviteRef.current?.invite_id === riskInvite.invite_id) return;
    inviteRef.current = riskInvite;
    setInvite(riskInvite);
    prepareHumanTransport(riskInvite.invite_id);
  }, [prepareHumanTransport]);

  // AI 통화 중 위험 발화가 감지되면 보호자에게 역으로 벨을 보낸다. 보호자가
  // 받기 전까지 AI 대화는 멈추지 않고, 받았을 때만 사람 영상통화로 전환한다.
  useEffect(() => {
    if (phase !== "incall" || invite?.purpose !== "risk" || !invite.invite_id) return undefined;
    let alive = true;
    let timer = null;
    const inviteId = invite.invite_id;
    const tick = async () => {
      if (!alive) return;
      try {
        const current = await api.getInvite(inviteId);
        if (!alive) return;
        setInvite(current);
        inviteRef.current = current;
        if (current.state === "answered") {
          if (transportFailed.current) {
            await api.endInvite(inviteId).catch(() => {});
            await resumeRiskAi();
            return;
          }
          // 수락만으로 AI를 끊지 않는다. 양쪽 WebRTC가 실제 connected가
          // 될 때까지 현재 CallScreen과 TTS/STT를 그대로 유지한다.
          timer = setTimeout(tick, RING_POLL_MS);
          return;
        }
        if (current.should_take_over || ["declined", "timeout", "cancelled", "ended", "ai_takeover"].includes(current.state)) {
          await resumeRiskAi();
          return;
        }
      } catch {
        await resumeRiskAi();
        return;
      }
      if (alive) timer = setTimeout(tick, RING_POLL_MS);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [phase, invite?.invite_id, invite?.purpose, resumeRiskAi]);

  // 보호자가 가족 화면의 "지금 이어받기"를 누르면 같은 AI call_id에 연결된
  // handoff 초대가 생긴다. AI 화면은 이 초대를 찾는 동안 계속 말하고 듣는다.
  useEffect(() => {
    if (phase !== "incall" || !call?.call_id || invite?.purpose === "risk") {
      return undefined;
    }
    let alive = true;
    let timer = null;
    const tick = async () => {
      if (!alive) return;
      try {
        const { invite: handoff } = await api.getCallHandoff(call.call_id);
        if (!alive) return;
        if (handoff?.state === "answered") {
          const isNew = inviteRef.current?.invite_id !== handoff.invite_id;
          setInvite(handoff);
          inviteRef.current = handoff;
          if (isNew) prepareHumanTransport(handoff.invite_id);
        } else if (
          handoff
          && inviteRef.current?.invite_id === handoff.invite_id
          && ["ended", "cancelled", "declined", "timeout"].includes(handoff.state)
        ) {
          await resumeRiskAi();
        }
      } catch {
        // AI 통화 자체는 정상 경로다. 이어받기 조회 장애로 끊지 않는다.
      }
      if (alive) timer = setTimeout(tick, RING_POLL_MS);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [phase, call?.call_id, invite?.purpose, prepareHumanTransport, resumeRiskAi]);

  // 초대를 수락한 시점이 아니라 WebRTC가 실제 연결된 시점에만 AI 화면을
  // 내린다. CallScreen이 언마운트되면서 TTS·STT·Anam도 함께 정리된다.
  useEffect(() => {
    if (
      phase !== "incall"
      || !call?.call_id
      || !invite?.invite_id
      || !["risk", "handoff"].includes(invite.purpose)
      || invite.state !== "answered"
      || humanTransportState !== "connected"
    ) return;
    api.markHumanConnected(call.call_id, invite.invite_id).catch(() => {});
    phaseRef.current = "human";
    setPhase("human");
  }, [phase, call?.call_id, invite, humanTransportState]);

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
          if (!current.intro_complete) {
            timer = setTimeout(tick, RING_POLL_MS);
            return;
          }
          stopWaitingMelody();
          if (transportFailed.current) {
            fallBackFromHuman(inviteId);
          } else {
            phaseRef.current = "human";
            setPhase("human");
          }
          return;
        }

        if (current.state === "ai_takeover") {
          // 다른 폴링이나 사용자의 버튼이 먼저 전환을 끝낸 경우다.
          // 이미 열린 통화가 있으면 그대로 사용하고, 응답만 놓쳤다면 새 AI
          // 세션으로 조용히 복구해 중복 takeover 요청을 보내지 않는다.
          await releaseHumanTransport(false);
          if (!call) await connectAI(target?.persona_id);
          return;
        }

        if (current.should_take_over) {
          if (takeoverInFlight.current) {
            timer = setTimeout(tick, RING_POLL_MS);
            return;
          }
          takeoverInFlight.current = true;
          try {
            await releaseHumanTransport(false);
            const res = await api.takeOverInvite(inviteId);
            if (!alive) return;
            setError("");
            setInvite(res.invite);
            enterCall(res);
          } catch (reason) {
            if (!alive) return;
            // 서버 전환은 끝났지만 응답이 유실된 경쟁 상황도 통화 실패로
            // 보이지 않게 새 AI 세션으로 이어 준다.
            if (String(reason?.message || "").includes("ai_takeover")) {
              await connectAI(target?.persona_id);
            } else {
              throw reason;
            }
          } finally {
            takeoverInFlight.current = false;
          }
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
    phase, invite?.invite_id, call, target?.persona_id, connectAI, enterCall,
    fallBackFromHuman, releaseHumanTransport,
  ]);

  // 24초 인트로가 끝나 사람 화면을 연 뒤에도 미디어가 붙지 않을 때만
  // 조용히 AI로 넘긴다. 보호자가 받자마자 시작한 별도 타이머로 인트로 중
  // 연결을 끊으면 양쪽 화면이 서로 다른 상태가 된다.
  useEffect(() => {
    if (phase !== "human" || !invite?.invite_id || humanTransportState === "connected") {
      return undefined;
    }
    const id = setTimeout(
      () => invite.purpose === "risk"
        ? resumeRiskAi()
        : fallBackFromHuman(invite.invite_id), HUMAN_CONNECT_GRACE_MS,
    );
    return () => clearTimeout(id);
  }, [phase, invite?.invite_id, invite?.purpose, humanTransportState, fallBackFromHuman, resumeRiskAi]);

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
          if (["risk", "handoff"].includes(inviteRef.current?.purpose) && call?.call_id) {
            await api.endCall(call.call_id).catch(() => {});
          }
          setInvite(null);
          setTarget(null);
          setCall(null);
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
  }, [phase, invite?.invite_id, call?.call_id, releaseHumanTransport]);

  async function startCalling(picked) {
    const person = picked ?? target;
    startWaitingMelody(24000);
    if (!callMedia.ready) {
      try {
        const prepared = await callMedia.prepare();
        if (!prepared?.ready) throw new Error("microphone unavailable");
      } catch {
        stopWaitingMelody();
        setError("마이크 연결이 안 됐어요. 마이크 권한과 연결 상태를 확인해 주세요.");
        return;
      }
    }
    if (picked) setTarget(picked);
    setError("");
    setCall(null);
    setSummary(null);
    setInvite(null);
    callingIntroDoneRef.current = false;
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

  function reset() {
    setTarget(null);
    setError("");
    // 통화가 끝난 직후의 중복 상태 전환을 막는다.
    cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    // 호출 기록을 닫는다. 실패해도 화면은 대기로 돌아가야 한다.
    if (invite?.invite_id) api.endInvite(invite.invite_id).catch(() => {});
    releaseHumanTransport(false);
    setInvite(null);
    setCall(null);
    setSummary(null);
    callingIntroDoneRef.current = false;
    setPhase("idle");
  }

  function finishCallingIntro() {
    callingIntroDoneRef.current = true;
    stopWaitingMelody();
    if (!call) return;
    phaseRef.current = "incall";
    setPhase("incall");
  }

  /** 사람 통화를 끝낸다. 리포트가 없으므로 대기 화면으로 곧장 돌아간다. */
  async function endHumanCall() {
    if (invite?.invite_id) await api.endInvite(invite.invite_id).catch(() => {});
    if (["risk", "handoff"].includes(invite?.purpose) && call?.call_id) {
      await api.endCall(call.call_id).catch(() => {});
    }
    await releaseHumanTransport(false);
    cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
    setInvite(null);
    setTarget(null);
    setCall(null);
    setPhase("idle");
  }

  const wrap = (node, { gear = false, wide = false, roleSwitch = false, displayDock = true, embeddedControls = false, shell = "default" } = {}) => {
    const fontRole = "readable";
    return (
    <div className={`frame app-shell app-shell-${shell}${wide ? " guardian-frame" : ""}`}>
      <div className={`device app-device app-device-${shell} font-role-${fontRole}${wide ? " guardian-device" : ""}`}>
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
  };

  const chooseRole = (picked) => {
    setRole(picked);
    setBooted(true);
    writeLocal(KEY_ROLE, picked);
    setRoleOnboarded(null);
    // 역할 선택 뒤에는 데모용 직행 주소가 아니라 실제 앱의 연동·온보딩
    // 흐름을 탄다. 저장된 연동이 있으면 해당 역할의 홈으로 바로 이어진다.
    window.location.hash = "";
  };

  const finishRoleOnboarding = (result) => {
    const nextElderId = result?.elderId || result?.elder_id || "elder_001";
    setLinked(nextElderId);
    writeLocal(KEY_LINKED, nextElderId);
    if (result?.personaId) {
      setGuardianPersonaId(result.personaId);
      setMyPersonaId(result.personaId);
      writeLocal(KEY_MY_PERSONA, result.personaId);
      setGuardianOnboarded(true);
      writeLocal(KEY_GUARDIAN_ONBOARDING, "done");
    }
    setRoleOnboarded(true);
  };

  const acceptAccount = (user) => {
    setDemoMode(false);
    setAccount(user);
    setRole(null);
    setRoleOnboarded(null);
    setLinked(null);
    setGuardianOnboarded(false);
    setMyPersonaId(null);
    removeLocal(KEY_ROLE);
    removeLocal(KEY_LINKED);
    removeLocal(KEY_GUARDIAN_ONBOARDING);
    removeLocal(KEY_MY_PERSONA);
  };

  const skipLogin = () => {
    api.saveAuthToken("");
    setDemoMode(true);
    setAccount({ user_id: "demo", display_name: "체험 사용자" });
    setRole(null);
    setRoleOnboarded(null);
    setLinked("elder_001");
    setGuardianOnboarded(true);
    setMyPersonaId(null);
    removeLocal(KEY_ROLE);
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
  if (import.meta.env.DEV && hash === "#roles")
    return wrap(<RoleScreen onPick={chooseRole} />, { wide: true, shell: "roles" });

  // 주소로 직접 들어온 경우는 입구를 건너뛴다.
  // #elder는 이 브라우저에 저장된 보호자 역할과 무관하게 어르신 화면을 연다.
  const directElder = import.meta.env.DEV && hash === "#elder";
  if (import.meta.env.DEV && (hash === "#child" || hash === "#family")) {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true, roleSwitch: true, shell: "family" });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "family" });
  }

  if (!directElder && !booted)
    return wrap(<SplashScreen onDone={() => setBooted(true)} />);

  if (!directElder && !authChecked)
    return wrap(<div className="screen"><p className="hint">계정을 확인하는 중…</p></div>);

  if (!directElder && !account)
    return wrap(<LoginScreen onAuthenticated={acceptAccount} onSkip={skipLogin} />, { wide: true, shell: "login" });

  if (!directElder && !role)
    return wrap(<RoleScreen account={account} onPick={chooseRole} onLogout={async () => { if (!demoMode) await api.logoutAccount().catch(() => {}); api.saveAuthToken(""); setDemoMode(false); setAccount(null); setRole(null); removeLocal(KEY_ROLE); }} />, { wide: true, shell: "roles" });

  if (!directElder && roleOnboarded === null)
    return wrap(<div className="screen"><p className="hint">완료한 설정을 확인하는 중…</p></div>);

  if (!directElder && !roleOnboarded)
    return wrap(<RoleOnboardingScreen role={role} account={account} elderId={elderId} theme={theme} size={size} onTheme={setTheme} onSize={setSize} onDone={finishRoleOnboarding} onCancel={() => { setRole(null); setRoleOnboarded(null); removeLocal(KEY_ROLE); }} />, { wide: true, shell: `journey-${role}` });

  if (!directElder && !linked)
    return wrap(
      <LinkScreen
        role={role}
        onLinked={finishLink}
        onSkip={() => finishLink("skipped")}
      />,
      { wide: true, roleSwitch: true, shell: role === "child" ? "family" : "elder" }
    );

  if (!directElder && role === "child") {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true, shell: "family" });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} onDisplaySettings={() => setSettingsOpen(true)} />, { gear: true, wide: true, roleSwitch: true, displayDock: false, shell: "family" });
  }

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
      { gear: true, roleSwitch: true, embeddedControls: true, shell: "elder" }
    );

  if (phase === "connecting")
    return wrap(
      <CallingScreen
        name={profile?.persona?.display_name ?? "가족"}
        announcement={call?.announcement ?? "연결하고 있어요"}
      />,
      { shell: "elder" }
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
          anamReady={Boolean(call.anam_ready)}
          performanceStyle={profile?.persona?.avatar_performance_style ?? "calm"}
          onRiskDetected={handleRiskDetected}
          handoffPending={Boolean(
            invite?.purpose === "handoff"
            && invite?.state === "answered"
            && humanTransportState !== "connected"
          )}
          onEnded={(s) => {
            setSummary(s);
            setPhase("ended");
          }}
        />}

        {phase === "calling" && <CallingScreen
          name={profile?.persona?.display_name ?? "가족"}
          announcement={call?.announcement ?? "연결하고 있어요"}
          morphUrl={profile?.morph_url ?? null}
          introDurationSec={invite?.intro_duration_sec ?? 24}
          onWaitEnded={finishCallingIntro}
        />}
      </div>,
      { shell: "elder" }
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
      />,
      { shell: "elder" }
    );

  if (phase === "ended" && summary)
    return wrap(<SummaryScreen summary={summary} onRestart={reset} />, { shell: "elder" });

  return wrap(<div className="screen"><p className="hint">준비하는 중…</p></div>, { shell: "elder" });
}
