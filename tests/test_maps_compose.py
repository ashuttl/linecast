"""Tests for compose_map and the zoom-scaled view cache key.

compose_map is the street-mode sibling of compose_terrain: area fills
under one pre-ranked braille layer. The colour mode is patched through
compose_map.__globals__ rather than by re-importing — after the
test_oneline sys.modules purge, sys.modules holds a newer module
generation than the function bound at the top of this file.
"""

import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _color, _globe, _maps_style
from linecast._framebuffer import HALF_BLOCK
from linecast.maps import (
    LABEL_DARK, LABEL_LIGHT, MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP,
    _view_key, compose_map, max_zoom,
)

GREEN = (40, 60, 40)
NAVY = (30, 44, 62)
ROAD = (132, 136, 150)
ROUTE = (120, 210, 255)


def _strip(s):
    return re.sub(r"\033\[[^m]*m", "", s)


class FakeLayer:
    """Duck-type for the ranked DotLayer compose_map reads."""

    def __init__(self, dots, color, ribbon=()):
        self.dots = dots
        self.color = color
        self.ribbon = set(ribbon)


def _fills(rows):
    """rows: list of per-cell (top, bot) pairs -> a sub-pixel grid."""
    return [[c[0] for c in rows], [c[1] for c in rows]]


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
    monkeypatch.setitem(compose_map.__globals__, "color_mode",
                        lambda: "truecolor")


def _mode(monkeypatch, mode):
    monkeypatch.setattr(_color, "_COLOR_MODE", mode)
    monkeypatch.setitem(compose_map.__globals__, "color_mode", lambda: mode)


class TestComposeMapPriority:
    def test_priority_order_across_a_row(self):
        # col0: overlay over a braille dot -> the glyph wins;
        # col1: braille only -> the dot, inked by the layer;
        # col2: fill only -> a half-block;
        # col3: unpainted -> a space.
        layer = FakeLayer(dots=[[0x01, 0x07, 0, 0]],
                          color=[[ROAD, ROUTE, None, None]])
        fills = _fills([(GREEN, GREEN), (GREEN, GREEN),
                        (GREEN, NAVY), (None, None)])
        line = compose_map(fills, layer, {(0, 0): ("X", (9, 9, 9))}, 4, 1)[0]
        plain = _strip(line)
        assert plain[0] == "X"
        assert plain[1] == chr(0x2800 + 0x07)
        assert plain[2] == HALF_BLOCK
        assert plain[3] == " "
        assert "38;2;120;210;255" in line       # the route owns its cell

    def test_glyph_beats_braille_in_the_same_cell(self):
        layer = FakeLayer(dots=[[0xFF]], color=[[ROAD]])
        line = compose_map(_fills([(GREEN, GREEN)]), layer,
                           {(0, 0): ("✚", (208, 124, 124))}, 1, 1)[0]
        assert _strip(line)[0] == "✚"
        assert chr(0x2800 + 0xFF) not in line

    def test_braille_takes_the_layers_winning_ink(self):
        layer = FakeLayer(dots=[[0x03]], color=[[ROUTE]])
        line = compose_map(_fills([(GREEN, GREEN)]), layer, {}, 1, 1)[0]
        assert _strip(line)[0] == chr(0x2800 + 0x03)
        assert "38;2;120;210;255" in line

    def test_stroke_cell_flattens_the_fill_to_one_background(self):
        layer = FakeLayer(dots=[[0x01]], color=[[ROAD]])
        fills = _fills([((100, 100, 100), (0, 0, 0))])
        line = compose_map(fills, layer, {}, 1, 1)[0]
        assert "48;2;50;50;50" in line          # avg of the two sub-pixels
        assert HALF_BLOCK not in line

    def test_overlay_ink_none_picks_for_contrast(self):
        layer = FakeLayer(dots=[[0]], color=[[None]])
        light = compose_map(_fills([((230, 230, 235), (230, 230, 235))]),
                            layer, {(0, 0): ("A", None)}, 1, 1)[0]
        dark = compose_map(_fills([((20, 30, 40), (20, 30, 40))]),
                           layer, {(0, 0): ("A", None)}, 1, 1)[0]
        assert f"38;2;{LABEL_DARK[0]};" in light
        assert f"38;2;{LABEL_LIGHT[0]};" in dark

    def test_unpainted_cell_still_picks_a_light_glyph_ink(self):
        # No fill to judge, so the terminal background stands in.
        layer = FakeLayer(dots=[[0]], color=[[None]])
        line = compose_map(_fills([(None, None)]), layer,
                           {(0, 0): ("A", None)}, 1, 1)[0]
        assert f"38;2;{LABEL_LIGHT[0]};" in line
        assert "48;2;" not in line              # and paints no background

    def test_bold_overlay_keeps_the_compose_terrain_idiom(self, monkeypatch):
        # BOLD/RESET are frozen to "" at import under pytest's no-tty
        # colour mode; patch the exact globals compose_map reads.
        monkeypatch.setitem(compose_map.__globals__, "BOLD", "\033[1m")
        monkeypatch.setitem(compose_map.__globals__, "RESET", "\033[0m")
        layer = FakeLayer(dots=[[0]], color=[[None]])
        line = compose_map(_fills([(GREEN, GREEN)]), layer,
                           {(0, 0): ("+", (255, 240, 120), True)}, 1, 1)[0]
        assert "\033[1m+\033[0m" in line


