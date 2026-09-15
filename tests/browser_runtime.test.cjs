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

function setup(script, preview = false, opts = {}) {
  const names = ['cam', 'cap', 'dot', 'livetxt', 'capture', 'capture-hint', 'activity-body', 'pull', 'zoom-level',
    'drive', 'stick', 'knob', 'estop', 'estop-alarm', 'speed', 'rot-left', 'rot-right', 'shout', 'shout-text', 'note',
    'volts', 'sonar', 'picture', 'wire', 'look', 'look-knob'];
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
  const window = {...element(), location: {href: '', protocol: 'http:', host: 'pi.local'}};
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
  // The drive socket. Absent unless a test asks for one, because "no
  // WebSocket in this environment" is exactly the fallback path that every
  // other drive test in this file is then exercising for free.
  const sockets = [];
  if (opts.websocket) {
    window.WebSocket = function (url) {
      this.url = url;
      this.readyState = 0;   // CONNECTING
      this.sent = [];
      this.send = frame => {
        if (this.readyState !== 1) { throw new Error('not open'); }
        this.sent.push(frame);
      };
      this.close = () => { this.readyState = 3; };
      sockets.push(this);
    };
  }
  // The two picture pages load poll.js first, as their templates do; the
  // loop lives there and camera.js / robot.js call window.KonaPoll.
  const scripts = ['camera.js', 'robot.js', 'drive.js'].includes(script) ? ['poll.js', script] : [script];
  scripts.forEach(s => vm.runInNewContext(fs.readFileSync(path.join(staticDir, s), 'utf8'), env));
  return {nodes, page, label, note, document, window, requests, timers, intervals, created, revoked, camFrame, beacons,
    files: () => files,
    socket: () => sockets[sockets.length - 1],
    // A socket the browser has finished opening: readyState 1 and onopen fired.
    openSocket() {
      const ws = sockets[sockets.length - 1];
      assert.ok(ws, 'no socket was created');
      ws.readyState = 1;
      ws.onopen();
      return ws;
    },
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
    },
    // The look throttle picks its own delay from how long ago it last sent,
    // so a test cannot name it. This fires the most recently scheduled
    // timeout -- Map keeps insertion order, and older pending timers from
    // poll.js and the telemetry loop are sitting in front of it.
    firePending() {
      const entry = [...timers].pop();
      assert.ok(entry, 'no timeout was pending');
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

// The two maps share map_base.js, which owns the tile layer, the theme it
// picks and the "Map unavailable" message. Loading it first is not optional:
// map.js returns early without window.KonaMapBase, exactly as it would in a
// browser where the file 404'd.
function mapContext(opts) {
  opts = opts || {};
  const handlers = {}, classes = new Set(), added = [], removed = [];
  const observers = [];
  let mapsRemoved = 0, resized = 0;
  const layer = () => ({addTo(m) { added.push(this); return this; },
                        on(name, fn) { handlers[name] = fn; return this; }});
  const map = {
    remove() { mapsRemoved++; }, setView() {}, fitBounds() {}, on() {},
    invalidateSize() { resized++; },
    removeLayer(l) { removed.push(l); }
  };
  const icons = [];
  const L = {map: () => map, tileLayer: () => layer(),
    marker: (_ll, o) => { icons.push(o.icon.className); return layer(); },
    polyline: () => layer(), circle: () => layer(),
    divIcon: spec => spec, control: {zoom: () => layer()}};
  const mapEl = {hidden: false,
    classList: {toggle: (n, on) => on ? classes.add(n) : classes.delete(n),
                contains: n => classes.has(n)}};
  const notice = {hidden: true};
  let mediaListener = null;
  const media = {
    matches: !!opts.phoneIsDark,
    addEventListener: (_n, fn) => { mediaListener = fn; },
    removeEventListener: () => { mediaListener = null; }
  };
  const root = {
    attr: opts.chosen || null,
    getAttribute(n) { return n === 'data-theme' ? this.attr : null; },
    setAttribute(n, v) { if (n === 'data-theme') { this.attr = v; fire(); } },
    removeAttribute(n) { if (n === 'data-theme') { this.attr = null; fire(); } }
  };
  function fire() { observers.forEach(fn => fn()); }
  const nodes = Object.assign({
    'map-points': {textContent: opts.points || '[{"lat":30,"lon":-97}]'},
    'kona-map': mapEl, 'map-unavailable': notice
  }, opts.config ? {'map-config': {textContent: opts.config}} : {});
  const document = {documentElement: root, getElementById: id => nodes[id] || null};
  const window = {
    matchMedia: () => media,
    MutationObserver: function (fn) {
      return {observe() { observers.push(fn); }, disconnect() {
        const i = observers.indexOf(fn); if (i >= 0) { observers.splice(i, 1); }
      }};
    }
  };
  const ctx = {window, document, L, getComputedStyle: () => ({getPropertyValue: () => ''})};
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map_base.js'),'utf8'), ctx);
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'map.js'),'utf8'), ctx);
  return {window, document, nodes, mapEl, notice, handlers, classes, root, media,
          added, removed, observers, icons,
          setPoints: v => { nodes['map-points'] = v ? {textContent: v} : null; },
          phoneGoesDark: () => { media.matches = true; if (mediaListener) { mediaListener(); } },
          mapsRemoved: () => mapsRemoved, resized: () => resized,
          tileUrls: () => added.filter(l => l.on).length};
}

