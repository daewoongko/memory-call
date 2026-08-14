/**
 * P2P 진단 화면(#nettest)이 실제로 도는지.
 *
 * 이 저장소의 교훈 하나 — `vite build` 는 실행 시점 오류를 못 잡는다. 폰을
 * 들고 나가기 전에 화면이 열리는지, 두 기기가 실제로 붙는지를 여기서 본다.
 *
 * 여기서 재는 값 자체는 형의 망에 대한 답이 아니다. 브라우저 두 개가 같은
 * 기계에 있으므로 host 후보로 곧장 붙고, 이 컨테이너는 UDP 가 막혀 STUN 에
 * 닿지 못한다. 확인하려는 것은 **도구가 동작하는가** 다.
 *
 *     node e2e/nettest.mjs http://127.0.0.1:8021
 */

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.log("playwright 가 없어 건너뜁니다.");
  process.exit(0);
}

const BASE = (process.argv[2] || "http://127.0.0.1:8021").replace(/\/$/, "");
const problems = [];
const log = (m) => console.log(m);
const check = (ok, message) => {
  log(`    [${ok ? "통과" : "실패"}] ${message}`);
  if (!ok) problems.push(message);
  return ok;
};

function watch(page, who) {
  page.on("pageerror", (e) => problems.push(`[${who}] 실행 오류: ${e.message}`));
  page.on("console", (m) => {
    const noise = /favicon|404|ERR_TUNNEL|cdn\.jsdelivr|STUN|stun/i;
    if (m.type() === "error" && !noise.test(m.text()))
      problems.push(`[${who}] 콘솔 오류: ${m.text()}`);
  });
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const phone = () => browser.newContext({ viewport: { width: 412, height: 915 } });
const a = await (await phone()).newPage();
const b = await (await phone()).newPage();
watch(a, "폰A");
watch(b, "폰B");

try {
  log("\n화면이 열리는가");
  await Promise.all([
    a.goto(`${BASE}/#nettest`, { waitUntil: "domcontentloaded" }),
    b.goto(`${BASE}/#nettest`, { waitUntil: "domcontentloaded" }),
  ]);
  await a.locator(".nettest").waitFor({ timeout: 15000 });
  await b.locator(".nettest").waitFor({ timeout: 15000 });
  check(true, "#nettest 화면이 그려진다");

  // 1층: 혼자서 하는 진단이 끝나는가 (STUN 이 막혀도 결론은 나야 한다)
  log("\n이 기기 진단이 끝나는가");
  await a.locator(".nettest-card", { hasText: "1. 이 기기" })
    .locator(".nettest-row").first().waitFor({ timeout: 20000 });
  const rows = await a.locator(".nettest-card").first()
    .locator(".nettest-row").allTextContents();
  check(rows.length >= 3, `진단 항목이 채워진다 (${rows.length}개)`);
  log(`    ${rows.map((r) => r.replace(/\s+/g, " ")).join(" | ")}`);

  // 2층: 두 기기가 실제로 붙는가
  log("\n두 기기를 붙인다");
  await a.locator("button", { hasText: "방 만들기" }).click();
  const room = await a.locator(".nettest-room b").textContent({ timeout: 15000 });
  check(/^\d{6}$/.test(room.trim()), `방 번호가 나온다 (${room.trim()})`);

  await b.locator('input[aria-label="방 번호"]').fill(room.trim());
  await b.locator("button", { hasText: "들어가기" }).click();

  const verdictA = a.locator(".nettest-verdict");
  await verdictA.waitFor({ timeout: 40000 });
  const headline = (await verdictA.locator("b").first().textContent()).trim();
  const level = await verdictA.getAttribute("class");
  check(level.includes("ok"), `연결 판정: ${headline}`);
  log(`    ${(await verdictA.textContent()).replace(/\s+/g, " ").slice(0, 160)}`);

  // 결과가 서버에 남는가
  log("\n결과를 남긴다");
  await a.locator('input[aria-label="측정 환경"]').fill("자동 시험 (같은 기계)");
  await a.locator("button", { hasText: "결과 저장" }).click();
  await a.locator("button", { hasText: "저장됨" }).waitFor({ timeout: 10000 });

  const saved = await a.evaluate(async (base) => {
    const res = await fetch(`${base}/api/nettest/results?limit=5`);
    return res.json();
  }, BASE);
  check(saved.results?.length > 0 && saved.results[0].connected === 1,
        `측정 기록이 남는다 (${saved.results?.length}건)`);

  await a.screenshot({ path: "e2e/shot-nettest.png", fullPage: true });
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
console.log("진단 화면 동작 확인");
