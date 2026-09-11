"""The lockout key and the failure window, without a web app around them."""

from kona_tracker.web.auth import Lockout, client_key


def test_without_a_trusted_header_the_peer_address_is_the_key():
    """A forwarded-address header nobody vouches for must not pick the bucket.

    Behind a Cloudflare tunnel every visitor is 127.0.0.1, so this is the
    setting that must be turned on; unset, a forged CF-Connecting-IP or
    X-Forwarded-For is just noise.
    """
    headers = {"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.1"}
    assert client_key(headers, "127.0.0.1") == "127.0.0.1"
    assert client_key(headers, "127.0.0.1", "") == "127.0.0.1"


def test_a_trusted_header_counts_only_from_the_tunnels_own_peer():
    """The regression the security review caught: honouring the header from
    every peer lets a Wi-Fi visitor pick a fresh bucket per guess and
    brute-force the passcode with no lockout at all. cloudflared connects
    over localhost; nobody else's word for their address is taken."""
    header = {"CF-Connecting-IP": "203.0.113.9"}
    assert client_key(header, "127.0.0.1", "CF-Connecting-IP") == "203.0.113.9"
    assert client_key(header, "::1", "CF-Connecting-IP") == "203.0.113.9"
    assert client_key(header, "192.168.1.20", "CF-Connecting-IP") == "192.168.1.20"
    # The tunnel host can be somewhere else, if you say so.
    assert client_key(header, "10.0.0.5", "CF-Connecting-IP", ("10.0.0.5",)) == "203.0.113.9"
    assert client_key(header, "127.0.0.1", "CF-Connecting-IP", ("10.0.0.5",)) == "127.0.0.1"


def test_a_trusted_header_is_used_only_when_it_carries_an_address():
    assert client_key({"CF-Connecting-IP": " 203.0.113.9 "}, "127.0.0.1", "CF-Connecting-IP") == (
        "203.0.113.9"
    )
    assert client_key({"CF-Connecting-IP": "2001:db8::1"}, "127.0.0.1", "CF-Connecting-IP") == (
        "2001:db8::1"
    )
    # A LAN visitor bypassing the tunnel sends no header: their own address.
    assert client_key({}, "192.168.1.20", "CF-Connecting-IP") == "192.168.1.20"
    # Garbage in the header is not an address and earns no bucket of its own.
    assert client_key({"CF-Connecting-IP": "not-an-ip"}, "192.168.1.20", "CF-Connecting-IP") == (
        "192.168.1.20"
    )
    assert client_key({"CF-Connecting-IP": ""}, "192.168.1.20", "CF-Connecting-IP") == (
        "192.168.1.20"
    )


def test_lockout_forgets_clean_and_expired_keys():
    """With per-visitor keys open to the internet, memory must stay bounded.

    Driven by an injected clock rather than `time.sleep`. The sleeping
    version passed on Linux and flapped on the Windows CI leg, because
    `time.monotonic()` there advances in roughly 16ms steps and a 50ms
    window is only three of them. A test whose result depends on the
    platform's timer resolution is not testing the code.
    """
    now = [1000.0]
    lock = Lockout(attempts=2, seconds=30, clock=lambda: now[0])

    assert lock.blocked("a") is False
    assert lock.tracked() == 0, "asking must not create an entry"

    lock.fail("a")
    lock.fail("a")
    assert lock.blocked("a") is True and lock.tracked() == 1

    now[0] += 31  # a's window has closed
    lock.fail("b")  # a failure elsewhere sweeps it on the way past
    assert lock.tracked() == 1 and lock.blocked("a") is False
    lock.clear("b")
    assert lock.tracked() == 0
