// No packages: run with an existing Node installation:
// node --test tests/browser_runtime.test.cjs
// Executes the shipped scripts with controlled network/timer/DOM boundaries.
//
// MANUAL TEST, NOT A GATE. CI (.github/workflows/ci.yml) runs ruff and pytest
// only; nothing runs this file automatically, so a green CI says nothing
// about it. Run it yourself after touching app.js, poll.js, camera.js or robot.js. Wiring it
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
    dataset: {}, disabled: false,
    classList: {
      add: (...xs) => xs.forEach(x => classes.add(x)),
      remove: (...xs) => xs.forEach(x => classes.delete(x)),
      contains: x => classes.has(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x)
    },
    // Chained, not overwritten: the drive page and poll.js both listen for
    // visibilitychange and pagehide, and a stub that kept only the last one
    // would hide whichever script was loaded first.
    addEventListener: (name, fn) => {
      const prev = events[name];
      events[name] = prev ? (e) => { prev(e); fn(e); } : fn;
    },
    removeAttribute(name) { delete attrs[name]; if (name === 'src') this.naturalWidth = 0; },
    getAttribute: name => attrs[name] || null,
    setAttribute(name, value) { attrs[name] = String(value); },
    // A joystick needs a box to measure the thumb against, and pointer
    // capture so a thumb sliding off the pad still belongs to it.
    getBoundingClientRect: () => ({left: 0, top: 0, width: 128, height: 128}),
    setPointerCapture() {}, releasePointerCapture() {},
    appendChild() {}, querySelectorAll() { return []; }, querySelector() { return null; },
    closest() { return null; }, click() {}
  };
}

