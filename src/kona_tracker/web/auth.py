"""One shared passcode, one signed cookie.

Why this shape: two people, one dog, no accounts. The passcode is compared in
constant time; the cookie is a signed timestamp (itsdangerous) so the server
keeps no session table and survives restarts if KONA_SECRET is set. A small
per-IP failure counter makes a 6-digit code impractical to brute-force from
the LAN without adding a database.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

COOKIE_NAME = "kona_session"


class Lockout:
    def __init__(self, attempts: int, seconds: int):
        self._attempts = attempts
        self._seconds = seconds
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails[key] if now - t < self._seconds]
            self._fails[key] = recent
            return len(recent) >= self._attempts

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


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
