"""One camera from the street to the planet.

The street register rasterises through the same orthographic projection
at every zoom now, so a zoom out of a street and on past the old
hand-off changes the scale of the picture and never its projection.
What the footprint still decides is where the ground comes from — the
vector tiles while they can be asked, the baked planet beyond — and
where the flat box rasteriser is still the camera's own picture, which
is what keeps a street-scale view the bytes it has always been.

No network and no fixtures: the tiles are hand-encoded against the
window they are drawn into, the way tests/test_maps_streets.py encodes
its own, so a rasteriser bug cannot be masked by a recording made from
the same code.
"""

import math
import re
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import maps
from linecast._maps import globe as _globe
from linecast._maps import overscan as over
from linecast._maps import streets as st
from linecast._maps import style as _maps_style
from linecast._maps import views as _views
from linecast.radar.basemap import _BITS
from linecast.radar.render import bbox_for
from test_maps_streets import EXTENT, field, layer, line_feature, vstr

# a 160x45 terminal's map: the band a 10 deg view lands on there
# is the shallowest that draws a motorway at all
GW, HC = 160, 43
LAT, LON = 46.8, 8.2


# ---------------------------------------------------------------------------
# A graticule of motorways, encoded into whatever tiles a view reads
# ---------------------------------------------------------------------------
def _tile_xy(lon, lat, z, tx, ty, extent=EXTENT):
    """(lon, lat) -> tile-local coordinates: the projector, inverted."""
    n = 1 << z
    wx = (lon + 180.0) / 360.0
    sin_lat = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    wy = 0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
    return (round((wx * n - tx) * extent), round((wy * n - ty) * extent))


def _varint(out, n):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _zig(n):
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


def _linestring(pts):
    geom = bytearray()
    _varint(geom, (1 << 3) | 1)                 # MoveTo, one point
    _varint(geom, _zig(pts[0][0]))
    _varint(geom, _zig(pts[0][1]))
    _varint(geom, ((len(pts) - 1) << 3) | 2)    # LineTo, the rest
    prev = pts[0]
    for p in pts[1:]:
        _varint(geom, _zig(p[0] - prev[0]))
        _varint(geom, _zig(p[1] - prev[1]))
        prev = p
    return bytes(geom)


def _road_layer(name, groups):
    """One layer of linestrings, each group carrying its own properties.

    A tile is one key table and one value table for the whole layer, so
    the groups share them and each feature points into them.
    """
    keys, values, index = [], [], {}

    def slot(table, item, encode):
        if item not in index.setdefault(id(table), {}):
            index[id(table)][item] = len(table)
            table.append(encode(item))
        return index[id(table)][item]

    feats = []
    for parts, props in groups:
        tags = []
        for k, v in props.items():
            tags.append(slot(keys, k, lambda s: s))
            tags.append(slot(values, v, vstr))
        for pts in parts:
            feats.append(line_feature(_linestring(pts), tags=tuple(tags)))
    return layer(name, feats, keys=keys, values=values)


NAMED = "Grand Parallel"


