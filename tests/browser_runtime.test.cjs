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
    closest() { return null; }, click() {}
  };
}

function setup(script, preview = false) {
  const names = ['cam', 'cap', 'dot', 'livetxt', 'capture', 'capture-hint', 'activity-body', 'pull'];
  const nodes = Object.fromEntries(names.map(name => [name, element()]));
  const page = element(), label = element(), note = element(), freshness = element(), camFrame = element();
  nodes.pull.querySelector = () => label;
  nodes['activity-body'].querySelector = selector => ({
    '.preview-banner': preview ? element() : null, '.freshness': freshness, 'p.note': note
  })[selector] || null;
  const document = {...element(), hidden: false,
    getElementById: id => nodes[id], querySelectorAll: () => [],
    querySelector: s => s === 'main.activity-page' ? page : s === '.cam' ? camFrame : null,
    createElement: element, createTextNode: text => ({textContent: text})
  };
  const timers = new Map(), intervals = new Map(), requests = [], created = [], revoked = [];
  const window = {...element(), location: {href: ''}};
  let nextTimer = 0, files = 0;
  const env = {
    document, window, AbortController, Date, console,
    setTimeout: (fn, delay) => { timers.set(++nextTimer, {fn, delay}); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    // Intervals are kept apart from timeouts so `fire(delay)` cannot reach
    // the quiet refresh ticker by accident; `tick()` is its own door.
    setInterval: (fn, delay) => { intervals.set(++nextTimer, {fn, delay}); return nextTimer; },
    clearInterval: id => intervals.delete(id),
    fetch: (url, options = {}) => new Promise((resolve, reject) => {
      const req = {url, options, resolve, reject}; requests.push(req);
      options.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name:'AbortError'})));
    }),
    // Object URLs are recorded, never created: the test can prove at most
    // one is alive without a real Blob.
    URL: {
      createObjectURL: () => { const u = 'blob:' + (created.length + 1); created.push(u); return u; },
      revokeObjectURL: u => { revoked.push(u); }
    },
    File: class { constructor() { files++; } }, navigator: {},
    DOMParser: class { parseFromString() { return {getElementById: () => ({innerHTML:'new render'}), querySelector: () => null}; } }
  };
  vm.runInNewContext(fs.readFileSync(path.join(staticDir, script), 'utf8'), env);
  return {nodes, page, label, note, document, window, requests, timers, intervals, created, revoked, camFrame,
    files: () => files,
    tick() {
      const entry = [...intervals][0];
      assert.ok(entry, 'no interval installed');
      entry[1].fn();
    },
    fire(delay) {
      const entry = [...timers].find(([, t]) => t.delay === delay);
      assert.ok(entry, `missing timer ${delay}`);
      timers.delete(entry[0]); entry[1].fn();
    }
  };
}
async function settle() { for (let n = 0; n < 12; n++) await Promise.resolve(); }
function response(json, options = {}) { return {ok:true, redirected:false, status:200, json:async () => json, text:async () => '<main>new</main>', blob:async () => ({}), ...options}; }
// One /snapshot.jpg response: the pixels are a stand-in, the headers are the truth.
function frame(state, seq, extra = {}) {
  const map = {'X-Kona-State': state, 'X-Kona-Seq': String(seq), 'X-Kona-Error': extra.error || ''};
  if (extra.age !== undefined) { map['X-Kona-Frame-Age'] = String(extra.age); }
  return {ok:true, redirected:false, status:200, headers:{get: n => n in map ? map[n] : null},
    blob:async () => ({state}), json:async () => null, text:async () => ''};
}

test('camera long-polls one frame at a time and reveals only a decoded live frame', async () => {
  const x = setup('camera.js');
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.requests.length, 1);
  assert.equal(x.requests[0].url, '/snapshot.jpg?after=0');
  x.requests[0].resolve(frame('live', 7)); await settle();
  assert.deepEqual(x.created, ['blob:1']);
  assert.equal(x.nodes.cam.src, 'blob:1');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true, 'masked until it decodes');
  x.nodes.cam.naturalWidth = 1280; x.nodes.cam.events.load();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), false);
  // The next request is already queued and asks for the frame after this one.
  x.fire(0);
  assert.equal(x.requests.length, 2);
  assert.equal(x.requests[1].url, '/snapshot.jpg?after=7');
  // Exactly one in flight: nothing else is scheduled while it is pending.
  assert.equal([...x.timers.values()].filter(t => t.delay !== 10000).length, 0);
});

test('a response the server did not call live stays masked and is described honestly', async () => {
  const x = setup('camera.js');
  x.requests[0].resolve(frame('stale', 3, {age: 4.2})); await settle();
  assert.equal(x.created.length, 0, 'no object URL for a placeholder');
  assert.equal(x.nodes.livetxt.textContent, 'STALE');
  assert.equal(x.nodes.cap.textContent, 'No new frames for 4 s');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
  assert.equal(x.camFrame.classList.contains('connecting'), true);
  x.fire(500);  // the floor after a non-live answer; the server paces live ones
  x.requests[1].resolve(frame('disconnected', 3, {error: 'black_frame'})); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'CHECK CAMERA');
  assert.match(x.nodes.cap.textContent, /lens cover/);
  assert.equal(x.camFrame.classList.contains('connecting'), false, 'a hard failure drops the overlay');
  x.fire(500);
  x.requests[2].resolve(frame('connecting', 3)); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.created.length, 0);
});

