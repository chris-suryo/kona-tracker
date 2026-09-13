// The location map. Points come from a JSON data block the server renders
// (a <script type="application/json"> is data, not code, so it needs no
// CSP nonce) and init is a named function so a refreshed page can call it
// again after its markup has been swapped.
(function () {
  var activeMap = null;
  // The route green used to be the literal #5F8A48 -- which is the *dark*
  // theme's --t3, hardcoded, the one place in the app that bypassed the
  // token system. It never changed with the theme, so a light-theme viewer
  // got a dark-theme green on unfiltered tiles. Read the token instead.
  function ink(name, fallback) {
    try {
      var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || fallback;
    } catch (e) { return fallback; }
  }

  function destroy() {
    if (activeMap) { activeMap.remove(); activeMap = null; }
  }
  function init() {
    destroy();
    var block = document.getElementById('map-points');
    var el = document.getElementById('kona-map');
    if (!block || !el || typeof L === 'undefined') { return; }
    var points;
    try { points = JSON.parse(block.textContent); } catch (e) { return; }
    if (!points || !points.length) { return; }
    var latlngs = points.map(function (p) { return [p.lat, p.lon]; });
    var map = L.map(el, { zoomControl: false, scrollWheelZoom: false });
    activeMap = map;
    // Tile settings come from a second JSON data block, for the same reason
    // the points do: the CSP is script-src 'self', so nothing may be inlined
    // as code. It also keeps the Stadia key out of this file and out of git.
    var cfg = { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maxZoom: 19, dark: false,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' };
    var cfgBlock = document.getElementById('map-config');
    if (cfgBlock) {
      try {
        var parsed = JSON.parse(cfgBlock.textContent);
        if (parsed && parsed.url) { cfg = parsed; }
      } catch (e) { /* keep the OSM default rather than render nothing */ }
    }
    // Alidade Smooth Dark is already dark; the CSS filter that fakes a dark
    // basemap must not also run, or it darkens twice.
    el.classList.toggle('tiles-dark', !!cfg.dark);
    // Deliberately no per-layer `referrerPolicy`, though the frontend branch
    // added one for OSM's usage policy. An element-level policy overrides the
    // page's `Referrer-Policy: no-referrer`, so it would send this
    // deployment's hostname -- a Cloudflare tunnel URL included -- to the tile
    // host, on the default OSM path as well as Stadia. OSM's ask is a policy
    // nicety and tiles load without it; the hostname leak is concrete. It
    // would buy something real only under domain-based tile auth, which needs
    // a stable hostname the quick tunnel does not give us. If that ever
    // changes, add it back and fix the comment above SECURITY_HEADERS too.
    var tiles = L.tileLayer(cfg.url, {
      maxZoom: cfg.maxZoom || 19,
      attribution: cfg.attribution
    });
    // From the frontend branch: a dead tile server should say so rather than
    // leave a blank grey rectangle that reads as a broken app. But a single
    // failed tile is not a dead server -- a retina variant that does not
    // exist, one request lost on a phone changing cells -- and hiding a map
    // that has already drawn is worse than the grey rectangle this guards
    // against. It showed up exactly that way on 2026-09-12: a full map on
    // screen with "Map unavailable" printed underneath it, which is the page
    // contradicting itself. So the message is for the case it was written
    // for and no other: errors before any tile has arrived. If one does
    // arrive later the map comes back, and Leaflet is told to re-measure,
    // because it sized itself while the element was hidden.
    var unavailable = document.getElementById('map-unavailable');
    var arrived = 0;
    tiles.on('tileerror', function () {
      if (arrived > 0) { return; }
      el.hidden = true;
      if (unavailable) { unavailable.hidden = false; }
    });
    tiles.on('tileload', function () {
      arrived += 1;
      if (!el.hidden) { return; }
      el.hidden = false;
      if (unavailable) { unavailable.hidden = true; }
      map.invalidateSize();
    });
    tiles.addTo(map);
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: ink('--t4', '#5F8A48'), weight: 5, opacity: .9 }).addTo(map);
      map.fitBounds(latlngs, { padding: [28, 28], maxZoom: 17 });
    } else {
      map.setView(latlngs[0], 16);
    }
    // A finished walk has two ends and they matter: a dot where the route
    // begins, the K where it ended. One point is a place, not a route.
    if (latlngs.length > 1) {
      L.marker(latlngs[0], {
        icon: L.divIcon({ className: 'kona-map-start', html: '<span></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
        interactive: false
      }).addTo(map);
    }
    var last = points[points.length - 1];
    if (last.accuracy) {
      L.circle([last.lat, last.lon], {
        radius: last.accuracy, color: ink('--t4', '#5F8A48'), weight: 1, fillOpacity: .12
      }).addTo(map);
    }
    L.marker([last.lat, last.lon], {
      icon: L.divIcon({ className: 'kona-map-marker', html: '<span>K</span>', iconSize: [34, 34], iconAnchor: [17, 17] })
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
  }
  window.KonaMap = { init: init, destroy: destroy };
  init();
})();
