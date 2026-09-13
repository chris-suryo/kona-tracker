// Shared by every page. No framework, no build step: the pages are HTML
// rendered by the server, and this file only does what CSS cannot.
(function () {
  // Optional images (Kona's photo, when Fi has none) fall back to the
  // initial behind them. Formerly an inline onerror= handler; the page now
  // ships a Content-Security-Policy that forbids inline script, so the
  // listener lives here. `error` does not bubble, hence capture; images that
  // failed before this script ran are caught by the second pass.
  function dropIfBroken(img) {
    if (img.tagName === 'IMG' && img.hasAttribute('data-optional')) { img.remove(); }
  }
  document.addEventListener('error', function (e) { dropIfBroken(e.target); }, true);
  document.querySelectorAll('img[data-optional]').forEach(function (img) {
    if (img.complete && img.naturalWidth === 0) { img.remove(); }
  });
})();

// Pull to refresh, on the Activity page. Safari's own pull-to-refresh
// reloads the document, does not exist at all once the app is on the home
// screen, and a reload is the wrong tool anyway: this fetches a fresh
// render of the same page and swaps its body in, so nothing is torn down
// and the numbers, labels and stale wording still come from one place --
// the server's template. Coming back to the app does the same, so opening
// it shows the current numbers without a gesture.
(function () {
  var page = document.querySelector('main.activity-page');
  var body = document.getElementById('activity-body');
  var bar = document.getElementById('pull');
  if (!page || !body || !bar) { return; }
  // Sample preview must remain sample data, including after sleep/wake.
  if (body.querySelector('.preview-banner')) { return; }
  var label = bar.querySelector('span');
  var THRESHOLD = 60, RESISTANCE = 0.5;
  var startY = null, pulling = false, busy = false;
  var dismissTimer = null;

  function interruptDismissal() {
    clearTimeout(dismissTimer);
    bar.classList.remove('finished', 'failed');
  }

  function show(dy) {
    interruptDismissal();
    bar.hidden = false;
    bar.classList.add('dragging');
    bar.style.transform = 'translateY(' + (Math.min(dy, 88) - 48) + 'px)';
    bar.style.opacity = String(Math.min(dy / 36, 1));
    bar.classList.toggle('ready', dy >= THRESHOLD);
    label.textContent = dy >= THRESHOLD ? 'Release to refresh' : 'Pull to refresh';
  }
  function hide() {
    clearTimeout(dismissTimer);
    bar.classList.remove('ready', 'busy', 'dragging', 'finished', 'failed');
    bar.style.transform = '';
    bar.style.opacity = '';
    dismissTimer = setTimeout(function () { bar.hidden = true; }, 220);
  }

  // The honest failure: keep every number on screen with the time it was
  // true, in the same words the page already uses when Fi goes quiet --
  // except that this time it was our own server that did not answer, and
  // the sentence must not blame Fi for that.
  function failed() {
    var current = body.querySelector('.collar-summary .eyebrow');
    if (current) { current.textContent = 'Last reported'; }
    var location = body.querySelector('.location-heading .eyebrow');
    if (location) { location.textContent = 'Last reported location'; }
    body.querySelectorAll('.status-dot.live').forEach(function (dot) {
      dot.classList.remove('live'); dot.classList.add('warn-dot');
    });
    var freshness = body.querySelector('.freshness');
    var asOf = freshness ? freshness.getAttribute('data-as-of') : '';
    if (freshness) {
      freshness.textContent = '';
      var dot = document.createElement('span');
      dot.className = 'status-dot warn-dot';
      freshness.appendChild(dot);
      freshness.appendChild(document.createTextNode(
        asOf ? 'Last successful update ' + asOf : 'No answer from this server'));
    }
    var note = body.querySelector('p.note');
    if (note) {
      note.className = 'note warn';
      note.textContent = asOf
        ? "Couldn't refresh just now, so these are the numbers from " + asOf + ', not from this moment.'
        : "Couldn't refresh just now.";
    }
  }

  // `force` asks the server to go to Fi now (the pull gesture, and coming
  // back to the app); without it the request returns whatever the server
  // already has, which is what the quiet timer below wants. `silent` keeps
  // the pull bar out of it: a bar that announces itself every minute is an
  // interruption, not feedback.
  function refresh(force, silent) {
    if (busy) { return; }
    busy = true;
    if (!silent) {
      interruptDismissal();
      bar.hidden = false;
      bar.classList.remove('ready', 'dragging');
      bar.style.transform = '';
      bar.style.opacity = '';
      bar.classList.add('busy');
      label.textContent = 'Refreshing\u2026';
    }
    var succeeded = false;
    var controller = new AbortController();
    var deadline = setTimeout(function () { controller.abort(); }, 20000);
    fetch(force ? '/activity?fresh=1' : '/activity', { cache: 'no-store', signal: controller.signal, headers: { 'Accept': 'text/html' } })
      .then(function (r) {
        if (r.redirected) { window.location.href = r.url; return; }  // signed out
        if (!r.ok) { throw new Error('refresh failed'); }
        return r.text().then(function (html) {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var next = doc.getElementById('activity-body');
          if (!next) { throw new Error('unexpected page'); }
          if (window.KonaMap) { window.KonaMap.destroy(); }
          body.innerHTML = next.innerHTML;
          var hdr = doc.querySelector('.hdr .right'), here = document.querySelector('.hdr .right');
          if (hdr && here) { here.innerHTML = hdr.innerHTML; }  // the battery
          if (window.KonaMap) { window.KonaMap.init(); }
          succeeded = true;
        });
      })
      .catch(failed)
      .finally(function () {
        clearTimeout(deadline);
        busy = false;
        if (silent) { return; }
        bar.classList.remove('busy');
        bar.classList.add('finished');
        bar.classList.toggle('failed', !succeeded);
        label.textContent = succeeded ? 'Updated' : 'Could not refresh';
        dismissTimer = setTimeout(hide, 650);
      });
  }

  page.addEventListener('touchstart', function (e) {
    startY = null;
    if (busy || window.scrollY > 0 || e.touches.length !== 1) { return; }
    if (e.target.closest && e.target.closest('.leaflet-container')) { return; }  // map drags
    startY = e.touches[0].clientY;
    pulling = false;
  }, { passive: true });
  page.addEventListener('touchmove', function (e) {
    if (startY === null) { return; }
    if (e.touches.length !== 1) { cancel(); return; }
    var dy = (e.touches[0].clientY - startY) * RESISTANCE;
    if (dy <= 0 || window.scrollY > 0) {
      if (pulling) { pulling = false; hide(); }
      return;
    }
    pulling = true;
    show(dy);
  }, { passive: true });
  function end() {
    if (startY === null) { return; }
    var ready = bar.classList.contains('ready');
    startY = null;
    if (!pulling) { return; }
    pulling = false;
    if (ready) { refresh(true); } else { hide(); }
  }
  page.addEventListener('touchend', end);
  function cancel() { startY = null; pulling = false; if (!busy) { hide(); } }
  page.addEventListener('touchcancel', cancel);
  // Nothing on this page moved on its own until now. It rendered once and
  // sat there, so a dog could go out, walk, and come home while the screen
  // still showed where she was when the page opened -- which is how the map
  // came to look stuck during a walk on 2026-09-12. Three clocks stack up:
  // the collar reports every few minutes, the server asks Fi at most once
  // per KONA_FI_REFRESH_SECONDS, and the page asked for neither.
  //
  // This fixes the third. The tick is deliberately not a forced Fi call: it
  // collects whatever the server already has, and by asking at all it starts
  // the background refresh that the next tick will collect. So the page
  // follows the server's cadence instead of adding a second one on top of
  // somebody else's private API. Watching faster is the server's setting to
  // change, not this file's.
  //
  // It runs only while the page is actually on screen. A phone in a pocket
  // asks for nothing.
  var AUTO_REFRESH_MS = 60000;
  var ticker = null;
  function startTicking() {
    if (ticker === null) { ticker = setInterval(function () { refresh(false, true); }, AUTO_REFRESH_MS); }
  }
  function stopTicking() {
    if (ticker !== null) { clearInterval(ticker); ticker = null; }
  }
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stopTicking(); return; }
    refresh(true);
    startTicking();
  });
  startTicking();
  window.KonaRefresh = refresh;
})();

