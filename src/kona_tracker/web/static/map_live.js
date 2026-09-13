// The full-screen live map. Built for the case the Activity card's little
// map tile cannot serve: someone watching the dot move while the dog is out.
//
// Two clocks run here. A poll asks the server for new points every few
// seconds, and a one-second ticker counts the fix age up between polls so
// the number on screen never looks frozen when nothing has changed. The age
// arrives as *seconds*, not a timestamp, so a phone clock that disagrees
// with the server's cannot turn a fresh fix into a stale-looking one.
//
// The map object is created once and then updated in place. Rebuilding it
// on every poll would reset the zoom the person just set with their fingers,
// which is the fastest way to make a live map useless.
(function () {
  'use strict';

  // Poll faster while she is actually moving. At rest the collar itself
  // reports on a multi-minute schedule (Fi's own GPS-rate setting), so
  // asking every few seconds would only spend requests to be told the same
  // thing. The server has its own floor in front of Fi; this is the page.
  var WALKING_MS = 10000;
  var RESTING_MS = 60000;
  var TICK_MS = 1000;
  // Give up on a poll rather than let requests pile up on a bad connection.
  var TIMEOUT_MS = 8000;

  var map = null;
  var trail = null;
  var here = null;
  var halo = null;
  var start = null;
  var followed = true;
  var ageSeconds = null;
  var pollTimer = null;
  var tickTimer = null;

  function el(id) { return document.getElementById(id); }

  function tileConfig() {
    var cfg = {
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      maxZoom: 19,
      dark: false,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    };
    var block = el('map-config');
    if (!block) { return cfg; }
    try {
      var parsed = JSON.parse(block.textContent);
      if (parsed && parsed.url) { return parsed; }
    } catch (e) { /* the OSM default beats rendering nothing */ }
    return cfg;
  }

  function readPoints() {
    var block = el('map-points');
    if (!block) { return []; }
    try {
      var parsed = JSON.parse(block.textContent);
      return parsed && parsed.length ? parsed : [];
    } catch (e) { return []; }
  }

  function ageText(seconds) {
    if (seconds === null || seconds === undefined) { return '—'; }
    if (seconds < 90) { return seconds + ' s ago'; }
    if (seconds < 5400) { return Math.round(seconds / 60) + ' min ago'; }
    return Math.round(seconds / 3600) + ' h ago';
  }

  // A fix that has stopped arriving is the one thing a live map must not
  // hide: a confident dot in a place she left four minutes ago is worse
  // than no map. Past two minutes the age goes amber, past five it is red.
  function paintAge() {
    var node = el('live-age');
    if (!node) { return; }
    node.textContent = ageText(ageSeconds);
    node.classList.toggle('warn', ageSeconds !== null && ageSeconds >= 120 && ageSeconds < 300);
    node.classList.toggle('bad', ageSeconds !== null && ageSeconds >= 300);
  }

  function buildMap(points) {
    var host = el('kona-map');
    if (!host || typeof L === 'undefined' || !points.length) { return false; }
    var cfg = tileConfig();
    map = L.map(host, { zoomControl: false, scrollWheelZoom: true, attributionControl: true });
    host.classList.toggle('tiles-dark', !!cfg.dark);
    var tiles = L.tileLayer(cfg.url, { maxZoom: cfg.maxZoom || 19, attribution: cfg.attribution });
    var unavailable = el('map-unavailable');
    var arrived = 0;
    // Same rule as the small map: a single dead tile is not a dead server,
    // and hiding a map that has already drawn is worse than one grey square.
    tiles.on('tileerror', function () {
      if (arrived > 0) { return; }
      host.hidden = true;
      if (unavailable) { unavailable.hidden = false; }
    });
    tiles.on('tileload', function () {
      arrived += 1;
      if (!host.hidden) { return; }
      host.hidden = false;
      if (unavailable) { unavailable.hidden = true; }
      map.invalidateSize();
    });
    tiles.addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    // Panning by hand means "I want to look over here". Stop recentring
    // until they ask for it back, or the map will yank itself away from
    // whatever they were looking at on the next poll.
    map.on('dragstart', function () {
      followed = false;
      var recentre = el('live-recentre');
      if (recentre) { recentre.hidden = false; }
    });
    draw(points, true);
    return true;
  }

  function draw(points, fit) {
    if (!map || !points.length) { return; }
    var latlngs = points.map(function (p) { return [p.lat, p.lon]; });
    var last = points[points.length - 1];
    if (latlngs.length > 1) {
      if (trail) { trail.setLatLngs(latlngs); }
      else { trail = L.polyline(latlngs, { color: '#5F8A48', weight: 5, opacity: .9 }).addTo(map); }
      if (start) { start.setLatLng(latlngs[0]); }
      else {
        start = L.marker(latlngs[0], {
          icon: L.divIcon({ className: 'kona-map-start', html: '<span></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
          interactive: false
        }).addTo(map);
      }
    }
    if (here) { here.setLatLng([last.lat, last.lon]); }
    else {
      here = L.marker([last.lat, last.lon], {
        icon: L.divIcon({ className: 'kona-map-marker', html: '<span>K</span>', iconSize: [34, 34], iconAnchor: [17, 17] })
      }).addTo(map);
    }
    // The accuracy circle is the honest part of the picture: Fi's own error
    // radius ran 65 m on a cold fix down to 4 m once warm.
    if (last.accuracy) {
      if (halo) { halo.setLatLng([last.lat, last.lon]).setRadius(last.accuracy); }
      else {
        halo = L.circle([last.lat, last.lon], {
          radius: last.accuracy, color: '#5F8A48', weight: 1, fillOpacity: .12
        }).addTo(map);
      }
    } else if (halo) {
      map.removeLayer(halo);
      halo = null;
    }
    if (!followed && !fit) { return; }
    if (latlngs.length > 1) { map.fitBounds(latlngs, { padding: [40, 40], maxZoom: 17 }); }
    else { map.setView(latlngs[0], 17); }
  }

  function text(id, value) {
    var node = el(id);
    if (node) { node.textContent = value; }
  }

  function stat(id, on) {
    var node = el(id);
    if (node) { node.hidden = !on; }
  }

  function apply(data) {
    if (!data) { return; }
    if (data.title) { text('live-title', data.title); }
    var bits = [];
    if (data.area && (data.kind === 'rest' || data.kind === 'home')) { bits.push(data.area); }
    if (data.reported) { bits.push('Collar reported ' + data.reported); }
    text('live-sub', bits.join(' · '));
    if (data.distance) { text('live-distance', data.distance); }
    stat('live-distance-stat', !!data.distance);
    var elapsed = el('live-elapsed');
    if (elapsed && data.elapsed && data.elapsed.length) {
      elapsed.textContent = '';
      data.elapsed.forEach(function (pair) {
        elapsed.appendChild(document.createTextNode(pair[0]));
        var unit = document.createElement('small');
        unit.textContent = pair[1];
        elapsed.appendChild(unit);
      });
    }
    stat('live-elapsed-stat', !!(data.elapsed && data.elapsed.length));
    var note = el('live-note');
    if (note) {
      note.textContent = data.stale
        ? 'Fi stopped answering — this is the last fix we have.'
        : '';
      note.hidden = !data.stale;
    }
    ageSeconds = (typeof data.fix_age_s === 'number') ? data.fix_age_s : null;
    paintAge();
    if (data.points && data.points.length) {
      if (!map) { buildMap(data.points); }
      else { draw(data.points, false); }
    }
    return data.activity === 'walk' && data.live;
  }

  function schedule(walking) {
    if (pollTimer) { clearTimeout(pollTimer); }
    pollTimer = setTimeout(poll, walking ? WALKING_MS : RESTING_MS);
  }

  function poll() {
    if (document.hidden) { schedule(false); return; }
    var controller = new AbortController();
    var cut = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);
    fetch('/map.json', { cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } })
      .then(function (r) {
        clearTimeout(cut);
        if (!r.ok) { throw new Error('map poll failed'); }
        return r.json();
      })
      .then(function (data) { schedule(apply(data)); })
      // A failed poll changes nothing on screen on purpose: the last fix is
      // still the last fix, and the age ticking up says so by itself.
      .catch(function () { clearTimeout(cut); schedule(false); });
  }

  function tick() {
    if (ageSeconds === null) { return; }
    ageSeconds += 1;
    paintAge();
  }

  function startTimers() {
    var frame = el('live-frame');
    var walking = !!frame && frame.getAttribute('data-activity') === 'walk';
    schedule(walking);
    if (!tickTimer) { tickTimer = setInterval(tick, TICK_MS); }
  }

  var initial = readPoints();
  if (initial.length) { buildMap(initial); }
  var seeded = el('live-age');
  if (seeded && seeded.getAttribute('data-age') !== '') {
    ageSeconds = parseInt(seeded.getAttribute('data-age'), 10);
    if (isNaN(ageSeconds)) { ageSeconds = null; }
  }
  paintAge();

  var recentreButton = el('live-recentre');
  if (recentreButton) {
    recentreButton.addEventListener('click', function () {
      followed = true;
      recentreButton.hidden = true;
      poll();
    });
  }

  // A phone that locks mid-walk should come back current, not resume a
  // timer that fired into a sleeping tab.
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { poll(); }
  });

  startTimers();
  window.KonaLiveMap = { poll: poll };
})();