class TestComposeMapRibbon:
    def test_ribbon_blends_toward_the_motorway_ink(self):
        motorway = _maps_style.PALETTE_DARK["motorway"]
        layer = FakeLayer(dots=[[0, 0]], color=[[None, None]],
                          ribbon=[(0, 0)])
        fills = _fills([(GREEN, GREEN), (GREEN, GREEN)])
        line = compose_map(fills, layer, {}, 2, 1)[0]
        blend = tuple(round(a + (b - a) * _maps_style.RIBBON_BLEND)
                      for a, b in zip(GREEN, motorway))
        assert f"48;2;{blend[0]};{blend[1]};{blend[2]}" in line
        assert f"48;2;{GREEN[0]};{GREEN[1]};{GREEN[2]}" in line  # cell 1

    def test_ribbon_ignores_the_cells_own_stroke_colour(self):
        # A rank-90 route crossing the ribbon must not tint it cyan.
        motorway = _maps_style.PALETTE_DARK["motorway"]
        layer = FakeLayer(dots=[[0x01]], color=[[ROUTE]], ribbon=[(0, 0)])
        line = compose_map(_fills([(GREEN, GREEN)]), layer, {}, 1, 1)[0]
        blend = tuple(round(a + (b - a) * _maps_style.RIBBON_BLEND)
                      for a, b in zip(GREEN, motorway))
        assert f"48;2;{blend[0]};{blend[1]};{blend[2]}" in line
        assert "38;2;120;210;255" in line       # the route still owns the ink

    def test_ribbon_over_an_unpainted_cell_paints_nothing(self):
        layer = FakeLayer(dots=[[0]], color=[[None]], ribbon=[(0, 0)])
        line = compose_map(_fills([(None, None)]), layer, {}, 1, 1)[0]
        assert _strip(line) == " "


class TestComposeMapDegradedModes:
    def test_none_mode_never_leaks_a_half_block(self, monkeypatch):
        # halfblock() with empty escapes returns a bare ▄ for every cell
        # where top != bot, which would flood the screen. `none` renders
        # as a pure line map instead.
        _mode(monkeypatch, "none")
        layer = FakeLayer(dots=[[0, 0x07, 0]], color=[[None, ROAD, None]])
        fills = _fills([(GREEN, NAVY), (GREEN, GREEN), (NAVY, NAVY)])
        line = compose_map(fills, layer, {}, 3, 1)[0]
        assert HALF_BLOCK not in line
        assert "\033[" not in line
        assert line == " " + chr(0x2800 + 0x07) + " "

    def test_none_mode_still_draws_glyphs(self, monkeypatch):
        _mode(monkeypatch, "none")
        layer = FakeLayer(dots=[[0]], color=[[None]])
        line = compose_map(_fills([(GREEN, GREEN)]), layer,
                           {(0, 0): ("▲", None)}, 1, 1)[0]
        assert line == "▲"

    def test_16_mode_mixed_water_cell_is_unpainted(self, monkeypatch):
        # The 16-colour rule: a cell is navy only when both sub-pixels
        # are water. A mixed cell is left to the terminal's own
        # background and the coast stroke carries the boundary.
        _mode(monkeypatch, "16")
        layer = FakeLayer(dots=[[0, 0]], color=[[None, None]])
        fills = _fills([((0, 0, 128), (0, 0, 128)), ((0, 0, 128), None)])
        line = compose_map(fills, layer, {}, 2, 1)[0]
        assert _strip(line) == "  "
        assert line.count("\033[44m") == 1      # only the all-water cell

    def test_16_mode_unpainted_cell_with_a_stroke_keeps_the_dot(self,
                                                                monkeypatch):
        _mode(monkeypatch, "16")
        layer = FakeLayer(dots=[[0x09]], color=[[(92, 92, 255)]])
        line = compose_map(_fills([(None, None)]), layer, {}, 1, 1)[0]
        assert _strip(line) == chr(0x2800 + 0x09)
        assert "\033[94m" in line               # bright blue coast
        assert "\033[4" not in line.replace("\033[49m", "")  # no bg painted


