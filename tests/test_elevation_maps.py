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
    BATHY_STOPS, COAST_STROKE, HYPSO_FAMILIES, BORDER_STROKE, LAKE_FILL,
    _coast_dots, _edge_dots, _water_subpixels, build_terrain_buffer,
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


class TestInlandWater:
    """Lakes and rivers, which elevation alone cannot see: a terrarium
    sample over a lake is the height of the lake's surface, so the
    hypsometric ramp paints it as the meadow next door."""

    BBOX = (-71.5, 42.0, -70.5, 42.6)

    def _lake_on_the_right(self, meters):
        elev = [[meters] * 2 for _ in range(2)]
        water = [[False, True] for _ in range(2)]
        return (build_terrain_buffer(elev, self.BBOX, 2, 2),
                build_terrain_buffer(elev, self.BBOX, 2, 2, water))

    @staticmethod
    def _is_lake_tint(rgb):
        # the shade multiplier only ever dims the tint, and barely
        return all(int(c * 0.92) <= v <= c for c, v in zip(LAKE_FILL, rgb))

    def test_a_lake_on_a_hillside_takes_the_lake_tint(self):
        dry, wet = self._lake_on_the_right(500.0)
        assert wet[0][0] == dry[0][0]          # the land is untouched
        assert self._is_lake_tint(wet[0][1])
        assert not self._is_lake_tint(dry[0][1])

    def test_a_lake_below_sea_level_is_a_lake_and_not_the_sea(self):
        # the Dead Sea is not four hundred metres of open ocean
        dry, wet = self._lake_on_the_right(-400.0)
        assert self._is_lake_tint(wet[0][1])
        assert dry[0][1][2] > dry[0][1][0]     # the bathy ramp is blue
        assert not self._is_lake_tint(dry[0][1])

    def test_known_water_over_unknown_ground_still_reads_as_water(self):
        elev = [[None] * 2 for _ in range(2)]
        water = [[False, True] for _ in range(2)]
        buf = build_terrain_buffer(elev, self.BBOX, 2, 2, water)
        assert buf[0][0] == BG_PRIMARY
        assert buf[0][1] == LAKE_FILL

    def test_a_sub_pixel_needs_half_its_dots(self):
        # one cell: 2x4 dots -> 1x2 sub-pixels, each spanning 2x2 dots
        one = [bytearray((1, 0)), bytearray((0, 0)),
               bytearray((0, 0)), bytearray((0, 0))]
        two = [bytearray((1, 1)), bytearray((0, 0)),
               bytearray((0, 0)), bytearray((0, 0))]
        assert _water_subpixels(one, 1, 1) == [[False], [False]]
        assert _water_subpixels(two, 1, 1) == [[True], [False]]


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

    def test_a_lake_shore_is_stroked_exactly_like_a_sea_shore(self):
        # the same cell, once as sea and once as a lake the elevation
        # data cannot see: one union, one boundary, one rule
        sea = _coast_dots([[-5.0, 10.0] for _ in range(4)], 1, 1)
        lake = _coast_dots([[80.0, 80.0] for _ in range(4)], 1, 1,
                           water=[bytearray((1, 0)) for _ in range(4)])
        assert lake == sea

    def test_tile_water_over_land_is_water_and_not_both(self):
        # a dot in both masks would be stroked from its own side; the
        # union rule means the tile wins and nothing self-strokes
        water = [bytearray((1, 1)) for _ in range(4)]
        assert _coast_dots([[80.0, 80.0] for _ in range(4)], 1, 1,
                           water=water) == [[0]]


