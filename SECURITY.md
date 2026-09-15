# Security

This is a personal project: one household, two people, one dog. It is not a
product and has no users to notify.

## Reporting something

Open an issue, or use GitHub's private vulnerability reporting on this
repository. There is no SLA. If it is serious and you would rather not file it
publicly, the private report is the right channel.

## What this app assumes

The threat model is written down in the code rather than here, but the short
version:

- **One shared passcode, no accounts.** Anyone who has it can see the camera
  and drive the robot. Treat it as a house key.
- **It is meant for a LAN or a tunnel, not the open internet.** There is no
  HSTS and the LAN address is plain HTTP on purpose. `docs/remote-access.md`
  covers the two supported ways to reach it from outside (a Cloudflare tunnel
  and Tailscale) and the one setting that silently breaks login if it is
  wrong. Port-forwarding it to the internet is not supported.
- **The robot's dead-man switch runs on the Pi, not in the browser.** The page
  cannot choose how long a motor command survives.
- **Secrets live in `.env`**, which is gitignored and has never been
  committed. `probe-out/` likewise. A test walks the tree on every CI run and
  fails if a home-network address or a username reappears in the docs.

## Dependencies

Runtime dependencies are pinned by `uv.lock`. Leaflet and Bricolage Grotesque
are vendored rather than loaded from a CDN, and both are pinned by sha256 in
`tests/test_web.py`; changing either without updating the hash fails CI.
