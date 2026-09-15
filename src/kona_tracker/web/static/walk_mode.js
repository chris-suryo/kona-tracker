// The "Start walk" button, on both the Activity page and the full map.
//
// Fi decides a walk has begun two to three minutes after it has. On a
// twenty-minute walk that is most of the first mile spent at the resting
// cadence, and no amount of polling on our side can hurry Fi's own
// detection. The person holding the lead already knows, so this lets them
// say it: press once and the server starts asking Fi every twenty seconds.
//
// The button never draws its own new state from the press. It posts, and
// redraws from what the server answers -- the same rule the camera switches
// follow. A button that says "Stop walk" because you tapped it, while the
// server never heard the request, is a lie that survives until you reload.
//
// Nothing here holds on to the button. The Activity page swaps its sections
// in from a fresh render every minute, and a section that changed arrives as
// a new node -- so a handler bound to the button at load was bound to a node
// that could be gone by the time of the first tap. That was a real bug: the
// button went dead after any refresh, silently. The click is caught on the
// document instead and the button looked up at the moment it is needed.
(function () {
  'use strict';

  if (!document.getElementById('walk-toggle')) { return; }

  var busy = false;

  function button() { return document.getElementById('walk-toggle'); }
  function note() { return document.getElementById('walk-note'); }

  function draw(state) {
    var b = button(), n = note();
    if (!b || !state || !state.offered) { return; }
    b.dataset.on = state.on ? 'true' : 'false';
    b.classList.toggle('on', !!state.on);
    b.textContent = state.label;
    if (n && state.note) { n.textContent = state.note; }
  }

  function fail(message) {
    var n = note();
    if (n) { n.textContent = message; }
  }

  function send(on) {
    if (busy) { return; }
    busy = true;
    var pressed = button();
    if (pressed) { pressed.disabled = true; }
    var body = new URLSearchParams();
    body.set('on', on ? 'true' : 'false');
    fetch('/live', { method: 'POST', body: body, headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) { throw new Error('live mode refused'); }
        return r.json();
      })
      .then(function (state) {
        // The server answers with its own state, not an echo of the press.
        draw({
          offered: true,
          on: !!state.live,
          label: state.live ? 'Stop walk' : 'Start walk',
          // Must match live_button() in views/map.py: the server renders this
          // caption on load and this redraws it after a press.
          note: state.live
            ? 'Stops on its own in '
              + Math.max(1, Math.round((state.seconds_left || 0) / 60)) + ' min'
            : ''
        });
        // The map page has a poller; wake it so the first fast fix is not
        // one whole resting interval away.
        if (window.KonaLiveMap && window.KonaLiveMap.poll) { window.KonaLiveMap.poll(); }
      })
      .catch(function () {
        fail('Could not reach the server just now. The button is unchanged.');
      })
      .then(function () {
        busy = false;
        // The one that was pressed, and the current one if a refresh has
        // replaced it in the meantime: a swapped-in button is never disabled.
        if (pressed) { pressed.disabled = false; }
        var now = button();
        if (now) { now.disabled = false; }
      });
  }

  document.addEventListener('click', function (e) {
    var target = e.target && e.target.closest ? e.target.closest('#walk-toggle') : null;
    if (!target) { return; }
    send(target.dataset.on !== 'true');
  });

  window.KonaWalkMode = { draw: draw };
})();