def _graticule(key, step=1.0):
    """One tile of a 1-degree motorway grid, with one named parallel.

    The grid is drawn in lat/lon, so what the rasteriser does with it is
    exactly what the projection does with it: flat, the parallels are
    rows and the meridians are columns; through the camera the parallels
    bow toward the pole and the meridians lean in.
    """
    z, tx, ty = key
    n = 1 << z
    lon0 = tx / n * 360.0 - 180.0
    lon1 = (tx + 1) / n * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    lat0 = math.degrees(math.atan(math.sinh(math.pi
                                            * (1 - 2 * (ty + 1) / n))))
    lons = [v * step for v in range(int(lon0 // step) - 1,
                                    int(lon1 // step) + 2)]
    lats = [v * step for v in range(int(lat0 // step) - 1,
                                    int(lat1 // step) + 2)]
    plain, named = [], []
    for lat in lats:
        pts = [_tile_xy(lon, lat, z, tx, ty) for lon in lons]
        (named if abs(lat - 47.0) < 1e-9 else plain).append(pts)
    for lon in lons:
        plain.append([_tile_xy(lon, lat, z, tx, ty) for lat in lats])
    groups = [(plain, {"class": "motorway"})]
    if named:
        groups.append((named, {"class": "motorway", "name": NAMED}))
    layers = [_road_layer("transportation", groups)]
    if named:
        layers.append(_road_layer("transportation_name",
                                  [(named, {"class": "motorway",
                                            "name": NAMED})]))
    return b"".join(field(3, 2, lyr) for lyr in layers)


def _built(bbox, gw, hc, window=None):
    """The street view a loader would build for this bbox, tiles and all."""
    cam = _globe.Camera.for_bbox(bbox, gw, hc)
    camera = None if _globe.affine_ok(cam.lat, cam.zoom, gw, hc) else cam
    band, _z_src, keys = st.view_tiles(
        bbox, hc, window, None if camera is None else camera.bounds)
    tiles = {k: _graticule(k) for k in keys}
    return st.build_street_view(bbox, gw, hc, tiles, band, "en", (), None,
                                camera)


def _lit(dots):
    return {(cx * 2 + sx, cy * 4 + sy)
            for cy, row in enumerate(dots)
            for cx, v in enumerate(row) if v
            for sx in (0, 1) for sy in range(4) if v & _BITS[sx][sy]}


def _near(dots, real, reach=1):
    """The share of `dots` within `reach` dots of one of `real`'s."""
    close = {(x + dx, y + dy) for x, y in _lit(real)
             for dx in range(-reach, reach + 1)
             for dy in range(-reach, reach + 1)}
    mine = _lit(dots)
    assert mine
    return sum(1 for d in mine if d in close) / len(mine)


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------
class TestTheBuildFollowsTheCamera:
    def test_the_loader_passes_the_camera_only_past_the_bound(
            self, monkeypatch):
        seen = []

        def build(bbox, gw, hc, tiles, band, lang="en", reserved=(),
                  builtup=None, camera=None, window=None):
            seen.append(camera)
            return None, None, None

        monkeypatch.setattr(st, "build_street_view", build)
        monkeypatch.setattr(st, "fetch_tiles",
                            lambda keys: {k: b"" for k in keys} or {"x": b"x"})
        monkeypatch.setattr(st, "view_tiles",
                            lambda *a, **k: (7, 14, [(14, 0, 0)]))
        monkeypatch.setattr(st, "fetch_tiles", lambda keys: {(14, 0, 0): b"x"})
        for zoom in (0.002, 10.0):
            _views._street_cache.clear()
            _views._get_street_tiles(bbox_for(LAT, LON, zoom, GW, HC),
                                     GW, HC, True)
        assert seen[0] is None
        assert isinstance(seen[1], _globe.Camera)
        assert seen[1].zoom == pytest.approx(10.0)

    def test_the_tiles_follow_the_cameras_own_footprint(self, monkeypatch):
        asked = []

        def view_tiles(bbox, hc, window=None, coverage=None):
            asked.append(coverage)
            return 7, 14, [(14, 0, 0)]

        monkeypatch.setattr(st, "view_tiles", view_tiles)
        monkeypatch.setattr(st, "fetch_tiles", lambda keys: {(14, 0, 0): b"x"})
        monkeypatch.setattr(st, "build_street_view",
                            lambda *a, **k: (None, None, None))
        for zoom in (0.002, 10.0):
            _views._street_cache.clear()
            _views._get_street_tiles(bbox_for(LAT, LON, zoom, GW, HC),
                                     GW, HC, True)
        assert asked[0] is None
        # the window's bbox is a scale past the bound, not a footprint:
        # the camera's own bounds are what has to be covered
        cam = _globe.Camera.for_bbox(bbox_for(LAT, LON, 10.0, GW, HC),
                                     GW, HC)
        assert asked[1] == cam.footprint

    def test_every_stroke_lands_where_the_camera_puts_it(self):
        # a parallel is a row on the box and a bow on the sphere, and
        # the whole road net moves with it
        bbox = bbox_for(LAT, LON, 10.0, GW, HC)
        cam = _globe.Camera.for_bbox(bbox, GW, HC)
        assert not _globe.affine_ok(cam.lat, cam.zoom, GW, HC)
        band, _z, keys = st.view_tiles(bbox, HC, None, cam.bounds)
        tiles = {k: _graticule(k) for k in keys}
        flat = st.build_street_view(bbox, GW, HC, tiles, band)[1]
        turned = st.build_street_view(bbox, GW, HC, tiles, band, "en", (),
                                      None, cam)[1]
        assert flat.dots != turned.dots
        # the camera's own placement of a point on the 47th parallel
        # well west of the centre meridian, where the bow is dots
        # rather than a rounding
        x, y = cam.project(1.0, 47.0, GW * 2, HC * 4)
        assert turned.dots[int(y) // 4][int(x) // 2]
        # the box put that same point rows away, and drew no dot there
        fy = (bbox[3] - 47.0) / (bbox[3] - bbox[1]) * HC * 4
        assert abs(int(fy) - int(y)) >= 4       # a whole cell row
        assert not turned.dots[int(fy) // 4][int(x) // 2]
        assert flat.dots[int(fy) // 4][int(x) // 2]

    def test_the_fills_and_the_labels_move_with_the_strokes(self):
        # one build, and everything in it on one geometry: the label
        # anchors are the camera's cells, not the box's
        bbox = bbox_for(LAT, LON, 10.0, GW, HC)
        cam = _globe.Camera.for_bbox(bbox, GW, HC)
        band, _z, keys = st.view_tiles(bbox, HC, None, cam.bounds)
        tiles = {k: _graticule(k) for k in keys}
        overlays = st.build_street_view(bbox, GW, HC, tiles, band, "en", (),
                                        None, cam)[2]
        marks = [cell for cell, entry in overlays.items()
                 if entry[0] in (_maps_style.GLYPH_GENERIC,
                                 _maps_style.GLYPH_CAPITAL)]
        assert marks
        here = {cam.screen_cell(e[0], e[1])
                for e in _globe._load_data()["cities"]}
        assert all(cell in here for cell in marks)
        # A settlement below GAZETTEER_BAND comes from the world
        # gazetteer, and only a camera can say which of a world list is
        # on the screen — so these marks are the camera's cells whether
        # or not one was passed in, and that is the point: they are the
        # cells the planet puts them in on the far side of the
        # hand-off.  What the camera moves here is the tile's own work.
        flat = st.build_street_view(bbox, GW, HC, tiles, band)[2]
        flat_marks = [cell for cell, entry in flat.items()
                      if entry[0] in (_maps_style.GLYPH_GENERIC,
                                      _maps_style.GLYPH_CAPITAL)]
        assert sorted(flat_marks) == sorted(marks)


class TestHoverFollowsTheProjection:
    def test_the_index_names_the_road_at_the_cameras_own_cells(self):
        # the index is a map of the cells the raster drew, so it
        # follows the camera for free — and the box rasteriser's index
        # answers about the ground the camera never put there
        bbox = bbox_for(LAT, LON, 10.0, GW, HC)
        cam = _globe.Camera.for_bbox(bbox, GW, HC)
        assert not _globe.affine_ok(cam.lat, cam.zoom, GW, HC)
        band, _z, keys = st.view_tiles(bbox, HC, None, cam.bounds)
        tiles = {k: _graticule(k) for k in keys}
        turned = st.build_street_view(bbox, GW, HC, tiles, band, "en", (),
                                      None, cam)[1]
        flat = st.build_street_view(bbox, GW, HC, tiles, band)[1]
        # a point on the named parallel, well off the centre meridian
        col, row = cam.screen_cell(1.0, 47.0)
        hit = turned.hover.at(col, row)
        assert hit is not None and hit.name == NAMED
        # the flat index has that road rows away, and says so
        miss = flat.hover.at(col, row)
        assert miss is None or miss.name != NAMED


# ---------------------------------------------------------------------------
# The far end
# ---------------------------------------------------------------------------
class TestTheLoaderPicksItsSource:
    def test_tiles_inside_and_the_planet_beyond(self, monkeypatch):
        seen = []
        monkeypatch.setattr(maps, "_get_street_tiles",
                            lambda *a, **k: seen.append("tiles"))
        monkeypatch.setattr(maps, "_get_globe",
                            lambda *a, **k: seen.append("planet"))
        maps._get_street(bbox_for(LAT, LON, 2.0, GW, HC), GW, HC, True)
        maps._get_street(bbox_for(LAT, LON, 60.0, GW, HC), GW, HC, True)
        assert seen == ["tiles", "planet"]

    def test_the_margin_is_drawn_from_the_windows_own_source(
            self, monkeypatch):
        # the last degrees before the hand-off: the window is on the
        # tiles and its overscan, a quarter again as wide, would be sent
        # to the planet.  The window decides, for street as for terrain
        seen = []
        monkeypatch.setattr(maps, "_get_street_tiles",
                            lambda *a, **k: seen.append("tiles"))
        monkeypatch.setattr(maps, "_get_globe",
                            lambda *a, **k: seen.append("planet"))
        zoom = 30.0
        assert _globe.local_tiles(LAT, zoom, GW, HC)
        frame, _at = over.plan(bbox_for(LAT, LON, zoom, GW, HC), GW, HC)
        assert not _globe.Camera.for_bbox(frame.bbox, frame.gw,
                                          frame.hc).local_tiles
        maps._get_street(frame.bbox, frame.gw, frame.hc, True, "en", (),
                         over.window_hint(frame, GW, HC))
        assert seen == ["tiles"]

    def test_the_planet_keeps_the_street_map_s_look(self, monkeypatch):
        # two quiet fills, the coast in the street map's ink, the
        # gazetteer's names, and no borders
        gw, hc = 40, 12
        spy = hc * 2
        view = _globe.GlobeView(
            [[500.0] * gw for _ in range(spy)],
            [[0xFF] * gw for _ in range(hc)],
            [[1.0] * gw for _ in range(spy)],
            [[0.0] * gw for _ in range(spy)],
            None,
            maps.DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc))
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: view)
        _views._terrain_cache.clear()
        fills, layer_, labels = maps._get_street(
            bbox_for(20.0, -30.0, 125.0, gw, hc), gw, hc, True)
        palette = _maps_style.palette()
        assert {c for row in fills for c in row} <= {
            palette.get("water"), palette.get("ground"), maps.BG_PRIMARY}
        assert layer_.dots == view.coast
        assert layer_.color[0][0] == palette.get("coast")
        assert not layer_.ribbon            # no motorway ribbon out here
        assert labels                       # the vendored gazetteer's


# ---------------------------------------------------------------------------
# Continuity
# ---------------------------------------------------------------------------
class TestOneGeometryAcrossTheHandOff:
    def test_the_source_does_not_change_at_forty_five(self):
        # 44.9 and 45.1 sit either side of the old cut; the register
        # crosses nothing there now — the source changed at
        # `local_tiles` well before it, and the projection not at all
        for zoom in (44.9, 45.1):
            assert maps.wide_source(LAT, zoom, GW, HC)
        assert (maps.wide_source(LAT, 44.9, GW, HC)
                == maps.wide_source(LAT, 45.1, GW, HC))

    def test_a_zoom_about_the_centre_is_a_uniform_scaling(self):
        a = _globe.Camera(LAT, LON, 44.9, GW, HC)
        b = _globe.Camera(LAT, LON, 45.1, GW, HC)
        ratio = 44.9 / 45.1
        dw, dh = GW * 2, HC * 4
        for plat, plon in ((50.0, 12.0), (30.0, -4.0), (46.8, 8.2)):
            ax, ay = a.project(plon, plat, dw, dh)
            bx, by = b.project(plon, plat, dw, dh)
            assert ax - dw / 2 == pytest.approx((bx - dw / 2) / ratio,
                                                abs=1e-9)
            assert ay - dh / 2 == pytest.approx((by - dh / 2) / ratio,
                                                abs=1e-9)


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _braille(frame):
    body = "\n".join(ANSI.sub("", frame).split("\n")[1:-1])
    return sum(1 for ch in body if 0x2800 <= ord(ch) <= 0x28FF)


class TestTheTransitionIsInked:
    """Eleven taps out from a street and eleven back, every frame inked.

    A street zoom used to cross the hand-off in one cut, because
    neither side could stand in for the other.  It eases through now,
    so the frames between the tap and the data are a scaling of the
    picture that was there — and none of them may be blank.
    """

    COLS, ROWS = 60, 20

    def _ladder(self):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        out, zoom = [], 0.05
        for _ in range(11):
            out.append(zoom)
            zoom = min(maps.max_zoom(gw, hc), zoom * _maps_style.ZOOM_STEP
                       ** 2)
        return out

    def test_every_frame_of_the_run_has_ink(self, monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))

        def tiles(bbox, ogw, ohc, block, lang="en", reserved=(),
                  window=None):
            ink = (200, 80, 40)
            return ([[ink] * ogw for _ in range(ohc * 2)],
                    maps._ShiftedLayer(
                        [[0xFF] * ogw for _ in range(ohc)],
                        [[ink] * ogw for _ in range(ohc)]),
                    {})

        def planet(lat0, lon0, zoom, ogw, ohc, block, street=False):
            return _globe.GlobeView(
                [[500.0] * ogw for _ in range(ohc * 2)],
                [[0xFF] * ogw for _ in range(ohc)],
                [[1.0] * ogw for _ in range(ohc * 2)],
                [[0.0] * ogw for _ in range(ohc * 2)], None, None)

        monkeypatch.setattr(maps, "_get_street_tiles", tiles)
        monkeypatch.setattr(maps, "_get_globe", planet)
        maps._last_street[0] = None
        ladder = self._ladder()
        for zoom in ladder + ladder[::-1]:
            frame = maps.render_map(LAT, LON, "Alps", zoom, block=False,
                                    view="street")
            assert _braille(frame), f"blank frame at {zoom} deg"
        maps._last_street[0] = None

    def test_every_frame_still_has_ink_while_the_loaders_miss(
            self, monkeypatch):
        # the same run with nothing landing: every frame is a stand-in,
        # and a stand-in that goes blank is the cut this stage removed
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        ink = (200, 80, 40)
        ladder = self._ladder()
        maps._last_street[0] = (
            bbox_for(LAT, LON, ladder[-1], gw, hc), gw, hc,
            [[ink] * gw for _ in range(hc * 2)],
            maps._ShiftedLayer([[0xFF] * gw for _ in range(hc)],
                               [[ink] * gw for _ in range(hc)]),
            {})
        monkeypatch.setattr(maps, "_get_street_tiles",
                            lambda *a, **k: (None, None, None))
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: None)
        for zoom in ladder[-2::-1]:
            frame = maps.render_map(LAT, LON, "Alps", zoom, block=False,
                                    view="street")
            assert _braille(frame), f"blank frame at {zoom} deg"
        maps._last_street[0] = None


# ---------------------------------------------------------------------------
# The resting crop
# ---------------------------------------------------------------------------
class TestTheRestingCropIsTheWindow:
    """A pan inside the margin, once it comes to rest.

    Street's crop was a slice at any offset, because its ground was
    rasterised onto a box linear in longitude and latitude.  Under one
    camera a slice taken off the built view's centre is the right
    ground in the wrong place — the built view has turned with the
    meridians — so at rest the window's own samples are fetched out of
    it instead.
    """

    ZOOM, DCOL = 10.0, 7

    def _pan(self):
        """(the built overscan's view and frame, the window, its view)."""
        bbox = bbox_for(LAT, LON, self.ZOOM, GW, HC)
        frame, at = over.plan(bbox, GW, HC)
        colw, _rowh = frame.cell
        window = (bbox[0] + self.DCOL * colw, bbox[1],
                  bbox[2] + self.DCOL * colw, bbox[3])
        built = _built(frame.bbox, frame.gw, frame.hc,
                       over.window_hint(frame, GW, HC))
        real = _built(window, GW, HC)
        return built, frame, (at[0] + self.DCOL, at[1]), window, real

    def test_the_resting_roads_land_on_the_real_ones(self):
        built, frame, (dx, dy), window, real = self._pan()
        assert over.locate(frame, window, GW, HC,
                           cap=_globe.cap(self.ZOOM, GW, HC)) == (dx, dy)
        cut = over.Resample(frame, window, GW, HC)
        exact = cut.layer(built[1])
        sliced = over.crop_layer(built[1], dx, dy, GW, HC)
        # every dot of the resampled road net is on the real one or
        # next to it; the slice is not
        assert _near(exact.dots, real[1].dots) > 0.99
        assert _near(sliced.dots, real[1].dots) < 0.95
        on = _near(exact.dots, real[1].dots, 0)
        slid = _near(sliced.dots, real[1].dots, 0)
        assert on > 0.6 and on > 1.5 * slid

    def test_every_resampled_road_cell_keeps_its_own_ink(self):
        # the ink follows the dots, not the ground under the middle of
        # the cell: a road inked from the empty cell beside it is a
        # road the composer draws in no colour at all
        built, frame, _at, window, _real = self._pan()
        exact = over.Resample(frame, window, GW, HC).layer(built[1])
        lit = [(cx, cy) for cy, row in enumerate(exact.dots)
               for cx, v in enumerate(row) if v]
        assert lit
        assert all(exact.color[cy][cx] is not None for cx, cy in lit)

    def test_a_window_at_the_built_views_centre_is_a_slice(self):
        bbox = bbox_for(LAT, LON, self.ZOOM, GW, HC)
        frame, at = over.plan(bbox, GW, HC)
        assert maps._exact_crop(frame, bbox, GW, HC, at, False) is None
        # and so is a street-scale window, where a crop of the box is
        # the window's own picture
        close = bbox_for(LAT, LON, 0.002, GW, HC)
        cframe, cat = over.plan(close, GW, HC)
        colw, _rowh = cframe.cell
        moved = (close[0] + 6 * colw, close[1], close[2] + 6 * colw,
                 close[3])
        assert maps._exact_crop(cframe, moved, GW, HC,
                                (cat[0] + 6, cat[1]), False) is None

    def test_a_frame_in_motion_still_slices(self):
        bbox = bbox_for(LAT, LON, self.ZOOM, GW, HC)
        frame, at = over.plan(bbox, GW, HC)
        colw, _rowh = frame.cell
        window = (bbox[0] + self.DCOL * colw, bbox[1],
                  bbox[2] + self.DCOL * colw, bbox[3])
        moved = (at[0] + self.DCOL, at[1])
        assert maps._exact_crop(frame, window, GW, HC, moved, True) is None
        assert maps._exact_crop(frame, window, GW, HC, moved,
                                False) is not None

    def test_a_hover_hit_after_a_resample_names_the_right_road(self):
        built, frame, (dx, dy), window, real = self._pan()
        cut = over.Resample(frame, window, GW, HC)
        labels, moved = cut.overlays(built[2])
        hover = over.ResampledHover(built[1].hover, cut, moved,
                                    cut.ink_source(built[1].dots),
                                    cut.layer(built[1]).dots)
        # every cell of the window the named road is drawn in, by the
        # window's own build, answers with that road
        want = {cell for cell in _road_cells(real[1], real[1].hover)}
        assert want
        named = 0
        for col, row in sorted(want):
            hit = hover.at(col, row)
            if hit is not None and hit.name == NAMED:
                named += 1
        assert named > 0.9 * len(want)
        # and the sliced index, read through the offset, names it in
        # the wrong place
        sliced = over.CroppedHover(built[1].hover, dx, dy, GW, HC, labels)
        off = sum(1 for col, row in sorted(want)
                  if (sliced.at(col, row) is not None
                      and sliced.at(col, row).name == NAMED))
        assert off < named


def _road_cells(layer_, index):
    """The cells a named road owns the ink of, in a built view."""
    out = []
    for row, line in enumerate(index.owner):
        for col, idx in enumerate(line):
            if idx is not None and index.feats[idx][1] == NAMED:
                out.append((col, row))
    return out


# ---------------------------------------------------------------------------
# Found in review
# ---------------------------------------------------------------------------
class TestAPanThenAZoomOutStaysInked:
    """A pan inside the margin and then a zoom out past the tiles.

    The overscan is centred where the window was built, and the window
    has since moved a few columns off it; the planet is not there yet.
    The stand-in used to refuse any moved centre, which is the right
    rule for a disk with the limb in it and a blank frame for a patch
    of the sphere that has none.
    """

    COLS, ROWS = 160, 45

    @pytest.mark.parametrize("view", ["street", "terrain"])
    def test_the_frames_before_the_planet_lands_have_ink(self, view,
                                                         monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        zoom = 30.0
        assert _globe.local_tiles(LAT, zoom, gw, hc)
        assert not _globe.local_tiles(LAT, zoom * 1.5, gw, hc)
        bbox = bbox_for(LAT, LON, zoom, gw, hc)
        frame, _at = over.plan(bbox, gw, hc)
        assert maps._margin_is_local(frame)
        ink = (200, 80, 40)
        fills = [[ink] * frame.gw for _ in range(frame.hc * 2)]
        dots = [[0xFF] * frame.gw for _ in range(frame.hc)]
        layer_ = maps._ShiftedLayer(dots, [[ink] * frame.gw
                                           for _ in range(frame.hc)])
        if view == "street":
            maps._last_street[0] = (tuple(frame.bbox), frame.gw, frame.hc,
                                    fills, layer_, {})
        else:
            maps._last_terrain[0] = (tuple(frame.bbox), frame.gw, frame.hc,
                                     fills, dots, layer_, None, None, None)
        monkeypatch.setattr(maps, "_get_street_tiles",
                            lambda *a, **k: (None, None, None))
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: None)
        colw, _rowh = frame.cell
        try:
            for dcol in (0, 1, 5):
                lon = LON + dcol * colw
                crop = maps.render_map(LAT, lon, "Alps", zoom, block=False,
                                       view=view)
                assert _braille(crop), f"blank crop {dcol} columns over"
                out = maps.render_map(LAT, lon, "Alps", zoom * 1.5,
                                      block=False, view=view)
                assert _braille(out), f"blank zoom-out {dcol} columns over"
        finally:
            maps._last_street[0] = maps._last_terrain[0] = None

    def test_a_disk_with_the_limb_in_it_still_refuses_a_moved_centre(self):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        assert not maps._limb_in((bbox_for(LAT, LON, 30.0, gw, hc), gw, hc))
        assert maps._limb_in((bbox_for(LAT, LON, 130.0, gw, hc), gw, hc))
        fills = [[(1, 2, 3)] * gw for _ in range(hc * 2)]
        layer_ = maps._ShiftedLayer([[0xFF] * gw for _ in range(hc)],
                                    [[(1, 2, 3)] * gw for _ in range(hc)])
        prev = (bbox_for(LAT, LON, 130.0, gw, hc), gw, hc, fills, layer_, {})
        moved = bbox_for(LAT, LON + 20.0, 90.0, gw, hc)
        assert maps._street_stand_in(prev, moved, gw, hc, True, "g") is None
        same = bbox_for(LAT, LON, 90.0, gw, hc)
        assert maps._street_stand_in(prev, same, gw, hc, True, "g")


class TestTheMarginGoesAheadWhileTheSliceIsExact:
    """The default street view on a wide terminal fails the affine bound
    and still gets its margin ahead of the motion: a window at the far
    side of that margin is a sixteenth of a dot out of register, and
    the slice is the picture.  Ten degrees up it is seven dots out, and
    the margin sits evenly about the window instead."""

    COLS, ROWS = 160, 45

    def _frame(self, zoom, monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))
        seen = []

        def tiles(bbox, ogw, ohc, block, lang="en", reserved=(),
                  window=None):
            seen.append((tuple(bbox), ogw, ohc))
            return None, None, None

        monkeypatch.setattr(maps, "_get_street_tiles", tiles)
        maps._last_street[0] = None
        maps.render_map(40.7128, -74.006, "New York", zoom, block=False,
                        view="street", motion=(1, 0))
        maps._last_street[0] = None
        return seen[0]

    def test_the_default_view_is_built_ahead(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        zoom = 0.05
        assert not _globe.affine_ok(40.7128, zoom, gw, hc)
        bbox = bbox_for(40.7128, -74.006, zoom, gw, hc)
        ahead = over.plan(bbox, gw, hc, (1, 0))[0]
        even = over.plan(bbox, gw, hc)[0]
        assert ahead.bbox != even.bbox
        assert self._frame(zoom, monkeypatch)[0] == pytest.approx(ahead.bbox)

    def test_ten_degrees_up_it_is_built_evenly(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        zoom = 10.0
        bbox = bbox_for(40.7128, -74.006, zoom, gw, hc)
        even = over.plan(bbox, gw, hc)[0]
        assert self._frame(zoom, monkeypatch)[0] == pytest.approx(even.bbox)


class TestTheVectorTilesFollowTheFootprint:
    def test_the_footprint_is_the_bounds_without_the_pad(self):
        cam = _globe.Camera(LAT, LON, 10.0, GW, HC)
        fp, b = cam.footprint, cam.bounds
        assert b[0] < fp[0] < fp[2] < b[2] and b[1] < fp[1] < fp[3] < b[3]
        # the pad is one cell of the window on each side
        assert b[3] - fp[3] == pytest.approx(10.0 / HC)
        assert b[1] - fp[1] == pytest.approx(-10.0 / HC)

    def test_the_default_street_overscan_asks_eight_tiles_not_twelve(
            self, monkeypatch):
        # the case the pad cost most: the default street view's overscan
        # on a 160x45 terminal at New York reached a tile ring further
        asked = []

        def view_tiles(bbox, hc, window=None, coverage=None):
            asked.append(coverage)
            return 7, 13, [(13, 0, 0)]

        monkeypatch.setattr(st, "view_tiles", view_tiles)
        monkeypatch.setattr(st, "fetch_tiles", lambda keys: {(13, 0, 0): b"x"})
        monkeypatch.setattr(st, "build_street_view",
                            lambda *a, **k: (None, None, None))
        bbox = bbox_for(40.7128, -74.006, 0.05, GW, HC)
        frame, _at = over.plan(bbox, GW, HC)
        cam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        assert not _globe.affine_ok(cam.lat, cam.zoom, frame.gw, frame.hc)
        _views._street_cache.clear()
        _views._get_street_tiles(frame.bbox, frame.gw, frame.hc, True, "en",
                                 (), over.window_hint(frame, GW, HC))
        assert asked == [cam.footprint]
        from linecast._vtiles import tiles_for_bbox
        assert len(tiles_for_bbox(cam.footprint, 13)) == 8
        assert len(tiles_for_bbox(cam.bounds, 13)) == 12


class TestTheResampledWritingIsWhereItIsRead:
    """The hover through a resample answers a mark by the window cell
    its letters are in now, and lights a road's letters where they
    were written — not where each letter's ground would land on its
    own, which for a long name is a cell or two off."""

    ZOOM, DCOL = 10.0, 7

    def _cut(self):
        bbox = bbox_for(LAT, LON, self.ZOOM, GW, HC)
        frame, at = over.plan(bbox, GW, HC)
        colw, _rowh = frame.cell
        window = (bbox[0] + self.DCOL * colw, bbox[1],
                  bbox[2] + self.DCOL * colw, bbox[3])
        built = _built(frame.bbox, frame.gw, frame.hc,
                       over.window_hint(frame, GW, HC))
        return built, over.Resample(frame, window, GW, HC)

    def test_a_named_roads_lit_letters_are_the_letters_on_the_page(self):
        built, cut = self._cut()
        labels, moved = cut.overlays(built[2])
        layer_ = cut.layer(built[1])
        hover = over.ResampledHover(built[1].hover, cut, moved,
                                    cut.ink_source(built[1].dots),
                                    layer_.dots)
        hits = 0
        for row in range(HC):
            for col in range(GW):
                hit = hover.at(col, row)
                if hit is None or hit.name != NAMED:
                    continue
                hits += 1
                # every lit letter is a letter of that name on the page
                for c, r in hit.glyphs:
                    assert labels[(c, r)][0] in NAMED
                # and every lit cell is a cell the road is drawn in
                for c, r in hit.cells:
                    assert layer_.dots[r][c]
        assert hits

    def test_two_runs_landing_on_one_cell_keep_the_first_whole(self):
        class Landing(over.Resample):
            __slots__ = ()

            def relocate(self, col, row):
                return (20, 7)

        bbox = bbox_for(LAT, LON, self.ZOOM, GW, HC)
        frame, _at = over.plan(bbox, GW, HC)
        cut = Landing(frame, bbox, GW, HC)
        labels = {(10, 5): ("A", "ink", False), (11, 5): ("b", "ink", False),
                  (40, 9): ("C", "ink", False), (41, 9): ("d", "ink", False)}
        kept, moved = cut.overlays(labels)
        assert kept == {(20, 7): ("A", "ink", False),
                        (21, 7): ("b", "ink", False)}
        assert moved == {(10, 5): (20, 7), (11, 5): (21, 7)}
