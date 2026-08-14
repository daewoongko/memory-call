import { useCallback, useEffect, useState } from "react";
import { preflightCallMedia } from "./callTransport.js";

const initial = { status: "checking", ready: false, audio: false, video: false, message: "통화 장치를 확인하고 있어요." };

const prepared = (result) => ({
  status: result.video ? "ready" : "audio-only",
  ready: true,
  audio: true,
  video: Boolean(result.video),
  message: result.video ? "마이크와 카메라가 준비됐어요." : "마이크가 준비됐어요. 영상 없이 음성으로 연결됩니다.",
});

const unavailable = (error) => ({
  status: "blocked", ready: false, audio: false, video: false,
  message: error?.name === "NotAllowedError" || error?.name === "SecurityError"
    ? "Chrome 설정에서 이 사이트의 마이크 권한을 허용해 주세요."
    : "마이크를 확인하지 못했어요. 기기 연결 상태를 확인해 주세요.",
});

export function useCallMediaReadiness(enabled = true) {
  const [state, setState] = useState(initial);
  const prepare = useCallback(async () => {
    setState((current) => ({ ...current, status: "checking", message: "통화 장치를 확인하고 있어요." }));
    try {
      const next = prepared(await preflightCallMedia());
      setState(next);
      return next;
    } catch (error) {
      const next = unavailable(error);
      setState(next);
      throw error;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState({ ...initial, status: "inactive", message: "" });
      return undefined;
    }
    let alive = true;
    const inspect = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        if (alive) setState(unavailable(new Error("unsupported")));
        return;
      }
      if (!navigator.permissions?.query) {
        if (alive) setState({ ...initial, status: "needs-action", message: "통화 전에 마이크와 카메라를 준비해 주세요." });
        return;
      }
      try {
        const microphone = await navigator.permissions.query({ name: "microphone" });
        if (!alive) return;
        if (microphone.state === "granted") {
          try {
            const next = prepared(await preflightCallMedia());
            if (alive) setState(next);
          } catch (error) {
            if (alive) setState(unavailable(error));
          }
        } else {
          setState({
            ...initial,
            status: microphone.state === "denied" ? "blocked" : "needs-action",
            message: microphone.state === "denied"
              ? "Chrome 설정에서 이 사이트의 마이크 권한을 허용해 주세요."
              : "통화 전에 마이크와 카메라를 준비해 주세요.",
          });
        }
      } catch {
        if (alive) setState({ ...initial, status: "needs-action", message: "통화 전에 마이크와 카메라를 준비해 주세요." });
      }
    };
    inspect();
    return () => { alive = false; };
  }, [enabled]);

  return { ...state, prepare };
}
