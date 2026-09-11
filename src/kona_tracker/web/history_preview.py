"""Fictional history for design review only; never a fallback for Fi data.

Keep this separate from fi/service.py: a successful prototype does not prove
that the collar exposes hourly buckets or sleep intervals.
"""

from datetime import date, timedelta

SAMPLE_DAY = date(2026, 9, 11)
STEPS = (220, 40, 0, 0, 60, 320, 2340, 2580, 860, 640, 360)
SLEEP = (30, 60, 60, 60, 60, 60, 60, 30, 0, 0, 0)
NAPS = (0, 0, 0, 0, 0, 0, 0, 0, 42, 36, 6)


def history_preview(metric: str, period: str, day: int, selected: int | None) -> dict:
    """Bounded fixture selection; all totals are derived from displayed bars."""
    current = SAMPLE_DAY - timedelta(days=day)
    steps = list(STEPS) + (
        [None] * 13 if day == 0 else [0, 120, 480, 940, 0, 760, 1520, 620, 140, 0, 0, 0, 0]
    )
    sleep = list(SLEEP) + ([None] * 13 if day == 0 else [0] * 13)
    naps = list(NAPS) + ([None] * 13 if day == 0 else [0, 0, 24, 18, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    # Distinct fictional days, including an explicitly missing reading.
    if day:
        steps = [round(v * (1 + day * 0.04)) for v in steps]
    if day == 2:
        steps[14] = None
        sleep[14] = naps[14] = None
    buckets = []
    if period == "day":
        for hour in range(24):
            value = (
                steps[hour]
                if metric == "steps"
                else None
                if sleep[hour] is None
                else sleep[hour] + naps[hour]
            )
            buckets.append(
                {
                    "label": f"{hour:02}:00–{hour + 1:02}:00",
                    "short": f"{hour:02}",
                    "value": value,
                    "sleep": sleep[hour],
                    "nap": naps[hour],
                    "future": day == 0 and hour >= 11,
                    "href": f"/preview/{metric}?period=day&day={day}&selected={hour}#chart-title",
                }
            )
    else:
        for offset in reversed(range(7)):
            daily = history_preview(metric, "day", offset, None)
            buckets.append(
                {
                    "label": daily["date_label"],
                    "short": (SAMPLE_DAY - timedelta(days=offset)).strftime("%a"),
                    "value": daily["total"],
                    "sleep": daily["sleep_total"],
                    "nap": daily["nap_total"],
                    "future": False,
                    "partial": offset in (0, 2),
                    "href": f"/preview/{metric}?day={offset}",
                }
            )
    total = sum(b["value"] for b in buckets if b["value"] is not None)
    sleep_total = sum(b["sleep"] for b in buckets if b["sleep"] is not None)
    nap_total = sum(b["nap"] for b in buckets if b["nap"] is not None)
    maximum = (
        3000
        if metric == "steps" and period == "day"
        else 60
        if period == "day"
        else 20000
        if metric == "steps"
        else 720
    )
    if metric == "steps":
        maximum = max(maximum, ((max(b["value"] or 0 for b in buckets) + 999) // 1000) * 1000)
    spacing = 336 / len(buckets)
    for i, bucket in enumerate(buckets):
        bucket.update(
            x=round(2 + i * spacing, 2), width=round(spacing - (3 if period == "day" else 12), 2)
        )
        bucket["height"] = round((bucket["value"] or 0) / maximum * 150, 2)
        bucket["sleep_height"] = round((bucket["sleep"] or 0) / maximum * 150, 2)
        bucket["nap_height"] = round((bucket["nap"] or 0) / maximum * 150, 2)
    chosen = buckets[selected] if selected is not None and selected < len(buckets) else None
    intervals = [(30, 450, "sleep"), (480, 522, "nap"), (540, 576, "nap"), (600, 606, "nap")]
    if day:
        intervals.append((780, 804, "nap"))
        if day != 2:
            intervals.append((840, 858, "nap"))
    return {
        "tab": None,
        "preview": True,
        "metric": metric,
        "period": period,
        "day": day,
        "date_label": current.strftime("%a, %d %b"),
        "buckets": buckets,
        "total": total,
        "sleep_total": sleep_total,
        "nap_total": nap_total,
        "maximum": maximum,
        "selected": selected,
        "chosen": chosen,
        "intervals": [
            {
                "x": start / 1440 * 340,
                "width": (end - start) / 1440 * 340,
                "kind": kind,
                "label": (
                    f"{kind.title()} · {start // 60:02}:{start % 60:02}"
                    f"–{end // 60:02}:{end % 60:02}"
                ),
            }
            for start, end, kind in intervals
        ],
        "partial": period == "week" or day == 2,
        "total_label": f"{total:,}" if metric == "steps" else f"{total // 60} h {total % 60:02} m",
    }
