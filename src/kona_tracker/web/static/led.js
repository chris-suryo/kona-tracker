// The robot's two front lights.
//
// **Why this control exists on the Robot tab and not in drive mode.** The
// gateway writes these over I2C directly -- the ultrasonic module at 0x77,
// registers 2-8, not the serial bus that owns the motors -- so they answer
// when `/health` reports the robot's own software down. They are the one
// control that still works on a robot that will not drive, which makes them
// most useful exactly where you look when nothing else is responding.
//
// **The rule this file follows.** Never draw from the press; always draw from
// what the robot answered. A toggle that flips on tap and then quietly fails
// is worse than one that takes 200 ms to move, because it teaches you to
// trust it. Same discipline as the camera switches in camera.js.
(function () {
  'use strict';

  var section = document.getElementById('led-settings');
  if (!section) { return; }
  var note = document.getElementById('led-note');
  var onOff = [].slice.call(section.querySelectorAll('[data-led-on]'));
  var swatches = [].slice.call(section.querySelectorAll('[data-led-rgb]'));
  var all = onOff.concat(swatches);

  // What the robot last told us. Kept so a colour press can turn the lights
  // on with the colour, and an On press can restore the colour rather than
  // sending black -- the gateway remembers a colour across an off, and this
  // keeps our idea of it in step with the gateway's.
  var known = { on: null, r: null, g: null, b: null };

  function rgbOf(el) {
    var parts = el.dataset.ledRgb.split(',');
    return { r: +parts[0], g: +parts[1], b: +parts[2] };
  }

  function same(a, b) { return a.r === b.r && a.g === b.g && a.b === b.b; }

  function draw(state) {
    known = state;
    // Four nulls is the gateway saying "nobody has set these since I
    // started". That is NOT off: a demo may have left them lit, or they may
    // be dark, and we have no way to tell. So nothing is drawn as pressed
    // and the note says so, rather than showing a confident Off.
    var unset = state.on === null || state.on === undefined;
    onOff.forEach(function (el) {
      el.disabled = false;
      el.setAttribute('aria-pressed', String(!unset && state.on === (el.dataset.ledOn === '1')));
    });
    swatches.forEach(function (el) {
      el.disabled = false;
      // A colour is "current" only while the lights are actually on. Marking
      // a swatch pressed under an Off state would claim the robot is showing
      // a colour it is not.
      el.setAttribute('aria-pressed', String(state.on === true && same(rgbOf(el), state)));
    });
    section.removeAttribute('data-pending');
    section.hidden = false;
    note.classList.remove('warn');
    note.textContent = unset
      ? 'Not set since the robot started, so we cannot say what they are showing.'
      : state.on
        ? 'On. They keep this colour until you change it.'
        : 'Off. Turning them back on restores this colour.';
  }

  function fail(message) {
    // Left visible and disabled rather than hidden: a section that vanishes
    // on a network blip reads as a feature that was never there.
    all.forEach(function (el) { el.disabled = true; });
    section.removeAttribute('data-pending');
    section.hidden = false;
    note.classList.add('warn');
    note.textContent = message;
  }

  // The gateway's own words when it has them -- `led_unavailable` means the
  // I2C write failed, which is a different problem from the gateway being
  // gone, and the two want different things from whoever is reading.
  function settle(response) {
    // `.json()` REJECTS on a non-JSON body, and a failing server is exactly
    // when the body stops being JSON -- a 500 page, a proxy's error, a login
    // redirect's HTML. Left unguarded that rejection became the message on
    // screen, and the screenshot on 2026-09-15 read: "Unexpected token 'I',
    // "Internal S"... is not valid JSON". Same shape as drive.js's post().
    return response.json().catch(function () { return {}; }).then(function (data) {
      if (!response.ok) {
        throw new Error(data && data.error
          ? data.error
          : 'The robot did not answer about its lights.');
      }
      draw({ on: data.on, r: data.r, g: data.g, b: data.b });
    });
  }

  function send(body) {
    all.forEach(function (el) { el.disabled = true; });
    note.classList.remove('warn');
    note.textContent = 'Asking the robot…';
    fetch('/robot/led', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body
    }).then(settle).catch(function (e) { fail(e.message); });
  }

  onOff.forEach(function (el) {
    el.addEventListener('click', function () {
      var on = el.dataset.ledOn === '1';
      // Send the colour either way. Off with a colour attached is what lets
      // the gateway remember it, and On with the last known colour is what
      // stops the lights coming back black after a gateway restart cleared
      // its memory. A colour we have never learned defaults to white, which
      // is the one value that cannot be mistaken for "it kept the old one".
      var c = known.r === null || known.r === undefined
        ? { r: 255, g: 255, b: 255 }
        : known;
      send('on=' + (on ? 'true' : 'false') + '&r=' + c.r + '&g=' + c.g + '&b=' + c.b);
    });
  });

  swatches.forEach(function (el) {
    el.addEventListener('click', function () {
      // Picking a colour turns them on. Setting a colour on lights that are
      // off would look like a broken button: you tap green and nothing on the
      // robot changes. The label under "Colour" says this out loud.
      var c = rgbOf(el);
      send('on=true&r=' + c.r + '&g=' + c.g + '&b=' + c.b);
    });
  });

  fetch('/robot/led', { cache: 'no-store' })
    .then(settle)
    .catch(function (e) { fail(e.message); });
})();
