// No packages: run with an existing Node installation:
// node --test tests/browser_runtime.test.cjs
// Executes the shipped scripts with controlled network/timer/DOM boundaries.
//
// MANUAL TEST, NOT A GATE. CI (.github/workflows/ci.yml) runs ruff and pytest
// only; nothing runs this file automatically, so a green CI says nothing
// about it. Run it yourself after touching app.js or camera.js. Wiring it
// into CI means installing Node on both runners, which is a dependency
// decision that is Chris's to make (docs/overnight-brief.md, item 3).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const staticDir = path.join(__dirname, '../src/kona_tracker/web/static');

function element() {
  const events = {}, classes = new Set(), attrs = {};
  return {
    events, textContent: '', hidden: false, naturalWidth: 640, style: {},
    classList: {
      add: (...xs) => xs.forEach(x => classes.add(x)),
      remove: (...xs) => xs.forEach(x => classes.delete(x)),
      contains: x => classes.has(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x)
    },
    addEventListener: (name, fn) => { events[name] = fn; },
    removeAttribute(name) { delete attrs[name]; if (name === 'src') this.naturalWidth = 0; },
    getAttribute: name => attrs[name] || null,
    appendChild() {}, querySelectorAll() { return []; }, querySelector() { return null; },
    closest() { return null; }
  };
}

function setup(script, preview = false) {
  const names = ['cam', 'cap', 'dot', 'livetxt', 'capture', 'capture-hint', 'activity-body', 'pull'];
  const nodes = Object.fromEntries(names.map(name => [name, element()]));
  const page = element(), label = element(), note = element(), freshness = element();
  nodes.pull.querySelector = () => label;
  nodes['activity-body'].querySelector = selector => ({
    '.preview-banner': preview ? element() : null, '.freshness': freshness, 'p.note': note
  })[selector] || null;
  const document = {...element(), hidden: false,
    getElementById: id => nodes[id], querySelectorAll: () => [],
    querySelector: s => s === 'main.activity-page' ? page : null,
    createElement: element, createTextNode: text => ({textContent: text})
  };
  const timers = new Map(), requests = [], window = {...element(), location: {href: ''}};
  let nextTimer = 0, files = 0;
  const env = {
    document, window, AbortController, Date, console,
    setTimeout: (fn, delay) => { timers.set(++nextTimer, {fn, delay}); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options = {}) => new Promise((resolve, reject) => {
      const req = {url, options, resolve, reject}; requests.push(req);
      options.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name:'AbortError'})));
    }),
    File: class { constructor() { files++; } }, navigator: {},
    DOMParser: class { parseFromString() { return {getElementById: () => ({innerHTML:'new render'}), querySelector: () => null}; } }
  };
  vm.runInNewContext(fs.readFileSync(path.join(staticDir, script), 'utf8'), env);
  return {nodes, page, label, note, document, window, requests, timers,
    files: () => files,
    fire(delay) {
      const entry = [...timers].find(([, t]) => t.delay === delay);
      assert.ok(entry, `missing timer ${delay}`);
      timers.delete(entry[0]); entry[1].fn();
    }
  };
}
async function settle() { for (let n = 0; n < 12; n++) await Promise.resolve(); }
function response(json, options = {}) { return {ok:true, redirected:false, json:async () => json, text:async () => '<main>new</main>', ...options}; }

test('camera starts unverified, polls serially, and masks the picture on timeout', async () => {
  const x = setup('camera.js');
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.requests.length, 1);
  x.requests[0].resolve(response({state:'live'})); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), false);
  x.fire(2000); assert.equal(x.requests.length, 2);
  assert.equal([...x.timers.values()].filter(t => t.delay === 2000).length, 0);
  x.fire(5000); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'OFFLINE');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
  x.fire(2000); x.requests[2].resolve(response({state:'live'})); await settle();
  assert.match(x.nodes.cam.src, /^\/stream.mjpg\?t=/);
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
});

test('a decoded first frame reveals at once, not on the next poll tick', async () => {
  // Regression: the reveal used to live only inside poll(), so a frame that
  // decoded just after a poll sat masked for a full 2000ms cycle. The <img>
  // 'load' event now reveals it the moment it decodes, once the server is live.
  const x = setup('camera.js');
  x.nodes.cam.naturalWidth = 0;  // the MJPEG has not decoded a frame yet
  x.requests[0].resolve(response({state:'live'})); await settle();
  // Server says live, but with no frame the picture stays honestly masked.
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
  // The first frame decodes: reveal immediately, without firing the 2000ms poll.
  x.nodes.cam.naturalWidth = 480;
  x.nodes.cam.events.load();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), false);
});

test('the load event never reveals a placeholder the server has not called live', async () => {
  // A frame can decode (naturalWidth > 0) while the server is still connecting
  // or disconnected — that frame is the NO-SIGNAL placeholder. The load-driven
  // reveal must stay shut until /status.json actually reports live.
  const x = setup('camera.js');
  x.requests[0].resolve(response({state:'connecting'})); await settle();
  x.nodes.cam.naturalWidth = 480;
  x.nodes.cam.events.load();
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
});