function setup(script, preview = false) {
  const names = ['cam', 'cap', 'dot', 'livetxt', 'capture', 'capture-hint', 'activity-body', 'pull', 'zoom-level',
    'drive', 'stick', 'knob', 'estop', 'estop-alarm', 'speed', 'rot-left', 'rot-right', 'shout', 'shout-text', 'note',
    'volts', 'sonar', 'picture'];
  const nodes = Object.fromEntries(names.map(name => [name, element()]));
  const page = element(), label = element(), note = element(), freshness = element(), camFrame = element();
  // A 400x225 frame at the page origin, so the zoom maths can be checked in px.
  camFrame.clientWidth = 400; camFrame.clientHeight = 225;
  camFrame.getBoundingClientRect = () => ({left: 0, top: 0});
  nodes.pull.querySelector = () => label;
  // The drive page reads its send interval from the server, so the loop and
  // the gateway's TTL can never drift apart.
  nodes.drive.dataset.interval = '200';
  nodes['activity-body'].querySelector = selector => ({
    '.preview-banner': preview ? element() : null, '.freshness': freshness, 'p.note': note
  })[selector] || null;
  const document = {...element(), hidden: false,
    getElementById: id => nodes[id], querySelectorAll: () => [],
    querySelector: s => s === 'main.activity-page' ? page : s === '.cam' ? camFrame : null,
    createElement: element, createTextNode: text => ({textContent: text})
  };
  const timers = new Map(), intervals = new Map(), requests = [], created = [], revoked = [], beacons = [];
  // Timers are fired by hand here, so the wall clock never moves and code
  // that asks "how long since the last answer?" would always say "no time".
  // `advance()` is how a test says that time passed.
  const clock = {offset: 0};
  const RealDate = Date;
  function StoppedDate(...args) { return new RealDate(...args); }
  StoppedDate.now = () => RealDate.now() + clock.offset;
  StoppedDate.prototype = RealDate.prototype;
  const window = {...element(), location: {href: ''}};
  let nextTimer = 0, files = 0;
  const env = {
    document, window, AbortController, Date: StoppedDate, console,
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
    File: class { constructor() { files++; } },
    Blob: class { constructor(parts) { this.parts = parts; } },
    navigator: {sendBeacon: (url) => { beacons.push(url); return true; }},
    DOMParser: class { parseFromString() { return {getElementById: () => ({innerHTML:'new render'}), querySelector: () => null}; } }
  };
  // The two picture pages load poll.js first, as their templates do; the
  // loop lives there and camera.js / robot.js call window.KonaPoll.
  const scripts = ['camera.js', 'robot.js', 'drive.js'].includes(script) ? ['poll.js', script] : [script];
  scripts.forEach(s => vm.runInNewContext(fs.readFileSync(path.join(staticDir, s), 'utf8'), env));
  return {nodes, page, label, note, document, window, requests, timers, intervals, created, revoked, camFrame, beacons,
    files: () => files,
    advance(ms) { clock.offset += ms; },
    // `tick()` fires whichever interval is first; a page with three of them
    // needs to name the one it means.
    tickEvery(delay) {
      const entry = [...intervals].find(([, t]) => t.delay === delay);
      assert.ok(entry, `missing interval ${delay}`);
      entry[1].fn();
    },
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

test('the robot page runs the same loop against its own camera and its own words', async () => {
  const x = setup('robot.js');
  assert.equal(x.nodes.livetxt.textContent, 'CONNECTING');
  assert.equal(x.nodes.cap.textContent, 'Reaching the robot…');
  assert.equal(x.requests[0].url, '/snapshot.jpg?cam=robot&after=0');
  x.requests[0].resolve(frame('live', 3)); await settle();
  x.nodes.cam.naturalWidth = 640; x.nodes.cam.events.load();
  assert.equal(x.nodes.livetxt.textContent, 'LIVE');
  x.fire(0);
  assert.equal(x.requests[1].url, '/snapshot.jpg?cam=robot&after=3');
  // An off robot is its normal state, said plainly: never a USB cable.
  x.requests[1].resolve(frame('disconnected', 3, {error: 'open'})); await settle();
  assert.equal(x.nodes.livetxt.textContent, 'ROBOT OFF');
  assert.match(x.nodes.cap.textContent, /off or off the network/);
  assert.doesNotMatch(x.nodes.cap.textContent, /USB/);
  assert.equal(x.nodes.cam.classList.contains('unavailable'), true);
  // Nothing on this page can move the robot yet.
  assert.equal(x.requests.filter(q => q.options.method === 'POST').length, 0);
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


test('a route gets a start dot and a single point does not', () => {
  const icons = [];
  const layer = {addTo() {}, on() {}};
  const L = {map: () => ({remove() {}, setView() {}, fitBounds() {}}), tileLayer: () => layer,
    marker: (ll, opts) => { icons.push(opts.icon.className); return layer; },
    polyline: () => layer, divIcon: (o) => o, control: {zoom: () => layer}};
  const classes = new Set();
  const mapEl = {hidden: false, classList: {toggle: (n, on) => on ? classes.add(n) : classes.delete(n), contains: n => classes.has(n)}};
  let points = '[{"lat":30,"lon":-97},{"lat":30.001,"lon":-97.001}]';
  const document = {getElementById: id => id === 'map-points' ? {textContent: points} : id === 'kona-map' ? mapEl : null};
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), {window,document,L});
  assert.deepEqual(icons, ['kona-map-start', 'kona-map-marker']);
  icons.length = 0; points = '[{"lat":30,"lon":-97}]';
  window.KonaMap.init();
  assert.deepEqual(icons, ['kona-map-marker'], 'one point is a place, not a route');
});


// The camera's own zoom: a pinch scales about the fingers, a drag pans
// while zoomed and never past the edge, a double-tap jumps in and out.
function touch(x, y) { return {clientX: x, clientY: y}; }
function pinchFrom(x, d1, d2) {
  x.camFrame.events.touchstart({touches: [touch(100, 100), touch(100 + d1, 100)], target: element(), preventDefault() {}});
  x.camFrame.events.touchmove({touches: [touch(100, 100), touch(100 + d2, 100)], target: element(), preventDefault() {}});
  x.camFrame.events.touchend({touches: []});
}

test('a pinch zooms the picture about the fingers and shows the level', () => {
  const x = setup('camera.js');
  pinchFrom(x, 100, 200);
  const z = x.window.KonaZoom.get();
  assert.equal(z.s, 2);
  // The spot that was under the fingers' midpoint (150 in the frame) is
  // still under it after they spread and drifted right to 200: image
  // coordinate 150 at 2x sits at x + 300, so x = -100. y did not move.
  assert.equal(z.x, -100);
  assert.equal(z.y, -100);
  assert.match(x.nodes.cam.style.transform, /scale\(2\.000\)/);
  assert.equal(x.nodes['zoom-level'].hidden, false);
  assert.equal(x.nodes['zoom-level'].textContent, '2\u00d7');
  assert.equal(x.camFrame.classList.contains('zoomed'), true);
});

test('zoom is capped, and a near-1x pinch snaps back to exactly 1x with no offset', () => {
  const x = setup('camera.js');
  pinchFrom(x, 50, 500);
  assert.equal(x.window.KonaZoom.get().s, 4, 'ZOOM_MAX');
  x.window.KonaZoom.reset();
  pinchFrom(x, 100, 104);
  const z = {...x.window.KonaZoom.get()};  // spread: vm objects have another realm's prototype
  assert.deepEqual(z, {s: 1, x: 0, y: 0});
  assert.equal(x.nodes.cam.style.transform, '');
  assert.equal(x.nodes['zoom-level'].hidden, true);
});

test('a drag while zoomed pans but never shows a gap past the picture edge', () => {
  const x = setup('camera.js');
  pinchFrom(x, 100, 200);           // 2x, offset (-100, -100)
  x.camFrame.events.touchstart({touches: [touch(200, 100)], target: element(), preventDefault() {}});
  x.camFrame.events.touchmove({touches: [touch(120, 60)], target: element(), preventDefault() {}});
  x.camFrame.events.touchend({touches: []});
  let z = x.window.KonaZoom.get();
  assert.equal(z.x, -180, 'dragged 80px left');
  assert.equal(z.y, -140);
  // A second drag starting where the first did is two drags, not a
  // double-tap: it moved. Far past the edge it clamps to (1 - s) * frame.
  x.camFrame.events.touchstart({touches: [touch(200, 100)], target: element(), preventDefault() {}});
  x.camFrame.events.touchmove({touches: [touch(-900, -900)], target: element(), preventDefault() {}});
  x.camFrame.events.touchend({touches: []});
  z = x.window.KonaZoom.get();
  assert.deepEqual([z.x, z.y], [-400, -225]);
});

test('a drag at 1x does nothing to the picture, so the page can still scroll', () => {
  const x = setup('camera.js');
  let prevented = 0;
  x.camFrame.events.touchstart({touches: [touch(200, 100)], target: element(), preventDefault() { prevented++; }});
  x.camFrame.events.touchmove({touches: [touch(120, 60)], target: element(), preventDefault() { prevented++; }});
  assert.equal(prevented, 0);
  assert.equal(x.nodes.cam.style.transform, '');
});

test('a double-tap jumps in on the spot and a second one jumps back out', () => {
  const x = setup('camera.js');
  const tap = () => {
    x.camFrame.events.touchstart({touches: [touch(300, 50)], target: element(), preventDefault() {}});
    x.camFrame.events.touchend({touches: []});
  };
  tap(); tap();
  let z = x.window.KonaZoom.get();
  assert.equal(z.s, 2.5);
  // (300, 50) stays under the finger: 300 - 300 * 2.5 = -450, clamped to -400 wide... but
  // -450 < (1 - 2.5) * 400 = -600? No: -450 > -600, so it stands.
  assert.equal(z.x, -450);
  assert.equal(z.y, -75);
  tap(); tap();
  assert.deepEqual({...x.window.KonaZoom.get()}, {s: 1, x: 0, y: 0});
});

test('a touch on the shutter is a button press, not a zoom gesture', () => {
  const x = setup('camera.js');
  const button = element(); button.closest = sel => sel === 'button' ? button : null;
  const tap = () => {
    x.camFrame.events.touchstart({touches: [touch(300, 50)], target: button, preventDefault() {}});
    x.camFrame.events.touchend({touches: []});
  };
  tap(); tap();
  assert.equal(x.window.KonaZoom.get().s, 1);
});

// ---------------------------------------------------------------------------
// Landscape drive mode. The robot holds a motor duty until another arrives,
// so what matters most here is not that the stick drives -- it is that every
// way of letting go ends in a stop, and that a stop which did not land is
// impossible to miss.

function telemetry(x, extra = {}) {
  const poll = x.requests.filter(q => q.url === '/robot/telemetry').pop();
  assert.ok(poll, 'no telemetry poll in flight');
  poll.resolve(response({
    battery_v: 8.01, sonar_mm: 412, driving: false, demo: null,
    last_command_age_ms: null, low_battery: false, battery_age_ms: 300,
    demo_detection: true, sonar_usable: true, min_duty: 25, max_duty: 55, ...extra
  }));
  return settle();
}
const drives = x => x.requests.filter(q => q.url === '/robot/drive');
// The drive loop is an interval; a stop clears it. Its absence is the proof
// that nothing is still being sent, and is stronger than a request count.
const looping = x => [...x.intervals.values()].some(t => t.delay === 200);
const stops = x => x.requests.filter(q => q.url === '/robot/stop');

async function ready(extra = {}) {
  const x = setup('drive.js');
  await telemetry(x, extra);
  return x;
}
function press(x, clientX, clientY) {
  x.nodes.stick.events.pointerdown({pointerId: 1, clientX, clientY, preventDefault() {}});
}

test('nothing can drive until the robot has actually answered', async () => {
  const x = setup('drive.js');
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'true');
  assert.equal(x.nodes['rot-left'].disabled, true);
  press(x, 64, 8);
  assert.equal(drives(x).length, 0, 'a disabled stick sends nothing');
  await telemetry(x);
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'false');
  assert.equal(x.nodes['rot-left'].disabled, false);
});

