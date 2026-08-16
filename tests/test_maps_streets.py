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
from linecast._radar_basemap import DotLayer

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


def vstr(s):
    return field(1, 2, s.encode())


def vint(n):
    return field(4, 0, n)


def layer(name, features, keys=(), values=(), extent=EXTENT):
    """`values` are pre-encoded Value payloads (vstr/vint)."""
    parts = [field(15, 0, 2), field(1, 2, name.encode())]
    parts += [field(2, 2, f) for f in features]
    parts += [field(3, 2, k.encode()) for k in keys]
    parts += [field(4, 2, v) for v in values]
    parts.append(field(5, 0, extent))
    return b"".join(parts)


def polyline(*pts):
    """A linestring: MoveTo the first point, LineTo the rest."""
    nums = [cmd(1, 1), zigzag(pts[0][0]), zigzag(pts[0][1]),
            cmd(2, len(pts) - 1)]
    prev = pts[0]
    for p in pts[1:]:
        nums += [zigzag(p[0] - prev[0]), zigzag(p[1] - prev[1])]
        prev = p
    return b"".join(varint(n) for n in nums)


def line_feature(geometry, tags=()):
    out = field(3, 0, 2)                      # type: linestring
    if tags:
        out += field(2, 2, b"".join(varint(t) for t in tags))
    return out + field(4, 2, geometry)


def tagged_line(name, geometry, props):
    """One linestring feature carrying `props` (str or int values)."""
    keys, values, tags = [], [], []
    for i, (k, v) in enumerate(props.items()):
        keys.append(k)
        values.append(vint(v) if isinstance(v, int) else vstr(v))
        tags += [i, i]
    return layer(name, [line_feature(geometry, tags=tags)],
                 keys=keys, values=values)


def tile(*layers):
    return b"".join(field(3, 2, lyr) for lyr in layers)


def classed(name, geometry, cls, key="class"):
    """One polygon feature carrying a single string property."""
    return layer(name, [feature(geometry, tags=(0, 0))],
                 keys=(key,), values=(vstr(cls),))


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
        fills, _layer, _labels = build(classed("water", LEFT_HALF, "lake"))
        assert len(fills) == HC * 2
        for row in fills:
            assert row == [ink("water"), ink("water"),
                           ink("ground"), ink("ground")]

    def test_water_stacks_over_park(self):
        # A pond in a park: water is above park in the stacking order.
        fills, _layer, _labels = build(
            classed("park", WHOLE, "public_park"),
            classed("water", LEFT_HALF, "lake"))
        assert fills[0] == [ink("water"), ink("water"),
                            ink("park"), ink("park")]

    def test_buildings_sit_on_everything(self):
        fills, _layer, _labels = build(
            classed("water", WHOLE, "lake"),
            layer("building", [feature(LEFT_HALF)]))
        assert fills[0] == [ink("building"), ink("building"),
                            ink("water"), ink("water")]

    def test_swimming_pools_are_not_water(self):
        fills, _layer, _labels = build(
            classed("water", LEFT_HALF, "swimming_pool"))
        assert fills[0] == [ink("ground")] * GW

    def test_landcover_paints_parks_and_nothing_else(self):
        # No grass, wood, farmland, wetland or sand — the single largest
        # declutter decision in the style spec.
        park = layer("landcover", [feature(LEFT_HALF, tags=(0, 0))],
                     keys=("subclass",), values=(vstr("park"),))
        wood = layer("landcover", [feature(LEFT_HALF, tags=(0, 0))],
                     keys=("subclass",), values=(vstr("wood"),))
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
        fills, _layer, _labels = st.build_street_view(
            WORLD, GW, HC, {Z0: b"\xff\xff\xff\xff"}, 7)
        assert fills[0] == [ink("ground")] * GW

    def test_a_missing_tile_contributes_nothing(self):
        fills, _layer, _labels = st.build_street_view(
            WORLD, GW, HC, {Z0: None}, 7)
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
                      keys=("subclass",), values=(vstr("park"),))
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
        _fills, layer_, _labels = build(classed("water", LEFT_HALF, "lake"))
        assert layer_.dots[0] == [0, 0, 0x47, 0]
        assert layer_.color[0][2] == ink("coast")
        assert layer_.rank[0][2] == _maps_style.LINE_STYLES["coast"][3]

    def test_no_water_means_no_coast(self):
        _fills, layer_, _labels = build(classed("park", WHOLE, "public_park"))
        assert layer_.dots[0] == [0, 0, 0, 0]

    def test_a_building_over_water_does_not_erase_the_coast(self):
        # The water mask is snapshotted before buildings are painted, so
        # a pier or a boathouse cannot punch a hole in the shoreline.
        fills, layer_, _labels = build(classed("water", LEFT_HALF, "lake"),
                              layer("building", [feature(LEFT_HALF)]))
        assert fills[0][0] == ink("building")
        assert layer_.dots[0] == [0, 0, 0x47, 0]

    def test_the_stroke_and_the_fill_agree_cell_for_cell(self):
        # Every stroked cell must border the painted water; this is the
        # invariant the whole _edge_dots exercise exists to guarantee.
        fills, layer_, _labels = build(classed("water", LEFT_HALF, "lake"))
        for cx, mask in enumerate(layer_.dots[0]):
            if mask:
                neighbours = {fills[0][max(0, cx - 1)],
                              fills[0][min(GW - 1, cx + 1)]}
                assert ink("water") in neighbours