test('hidden camera releases stream and ignores obsolete responses after resume', async () => {
  const x = setup('camera.js');
  x.document.hidden = true; x.document.events.visibilitychange();
  assert.equal(x.requests[0].options.signal.aborted, true);
  assert.equal(x.nodes.cam.naturalWidth, 0);
  x.document.hidden = false; x.document.events.visibilitychange();
  await settle(); assert.equal(x.requests.length, 2);
  x.nodes.cam.naturalWidth = 640;
  x.requests[1].resolve(response({state:'live'})); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
  assert.equal([...x.timers.values()].filter(t => t.delay === 2000).length, 1);
});

test('HTTP failure and malformed status never display LIVE', async () => {
  for (const r of [response({}, {ok:false}), response({state:'surprise'})]) {
    const x = setup('camera.js'); x.requests[0].resolve(r); await settle();
    assert.equal(x.nodes.livetxt.textContent, 'OFFLINE');
  }
});

test('an idle hub restarts the stream; historical errors do not override connecting', async () => {
  const x = setup('camera.js');
  x.requests[0].resolve(response({state:'idle'})); await settle();
  assert.match(x.nodes.cam.src, /^\/stream.mjpg\?t=/);
  x.fire(2000);
  x.requests[1].resolve(response({state:'connecting',last_error_kind:'black_frame'}));
  await settle();
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
});

test('a placeholder snapshot cannot be shared as Kona right now', async () => {
  const x = setup('camera.js');
  x.nodes.capture.events.click();
  x.requests[1].resolve(response(null, {headers:{get: () => 'disconnected'}}));
  await settle();
  assert.equal(x.files(), 0);
  assert.equal(x.nodes.capture.disabled, false);
  assert.match(x.nodes['capture-hint'].textContent, /Could not capture/);
});

test('sample preview never installs automatic or pull refresh', () => {
  const x = setup('app.js', true);
  assert.equal(x.window.KonaRefresh, undefined);
  assert.equal(x.document.events.visibilitychange, undefined);
  assert.equal(x.requests.length, 0);
});

test('refresh timeout unlocks retry and explains failure', async () => {
  const x = setup('app.js');
  x.window.KonaRefresh(); x.window.KonaRefresh();
  assert.equal(x.requests.length, 1);
  x.fire(20000); await settle();
  x.fire(650); x.fire(220);
  assert.equal(x.nodes.pull.hidden, true);
  assert.match(x.note.textContent, /Couldn't refresh/);
  x.window.KonaRefresh(); assert.equal(x.requests.length, 2);
});

test('refresh disposes the old map before installing a new one', async () => {
  const x = setup('app.js'), calls = [];
  x.window.KonaMap = {destroy() { calls.push('destroy'); }, init() { calls.push('init'); }};
  x.window.KonaRefresh(); x.requests[0].resolve(response({})); await settle();
  assert.deepEqual(calls, ['destroy', 'init']);
  assert.equal(x.nodes['activity-body'].innerHTML, 'new render');
});

test('cancelled touch never triggers a refresh', () => {
  const x = setup('app.js'); x.window.scrollY = 0;
  x.page.events.touchstart({touches:[{clientY:0}], target:element()});
  x.page.events.touchmove({touches:[{clientY:150}]});
  x.page.events.touchcancel(); x.page.events.touchend();
  assert.equal(x.requests.length, 0);
});

test('a new pull is not hidden by the previous dismissal timer', async () => {
  const x = setup('app.js'); x.window.scrollY = 0;
  x.window.KonaRefresh(); x.requests[0].resolve(response({})); await settle();
  assert.equal(x.nodes.pull.classList.contains('finished'), true);
  x.page.events.touchstart({touches:[{clientY:0}], target:element()});
  x.page.events.touchmove({touches:[{clientY:150}]});
  assert.equal([...x.timers.values()].some(t => t.delay === 650), false);
  assert.equal(x.nodes.pull.hidden, false);
  x.page.events.touchend();
  assert.equal(x.requests.length, 2);
  assert.equal(x.nodes.pull.style.transform, '');
});

test('map init releases the previous Leaflet instance even when new points are absent', () => {
  let removed = 0, points = '[{"lat":30,"lon":-97}]';
  const window = {}, layer = {addTo() {}}, map = {remove() { removed++; }, setView() {}};
  const L = {map: () => map, tileLayer: () => layer, marker: () => layer,
    divIcon: () => ({}), control: {zoom: () => layer}};
  const document = {getElementById: id => id === 'map-points' ? (points ? {textContent:points} : null) : {}};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), {window,document,L});
  window.KonaMap.init(); assert.equal(removed, 1);
  points = null; window.KonaMap.init(); assert.equal(removed, 2);
  window.KonaMap.destroy(); assert.equal(removed, 2);
});
