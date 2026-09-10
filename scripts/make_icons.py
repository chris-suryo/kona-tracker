"""Render the app icons.

Run this whenever the palette changes:

    uv run python scripts/make_icons.py

The mark is a paw drawn from circles and an ellipse rather than a font
glyph, so it needs no typeface and stays crisp at every size. It is drawn
at 4x and downsampled with INTER_AREA, which gives cleaner edges than
OpenCV's anti-aliasing alone.

Icons are full-bleed squares on purpose: iOS applies its own rounded-corner
mask, and a pre-rounded icon would get double-rounded.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

STATIC = Path(__file__).resolve().parents[1] / "src" / "kona_tracker" / "web" / "static"

# Meadow tokens. OpenCV works in BGR, so these are reversed from the CSS hex:
# background #27512A (deep moss), mark #CDE9B4 (light tint).
BG_BGR = (42, 81, 39)
MARK_BGR = (180, 233, 205)

SUPERSAMPLE = 4
BASE = 512

# Geometry as fractions of the canvas, so one description drives every size.
# Four toes in an arc above a wide pad.
TOES = [
    (0.250, 0.455, 0.088),  # x, y, radius
    (0.400, 0.330, 0.098),
    (0.600, 0.330, 0.098),
    (0.750, 0.455, 0.088),
]
PAD_CENTER = (0.500, 0.670)
PAD_AXES = (0.230, 0.180)

SIZES = {
    "icon-512.png": 512,
    "icon-192.png": 192,
    "icon-180.png": 180,
    "favicon-32.png": 32,
}


def render(size: int) -> np.ndarray:
    """One square RGB icon at `size` pixels."""
    big = size * SUPERSAMPLE
    canvas = np.full((big, big, 3), BG_BGR, np.uint8)

    for fx, fy, fr in TOES:
        cv2.circle(
            canvas,
            (round(fx * big), round(fy * big)),
            round(fr * big),
            MARK_BGR,
            thickness=-1,
            lineType=cv2.LINE_AA,
        )

    cv2.ellipse(
        canvas,
        (round(PAD_CENTER[0] * big), round(PAD_CENTER[1] * big)),
        (round(PAD_AXES[0] * big), round(PAD_AXES[1] * big)),
        angle=0,
        startAngle=0,
        endAngle=360,
        color=MARK_BGR,
        thickness=-1,
        lineType=cv2.LINE_AA,
    )

    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        path = STATIC / name
        if not cv2.imwrite(str(path), render(size)):
            raise RuntimeError(f"could not write {path}")
        print(f"wrote {path.relative_to(Path.cwd())} ({size}x{size})")


if __name__ == "__main__":
    main()
