"""The icon generator must keep producing decodable square PNGs; a silent
failure here shows up as a blank tile on someone's home screen."""

import runpy
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402  (only meaningful once cv2 imported)

STATIC = Path(__file__).resolve().parents[1] / "src" / "kona_tracker" / "web" / "static"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_icons.py"
EXPECTED = {"icon-512.png": 512, "icon-192.png": 192, "icon-180.png": 180, "favicon-32.png": 32}


@pytest.mark.parametrize("name,size", sorted(EXPECTED.items()))
def test_committed_icons_are_square_pngs_of_the_right_size(name, size):
    path = STATIC / name
    assert path.exists(), f"{name} missing; run `uv run python scripts/make_icons.py`"
    assert path.read_bytes().startswith(b"\x89PNG")
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape == (size, size, 3)


def test_generator_reproduces_the_committed_icons(tmp_path, monkeypatch):
    """Rendering is deterministic, so a rerun must not dirty the working tree."""
    before = {n: (STATIC / n).read_bytes() for n in EXPECTED}
    monkeypatch.setitem(sys.modules, "__main__", sys.modules[__name__])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    after = {n: (STATIC / n).read_bytes() for n in EXPECTED}
    assert before == after


def test_mark_sits_inside_the_maskable_safe_zone():
    """Android crops maskable icons to the inner 80% circle. Anything outside
    radius 0.4 from centre would get sliced off."""
    img = cv2.imdecode(np.fromfile(str(STATIC / "icon-512.png"), np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    corner = img[0, 0]
    mark = np.any(np.abs(img.astype(int) - corner.astype(int)) > 30, axis=2)
    ys, xs = np.nonzero(mark)
    assert len(xs) > 0, "no mark drawn"
    radii = np.hypot(xs - w / 2, ys - h / 2) / w
    assert radii.max() <= 0.40, f"mark reaches {radii.max():.3f} of the width from centre"