test('the stick drives while a thumb is down and stops the moment it lifts', async () => {
  const x = await ready();
  press(x, 64, 8);  // centre is (64,64) and the radius is 56: full forward
  assert.equal(drives(x).length, 1);
  // Slow is the default until the directions have been checked on a stand,
  // so full deflection asks for 0.4, and sideways is strafe, not turn.
  assert.equal(drives(x)[0].options.body, 'vx=0.400&vy=0.000&omega=0.000');
  drives(x)[0].resolve(response({ok: true})); await settle();
  // It keeps refreshing on its own while held -- that is what stops the
  // gateway's watchdog from firing mid-drive.
  x.tickEvery(200);
  assert.equal(drives(x).length, 2);
  drives(x)[1].resolve(response({ok: true})); await settle();
  assert.equal(looping(x), true, 'the refresh loop is running while held');
  x.nodes.stick.events.pointerup({pointerId: 1});
  assert.equal(stops(x).length, 1, 'letting go is an explicit stop, not just silence');
  assert.equal(looping(x), false, 'and the loop is gone, not merely idle');
});

test('a thumb pushed into a corner asks for a direction, not for 1.41x', async () => {
  const x = await ready();
  press(x, 64 + 56, 64 - 56);  // hard diagonal
  const body = drives(x)[0].options.body;
  const [vx, vy] = [/vx=(-?[\d.]+)/, /vy=(-?[\d.]+)/].map(re => parseFloat(body.match(re)[1]));
  assert.ok(Math.abs(Math.hypot(vx, vy) - 0.4) < 0.002, `clamped to the disk, got ${body}`);
  assert.ok(vx > 0 && vy < 0, 'forward and to the right');
});