class TestEdgeDots:
    """The generalized stroke: two masks in, braille out.

    _coast_dots is now a thin wrapper over this, and the tile-water
    mask (S4) will be the second caller — same function, so the coast
    can never disagree with the fill in either mode.
    """

    def test_matches_coast_dots_on_the_same_grid(self):
        # 2 cells x 1: dot grid 4 wide x 4 tall.  Columns 0-1 are sea,
        # 2-3 are land, with two holes punched in the data.
        fine = [
            [-5.0, -5.0, 10.0, 10.0],
            [-5.0, -5.0, 10.0, 10.0],
            [None, -5.0, 10.0, 10.0],
            [-5.0, -5.0, 10.0, None],
        ]
        # the same grid, split into the two masks by hand
        is_land = [[False, False, True, True],
                   [False, False, True, True],
                   [False, False, True, True],
                   [False, False, True, False]]
        is_water = [[True, True, False, False],
                    [True, True, False, False],
                    [False, True, False, False],
                    [True, True, False, False]]
        # only dot column 2 is land touching water; it is the left
        # sub-column of cell 1, all four rows -> 0x01|0x02|0x04|0x40
        expected = [[0, 0x47]]
        assert _coast_dots(fine, 2, 1) == expected
        assert _edge_dots(is_land, is_water, 2, 1) == expected

    def test_unknown_next_to_water_is_never_stroked(self):
        # The case the old suite missed: a missing sample beside water.
        # It is in neither mask, so neither side of the boundary gets a
        # dot — a hole in the data must not invent a shoreline.
        fine = [[None, -5.0] for _ in range(4)]
        assert _coast_dots(fine, 1, 1) == [[0]]
        is_land = [[False, False] for _ in range(4)]
        is_water = [[False, True] for _ in range(4)]
        assert _edge_dots(is_land, is_water, 1, 1) == [[0]]

    def test_tile_masks_have_no_unknown_state(self):
        # How street mode calls it: is_land is simply "not water", so
        # every land dot on the boundary strokes.  West column water,
        # east column land -> the east sub-column of the cell.
        is_water = [[True, False] for _ in range(4)]
        is_land = [[not w for w in row] for row in is_water]
        assert _edge_dots(is_land, is_water, 1, 1) == [[0xB8]]

    def test_a_dot_in_both_masks_still_strokes_once(self):
        # Defensive: overlapping masks must not double-set or crash.
        is_land = [[True, True] for _ in range(4)]
        is_water = [[True, True] for _ in range(4)]
        assert _edge_dots(is_land, is_water, 1, 1) == [[0xFF]]


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

    def test_coast_beats_border_for_the_cell_ink(self):
        # Pinned because the street-mode rank table (coast 14 > border
        # 11) is written to agree with what terrain mode already does.
        terrain = [[(100, 120, 90)], [(100, 120, 90)]]
        bm = self.FakeBasemap([[0x01]], [[BORDER]])
        coast = [[0x02]]
        line = compose_terrain(bm, terrain, {}, 1, 1, coast=coast)[0]
        plain = re.sub(r"\033\[[^m]*m", "", line)
        assert plain[0] == chr(0x2800 + 0x03)     # both masks OR together
        assert f"38;2;{COAST_STROKE[0]};{COAST_STROKE[1]};{COAST_STROKE[2]}" \
            in line
        assert f"38;2;{BORDER_STROKE[0]};{BORDER_STROKE[1]};" \
            f"{BORDER_STROKE[2]}" not in line

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

    class FakeStrokeLayer:
        """Duck-type for the strokes= parameter: .dots + .color grids."""

        def __init__(self, dots, color):
            self.dots = dots
            self.color = color

    def test_stroke_layer_dots_and_ink(self):
        terrain = [[(100, 120, 90)] * 2, [(100, 120, 90)] * 2]
        bm = self.FakeBasemap([[0, 0]], [[None, None]])
        streets = self.FakeStrokeLayer([[0x07, 0]], [[(235, 197, 120), None]])
        lines = compose_terrain(bm, terrain, {}, 2, 1, strokes=[streets])
        plain = re.sub(r"\033\[[^m]*m", "", lines[0])
        # cell 0 strokes dots 0x07 in the layer's own ink; cell 1 is fill
        assert plain[0] == chr(0x2800 + 0x07)
        assert "38;2;235;197;120" in lines[0]

    def test_stroke_masks_or_with_coast_higher_layer_owns_ink(self):
        terrain = [[(100, 120, 90)], [(100, 120, 90)]]
        bm = self.FakeBasemap([[0]], [[None]])
        coast = [[0x01]]
        route = self.FakeStrokeLayer([[0x40]], [[(120, 220, 255)]])
        lines = compose_terrain(bm, terrain, {}, 1, 1, coast=coast,
                                strokes=[route])
        plain = re.sub(r"\033\[[^m]*m", "", lines[0])
        # coast dot 0x01 | route dot 0x40 merge into one glyph...
        assert plain[0] == chr(0x2800 + 0x41)
        # ...and the stroke layer's ink beats the coast's
        assert "38;2;120;220;255" in lines[0]

    def test_later_stroke_layer_wins_the_cell(self):
        terrain = [[(100, 120, 90)], [(100, 120, 90)]]
        bm = self.FakeBasemap([[0]], [[None]])
        streets = self.FakeStrokeLayer([[0x01]], [[(116, 120, 132)]])
        route = self.FakeStrokeLayer([[0x02]], [[(120, 220, 255)]])
        # strokes are ordered lowest priority first: route drawn last, wins
        line = compose_terrain(bm, terrain, {}, 1, 1,
                               strokes=[streets, route])[0]
        assert "38;2;120;220;255" in line
        assert "38;2;116;120;132" not in line

    def test_overlay_still_beats_strokes(self):
        terrain = [[(100, 120, 90)], [(100, 120, 90)]]
        bm = self.FakeBasemap([[0]], [[None]])
        streets = self.FakeStrokeLayer([[0xFF]], [[(116, 120, 132)]])
        line = compose_terrain(bm, terrain, {(0, 0): ("X", (1, 2, 3))}, 1, 1,
                               strokes=[streets])[0]
        plain = re.sub(r"\033\[[^m]*m", "", line)
        assert plain[0] == "X"

    def test_bold_overlay_third_element(self, monkeypatch):
        # BOLD/RESET are frozen to "" at import under pytest's no-tty
        # color mode; patch the exact globals compose_terrain reads —
        # after the test_oneline sys.modules purge, sys.modules holds a
        # *newer* module generation than the function bound at the top
        # of this file, so go through __globals__ rather than the module
        monkeypatch.setitem(compose_terrain.__globals__, "BOLD", "\033[1m")
        monkeypatch.setitem(compose_terrain.__globals__, "RESET", "\033[0m")
        terrain = [[(100, 120, 90)], [(100, 120, 90)]]
        bm = self.FakeBasemap([[0]], [[None]])
        plain_ov = compose_terrain(bm, terrain,
                                   {(0, 0): ("X", (1, 2, 3))}, 1, 1)[0]
        bold_ov = compose_terrain(bm, terrain,
                                  {(0, 0): ("X", (1, 2, 3), True)}, 1, 1)[0]
        assert "\033[1mX" not in plain_ov
        # bold glyph is followed by a full reset so the weight can't
        # leak into the next cell (the Framebuffer.render idiom)
        assert "\033[1mX\033[0m" in bold_ov


