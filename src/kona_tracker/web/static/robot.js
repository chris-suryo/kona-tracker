// Robot tab. The picture loop is poll.js, shared with the Camera tab and
// pointed at the robot's own hub on the server. Nothing here moves the
// robot: driving is drive.js on its own landscape page, behind the Pi-side
// gateway's watchdog, and the front lights are led.js. This file only
// starts the picture.
window.KonaPoll({ cam: 'robot' });
