"""Tests for the street-mode tile rasteriser.

No network and no binary fixtures: every tile is hand-encoded in-test
with a minimal protobuf writer, so a rasteriser bug cannot be masked by
a fixture recorded from the same code.

The geometry is arranged so the expectations are derivable by hand.
Longitude is exactly linear in both tile space and view space, so a
polygon that spans the full tile height and half its width lands on an
exact dot column no matter what the mercator latitude curve does. The
view is therefore the whole world (the z0 tile), and every assertion is
about columns.
"""

import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_streets as st
from linecast import _maps_style

WORLD = (-180.0, -85.0511287798066, 180.0, 85.0511287798066)
EXTENT = 4096
DARK_BG = (14, 15, 18)


# ---------------------------------------------------------------------------
# Minimal protobuf writer (independent of the decoder)
# ---------------------------------------------------------------------------
def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(num, wt, payload):
    key = varint((num << 3) | wt)
    if wt == 0:
        return key + varint(payload)
    return key + varint(len(payload)) + payload


def zigzag(n):
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


def cmd(cid, count):
    return (count << 3) | cid


def rect(x0, y0, x1, y1):
    """A closed exterior ring: clockwise on screen (y down) so the
    shoelace sum is positive and _mvt reads it as an exterior."""
    nums = [cmd(1, 1), zigzag(x0), zigzag(y0),
            cmd(2, 3),
            zigzag(x1 - x0), zigzag(0),
            zigzag(0), zigzag(y1 - y0),
            zigzag(x0 - x1), zigzag(0),
            cmd(7, 1)]
    return b"".join(varint(n) for n in nums)


def feature(geometry, tags=()):
    out = field(3, 0, 3)                      # type: polygon
    if tags:
        out += field(2, 2, b"".join(varint(t) for t in tags))
    return out + field(4, 2, geometry)


def layer(name, features, keys=(), values=(), extent=EXTENT):
    parts = [field(15, 0, 2), field(1, 2, name.encode())]
    parts += [field(2, 2, f) for f in features]
    parts += [field(3, 2, k.encode()) for k in keys]
    parts += [field(4, 2, field(1, 2, v.encode())) for v in values]
    parts.append(field(5, 0, extent))
    return b"".join(parts)


def tile(*layers):
    return b"".join(field(3, 2, lyr) for lyr in layers)


def classed(name, geometry, cls, key="class"):
    """One polygon feature carrying a single string property."""
    return layer(name, [feature(geometry, tags=(0, 0))],
                 keys=(key,), values=(cls,))


