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

// 벨이 몇 초 울리는지는 서버가 정해서 내려보낸다. 받을 기기가 없으면 짧게
// 울려야 하는데, 그 판단에 필요한 정보가 화면에는 없기 때문이다.
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

// 가족 응답을 기다리는 시간 (명세 FR-01)
const ANNOUNCE_MS = 2600; // AI 통화 안내를 보여주는 시간 (명세 13.1)

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
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [incomingReason, setIncomingReason] = useState(null);
  // 지금 통화하려는 가족. 대기 화면에서 고른 값이 통화 끝까지 따라간다.
  const [target, setTarget] = useState(null);
  const cooldownUntil = useRef(0);
  const [error, setError] = useState("");
  const timers = useRef([]);

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
        .then((r) => alive && r.due && setIncomingReason(r.reason))
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
    timers.current.push(setTimeout(() => setPhase("incall"), ANNOUNCE_MS));
  }, []);

  const connectAI = useCallback(async () => {
    try {
      enterCall(await api.startCall(target?.persona_id, elderId));
    } catch (e) {
      setError(`통화를 열지 못했어요. (${e.message})`);
      setPhase("idle");
    }
  }, [target, elderId, enterCall]);

  /**
   * 벨이 울리는 동안 서버에 물어본다.
   *
   * 예전에는 여기가 setSecondsLeft(s => s - 1) 하나였다. 화면 안에서만 도는
   * 숫자였으므로 보호자가 무엇을 하든 15초 뒤에는 똑같이 AI 로 넘어갔다.
   * 이제 받았는지 여부는 서버가 판정하고 화면은 그 결과를 따라간다.
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
        setSecondsLeft(Math.max(0, Math.ceil(current.seconds_left ?? 0)));

        if (current.state === "answered") {
          setInvite(current);
          setPhase("human");
          return;
        }
        if (current.should_take_over) {
          const res = await api.takeOverInvite(inviteId);
          if (!alive) return;
          setInvite(res.invite);
          enterCall(res);
          return;
        }
        if (current.state === "cancelled" || current.state === "ended") {
          setPhase("idle");
          setInvite(null);
          return;
        }
      } catch (e) {
        if (!alive) return;
        // 벨이 울리는 중의 통신 오류로 어르신을 대기 화면에 가둘 수는 없다.
        // 이 서비스에서 잘못될 수 있는 방향 중 AI 가 받는 쪽이 정상이다.
        setError(`연결이 고르지 않아 AI 가 받을게요. (${e.message})`);
        connectAI();
        return;
      }
      if (alive) timer = setTimeout(tick, RING_POLL_MS);
    };

    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [phase, invite?.invite_id, connectAI, enterCall]);

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
  }, [phase, invite?.invite_id]);

  async function startCalling(picked) {
    const person = picked ?? target;
    if (picked) setTarget(picked);
    setError("");
    setCall(null);
    setSummary(null);
    setInvite(null);
    setSecondsLeft(0);
    setPhase("calling");

    try {
      const created = await api.ringFamily({
        elder_id: elderId,
        persona_id: person?.persona_id,
        from_device: deviceId(),
      });
      setInvite(created);
      setSecondsLeft(Math.ceil(created.seconds_left ?? created.ring_timeout_sec));
    } catch (e) {
      // 호출을 만들지 못해도 통화는 이어져야 한다. 어르신에게는 전화가
      // 실패한 것이 아니라 가족이 받지 않은 것과 같아야 한다.
      setError(`가족을 부르지 못해 AI 가 받을게요. (${e.message})`);
      connectAI();
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
    setInvite(null);
    setCall(null);
    setSummary(null);
    setPhase("idle");
  }

  /** 어르신이 벨이 울리는 중에 그만둔다. AI 로 넘기지 않는다. */
  function stopCalling() {
    if (invite?.invite_id) api.cancelInvite(invite.invite_id).catch(() => {});
    setInvite(null);
    setPhase("idle");
  }

  /** 사람 통화를 끝낸다. 리포트가 없으므로 대기 화면으로 곧장 돌아간다. */
  function endHumanCall() {
    if (invite?.invite_id) api.endInvite(invite.invite_id).catch(() => {});
    cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
    setInvite(null);
    setTarget(null);
    setPhase("idle");
  }

  const wrap = (node, { gear = false, wide = false, roleSwitch = false } = {}) => (
    <div className={`frame${wide ? " guardian-frame" : ""}`}>
      <div className={`device${wide ? " guardian-device" : ""}`}>
        {wide && (roleSwitch || gear) && <WideDisplayDock
          theme={theme}
          size={size}
          onTheme={setTheme}
          onSize={setSize}
          onRole={() => { setRole(null); window.location.hash = ""; }}
        />}
        {!wide && roleSwitch && (
          <button
            className="role-switch"
            onClick={() => { setRole(null); window.location.hash = ""; }}
            aria-label="역할 선택 화면으로 돌아가기"
          >
            역할 선택
          </button>
        )}
        {!wide && gear && (
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
          />
        )}
      </div>
    </div>
  );

  const chooseRole = (picked) => {
    setRole(picked);
    writeLocal(KEY_ROLE, picked);
    window.location.hash = picked === "child" ? "#family" : `#${picked}`;
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

  // 루트에서는 저장된 역할과 관계없이 항상 역할을 먼저 고른다.
  if (!hash || hash === "#roles")
    return wrap(<RoleScreen onPick={chooseRole} />, { wide: true });

  // 주소로 직접 들어온 경우는 입구를 건너뛴다.
  // #elder는 이 브라우저에 저장된 보호자 역할과 무관하게 어르신 화면을 연다.
  const directElder = hash === "#elder";
  if (hash === "#care" || hash === "#guardian")
    return wrap(<CareManagerScreen />, { gear: true, wide: true, roleSwitch: true });
  if (hash === "#child" || hash === "#family") {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true, roleSwitch: true });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} />, { gear: true, wide: true, roleSwitch: true });
  }

  if (!directElder && !booted)
    return wrap(<SplashScreen onDone={() => setBooted(true)} />);

  if (!directElder && !role) return wrap(<RoleScreen onPick={chooseRole} />);

  if (!directElder && !linked)
    return wrap(
      <LinkScreen
        role={role}
        onLinked={finishLink}
        onSkip={() => finishLink("skipped")}
      />
    );

  if (!directElder && role === "care") {
    return wrap(<CareManagerScreen />, { gear: true, wide: true });
  }

  if (!directElder && role === "child") {
    if (!guardianOnboarded) return wrap(<GuardianOnboardingScreen elderId={elderId} onDone={finishGuardianOnboarding} />, { wide: true });
    return wrap(<ChildScreen elderId={elderId} myPersonaId={myPersonaId} onMyPersonaChange={saveMyPersona} />, { gear: true, wide: true });
  }


  if (phase === "idle" && incomingReason)
    return wrap(
      <IncomingScreen
        profile={profile}
        reason={incomingReason}
        onAnswer={answerIncoming}
        onDecline={() => {
          cooldownUntil.current = Date.now() + RING_COOLDOWN_MS;
          setIncomingReason(null);
        }}
      />
    );

  if (phase === "idle")
    return wrap(
      <FamilyScreen elderId={elderId} onPick={startCalling} error={error} />,
      { gear: true, roleSwitch: true }
    );

  if (phase === "connecting")
    return wrap(
      <CallingScreen
        name={profile?.persona?.display_name ?? "가족"}
        secondsLeft={0}
        announcement={call?.announcement ?? "연결하고 있어요"}
        onSkip={() => {}}
      />
    );

  if (phase === "calling")
    return wrap(
      <CallingScreen
        name={profile?.persona?.display_name ?? "가족"}
        waitMs={profile?.elder?.speech_wait_time_ms ?? 2000}
        secondsLeft={secondsLeft}
        announcement={call?.announcement ?? "연결하고 있어요"}
        onSkip={() => {
          if (invite?.invite_id) {
            api.takeOverInvite(invite.invite_id, "transport_failed")
              .then((res) => { setInvite(res.invite); enterCall(res); })
              .catch((e) => setError(`연결하지 못했어요. (${e.message})`));
          } else {
            connectAI();
          }
        }}
        onStop={stopCalling}
      />
    );

  if (phase === "human" && invite)
    return wrap(
      <HumanCallScreen
        name={profile?.persona?.display_name ?? "가족"}
        face={profile?.faces?.at(-1)?.url}
        answeredAt={invite.answered_at}
        onEnd={endHumanCall}
      />
    );

  if (phase === "incall" && call)
    return wrap(
      <CallScreen
        faces={call.faces?.length ? call.faces : profile?.faces ?? []}
        morphUrl={call.morph_url ?? profile?.morph_url ?? null}
        loops={call.loops ?? profile?.loops ?? {}}
        opening={call.opening ?? ""}
        name={profile?.persona?.display_name ?? "가족"}
        waitMs={profile?.elder?.speech_wait_time_ms ?? 2000}
        callId={call.call_id}
        api={api}
        onEnded={(s) => {
          setSummary(s);
          setPhase("ended");
        }}
      />
    );

  if (phase === "ended" && summary)
    return wrap(<SummaryScreen summary={summary} onRestart={reset} />);

  return wrap(<div className="screen"><p className="hint">준비하는 중…</p></div>);
}
