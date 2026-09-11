// Camera tab. Lives in a file rather than inline so the page can carry a
// Content-Security-Policy with script-src 'self' and no nonce plumbing.
// MJPEG in Safari sometimes stalls after sleep/wake or a network blip;
// a cache-busted reload of the <img> is the whole recovery story. The
// server already swaps in a "NO SIGNAL" frame when the picture is not
// fresh; the label below just says so in words.
(function () {
  var img = document.getElementById('cam'), cap = document.getElementById('cap'),
      dot = document.getElementById('dot'), txt = document.getElementById('livetxt'), tries = 0;
  function reload() {
    tries += 1;
    img.src = '/stream.mjpg?t=' + Date.now();
  }
  img.addEventListener('load', function () { tries = 0; });
  img.addEventListener('error', function () { setTimeout(reload, Math.min(1000 * tries, 5000)); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { reload(); poll(); } });
  function set(cls, label, sub) { dot.className = 'dot ' + cls; txt.textContent = label; cap.textContent = sub; }
  function poll() {
    fetch('/status.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (s) {
      if (s.state === 'live') set('on', 'LIVE', '');
      else if (s.last_error_kind === 'black_frame') set('off', 'CHECK CAMERA', 'Image is fully dark—check the lens cover and room light');
      else if (s.state === 'stale') set('stale', 'STALE', 'No new frames for ' + Math.round(s.last_frame_age) + ' s');
      else if (s.state === 'connecting') set('stale', 'CONNECTING', 'Opening the camera…');
      else set('off', 'OFFLINE', 'Camera disconnected, reconnecting…');
    }).catch(function () { set('off', 'OFFLINE', 'No connection to the server'); });
  }
  poll(); setInterval(poll, 2000);

  // Share a real JPEG when the browser permits file sharing (iPhone over
  // HTTPS or localhost). On an ordinary LAN HTTP address, save the same
  // image instead; the camera action still completes honestly.
  var capture = document.getElementById('capture');
  var captureHint = document.getElementById('capture-hint');
  capture.addEventListener('click', function () {
    capture.disabled = true;
    captureHint.textContent = 'Capturing…';
    fetch('/snapshot.jpg?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('capture failed'); return r.blob(); })
      .then(function (blob) {
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
        captureHint.textContent = e.name === 'AbortError' ? 'Capture and share a still' : 'Could not capture—try again';
      })
      .finally(function () { capture.disabled = false; });
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
