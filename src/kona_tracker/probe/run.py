"""The probe: log in once, dump everything Fi will tell us about the pets, and
write a redacted, human-readable summary.

Every step after login is best-effort and independent: if introspection is
disabled, the known queries and the speculative-field errors still run, and
the summary says which steps failed and why. The whole point is to learn the
real API surface, so a failure message IS a result, not an abort.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from kona_tracker.fi import queries
from kona_tracker.fi.client import FiClient, FiError, FiGraphQLError
from kona_tracker.fi.parse import (
    NAP,
    SLEEP,
    activity_from,
    hours_from_duration,
    pets_from,
    rest_from,
)
from kona_tracker.fi.queries import REST_PERIODS
from kona_tracker.probe.redact import redact
from kona_tracker.probe.scan import SchemaScan, scan_schema


@dataclass
class ProbeReport:
    pets: list[dict[str, str]] = field(default_factory=list)
    introspection_ok: bool = False
    scan: SchemaScan | None = None
    errors: dict[str, str] = field(default_factory=dict)  # step -> message
    speculative_hints: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    #: Redacted bodies of the responses the metric lines do not summarise,
    #: inlined into summary.md so one pasted file carries everything.
    extras: dict[str, Any] = field(default_factory=dict)


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(redact(obj), indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "pet"


def _msg(entry: dict[str, str]) -> str:
    """A redacted error plus its value-free shape, when one could be made."""
    message = str(entry.get("message", entry))
    shape = entry.get("shape")
    return f"{message} (shape: {shape})" if shape else message


def _collapse_positions(obj: Any) -> Any:
    """GPS tracks are one row per second; the shape is the point, not the list.

    `positions` becomes a count, first and last timestamps, and the error
    radius range. Coordinates are already gone by the time this runs.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "positions" and isinstance(v, list):
                dates = [p.get("date") for p in v if isinstance(p, dict) and p.get("date")]
                radii = [
                    p["errorRadius"]
                    for p in v
                    if isinstance(p, dict) and type(p.get("errorRadius")) in (int, float)
                ]
                out[k] = {
                    "count": len(v),
                    "first": min(dates) if dates else None,
                    "last": max(dates) if dates else None,
                    "errorRadius": [min(radii), max(radii)] if radii else None,
                }
            else:
                out[k] = _collapse_positions(v)
        return out
    if isinstance(obj, list):
        return [_collapse_positions(v) for v in obj]
    return obj


def _try(report: ProbeReport, step: str, fn):
    """Run a step; record its error instead of raising. Returns None on failure."""
    try:
        return fn()
    except FiGraphQLError as e:
        report.errors[step] = "; ".join(_msg(x) for x in e.errors)
        return e.data  # partial data, if any
    except FiError as e:
        report.errors[step] = str(e)
        return None


def run_probe(client: FiClient, out_dir: Path) -> ProbeReport:
    """`client` must already be logged in."""
    report = ProbeReport()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Who's in the household.
    data = _try(report, "pets", lambda: client.graphql(queries.CURRENT_USER_PETS))
    for pet in pets_from(data):
        report.pets.append({"id": pet.id, "name": pet.name})

    # 2. Full schema.
    data = _try(report, "introspection", lambda: client.graphql(queries.INTROSPECTION))
    if data and data.get("__schema"):
        report.introspection_ok = True
        path = out_dir / "schema.json"
        _write_json(path, data)
        report.files.append(path)
        report.scan = scan_schema(data["__schema"])

    # 3. Known queries + speculative fields, per pet.
    for pet in report.pets:
        slug = _safe_name(pet["name"])
        for label, q in (
            ("rest", queries.pet_rest(pet["id"])),
            ("activity", queries.pet_activity(pet["id"])),
        ):
            data = _try(report, f"{label}:{slug}", lambda q=q: client.graphql(q))
            if data is not None:
                report.metrics.extend(_metric_lines(label, data, slug))
                path = out_dir / f"pet-{slug}-{label}.json"
                _write_json(path, data)
                report.files.append(path)
        # Sourced from pytryfi but never yet seen from a real collar. Each is
        # its own step so one unsupported shape cannot sink the others.
        # `whereabouts` is the exact document the page now sends for her
        # resting position, so this run is what verifies it.
        for label, q in (
            ("profile", queries.pet_profile(pet["id"])),
            ("device", queries.pet_device(pet["id"])),
            ("location", queries.pet_location(pet["id"])),
            ("whereabouts", queries.pet_whereabouts(pet["id"])),
        ):
            data = _try(report, f"{label}:{slug}", lambda q=q: client.graphql(q))
            if data is not None:
                path = out_dir / f"pet-{slug}-{label}.json"
                _write_json(path, data)
                report.files.append(path)
                report.extras[f"{label}:{slug}"] = _collapse_positions(redact(data))

        # Speculative: the errors are the data. One query per known type, so
        # each rejection names the type it was checked against.
        for label, q in queries.speculative_queries(pet["id"]):
            try:
                data = client.graphql(q)
                path = out_dir / f"pet-{slug}-speculative-{label}.json"
                _write_json(path, data)
                report.files.append(path)
                report.speculative_hints.append(
                    f"[{label}] query ACCEPTED -- see the inlined body below."
                )
                report.extras[f"speculative-{label}:{slug}"] = _collapse_positions(redact(data))
            except FiGraphQLError as e:
                report.speculative_hints.extend(f"[{label}] {_msg(x)}" for x in e.errors)
            except FiError as e:
                report.errors[f"speculative-{label}:{slug}"] = str(e)

    summary = out_dir / "summary.md"
    summary.write_text(render_summary(report), encoding="utf-8")
    report.files.append(summary)
    return report


