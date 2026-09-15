// The parts both maps share: the basemap, and the marker that says "here".
//
// **Why this file exists.** There are two maps -- the small one on Activity
// and the walk page (`map.js`), and the live one (`map_live.js`) -- and they
// had drawn the same tile layer and the same marker with two copies of the
// same twenty lines. On 2026-09-15 that cost a real bug: the route green was
// fixed in one and not the other, and nobody noticed for a day because you
// only ever look at one map at a time. Two copies of a rule is a rule that
// will drift; the theme tokens in app.css have the same problem and are
// pinned by a test for exactly this reason.
//
// **Why the theme is resolved here and not on the server.** Since the Light
// / Dark control landed, the choice lives in `localStorage` and is applied by
// `theme.js` before the page paints. The server renders the page and cannot
// know which one a phone will choose, so it sends *both* basemaps in the
// `#map-config` block and the browser picks. Getting this wrong is not
// subtle: choosing Light gave a bright page sitting on a black map, which is
// exactly what Chris saw.
(function () {
  'use strict';

  var DEFAULT = {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    maxZoom: 19,
    dark: false,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  };

  // Read once per attach. A missing or unparseable block means OSM rather
  // than no map: a basemap we did not configure is better than a grey box.
  function config() {
    var block = document.getElementById('map-config');
    var both = { light: DEFAULT, dark: DEFAULT };
    if (!block) { return both; }
    var parsed;
    try { parsed = JSON.parse(block.textContent); } catch (e) { return both; }
    if (!parsed) { return both; }
    // Tolerates the single-layer shape this block used to have, so a page
    // served by an older build does not lose its map mid-deploy.
    if (parsed.url) { return { light: parsed, dark: parsed }; }
    return {
      light: parsed.light && parsed.light.url ? parsed.light : DEFAULT,
      dark: parsed.dark && parsed.dark.url ? parsed.dark : DEFAULT
    };
  }

  // The same resolution order app.css uses: an explicit choice wins over the
  // phone, and no attribute means follow the phone. Kept in step with the
  // `:root:not([data-theme="light"])` guard by tests/test_theme.py.
  function wantsDark() {
    var chosen = document.documentElement.getAttribute('data-theme');
    if (chosen === 'dark') { return true; }
    if (chosen === 'light') { return false; }
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    } catch (e) {
      return false;
    }
  }

  // The marker for where she is now. Her photo when Fi has one, the initial
  // when it does not -- the same `data-optional` contract the avatar in the
  // header uses, so the broken-image fallback in app.js covers this too. It
  // has to be that listener and not an inline `onerror=`: the page sends
  // `script-src 'self'` and an inline handler simply never runs.
  function hereIcon() {
    return L.divIcon({
      className: 'kona-map-marker',
      html: '<span>K<img src="/avatar.jpg" alt="" data-optional></span>',
      iconSize: [34, 34],
      iconAnchor: [17, 17]
    });
  }

  function startIcon() {
    return L.divIcon({
      className: 'kona-map-start',
      html: '<span></span>',
      iconSize: [14, 14],
      iconAnchor: [7, 7]
    });
  }

  // Adds the basemap to `map`, and keeps it in step with the theme for as
  // long as the map lives. Returns a handle whose `destroy()` unsubscribes;
  // forgetting it would leave a listener holding a removed map.
  function tiles(opts) {
    var map = opts.map;
    var host = opts.host;
    var unavailable = opts.unavailable || null;
    var both = config();
    var layer = null;
    var dark = null;
    // Deliberately outside build(): a theme swap makes a brand-new layer with
    // no tiles yet, and if this reset with it, changing theme on a working
    // map could flash "Map unavailable" over a map that is plainly fine.
    var arrived = 0;

    function build(useDark) {
      var cfg = useDark ? both.dark : both.light;
      dark = useDark;
      // `.tiles-dark` suppresses the CSS filter that fakes a dark basemap out
      // of light raster tiles. Alidade Smooth Dark is already dark and
      // filtering it darkens it twice; OSM has no dark raster, so it stays
      // off there and the filter does the work.
      host.classList.toggle('tiles-dark', !!cfg.dark);
      // Deliberately no per-layer `referrerPolicy`, though an earlier branch
      // added one for OSM's usage policy. An element-level policy overrides
      // the page's `Referrer-Policy: no-referrer`, so it would send this
      // deployment's hostname -- a Cloudflare tunnel URL included -- to the
      // tile host. OSM's ask is a policy nicety and tiles load without it;
      // the hostname leak is concrete.
      var made = L.tileLayer(cfg.url, { maxZoom: cfg.maxZoom || 19, attribution: cfg.attribution });
      // A dead tile server should say so rather than leave a blank grey
      // rectangle that reads as a broken app. But a single failed tile is not
      // a dead server -- a retina variant that does not exist, one request
      // lost on a phone changing cells -- and hiding a map that has already
      // drawn is worse than the grey rectangle this guards against. It showed
      // up exactly that way on 2026-09-12: a full map on screen with "Map
      // unavailable" printed underneath it, the page contradicting itself.
      made.on('tileerror', function () {
        if (arrived > 0) { return; }
        host.hidden = true;
        if (unavailable) { unavailable.hidden = false; }
      });
      made.on('tileload', function () {
        arrived += 1;
        if (!host.hidden) { return; }
        host.hidden = false;
        if (unavailable) { unavailable.hidden = true; }
        // It sized itself while the element was hidden, so it has to measure
        // again or it draws into a box of the wrong height.
        map.invalidateSize();
      });
      made.addTo(map);
      layer = made;
    }

    function resync() {
      var want = wantsDark();
      if (want === dark) { return; }
      var old = layer;
      build(want);
      // New layer first, old one second: removing first shows the page's own
      // background through the map for as long as the new tiles take.
      if (old) { map.removeLayer(old); }
    }

    build(wantsDark());

    // Two ways the answer can change while the page is open: the phone
    // crosses into its dark hours, or something sets data-theme (the Settings
    // control does, via KonaTheme.set). Watching the attribute rather than
    // listening for a custom event means any future path is covered too.
    var media = null;
    try {
      media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    } catch (e) { media = null; }
    if (media) {
      // addEventListener is the modern spelling; addListener is what older
      // WebKit has, and this app's whole audience is iPhones.
      if (media.addEventListener) { media.addEventListener('change', resync); }
      else if (media.addListener) { media.addListener(resync); }
    }
    var observer = null;
    if (window.MutationObserver) {
      observer = new window.MutationObserver(resync);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    }

    return {
      destroy: function () {
        if (observer) { observer.disconnect(); observer = null; }
        if (media) {
          if (media.removeEventListener) { media.removeEventListener('change', resync); }
          else if (media.removeListener) { media.removeListener(resync); }
          media = null;
        }
        layer = null;
      }
    };
  }

  window.KonaMapBase = { tiles: tiles, hereIcon: hereIcon, startIcon: startIcon, wantsDark: wantsDark };
})();