const STADIA = JSON.stringify({
  light: {url: 'https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png?api_key=K',
          attribution: 'a', maxZoom: 20, dark: false},
  dark: {url: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png?api_key=K',
         attribution: 'a', maxZoom: 20, dark: true}
});

test('map init releases the previous Leaflet instance even when new points are absent', () => {
  // No #map-config on purpose: the OSM fallback must work when it is absent.
  const x = mapContext();
  x.window.KonaMap.init(); assert.equal(x.mapsRemoved(), 1);
  x.setPoints(null); x.window.KonaMap.init(); assert.equal(x.mapsRemoved(), 2);
  x.window.KonaMap.destroy(); assert.equal(x.mapsRemoved(), 2);
});

// A map on screen with "Map unavailable" printed under it is the page
// contradicting itself; that is what one failed tile used to produce.
test('one failed tile does not hide a map that has already drawn', () => {
  const x = mapContext();
  x.window.KonaMap.init();
  x.handlers.tileload();
  x.handlers.tileerror();
  assert.equal(x.mapEl.hidden, false, 'a drawn map stays drawn');
  assert.equal(x.notice.hidden, true);
});

test('a tile server that answers nothing says so, and recovers if it wakes up', () => {
  const x = mapContext();
  x.window.KonaMap.init();

  x.handlers.tileerror();
  assert.equal(x.mapEl.hidden, true);
  assert.equal(x.notice.hidden, false);

  x.handlers.tileload();
  assert.equal(x.mapEl.hidden, false);
  assert.equal(x.notice.hidden, true);
  assert.equal(x.resized(), 1, 'Leaflet sized itself while hidden and must re-measure');
});

// The bug this whole shape exists to prevent: choosing Light in Settings gave
// a bright page sitting on Alidade Smooth *Dark*, because the server picked
// the basemap and could not know what the browser had chosen.
test('an explicit light choice gets the light basemap even on a dark phone', () => {
  const x = mapContext({config: STADIA, chosen: 'light', phoneIsDark: true});
  x.window.KonaMap.init();
  assert.equal(x.classes.has('tiles-dark'), false,
    'light tiles may be filtered; suppressing the filter leaves a white map on a dark page');
});

test('an explicit dark choice suppresses the filter that would darken it twice', () => {
  const x = mapContext({config: STADIA, chosen: 'dark', phoneIsDark: false});
  x.window.KonaMap.init();
  assert.equal(x.classes.has('tiles-dark'), true);
});

test('with no choice made the phone decides', () => {
  assert.equal(mapContext({config: STADIA, phoneIsDark: true}).window.KonaMapBase.wantsDark(), true);
  assert.equal(mapContext({config: STADIA, phoneIsDark: false}).window.KonaMapBase.wantsDark(), false);
});

