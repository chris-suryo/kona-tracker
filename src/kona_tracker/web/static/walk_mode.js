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
(function () {
  'use strict';

  var button = document.getElementById('walk-toggle');
  var note = document.getElementById('walk-note');
  if (!button) { return; }

  var busy = false;

  function draw(state) {
    if (!state || !state.offered) { return; }
    button.dataset.on = state.on ? 'true' : 'false';
    button.classList.toggle('on', !!state.on);
    button.textContent = state.label;
    if (note && state.note) { note.textContent = state.note; }
  }

  function fail(message) {
    if (note) { note.textContent = message; }
  }

  function send(on) {
    if (busy) { return; }
    busy = true;
    button.disabled = true;
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
          note: state.live
            ? 'Asking Fi every ' + state.every_seconds + ' s · stops in '
              + Math.max(1, Math.round((state.seconds_left || 0) / 60)) + ' min'
            : 'Ask Fi every ' + state.every_seconds + ' s while you are out'
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
        button.disabled = false;
      });
  }

  button.addEventListener('click', function () {
    send(button.dataset.on !== 'true');
  });

  window.KonaWalkMode = { draw: draw };
})();
