// The location map. Points come from a JSON data block the server renders
// (a <script type="application/json"> is data, not code, so it needs no
// CSP nonce) and init is a named function so a refreshed page can call it
// again after its markup has been swapped.
(function () {
  var activeMap = null;
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
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: '#5F8A48', weight: 5, opacity: .9 }).addTo(map);
      map.fitBounds(latlngs, { padding: [28, 28], maxZoom: 17 });
    } else {
      map.setView(latlngs[0], 16);
    }
    var last = points[points.length - 1];
    if (last.accuracy) {
      L.circle([last.lat, last.lon], {
        radius: last.accuracy, color: '#5F8A48', weight: 1, fillOpacity: .12
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
