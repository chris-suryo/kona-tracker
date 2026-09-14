// Does any page scroll sideways on a phone?
//
// "The text isn't aligning right" turned out, in one case, to be literal: the
// Activity header ran to 410 CSS px on a 390 px screen and the battery was
// clipped off the edge. Nothing in the test suite could see that -- pytest
// renders HTML but never lays it out, and the Node harness stubs the DOM --
// so it took a real browser and a measurement.
//
// Not a CI gate, for the same reason browser_runtime.test.cjs is not: CI has
// no browser. Run it next to scripts/audit_shots.js.
//
//   uv run python scripts/audit_server.py &
//   NODE_PATH=/opt/node22/lib/node_modules node scripts/check_overflow.js
//
// Exits non-zero when any page at any width overflows, so it can be chained.
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8140';
// 320 is the iPhone SE; 390 is the 14/15; 430 is the Pro Max. If it survives
// 320 it survives everything these two people own.
const WIDTHS = [320, 375, 390, 430];
const PAGES = ['/activity', '/rest', '/steps', '/map', '/settings', '/camera', '/robot'];

(async () => {
  const browser = await chromium.launch();
  let failures = 0;
  for (const width of WIDTHS) {
    const context = await browser.newContext({ viewport: { width, height: 844 }, deviceScaleFactor: 2 });
    const page = await context.newPage();
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.fill('#passcode', '4242');
    await page.click('button[type=submit]');
    await page.waitForLoadState('domcontentloaded');
    for (const path of PAGES) {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(900);
      const seen = await page.evaluate(() => {
        const doc = document.documentElement;
        const over = [];
        document.querySelectorAll('*').forEach(el => {
          const box = el.getBoundingClientRect();
          if (box.right > doc.clientWidth + 0.5 || box.left < -0.5) {
            const name = (el.className.baseVal ?? el.className ?? '').toString().trim();
            over.push(`${el.tagName.toLowerCase()}${name ? '.' + name.split(/\s+/)[0] : ''} [${Math.round(box.left)}..${Math.round(box.right)}]`);
          }
        });
        return { view: doc.clientWidth, scroll: doc.scrollWidth, over: over.slice(0, 5) };
      });
      if (seen.scroll > seen.view) {
        failures += 1;
        console.log(`FAIL ${width}px ${path}: scrolls to ${seen.scroll}px — ${seen.over.join(', ')}`);
      }
    }
    await context.close();
  }
  await browser.close();
  console.log(failures ? `${failures} page/width combinations overflow` : 'No horizontal overflow at 320, 375, 390 or 430px.');
  process.exit(failures ? 1 : 0);
})();