test('only one command is ever in flight, however fast the ticks come', async () => {
  const x = await ready();
  press(x, 64, 8);
  x.tickEvery(200); x.tickEvery(200); x.tickEvery(200);
  assert.equal(drives(x).length, 1, 'the tick skips while one is pending');
  drives(x)[0].resolve(response({ok: true})); await settle();
  x.tickEvery(200);
  assert.equal(drives(x).length, 2);
});

for (const [name, fire] of [
  ['a lost pointer', x => x.nodes.stick.events.pointercancel({pointerId: 1})],
  ['the window losing focus', x => x.window.events.blur()],
  ['the page being hidden', x => { x.document.hidden = true; x.document.events.visibilitychange(); }],
  ['the phone being turned back to portrait', x => x.window.events.orientationchange()],
  ['Escape', x => x.document.events.keydown({key: 'Escape'})],
  ['the STOP button', x => x.nodes.estop.events.click()],
  // The alarm carries its own STOP because it is the only control that
  // exists in portrait, where `.drive` is display:none -- and portrait is
  // where the alarm is likeliest to be raised, since rotating upright is
  // itself a stop. A dead button there would be the worst of both.
  ['the alarm\u2019s own STOP', x => x.nodes['estop-alarm'].events.click()]
]) {
  test(`${name} stops the robot`, async () => {
    const x = await ready();
    press(x, 64, 8);
    assert.equal(drives(x).length, 1);
    fire(x);
    assert.equal(stops(x).length, 1, `${name} did not send a stop`);
    assert.equal(looping(x), false, 'and nothing is still being sent');
  });
}

test('the page being torn down sends a stop that outlives the fetch', async () => {
  const x = await ready();
  press(x, 64, 8);
  x.window.events.pagehide();
  // A fetch dies with the page; a beacon does not. The watchdog on the Pi
  // is the backstop if even this fails to land.
  assert.deepEqual(x.beacons, ['/robot/stop']);
});

