import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("manifest는 다소니를 세로형 standalone 앱으로 설치한다", async () => {
  const manifest = JSON.parse(await read("../public/manifest.webmanifest"));
  assert.equal(manifest.name, "다소니");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.orientation, "portrait");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.theme_color, "#faf7f2");
  assert.ok(manifest.icons.some((icon) => icon.src === "/icons/dasoni-app-192.png"));
  assert.ok(manifest.icons.some((icon) => icon.sizes === "512x512" && icon.purpose === "maskable"));
});

test("service worker는 API와 화면 이동을 캐시하지 않는다", async () => {
  const source = await read("../public/sw.js");
  assert.match(source, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(source, /request\.mode === "navigate"/);
  assert.match(source, /fetch\(request, \{ cache: "no-cache" \}\)/);
  assert.doesNotMatch(source, /caches\.match\(request\)[\s\S]*fetch\(request/);
});

test("service worker는 잠금 화면 위험 알림과 앱 복귀를 처리한다", async () => {
  const source = await read("../public/sw.js");
  assert.match(source, /addEventListener\("push"/);
  assert.match(source, /showNotification/);
  assert.match(source, /urgent \? \[300, 120, 300/);
  assert.match(source, /addEventListener\("notificationclick"/);
  assert.match(source, /clients\.openWindow\(url\)/);
  assert.match(source, /"\/#guardian"/);
});

test("설치 문서는 manifest와 iOS 아이콘을 함께 선언한다", async () => {
  const html = await read("../index.html");
  assert.match(html, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.match(html, /rel="apple-touch-icon"/);
  assert.match(html, /dasoni-apple-touch-icon\.png/);
  assert.match(html, /apple-mobile-web-app-capable/);
});
