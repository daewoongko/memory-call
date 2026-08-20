/* 배너와 낱장 카드를 PNG 로 굽는다.
   node docs/banner/render.mjs           → out/ 에 5장
   playwright 는 전역 설치본을 쓴다 (NODE_PATH 없이 돌리려고 절대 경로). */
import pw from "/opt/node22/lib/node_modules/playwright/index.js";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "out");
await mkdir(out, { recursive: true });

const cards = [
  ["card-01.html", "dasoni-01-role"],
  ["card-02.html", "dasoni-02-call-home"],
  ["card-03.html", "dasoni-03-today"],
  ["card-04.html", "dasoni-04-report"],
];

const b = await pw.chromium.launch();

// 낱장 카드 — 1080×1350 (4:5)
for (const [file, name] of cards) {
  const p = await b.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 2 });
  await p.goto("file://" + resolve(here, file));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(2000);          // 웹폰트가 늦게 오면 시스템 폰트로 굳는다
  await p.screenshot({ path: `${out}/${name}.png`, clip: { x: 0, y: 0, width: 1080, height: 1350 } });
  await p.close();
  console.log(name);
}

// 배너 — 폭 1512, 높이는 내용에 맞춘다
{
  const p = await b.newPage({ viewport: { width: 1512, height: 1000 }, deviceScaleFactor: 2 });
  await p.goto("file://" + resolve(here, "index.html"));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(2000);
  const h = await p.evaluate(() => Math.round(document.querySelector(".field").getBoundingClientRect().height));
  await p.setViewportSize({ width: 1512, height: h });
  await p.waitForTimeout(400);
  await p.screenshot({ path: `${out}/dasoni-banner.png` });
  await p.close();
  console.log("dasoni-banner", h);
}

await b.close();
