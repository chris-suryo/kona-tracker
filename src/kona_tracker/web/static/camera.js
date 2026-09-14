// Camera tab: the house camera. The picture loop itself is poll.js, shared
// with the Robot tab; what is here is everything only this camera has --
// pinch-to-zoom, the shutter, the pan/tilt pad and the switches. Lives in a
// file rather than inline so the page can carry a Content-Security-Policy
// with script-src 'self' and no nonce plumbing.
(function () {
  var img = document.getElementById('cam');
  var frame = document.querySelector('.cam');
  window.KonaPoll({ cam: 'house' });

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
