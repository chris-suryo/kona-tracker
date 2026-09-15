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
  var look = document.getElementById('look'), lookKnob = document.getElementById('look-knob');
  var shout = document.getElementById('shout'), shoutText = document.getElementById('shout-text');
  var note = document.getElementById('note');
  var volts = document.getElementById('volts'), sonar = document.getElementById('sonar');
  var picture = document.getElementById('picture');
  var wireLabel = document.getElementById('wire');
  var legend = document.getElementById('legend');

  // The watchdog window, stated on the HUD as a fact about the robot and
  // never sent back to it: this page does not choose its own dead-man
  // switch. Both numbers come from robot/gateway.py through the template.
  var TTL = parseInt(root.dataset.ttl, 10) || 0;

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
  var LOOK_RADIUS = 44;     // the look stick is smaller; its own travel
  // The gateway clamps pan and tilt to this and so do we, for the same
  // reason it does: a servo driven into its mechanical stop stalls, draws
  // full current and strips its own gears. Kept equal to LOOK_LIMIT_DEG in
  // robot/gateway.py -- if that ever moves, this moves with it.
  var LOOK_LIMIT_DEG = 45;
  // A servo command every 200ms would be five writes a second into an RPC
  // server that handles one request at a time and already carries the drive
  // loop. Aiming a camera does not need that rate: the eye cannot tell 6 Hz
  // from 20, and a dropped intermediate position is invisible because the
  // last one sent is the one that sticks.
  var LOOK_INTERVAL_MS = 160;
  // Below this the servo would be asked to move less than its own backlash,
  // so the request is noise. In degrees.
  var LOOK_EPSILON_DEG = 1.5;
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
  // The drive socket, when one is open. Null means every command goes over
  // HTTP, which is the original path and still the fallback.
  var wire = null;
  // Where the camera is pointed, in degrees, as far as we know. Not reset
  // on release: a servo holds where it is put, and this is our record of
  // that rather than a command in flight.
  var lookPan = 0, lookTilt = 0;
  var lookPointer = null, lookSent = 0, lookTimer = null, lookInFlight = false;
  var lookLastTap = 0;
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

  // -- the fast path -------------------------------------------------------
  //
  // Over HTTP this page could only send as fast as the round trip allowed:
  // `sending` holds one command in flight so they cannot pile up, which on
  // Chris's 700 ms LTE link capped it near 1.5 commands a second against a
  // 500 ms TTL. The robot session measured what that does -- the gateway's
  // watchdog firing seven times in six seconds with the stick held down.
  //
  // A socket has no round trip in the send path. Frames go out back to back
  // and the server pushes the latest one to the Pi on its own steady clock,
  // so the robot sees one rate whatever the phone's connection is doing.
  //
  // It is strictly an optimisation: everything still works with `wire` null,
  // which is what happens on a browser without WebSocket, behind a proxy that
  // will not upgrade, or after the socket drops. Nothing below may become
  // load-bearing for stopping -- `stopNow` stays on HTTP, because a stop is
  // the one thing that has to be *watched* landing.

  // Says which transport is carrying commands right now. "polling" is not a
  // failure -- it is the original path and it works -- but it is 1.5 commands
  // a second on a 700 ms link against 4.5 on the socket, and knowing which
  // one you are on is the difference between diagnosing lag and guessing at it.
  function showWire(state) {
    if (!wireLabel) { return; }
    wireLabel.textContent = state;
    wireLabel.className = 'v' + (state === 'socket' ? '' : ' unknown');
  }

  function openWire() {
    showWire('polling');
    if (!window.WebSocket) { return; }
    var url;
    try {
      url = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
        window.location.host + '/robot/ws/drive';
    } catch (e) { return; }
    var socket;
    try { socket = new window.WebSocket(url); } catch (e) { return; }
    socket.onopen = function () { wire = socket; showWire('socket'); };
    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data && data.ok === false) {
        // Same handling as a failed POST: the watchdog stops the robot on
        // its own within one TTL, so say so and let go rather than hammer.
        shoutAt(data.error || 'The robot did not answer.');
        letGo();
      }
    };
    // A closed socket is not an error worth showing -- the HTTP path picks
    // it straight back up, and the person is mid-drive. It is not reopened
    // on a timer either: a reconnect loop under a thumb would be a second
    // command stream fighting the first. Coming back to the page is when it
    // is retried; see the visibilitychange handler below.
    socket.onclose = function () { if (wire === socket) { wire = null; showWire('polling'); } };
    socket.onerror = function () { if (wire === socket) { wire = null; showWire('polling'); } };
  }

  // Lock the phone with drive mode open and iOS closes the socket. Without
  // this the page would spend the rest of its life on the slow path, having
  // silently downgraded at the moment nobody was looking -- which is the
  // normal way this page gets used: open it, put the phone down, come back.
  //
  // Only while not driving. Opening a second socket under a held thumb would
  // be two command streams into a robot, and the server's newest-wins rule
  // would be arbitrating a race this page started.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden || driving || wire) { return; }
    openWire();
  });

  // Both transports, one door. Returns true when the socket took it, so the
  // caller knows whether to expect a promise.
  function pushDrive(vx, vy, omega) {
    if (!wire || wire.readyState !== 1) { return false; }
    try {
      wire.send(JSON.stringify({ vx: +vx.toFixed(3), vy: +vy.toFixed(3), omega: +omega.toFixed(3) }));
      return true;
    } catch (e) {
      wire = null;
      showWire('polling');
      return false;
    }
  }

  function pushStop() {
    if (!wire || wire.readyState !== 1) { return; }
    try { wire.send('{"stop":true}'); } catch (e) { wire = null; showWire('polling'); }
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
    // Down the socket too, where there is one: it arrives without waiting
    // for a round trip. It does NOT replace the POST below -- this one
    // cannot be watched landing, and a stop that was not confirmed is the
    // most dangerous state this page can be in. Both, always.
    pushStop();
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

  // Stop sending, without claiming a stop landed. The gateway's watchdog
  // zeroes the motors within one TTL of commands ceasing, so the honest
  // thing after a failure is to say so and let go -- not to keep hammering
  // a robot that is not listening. Shared by both transports so the socket
  // and the POST path cannot come to disagree about what a failure does.
  function letGo() {
    driving = false;
    clearInterval(ticker); ticker = null;
    place(0, 0);
  }

  function tick() {
    if (!driving) { return; }
    // Screen axes to body axes: up is forward, left is +vy (the gateway's
    // convention, and it owns the mecanum kinematics and the wiring).
    var vx = -stickVec.y * scale();
    var vy = -stickVec.x * scale();
    var omega = spin * scale();
    // The socket first, and without the `sending` gate: that gate exists
    // because an HTTP command in flight must not be joined by another, and
    // a frame on an open socket is neither in flight nor cancellable. Errors
    // arrive later, on the socket, and are handled there.
    if (pushDrive(vx, vy, omega)) { quiet(); return; }
    if (sending) { return; }
    sending = true;
    post('/robot/drive', 'vx=' + vx.toFixed(3) + '&vy=' + vy.toFixed(3) + '&omega=' + omega.toFixed(3))
      .then(function () { quiet(); })
      .catch(function (e) {
        if (e.message === 'signed out') { return; }
        shoutAt(e.message);
        letGo();
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

  // -- looking around ------------------------------------------------------
  //
  // The second stick. Chris asked for it twice: "I'd rather have two
  // joysticks: one controls the movement, and the other two control pan and
  // look around", and later "the pan up and down with the camera hasn't been
  // done". Left thumb drives, right thumb looks, the way a twin-stick game
  // lays it out.
  //
  // **It is not a dead-man control, and that is the important difference.**
  // Everything else on this page stops when you let go, because everything
  // else moves a two-kilogram robot across a floor. A servo holds where it is
  // put, and a camera that snapped back to level on every release would be
  // useless for the one thing this is for: looking around a room. So the knob
  // stays where you left it and `lookPan`/`lookTilt` are our record of where
  // the camera is, not of a command in flight.
  //
  // Degrees are absolute and sent as such. The gateway's `/look` takes a
  // position, not a rate, so there is no integration here and no drift.
  function placeLook() {
    var x = lookPan / LOOK_LIMIT_DEG;
    var y = -lookTilt / LOOK_LIMIT_DEG;
    lookKnob.style.transform = x || y
      ? 'translate(' + (x * LOOK_RADIUS).toFixed(1) + 'px,' + (y * LOOK_RADIUS).toFixed(1) + 'px)'
      : '';
  }

  function sendLook() {
    // One in flight at a time, and the newest wins. Unlike a drive command,
    // a superseded look is genuinely worthless: only the last position
    // matters, and queueing them would walk the servo through every
    // intermediate point a thumb passed over.
    if (lookInFlight) { return; }
    var pan = lookPan, tilt = lookTilt;
    lookInFlight = true;
    lookSent = Date.now();
    post('/robot/look', 'pan_deg=' + pan.toFixed(1) + '&tilt_deg=' + tilt.toFixed(1))
      .then(function () { quiet(); })
      .catch(function (e) {
        if (e.message === 'signed out') { return; }
        // Said, but not escalated: a camera that did not turn is a
        // disappointment, where a robot that did not stop is a hazard. It
        // does not call letGo(), because driving is unaffected.
        shoutAt(e.message);
      })
      .then(function () {
        lookInFlight = false;
        // A move that arrived while the last one was in flight is still
        // pending; land it now rather than leave the camera short of where
        // the thumb finished.
        if (pan !== lookPan || tilt !== lookTilt) { scheduleLook(); }
      }, function () { lookInFlight = false; });
  }

  function scheduleLook() {
    if (lookTimer) { return; }
    var wait = Math.max(0, LOOK_INTERVAL_MS - (Date.now() - lookSent));
    lookTimer = setTimeout(function () { lookTimer = null; sendLook(); }, wait);
  }

  function aim(pan, tilt) {
    pan = Math.max(-LOOK_LIMIT_DEG, Math.min(LOOK_LIMIT_DEG, pan));
    tilt = Math.max(-LOOK_LIMIT_DEG, Math.min(LOOK_LIMIT_DEG, tilt));
    // The knob moves immediately and the request is throttled behind it.
    // This is the one place on this page where drawing ahead of the robot is
    // right: the alternative is a stick that lags a thumb by 160ms, which
    // feels broken, and a wrong camera angle costs nothing.
    var moved = Math.abs(pan - lookPan) >= LOOK_EPSILON_DEG ||
                Math.abs(tilt - lookTilt) >= LOOK_EPSILON_DEG;
    lookPan = pan;
    lookTilt = tilt;
    placeLook();
    if (moved) { scheduleLook(); }
  }

  function aimAt(e) {
    var box = look.getBoundingClientRect();
    var x = (e.clientX - (box.left + box.width / 2)) / LOOK_RADIUS;
    var y = (e.clientY - (box.top + box.height / 2)) / LOOK_RADIUS;
    var length = Math.hypot(x, y);
    // The unit disk, as the drive stick does it: a corner would ask for 1.41x
    // and clamping the two axes separately would bend the direction.
    if (length > 1) { x /= length; y /= length; }
    // Screen up is tilt up. The gateway's sign convention for tilt is not
    // documented and has never been checked on hardware -- which is exactly
    // what docs/robot-measurements.md asks Chris to find out. If it comes
    // back inverted it is one minus sign, here.
    aim(x * LOOK_LIMIT_DEG, -y * LOOK_LIMIT_DEG);
  }

  if (look && lookKnob) {
    look.addEventListener('pointerdown', function (e) {
      if (look.getAttribute('aria-disabled') === 'true') { return; }
      // Double-tap near the middle levels the camera. The centre dot is the
      // target, and it is the only way back once you have aimed somewhere --
      // dragging to exactly zero by thumb is not a thing anyone manages.
      var now = Date.now();
      if (now - lookLastTap < 300) {
        lookLastTap = 0;
        aim(0, 0);
        scheduleLook();
        e.preventDefault();
        return;
      }
      lookLastTap = now;
      lookPointer = e.pointerId;
      look.setPointerCapture(e.pointerId);
      look.classList.add('held');
      aimAt(e);
      e.preventDefault();
    });
    look.addEventListener('pointermove', function (e) {
      if (lookPointer !== e.pointerId) { return; }
      aimAt(e);
      e.preventDefault();
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) {
      look.addEventListener(name, function (e) {
        if (lookPointer !== e.pointerId) { return; }
        lookPointer = null;
        look.classList.remove('held');
        // One last send, so the camera ends where the thumb did rather than
        // wherever the throttle happened to last fire.
        scheduleLook();
      });
    });
  }

  // Rotate left is POSITIVE omega. The gateway's frame is "vx forward, vy
  // left, omega counter-clockwise" (robot_gateway.py, wheel_duties), and
  // counter-clockwise seen from above is a left turn -- so the left button
  // sends +1. These were the other way round until 2026-09-15, when Chris
  // drove the robot for the first time and reported "the left and right
  // turns are reversed". Ours, not theirs: the gateway matches its own
  // documented contract, and we were sending the opposite sign.
  //
  // Fixed here rather than on the Pi for that reason. A negation on their
  // side would have made every other client wrong instead.
  [[rotL, 1], [rotR, -1]].forEach(function (pair) {
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
    // The look stick goes with them. Unlike the LEDs -- which the gateway
    // drives straight over I2C and which therefore survive the robot's own
    // software dying -- `/look` goes through the RPC server on port 9030,
    // the same one that owns the motors. Every reason this is called with
    // false means that server is unreachable or busy.
    //
    // The arguable case is `low_battery`: the gateway's refusal is about the
    // motors, and a servo on a flat pack might well still answer. Nobody has
    // checked, so it is disabled with everything else -- a control that is
    // dead when it need not be is a smaller fault than one that silently
    // does nothing, and it is the state the battery reading already explains.
    if (look) { look.setAttribute('aria-disabled', String(!enabled)); }
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
    if (words.length) {
      note.textContent = words.join(' ');
      note.className = 'drive-note';
    } else {
      // Nothing wrong is worth a line too. Before this the HUD was blank
      // until something failed, so a second driver had no way to tell "all
      // good" from "not connected yet". The one fact worth stating is the
      // dead-man window, because it is the thing that makes letting go safe.
      note.textContent = 'Ready' + (TTL ? ' \u00b7 let go and she stops within ' + (TTL / 1000) + ' s' : '');
      note.className = 'drive-note calm';
    }
    note.hidden = false;

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

  // -- the first-drive legend --------------------------------------------
  // Shown the first time this page opens on a phone, and never again unless
  // the Robot tab's "Show me the controls again" link asks (?legend=1). The
  // choice lives in localStorage like the theme does, with the same rule:
  // storage that throws (private browsing, blocked site data) is never worth
  // a broken page, and on the side of saying too much -- a legend that shows
  // again is a nuisance, a driver who never saw it is the problem.
  var SEEN = 'kona-drive-seen';
  function legendSeen() {
    try { return window.localStorage.getItem(SEEN) === '1'; } catch (e) { return false; }
  }
  function legendDismissed() {
    try { window.localStorage.setItem(SEEN, '1'); } catch (e) { /* lasts until the page closes */ }
  }
  function askedForLegend() {
    var search = (window.location && window.location.search) || '';
    return /(^\?|&)legend=1(&|$)/.test(search);
  }
  if (legend) {
    if (askedForLegend() || !legendSeen()) { legend.hidden = false; }
    legend.addEventListener('click', function (e) {
      legend.hidden = true;
      legendDismissed();
      // The legend covers STOP for as long as it is up. A first-time driver
      // whose first instinct is the big red button must get a stop, not a
      // dismissal and a second tap: if the tap landed where STOP is, it is
      // a STOP. The security review of this page named the one-tap window;
      // this closes it. (elementsFromPoint is everywhere the page runs; the
      // guard is for the test harness.)
      var under = document.elementsFromPoint ? document.elementsFromPoint(e.clientX, e.clientY) : [];
      if (under.indexOf(estop) !== -1) { stopNow('e-stop'); }
    });
  }

  // Opened last, once everything it can call into exists. Failing to open
  // costs nothing: every command falls back to the HTTP path above.
  openWire();

  allow(false, 'not yet known');
})();
