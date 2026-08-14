/**
 * 폰 두 대 흐름 확인.
 *
 * `vite build` 는 실행 시점 오류를 못 잡는다. 정의 전에 쓴 const 함수 같은
 * 문제는 빌드를 통과하고 브라우저에서 터진다. 그래서 실제 브라우저 두 개로
 * 어르신과 보호자를 동시에 띄워 호출이 오가는지 본다.
 *
 * 확인하는 것은 하나다. **보호자가 받았을 때와 받지 않았을 때가 갈리는가.**
 *
 *     python tools/serve.py --no-reload --port 8021   # 터미널 1
 *     cd frontend && npm run build
 *     node e2e/two_devices.mjs http://127.0.0.1:8021  # 터미널 2
 *
 * playwright 는 이 저장소의 의존성이 아니다. 없으면 안내만 하고 건너뛴다.
 *   npm i -D playwright && npx playwright install chromium
 */

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.log("playwright 가 없어 건너뜁니다.");
  console.log("  npm i -D playwright && npx playwright install chromium");
  process.exit(0);
}

const BASE = (process.argv[2] || "http://127.0.0.1:8021").replace(/\/$/, "");
// 가족 온보딩의 현재 기본 프로필과 같은 사람에게 전화를 건다.
// 데모 가족의 기본값이 바뀌었는데 테스트만 예전 민준을 고정하면,
// 정상적으로 등록된 가족 폰을 두고도 "받을 기기 없음"으로 오판한다.
const PERSONA = "persona_jeonghun";
const PERSONA_NAME = "정훈";

const problems = [];
const log = (m) => console.log(m);
const check = (condition, message) => {
  log(`    [${condition ? "통과" : "실패"}] ${message}`);
  if (!condition) problems.push(message);
  return condition;
};

function watch(page, who) {
  page.on("pageerror", (e) => problems.push(`[${who}] 실행 오류: ${e.message}`));
  page.on("console", (m) => {
    // 폰트 CDN 차단과 음성 합성 키 부재는 이 환경의 사정이지 앱의 문제가
    // 아니다. 호출이 오가는지를 보는 시험이라 음성 없이도 결론이 선다.
    const noise =
      /favicon|404|ERR_TUNNEL_CONNECTION_FAILED|cdn\.jsdelivr|TTS 503|음성을 재생하지 못했습니다|503 \(Service Unavailable\)/i;
    if (m.type() === "error" && !noise.test(m.text()))
      problems.push(`[${who}] 콘솔 오류: ${m.text()}`);
  });
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});

// 폰 두 대 = 컨텍스트 두 개. localStorage 가 갈려야 device_id 도 갈린다.
const phone = () => browser.newContext({ viewport: { width: 412, height: 915 } });
const elder = await (await phone()).newPage();
const guardian = await (await phone()).newPage();
watch(elder, "어르신");
watch(guardian, "보호자");

const ring = () => elder.locator("button.family-card", { hasText: PERSONA_NAME }).first();
const overlay = guardian.locator(".guardian-call-scrim");

/**
 * 어르신 화면이 대기 상태로 가라앉을 때까지 기다린다.
 *
 * 첫 렌더에서는 가족 화면이 보이다가 pending-call 응답이 오면 복약 안내
 * 전화가 그 위를 덮는다. 그 사이를 붙잡으면 눌렀던 버튼이 사라진다.
 * 복약 전화는 미뤄 둔다 — 여기서 보려는 것은 어르신이 거는 쪽이다.
 */
async function elderIdle() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await elder.waitForTimeout(700);
    const later = elder.locator(".incoming button.danger");
    if (await later.count()) {
      if (attempt === 0) log("    복약 안내 전화가 와 있어 미뤄둡니다");
      await later.click({ timeout: 5000 }).catch(() => {});
      continue;
    }
    if (await ring().count()) return true;
  }
  problems.push("어르신 대기 화면이 안정되지 않음");
  return false;
}