test('the basemap follows the theme changing while the page is open', () => {
  const x = mapContext({config: STADIA, phoneIsDark: false});
  x.window.KonaMap.init();
  assert.equal(x.classes.has('tiles-dark'), false);

  // The phone crossing into its dark hours, and then an explicit choice --
  // both have to reach the map, which is why map_base.js watches the media
  // query and the attribute rather than listening for one custom event.
  x.phoneGoesDark();
  assert.equal(x.classes.has('tiles-dark'), true, 'the phone went dark; the map did not follow');
  assert.equal(x.removed.length, 1, 'the old layer must be dropped, not stacked under the new one');

  x.root.setAttribute('data-theme', 'light');
  assert.equal(x.classes.has('tiles-dark'), false, 'choosing Light must beat a dark phone');
});

test('a theme swap never flashes "Map unavailable" over a map that is fine', () => {
  // The new layer starts with no tiles. If the arrived counter reset with it,
  // changing theme on a working map would hide it and print the error.
  const x = mapContext({config: STADIA, phoneIsDark: false});
  x.window.KonaMap.init();
  x.handlers.tileload();
  x.phoneGoesDark();
  x.handlers.tileerror();
  assert.equal(x.mapEl.hidden, false);
  assert.equal(x.notice.hidden, true);
});

test('destroy unsubscribes the theme listeners', () => {
  // They hold a reference to a map that is about to be removed; left
  // attached, the next theme change would add a tile layer to a dead map.
  const x = mapContext({config: STADIA});
  x.window.KonaMap.init();
  assert.equal(x.observers.length, 1);
  x.window.KonaMap.destroy();
  assert.equal(x.observers.length, 0);
});

test('the here-marker offers her photo and keeps the initial behind it', () => {
  // `data-optional` is the contract app.js removes a broken image by; an
  // inline onerror= would be silently dropped by `script-src 'self'`.
  const x = mapContext({config: STADIA});
  const icon = x.window.KonaMapBase.hereIcon();
  assert.match(icon.html, /src="\/avatar\.jpg"/);
  assert.match(icon.html, /data-optional/);
  assert.match(icon.html, /<span>K/, 'the initial must stay as the fallback');
});

test('an unparseable map-config falls back to OSM rather than drawing nothing', () => {
  const x = mapContext({config: '{not json'});
  x.window.KonaMap.init();
  assert.equal(x.classes.has('tiles-dark'), false);
  assert.equal(x.mapEl.hidden, false);
});


test('a route gets a start dot and a single point does not', () => {
  // map.js self-inits on load, so clear what that pass recorded first.
  const x = mapContext({points: '[{"lat":30,"lon":-97},{"lat":30.001,"lon":-97.001}]'});
  x.icons.length = 0;
  x.window.KonaMap.init();
  assert.deepEqual(x.icons, ['kona-map-start', 'kona-map-marker']);
  x.icons.length = 0;
  x.setPoints('[{"lat":30,"lon":-97}]');
  x.window.KonaMap.init();
  assert.deepEqual(x.icons, ['kona-map-marker'], 'one point is a place, not a route');
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

async function ready(extra = {}, opts = {}) {
  const x = setup('drive.js', false, opts);
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

// The robot's front lights. They are the one control that answers while the
// robot's own software is down (I2C 0x77, not the motor bus), so the thing
// worth testing is that the page never *claims* a state it was not told.
function ledContext() {
  const calls = [];
  let resolveNext = null;
  const nodes = {};
  function button(attrs) {
    const el = element();
    Object.assign(el.dataset, attrs);
    return el;
  }
  const off = button({ledOn: '0'}), on = button({ledOn: '1'});
  const swatches = [
    button({ledRgb: '255,255,255'}), button({ledRgb: '255,170,60'}),
    button({ledRgb: '120,220,90'})
  ];
  const section = element(), note = element();
  section.hidden = true;
  section.setAttribute('data-pending', '');
  section.querySelectorAll = sel => sel === '[data-led-on]' ? [off, on] : swatches;
  nodes['led-settings'] = section;
  nodes['led-note'] = note;
  const document = {...element(), getElementById: id => nodes[id] || null};
  const window = {...element()};
  const env = {
    document, window, console,
    fetch: (url, options = {}) => new Promise(resolve => {
      calls.push({url, method: options.method || 'GET', body: options.body});
      resolveNext = resolve;
    })
  };
  env.window = window;
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'led.js'),'utf8'), env);
  return {
    calls, section, note, off, on, swatches,
    answer: (body, ok = true) => {
      const r = resolveNext;
      resolveNext = null;
      r({ok, json: () => Promise.resolve(body)});
      return new Promise(res => setImmediate(res));
    },
    // A server that answered with something that is not JSON at all: a 500
    // page, a proxy's error, the login redirect's HTML.
    answerNotJson: (ok = false) => {
      const r = resolveNext;
      resolveNext = null;
      r({ok, json: () => Promise.reject(new SyntaxError(
        'Unexpected token \'I\', "Internal S"... is not valid JSON'))});
      return new Promise(res => setImmediate(res));
    }
  };
}