class TestViewKeyPrecision:
    def test_wide_views_keep_todays_four_places(self):
        # Unchanged behaviour for every existing caller: at a degree or
        # more the key is exactly what it always was.
        bbox = (-71.123456, 43.123456, -69.123456, 45.123456)
        assert _view_key(bbox, 80, 22)[:3] == (
            (-71.1235, 43.1235, -69.1235, 45.1235), 80, 22)

    def test_a_one_cell_pan_at_the_deepest_zoom_is_a_distinct_key(self):
        # 0.0012 deg over 22 cells: one cell of pan is ~5.5e-5 deg,
        # which 4 dp would round away entirely.
        zoom, hc = MIN_ZOOM_DEG, 22
        cell = zoom / hc
        a = (-70.371, 43.677, -70.361, 43.677 + zoom)
        b = (a[0], a[1] + cell, a[2], a[3] + cell)
        assert _view_key(a, 80, hc) != _view_key(b, 80, hc)
        # ...and the min/max latitudes stay distinct within one key
        key = _view_key(a, 80, hc)[0]
        assert key[1] != key[3]

    def test_precision_tracks_the_span(self):
        assert _view_key((0, 0, 1, 1), 1, 1)[0] == (0, 0, 1, 1)
        deep = _view_key((0.1234567, 0.1234567, 0.1244567, 0.1244567), 1, 1)
        assert deep[0][0] == round(0.1234567, 6)
        wide = _view_key((0.1234567, 0.0, 10.1234567, 60.0), 1, 1)
        assert wide[0][0] == round(0.1234567, 4)

    def test_degenerate_span_does_not_explode(self):
        assert _view_key((1.0, 5.0, 2.0, 5.0), 10, 10)[0] == (1.0, 5.0,
                                                              2.0, 5.0)


class TestZoomRange:
    def test_street_mode_reaches_the_deep_bands(self):
        # The old floor of 0.1 topped out at band 3; buildings and POI
        # text live at band 7.
        assert MIN_ZOOM_DEG == 0.0012
        # the ceiling admits the whole planet: past _globe.ZOOM_DEG the
        # terrain view is orthographic, and 130 fits the disk with margin
        assert MAX_ZOOM_DEG == 130.0
        hc = 22
        deepest = (-70.0, 43.0, -69.0, 43.0 + MIN_ZOOM_DEG)
        assert _maps_style.band_for(_maps_style.z_eff(deepest, hc)) == 7
        old_floor = (-70.0, 43.0, -69.0, 43.1)
        assert _maps_style.band_for(_maps_style.z_eff(old_floor, hc)) == 3

    def test_a_narrow_terminal_gets_a_higher_ceiling(self):
        # The disk is as wide as it is tall, and a cell is two grid
        # rows: a map narrower than twice its height in cells runs the
        # planet off both sides at 130.
        assert max_zoom(100, 40) == MAX_ZOOM_DEG
        gw, hc = 54, 45
        assert max_zoom(gw, hc) > MAX_ZOOM_DEG

        def edges(zoom):
            _lls, _zs, rhos = _globe.geometry(0.0, 0.0, zoom, gw, hc * 2)
            on = [x for row in rhos for x, rho in enumerate(row) if rho <= 1.0]
            return min(on), max(on)

        assert edges(MAX_ZOOM_DEG) == (0, gw - 1)   # clipped, both edges
        left, right = edges(max_zoom(gw, hc))
        assert 0 < left and right < gw - 1

    def test_the_step_walks_the_whole_range_in_a_sane_number_of_presses(self):
        assert ZOOM_STEP == 1.5
        presses = math.log(4.0 / MIN_ZOOM_DEG) / math.log(ZOOM_STEP)
        assert 19 < presses < 21          # 4.0 -> the floor in 20 presses
