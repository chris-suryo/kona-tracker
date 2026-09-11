// Camera tab. Lives in a file rather than inline so the page can carry a
// Content-Security-Policy with script-src 'self' and no nonce plumbing.
// MJPEG in Safari sometimes stalls after sleep/wake or a network blip;
// a cache-busted reload of the <img> is the whole recovery story. The
// server already swaps in a "NO SIGNAL" frame when the picture is not
// fresh; the label below just says so in words.
(function () {
  var img = document.getElementById('cam'), cap = document.getElementById('cap'),
      dot = document.getElementById('dot'), txt = document.getElementById('livetxt'), tries = 0;
  var pollTimer = null, retryTimer = null, pending = null, epoch = 0;
  var suspended = document.hidden, streamFailed = false, statusFailed = false;
  function reload() {
    if (suspended) { return; }
    clearTimeout(retryTimer); retryTimer = null;
    tries += 1;
    streamFailed = false;
    img.src = '/stream.mjpg?t=' + Date.now();
  }
  img.addEventListener('load', function () { tries = 0; });
  img.addEventListener('error', function () {
    if (suspended) { return; }
    streamFailed = true;
    set('off', 'OFFLINE', 'Video interrupted. Reconnecting…');
    if (retryTimer === null) {
      retryTimer = setTimeout(reload, Math.min(1000 * (tries + 1), 5000));
    }
  });
  function set(cls, label, sub) {
    dot.className = 'dot ' + cls; txt.textContent = label; cap.textContent = sub;
    // An old image must not look like a live view when the server is gone.
    img.classList.toggle('unavailable', cls !== 'on');
  }
  function poll() {
    if (suspended || pending) { return; }
    var run = epoch, controller = new AbortController();
    pending = controller;
    var deadline = setTimeout(function () { controller.abort(); }, 5000);
    fetch('/status.json', { cache: 'no-store', signal: controller.signal }).then(function (r) {
      if (r.redirected) { window.location.href = r.url; throw new Error('signed out'); }
      if (!r.ok) { throw new Error('status failed'); }
      return r.json();
    }).then(function (s) {
      if (run !== epoch) { return; }
      if (!s || ['live', 'stale', 'connecting', 'disconnected', 'idle'].indexOf(s.state) < 0) {
        throw new Error('invalid status');
      }
      if (statusFailed) {
        statusFailed = false; reload();
        set('stale', 'CONNECTING', 'Reconnecting video…');
        return;
      }
      if (s.state === 'live' && !streamFailed && img.naturalWidth > 0) set('on', 'LIVE', '');
      else if (s.state === 'live') set('stale', 'CONNECTING', 'Waiting for video on this phone…');
      else if (s.state === 'disconnected' && s.last_error_kind === 'reader_limit') set('off', 'CHECK CAMERA', 'Camera recovery is stuck. Reconnect USB or restart the server.');
      else if (s.state === 'disconnected' && s.last_error_kind === 'black_frame') set('off', 'CHECK CAMERA', 'No usable picture. Check the lens cover; for USB, unplug and reconnect the camera.');
      else if (s.state === 'stale') set('stale', 'STALE', 'No new frames for ' + Math.round(s.last_frame_age) + ' s');
      else if (s.state === 'connecting') set('stale', 'CONNECTING', 'Opening the camera…');
      else if (s.state === 'idle') { reload(); set('stale', 'CONNECTING', 'Reconnecting video…'); }
      else set('off', 'OFFLINE', 'Camera disconnected, reconnecting…');
    }).catch(function () {
      if (run === epoch) { statusFailed = true; set('off', 'OFFLINE', 'No connection to the server'); }
    }).finally(function () {
      clearTimeout(deadline);
      if (pending === controller) { pending = null; }
      if (run === epoch && !suspended) { pollTimer = setTimeout(poll, 2000); }
    });
  }
  function pause() {
    suspended = true; epoch += 1;
    clearTimeout(pollTimer); clearTimeout(retryTimer); retryTimer = null;
    if (pending) { pending.abort(); pending = null; }
    img.removeAttribute('src');
    set('off', 'PAUSED', 'Video paused while this page is hidden');
  }
  function resume() {
    if (document.hidden || !suspended) { return; }
    suspended = false;
    set('stale', 'CONNECTING', 'Opening the camera…');
    reload(); poll();
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); else resume(); });
  window.addEventListener('pagehide', pause);
  window.addEventListener('pageshow', resume);
  set('stale', 'CONNECTING', 'Opening the camera…');
  if (suspended) { pause(); } else { poll(); }

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
})();
