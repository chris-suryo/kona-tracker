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

(async () => {
  const b = await chromium.launch();
  for (const scheme of ['light', 'dark']) {
    // Logged out, in a context that never signs in.
    const anon = await b.newContext({ viewport: PHONE, deviceScaleFactor: 2, colorScheme: scheme });
    await stubTiles(anon);
    const ap = await anon.newPage();
    await ap.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await ap.waitForTimeout(600);
    await ap.screenshot({ path: path.join(OUT, `login-${scheme}.png`), fullPage: true });
    await anon.close();

    const c = await b.newContext({ viewport: PHONE, deviceScaleFactor: 2, colorScheme: scheme });
    await stubTiles(c);
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
    // A fresh context has never driven, so the first-drive legend is up.
    // Both states are worth a reviewer's eyes: the legend, and the controls
    // it was covering.
    await lp.screenshot({ path: path.join(OUT, `drive-first-visit-${scheme}.png`) });
    await lp.click('#legend');
    await lp.waitForTimeout(300);
    await lp.screenshot({ path: path.join(OUT, `drive-landscape-${scheme}.png`) });
    await lp.setViewportSize(PHONE);
    await lp.waitForTimeout(500);
    await lp.screenshot({ path: path.join(OUT, `drive-portrait-prompt-${scheme}.png`) });
    await land.close();
  }
  await b.close();
  console.log('done');
})();
