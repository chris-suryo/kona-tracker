// Camera tab: the house camera. The picture loop itself is poll.js, shared
// with the Robot tab; what is here is everything only this camera has --
// pinch-to-zoom, full view, the shutter, the pan/tilt pad and the switches. Lives in a
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
  var lastTap = 0, lastTapAt = null, swipe = null;
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
    awake();  // in full view, any touch brings the controls back
    if (e.target.closest && e.target.closest('button')) { return; }  // the shutter is a button, not a gesture
    swipe = null;
    if (e.touches.length === 2) {
      var m = local({ clientX: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                      clientY: (e.touches[0].clientY + e.touches[1].clientY) / 2 });
      pinch = { dist: span(e.touches[0], e.touches[1]), s: zoom.s, mx: m.x, my: m.y };
      drag = null;
    } else if (e.touches.length === 1) {
      var p = local(e.touches[0]);
      touchBegan = Date.now(); touchMoved = false;
      drag = zoom.s > 1 ? { x: p.x, y: p.y, ox: zoom.x, oy: zoom.y } : null;
      // At 1x in full view a downward swipe minimizes, as on a video player.
      // Zoomed in, the same swipe pans the picture instead.
      swipe = full && zoom.s === 1 ? { x: p.x, y: p.y } : null;
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
      } else if (swipe) {
        var down = p.y - swipe.y;
        e.preventDefault();  // full view has no page behind it to scroll
        if (down > SWIPE_PX && Math.abs(p.x - swipe.x) < down) { swipe = null; minimize(); }
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
      drag = null; swipe = null; lastPoint = null; touchBegan = 0;
    }
    applyZoom();
  }
  frame.addEventListener('touchend', endTouch);
  frame.addEventListener('touchcancel', endTouch);
  window.KonaZoom = { get: function () { return { s: zoom.s, x: zoom.x, y: zoom.y }; }, reset: function () { zoom.s = 1; applyZoom(); } };
  applyZoom();  // a clean 1x: no transform, no badge

  // Full view. The picture fills the screen, black around it, letterboxed
  // rather than cropped. It is the same <img> and the same loop, so zoom,
  // the badge and the shutter all carry on. Minimize with the same button,
  // a swipe down, or the phone's own Back. An iPhone has no Fullscreen API
  // for a page element and no way for a page to turn its screen, so there
  // it is a fixed overlay and the person turns the phone; where the API
  // exists (Android, an iPad, a desktop) the page asks for it as well, to
  // drop the browser's own bars too.
  var expand = document.getElementById('expand');
  var toast = document.getElementById('cam-toast');
  var root = document.documentElement;
  var full = false, pushed = false, quietTimer = null, toastTimer = null, wake = null, wokeAt = 0, sized = null;
  var QUIET_MS = 3000, WAKE_GRACE_MS = 400, TOAST_MS = 2500, SWIPE_PX = 80;

  // The controls fade after a few quiet seconds in full view and come back
  // on any touch. A tap that wakes them must not also press whatever button
  // reappears under the finger, hence the grace period the buttons check.
  function awake() {
    clearTimeout(quietTimer);
    if (frame.classList.contains('quiet')) { wokeAt = Date.now(); frame.classList.remove('quiet'); }
    if (full) { quietTimer = setTimeout(function () { frame.classList.add('quiet'); }, QUIET_MS); }
  }
  function justWoke() { return Date.now() - wokeAt < WAKE_GRACE_MS; }
  // Keep the screen on while watching. The API exists only on an https://
  // page; over plain http it is absent and the phone dims as it always has.
  function keepAwake(on) {
    var lock = navigator.wakeLock;
    if (on && lock && !wake) {
      wake = lock.request('screen').catch(function () { return null; });
    } else if (!on && wake) {
      wake.then(function (sentinel) { if (sentinel) { sentinel.release().catch(function () {}); } });
      wake = null;
    }
  }
  function setFull(on) {
    if (on === full) { return; }
    full = on;
    // The frame is about to change size; an offset measured against the old
    // one would leave a gap, so the picture starts again at 1x.
    zoom.s = 1; applyZoom();
    frame.classList.toggle('full', on);
    frame.classList.remove('quiet');
    if (toast && !on) { clearTimeout(toastTimer); toast.hidden = true; }  // its words were for full view
    if (root) { root.classList.toggle('cam-full', on); }
    expand.setAttribute('aria-label', on ? 'Minimize' : 'Full screen');
    expand.setAttribute('aria-pressed', String(on));
    awake();
    keepAwake(on);
    // The whole page goes fullscreen, not the figure: a fullscreen element is
    // drawn above everything else, and the photo panel, which lives outside
    // the figure, would open unseen behind the picture. The CSS overlay is
    // what makes the picture fill the screen either way.
    if (on && root && root.requestFullscreen && !document.fullscreenElement) {
      root.requestFullscreen().catch(function () {});
    } else if (!on && document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(function () {});
    }
  }
  function maximize() {
    if (full) { return; }
    setFull(true);
    // A history entry, so the phone's Back gesture minimizes rather than
    // leaving the camera altogether.
    if (window.history && window.history.pushState) {
      window.history.pushState({ konaFull: true }, '');
      pushed = true;
    }
  }
  function minimize() {
    if (!full) { return; }
    // Step back over our own entry only while it is still on top: a Back
    // that the browser already spent leaving its fullscreen must not be
    // followed by a second one that leaves the camera page.
    var h = window.history;
    if (pushed && h && h.state && h.state.konaFull) { pushed = false; h.back(); return; }  // popstate finishes it
    pushed = false;
    setFull(false);
  }
  window.addEventListener('popstate', function () { pushed = false; setFull(false); });
  // Leaving the browser's fullscreen by its own means (Esc, Android's Back)
  // leaves full view with it.
  document.addEventListener('fullscreenchange', function () {
    if (full && !document.fullscreenElement) { minimize(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { if (still && !still.hidden) { hideStill(); } else { minimize(); } }
  });
  // Turning the phone resizes the frame under a zoomed picture; start over
  // at 1x rather than leave it off the edge.
  window.addEventListener('resize', function () {
    var f = frameSize(), was = sized;
    sized = f;
    if (was && (was.w !== f.w || was.h !== f.h) && zoom.s !== 1) { zoom.s = 1; applyZoom(); }
  });
  // Coming back to the page drops the screen lock; take it again.
  document.addEventListener('visibilitychange', function () {
    if (full && !document.hidden) { wake = null; keepAwake(true); }
  });
  // A mouse has no touchstart: a desktop, or an iPad with a trackpad,
  // wakes the controls by moving or pressing instead.
  frame.addEventListener('pointerdown', awake);
  frame.addEventListener('mousemove', function () { if (full) { awake(); } });
  expand.addEventListener('click', function () {
    if (justWoke()) { return; }
    if (full) { minimize(); } else { maximize(); }
  });

  // Words for the shutter: under the picture on the page, and over it in
  // full view, where the line under the picture is covered.
  var capture = document.getElementById('capture');
  var captureHint = document.getElementById('capture-hint');
  var HINT = captureHint.textContent;
  function say(text) {
    captureHint.textContent = text;
    if (!toast) { return; }
    clearTimeout(toastTimer);
    toast.hidden = !full;
    toast.textContent = text;
    if (full) { toastTimer = setTimeout(function () { toast.hidden = true; }, TOAST_MS); }
  }

  // The captured still, held up to be saved. One object URL at a time,
  // revoked when the panel closes.
  var still = document.getElementById('still'), stillImg = document.getElementById('still-img'), stillUrl = null;
  function showStill(blob) {
    if (stillUrl) { URL.revokeObjectURL(stillUrl); }
    stillUrl = URL.createObjectURL(blob);
    stillImg.src = stillUrl;
    still.hidden = false;
  }
  function hideStill() {
    still.hidden = true;
    captureHint.textContent = HINT;
    stillImg.removeAttribute('src');
    if (stillUrl) { URL.revokeObjectURL(stillUrl); stillUrl = null; }
  }
  document.getElementById('still-done').addEventListener('click', hideStill);
  still.addEventListener('click', function (e) { if (e.target === still) { hideStill(); } });  // a tap beside the photo

  // Two ways to get the photo into Photos, chosen by what the phone allows.
  // On an https:// page the share sheet takes the file and offers "Save
  // Image". Over plain http an iPhone refuses to share a file, and the old
  // fallback, a download link, opened a preview and filed the JPEG under
  // Files; so the photo is shown instead, to be pressed and held for "Save
  // to Photos". Only a frame the server called live is ever captured.
  capture.addEventListener('click', function () {
    if (justWoke()) { return; }
    capture.disabled = true;
    say('Capturing…');
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
        // Files only, no title: a title travels as a second, text item, and
        // a share of mixed items is where iOS stops offering "Save Image".
        if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
          return navigator.share({ files: [file] }).then(function () { say('Photo shared'); });
        }
        showStill(blob);
        say('Press and hold the photo to save it');
      })
      .catch(function (e) {
        // Closing the share sheet without choosing is not a failure.
        say(e.name === 'AbortError' && !controller.signal.aborted ? HINT : 'Could not capture—try again');
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