try {
  // ── 보호자 폰 ────────────────────────────────────────────
  log("\n보호자 폰 — 전화를 받을 준비");
  await guardian.goto(`${BASE}/#child`, { waitUntil: "domcontentloaded" });
  // React 가 그려지기 전에 물어보면 아무것도 없다고 나온다.
  await guardian.waitForSelector(".guardian-onboarding, .child-screen", { timeout: 20000 });

  if (await guardian.locator(".guardian-onboarding").count()) {
    // 페르소나가 자동 선택되고 이름이 채워져야 버튼이 열린다.
    await guardian.locator("button.onboarding-default-start:not([disabled])")
      .waitFor({ timeout: 20000 });

    // 떠 있는 설정 독이 이 버튼을 덮은 적이 두 번 있다. 버튼은 멀쩡히 보이고
    // disabled 도 아니어서 "눌러도 아무 일이 없다"로만 나타난다. 클릭이
    // 우연히 통과할 수도 있으므로 히트 타겟을 직접 찍어 둔다.
    const hit = await guardian.evaluate(() => {
      const el = document.querySelector("button.onboarding-default-start");
      const box = el.getBoundingClientRect();
      const top = document.elementFromPoint(
        box.x + box.width / 2, box.y + box.height / 2);
      return { own: top === el, covered: String(top?.className ?? "").slice(0, 40) };
    });
    check(hit.own, `시작 버튼을 무엇도 덮지 않는다${hit.own ? "" : ` (${hit.covered} 가 덮음)`}`);

    await guardian.locator("button.onboarding-default-start").click();
  }
  await guardian.locator(".child-screen").waitFor({ timeout: 20000 });

  if (await guardian.locator(".child-identity-setup button").count()) {
    await guardian.locator(".child-identity-setup button", { hasText: PERSONA_NAME })
      .first().click();
  }
  await guardian.waitForTimeout(2500); // 기기 등록 + 폴링 한 바퀴

  const mine = await guardian.evaluate(() => localStorage.getItem("dasoni.guardianPersona"));
  check(mine === PERSONA, `이 폰의 주인이 ${PERSONA_NAME} 으로 등록된다 (${mine})`);

  // ── 1. 가족이 받는다 ─────────────────────────────────────
  log("\n1. 가족이 받는다");
  await elder.goto(`${BASE}/#elder`, { waitUntil: "domcontentloaded" });
  await elderIdle();
  await ring().click();

  const countdown = await elder.locator(".countdown").textContent();
  check(/^1[0-9]초$/.test(countdown.trim()),
        `받을 기기가 있으므로 길게 기다린다 (${countdown.trim()})`);

  await overlay.waitFor({ state: "visible", timeout: 12000 });
  check(true, "보호자 폰에 벨이 도착한다");

  await guardian.locator(".guardian-call-answer").click({ timeout: 10000 });
  await elder.locator(".human-call").waitFor({ timeout: 12000 });
  check(true, "어르신 화면이 사람 통화로 바뀐다");
  check(Boolean(await guardian.locator(".guardian-call-timer").count()),
        "보호자 화면이 통화 중으로 바뀐다");

  // ── 2. 어르신이 끊으면 보호자도 풀린다 ──────────────────
  log("\n2. 어르신이 끊는다");
  await elder.locator(".human-call .round.danger").click();
  await overlay.waitFor({ state: "detached", timeout: 12000 })
    .catch(() => {});
  check(!(await guardian.locator(".guardian-call-timer").count()),
        "보호자 화면이 통화 중에 갇히지 않는다");

  // ── 3. 거절하면 AI 가 대신 받는다 ───────────────────────
  log("\n3. 가족이 거절한다");
  await elderIdle();
  await ring().click();
  await overlay.waitFor({ state: "visible", timeout: 12000 });
  await guardian.locator(".guardian-call-decline").click({ timeout: 10000 });

  await elder.locator(".human-call").waitFor({ state: "detached", timeout: 3000 })
    .catch(() => {});
  await elder.waitForTimeout(6000);
  const afterDecline = (await elder.evaluate(() => document.body.innerText))
    .replace(/\s+/g, " ");
  check(!/초$/.test(afterDecline.trim()) && !afterDecline.includes("에게 거는 중"),
        "거절하면 벨이 끝나기를 기다리지 않는다");
  log(`    화면: ${afterDecline.slice(0, 90)}`);

  await elder.screenshot({ path: "e2e/shot-elder-after-decline.png" });
  await guardian.screenshot({ path: "e2e/shot-guardian.png" });

  // ── 4. 보호자 폰 화면이 꺼지면 짧게 운다 ────────────────
  //
  // 폴링이 곧 "지금 받을 수 있다"는 신고다. 화면이 꺼졌는데도 신고가 계속
  // 나가면 서버는 받을 사람이 있다고 믿고 벨을 끝까지 울리고, 어르신은
  // 아무도 받지 않을 전화를 15초 동안 들여다보게 된다. 실제로 그랬다.
  //
  // 브라우저를 잠글 수는 없으니 앱이 읽는 값을 그대로 가려서 흉내낸다.
  log("\n4. 보호자 폰 화면이 꺼진다");
  const setVisibility = (page, value) => page.evaluate((state) => {
    Object.defineProperty(document, "visibilityState", {
      get: () => state, configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, value);

  await setVisibility(guardian, "hidden");

  const idleFor = 14000; // DEVICE_ALIVE_SEC 를 확실히 넘긴다
  log(`    ${idleFor / 1000}초 기다렸다가 다시 겁니다`);
  await elder.waitForTimeout(idleFor);

  const askDevices = () => elder.evaluate(async (base) => {
    const res = await fetch(`${base}/api/devices?elder_id=elder_001`);
    return res.json();
  }, BASE);

  const asleep = await askDevices();
  check(asleep.listening === 0,
        `서버가 받을 기기 없음을 안다 (듣고 있는 기기 ${asleep.listening}대)`);

  // 3번에서 AI 가 대신 받아 통화 중이다. 대기 화면으로 돌려놓는다.
  await elder.reload({ waitUntil: "domcontentloaded" });
  await elderIdle();
  await ring().click();
  const shortRing = (await elder.locator(".countdown").textContent()).trim();
  check(shortRing === "6초", `받을 폰이 없으므로 짧게 운다 (${shortRing})`);
  await elder.locator(".dev button").click().catch(() => {});

  // ── 5. 다시 켜면 돌아온다 ───────────────────────────────
  log("\n5. 보호자가 폰을 다시 켠다");
  await setVisibility(guardian, "visible");
  await guardian.waitForTimeout(3000);
  const awake = await askDevices();
  check(awake.listening === 1,
        `폴링이 되살아나 다시 받을 수 있다 (듣고 있는 기기 ${awake.listening}대)`);
} catch (reason) {
  problems.push(`흐름이 끊겼습니다: ${reason.message.split("\n")[0]}`);
} finally {
  await browser.close();
}

console.log("\n" + "─".repeat(52));
if (problems.length) {
  console.log("문제:");
  for (const p of problems) console.log("  · " + p);
  process.exit(1);
}
console.log("두 기기 흐름 통과");
