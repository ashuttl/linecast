"""Tests for the terrarium elevation source and the maps terrain renderer.

No network: the tile fetcher is monkeypatched to return synthetic
terrarium-encoded PNGs (8-bit RGB, the real tiles' format).
"""

import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _color, _elevation
from linecast._color import BG_PRIMARY
from linecast._elevation import decode_meters, elevation_grid
from linecast._radar_basemap import BORDER, COAST
from linecast.maps import (
    BATHY_STOPS, HYPSO_STOPS, _coast_dots, build_terrain_buffer,
    compose_terrain,
)

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype, data):
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _terrarium_png(width, height, meters):
    """A solid 8-bit RGB PNG encoding one elevation, terrarium-style."""
    v = int(meters + 32768)
    r, g, b = v >> 8, v & 0xFF, 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = bytes([0]) + bytes([r, g, b]) * width
    idat = zlib.compress(row * height)
    return b"".join([_SIG, _chunk(b"IHDR", ihdr), _chunk(b"IDAT", idat),
                     _chunk(b"IEND", b"")])


class TestDecodeMeters:
    def test_sea_level(self):
        assert decode_meters(128, 0, 0) == 0.0

    def test_everest(self):
        v = 32768 + 8848
        assert decode_meters(v >> 8, v & 0xFF, 0) == 8848.0

    def test_depth_with_fraction(self):
        v = 32768 - 4000
        assert decode_meters(v >> 8, v & 0xFF, 128) == -3999.5


class TestElevationGrid:
    def test_uniform_tiles_give_uniform_grid(self, monkeypatch):
        png = _terrarium_png(256, 256, 1234)
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: png)
        grid = elevation_grid((-71.5, 42.0, -70.5, 42.6), 20, 10)
        assert len(grid) == 10 and len(grid[0]) == 20
        assert all(v == 1234.0 for row in grid for v in row)

    def test_missing_tiles_give_none(self, monkeypatch):
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: None)
        grid = elevation_grid((-71.5, 42.0, -70.5, 42.6), 8, 4)
        assert all(v is None for row in grid for v in row)


class TestTerrainBuffer:
    BBOX = (-71.5, 42.0, -70.5, 42.6)

    def test_flat_land_is_uniform_hypso(self):
        elev = [[500.0] * 10 for _ in range(6)]
        buf = build_terrain_buffer(elev, self.BBOX, 10, 6)
        assert len({c for row in buf for c in row}) == 1
        # flat terrain shades identically, so only the ramp hue varies:
        # 500 m must land between the 400 and 800 stop colors (greens
        # heading to tan), i.e. red channel above the deep-green base
        assert buf[0][0][0] > 0

    def test_water_uses_bathy_ramp(self):
        deep = [[-4000.0] * 4 for _ in range(4)]
        shallow = [[-30.0] * 4 for _ in range(4)]
        b_deep = build_terrain_buffer(deep, self.BBOX, 4, 4)[1][1]
        b_shallow = build_terrain_buffer(shallow, self.BBOX, 4, 4)[1][1]
        assert sum(b_deep) < sum(b_shallow)  # deeper = darker
        assert b_deep[2] > b_deep[0]         # and blue-dominant

    def test_slope_changes_shade(self):
        # west-facing vs east-facing slopes get different light
        rising = [[float(x * 200) for x in range(10)] for _ in range(6)]
        falling = [[float((9 - x) * 200) for x in range(10)] for _ in range(6)]
        b1 = build_terrain_buffer(rising, self.BBOX, 10, 6)[3][5]
        b2 = build_terrain_buffer(falling, self.BBOX, 10, 6)[3][5]
        assert b1 != b2

    def test_none_renders_background(self):
        elev = [[None] * 4 for _ in range(4)]
        buf = build_terrain_buffer(elev, self.BBOX, 4, 4)
        assert buf[0][0] == BG_PRIMARY


class TestCoastDots:
    def test_vertical_shoreline(self):
        # 1 cell: fine grid 2 wide x 4 tall, west column water, east land —
        # every land dot touches water, so the east dot column is stroked
        fine = [[-5.0, 10.0] for _ in range(4)]
        dots = _coast_dots(fine, 1, 1)
        assert dots == [[0x08 | 0x10 | 0x20 | 0x80]]  # right-column bits

    def test_all_land_or_all_sea_draws_nothing(self):
        assert _coast_dots([[100.0, 100.0]] * 4, 1, 1) == [[0]]
        assert _coast_dots([[-100.0, -100.0]] * 4, 1, 1) == [[0]]

    def test_missing_data_is_not_water(self):
        # a None neighbor (missing tile) must not fake a coastline
        fine = [[None, 10.0] for _ in range(4)]
        assert _coast_dots(fine, 1, 1) == [[0]]


class TestComposeTerrain:
    # patch the _color module *imported at the top of this file*: it is the
    # same module generation compose_terrain reads, even after test_oneline
    # purges sys.modules and later imports resolve to fresh copies
    @pytest.fixture(autouse=True)
    def _truecolor(self, monkeypatch):
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")

    class FakeBasemap:
        def __init__(self, dots, color):
            self.dots = dots
            self.color = color

    def test_ne_coast_dropped_border_kept(self):
        terrain = [[(100, 120, 90)] * 3, [(100, 120, 90)] * 3]
        # cells 0-1: Natural Earth coast strokes (both become fill — the
        # drawn coastline is derived from elevation instead);
        # cell 2: border stroke (kept)
        bm = self.FakeBasemap([[0x01, 0x02, 0x04]],
                              [[COAST, (120, 150, 178), BORDER]])
        lines = compose_terrain(bm, terrain, {}, 3, 1)
        plain = re.sub(r"\033\[[^m]*m", "", lines[0])
        assert plain == "  ⠄"
        assert "48;2;100;120;90" in lines[0]

    def test_derived_coast_stroked(self):
        terrain = [[(100, 120, 90)] * 2, [(100, 120, 90)] * 2]
        bm = self.FakeBasemap([[0, 0]], [[None, None]])
        coast = [[0, 0x03]]
        lines = compose_terrain(bm, terrain, {}, 2, 1, coast=coast)
        plain = re.sub(r"\033\[[^m]*m", "", lines[0])
        assert plain == " " + chr(0x2800 + 0x03)

    def test_overlay_ink_contrast(self):
        light = [[(230, 230, 235)], [(230, 230, 235)]]
        dark = [[(20, 30, 40)], [(20, 30, 40)]]
        bm = self.FakeBasemap([[0]], [[None]])
        on_light = compose_terrain(bm, light, {(0, 0): ("X", None)}, 1, 1)[0]
        on_dark = compose_terrain(bm, dark, {(0, 0): ("X", None)}, 1, 1)[0]
        from linecast.maps import LABEL_DARK, LABEL_LIGHT
        assert f"38;2;{LABEL_DARK[0]};{LABEL_DARK[1]};{LABEL_DARK[2]}" in on_light
        assert f"38;2;{LABEL_LIGHT[0]};{LABEL_LIGHT[1]};{LABEL_LIGHT[2]}" in on_dark

    def test_explicit_ink_respected(self):
        terrain = [[(100, 100, 100)], [(100, 100, 100)]]
        bm = self.FakeBasemap([[0]], [[None]])
        line = compose_terrain(bm, terrain, {(0, 0): ("+", (255, 240, 120))},
                               1, 1)[0]
        assert "38;2;255;240;120" in line
