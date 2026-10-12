"""The Settings page's two status lists: the collar, and this server.

Settings used to hold only what a person can change, on the rule that status
belongs on the tab it describes. That left the one question with no page to
answer it -- "is everything working?" -- and left half a screen empty. These
lists answer it in words, from state the server already holds: nothing here
asks Fi, the camera or the database for anything.

Each row is `{"label", "value", "warn"}`; `warn` colours the value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views.format import _clock, _since, kona_zone

CAMERA_WORDS = {
    "live": ("Live", False),
    "idle": ("Idle · opens when someone watches", False),
    "connecting": ("Connecting", False),
    "stale": ("Picture stopped updating", True),
    "disconnected": ("Not connected", True),
}


def _row(label: str, value: str, warn: bool = False) -> dict[str, Any]:
    return {"label": label, "value": value, "warn": warn}


def ago(seconds: float | None) -> str | None:
    """`just now`, `4 min ago`, `3 h ago`, `2 days ago`."""
    if seconds is None:
        return None
    s = max(0, int(seconds))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 2 * 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def size_label(size_bytes: int | None) -> str | None:
    if size_bytes is None:
        return None
    if size_bytes < 1024 * 1024:
        return f"{max(1, round(size_bytes / 1024))} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def collar_rows(snapshot: FiSnapshot | None) -> list[dict[str, Any]]:
    """What the collar itself reports. Empty when there is no reading.

    No battery percentage, which the Activity header already shows, and no
    "time left": `timeToEmptyS` read 4.3 days on the charger and 12
    hours with cellular on. It is a power estimate, not a fact about the
    battery, and the Activity page already decided against it.
    """
    status = snapshot.status if snapshot else None
    if status is None:
        return []
    zone = kona_zone(snapshot.profile.timezone if snapshot.profile else None)
    rows = []
    # Not the battery percentage: it is in the Activity header, and this page
    # does not repeat it (test_profile_page_holds_personal_actions...). Being
    # on the charger is shown nowhere else.
    if status.on_base is not None:
        rows.append(_row("Charger", "On the charger" if status.on_base else "Off the charger"))
    if status.led_on is not None:
        light = "Off"
        if status.led_on:
            light = f"On · {status.led_color}" if status.led_color else "On"
        rows.append(_row("Light", light))
    if status.next_update is not None:
        # Past due is the useful case: a collar that has missed its own
        # schedule is out of range, flat, or off, and says so nowhere else.
        when = _since(status.next_update, _clock(snapshot.fetched_at, zone), zone)
        if status.next_update < snapshot.fetched_at:
            rows.append(_row("Next report", f"Overdue · was expected {when}", warn=True))
        else:
            rows.append(_row("Next report", f"Expected by {when}"))
    return rows


def fi_row(health: dict[str, Any]) -> dict[str, Any]:
    state, age = health.get("fi"), ago(health.get("fi_age_s"))
    if state == "unconfigured":
        return _row("Fi", "Not set up")
    if state == "pending":
        return _row("Fi", "Not asked yet")
    if state == "stale":
        return _row("Fi", f"Not answering · last good reading {age}", warn=True)
    if state == "unavailable":
        return _row("Fi", "Not answering", warn=True)
    if state == "partial":
        return _row("Fi", f"Partly answering · checked {age}", warn=True)
    return _row("Fi", f"Checked {age}" if age else "Checked")


def system_rows(
    health: dict[str, Any],
    recorder: dict[str, Any] | None,
    heartbeat: Any | None,
    started_at: datetime | None,
    now: datetime,
) -> list[dict[str, Any]]:
    camera, warn = CAMERA_WORDS.get(health.get("camera") or "", ("Unknown", True))
    rows = [_row("Camera", camera, warn), fi_row(health)]
    if recorder is None:
        rows.append(_row("Recording", "Off · KONA_DB_PATH is blank", warn=True))
    else:
        size = size_label(recorder["size_bytes"])
        detail = " · ".join(part for part in (recorder["file"], size) if part)
        words = {
            "recording": ("On", False),
            "paused": ("Paused · retrying on the next refresh", True),
            "stopped": ("Stopped · see kona.log", True),
        }
        state, bad = words.get(recorder["state"], ("Unknown", True))
        rows.append(_row("Recording", f"{state} · {detail}" if detail else state, bad))
    if heartbeat is None:
        rows.append(_row("Heartbeat", "Off"))
    else:
        failed = f", {heartbeat.failures} failed" if heartbeat.failures else ""
        rows.append(
            _row("Heartbeat", f"On · {heartbeat.sent} sent{failed}", bool(heartbeat.failures))
        )
    if started_at is not None:
        rows.append(_row("Server", f"Started {ago((now - started_at).total_seconds())}"))
    return rows
