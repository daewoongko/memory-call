import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api.js";
import { deviceId, deviceLabel } from "./device.js";

/**
 * 보호자 기기의 수신 대기.
 *
 * 별도 heartbeat 를 두지 않는다. 폴링하고 있다는 사실 자체가 화면을 열어
 * 두었다는 증거이므로, 서버가 그 시각으로 "받을 기기가 있는가"를 판정한다.
 * 경로를 둘로 나누면 두 값이 어긋나고, 어긋나면 벨이 잘못 배달된다.
 *
 * **화면이 가려지면 반드시 폴링을 멈춘다.** 이 폴링이 곧 "지금 전화를 받을
 * 수 있다"는 신고이기 때문이다. 잠긴 폰이 계속 신고하면 서버는 받을 사람이
 * 있다고 믿고 벨을 끝까지 울리고, 어르신은 아무도 받지 않을 전화를 오래
 * 들여다보게 된다. 멈추면 몇 초 만에 신고가 낡아 서버가 AI 로 넘긴다.
 */

const POLL_MS = 1500;

export function useIncomingCall({ elderId = "elder_001", personaId, enabled = true }) {
  const [invite, setInvite] = useState(null);
  const [ready, setReady] = useState(false);
  // 지금 실제로 벨을 받을 수 있는가. 등록되었다는 것과는 다르다.
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  // 받기·거절을 누른 직후 폴링이 같은 벨을 다시 물고 오지 않도록 기억해 둔다.
  const handled = useRef(new Set());

  const active = Boolean(enabled && personaId);

  useEffect(() => {
    if (!active) {
      setReady(false);
      return undefined;
    }

    // 이 실행에만 속한 플래그다. StrictMode 의 두 번째 마운트는 자기 것을
    // 새로 만들어 쓰므로 첫 번째 정리에 걸려 죽지 않는다.
    let alive = true;
    let timer = null;

    const visible = () =>
      typeof document === "undefined" || document.visibilityState === "visible";

    const tick = async () => {
      if (!alive) return;
      // 가려져 있으면 물어보지 않고 다음 차례도 잡지 않는다. 다시 보일 때
      // visibilitychange 가 체인을 새로 시작한다.
      if (!visible()) {
        setListening(false);
        return;
      }
      try {
        const { invite: incoming } = await api.getIncomingInvite(deviceId());
        if (!alive) return;
        setInvite(
          incoming && !handled.current.has(incoming.invite_id) ? incoming : null
        );
        setListening(true);
        setError("");
      } catch (reason) {
        if (!alive) return;
        setListening(false);
        setError(reason.message);
      } finally {
        if (alive && visible()) timer = setTimeout(tick, POLL_MS);
      }
    };

    api
      .registerDevice({
        device_id: deviceId(),
        elder_id: elderId,
        role: "guardian",
        persona_id: personaId,
        label: deviceLabel(),
      })
      .then(() => {
        if (!alive) return;
        setReady(true);
        tick();
      })
      .catch((reason) => alive && setError(reason.message));

    const onVisibility = () => {
      if (!alive) return;
      clearTimeout(timer);
      if (visible()) tick();
      else setListening(false);
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      alive = false;
      clearTimeout(timer);
      setListening(false);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active, elderId, personaId]);

  const forget = useCallback((inviteId) => {
    handled.current.add(inviteId);
    setInvite(null);
  }, []);

  const answer = useCallback(async (inviteId) => {
    const result = await api.answerInvite(inviteId, deviceId());
    forget(inviteId);
    return result;
  }, [forget]);

  const decline = useCallback(async (inviteId, reason) => {
    const result = await api.declineInvite(inviteId, deviceId(), reason);
    forget(inviteId);
    return result;
  }, [forget]);

  return { invite, ready, listening, error, answer, decline };
}
