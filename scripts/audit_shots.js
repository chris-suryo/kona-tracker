// Captures docs/screenshots/current-ui/ against scripts/audit_server.py.
// See docs/screenshots/README.md -- in particular, `waitUntil` must stay
// 'domcontentloaded': with 'load' every page hangs on a webfont host.
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:8140';
const path = require('path');
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'current-ui');

// iPhone 14/15 logical viewport. deviceScaleFactor 2 keeps the PNGs legible
// to a reviewer zooming in without tripling the file size at 3x.
const PHONE = { width: 390, height: 844 };
const LANDSCAPE = { width: 844, height: 390 };

const PORTRAIT_PAGES = [
  ['/activity',  'activity'],
  ['/map',       'map-live'],
  ['/rest',      'rest'],
  ['/steps',     'steps'],
  ['/walks/3f0WNDOsmKujNTHK3ByXXo', 'walk-detail'],
  ['/camera',    'camera'],
  ['/robot',     'robot'],
  ['/settings',  'settings'],
  ['/preview/steps', 'history-preview'],
];

(async () => {
  const b = await chromium.launch();
  for (const scheme of ['light', 'dark']) {
    // Logged out, in a context that never signs in.
    const anon = await b.newContext({ viewport: PHONE, deviceScaleFactor: 2, colorScheme: scheme });
    const ap = await anon.newPage();
    await ap.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await ap.waitForTimeout(600);
    await ap.screenshot({ path: path.join(OUT, `login-${scheme}.png`), fullPage: true });
    await anon.close();

    const c = await b.newContext({ viewport: PHONE, deviceScaleFactor: 2, colorScheme: scheme });
    const p = await c.newPage();
    await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await p.fill('#passcode', '4242');
    await p.click('button[type=submit]');
    await p.waitForLoadState('domcontentloaded');
    for (const [route, name] of PORTRAIT_PAGES) {
      await p.goto(BASE + route, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(1800);   // camera poll + map tiles give up
      await p.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`), fullPage: true });
    }
    await c.close();

    // Drive mode is landscape-only; portrait shows a "turn sideways" prompt,
    // and both are worth a reviewer's eyes.
    const land = await b.newContext({ viewport: LANDSCAPE, deviceScaleFactor: 2, colorScheme: scheme });
    const lp = await land.newPage();
    await lp.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await lp.fill('#passcode', '4242');
    await lp.click('button[type=submit]');
    await lp.waitForLoadState('domcontentloaded');
    await lp.goto(BASE + '/drive', { waitUntil: 'domcontentloaded' });
    await lp.waitForTimeout(2000);
    await lp.screenshot({ path: path.join(OUT, `drive-landscape-${scheme}.png`) });
    await lp.setViewportSize(PHONE);
    await lp.waitForTimeout(500);
    await lp.screenshot({ path: path.join(OUT, `drive-portrait-prompt-${scheme}.png`) });
    await land.close();
  }
  await b.close();
  console.log('done');
})();