test('the light switch stays hidden until the robot has actually answered', async () => {
  const x = ledContext();
  assert.equal(x.section.hidden, true, 'a switch whose state we do not know must not be offered');
  await x.answer({on: false, r: 0, g: 255, b: 40});
  assert.equal(x.section.hidden, false);
  assert.equal(x.section.getAttribute('data-pending'), null);
});

test('four nulls read as unknown, never as off', async () => {
  // The gateway says nulls when nothing has set the lights since it started.
  // A demo may have left them lit; drawing a confident Off invents a fact.
  const x = ledContext();
  await x.answer({on: null, r: null, g: null, b: null});
  assert.equal(x.off.getAttribute('aria-pressed'), 'false');
  assert.equal(x.on.getAttribute('aria-pressed'), 'false');
  assert.match(x.note.textContent, /cannot say/);
});

test('a swatch is only current while the lights are actually on', async () => {
  const dark = ledContext();
  await dark.answer({on: false, r: 255, g: 255, b: 255});
  assert.equal(dark.swatches[0].getAttribute('aria-pressed'), 'false',
    'off with a remembered colour must not claim the robot is showing it');
  const lit = ledContext();
  await lit.answer({on: true, r: 255, g: 255, b: 255});
  assert.equal(lit.swatches[0].getAttribute('aria-pressed'), 'true');
});

test('the page draws from the answer, not from the press', async () => {
  // A toggle that flips on tap and then quietly fails teaches you to trust it.
  const x = ledContext();
  await x.answer({on: false, r: 255, g: 0, b: 0});
  x.on.events.click();
  assert.equal(x.on.getAttribute('aria-pressed'), 'false', 'not until the robot says so');
  await x.answer({on: true, r: 255, g: 0, b: 0});
  assert.equal(x.on.getAttribute('aria-pressed'), 'true');
});

test('picking a colour turns the lights on in the same request', async () => {
  // Setting a colour on lights that are off looks like a dead button: you
  // tap green and nothing on the robot changes.
  const x = ledContext();
  await x.answer({on: false, r: 0, g: 0, b: 0});
  x.swatches[1].events.click();
  const sent = x.calls[x.calls.length - 1];
  assert.equal(sent.method, 'POST');
  assert.equal(sent.body, 'on=true&r=255&g=170&b=60');
});

test('turning them off carries the colour so it survives the toggle', async () => {
  const x = ledContext();
  await x.answer({on: true, r: 120, g: 220, b: 90});
  x.off.events.click();
  assert.equal(x.calls[x.calls.length - 1].body, 'on=false&r=120&g=220&b=90');
});

test('turning on a robot that never told us a colour sends white, not black', async () => {
  // Black is indistinguishable from off. "On" that does nothing visible is
  // the worst possible answer to a press.
  const x = ledContext();
  await x.answer({on: null, r: null, g: null, b: null});
  x.on.events.click();
  assert.equal(x.calls[x.calls.length - 1].body, 'on=true&r=255&g=255&b=255');
});