# ---------------------------------------------------------------------------
# Terrain mode's half: inland water only
# ---------------------------------------------------------------------------
class TestInlandWater:
    """What terrain mode takes from the tiles.  Not the ocean: below sea
    level is bathymetry's job there, and the low-zoom ocean polygon is
    generalised past the coastline the elevation data draws."""

    def _mask(self, cls):
        view = st.decode_view({Z0: tile(classed("water", LEFT_HALF, cls))})
        return st.inland_water_mask(view, WORLD, GW, HC)

    def test_a_lake_fills_the_left_half(self):
        assert all(list(row) == [1, 1, 1, 1, 0, 0, 0, 0]
                   for row in self._mask("lake"))

    def test_the_ocean_is_not_inland_water(self):
        assert not any(any(row) for row in self._mask("ocean"))

    def test_a_swimming_pool_is_not_a_lake_either(self):
        assert not any(any(row) for row in self._mask("swimming_pool"))

    def test_a_river_polygon_counts(self):
        # a riverbank wide enough to be a polygon is water like any other
        assert any(any(row) for row in self._mask("river"))


class TestWaterLines:
    """Rivers, which have no polygon until they are wide enough to have
    one — terrain's band gates, not street's."""

    def _lit(self, cls, band, color=(1, 2, 3)):
        line = polyline((0, EXTENT // 2), (EXTENT, EXTENT // 2))
        view = st.decode_view({Z0: tile(tagged_line("waterway", line,
                                                    {"class": cls}))})
        layer_ = st.water_lines(view, WORLD, GW, HC, band, color)
        lit = sum(bin(m).count("1") for row in layer_.dots for m in row)
        return lit, layer_

    def test_a_river_is_drawn_from_band_one(self):
        assert self._lit("river", 0)[0] == 0    # B0: a river is a scratch
        assert self._lit("river", 1)[0] > 0

    def test_a_stream_waits_for_the_deep_bands(self):
        assert self._lit("stream", 5)[0] == 0
        assert self._lit("stream", 6)[0] > 0

    def test_the_stroke_carries_the_ink_it_was_given(self):
        _lit, layer_ = self._lit("river", 4, color=(9, 8, 7))
        assert (9, 8, 7) in [c for row in layer_.color for c in row if c]

    def test_a_ferry_is_not_a_river(self):
        assert self._lit("ferry", 7)[0] == 0

    def test_a_centreline_yields_to_the_water_it_runs_through(self):
        # Terrain draws its inland mask and the river over it; where the
        # mask is wide enough to draw itself, the centreline is a seam.
        line = polyline((0, EXTENT // 2), (EXTENT, EXTENT // 2))
        view = st.decode_view({Z0: tile(
            tagged_line("waterway", line, {"class": "river"}),
            classed("water", WHOLE, "lake"))})
        gw, hc = 16, 4
        water = st.inland_water_mask(view, WORLD, gw, hc)
        assert any(any(row) for row in water)
        bare = st.water_lines(view, WORLD, gw, hc, 4, (1, 2, 3))
        hidden = st.water_lines(view, WORLD, gw, hc, 4, (1, 2, 3), water)
        assert any(any(row) for row in bare.dots)
        assert not any(any(row) for row in hidden.dots)


# ---------------------------------------------------------------------------
# Water wide enough to speak for itself
# ---------------------------------------------------------------------------
def dot_mask(rows):
    """A dot-resolution water mask from an ASCII picture ('~' = water)."""
    return [bytearray(1 if ch == "~" else 0 for ch in row) for row in rows]


def as_text(mask):
    return ["".join("~" if v else "." for v in row) for row in mask]


class TestOpenWater:
    """The erosion behind the centreline rule: which water is wide
    enough that its own fill and coastline already say so."""

    def test_a_wide_body_keeps_its_core(self):
        # Eight dots across, ten down, in open land.
        mask = dot_mask(["." * 12] * 2 + ["..~~~~~~~~.."] * 10
                        + ["." * 12] * 2)
        out = as_text(st.open_water(mask, 3))
        # A surviving dot needs four dots of water each way, itself
        # included, so an eight-wide body keeps two columns and a
        # ten-deep one keeps four rows.
        assert out[5] == out[8] == ".....~~....."
        assert out[4] == out[9] == "." * 12
        assert set("".join(out)) == {".", "~"}

    def test_a_hairline_channel_keeps_its_centreline(self):
        # One dot of river is a polygon the centreline is still carrying,
        # however far it runs.
        mask = dot_mask(["." * 12] * 5 + ["~" * 12] + ["." * 12] * 6)
        assert not any(any(row) for row in st.open_water(mask, 3))

    def test_dry_land_hides_nothing(self):
        mask = dot_mask(["." * 12] * 12)
        assert not any(any(row) for row in st.open_water(mask, 3))

    def test_water_running_off_the_view_is_assumed_to_continue(self):
        # The mask holds only what is on screen.  Truncating the run at
        # the edge would leave a stub of centreline in the last few dots
        # of an estuary, appearing and disappearing as you pan.
        mask = dot_mask(["~" * 12] * 12)
        out = st.open_water(mask, 3)
        assert all(all(row) for row in out)

    def test_the_radius_defaults_to_the_style_table(self):
        mask = dot_mask(["." * 12] * 5 + ["~" * 12] + ["." * 12] * 6)
        radius = _maps_style.WATERWAY_HIDE_DOTS
        assert (as_text(st.open_water(mask))
                == as_text(st.open_water(mask, radius)))


class TestCentrelineSuppression:
    """A river arrives twice — a polygon in `water` and a centreline in
    `waterway` — and OpenStreetMap carries the centreline the length of
    a tidal estuary.  Where the polygon can draw itself, it does."""

    GW, HC = 16, 4

    def _cells(self, water):
        line = polyline((0, EXTENT // 2), (EXTENT, EXTENT // 2))
        view = st.decode_view({Z0: tile(
            tagged_line("waterway", line, {"class": "river"}),
            classed("water", LEFT_HALF, "river"))})
        layer = DotLayer(WORLD, self.GW, self.HC)
        st.draw_lines(layer, view, WORLD, self.GW, self.HC, 7,
                      _maps_style.palette(), water)
        # `waterway` is the only line layer in the tile, so every dot
        # the pass drew is centreline.
        return {(col, row) for row, line_ in enumerate(layer.dots)
                for col, mask in enumerate(line_) if mask}

    def _mask(self):
        view = st.decode_view({Z0: tile(classed("water", LEFT_HALF,
                                                "river"))})
        return st.class_grid(view, WORLD, self.GW, self.HC, 7)[1]

    def test_the_seam_over_open_water_goes(self):
        # The left half is the water; its middle is where the polygon is
        # widest and the centreline least needed.
        wet = {c for c, _r in self._cells(self._mask())}
        assert self.GW // 4 not in wet

    def test_the_same_river_on_dry_land_is_untouched(self):
        # Only the reach inside the polygon is dropped; the rest of the
        # line is drawn exactly as it was.
        bare = self._cells(None)
        kept = self._cells(self._mask())
        assert kept < bare
        assert {c for c, _r in kept} & {c for c, _r in bare
                                        if c >= self.GW * 3 // 4}

    def test_no_mask_means_no_suppression(self):
        bare = {c for c, _r in self._cells(None)}
        assert self.GW // 4 in bare


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
        # The style zoom is ~10; the source runs a lookahead ahead of it,
        # because a z10 tile is generalised past the point of carrying
        # names and nothing drawn is gated on the tile anyway.
        assert z_src == 10 + _maps_style.Z_SRC_LOOKAHEAD
        assert keys and all(k[0] == z_src for k in keys)

    def test_the_lookahead_stays_inside_the_tile_budget(self, monkeypatch):
        # The guard below is for pathological windows, not for the
        # ordinary case: an ordinary street view must never wake it.
        monkeypatch.setattr(st, "tile_info",
                            lambda: ("http://x/{z}/{x}/{y}", "v", 14))
        for deg in (4.0, 1.0, 0.4, 0.12, 0.05, 0.025, 0.012):
            half = deg / 2
            bbox = (-70.371 - deg, 43.677 - half, -70.371 + deg,
                    43.677 + half)
            _band, z_src, keys = st.view_tiles(bbox, 34)
            assert len(keys) <= st._MAX_TILES, (deg, z_src, len(keys))

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


# ---------------------------------------------------------------------------
# The polyline walker
# ---------------------------------------------------------------------------
RED, BLUE = (255, 0, 0), (0, 0, 255)


def _layer():
    """A 4x1 cell layer: 8 dot columns, 4 dot rows."""
    return DotLayer(WORLD, GW, HC)


class TestStrokePolyline:
    def test_a_horizontal_w1_line(self):
        # Dot row 0 across all 8 columns. Each cell holds two dot
        # columns, so it takes the row-0 bit of each: 0x01 | 0x08.
        layer = _layer()
        st.stroke_polyline(layer, [(0, 0), (7, 0)], RED, 34)
        assert layer.dots[0] == [0x09] * 4
        assert layer.color[0][0] == RED

    def test_weight_two_thickens_across_the_dominant_axis(self):
        # Horizontal: the second pass is offset down, never diagonally —
        # the basemap's (1,0),(0,1) pair thickens diagonals into fuzz.
        flat = _layer()
        st.stroke_polyline(flat, [(0, 0), (7, 0)], RED, 34, weight=2)
        assert flat.dots[0] == [0x1B] * 4          # rows 0 and 1
        # Vertical: offset sideways instead, filling the whole cell.
        tall = _layer()
        st.stroke_polyline(tall, [(0, 0), (0, 3)], RED, 34, weight=2)
        assert tall.dots[0] == [0xFF, 0, 0, 0]

    def test_weight_three_claims_its_cells_for_the_ribbon(self):
        layer = _layer()
        st.stroke_polyline(layer, [(0, 0), (7, 0)], RED, 50, weight=3)
        assert layer.ribbon == {(0, 0), (1, 0), (2, 0), (3, 0)}
        assert layer.dots[0] == [0x1B] * 4         # still a w2 stroke

    def test_weight_one_claims_no_ribbon(self):
        layer = _layer()
        st.stroke_polyline(layer, [(0, 0), (7, 0)], RED, 50)
        assert layer.ribbon == set()

    def test_a_dash_runs_on_the_dot_index(self):
        # DASH24: two dots on, four off, so dots 0,1 and 6,7 survive.
        layer = _layer()
        st.stroke_polyline(layer, [(0, 0), (7, 0)], RED, 10, dash=(2, 4))
        assert layer.dots[0] == [0x09, 0, 0, 0x09]

    def test_dash_phase_is_continuous_through_a_vertex(self):
        # A vertex mid-line must not restart the pattern; the walker
        # counts dots along the whole polyline, not per segment.
        split = _layer()
        st.stroke_polyline(split, [(0, 0), (3, 0), (7, 0)], RED, 10,
                           dash=(2, 4))
        whole = _layer()
        st.stroke_polyline(whole, [(0, 0), (7, 0)], RED, 10, dash=(2, 4))
        assert split.dots == whole.dots

    def test_a_repeated_vertex_is_dropped(self):
        # A generalised line often repeats a vertex; rounding onto the
        # dot the walker is already standing on must not cost a dot of
        # dash phase.
        stutter = _layer()
        st.stroke_polyline(stutter, [(0, 0), (0.2, 0.1), (7, 0)], RED, 10,
                           dash=(2, 4))
        clean = _layer()
        st.stroke_polyline(clean, [(0, 0), (7, 0)], RED, 10, dash=(2, 4))
        assert stutter.dots == clean.dots

    def test_a_single_vertex_draws_nothing(self):
        layer = _layer()
        st.stroke_polyline(layer, [(2, 2)], RED, 10)
        st.stroke_polyline(layer, [(2, 2), (2.4, 2.1)], RED, 10)
        assert layer.dots == [[0] * 4]

    def test_crossties_straddle_the_line(self):
        # tick_every=4 on dot row 1: ties at dots 0 and 4, each setting
        # the dot above and below.
        layer = _layer()
        st.stroke_polyline(layer, [(0, 1), (7, 1)], RED, 22, tick_every=4)
        assert layer.dots[0] == [0x17, 0x12, 0x17, 0x12]

    def test_rank_decides_the_ink_whichever_arrives_first(self):
        low_first = _layer()
        st.stroke_polyline(low_first, [(0, 0), (7, 0)], RED, 16)
        st.stroke_polyline(low_first, [(0, 0), (7, 0)], BLUE, 50)
        high_first = _layer()
        st.stroke_polyline(high_first, [(0, 0), (7, 0)], BLUE, 50)
        st.stroke_polyline(high_first, [(0, 0), (7, 0)], RED, 16)
        assert low_first.color[0][0] == BLUE
        assert high_first.color[0][0] == BLUE


class TestClipping:
    def test_an_off_screen_excursion_leaves_the_on_screen_dots_alone(self):
        # The clip window starts 8 dots outside the grid, so a line
        # entering from x=-1004 is clipped at x=-8 — 996 skipped dots,
        # exactly 166 periods of DASH24, so the phase on screen is
        # identical to the pre-clipped line's.
        far = _layer()
        st.stroke_polyline(far, [(-1004, 0), (7, 0)], RED, 10, dash=(2, 4))
        near = _layer()
        st.stroke_polyline(near, [(-8, 0), (7, 0)], RED, 10, dash=(2, 4))
        assert far.dots == near.dots
        assert far.dots[0] != [0] * 4

    def test_a_skipped_span_still_advances_the_dash(self):
        # Same geometry, one period shorter: the phase must move.
        shifted = _layer()
        st.stroke_polyline(shifted, [(-1005, 0), (7, 0)], RED, 10,
                           dash=(2, 4))
        aligned = _layer()
        st.stroke_polyline(aligned, [(-1004, 0), (7, 0)], RED, 10,
                           dash=(2, 4))
        assert shifted.dots != aligned.dots

    def test_a_wholly_off_screen_segment_draws_nothing(self):
        layer = _layer()
        st.stroke_polyline(layer, [(-500, -500), (-400, -400)], RED, 34)
        assert layer.dots == [[0] * 4]

    def test_an_excursion_between_two_visible_points(self):
        # Out of the window and back: the on-screen ends still draw.
        layer = _layer()
        st.stroke_polyline(layer, [(0, 0), (0, -900), (7, 0)], RED, 34)
        assert layer.dots[0][0]
        assert layer.dots[0][3]

    def test_clip_segment_rejects_and_trims(self):
        assert st.clip_segment(-50, -50, -40, -40, -8, -8, 16, 12) is None
        assert st.clip_segment(0, 0, 4, 4, -8, -8, 16, 12) == (0, 0, 4, 4)
        trimmed = st.clip_segment(-100, 5, 4, 5, -8, -8, 16, 12)
        assert trimmed == (-8, 5, 4, 5)

    def test_clip_segment_handles_a_line_parallel_to_an_edge(self):
        # Horizontal, but above the window: parallel and outside.
        assert st.clip_segment(0, -50, 10, -50, -8, -8, 16, 12) is None


class TestStrokeInk:
    def test_a_tunnel_fades_toward_the_ground_and_dashes(self):
        palette = _maps_style.palette()
        plain, plain_dash = st.stroke_ink("minor", {}, palette)
        tunnel, tunnel_dash = st.stroke_ink(
            "minor", {"brunnel": "tunnel"}, palette)
        assert plain == palette["minor"]
        assert plain_dash is None
        assert tunnel_dash == _maps_style.DASH11
        expected = tuple(round(g + (m - g) * _maps_style.TUNNEL_BLEND)
                         for g, m in zip(palette["ground"],
                                         palette["minor"]))
        assert tunnel == expected

    def test_a_bridge_gets_no_special_treatment(self):
        # A casing would have to knock a hole in the layers underneath,
        # which an OR-only dot mask cannot do; the bridge simply wins
        # its cells by rank, which is the correct read anyway.
        palette = _maps_style.palette()
        assert st.stroke_ink("minor", {"brunnel": "bridge"}, palette) \
            == st.stroke_ink("minor", {}, palette)

    def test_a_tunnel_in_a_coarse_palette_keeps_its_ink(self, monkeypatch):
        monkeypatch.setattr(_maps_style, "color_mode", lambda: "16")
        palette = _maps_style.palette()
        color, dash = st.stroke_ink("minor", {"brunnel": "tunnel"}, palette)
        assert color == palette["minor"]      # nothing to fade toward
        assert dash == _maps_style.DASH11


# ---------------------------------------------------------------------------
# Line classes, end to end
# ---------------------------------------------------------------------------
# The equator crosses the world tile at py 2048 and the view's vertical
# middle at dot row 2, so a full-width line lands on 0x04 | 0x20 per cell.
EQUATOR = polyline((0, 2048), (4096, 2048))
FLAT_W1 = [0x24] * 4


class TestLineClasses:
    def test_a_motorway_draws_in_the_accent_ink(self):
        _fills, layer, _labels = build(
            tagged_line("transportation", EQUATOR, {"class": "motorway"}),
            band=1)
        assert layer.dots[0] == FLAT_W1
        assert layer.color[0][0] == ink("motorway")
        assert layer.rank[0][0] == 50

    def test_a_ramp_off_a_motorway_takes_the_ramp_ink(self):
        _fills, layer, _labels = build(
            tagged_line("transportation", EQUATOR,
                        {"class": "motorway", "ramp": 1}),
            band=5)
        assert layer.color[0][0] == ink("ramp")

    def test_tertiary_arrives_as_minor(self):
        _fills, layer, _labels = build(
            tagged_line("transportation", EQUATOR, {"class": "tertiary"}),
            band=5)
        assert layer.color[0][0] == ink("minor")

    def test_a_class_below_its_band_is_not_drawn(self):
        # Secondary's OMT floor is z11, which is why it debuts at B4.
        args = ("transportation", EQUATOR, {"class": "secondary"})
        assert build(tagged_line(*args), band=3)[1].dots[0] == [0] * 4
        assert build(tagged_line(*args), band=4)[1].dots[0] == FLAT_W1

    def test_a_ferry_dashes_in_the_waterway_ink(self):
        _fills, layer, _labels = build(
            tagged_line("transportation", EQUATOR, {"class": "ferry"}),
            band=5)
        assert layer.color[0][0] == ink("waterway")
        assert layer.dots[0] != FLAT_W1          # DASH24, not solid

    def test_a_dropped_class_leaves_no_mark(self):
        for cls in ("pier", "raceway", "aerialway"):
            _fills, layer, _labels = build(
                tagged_line("transportation", EQUATOR, {"class": cls}),
                band=7)
            assert layer.dots[0] == [0] * 4, cls

    def test_a_river_and_a_stream_split_by_weight_of_class(self):
        river = build(tagged_line("waterway", EQUATOR, {"class": "river"}),
                      band=3)[1]
        stream = build(tagged_line("waterway", EQUATOR, {"class": "stream"}),
                       band=3)[1]
        assert river.dots[0] == FLAT_W1          # waterway_major from B3
        assert stream.dots[0] == [0] * 4         # waterway_minor waits

    def test_a_runway_is_a_stroke_not_a_fill(self):
        _fills, layer, _labels = build(
            tagged_line("aeroway", EQUATOR, {"class": "runway"}), band=4)
        assert layer.color[0][0] == ink("aeroway")
        assert layer.dots[0] != [0] * 4

    def test_admin_lines_come_from_the_boundary_layer(self):
        country = build(tagged_line("boundary", EQUATOR,
                                    {"admin_level": 2}), band=1)[1]
        state = build(tagged_line("boundary", EQUATOR,
                                  {"admin_level": 4}), band=1)[1]
        county = build(tagged_line("boundary", EQUATOR,
                                   {"admin_level": 6}), band=1)[1]
        assert country.color[0][0] == ink("border0")
        assert state.color[0][0] == ink("border1")
        assert county.dots[0] == [0] * 4

    def test_a_maritime_boundary_is_dropped(self):
        _fills, layer, _labels = build(
            tagged_line("boundary", EQUATOR,
                        {"admin_level": 2, "maritime": 1}), band=1)
        assert layer.dots[0] == [0] * 4

    def test_a_polygon_in_a_line_layer_is_ignored(self):
        # OMT does carry polygonal transportation (pedestrian squares);
        # the stroke walker must not try to trace them.
        square = classed("transportation", WHOLE, "motorway")
        _fills, layer, _labels = build(square, band=7)
        assert layer.dots[0] == [0] * 4

    def test_a_road_beats_the_coastline_it_crosses(self):
        # A bridge is a real thing and it wins its cells; the coast
        # beats admin borders in turn.
        _fills, layer, _labels = build(
            classed("water", LEFT_HALF, "lake"),
            tagged_line("transportation", EQUATOR, {"class": "motorway"}),
            band=1)
        assert layer.color[0][2] == ink("motorway")
        assert layer.dots[0][2] & 0x47           # the coast dots survive
