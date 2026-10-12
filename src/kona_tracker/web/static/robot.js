// Robot tab. The picture loop is poll.js, shared with the Camera tab and
// pointed at the robot's own hub on the server. Nothing here moves the
// robot: driving is drive.js on its own landscape page, behind the Pi-side
// gateway's watchdog, and the front lights are led.js. This file starts the
// picture, and says what the battery reads.
window.KonaPoll({ cam: 'robot' });

// The battery, which until now only drive mode ever showed -- so the only
// way to find out the robot needed charging was to try to drive it. Read
// from the same /robot/telemetry drive mode polls, but every 30 s rather
// than every second: each read is a round trip to the Pi, and a battery
// does not change faster than that. Only while the page is visible.
(function () {
  var line = document.getElementById('robot-battery');
  if (!line) { return; }  // no gateway configured: nothing to ask
  var EVERY_MS = 30000, timer = null, busy = false;

  function say(text, cls) {
    line.textContent = text;
    line.className = 'robot-battery' + (cls ? ' ' + cls : '');
    line.hidden = false;
  }
  function read() {
    if (busy || document.hidden) { return; }
    busy = true;
    fetch('/robot/telemetry', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) { say('Robot not answering', 'quiet'); return; }
        // An unknown battery is not a flat one: the gateway's reads come
        // back empty routinely. drive.js makes the same call.
        if (typeof data.battery_v !== 'number') { say('Battery: no reading yet', 'quiet'); return; }
        var volts = data.battery_v.toFixed(2) + ' V';
        if (data.low_battery) { say('Battery low · ' + volts + ' · charge before driving', 'bad'); }
        else { say('Battery ' + volts); }
      })
      .catch(function () { say('Robot not answering', 'quiet'); })
      .then(function () { busy = false; });
  }
  function start() { if (!timer) { read(); timer = setInterval(read, EVERY_MS); } }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener('visibilitychange', function () { if (document.hidden) { stop(); } else { start(); } });
  if (!document.hidden) { start(); }
})();