test('a refusal disables the controls and shows the gateway own words', async () => {
  const x = ledContext();
  await x.answer({error: 'The robot did not answer (led_unavailable).'}, false);
  assert.equal(x.section.hidden, false, 'a section that vanishes reads as a feature never built');
  assert.equal(x.off.disabled, true);
  assert.equal(x.swatches[0].disabled, true);
  assert.match(x.note.textContent, /led_unavailable/);
});

// -- the drive socket ------------------------------------------------------
//
// The whole reason it exists: over HTTP the page holds one command in flight
// at a time, so on Chris's 700 ms LTE link it could only send ~1.5 commands a
// second against a 500 ms TTL, and the gateway's watchdog fired seven times in
// six seconds with the stick held down. A socket has no round trip in the send
// path. Everything here is about it staying strictly an optimisation.

async function wired(extra = {}) {
  const x = await ready(extra, {websocket: true});
  x.openSocket();
  return x;
}

test('with no WebSocket in the browser everything still drives over HTTP', async () => {
  // Not a hypothetical: the CSP is `connect-src 'self'`, and some Safari
  // versions have refused ws: under exactly that. The page must degrade to
  // the original path rather than become a set of dead controls.
  const x = await ready();
  press(x, 64, 8);
  assert.equal(drives(x).length, 1, 'no socket means the POST path carries it');
  assert.equal(x.nodes.wire.textContent, 'polling');
});

test('an open socket carries the command and no POST is made', async () => {
  const x = await wired();
  const before = drives(x).length;
  press(x, 64, 8);
  assert.equal(drives(x).length, before, 'the socket took it; nothing should be POSTed');
  assert.deepEqual(JSON.parse(x.socket().sent[0]), {vx: 0.4, vy: 0, omega: 0});
  assert.equal(x.nodes.wire.textContent, 'socket');
});

test('the socket is not gated by one-command-in-flight', async () => {
  // This is the entire performance claim. Over HTTP `sending` blocks the next
  // command until the last answers, which on a slow link is the bottleneck.
  const x = await wired();
  press(x, 64, 8);
  x.tickEvery(200);
  x.tickEvery(200);
  assert.equal(x.socket().sent.length, 3, 'a frame in flight must not block the next');
});

test('a socket that drops mid-drive falls back to POSTing, silently', async () => {
  // A closed socket is not worth shouting about: the HTTP path picks it
  // straight up and the person is mid-drive with a thumb down.
  const x = await wired();
  press(x, 64, 8);
  const before = drives(x).length;
  x.socket().readyState = 3;
  x.socket().onclose();
  assert.equal(x.nodes.wire.textContent, 'polling');
  x.tickEvery(200);
  assert.equal(drives(x).length, before + 1, 'the HTTP path did not take over');
  assert.equal(x.nodes.shout.hidden, true, 'a dropped socket is not an alarm');
});

test('an error frame lets go rather than hammering, same as a failed POST', async () => {
  const x = await wired();
  press(x, 64, 8);
  x.socket().onmessage({data: JSON.stringify(
    {ok: false, error: 'The robot battery is too low to drive.', reason: 'low_battery'})});
  assert.equal(x.nodes.shout.hidden, false);
  assert.match(x.nodes['shout-text'].textContent, /too low/);
  // Letting go means the send ticker is gone, not merely that the next tick
  // happens to send nothing: a cleared interval cannot be restarted by a
  // thumb that is still down.
  assert.equal([...x.intervals].some(([, t]) => t.delay === 200), false,
    'the send ticker survived a refusal');
});

test('a stop goes down the socket AND over HTTP, never only one', async () => {
  // The socket arrives first, without waiting for a round trip. The POST is
  // the one that can be watched landing, and a stop that was not confirmed is
  // the most dangerous state this page can be in.
  const x = await wired();
  press(x, 64, 8);
  x.nodes.stick.events.pointerup({pointerId: 1});
  assert.equal(x.socket().sent[x.socket().sent.length - 1], '{"stop":true}');
  assert.equal(stops(x).length, 1, 'the watched HTTP stop must still be sent');
});