test("a late decode never reveals after the server's latest word is not live", async () => {
  const x = setup('camera.js');
  x.requests[0].resolve(frame('live', 1)); await settle();
  x.fire(0);
  x.requests[1].resolve(frame('stale', 1, {age: 5})); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'STALE');
  x.nodes.cam.naturalWidth = 1280; x.nodes.cam.events.load();  // frame 1 decodes late
  assert.equal(x.nodes.livetxt.textContent, 'STALE');
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
});

test('at most one object URL is alive: the previous is revoked on the next frame, the last on pause', async () => {
  const x = setup('camera.js');
  x.requests[0].resolve(frame('live', 1)); await settle(); x.fire(0);
  x.requests[1].resolve(frame('live', 2)); await settle(); x.fire(0);
  x.requests[2].resolve(frame('live', 3)); await settle();
  assert.deepEqual(x.created, ['blob:1', 'blob:2', 'blob:3']);
  assert.deepEqual(x.revoked, ['blob:1', 'blob:2']);
  assert.equal(x.nodes.cam.src, 'blob:3');
  x.document.hidden = true; x.document.events.visibilitychange();
  assert.deepEqual(x.revoked, ['blob:1', 'blob:2', 'blob:3']);
  assert.equal(x.nodes.cam.naturalWidth, 0);
  assert.equal(x.nodes.livetxt.textContent, 'PAUSED');
});

test('failures back off and never spin; a 401 goes to login and schedules nothing more', async () => {
  const x = setup('camera.js');
  for (const delay of [500, 1000, 2000, 4000, 5000, 5000]) {
    x.requests[x.requests.length - 1].reject(new Error('network')); await settle();
    assert.equal(x.nodes.livetxt.textContent, 'OFFLINE');
    x.fire(delay);  // fails loudly if that exact delay is not the one scheduled
  }
  // An answer resets the backoff.
  x.requests[x.requests.length - 1].resolve(frame('live', 9)); await settle();
  x.fire(0);
  x.requests[x.requests.length - 1].reject(new Error('network')); await settle();
  x.fire(500);
  const before = x.requests.length;
  x.requests[before - 1].resolve(response(null, {ok:false, status:401})); await settle();
  assert.equal(x.window.location.href, '/login');
  assert.equal(x.timers.size, 0, 'nothing scheduled after being sent to login');
  assert.equal(x.requests.length, before);
});

test('a hidden page aborts its poll, shows PAUSED rather than OFFLINE, and resumes fresh', async () => {
  const x = setup('camera.js');
  x.document.hidden = true; x.document.events.visibilitychange();
  assert.equal(x.requests[0].options.signal.aborted, true);
  await settle();
  assert.equal(x.nodes.livetxt.textContent, 'PAUSED', 'the abort we caused is not a failure');
  assert.equal(x.timers.size, 0);
  x.document.hidden = false; x.document.events.visibilitychange();
  assert.equal(x.requests.length, 2);
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  x.requests[1].resolve(frame('live', 4)); await settle();
  x.nodes.cam.naturalWidth = 1280; x.nodes.cam.events.load();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
});

test('a hung poll is abandoned at the deadline and retried with backoff', async () => {
  const x = setup('camera.js');
  x.fire(10000);
  assert.equal(x.requests[0].options.signal.aborted, true);
  await settle();
  assert.equal(x.nodes.livetxt.textContent, 'OFFLINE');
  x.fire(500);
  assert.equal(x.requests.length, 2);
});

test('capture finds its own request among the polls and shares only a live frame', async () => {
  const x = setup('camera.js');
  const shots = () => x.requests.filter(q => q.url.indexOf('/snapshot.jpg?t=') === 0);
  x.nodes.capture.events.click();
  assert.equal(shots().length, 1);
  shots()[0].resolve(frame('disconnected', 1, {error: 'black_frame'})); await settle();
  assert.equal(x.files(), 0);
  assert.equal(x.nodes.capture.disabled, false);
  assert.match(x.nodes['capture-hint'].textContent, /Could not capture/);
  x.nodes.capture.events.click();
  shots()[1].resolve(frame('live', 2)); await settle();
  assert.equal(x.files(), 1);
  assert.equal(x.nodes['capture-hint'].textContent, 'Photo saved');
});

test('sample preview never installs automatic or pull refresh', () => {
  const x = setup('app.js', true);
  assert.equal(x.window.KonaRefresh, undefined);
  assert.equal(x.document.events.visibilitychange, undefined);
  assert.equal(x.requests.length, 0);
  assert.equal(x.intervals.size, 0, 'sample data must never tick');
});

