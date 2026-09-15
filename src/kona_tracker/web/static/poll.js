// The picture loop, shared by the Camera tab and the Robot tab. Lives in a
// file rather than inline so the page can carry a Content-Security-Policy
// with script-src 'self' and no nonce plumbing.
//
// The picture is polled, not streamed. An MJPEG stream held open in an <img>
// is a long-lived connection the phone can abandon without a clean close
// (a tab switch into Safari's back/forward cache, a walk out of Wi-Fi
// range), and every abandoned one left a worker alive on the server until
// the small pool the stream waits use was full and no new stream could
// start: status polls kept answering, video never arrived, and only a
// server restart cleared it. Measured on Chris's iPhone, 2026-09-11; the
// record is docs/history/camera-black-screen-handoff.md.
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
// live is ever assigned to the <img>, and the placeholder is never shown as
// a picture.
//
// window.KonaPoll({cam}) starts the loop for one camera. `cam` names the
// hub on the server (`house` is the default and the pre-robot URL, byte for
// byte); it also picks the words, because "unplug the USB cable" is wrong
// advice for a robot that is simply switched off.
(function () {
  // The honest words for a response that is not a picture, from its headers.
  var WORDS = {
    house: function (state, kind, age) {
      if (state === 'disconnected' && kind === 'reader_limit') { return ['off', 'CHECK CAMERA', 'Camera recovery is stuck. Reconnect USB or restart the server.']; }
      if (state === 'disconnected' && kind === 'black_frame') { return ['off', 'CHECK CAMERA', 'No usable picture. Check the lens cover; for USB, unplug and reconnect the camera.']; }
      if (state === 'stale') { return ['stale', 'STALE', 'No new frames for ' + Math.round(age || 0) + ' s']; }
      if (state === 'connecting' || state === 'idle') { return ['stale', 'CONNECTING', 'Opening the camera…']; }
      return ['off', 'OFFLINE', 'Camera disconnected, reconnecting…'];
    },
    // The robot runs on two cells and is off more than on. Off is its
    // normal state, not a fault, and the words say so; the picture follows
    // by itself when it comes back (the hub keeps retrying, 1 s to 30 s).
    robot: function (state, kind, age) {
      if (state === 'disconnected' && kind === 'reader_limit') { return ['off', 'ROBOT OFF', 'Could not reach the robot for a while. Turn it on, or check it is on the Wi-Fi.']; }
      if (state === 'disconnected' && kind === 'black_frame') { return ['off', 'CHECK ROBOT', 'No usable picture from the robot. Is its lens covered?']; }
      if (state === 'stale') { return ['stale', 'STALE', 'No new frames for ' + Math.round(age || 0) + ' s']; }
      if (state === 'connecting' || state === 'idle') { return ['stale', 'CONNECTING', 'Reaching the robot…']; }
      return ['off', 'ROBOT OFF', 'The robot is off or off the network. The picture follows when it is back.'];
    }
  };

  window.KonaPoll = function (opts) {
    var cam = (opts && opts.cam) || 'house';
    var describe = WORDS[cam] || WORDS.house;
    // The house camera keeps its original URL exactly; only another camera
    // is named, so nothing cached or bookmarked changes meaning.
    var url = '/snapshot.jpg?' + (cam === 'house' ? '' : 'cam=' + encodeURIComponent(cam) + '&') + 'after=';
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
      // OFFLINE / CHECK CAMERA / ROBOT OFF words stand over the black.
      if (frame) { frame.classList.toggle('connecting', cls === 'stale'); }
    }
    function connecting() {
      var words = describe('connecting');
      set(words[0], words[1], words[2]);
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
      fetch(url + seq, { cache: 'no-store', signal: controller.signal }).then(function (r) {
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
            if (run === epoch) {
              show(blob);
              // Optional, and only the Robot's drive mode uses it: the page
              // needs to know a frame actually landed, not merely that the
              // server has not yet called the picture stale. Watching a dog,
              // three seconds of frozen frame is nothing; steering by it,
              // three seconds is three seconds of driving blind.
              if (opts && opts.onFrame) { opts.onFrame(); }
            }
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
      connecting();
      poll();
    }
    document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); else resume(); });
    window.addEventListener('pagehide', pause);
    window.addEventListener('pageshow', resume);
    connecting();
    if (suspended) { pause(); } else { poll(); }
  };
})();