def _bullets(lines: list[str], items: list[str], empty: str = "none") -> None:
    lines.extend(f"- {i}" for i in items) if items else lines.append(f"- {empty}")


def _number(value: Any) -> str:
    return str(value) if type(value) in (int, float) else "unavailable"


def _date(value: datetime | None) -> str:
    return value.isoformat() if value else "unavailable"


def _reading(value: Any) -> str:
    """The raw figure, plus what it means if the seconds assumption holds.

    Chris reads this file to settle the unit question, so the hint is worth
    printing — but only when it lands somewhere plausible, and always beside
    the raw number rather than instead of it.
    """
    hours = hours_from_duration(value)
    hint = f"; {hours:.1f} h if seconds" if hours is not None else ""
    return f"{_number(value)} (raw API units{hint})"


def _metric_lines(label: str, data: dict, pet: str) -> list[str]:
    """Summarize known values only; missing/null is not a measured zero.

    Parsing lives in `fi/parse.py` so the probe and the Activity page read
    these responses through exactly one implementation.
    """
    result = []
    if label == "activity":
        for period in ("dailyStat", "weeklyStat"):
            stats = activity_from(data, period)
            result.append(
                f"{pet} {period}: totalSteps={_number(stats.steps)}, "
                f"stepGoal={_number(stats.step_goal)}, "
                f"totalDistance={_number(stats.distance)} (raw API units)."
            )
    else:
        found = False
        for period, _enum in REST_PERIODS:
            for window in rest_from(data, period):
                found = True
                span = f"{_date(window.start)} to {_date(window.end)}"
                for kind, amount in ((SLEEP, window.sleep), (NAP, window.nap)):
                    result.append(f"{pet} {period} {span}: {kind} duration={_reading(amount)}.")
        if not found:
            result.append(f"{pet}: rest summaries unavailable or empty; no sleep value confirmed.")
    return result


def render_summary(r: ProbeReport) -> str:
    lines: list[str] = ["# Fi API probe summary", ""]
    lines.append("Redacted: emails, session ids, locations, addresses, chip/module ids.")
    lines.append("")
    lines.append("## Pets")
    _bullets(lines, [f"{p['name'] or '(unnamed)'} (id {p['id']})" for p in r.pets], "none found")
    lines.append("")
    lines.append("## Returned metrics")
    lines.append("")
    _bullets(lines, r.metrics, "No metric values returned.")
    lines.append("")
    lines.append(
        "Durations are seconds (verified 2026-09-10: weekly SLEEP 27202 = 7.6 h). "
        "Distance units are still unverified. The newest daily rest window is today, in "
        "progress; last night is the window before it. Unavailable values are not zero."
    )
    lines.append("")
    lines.append(
        "Schema fields and validation hints show possible API shapes, not measured data. "
        "Sleep quality and scratching, licking, barking, eating, and drinking "
        "remain unconfirmed until queried successfully for this collar."
    )
    lines.append("")
    lines.append("## Introspection")
    if r.scan:
        lines.append(f"Enabled. Pet type has {len(r.scan.pet_fields)} fields:")
        lines.append("")
        lines.extend(f"- `{f}`" for f in r.scan.pet_fields)
        lines.append("")
        lines.append("### Keyword hits (sleep/rest/nap/quality/score/behavior/...)")
        lines.append("")
        _bullets(lines, [f"`{h}`" for h in r.scan.keyword_hits])
        lines.append("")
        lines.append("### Types with keyword names")
        lines.append("")
        _bullets(lines, [f"`{t}`" for t in r.scan.keyword_types])
    else:
        lines.append("DISABLED or failed: " + r.errors.get("introspection", "no schema returned"))
    lines.append("")
    lines.append("## Speculative field hints (validation errors are the data here)")
    lines.append("")
    _bullets(lines, r.speculative_hints)
    lines.append("")
    lines.append("## Step errors")
    lines.append("")
    _bullets(lines, [f"{k}: {v}" for k, v in r.errors.items()])
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.extend(f"- {p.name}" for p in r.files)
    lines.append("")
    if r.extras:
        lines.append("## Other responses (redacted, verbatim)")
        lines.append("")
        lines.append(
            "Profile, device and location as Fi returned them, with private values "
            "blanked. Field names and shapes are the point."
        )
        for label, body in r.extras.items():
            lines.append("")
            lines.append(f"### {label}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(body, indent=2, ensure_ascii=True, sort_keys=True))
            lines.append("```")
        lines.append("")
    return "\n".join(lines)
