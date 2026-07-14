"""Tests for the radar hybrid compositor (geography + radar + overlays)."""

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._color import BG_PRIMARY, lerp
from linecast._framebuffer import HALF_BLOCK
from linecast._radar_render import bbox_for, build_radar_buffer, compose

_ANSI_RE = re.compile(r"\033\[[^m]*m")


def _strip_ansi(s):
    return _ANSI_RE.sub("", s)


class FakeBasemap:
    def __init__(self, dots, color):
        self.dots = dots
        self.color = color


class TestBboxFor:
    def test_lat_span_equals_zoom(self):
        minlon, minlat, maxlon, maxlat = bbox_for(40.0, -105.0, 10.0, 80, 20)
        assert maxlat - minlat == 10.0

    def test_centered_on_lat_lon(self):
        lat, lon = 40.0, -105.0
        minlon, minlat, maxlon, maxlat = bbox_for(lat, lon, 8.0, 80, 20)
        assert (minlat + maxlat) / 2 == lat
        assert abs((minlon + maxlon) / 2 - lon) < 1e-9

    def test_lon_span_grows_with_latitude(self):
        zoom, gw, hc = 10.0, 80, 20
        b0 = bbox_for(0.0, 0.0, zoom, gw, hc)
        b60 = bbox_for(60.0, 0.0, zoom, gw, hc)
        span0 = b0[2] - b0[0]
        span60 = b60[2] - b60[0]
        assert span60 > span0
        # span grows as 1/cos(lat); at 60 degrees cos=0.5 so span should double
        assert math.isclose(span60, span0 / math.cos(math.radians(60.0)), rel_tol=1e-9)

    def test_returns_tuple_order(self):
        bbox = bbox_for(10.0, 20.0, 4.0, 40, 10)
        minlon, minlat, maxlon, maxlat = bbox
        assert minlon < maxlon
        assert minlat < maxlat


class TestBuildRadarBuffer:
    def test_zero_alpha_is_none(self):
        pw, ph = 2, 2
        rgba = bytearray(pw * ph * 4)  # all zero -> alpha 0 everywhere
        buf, echo = build_radar_buffer(rgba, pw, ph, graph_w=2, height_cells=1)
        for row in buf:
            for cell in row:
                assert cell is None
        assert echo == 0.0

    def test_opaque_pixel_exact_color(self):
        pw, ph = 2, 2
        rgba = bytearray(pw * ph * 4)
        rgba[0:4] = bytes([10, 20, 30, 255])  # pixel (0,0) fully opaque
        buf, echo = build_radar_buffer(rgba, pw, ph, graph_w=2, height_cells=1)
        assert buf[0][0] == (10, 20, 30)

    def test_partial_alpha_blends_toward_background(self):
        pw, ph = 1, 1
        rgba = bytearray([10, 20, 30, 128])
        buf, echo = build_radar_buffer(rgba, pw, ph, graph_w=1, height_cells=1)
        # spy_h = 2 but ph = 1, so only row 0 is populated
        expected = lerp(BG_PRIMARY, (10, 20, 30), 128 / 255)
        assert buf[0][0] == expected

    def test_echo_percentage(self):
        # 2x2 image (matches graph_w=2, height_cells=1 -> spy_h=2), one opaque pixel
        pw, ph = 2, 2
        rgba = bytearray(pw * ph * 4)
        rgba[0:4] = bytes([255, 255, 255, 255])
        buf, echo = build_radar_buffer(rgba, pw, ph, graph_w=2, height_cells=1)
        assert echo == 25.0

    def test_full_coverage_is_100_percent(self):
        pw, ph = 2, 2
        rgba = bytearray()
        for _ in range(pw * ph):
            rgba += bytes([1, 2, 3, 255])
        buf, echo = build_radar_buffer(rgba, pw, ph, graph_w=2, height_cells=1)
        assert echo == 100.0


class TestCompose:
    def test_returns_height_cells_lines(self):
        basemap = FakeBasemap(dots=[[0, 0] for _ in range(3)],
                               color=[[None, None] for _ in range(3)])
        radar = [[None, None] for _ in range(6)]  # spy_h = height_cells*2
        lines = compose(basemap, radar, {}, graph_w=2, height_cells=3)
        assert len(lines) == 3

    def test_overlay_beats_radar(self):
        basemap = FakeBasemap(dots=[[0]], color=[[None]])
        # radar present at this cell with two distinct colors (would draw a
        # half-block if not overridden by the overlay)
        radar = [[(10, 20, 30)], [(40, 50, 60)]]
        overlays = {(0, 0): ("X", (9, 9, 9))}
        lines = compose(basemap, radar, overlays, graph_w=1, height_cells=1)
        assert "X" in lines[0]
        assert HALF_BLOCK not in lines[0]

    def test_radar_cell_contains_half_block(self):
        basemap = FakeBasemap(dots=[[0]], color=[[None]])
        radar = [[(10, 20, 30)], [(40, 50, 60)]]
        lines = compose(basemap, radar, {}, graph_w=1, height_cells=1)
        assert HALF_BLOCK in lines[0]

    def test_braille_cell_contains_dot_char(self):
        basemap = FakeBasemap(dots=[[5]], color=[[(1, 2, 3)]])
        radar = [[None], [None]]
        lines = compose(basemap, radar, {}, graph_w=1, height_cells=1)
        assert chr(0x2800 + 5) in lines[0]

    def test_empty_cell_is_space(self):
        basemap = FakeBasemap(dots=[[0]], color=[[None]])
        radar = [[None], [None]]
        lines = compose(basemap, radar, {}, graph_w=1, height_cells=1)
        stripped = _strip_ansi(lines[0])
        assert stripped == " "

    def test_priority_order_across_row(self):
        # col0: overlay+radar -> overlay wins; col1: radar only -> half-block;
        # col2: braille dot only; col3: nothing -> space
        basemap = FakeBasemap(
            dots=[[0, 0, 7, 0]],
            color=[[None, None, (4, 5, 6), None]],
        )
        radar = [
            [(1, 1, 1), (10, 20, 30), None, None],
            [(1, 1, 1), (40, 50, 60), None, None],
        ]
        overlays = {(0, 0): ("Y", (9, 9, 9))}
        lines = compose(basemap, radar, overlays, graph_w=4, height_cells=1)
        line = lines[0]
        assert "Y" in line
        assert HALF_BLOCK in line
        assert chr(0x2800 + 7) in line
        assert _strip_ansi(line).count(" ") >= 1