test('a stop that did not land is shouted about and retried, never swallowed', async () => {
  const x = await ready();
  press(x, 64, 8);
  x.nodes.estop.events.click();
  stops(x)[0].resolve(response({error: 'The robot did not answer.'}, {ok: false, status: 503}));
  await settle();
  assert.equal(x.nodes.shout.hidden, false);
  assert.match(x.nodes['shout-text'].textContent, /did not reach the robot/);
  x.fire(700);
  assert.equal(stops(x).length, 2, 'it keeps trying: the robot may still be moving');
  stops(x)[1].resolve(response({ok: true})); await settle();
  assert.equal(x.nodes.shout.hidden, true, 'and goes quiet once one lands');
});

test('the robot may still be moving, and the screen says so', async () => {
  // stop_owed means the gateway has never had an all-zero acknowledged. It is
  // TRUE all through a normal drive, so on its own it is not news.
  const x = await ready({stop_owed: true, driving: true});
  assert.equal(x.nodes.shout.hidden, true, 'driving with a live command is not an alarm');
  // Nothing commanded, and still no confirmed stop: that is the runaway window.
  x.tickEvery(1000);
  await telemetry(x, {stop_owed: true, driving: false});
  assert.equal(x.nodes.shout.hidden, false);
  assert.match(x.nodes['shout-text'].textContent, /may still be moving/);
  x.tickEvery(1000);
  await telemetry(x, {stop_owed: false, driving: false});
  assert.equal(x.nodes.shout.hidden, true, 'and it clears when the gateway says so');
});

test('a gateway alarm is not erased by our own stop succeeding', async () => {
  const x = await ready({stop_owed: true, driving: false});
  assert.match(x.nodes['shout-text'].textContent, /may still be moving/);
  x.nodes.estop.events.click();
  stops(x)[0].resolve(response({ok: true})); await settle();
  // Our stop returned 200, but the gateway still has not confirmed a zero.
  // Believing our own request over its telemetry is how you get a silent page
  // and a moving robot.
  assert.equal(x.nodes.shout.hidden, false);
  assert.match(x.nodes['shout-text'].textContent, /may still be moving/);
});

test('drive mode calls the picture stale far sooner than the dog camera does', async () => {
  const x = await ready();
  assert.equal(x.nodes.picture.textContent, 'waiting', 'no frame has arrived yet');
  // poll.js hands a live frame up through onFrame.
  const shot = x.requests.filter(q => q.url.indexOf('/snapshot.jpg') === 0).pop();
  shot.resolve(frame('live', 1)); await settle();
  x.tickEvery(250);
  assert.equal(x.nodes.picture.textContent, 'live');
  // The hub would not call this stale for three seconds. Steering by it, the
  // truth is due much sooner than that.
  x.advance(900);
  x.tickEvery(250);
  assert.equal(x.nodes.picture.textContent, '0.9 s behind');
  assert.equal(x.nodes.picture.className, 'v bad');
});

test('a stop failure leads with the fact and keeps the reason after it', async () => {
  const x = await ready();
  x.nodes.estop.events.click();
  stops(x)[0].resolve(response(
    {error: "The robot's own software is not answering. Turn it off and on.", reason: 'unreachable'},
    {ok: false, status: 503}
  ));
  await settle();
  const said = x.nodes['shout-text'].textContent;
  assert.match(said, /did not reach the robot/, 'the danger must not be replaced by the diagnosis');
  assert.match(said, /not answering/, 'and the reason still comes with it');
});

test('a battery nobody could read is unknown, not flat, and does not block driving', async () => {
  // The gateway's own reads come back empty routinely. Refusing on a missed
  // read would look identical to a dead cell and make the robot unusable.
  const x = await ready({battery_v: null, sonar_mm: null});
  assert.equal(x.nodes.volts.textContent, 'unknown');
  assert.equal(x.nodes.sonar.textContent, 'unknown');
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'false');
  press(x, 64, 8);
  assert.equal(drives(x).length, 1);
});

test('a flat battery greys the controls out and says why', async () => {
  const x = await ready({battery_v: 6.8, low_battery: true});
  assert.equal(x.nodes.volts.textContent, '6.80 V');
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'true');
  press(x, 64, 8);
  assert.equal(drives(x).length, 0);
});

test('a guard the robot cannot run is said out loud, not assumed', async () => {
  // demo_detection false means the robot's own GetRunningFunc is unpatched,
  // so the gateway cannot tell whether a built-in demo is driving.
  const x = await ready({demo_detection: false});
  assert.equal(x.nodes.note.hidden, false);
  assert.match(x.nodes.note.textContent, /cannot tell whether a built-in demo/);
});