test('a socket that never opens is never used', async () => {
  // readyState stays CONNECTING. Sending into it throws, and a thrown send
  // must not lose the command -- it falls through to the POST.
  const x = await ready({}, {websocket: true});
  assert.equal(x.nodes.wire.textContent, 'polling');
  press(x, 64, 8);
  assert.equal(drives(x).length, 1, 'a half-open socket swallowed the command');
});

// -- scrubbing a chart -----------------------------------------------------
//
// The readings are rendered by the server and cloned across, so what this
// file can get wrong is *which* one it shows. Off by one and the page states
// the wrong hour's number with total confidence.
// A minimum viable DOM node: enough of firstChild / appendChild /
// removeChild / cloneNode for chart_scrub.js to move children between two
// elements, which is the only DOM work it does.
function node(text) {
  const self = {
    kids: [], textContent: text || '',
    get firstChild() { return self.kids[0] || null; },
    // Reparents, as the real DOM does: appending a node that already has a
    // parent removes it from that parent first. A stub that only copied
    // would let a move-children loop pass here and hang in a browser.
    appendChild(child) {
      if (child.parent) { child.parent.removeChild(child); }
      child.parent = self;
      self.kids.push(child);
      return child;
    },
    removeChild(child) {
      const i = self.kids.indexOf(child);
      if (i >= 0) { self.kids.splice(i, 1); child.parent = null; }
      return child;
    },
    cloneNode() {
      const copy = node(self.textContent);
      self.kids.forEach(k => copy.appendChild(k.cloneNode()));
      return copy;
    }
  };
  return self;
}

function scrubContext(opts = {}) {
  const count = opts.count === undefined ? 4 : opts.count;
  const readingCount = opts.readingCount === undefined ? count : opts.readingCount;
  const entries = [];
  for (let i = 0; i < readingCount; i++) {
    const entry = node('');
    entry.appendChild(node('bucket ' + i));
    entries.push(entry);
  }
  const links = [];
  for (let i = 0; i < count; i++) {
    const a = element();
    // Four 40px columns starting at x=0.
    a.getBoundingClientRect = () => ({left: i * 40, right: (i + 1) * 40, top: 0, bottom: 100});
    links.push(a);
  }
  const selection = node('');
  const readings = {children: entries};
  const chart = element();
  chart.dataset.readings = 'the-readings';
  chart.getElementsByTagName = () => links;
  const section = element();
  section.querySelector = sel => sel === '.chart-selection' ? selection : null;
  chart.parentNode = section;
  const document = {
    ...element(),
    getElementById: id => id === 'the-readings' ? readings : null,
    querySelectorAll: () => [chart]
  };
  vm.runInNewContext(fs.readFileSync(path.join(staticDir,'chart_scrub.js'),'utf8'),
    {document, window: {...element()}, console});
  function fire(name, x) {
    const handler = chart.events[name];
    assert.ok(handler, `chart never listened for ${name}`);
    handler({clientX: x, pointerId: 1, cancelable: true, preventDefault() {}});
  }
  return {
    chart, links, selection, entries,
    attached: () => !!chart.events.pointerdown,
    shown: () => (selection.firstChild ? selection.firstChild.textContent : null),
    current: () => links.findIndex(a => a.getAttribute('aria-current') === 'true'),
    down: x => fire('pointerdown', x),
    move: x => fire('pointermove', x)
  };
}

test('a finger dragged across the chart moves the reading with it', () => {
  const x = scrubContext();
  x.down(20);
  assert.equal(x.shown(), 'bucket 0');
  x.move(60);
  assert.equal(x.shown(), 'bucket 1');
  x.move(140);
  assert.equal(x.shown(), 'bucket 3');
});

test('the current bar is marked as the reading moves, and only one is', () => {
  const x = scrubContext();
  x.down(20);
  assert.equal(x.current(), 0);
  x.move(100);
  assert.equal(x.current(), 2);
  assert.equal(x.links.filter(a => a.getAttribute('aria-current') === 'true').length, 1);
});

