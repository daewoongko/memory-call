import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const p = await b.newPage({ viewport: { width: 1010, height: 600 }, deviceScaleFactor: 1 });
await p.goto('file://' + process.cwd() + '/build/preview.html');
await p.waitForTimeout(900);
const slides = await p.locator('.slide').all();
for (let i = 0; i < slides.length; i++) {
  await slides[i].screenshot({ path: `shots/s${String(i + 1).padStart(2, '0')}.png` });
}
console.log('captured', slides.length);
await b.close();