# Left half of the world, full height (and past it, into the tile's own
# buffer, so the polygon covers every dot row).
LEFT_HALF = rect(0, -EXTENT, EXTENT // 2, 2 * EXTENT)
WHOLE = rect(-EXTENT, -EXTENT, 2 * EXTENT, 2 * EXTENT)
# A speck: a quarter of a dot column at gw=4, so it cannot fill a
# sub-pixel on its own.
SPECK = rect(0, 0, 64, 64)

GW, HC = 4, 1
Z0 = (0, 0, 0)


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(_maps_style, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(_maps_style, "theme_bg", DARK_BG)


def build(*layers, band=7):
    return st.build_street_view(WORLD, GW, HC, {Z0: tile(*layers)}, band)


def ink(key):
    return _maps_style.palette()[key]


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------
class TestFills:
    def test_water_fills_the_left_half_and_ground_the_rest(self):
        fills, _layer = build(classed("water", LEFT_HALF, "lake"))
        assert len(fills) == HC * 2
        for row in fills:
            assert row == [ink("water"), ink("water"),
                           ink("ground"), ink("ground")]

    def test_water_stacks_over_park(self):
        # A pond in a park: water is above park in the stacking order.
        fills, _layer = build(classed("park", WHOLE, "public_park"),
                              classed("water", LEFT_HALF, "lake"))
        assert fills[0] == [ink("water"), ink("water"),
                            ink("park"), ink("park")]

    def test_buildings_sit_on_everything(self):
        fills, _layer = build(classed("water", WHOLE, "lake"),
                              layer("building", [feature(LEFT_HALF)]))
        assert fills[0] == [ink("building"), ink("building"),
                            ink("water"), ink("water")]

    def test_swimming_pools_are_not_water(self):
        fills, _layer = build(classed("water", LEFT_HALF, "swimming_pool"))
        assert fills[0] == [ink("ground")] * GW

    def test_landcover_paints_parks_and_nothing_else(self):
        # No grass, wood, farmland, wetland or sand — the single largest
        # declutter decision in the style spec.
        park = layer("landcover", [feature(LEFT_HALF, tags=(0, 0))],
                     keys=("subclass",), values=("park",))
        wood = layer("landcover", [feature(LEFT_HALF, tags=(0, 0))],
                     keys=("subclass",), values=("wood",))
        assert build(park)[0][0][0] == ink("park")
        assert build(wood)[0][0][0] == ink("ground")

    def test_landuse_splits_into_urban_and_cemetery(self):
        assert build(classed("landuse", LEFT_HALF,
                             "residential"))[0][0][0] == ink("urban")
        assert build(classed("landuse", LEFT_HALF,
                             "cemetery"))[0][0][0] == ink("park")
        assert build(classed("landuse", LEFT_HALF,
                             "quarry"))[0][0][0] == ink("ground")

    def test_a_line_feature_in_a_fill_layer_is_ignored(self):
        line = layer("water", [field(3, 0, 2) + field(4, 2, LEFT_HALF)])
        assert build(line)[0][0][0] == ink("ground")

    def test_a_building_smaller_than_a_sub_pixel_is_dropped(self):
        assert build(layer("building", [feature(SPECK)]))[0][0][0] \
            == ink("ground")

    def test_an_undecodable_tile_is_skipped_not_fatal(self):
        fills, _layer = st.build_street_view(
            WORLD, GW, HC, {Z0: b"\xff\xff\xff\xff"}, 7)
        assert fills[0] == [ink("ground")] * GW

    def test_a_missing_tile_contributes_nothing(self):
        fills, _layer = st.build_street_view(WORLD, GW, HC, {Z0: None}, 7)
        assert fills[0] == [ink("ground")] * GW


class TestBandGates:
    """A class must never appear before the tile can actually carry it."""

    def test_water_is_present_from_the_very_first_band(self):
        assert build(classed("water", LEFT_HALF, "lake"),
                     band=0)[0][0][0] == ink("water")

    def test_parks_wait_for_band_three(self):
        park = classed("park", LEFT_HALF, "public_park")
        assert build(park, band=2)[0][0][0] == ink("ground")
        assert build(park, band=3)[0][0][0] == ink("park")

    def test_landcover_and_landuse_wait_for_band_five(self):
        cover = layer("landcover", [feature(LEFT_HALF, tags=(0, 0))],
                      keys=("subclass",), values=("park",))
        use = classed("landuse", LEFT_HALF, "residential")
        assert build(cover, band=4)[0][0][0] == ink("ground")
        assert build(cover, band=5)[0][0][0] == ink("park")
        assert build(use, band=4)[0][0][0] == ink("ground")
        assert build(use, band=5)[0][0][0] == ink("urban")

    def test_buildings_wait_for_band_seven(self):
        b = layer("building", [feature(LEFT_HALF)])
        assert build(b, band=6)[0][0][0] == ink("ground")
        assert build(b, band=7)[0][0][0] == ink("building")


# ---------------------------------------------------------------------------
# The coast
# ---------------------------------------------------------------------------
class TestCoast:
    def test_the_coast_traces_the_water_fill(self):
        # Water covers dot columns 0-3 of 8, so the stroked dots are the
        # land column that touches it — dot column 4, which is the left
        # sub-column of cell 2: bits 0x01|0x02|0x04|0x40.
        _fills, layer_ = build(classed("water", LEFT_HALF, "lake"))
        assert layer_.dots[0] == [0, 0, 0x47, 0]
        assert layer_.color[0][2] == ink("coast")
        assert layer_.rank[0][2] == _maps_style.LINE_STYLES["coast"][3]

    def test_no_water_means_no_coast(self):
        _fills, layer_ = build(classed("park", WHOLE, "public_park"))
        assert layer_.dots[0] == [0, 0, 0, 0]

    def test_a_building_over_water_does_not_erase_the_coast(self):
        # The water mask is snapshotted before buildings are painted, so
        # a pier or a boathouse cannot punch a hole in the shoreline.
        fills, layer_ = build(classed("water", LEFT_HALF, "lake"),
                              layer("building", [feature(LEFT_HALF)]))
        assert fills[0][0] == ink("building")
        assert layer_.dots[0] == [0, 0, 0x47, 0]

    def test_the_stroke_and_the_fill_agree_cell_for_cell(self):
        # Every stroked cell must border the painted water; this is the
        # invariant the whole _edge_dots exercise exists to guarantee.
        fills, layer_ = build(classed("water", LEFT_HALF, "lake"))
        for cx, mask in enumerate(layer_.dots[0]):
            if mask:
                neighbours = {fills[0][max(0, cx - 1)],
                              fills[0][min(GW - 1, cx + 1)]}
                assert ink("water") in neighbours


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestFillColors:
    def _grid(self, quad):
        """One cell — four dot rows — carrying `quad` in each of its two
        sub-pixels, so row 0 of the result is the quad's reduction."""
        rows = [bytearray([quad[0], quad[1]]), bytearray([quad[2], quad[3]])]
        return rows + [r[:] for r in rows]

    def test_half_a_quad_is_enough(self):
        palette = _maps_style.palette()
        two = self._grid((st.WATER, st.WATER, st.GROUND, st.GROUND))
        one = self._grid((st.WATER, st.GROUND, st.GROUND, st.GROUND))
        assert st.fill_colors(two, 1, 1, palette)[0][0] == palette["water"]
        assert st.fill_colors(one, 1, 1, palette)[0][0] == palette["ground"]

    def test_the_topmost_qualifying_class_wins_a_split_quad(self):
        palette = _maps_style.palette()
        grid = self._grid((st.WATER, st.WATER, st.BUILDING, st.BUILDING))
        assert st.fill_colors(grid, 1, 1, palette)[0][0] \
            == palette["building"]

    def test_coarse_palettes_leave_the_ground_unpainted(self, monkeypatch):
        monkeypatch.setattr(_maps_style, "color_mode", lambda: "16")
        palette = _maps_style.palette()
        grid = self._grid((st.WATER, st.WATER, st.GROUND, st.PARK))
        assert st.fill_colors(grid, 1, 1, palette)[0][0] == (0, 0, 128)
        grid = self._grid((st.PARK, st.PARK, st.GROUND, st.GROUND))
        assert st.fill_colors(grid, 1, 1, palette)[0][0] is None


class TestProjector:
    def test_tile_corners_land_on_view_corners(self):
        project = st._projector(0, 0, 0, EXTENT, WORLD, 8, 4)
        assert project(0, 0) == pytest.approx((0.0, 0.0))
        x, y = project(EXTENT, EXTENT)
        assert x == pytest.approx(8.0)
        assert y == pytest.approx(4.0)

    def test_longitude_is_exactly_linear(self):
        project = st._projector(0, 0, 0, EXTENT, WORLD, 8, 4)
        assert project(EXTENT // 2, 0)[0] == pytest.approx(4.0)
        assert project(EXTENT // 4, 0)[0] == pytest.approx(2.0)

    def test_a_wrapped_tile_lands_beside_its_neighbour(self):
        # A view straddling the antimeridian holds tile x=0, whose
        # longitudes come back on the far side of the world.
        bbox = (179.0, 0.0, 181.0, 1.0)
        east = st._projector(1, 1, 0, EXTENT, bbox, 100, 100)   # 0..180E
        west = st._projector(1, 0, 0, EXTENT, bbox, 100, 100)   # 180W..0
        assert east(EXTENT, 0)[0] == pytest.approx(50.0)   # 180 -> midway
        assert west(0, 0)[0] == pytest.approx(50.0)        # -180 -> same


class TestFillClass:
    def test_unknown_layers_and_classes_are_dropped(self):
        assert st.fill_class("transportation", {"class": "motorway"}, 7) \
            is None
        assert st.fill_class("landuse", {"class": "military"}, 7) is None
        assert st.fill_class("water", {}, 0) == st.WATER


class TestViewTiles:
    def test_band_and_source_zoom_come_from_the_style_model(self,
                                                            monkeypatch):
        monkeypatch.setattr(st, "tile_info",
                            lambda: ("http://x/{z}/{x}/{y}", "v", 14))
        bbox = (-70.4, 43.6, -70.3, 43.7)      # 0.1 deg -> band 3
        band, z_src, keys = st.view_tiles(bbox, 22)
        assert band == 3
        assert z_src == 10
        assert keys and all(k[0] == z_src for k in keys)

    def test_deep_bands_pin_the_source_to_z14(self, monkeypatch):
        monkeypatch.setattr(st, "tile_info",
                            lambda: ("http://x/{z}/{x}/{y}", "v", 14))
        bbox = (-70.371, 43.677, -70.3705, 43.6782)
        band, z_src, _keys = st.view_tiles(bbox, 22)
        assert band >= 6
        assert z_src == 14

    def test_the_servers_maxzoom_is_respected(self, monkeypatch):
        monkeypatch.setattr(st, "tile_info",
                            lambda: ("http://x/{z}/{x}/{y}", "v", 9))
        bbox = (-70.371, 43.677, -70.3705, 43.6782)
        _band, z_src, _keys = st.view_tiles(bbox, 22)
        assert z_src == 9

    def test_a_pathological_window_coarsens_rather_than_hammering(self,
                                                                  monkeypatch):
        monkeypatch.setattr(st, "tile_info",
                            lambda: ("http://x/{z}/{x}/{y}", "v", 14))
        # A very wide, very short window: z_eff is driven by the height,
        # so the tile count across is enormous at the nominal zoom.
        bbox = (-180.0, 43.677, 180.0, 43.6782)
        _band, _z_src, keys = st.view_tiles(bbox, 22)
        assert len(keys) <= st._MAX_TILES

    def test_no_tilejson_still_yields_a_plan(self, monkeypatch):
        monkeypatch.setattr(st, "tile_info", lambda: None)
        band, z_src, keys = st.view_tiles((-70.4, 43.6, -70.3, 43.7), 22)
        assert band == 3
        assert z_src <= 14
        assert keys
