function applicationServerKey(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

export function pushCapability() {
  const supported = Boolean(
    globalThis.isSecureContext
    && "Notification" in globalThis
    && "serviceWorker" in navigator
    && "PushManager" in globalThis,
  );
  return {
    supported,
    permission: supported ? Notification.permission : "unsupported",
  };
}

export async function currentPushState() {
  const capability = pushCapability();
  if (!capability.supported) return { ...capability, subscribed: false };
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return { ...capability, subscribed: false };
  const subscription = await registration.pushManager.getSubscription();
  return { ...capability, subscribed: Boolean(subscription) };
}

export async function enableGuardianPush(publicKey) {
  const capability = pushCapability();
  if (!capability.supported) throw new Error("이 브라우저는 잠금 화면 알림을 지원하지 않습니다.");
  if (!publicKey) throw new Error("서버의 알림 키가 아직 설정되지 않았습니다.");
  const permission = Notification.permission === "granted"
    ? "granted"
    : await Notification.requestPermission();
  if (permission !== "granted") throw new Error("휴대폰 알림 권한을 허용해 주세요.");

  await navigator.serviceWorker.getRegistration()
    || await navigator.serviceWorker.register("/sw.js");
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  const subscription = existing || await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey(publicKey),
  });
  const serialized = subscription.toJSON();
  if (!serialized.endpoint || !serialized.keys?.p256dh || !serialized.keys?.auth) {
    throw new Error("브라우저 알림 구독 정보를 만들지 못했습니다.");
  }
  return {
    endpoint: serialized.endpoint,
    p256dh: serialized.keys.p256dh,
    auth: serialized.keys.auth,
  };
}

export async function disableGuardianPush() {
  const capability = pushCapability();
  if (!capability.supported) return false;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  return subscription ? subscription.unsubscribe() : true;
}
