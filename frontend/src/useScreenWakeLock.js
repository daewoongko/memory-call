import { useEffect, useRef } from "react";

export function useScreenWakeLock(enabled) {
  const lockRef = useRef(null);
  useEffect(() => {
    if (!enabled || !navigator.wakeLock?.request) return undefined;
    let active = true;
    const acquire = async () => {
      if (!active || document.visibilityState !== "visible" || lockRef.current) return;
      try {
        const lock = await navigator.wakeLock.request("screen");
        if (!active) return lock.release().catch(() => {});
        lockRef.current = lock;
        lock.addEventListener("release", () => {
          if (lockRef.current === lock) lockRef.current = null;
        });
      } catch {
        // 지원하지 않는 기기에서도 통화 기능은 유지한다.
      }
    };
    const onVisibility = () => document.visibilityState === "visible" && acquire();
    document.addEventListener("visibilitychange", onVisibility);
    acquire();
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisibility);
      const lock = lockRef.current;
      lockRef.current = null;
      lock?.release().catch(() => {});
    };
  }, [enabled]);
}
