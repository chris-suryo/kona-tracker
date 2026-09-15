// The location map. Points come from a JSON data block the server renders
// (a <script type="application/json"> is data, not code, so it needs no
// CSP nonce) and init is a named function so a refreshed page can call it
// again after its markup has been swapped.
(function () {
  var activeMap = null;
  var base = null;
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
    // The tile handle first: it holds a matchMedia listener and a
    // MutationObserver pointed at a map that is about to stop existing.
    if (base) { base.destroy(); base = null; }
    if (activeMap) { activeMap.remove(); activeMap = null; }
  }
  function init() {
    destroy();
    var block = document.getElementById('map-points');
    var el = document.getElementById('kona-map');
    if (!block || !el || typeof L === 'undefined' || !window.KonaMapBase) { return; }
    var points;
    try { points = JSON.parse(block.textContent); } catch (e) { return; }
    if (!points || !points.length) { return; }
    var latlngs = points.map(function (p) { return [p.lat, p.lon]; });
    var map = L.map(el, { zoomControl: false, scrollWheelZoom: false });
    activeMap = map;
    // The basemap, its theme and the "Map unavailable" message all live in
    // map_base.js, shared with the live map so the two cannot drift apart.
    base = window.KonaMapBase.tiles({
      map: map,
      host: el,
      unavailable: document.getElementById('map-unavailable')
    });
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: ink('--t4', '#5F8A48'), weight: 5, opacity: .9 }).addTo(map);
      map.fitBounds(latlngs, { padding: [28, 28], maxZoom: 17 });
    } else {
      map.setView(latlngs[0], 16);
    }
    // A finished walk has two ends and they matter: a dot where the route
    // begins, her face where it ended. One point is a place, not a route.
    if (latlngs.length > 1) {
      L.marker(latlngs[0], {
        icon: window.KonaMapBase.startIcon(),
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
      icon: window.KonaMapBase.hereIcon()
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
  }
  window.KonaMap = { init: init, destroy: destroy };
  init();
})();
