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
 * 화면이 가려지면 폴링을 멈춘다. 아이폰은 탭이 뒤로 가면 타이머를 강하게
 * 조이기 때문에, 멈췄다가 돌아올 때 즉시 한 번 물어보는 편이 정확하다.
 */

const POLL_MS = 1500;

export function useIncomingCall({ elderId = "elder_001", personaId, enabled = true }) {
  const [invite, setInvite] = useState(null);
  const [ready, setReady] = useState(false);
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

    const tick = async () => {
      if (!alive) return;
      try {
        const { invite: incoming } = await api.getIncomingInvite(deviceId());
        if (!alive) return;
        setInvite(
          incoming && !handled.current.has(incoming.invite_id) ? incoming : null
        );
        setError("");
      } catch (reason) {
        if (alive) setError(reason.message);
      } finally {
        if (alive) timer = setTimeout(tick, POLL_MS);
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

    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      clearTimeout(timer);
      tick();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
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

  const decline = useCallback(async (inviteId) => {
    const result = await api.declineInvite(inviteId, deviceId());
    forget(inviteId);
    return result;
  }, [forget]);

  return { invite, ready, error, answer, decline };
}