class TestDecodedTileMemo:
    """Terrarium tiles are immutable, and a pan re-reads nearly every
    tile the last view decoded — so the decode is memoised, checked
    against the bytes it came from."""

    BBOX = (-71.5, 42.0, -70.5, 42.6)

    @pytest.fixture(autouse=True)
    def _fresh(self):
        _elevation._decoded.clear()
        yield
        _elevation._decoded.clear()

    def test_the_same_bytes_decode_once(self, monkeypatch):
        png = _terrarium_png(256, 256, 40)
        calls = []
        real = _elevation.decode_rgba
        monkeypatch.setattr(_elevation, "decode_rgba",
                            lambda d: calls.append(1) or real(d))
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: png)
        elevation_grid(self.BBOX, 8, 4)
        first = len(calls)
        assert first > 0
        elevation_grid(self.BBOX, 8, 4)
        assert len(calls) == first

    def test_new_bytes_at_the_same_key_are_decoded_afresh(self, monkeypatch):
        tiles = [_terrarium_png(256, 256, 40)]
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: tiles[0])
        assert elevation_grid(self.BBOX, 4, 2)[0][0] == 40.0
        tiles[0] = _terrarium_png(256, 256, 900)
        assert elevation_grid(self.BBOX, 4, 2)[0][0] == 900.0

    def test_a_missing_tile_is_not_remembered(self, monkeypatch):
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: None)
        assert elevation_grid(self.BBOX, 4, 2)[0][0] is None
        png = _terrarium_png(256, 256, 12)
        monkeypatch.setattr(_elevation, "_fetch_tile",
                            lambda z, x, y, timeout=15: png)
        assert elevation_grid(self.BBOX, 4, 2)[0][0] == 12.0

    def test_the_memo_is_bounded(self):
        from linecast._png import DecodeMemo
        memo = DecodeMemo(cap=2)
        for i in range(3):
            memo.get(i, bytes([i]), lambda d: d * 2)
        assert list(memo._hits) == [1, 2]
        # a hit is refreshed, so the eviction order is by last use
        memo.get(1, b"\x01", lambda d: d * 2)
        memo.get(3, b"\x03", lambda d: d * 2)
        assert list(memo._hits) == [1, 3]

    def test_the_byte_budget_evicts_too(self):
        from linecast._png import DecodeMemo
        memo = DecodeMemo(cap=16, budget=10)
        memo.get("a", b"x" * 6, len)
        memo.get("b", b"y" * 6, len)
        assert list(memo._hits) == ["b"]
        memo.get("b", b"y" * 6, len)  # same bytes: served, not re-added
        assert memo._size == 6
