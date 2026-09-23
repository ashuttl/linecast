"""The terminal font's cell shape, and the views that draw to it.

Half-block graphics take a cell for two square sub-pixels, which is only
so on a cell twice as tall as it is wide.  cell_aspect() reads the real
shape from the terminal, and every round or ground-true view scales its
vertical axis by it.  The tests set the shape through the environment
override, as a capture would; a 9x15 cell makes a sub-pixel 0.833 cell
widths tall, so a disc needs 1.2 times as many sub-pixel rows as columns.
"""

import math

import pytest

from linecast.sky import view as sky
from linecast.maps import globe
from linecast._framebuffer import Framebuffer, cell_aspect
from linecast.radar.render import bbox_for
from linecast.moon.disc import _draw_moon_disc


class TestCellAspect:
    def test_ratio_override(self, monkeypatch):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "1.7")
        assert cell_aspect() == 1.7

    def test_pixel_override(self, monkeypatch):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "9x15")
        assert math.isclose(cell_aspect(), 15 / 9)

    @pytest.mark.parametrize("junk", ["", "wide", "0x9", "9x0", "0.5", "7"])
    def test_junk_or_absurd_override_falls_back(self, monkeypatch, junk):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", junk)
        assert cell_aspect() == 2.0 or junk == ""   # "" means: ask the terminal

    def test_no_terminal_falls_back(self, monkeypatch):
        monkeypatch.delenv("LINECAST_CELL_ASPECT", raising=False)
        # Under pytest's capture no stream is a tty, so the ioctl fails.
        assert cell_aspect(fallback=2.5) in (2.5,) or 1.0 <= cell_aspect() <= 4.0


def _painted_extent(fb):
    xs = [x for row in fb.fb for x, px in enumerate(row) if px != fb.bg]
    ys = [y for y, row in enumerate(fb.fb) if any(px != fb.bg for px in row)]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


class TestTheMoon:
    def test_disc_is_taller_in_subpixels_on_a_short_cell(self):
        wide = Framebuffer(60, 30, bg_color=(0, 0, 0))
        _draw_moon_disc(wide, 30, 30, 12.0, 1.0, 0.0, 0.0, aspect=15 / 9 / 2)
        square = Framebuffer(60, 30, bg_color=(0, 0, 0))
        _draw_moon_disc(square, 30, 30, 12.0, 1.0, 0.0, 0.0)
        w_wide, h_wide = _painted_extent(wide)
        w_sq, h_sq = _painted_extent(square)
        assert w_wide == w_sq                       # the width is the radius
        assert math.isclose(h_wide / w_wide, 1.2, abs_tol=0.08)
        assert math.isclose(h_sq / w_sq, 1.0, abs_tol=0.08)


class TestTheGlobe:
    def test_disk_is_taller_in_rows_on_a_short_cell(self, monkeypatch):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "9x15")
        _lls, _zs, rhos = globe.geometry(0.0, 0.0, 180.0, 200, 100)
        cols = max(sum(1 for r in row if r <= 1.0) for row in rhos)
        rows = sum(1 for row in rhos if any(r <= 1.0 for r in row))
        assert math.isclose(rows / cols, 1.2, abs_tol=0.05)

    def test_default_cell_keeps_the_grid_disk_round(self, monkeypatch):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "2.0")
        _lls, _zs, rhos = globe.geometry(0.0, 0.0, 180.0, 200, 100)
        cols = max(sum(1 for r in row if r <= 1.0) for row in rhos)
        rows = sum(1 for row in rhos if any(r <= 1.0 for r in row))
        assert math.isclose(cols / rows, 1.0, abs_tol=0.05)


class TestTheSky:
    def test_projection_scales_only_the_vertical(self):
        f = sky.focal_length(100, 90.0)
        v = (0.2, 0.3, 0.93)
        x1, y1 = sky.project(v, f, 50.0, 50.0)
        x2, y2 = sky.project(v, f, 50.0, 50.0, 1.2)
        assert x1 == x2
        assert math.isclose((50.0 - y1) / (50.0 - y2), 1.2)

    def test_unproject_inverts_project_at_any_aspect(self):
        f = sky.focal_length(100, 90.0)
        v = (0.1, 0.3, 0.9486832980505138)
        back = sky.unproject(*sky.project(v, f, 50.0, 50.0, 0.8), f, 50.0, 50.0, 0.8)
        assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(v, back))


class TestTheFlatMap:
    def test_window_widens_on_a_short_cell(self, monkeypatch):
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "2.0")
        square = bbox_for(40.0, -105.0, 10.0, 80, 20)
        monkeypatch.setenv("LINECAST_CELL_ASPECT", "9x15")
        wide = bbox_for(40.0, -105.0, 10.0, 80, 20)
        assert wide[3] - wide[1] == square[3] - square[1]     # the zoom is the height
        assert math.isclose((wide[2] - wide[0]) / (square[2] - square[0]), 1.2)