test('moving without a finger down changes nothing', () => {
  const x = scrubContext();
  x.move(100);
  assert.equal(x.shown(), null);
});

test('overshooting either end holds the end bar rather than losing the reading', () => {
  // A thumb that runs three pixels past the last bar has not stopped asking.
  const x = scrubContext();
  x.down(20);
  x.move(-30);
  assert.equal(x.shown(), 'bucket 0');
  x.move(9999);
  assert.equal(x.shown(), 'bucket 3');
});

test('a tap does not follow the link, because the reading is already showing', () => {
  const x = scrubContext();
  let defaulted = true;
  x.chart.events.click({cancelable: true, preventDefault() { defaulted = false; }});
  assert.equal(defaulted, false, 'a page load that changes nothing on screen');
});

test('focusing a bar with the keyboard brings its reading with it', () => {
  // Without this a keyboard user gets the focus ring and no number.
  const x = scrubContext();
  x.links[2].events.focus();
  assert.equal(x.shown(), 'bucket 2');
});

test('a readings list that does not match the bars disables the scrub entirely', () => {
  // Rather than scrub the wrong bucket. A page confidently showing the wrong
  // hour is worse than a page that still needs a tap and a reload.
  const x = scrubContext({count: 4, readingCount: 3});
  assert.equal(x.attached(), false, 'it attached to a list it could not trust');
  assert.equal(x.shown(), null);
});

test('a server that answers HTML does not put a JSON parse error on screen', async () => {
  // `.json()` rejects on a non-JSON body, and a failing server is exactly when
  // the body stops being JSON. Unguarded, that rejection WAS the message: a
  // screenshot on 2026-09-15 read `Unexpected token 'I', "Internal S"... is
  // not valid JSON` under the heading "Front lights".
  const x = ledContext();
  await x.answerNotJson();
  assert.doesNotMatch(x.note.textContent, /JSON|token/,
    'the browser is talking to the user instead of the page');
  assert.match(x.note.textContent, /robot/i);
  assert.equal(x.off.disabled, true);
});

test('coming back to the page reopens a socket that dropped while it was hidden', async () => {
  // iOS closes the socket when the phone locks. Without this the page spends
  // the rest of its life on the slow path, having downgraded silently at the
  // one moment nobody was looking -- and open-it, put-it-down, come-back is
  // the normal way drive mode gets used.
  const x = await wired();
  x.socket().readyState = 3;
  x.socket().onclose();
  assert.equal(x.nodes.wire.textContent, 'polling');
  const before = x.socket();
  x.document.events.visibilitychange();
  assert.notEqual(x.socket(), before, 'no new socket was opened');
  x.openSocket();
  assert.equal(x.nodes.wire.textContent, 'socket');
});

test('it does not open a second socket under a held thumb', async () => {
  // Two command streams into a robot, with the server's newest-wins rule
  // arbitrating a race this page started.
  const x = await wired();
  press(x, 64, 8);
  const before = x.socket();
  x.document.events.visibilitychange();
  assert.equal(x.socket(), before);
});

test('it does not stack sockets when one is already open', async () => {
  const x = await wired();
  const before = x.socket();
  x.document.events.visibilitychange();
  assert.equal(x.socket(), before);
});

// -- the look stick --------------------------------------------------------
//
// The second joystick Chris asked for twice. Its rules are deliberately the
// opposite of the drive stick's, which is the thing most likely to be "fixed"
// by someone reading only one of them.
function looks(x) { return x.requests.filter(r => r.url === '/robot/look'); }
function lookAt(x, clientX, clientY, id = 9) {
  x.nodes.look.events.pointerdown({pointerId: id, clientX, clientY, preventDefault() {}});
}