test('the strip stops claiming a reading once the robot goes quiet', async () => {
  const x = await ready();
  assert.equal(x.nodes.volts.textContent, '8.01 V');
  x.tickEvery(1000);
  x.requests.filter(q => q.url === '/robot/telemetry').pop()
    .reject(new Error('network'));
  await settle();
  // One unlucky poll is not a verdict, so the reading still stands.
  assert.equal(x.nodes.volts.textContent, '8.01 V');
  // Seconds of silence are.
  x.advance(4000);
  x.tickEvery(3000);
  assert.equal(x.nodes.volts.textContent, 'unknown');
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'true');
});

test('the speed control says what it caps, not how fast the robot feels', async () => {
  // It used to say "Slow". The gateway then began lifting every command above
  // the motors' stiction floor, so a 0.4 stick asks for duty 37 on this robot
  // -- above what used to be full throttle. The word stopped being true.
  const x = await ready();
  assert.equal(x.nodes.speed.textContent, 'Speed 40%');
  assert.match(x.nodes.speed.getAttribute('aria-label'), /motor duty 37/,
    "the duty is the robot's own number, read from telemetry, never hardcoded");
  x.nodes.speed.events.click();
  assert.equal(x.nodes.speed.getAttribute('aria-pressed'), 'true');
  assert.equal(x.nodes.speed.textContent, 'Speed 100%');
  assert.match(x.nodes.speed.getAttribute('aria-label'), /motor duty 55/);
  press(x, 64, 8);
  assert.equal(drives(x)[0].options.body, 'vx=1.000&vy=0.000&omega=0.000');
});

test('a duty range this page has not been told is not invented', async () => {
  // min_duty/max_duty are environment variables on the Pi, different per
  // robot. Absent them the pill still states its own cap and claims nothing
  // about motors.
  const x = setup('drive.js');
  await telemetry(x, {min_duty: undefined, max_duty: undefined});
  assert.equal(x.nodes.speed.getAttribute('aria-label'), null,
    'no duty claim before the robot has reported its range');
});

test('a distance sensor that cannot be read is said out loud', async () => {
  // Same family as demo_detection: a guard that cannot run must not look like
  // a guard that is running and finding nothing in the way.
  const x = await ready({sonar_usable: false});
  assert.equal(x.nodes.note.hidden, false);
  assert.match(x.nodes.note.textContent, /obstacle guard is off/);
  // And it does not block driving -- reverse, strafe and rotate are how you
  // get out of a corner, which is the gateway's own reasoning.
  assert.equal(x.nodes.stick.getAttribute('aria-disabled'), 'false');
});

test('rotating is a turn on the spot, and releasing it stops too', async () => {
  const x = await ready();
  x.nodes['rot-left'].events.pointerdown({preventDefault() {}});
  // POSITIVE for left. The gateway's frame is "omega counter-clockwise"
  // (robot_gateway.py, wheel_duties) and counter-clockwise is a left turn.
  // This test asserted -0.400 until 2026-09-15, when the first real drive
  // showed the two buttons swapped -- the test had been pinning our bug.
  assert.equal(drives(x)[0].options.body, 'vx=0.000&vy=0.000&omega=0.400');
  x.nodes['rot-left'].events.pointerup({});
  assert.equal(stops(x).length, 1);
});

test('the two rotate buttons send opposite signs, left positive', async () => {
  const left = await ready();
  left.nodes['rot-left'].events.pointerdown({preventDefault() {}});
  const right = await ready();
  right.nodes['rot-right'].events.pointerdown({preventDefault() {}});
  assert.equal(drives(left)[0].options.body, 'vx=0.000&vy=0.000&omega=0.400');
  assert.equal(drives(right)[0].options.body, 'vx=0.000&vy=0.000&omega=-0.400');
});

test('a drive the server refused lets go rather than hammering the robot', async () => {
  const x = await ready();
  press(x, 64, 8);
  drives(x)[0].resolve(response(
    {error: "A built-in demo is driving the robot. Stop the demo first.", reason: 'demo_running'},
    {ok: false, status: 409}
  ));
  await settle();
  assert.equal(x.nodes.shout.hidden, false);
  assert.match(x.nodes['shout-text'].textContent, /demo/);
  assert.equal(looping(x), false, 'the watchdog stops it; we do not hammer the robot');
});
