// Contact sheets for the nitpick round: one PNG per page, light and dark side
// by side, with a lettered-and-numbered grid burned over both so a remark
// from a phone can name a spot -- "steps, light, C4, too much gap" -- and be
// acted on without a screenshot of a screenshot.
//
// Chris asked whether ChatGPT could annotate the UI. Image models describe;
// they do not reliably draw on pixels. This is the workflow that works with
// nothing new installed: run this, open the sheet on the phone, circle things
// in Markup, send it back -- or just say the grid reference.
//
//   NODE_PATH=/opt/node22/lib/node_modules node scripts/contact_sheet.js
//
// Reads docs/screenshots/current-ui/*-light.png and the matching -dark.png
// (regenerate those first with audit_shots.js), writes
// docs/screenshots/contact/<page>.png. Playwright renders the layout: the two
// images and the grid are plain HTML in a page of its own, which is simpler
// and more legible than drawing into a canvas by hand, and it is the same
// Chromium the audit captures already use.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const IN = path.join(__dirname, '..', 'docs', 'screenshots', 'current-ui');
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'contact');
// Grid cells in CSS pixels of the *page* (the captures are 2x). 100 px is
// coarse enough to say in three characters and fine enough to point at a
// single control.
const CELL = 100;
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

function pngSize(buffer) {
  // IHDR is always the first chunk: width and height at bytes 16 and 20.
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function pages() {
  return fs.readdirSync(IN)
    .filter(name => name.endsWith('-light.png') && fs.existsSync(path.join(IN, name.replace('-light', '-dark'))))
    .map(name => name.replace('-light.png', ''))
    .sort();
}

function sheetHtml(page) {
  const light = fs.readFileSync(path.join(IN, `${page}-light.png`));
  const dark = fs.readFileSync(path.join(IN, `${page}-dark.png`));
  // The captures are deviceScaleFactor 2; the grid is drawn in page pixels,
  // so the image is shown at half its pixel size and the cells line up with
  // what a phone actually lays out.
  const size = pngSize(light);
  const w = size.width / 2, h = size.height / 2;
  const cols = Math.ceil(w / CELL), rows = Math.ceil(h / CELL);
  const lines = [];
  for (let c = 0; c <= cols; c++) {
    lines.push(`<i class="v" style="left:${c * CELL}px"></i>`);
    if (c < cols) { lines.push(`<b class="cl" style="left:${c * CELL}px">${LETTERS[c] || '?'}</b>`); }
  }
  for (let r = 0; r <= rows; r++) {
    lines.push(`<i class="h" style="top:${r * CELL}px"></i>`);
    if (r < rows) { lines.push(`<b class="rl" style="top:${r * CELL}px">${r + 1}</b>`); }
  }
  const panel = (label, buffer) => `
    <figure>
      <figcaption>${page} · ${label}</figcaption>
      <div class="frame" style="width:${w}px;height:${h}px">
        <img src="data:image/png;base64,${buffer.toString('base64')}" width="${w}" height="${h}">
        <div class="grid">${lines.join('')}</div>
      </div>
    </figure>`;
  // Inline styles are fine here: this page is never served by the app and
  // carries no CSP. Do not copy the pattern into a template.
  return `<!doctype html><meta charset="utf-8"><style>
    body { margin: 0; padding: 24px; background: #6b6f68; font: 600 13px/1.2 system-ui, sans-serif; color: #fff; }
    main { display: flex; gap: 32px; align-items: flex-start; }
    figure { margin: 0; }
    figcaption { margin: 0 0 0 24px; font-size: 15px; letter-spacing: .02em; }
    /* Room above the frame for the column letters, which sit just outside it. */
    .frame { position: relative; margin: 28px 0 0 24px; box-shadow: 0 2px 12px rgba(0,0,0,.4); }
    img { display: block; }
    .grid { position: absolute; inset: 0; pointer-events: none; }
    .grid i { position: absolute; display: block; background: rgba(255, 60, 60, .55); }
    .grid i.v { top: 0; bottom: 0; width: 1px; }
    .grid i.h { left: 0; right: 0; height: 1px; }
    .grid b { position: absolute; padding: 1px 4px; border-radius: 3px; background: rgba(255, 60, 60, .85); color: #fff; font-size: 11px; }
    .grid b.cl { top: -20px; transform: translateX(2px); }
    .grid b.rl { left: -24px; transform: translateY(2px); }
  </style><main>${panel('light', light)}${panel('dark', dark)}</main>`;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 2 });
  for (const page of pages()) {
    await p.setContent(sheetHtml(page), { waitUntil: 'load' });
    const box = await p.locator('main').boundingBox();
    await p.setViewportSize({ width: Math.ceil(box.width + 48), height: Math.ceil(box.height + 48) });
    await p.screenshot({ path: path.join(OUT, `${page}.png`), fullPage: true });
    console.log(page);
  }
  await b.close();
  console.log('done ->', path.relative(process.cwd(), OUT));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