test('the camera does not recentre when you let go', async () => {
  // The whole difference from the drive stick. A servo holds where it is put,
  // and a camera that snapped back to level on every release would be useless
  // for looking around a room -- which is what this page is for.
  const x = await ready();
  lookAt(x, 100, 64);          // right of centre (the pad is 128 wide at 0,0)
  const moved = x.nodes['look-knob'].style.transform;
  assert.notEqual(moved, '', 'the knob did not move');
  x.nodes.look.events.pointerup({pointerId: 9});
  assert.equal(x.nodes['look-knob'].style.transform, moved,
    'it snapped back to centre, which is the drive stick rule and wrong here');
});

test('letting go of the look stick never stops the robot', async () => {
  // The drive stick's release is a stop. If these two ever share that path,
  // aiming the camera while driving would cut the throttle.
  const x = await ready();
  press(x, 64, 8);
  const stopsBefore = stops(x).length;
  lookAt(x, 100, 64);
  x.nodes.look.events.pointerup({pointerId: 9});
  assert.equal(stops(x).length, stopsBefore, 'looking around stopped the robot');
});

test('it sends absolute degrees, clamped to the servo limit', async () => {
  const x = await ready();
  // Far outside the pad: the unit-disk clamp then the degree clamp.
  lookAt(x, 9999, 64);
  x.firePending();
  const body = looks(x)[0].options.body;
  const pan = parseFloat(body.match(/pan_deg=(-?[\d.]+)/)[1]);
  assert.ok(pan <= 45 && pan >= 44.9, `pan was ${pan}; the servo limit is 45`);
});

test('a drag is throttled rather than one request per pointermove', async () => {
  // Five servo writes a second into an RPC server that handles one request at
  // a time and already carries the drive loop.
  const x = await ready();
  lookAt(x, 70, 64);
  for (let i = 0; i < 12; i++) {
    x.nodes.look.events.pointermove({pointerId: 9, clientX: 70 + i * 3, clientY: 64, preventDefault() {}});
  }
  assert.equal(looks(x).length, 0, 'it sent before the throttle even fired');
  x.firePending();
  assert.equal(looks(x).length, 1, 'twelve moves became more than one request');
});

test('a move smaller than the servo backlash is not sent at all', async () => {
  const x = await ready();
  lookAt(x, 70, 64);
  x.firePending();
  looks(x)[0].resolve(response({ok: true}));
  const after = looks(x).length;
  // One pixel is well under LOOK_EPSILON_DEG once scaled.
  x.nodes.look.events.pointermove({pointerId: 9, clientX: 70.4, clientY: 64, preventDefault() {}});
  assert.equal(looks(x).length, after, 'it asked the servo to move less than it can');
});

test('double-tapping the middle levels the camera', async () => {
  // The only way back: dragging to exactly zero by thumb is not a thing
  // anyone manages.
  const x = await ready();
  lookAt(x, 100, 30);
  assert.notEqual(x.nodes['look-knob'].style.transform, '');
  x.nodes.look.events.pointerup({pointerId: 9});
  lookAt(x, 64, 64, 10);
  lookAt(x, 64, 64, 11);   // within the 300ms window; the clock is stopped
  assert.equal(x.nodes['look-knob'].style.transform, '', 'it did not return to level');
});

test('a look that fails says so without letting go of the drive', async () => {
  // A camera that did not turn is a disappointment; a robot that did not stop
  // is a hazard. They must not share an error path.
  const x = await ready();
  press(x, 64, 8);
  lookAt(x, 100, 64);
  x.firePending();
  looks(x)[0].reject(new Error('The robot did not answer.'));
  await new Promise(r => setImmediate(r));
  assert.equal(x.nodes.shout.hidden, false, 'it failed silently');
  assert.ok([...x.intervals].some(([, t]) => t.delay === 200), 'it stopped driving over a camera error');
});

test('the look stick is disabled with everything else when the robot is not answering', async () => {
  // `/look` goes through the RPC server that owns the motors, unlike the LEDs.
  const x = setup('drive.js');
  assert.equal(x.nodes.look.getAttribute('aria-disabled'), 'true');
  lookAt(x, 100, 64);
  assert.equal(looks(x).length, 0, 'a disabled stick moved a servo');
  await telemetry(x);
  assert.equal(x.nodes.look.getAttribute('aria-disabled'), 'false');
});
