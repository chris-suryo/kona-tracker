"""One shared passcode, one signed cookie.

Why this shape: two people, one dog, no accounts. The passcode is compared in
constant time; the cookie is a signed timestamp (itsdangerous) so the server
keeps no session table and survives restarts if KONA_SECRET is set. A small
per-client failure counter makes a 6-digit code impractical to brute-force
without adding a database.

"Per-client" is the whole subtlety. The key is the peer address by default,
which is right on a LAN and wrong behind a tunnel: `cloudflared` connects
over localhost, so every visitor on earth arrives as 127.0.0.1 and would
share one bucket -- a stranger could lock the household out with five wrong
guesses. `client_key` therefore reads a forwarded-address header, but only
the one named in KONA_TRUSTED_PROXY_HEADER, and only when it is set. Trusting
`X-Forwarded-For` unconditionally is worse than not trusting it: anyone can
send that header and pick their own bucket.
"""

from __future__ import annotations

import hmac
import ipaddress
import threading
import time
from collections.abc import Mapping

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

COOKIE_NAME = "kona_session"


#: Where the tunnel connects from. `cloudflared` runs on the same machine
#: and reaches the app over localhost; KONA_TRUSTED_PROXY_IPS widens this
#: if it ever moves to another box.
LOOPBACK_PEERS: tuple[str, ...] = ("127.0.0.1", "::1")


def client_key(
    headers: Mapping[str, str],
    client_host: str,
    trusted_header: str = "",
    trusted_peers: tuple[str, ...] = LOOPBACK_PEERS,
) -> str:
    """Which lockout bucket this request belongs to.

    With no trusted header configured this is the peer address, full stop; a
    forwarded-address header that happens to be present is ignored, because
    nothing vouches for it. With one configured (e.g. `CF-Connecting-IP`
    behind cloudflared) its value is used when it parses as an IP address
    **and the request came from a trusted peer** -- the tunnel's own address.
    Anyone else, such as a Wi-Fi visitor reaching port 8000 directly, keeps
    their peer address as the key however many headers they send: honouring
    the header from every peer would let a LAN attacker pick a fresh bucket
    per guess and brute-force the passcode with no lockout at all.
    """
    if trusted_header and client_host in trusted_peers:
        raw = (headers.get(trusted_header) or "").strip()
        if raw:
            try:
                return str(ipaddress.ip_address(raw))
            except ValueError:
                pass
    return client_host


class Lockout:
    """A sliding window of recent failures per key, in memory.

    Keys come and go: with a trusted proxy header, every distinct visitor
    address is a key, so entries are dropped as soon as they hold nothing
    recent, and `blocked` never creates one. A run of strangers must not
    grow this dict without bound.
    """

    def __init__(self, attempts: int, seconds: int):
        self._attempts = attempts
        self._seconds = seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self._fails.get(key, ()) if now - t < self._seconds]

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = self._recent(key, now)
            if recent:
                self._fails[key] = recent
            else:
                self._fails.pop(key, None)
            return len(recent) >= self._attempts

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            # Sweep everyone whose window has closed, then record this one.
            for other in [
                k for k, times in self._fails.items() if now - times[-1] >= self._seconds
            ]:
                del self._fails[other]
            self._fails[key] = [*self._recent(key, now), now]

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def tracked(self) -> int:
        """How many keys are held right now (for tests and diagnostics)."""
        with self._lock:
            return len(self._fails)


class PasscodeAuth:
    def __init__(self, passcode: str, secret: str, max_age: int, lockout: Lockout):
        self._passcode = passcode.encode()
        self._signer = TimestampSigner(secret, salt="kona-session")
        self._max_age = max_age
        self.lockout = lockout

    def check(self, candidate: str) -> bool:
        return hmac.compare_digest(self._passcode, candidate.encode())

    def issue_cookie(self) -> str:
        return self._signer.sign(b"ok").decode()

    def valid_cookie(self, value: str | None) -> bool:
        if not value:
            return False
        try:
            return self._signer.unsign(value, max_age=self._max_age) == b"ok"
        except (BadSignature, SignatureExpired):
            return False
