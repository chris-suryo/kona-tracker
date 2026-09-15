// Captures docs/screenshots/current-ui/ against scripts/audit_server.py.
// See docs/screenshots/README.md.
//
// `waitUntil` stays 'domcontentloaded'. The reason it used to give -- every
// page hanging on an unreachable webfont host -- died when the font was
// vendored, but the setting is still right: these pages poll and stream by
// design, so 'load' waits on work that is not meant to finish. What actually
// needed waiting on was the font, and fontsReady() below asks the browser
// for exactly that instead of guessing at a timeout.
const { chromium, devices } = require('playwright');
const BASE = 'http://127.0.0.1:8140';
const path = require('path');
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'current-ui');

// The app is used on an iPhone 14 Pro, from the home screen. Metrics come
// from Playwright's own descriptor rather than numbers typed from memory:
// 390x844 was the 14/15, not the Pro, and three CSS px too narrow.
//
// Three fields are chosen rather than copied, and each needs saying:
//
//  * `userAgent` is deliberately NOT taken. WebKit cannot be installed here
//    (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1, and no webkit build in
//    /opt/pw-browsers), so this is Blink wearing the descriptor's geometry.
//    Nothing in this app reads the UA, so Safari's string would buy no
//    fidelity and would put a false claim in every capture run's server log.
//    `defaultBrowserType: 'webkit'` in the descriptor is that same warning,
//    in Playwright's own words.
//  * the viewport height is the SCREEN's 852, not the descriptor's 660. 660
//    is Safari-with-a-toolbar; base.html ships a manifest and
//    apple-mobile-web-app-capable, and this app is opened from the home
//    screen, where there is no toolbar and the layout viewport is the
//    screen. 660 would draw the fold where the phone never draws it.
//  * `deviceScaleFactor` stays 2 against the descriptor's 3. DSF changes no
//    layout, only pixel density; 3 would take this set from ~3 MB to ~6.5 MB,
//    and it is regenerated and re-committed on every design pass.
const IPHONE = devices['iPhone 14 Pro'];
const PHONE = {
  viewport: { width: IPHONE.viewport.width, height: IPHONE.screen.height },
  screen: IPHONE.screen,
  deviceScaleFactor: 2,
  isMobile: IPHONE.isMobile,
  hasTouch: IPHONE.hasTouch,
};
// Drive mode is landscape: the screen rotated, which is what a phone held
// sideways actually gives the page.
const LANDSCAPE = {
  ...PHONE,
  viewport: { width: IPHONE.screen.height, height: IPHONE.screen.width },
  screen: { width: IPHONE.screen.height, height: IPHONE.screen.width },
};

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

// A flat tile for every basemap request. Tile hosts are unreachable from a
// sandbox, and without this EVERY map in this set is the "Map unavailable"
// state -- which is a real state, but showing it as the normal one is exactly
// the trap `sonar_cm` set in audit_server.py: a fixture that misses something
// does not fail, it quietly renders the empty case in front of a reviewer.
//
// Light and dark get visibly different greys, so a screenshot also says WHICH
// basemap the page asked for. That is not cosmetic: until 2026-09-15 the
// server always sent Alidade Smooth Dark, and a light page sat on a black map.
function tile(rgb) {
  // A 1x1 PNG of one colour, built rather than checked in.
  const zlib = require('zlib');
  const raw = Buffer.from([0x00, ...rgb]);
  const chunk = (tag, body) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(body.length);
    const head = Buffer.concat([Buffer.from(tag), body]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(zlib.crc32 ? zlib.crc32(head) >>> 0 : 0);
    return Buffer.concat([len, head, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(1, 0); ihdr.writeUInt32BE(1, 4);
  ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))
  ]);
}
const LIGHT_TILE = tile([0xe4, 0xe2, 0xda]);
const DARK_TILE = tile([0x24, 0x28, 0x22]);

async function stubTiles(context) {
  await context.route('**://*.stadiamaps.com/**', route => route.fulfill({
    status: 200, contentType: 'image/png',
    body: route.request().url().includes('_dark') ? DARK_TILE : LIGHT_TILE
  }));
  await context.route('**://tile.openstreetmap.org/**', route => route.fulfill({
    status: 200, contentType: 'image/png', body: LIGHT_TILE
  }));
}

// The one thing this capture used to get wrong silently. The font is local
// now, so document.fonts.ready settles in milliseconds -- but if a CSP
// directive, a path typo or a missing file ever blocks it again, these shots
// would quietly go back to being the fallback font with nothing to say so.
// Ask the browser directly and stop the run.
async function fontsReady(page) {
  const faces = await page.evaluate(async () => {
    await document.fonts.ready;
    return (await document.fonts.load('700 16px "Bricolage Grotesque"')).length;
  });
  if (!faces) {
    throw new Error('Bricolage Grotesque did not load: this capture would be the fallback font');
  }
}

(async () => {
  const b = await chromium.launch();
  for (const scheme of ['light', 'dark']) {
    // Logged out, in a context that never signs in.
    const anon = await b.newContext({ ...PHONE, colorScheme: scheme });
    await stubTiles(anon);
    const ap = await anon.newPage();
    await ap.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await ap.waitForTimeout(600);
    await fontsReady(ap);
    await ap.screenshot({ path: path.join(OUT, `login-${scheme}.png`), fullPage: true });
    await anon.close();

    const c = await b.newContext({ ...PHONE, colorScheme: scheme });
    await stubTiles(c);
    const p = await c.newPage();
    await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await p.fill('#passcode', '4242');
    await p.click('button[type=submit]');
    await p.waitForLoadState('domcontentloaded');
    for (const [route, name] of PORTRAIT_PAGES) {
      await p.goto(BASE + route, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(1800);   // camera poll + map tiles give up
      await fontsReady(p);
      await p.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`), fullPage: true });
    }
    await c.close();

    // Drive mode is landscape-only; portrait shows a "turn sideways" prompt,
    // and both are worth a reviewer's eyes.
    const land = await b.newContext({ ...LANDSCAPE, colorScheme: scheme });
    // Missing until 2026-09-15, so /drive's map alone rendered the
    // unreachable-tile path and the drive shots showed "Map unavailable" as
    // though that were drive mode's normal state -- the exact trap the
    // comment above stubTiles was written about, two contexts later.
    await stubTiles(land);
    const lp = await land.newPage();
    await lp.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await lp.fill('#passcode', '4242');
    await lp.click('button[type=submit]');
    await lp.waitForLoadState('domcontentloaded');
    await lp.goto(BASE + '/drive', { waitUntil: 'domcontentloaded' });
    await lp.waitForTimeout(2000);
    await fontsReady(lp);
    // A fresh context has never driven, so the first-drive legend is up.
    // Both states are worth a reviewer's eyes: the legend, and the controls
    // it was covering.
    await lp.screenshot({ path: path.join(OUT, `drive-first-visit-${scheme}.png`) });
    await lp.click('#legend');
    await lp.waitForTimeout(300);
    await lp.screenshot({ path: path.join(OUT, `drive-landscape-${scheme}.png`) });
    await lp.setViewportSize(PHONE.viewport);
    await lp.waitForTimeout(500);
    await fontsReady(lp);
    await lp.screenshot({ path: path.join(OUT, `drive-portrait-prompt-${scheme}.png`) });
    await land.close();
  }
  await b.close();
  console.log('done');
})();
