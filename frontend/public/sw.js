const STATIC_CACHE = "dasoni-static-v3";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith("dasoni-static-") && key !== STATIC_CACHE)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || request.mode === "navigate") return;

  const staticAsset = url.pathname.startsWith("/assets/")
    || url.pathname.startsWith("/icons/")
    || url.pathname === "/manifest.webmanifest";
  if (!staticAsset) return;

  event.respondWith((async () => {
    try {
      const response = await fetch(request, { cache: "no-cache" });
      if (response.ok) {
        const cache = await caches.open(STATIC_CACHE);
        await cache.put(request, response.clone());
      }
      return response;
    } catch (error) {
      const cached = await caches.match(request);
      if (cached) return cached;
      throw error;
    }
  })());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data?.json?.() || {};
  } catch {
    payload = { body: event.data?.text?.() || "가족 확인이 필요한 소식이 있어요." };
  }
  const urgent = Boolean(payload.urgent);
  event.waitUntil(self.registration.showNotification(
    payload.title || (urgent ? "다소니 긴급 확인" : "다소니 알림"),
    {
      body: payload.body || "가족 확인이 필요한 소식이 있어요.",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: payload.tag || "dasoni-guardian-alert",
      renotify: urgent,
      requireInteraction: urgent,
      vibrate: urgent ? [300, 120, 300, 120, 500] : [180, 80, 180],
      data: {
        url: payload.url || "/#guardian",
        kind: payload.kind || "notice",
        inviteId: payload.invite_id || null,
      },
      actions: [{ action: "open", title: urgent ? "지금 확인" : "열기" }],
    },
  ));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/#guardian", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const current = windows.find((client) => new URL(client.url).origin === self.location.origin);
    if (current) {
      await current.navigate(url);
      current.postMessage({
        type: "dasoni-push-open",
        kind: event.notification.data?.kind,
        inviteId: event.notification.data?.inviteId,
      });
      return current.focus();
    }
    return self.clients.openWindow(url);
  })());
});