// Page zoom off, everywhere except the map.
//
// Chris asked for this directly and reaffirmed it after being told the cost:
// it is a WCAG 1.4.4 failure, and anyone who needs to enlarge text to read
// this page loses that. It is his app and his two readers. Recorded as a
// decision in docs/device-capabilities.md, with the one-line revert, because
// a deliberate accessibility trade must never look like an oversight.
//
// The viewport meta in base.html covers Chrome and Android. iOS Safari has
// ignored user-scalable since iOS 10 and needs these instead: `gesture*` are
// Safari's own pinch events, and a two-finger drag arrives as a touchmove
// that no meta tag stops. Both listeners must be non-passive to be able to
// preventDefault at all.
//
// The map is the exception and stays pinchable: Leaflet claims `touch-action`
// on .leaflet-container and does its own zooming, so pinching the map moves
// the map instead of the page. Excluding it here is what keeps that working.
(function () {
  function overTheMap(target) {
    return !!(target && target.closest && target.closest('.leaflet-container'));
  }
  ['gesturestart', 'gesturechange', 'gestureend'].forEach(function (name) {
    document.addEventListener(name, function (e) {
      if (!overTheMap(e.target)) { e.preventDefault(); }
    }, { passive: false });
  });
  document.addEventListener('touchmove', function (e) {
    // One finger is a scroll, or the pull-to-refresh above. Two is a pinch.
    if (e.touches.length > 1 && !overTheMap(e.target)) { e.preventDefault(); }
  }, { passive: false });
})();