// The page used to render once and sit there, so a walk could finish while
// the screen still showed where she was when it opened.
test('an open page asks again on its own, quietly, without forcing a Fi call', async () => {
  const x = setup('app.js');
  assert.equal(x.intervals.size, 1);
  assert.equal([...x.intervals.values()][0].delay, 60000);
  x.tick();
  assert.equal(x.requests.length, 1);
  assert.equal(x.requests[0].url, '/activity', 'the timer collects, it does not force');
  assert.equal(x.nodes.pull.classList.contains('busy'), false, 'a quiet tick shows no pull bar');
  assert.notEqual(x.label.textContent, 'Refreshing\u2026');
  x.requests[0].resolve(response({})); await settle();
  assert.equal(x.nodes['activity-body'].innerHTML, 'new render');
  assert.equal(x.nodes.pull.classList.contains('finished'), false);
});

test('a pocketed phone stops asking, and asks once on the way back', () => {
  const x = setup('app.js');
  x.document.hidden = true; x.document.events.visibilitychange();
  assert.equal(x.intervals.size, 0);
  assert.equal(x.requests.length, 0);
  x.document.hidden = false; x.document.events.visibilitychange();
  assert.equal(x.requests.length, 1);
  assert.equal(x.requests[0].url, '/activity?fresh=1', 'coming back is a person asking');
  assert.equal(x.intervals.size, 1);
});

test('the pull gesture still forces a fresh reading', () => {
  const x = setup('app.js'); x.window.scrollY = 0;
  x.page.events.touchstart({touches:[{clientY:0}], target:element()});
  x.page.events.touchmove({touches:[{clientY:150}]});
  x.page.events.touchend();
  assert.equal(x.requests.length, 1);
  assert.equal(x.requests[0].url, '/activity?fresh=1');
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
  const window = {}, layer = {addTo() {}, on() {}}, map = {remove() { removed++; }, setView() {}};
  const L = {map: () => map, tileLayer: () => layer, marker: () => layer,
    divIcon: () => ({}), control: {zoom: () => layer}};
  // A real element always has classList; map.js toggles `tiles-dark` on it so
  // the CSS filter that fakes a dark basemap does not run over already-dark
  // Stadia tiles. The stub needs it or the harness fails where a browser
  // would not. No #map-config here on purpose: the OSM fallback must work
  // when the block is absent.
  const classes = new Set();
  const mapEl = {classList: {toggle: (n, on) => on ? classes.add(n) : classes.delete(n),
                             contains: n => classes.has(n)}};
  const document = {getElementById: id => id === 'map-points'
    ? (points ? {textContent:points} : null)
    : (id === 'kona-map' ? mapEl : null)};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), {window,document,L});
  window.KonaMap.init(); assert.equal(removed, 1);
  points = null; window.KonaMap.init(); assert.equal(removed, 2);
  window.KonaMap.destroy(); assert.equal(removed, 2);
});

// A map on screen with "Map unavailable" printed under it is the page
// contradicting itself; that is what one failed tile used to produce.
test('one failed tile does not hide a map that has already drawn', () => {
  const handlers = {};
  const window = {}, layer = {addTo() {}, on(name, fn) { handlers[name] = fn; }};
  let resized = 0;
  const map = {remove() {}, setView() {}, invalidateSize() { resized++; }};
  const L = {map: () => map, tileLayer: () => layer, marker: () => layer,
    divIcon: () => ({}), control: {zoom: () => layer}};
  const classes = new Set();
  const mapEl = {hidden: false,
    classList: {toggle: (n, on) => on ? classes.add(n) : classes.delete(n), contains: n => classes.has(n)}};
  const notice = {hidden: true};
  const document = {getElementById: id => ({
    'map-points': {textContent: '[{"lat":30,"lon":-97}]'},
    'kona-map': mapEl, 'map-unavailable': notice
  })[id] || null};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), {window,document,L});
  window.KonaMap.init();

  handlers.tileload();
  handlers.tileerror();
  assert.equal(mapEl.hidden, false, 'a drawn map stays drawn');
  assert.equal(notice.hidden, true);
});

test('a tile server that answers nothing says so, and recovers if it wakes up', () => {
  const handlers = {};
  const window = {}, layer = {addTo() {}, on(name, fn) { handlers[name] = fn; }};
  let resized = 0;
  const map = {remove() {}, setView() {}, invalidateSize() { resized++; }};
  const L = {map: () => map, tileLayer: () => layer, marker: () => layer,
    divIcon: () => ({}), control: {zoom: () => layer}};
  const classes = new Set();
  const mapEl = {hidden: false,
    classList: {toggle: (n, on) => on ? classes.add(n) : classes.delete(n), contains: n => classes.has(n)}};
  const notice = {hidden: true};
  const document = {getElementById: id => ({
    'map-points': {textContent: '[{"lat":30,"lon":-97}]'},
    'kona-map': mapEl, 'map-unavailable': notice
  })[id] || null};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), {window,document,L});
  window.KonaMap.init();

  handlers.tileerror();
  assert.equal(mapEl.hidden, true);
  assert.equal(notice.hidden, false);

  handlers.tileload();
  assert.equal(mapEl.hidden, false);
  assert.equal(notice.hidden, true);
  assert.equal(resized, 1, 'Leaflet sized itself while hidden and must re-measure');
});
