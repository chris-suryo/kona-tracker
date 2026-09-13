// Camera tab. Lives in a file rather than inline so the page can carry a
// Content-Security-Policy with script-src 'self' and no nonce plumbing.
//
// The picture is polled, not streamed. An MJPEG stream held open in an <img>
// is a long-lived connection the phone can abandon without a clean close
// (a tab switch into Safari's back/forward cache, a walk out of Wi-Fi
// range), and every abandoned one left a worker alive on the server until
// the small pool the stream waits use was full and no new stream could
// start: status polls kept answering, video never arrived, and only a
// server restart cleared it. Measured on Chris's iPhone, 2026-09-11; the
// record is docs/camera-black-screen-handoff.md.
//
// So each frame is one short request. The client sends back the seq it was
// last given and the server holds the request until a newer frame exists,
// for at most KONA_STALE_SECONDS (3 by default). That makes it one request
// per frame and self-pacing: a slow link asks late and skips frames rather
// than queueing them. Nothing outlives a request, so nothing can leak.
// DEADLINE below must stay above KONA_STALE_SECONDS or every poll on a
// quiet camera would be reported as a failure.
//
// Every response carries the truth about its own pixels in headers, so the
// badge and the picture can never disagree: only a frame the server called
// live is ever assigned to the <img>, and the NO SIGNAL placeholder is
// never shown as a picture.
(function () {
  var img = document.getElementById('cam'), cap = document.getElementById('cap'),
      dot = document.getElementById('dot'), txt = document.getElementById('livetxt');
  var frame = document.querySelector('.cam');
  var suspended = document.hidden, pending = null, nextTimer = null, epoch = 0;
  var seq = 0, lastState = null, backoff = 0, current = null;
  var DEADLINE = 10000, BACKOFF_MIN = 500, BACKOFF_MAX = 5000, NOT_LIVE_FLOOR = 500;

  function set(cls, label, sub) {
    dot.className = 'dot ' + cls; txt.textContent = label; cap.textContent = sub;
    // An old image must not look like a live view when the server is gone.
    img.classList.toggle('unavailable', cls !== 'on');
    // While we are hopefully connecting, the near-black frame carries a
    // "Connecting…" overlay so it reads as working, not as a dead camera. A
    // hard failure (cls 'off') drops the overlay and lets the badge's own
    // OFFLINE / CHECK CAMERA words stand over the black.
    if (frame) { frame.classList.toggle('connecting', cls === 'stale'); }
  }

  // The honest words for a response that is not a picture, from its headers.
  function describe(state, kind, age) {
    if (state === 'disconnected' && kind === 'reader_limit') { return ['off', 'CHECK CAMERA', 'Camera recovery is stuck. Reconnect USB or restart the server.']; }
    if (state === 'disconnected' && kind === 'black_frame') { return ['off', 'CHECK CAMERA', 'No usable picture. Check the lens cover; for USB, unplug and reconnect the camera.']; }
    if (state === 'stale') { return ['stale', 'STALE', 'No new frames for ' + Math.round(age || 0) + ' s']; }
    if (state === 'connecting' || state === 'idle') { return ['stale', 'CONNECTING', 'Opening the camera…']; }
    return ['off', 'OFFLINE', 'Camera disconnected, reconnecting…'];
  }

  function show(blob) {
    var old = current;
    current = URL.createObjectURL(blob);
    img.src = current;
    // Revoke on assignment, never on load: if the next frame lands before
    // this one decodes, this one's load event never fires and a load-keyed
    // revoke would leak. The browser keeps the decoded bitmap regardless,
    // so at most one object URL is alive at any instant.
    if (old) { URL.revokeObjectURL(old); }
  }
  function drop() {
    img.removeAttribute('src');
    if (current) { URL.revokeObjectURL(current); current = null; }
  }

  img.addEventListener('load', function () {
    // Only a frame the server called live is ever assigned, but a late load
    // for frame N must not flip the badge after a later word said otherwise.
    if (lastState === 'live' && img.naturalWidth > 0) { set('on', 'LIVE', ''); }
  });
  img.addEventListener('error', function () {
    if (suspended) { return; }
    // Loud rather than a silent black rectangle (a blocked blob: URL would
    // land here); the next response replaces it, so no backoff.
    set('off', 'OFFLINE', 'Video interrupted. Reconnecting…');
  });

  function schedule(delay) {
    clearTimeout(nextTimer);
    nextTimer = setTimeout(poll, delay);
  }
  function poll() {
    if (suspended || pending) { return; }
    var run = epoch, controller = new AbortController();
    pending = controller;
    var deadline = setTimeout(function () { controller.abort(); }, DEADLINE);
    var delay = 0;
    fetch('/snapshot.jpg?after=' + seq, { cache: 'no-store', signal: controller.signal }).then(function (r) {
      if (r.redirected) { epoch += 1; window.location.href = r.url; throw new Error('signed out'); }
      if (r.status === 401) {
        // The gate answers a bodyless 401 for /snapshot, never a redirect.
        epoch += 1; window.location.href = '/login'; throw new Error('signed out');
      }
      if (!r.ok) { throw new Error('snapshot failed'); }
      var state = r.headers.get('X-Kona-State');
      var got = parseInt(r.headers.get('X-Kona-Seq'), 10);
      if (!isNaN(got)) { seq = got; }
      lastState = state;
      backoff = 0;
      if (state === 'live') {
        return r.blob().then(function (blob) {
          if (run === epoch) { show(blob); }
        });
      }
      var words = describe(state, r.headers.get('X-Kona-Error'), parseFloat(r.headers.get('X-Kona-Frame-Age')));
      set(words[0], words[1], words[2]);
      delay = NOT_LIVE_FLOOR;  // the server already waited; this is a guard, not the pacing
    }).catch(function () {
      if (run !== epoch) { return; }  // paused, or sent to login: nothing to report
      backoff = backoff ? Math.min(backoff * 2, BACKOFF_MAX) : BACKOFF_MIN;
      delay = backoff;
      set('off', 'OFFLINE', 'No connection to the server');
    }).finally(function () {
      clearTimeout(deadline);
      if (pending === controller) { pending = null; }
      if (run === epoch && !suspended) { schedule(delay); }
    });
  }
  function pause() {
    suspended = true; epoch += 1;
    clearTimeout(nextTimer);
    if (pending) { pending.abort(); pending = null; }
    drop();
    set('off', 'PAUSED', 'Video paused while this page is hidden');
  }
  function resume() {
    if (document.hidden || !suspended) { return; }
    suspended = false;
    set('stale', 'CONNECTING', 'Opening the camera…');
    poll();
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); else resume(); });
  window.addEventListener('pagehide', pause);
  window.addEventListener('pageshow', resume);
  set('stale', 'CONNECTING', 'Opening the camera…');
  if (suspended) { pause(); } else { poll(); }

  // Zoom. The C120 has no motor, so "zoom" is what the Tapo app's is: the
  // picture, closer. Pinch to zoom, one finger to pan while zoomed,
  // double-tap to jump in on a spot or back out. The whole page keeps its
  // deliberate no-zoom rule (app.js); this is the one surface where a
  // pinch means something, and it means this, not the page. The transform
  // is on the <img> alone, so the badge, the shutter and each new frame
  // are untouched -- a frame arriving mid-pinch lands already zoomed.
  var ZOOM_MAX = 4, ZOOM_TAP = 2.5, SNAP_BELOW = 1.08, TAP_MS = 300, TAP_PX = 24;
  var zoom = { s: 1, x: 0, y: 0 };
  var pinch = null, drag = null, lastPoint = null, touchBegan = 0, touchMoved = false;
  var lastTap = 0, lastTapAt = null;
  var zoomBadge = document.getElementById('zoom-level');

  function frameSize() {
    return { w: frame.clientWidth || img.clientWidth || 1, h: frame.clientHeight || img.clientHeight || 1 };
  }
  function clampPan() {
    // The picture may never leave a gap: at scale s it is s times the
    // frame, so its left edge can travel from 0 back to (1 - s) widths.
    var f = frameSize();
    // `|| 0` folds a -0 into 0, so an "untouched" state compares equal.
    zoom.x = Math.min(0, Math.max(f.w * (1 - zoom.s), zoom.x)) || 0;
    zoom.y = Math.min(0, Math.max(f.h * (1 - zoom.s), zoom.y)) || 0;
  }
  function applyZoom() {
    if (zoom.s < SNAP_BELOW) { zoom.s = 1; zoom.x = 0; zoom.y = 0; }
    clampPan();
    img.style.transform = zoom.s === 1 ? '' : 'translate(' + zoom.x.toFixed(1) + 'px,' + zoom.y.toFixed(1) + 'px) scale(' + zoom.s.toFixed(3) + ')';
    if (frame) { frame.classList.toggle('zoomed', zoom.s !== 1); }
    if (zoomBadge) {
      zoomBadge.hidden = zoom.s === 1;
      zoomBadge.textContent = zoom.s.toFixed(1).replace(/\.0$/, '') + '\u00d7';
    }
  }
  // Scale about a point on the frame, so the spot under the fingers stays
  // under the fingers. With the transform's origin at the top-left corner,
  // the point p maps to x + p*s; holding it fixed across a scale change
  // from s to s2 gives x2 = p - (p - x) * (s2 / s).
  function scaleAbout(px, py, s2) {
    s2 = Math.min(ZOOM_MAX, Math.max(1, s2));
    var k = s2 / zoom.s;
    zoom.x = px - (px - zoom.x) * k;
    zoom.y = py - (py - zoom.y) * k;
    zoom.s = s2;
    applyZoom();
  }
  function local(touch) {
    var r = frame.getBoundingClientRect ? frame.getBoundingClientRect() : { left: 0, top: 0 };
    return { x: touch.clientX - r.left, y: touch.clientY - r.top };
  }
  function span(a, b) { return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1; }

  frame.addEventListener('touchstart', function (e) {
    if (e.target.closest && e.target.closest('button')) { return; }  // the shutter is a button, not a gesture
    if (e.touches.length === 2) {
      var m = local({ clientX: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                      clientY: (e.touches[0].clientY + e.touches[1].clientY) / 2 });
      pinch = { dist: span(e.touches[0], e.touches[1]), s: zoom.s, mx: m.x, my: m.y };
      drag = null;
    } else if (e.touches.length === 1) {
      var p = local(e.touches[0]);
      touchBegan = Date.now(); touchMoved = false;
      drag = zoom.s > 1 ? { x: p.x, y: p.y, ox: zoom.x, oy: zoom.y } : null;
      lastPoint = p;
    }
  }, { passive: false });
  frame.addEventListener('touchmove', function (e) {
    if (pinch && e.touches.length === 2) {
      // The midpoint anchors the scale; the fingers' drift pans by the rest.
      var m = local({ clientX: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                      clientY: (e.touches[0].clientY + e.touches[1].clientY) / 2 });
      var s2 = pinch.s * span(e.touches[0], e.touches[1]) / pinch.dist;
      zoom.x += m.x - pinch.mx; zoom.y += m.y - pinch.my;
      pinch.mx = m.x; pinch.my = m.y;
      scaleAbout(m.x, m.y, s2);
      e.preventDefault();
    } else if (e.touches.length === 1) {
      var p = local(e.touches[0]);
      if (lastPoint && Math.hypot(p.x - lastPoint.x, p.y - lastPoint.y) >= TAP_PX) { touchMoved = true; }
      if (drag) {
        zoom.x = drag.ox + (p.x - drag.x); zoom.y = drag.oy + (p.y - drag.y);
        applyZoom();
        e.preventDefault();  // zoomed in, a swipe pans the picture, not the page
      }
    }
  }, { passive: false });
  function endTouch(e) {
    if (e.touches.length < 2) { pinch = null; }
    if (e.touches.length === 0) {
      // A tap is a touch that neither moved nor lingered. Two of them, close
      // in time and place, are a double-tap: in on that spot, or back out.
      var now = Date.now();
      var quick = touchBegan && now - touchBegan < TAP_MS && !touchMoved;
      if (quick && lastPoint) {
        if (lastTap && now - lastTap < TAP_MS && lastTapAt && Math.hypot(lastPoint.x - lastTapAt.x, lastPoint.y - lastTapAt.y) < TAP_PX) {
          lastTap = 0;
          if (zoom.s === 1) { scaleAbout(lastPoint.x, lastPoint.y, ZOOM_TAP); } else { zoom.s = 1; applyZoom(); }
        } else {
          lastTap = now; lastTapAt = lastPoint;
        }
      } else if (!quick) {
        lastTap = 0;
      }
      drag = null; lastPoint = null; touchBegan = 0;
    }
    applyZoom();
  }
  frame.addEventListener('touchend', endTouch);
  frame.addEventListener('touchcancel', endTouch);
  window.KonaZoom = { get: function () { return { s: zoom.s, x: zoom.x, y: zoom.y }; }, reset: function () { zoom.s = 1; applyZoom(); } };
  applyZoom();  // a clean 1x: no transform, no badge

  // Share a real JPEG when the browser permits file sharing (iPhone over
  // HTTPS or localhost). On an ordinary LAN HTTP address, save the same
  // image instead; the camera action still completes honestly.
  var capture = document.getElementById('capture');
  var captureHint = document.getElementById('capture-hint');
  capture.addEventListener('click', function () {
    capture.disabled = true;
    captureHint.textContent = 'Capturing…';
    var controller = new AbortController();
    var deadline = setTimeout(function () { controller.abort(); }, 10000);
    fetch('/snapshot.jpg?t=' + Date.now(), { cache: 'no-store', signal: controller.signal })
      .then(function (r) {
        if (!r.ok || r.headers.get('X-Kona-State') !== 'live') throw new Error('no live frame');
        return r.blob();
      })
      .then(function (blob) {
        clearTimeout(deadline);  // the share sheet belongs to the person, not the network timer
        var file = new File([blob], 'kona-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.jpg', { type: 'image/jpeg' });
        if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
          return navigator.share({ title: 'Kona right now', files: [file] }).then(function () {
            captureHint.textContent = 'Photo shared';
          });
        }
        var url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = file.name; link.click();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        captureHint.textContent = 'Photo saved';
      })
      .catch(function (e) {
        captureHint.textContent = e.name === 'AbortError' && !controller.signal.aborted ? 'Capture and share a still' : 'Could not capture—try again';
      })
      .finally(function () { clearTimeout(deadline); capture.disabled = false; });
  });

  // Pan/tilt. Press and hold to keep moving; release to stop. Pointer
  // events cover touch and mouse with one code path, and losing the
  // pointer (drag off the button, phone call) must stop the motor.
  var pad = document.querySelector('.ptz');
  if (pad) {
    var held = null;
    function send(url, body) {
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body
      }).then(function (r) { return r.ok ? r.json() : null; });
    }
    function nudge(btn) {
      send('/control/move', 'pan=' + btn.dataset.pan + '&tilt=' + btn.dataset.tilt);
    }
    function release() { if (held) { clearInterval(held); held = null; } }
    pad.querySelectorAll('.nub, .presets .pill').forEach(function (btn) {
      btn.addEventListener('pointerdown', function (e) {
        e.preventDefault();
        if (btn.dataset.preset) {
          send('/control/preset', 'number=' + btn.dataset.preset);
          return;
        }
        nudge(btn);
        release();
        held = setInterval(function () { nudge(btn); }, 220);
      });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (ev) {
        btn.addEventListener(ev, release);
      });
    });
    window.addEventListener('blur', release);
  }

  // Switches: night vision, privacy, the LED. The section exists only when
  // the connected driver offers them (camera.html); the page then reads
  // their real state before it lets anyone press anything, so a control is
  // never shown in a state nobody has read. Every press posts one change
  // and redraws from the camera's own answer, never from the press.
  var settings = document.getElementById('cam-settings');
  if (settings) {
    var note = document.getElementById('setting-note');
    var controls = settings.querySelectorAll('[data-setting]');
    function draw(state) {
      controls.forEach(function (el) {
        var name = el.dataset.setting, value = state[name];
        el.disabled = value === undefined || value === null;
        if (el.classList.contains('opt')) {
          el.setAttribute('aria-pressed', String(value === el.dataset.value));
        } else {
          el.setAttribute('aria-checked', String(value === true));
        }
      });
      settings.removeAttribute('data-pending');
    }
    function fail(message) {
      controls.forEach(function (el) { el.disabled = true; });
      note.textContent = message;
      note.classList.add('warn');
    }
    function settle(r) {
      return r.json().then(function (data) {
        if (!r.ok) { throw new Error(data.error || 'The camera did not answer'); }
        draw(data.settings);
        note.classList.remove('warn');
        note.textContent = data.settings.privacy === true
          ? 'Privacy mode is on: the lens is covered and the picture is black.'
          : 'Changes go straight to the camera.';
      });
    }
    fetch('/control/settings', { cache: 'no-store' }).then(settle).catch(function (e) { fail(e.message); });
    controls.forEach(function (el) {
      el.addEventListener('click', function () {
        var name = el.dataset.setting;
        var value = el.classList.contains('opt') ? el.dataset.value
          : el.getAttribute('aria-checked') === 'true' ? 'off' : 'on';
        controls.forEach(function (c) { c.disabled = true; });
        note.textContent = 'Asking the camera…';
        fetch('/control/setting', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'name=' + encodeURIComponent(name) + '&value=' + encodeURIComponent(value)
        }).then(settle).catch(function (e) { fail(e.message); });
      });
    });
  }
})();
