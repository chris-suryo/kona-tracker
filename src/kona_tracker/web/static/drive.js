// Landscape drive mode. The picture is poll.js; this is everything that
// moves the robot, and everything that stops it.
//
// The robot holds a motor duty until another arrives -- nothing in its
// vendor stack ever expires a command -- so the real dead-man switch is the
// watchdog on the Pi, which zeroes the motors when drive commands stop
// landing. That is deliberately on the far side of the link, because the
// failure being guarded against is this phone or the PC going away.
//
// So this file has one job and one duty. The job: send a body velocity
// while a thumb is down, at the interval the server chose, and stop sending
// the instant it lifts. The duty: never let the screen say something the
// robot did not confirm. A stop that did not land is shouted about, not
// swallowed -- which is why it does not use camera.js's send(), whose
// `r.ok ? r.json() : null` turns every failure into a quiet nothing.
(function () {
  var root = document.getElementById('drive');
  if (!root) { return; }

  // The picture: the same loop and the same hub as the Robot tab. It runs
  // in portrait too, where CSS hides the view, so rotating the phone shows
  // a live frame rather than a reconnect.
  var lastFrameAt = 0;
  window.KonaPoll({ cam: 'robot', onFrame: function () { lastFrameAt = Date.now(); } });

  var stick = document.getElementById('stick'), knob = document.getElementById('knob');
  var estop = document.getElementById('estop'), speed = document.getElementById('speed');
  // The alarm's own STOP. It lives outside `.drive`, so it is the only
  // control that exists in portrait -- which is exactly the orientation the
  // alarm is most likely to be raised in, since rotating upright is a stop.
  var estopAlarm = document.getElementById('estop-alarm');
  var rotL = document.getElementById('rot-left'), rotR = document.getElementById('rot-right');
  var shout = document.getElementById('shout'), shoutText = document.getElementById('shout-text');
  var note = document.getElementById('note');
  var volts = document.getElementById('volts'), sonar = document.getElementById('sonar');
  var picture = document.getElementById('picture');

  // The send interval comes from the server so it cannot drift away from
  // the TTL it has to stay under. Both live in robot/gateway.py.
  var INTERVAL = parseInt(root.dataset.interval, 10) || 200;
  var TELEMETRY_MS = 1000;
  // No telemetry for this long and the page stops claiming the robot is
  // there. Three polls' grace: one may simply have been unlucky.
  var SILENT_MS = 3000;
  // The robot hub calls a picture stale after KONA_STALE_SECONDS (3 s), which
  // is right for watching a dog and far too slow for steering by it. This is
  // drive mode's own, stricter opinion; it changes nothing for the Camera tab.
  var PICTURE_STALE_MS = 600;
  var PICTURE_TICK_MS = 250;
  var RADIUS = 56;          // px of travel before the stick is at full tilt
  // The speed control caps the *velocity command*, not a pace. It used to be
  // labelled "Slow", which stopped being true on 2026-09-14: the gateway now
  // lifts every command above the motors' static-friction floor
  // (span = min_duty + (max_duty - min_duty) * peak), so with that robot's
  // 25/55 range a 0.4 stick asks for duty 37 -- Hiwonder's own cruising
  // speed, and above what used to be full throttle. The button said Slow and
  // the robot was not going slowly. It now says what it actually does.
  //
  // The duty range is a per-deployment environment variable on the Pi, which
  // is why min_duty/max_duty arrive in telemetry: this page must never
  // hardcode them, and does not.
  var SPEED_CAP = 0.4;
  var STOP_RETRY_MS = 700;

  var stickVec = { x: 0, y: 0 };   // -1..1, screen axes
  var spin = 0;                    // -1 left, +1 right
  var pointer = null;              // the pointerId driving the stick
  var sending = false;             // exactly one command in flight
  var driving = false;             // a thumb is down somewhere
  var capped = true;
  var ticker = null, stopRetry = null;
  var lastTelemetry = 0, telemetryEverOk = false;
  // Two independent reasons to shout, kept apart so neither can erase the
  // other: `owed` is the gateway telling us the board may still hold duty,
  // `failure` is our own last stop or drive that did not land.
  var owed = false, failure = '';
  // Set once telemetry reports the robot's duty range; null until then.
  var dutyAt = null;

  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body || ''
    }).then(function (r) {
      if (r.redirected) { window.location.href = r.url; throw new Error('signed out'); }
      // The body carries the reason on every failure; read it before
      // deciding what happened, never just the status.
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { throw new Error(data.error || 'The robot did not answer.'); }
        return data;
      });
    });
  }

  function renderShout() {
    // `owed` outranks our own failure: "it may still be moving" is the more
    // urgent of the two, and clearing it is the gateway's call, not ours.
    var message = owed
      ? 'The robot may still be moving. The gateway has not had a stop confirmed.'
      : failure;
    if (message) { shoutText.textContent = message; }
    shout.hidden = !message;
  }
  function shoutAt(message) { failure = message; renderShout(); }
  function quiet() { failure = ''; renderShout(); }

  // -- stopping ------------------------------------------------------------
  // Every path that ends a drive comes through here. It keeps retrying on
  // its own, because a failed stop is not a thing to report once and move
  // on from: the robot may still be moving.
  function stopNow(why) {
    driving = false;
    spin = 0;
    stickVec = { x: 0, y: 0 };
    place(0, 0);
    clearInterval(ticker); ticker = null;
    clearTimeout(stopRetry); stopRetry = null;
    post('/robot/stop').then(function () {
      quiet();
    }).catch(function (e) {
      if (e.message === 'signed out') { return; }
      // Always lead with the fact, then the reason. Once gateway reasons
      // became sentences, this branch started showing "the robot's software
      // is not answering" *instead of* "the stop did not reach the robot" --
      // a true sentence that buries the only part that matters, which is
      // that the wheels may still be turning. Caught in a screenshot.
      shoutAt('The stop did not reach the robot. ' +
        (e.message === 'The robot did not answer.' ? 'Retrying…' : e.message));
      stopRetry = setTimeout(function () { stopNow(why); }, STOP_RETRY_MS);
    });
  }

  // The last stop of all, when the page is being torn down and a fetch
  // would be cancelled with it. sendBeacon survives that; the watchdog on
  // the Pi is the backstop if even this does not land.
  function beaconStop() {
    if (navigator.sendBeacon) {
      try {
        navigator.sendBeacon('/robot/stop', new Blob([''], {
          type: 'application/x-www-form-urlencoded'
        }));
      } catch (e) { /* nothing left to tell */ }
    }
  }

  // -- driving -------------------------------------------------------------
  function scale() { return capped ? SPEED_CAP : 1; }

  function tick() {
    if (sending || !driving) { return; }
    sending = true;
    // Screen axes to body axes: up is forward, left is +vy (the gateway's
    // convention, and it owns the mecanum kinematics and the wiring).
    var vx = -stickVec.y * scale();
    var vy = -stickVec.x * scale();
    var omega = spin * scale();
    post('/robot/drive', 'vx=' + vx.toFixed(3) + '&vy=' + vy.toFixed(3) + '&omega=' + omega.toFixed(3))
      .then(function () { quiet(); })
      .catch(function (e) {
        if (e.message === 'signed out') { return; }
        // The watchdog stops the robot on its own within one TTL, so the
        // honest thing is to say so and let go, not to keep hammering.
        shoutAt(e.message);
        driving = false;
        clearInterval(ticker); ticker = null;
        place(0, 0);
      })
      .then(function () { sending = false; }, function () { sending = false; });
  }

  function begin() {
    if (driving) { return; }
    driving = true;
    tick();
    clearInterval(ticker);
    ticker = setInterval(tick, INTERVAL);
  }

  function place(x, y) {
    knob.style.transform = x || y
      ? 'translate(' + (x * RADIUS).toFixed(1) + 'px,' + (y * RADIUS).toFixed(1) + 'px)'
      : '';
  }

  function atPoint(e) {
    var box = stick.getBoundingClientRect();
    var x = (e.clientX - (box.left + box.width / 2)) / RADIUS;
    var y = (e.clientY - (box.top + box.height / 2)) / RADIUS;
    var length = Math.hypot(x, y);
    // Clamp into the unit disk rather than the square: a corner would ask
    // for 1.41x and the gateway would normalise it, changing the direction
    // the robot actually travels.
    if (length > 1) { x /= length; y /= length; }
    stickVec = { x: x, y: y };
    place(x, y);
  }

  stick.addEventListener('pointerdown', function (e) {
    if (stick.getAttribute('aria-disabled') === 'true') { return; }
    pointer = e.pointerId;
    stick.setPointerCapture(e.pointerId);
    stick.classList.add('held');
    atPoint(e);
    begin();
    e.preventDefault();
  });
  stick.addEventListener('pointermove', function (e) {
    if (pointer !== e.pointerId || !driving) { return; }
    atPoint(e);
    e.preventDefault();
  });
  // pointerup, pointercancel and a lost capture all mean the same thing:
  // nobody is holding this any more.
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) {
    stick.addEventListener(name, function (e) {
      if (pointer !== e.pointerId) { return; }
      pointer = null;
      stick.classList.remove('held');
      stopNow('released');
    });
  });

  [[rotL, -1], [rotR, 1]].forEach(function (pair) {
    var button = pair[0], direction = pair[1];
    button.addEventListener('pointerdown', function (e) {
      if (button.disabled) { return; }
      spin = direction;
      begin();
      e.preventDefault();
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (name) {
      button.addEventListener(name, function () {
        if (spin === direction) { stopNow('rotate released'); }
      });
    });
  });

  estop.addEventListener('click', function () { stopNow('e-stop'); });
  if (estopAlarm) { estopAlarm.addEventListener('click', function () { stopNow('e-stop'); }); }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { stopNow('escape'); }
  });

  function drawSpeed() {
    var percent = Math.round((capped ? SPEED_CAP : 1) * 100);
    speed.textContent = 'Speed ' + percent + '%';
    speed.setAttribute('aria-pressed', String(!capped));
    // The duty is the robot's own number and only arrives with telemetry, so
    // it is an aria detail rather than something the pill claims on its own.
    speed.setAttribute('aria-label', 'Speed limit ' + percent + ' percent' + (dutyAt
      ? ', motor duty ' + dutyAt(capped ? SPEED_CAP : 1)
      : ''));
  }
  speed.addEventListener('click', function () {
    capped = !capped;
    drawSpeed();
  });

  // Anything that takes the operator's attention away stops the robot. The
  // watchdog would too, half a second later; this is the half that does not
  // rely on the link still working.
  window.addEventListener('blur', function () { stopNow('blur'); });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stopNow('hidden'); }
  });
  window.addEventListener('pagehide', function () { stopNow('pagehide'); beaconStop(); });
  window.addEventListener('orientationchange', function () { stopNow('rotated'); });
  if (window.matchMedia) {
    var portrait = window.matchMedia('(orientation: portrait)');
    var onChange = function (e) { if (e.matches) { stopNow('portrait'); } };
    if (portrait.addEventListener) { portrait.addEventListener('change', onChange); }
  }

  // -- telemetry -----------------------------------------------------------
  function allow(enabled, why) {
    stick.setAttribute('aria-disabled', String(!enabled));
    rotL.disabled = rotR.disabled = !enabled;
    if (!enabled && driving) { stopNow(why); }
  }

  function draw(data) {
    telemetryEverOk = true;
    lastTelemetry = Date.now();

    // An unknown battery is not a flat one. The gateway's own reads come
    // back empty routinely (it pops a queue the robot's thread drains), and
    // refusing to drive on a missed read would look identical to a dead
    // cell. Say "unknown" and carry on.
    if (typeof data.battery_v === 'number') {
      volts.textContent = data.battery_v.toFixed(2) + ' V';
      volts.className = 'v' + (data.low_battery ? ' bad' : '');
    } else {
      volts.textContent = 'unknown';
      volts.className = 'v unknown';
    }
    if (typeof data.sonar_mm === 'number') {
      sonar.textContent = (data.sonar_mm / 1000).toFixed(2) + ' m';
      sonar.className = 'v' + (data.sonar_mm < 250 ? ' bad' : '');
    } else {
      sonar.textContent = 'unknown';
      sonar.className = 'v unknown';
    }

    // `stop_owed` means the gateway has never had an all-zero acknowledged,
    // so the board may still be holding duty. It is TRUE throughout normal
    // driving -- that is its job -- so the alarm is stop_owed WITHOUT a live
    // command: nothing is being asked for, and nothing has confirmed a stop.
    // That is exactly the window their watchdog retries into, and until it
    // wins, the wheels may still be turning.
    owed = data.stop_owed === true && data.driving !== true;
    renderShout();

    // The gateway lifts commands above the motors' stiction floor, and the
    // range is deployment-specific. Once it has told us, we can say what a
    // speed setting really asks the motors for instead of guessing.
    if (typeof data.min_duty === 'number' && typeof data.max_duty === 'number') {
      dutyAt = function (v) {
        return Math.round(data.min_duty + (data.max_duty - data.min_duty) * v);
      };
      drawSpeed();
    }

    var words = [];
    // False means the robot's own GetRunningFunc is unpatched, so the
    // gateway cannot tell whether a built-in demo is driving. Saying
    // nothing would imply a guard that is not running.
    if (data.demo_detection === false) {
      words.push('The robot cannot tell whether a built-in demo is running, so that guard is off.');
    }
    if (data.demo) { words.push('A built-in demo is driving: manual control is refused until it stops.'); }
    // Same family as demo_detection: a guard that cannot run must be said out
    // loud, not left to look like a guard that is running and finding nothing.
    if (data.sonar_usable === false) {
      words.push('The robot cannot read its distance sensor, so the obstacle guard is off.');
    }
    note.textContent = words.join(' ');
    note.hidden = words.length === 0;
    note.className = 'drive-note';

    allow(!data.low_battery && !data.demo, 'refused');
  }

  function drawPicture() {
    if (!lastFrameAt) {
      picture.textContent = 'waiting';
      picture.className = 'v unknown';
      return;
    }
    var age = Date.now() - lastFrameAt;
    if (age < PICTURE_STALE_MS) {
      picture.textContent = 'live';
      picture.className = 'v';
      return;
    }
    // Said in seconds because that is how it is felt: at half a second you
    // are steering something that is already somewhere else.
    picture.textContent = (age / 1000).toFixed(1) + ' s behind';
    picture.className = 'v bad';
  }

  function lost(message) {
    volts.textContent = sonar.textContent = 'unknown';
    volts.className = sonar.className = 'v unknown';
    note.textContent = message;
    note.className = 'drive-note gone';
    note.hidden = false;
    allow(false, 'robot lost');
  }

  function poll() {
    fetch('/robot/telemetry', { cache: 'no-store' }).then(function (r) {
      if (r.redirected) { window.location.href = r.url; throw new Error('signed out'); }
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { throw new Error(data.error || 'The robot did not answer.'); }
        return data;
      });
    }).then(draw).catch(function (e) {
      if (e.message === 'signed out') { return; }
      // Never keep showing a reading as if it were live. Until the first
      // success there is nothing to go stale, so say what is happening.
      if (!telemetryEverOk || Date.now() - lastTelemetry > SILENT_MS) { lost(e.message); }
    });
  }
  poll();
  setInterval(poll, TELEMETRY_MS);
  drawPicture();
  setInterval(drawPicture, PICTURE_TICK_MS);
  // A poll that hangs rather than fails would leave the strip looking live.
  setInterval(function () {
    if (telemetryEverOk && Date.now() - lastTelemetry > SILENT_MS) {
      lost('No answer from the robot for a few seconds.');
    }
  }, SILENT_MS);

  allow(false, 'not yet known');
})();
