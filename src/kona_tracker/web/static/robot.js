// Robot tab. The picture loop is poll.js, shared with the Camera tab and
// pointed at the robot's own hub on the server. Nothing here can move the
// robot: driving arrives only once the Pi-side safety service exists, and
// it will be its own block below this one, not a change to the loop.
window.KonaPoll({ cam: 'robot' });
