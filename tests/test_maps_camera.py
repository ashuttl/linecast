"""One camera from the valley to the planet.

The terrain register inverts the same orthographic projection at every
zoom now, so a zoom out of a valley and on past the hand-off changes
the scale of the picture and never its projection.  What the footprint
still decides is where the ground comes from — the Mercator sources
while they can be asked, the baked planet beyond — and where the flat
box rasteriser is still the camera's own picture, which is what keeps a
street-scale terrain view the bytes it has always been.
"""

import math
import re
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# every module is bound here rather than inside a test: one test file
# in the suite purges linecast from sys.modules as it loads, and a
# later import would hand back a second copy of a module the objects
# above already closed over
from linecast import _climate
from linecast import _elevation
from linecast import maps
from linecast._maps import globe as _globe
from linecast._maps import overscan as over
from linecast._maps import views as _views
from linecast._maps.route import Route
from linecast._radar import basemap as _basemap
from linecast._radar.basemap import _BITS, _edge_dots
from linecast._radar.render import bbox_for
from linecast._radar.ui import _get_basemap

GW, HC = 160, 45


def _equirect_lls(lat, lon, zoom, gw, h):
    """The flat view's own grid, for the same window."""
    minlon, minlat, maxlon, maxlat = bbox_for(lat, lon, zoom, gw, h // 2)
    return [[(maxlat - (maxlat - minlat) * (y + 0.5) / h,
              minlon + (maxlon - minlon) * (x + 0.5) / gw)
             for x in range(gw)] for y in range(h)]


class TestTheGridWhereTheBoundHolds:
    """Below the bound the camera and the box are the same picture."""

    def test_the_camera_agrees_with_the_flat_grid_within_the_bound(self):
        # the bound is a statement about screen dots, so the comparison
        # is made there: each sample's two (lat, lon) turned back into
        # the offset from the window's centre that the rasteriser would
        # have written
        lat, lon, zoom = 46.8, 8.2, 0.02
        assert _globe.affine_ok(lat, zoom, GW, HC)
        h = HC * 2
        cam = _globe.geometry(lat, lon, zoom, GW, h)[0]
        flat = _equirect_lls(lat, lon, zoom, GW, h)
        r = _globe._radius(zoom, h)
        rx = r * _globe._aspect()
        worst = 0.0
        for c_row, f_row in zip(cam, flat):
            for c, f in zip(c_row, f_row):
                dlat = math.radians(c[0] - f[0])
                dlon = math.radians(c[1] - f[1])
                worst = max(worst, math.hypot(
                    dlon * rx * math.cos(math.radians(lat)), dlat * r))
        # the grid is sub-pixels, the bound braille dots: two dots to a
        # sub-pixel down the screen
        assert worst * 2 <= _globe.AFFINE_DOTS

    def test_the_bound_passes_close_in_and_fails_wide(self):
        # the term that bites carries sin(lat) cos(lat), so the equator
        # keeps the flat grid for degrees and the middle latitudes lose
        # it inside a tenth of one
        assert _globe.affine_ok(0.0, 1.0, GW, HC)
        assert not _globe.affine_ok(0.0, 4.0, GW, HC)
        assert _globe.affine_ok(46.8, 0.02, GW, HC)
        assert not _globe.affine_ok(46.8, 0.1, GW, HC)
        assert _globe.affine_ok(80.0, 0.002, GW, HC)
        assert not _globe.affine_ok(80.0, 0.02, GW, HC)
        # and it is the window's own shape, not only its zoom
        assert _globe.affine_ok(46.8, 0.05, 80, 24)
        assert not _globe.affine_ok(46.8, 0.05, GW, HC)

    @pytest.mark.parametrize("lat", [0.0, 46.8, 80.0])
    @pytest.mark.parametrize("size", [(GW, HC), (80, 24)])
    def test_the_bound_is_what_the_two_maps_actually_differ_by(self, lat,
                                                               size):
        gw, hc = size
        zoom = 2.0
        h = hc * 2
        cam = _globe.geometry(lat, 0.0, zoom, gw, h)[0]
        flat = _equirect_lls(lat, 0.0, zoom, gw, h)
        r = _globe._radius(zoom, h)
        rx = r * _globe._aspect()
        worst = 0.0
        for c_row, f_row in zip(cam, flat):
            for c, f in zip(c_row, f_row):
                worst = max(worst, math.hypot(
                    math.radians(c[1] - f[1]) * rx * math.cos(
                        math.radians(lat)),
                    math.radians(c[0] - f[0]) * r))
        measured = worst * 2          # sub-pixels to dots
        claimed = _globe.affine_error(lat, zoom, gw, hc)
        # the lattice is coarse on purpose; it must not be optimistic by
        # more than a little, and never by an order
        assert 0.5 * claimed <= measured <= 1.05 * claimed + 1e-9


class TestBounds:
    """The source bbox holds every sample the window has."""

    @pytest.mark.parametrize("zoom", [0.05, 2.0, 20.0, 60.0, 130.0])
    @pytest.mark.parametrize("lat", [0.0, 60.0, 80.0])
    @pytest.mark.parametrize("lon", [8.2, 179.6, -179.6])
    def test_every_sample_falls_inside(self, zoom, lat, lon):
        gw, hc = 80, 24
        box = _globe.bounds(lat, lon, zoom, gw, hc)
        lls = _globe.geometry(lat, lon, zoom, gw * 2, hc * 4)[0]
        for row in lls:
            for ll in row:
                if ll is None:
                    continue
                # longitude is unwrapped about the centre, as the
                # stitchers take it
                dlon = (ll[1] - lon + 180.0) % 360.0 - 180.0
                assert box[1] - 1e-9 <= ll[0] <= box[3] + 1e-9
                assert (box[0] - lon - 1e-9 <= dlon
                        <= box[2] - lon + 1e-9)

    def test_a_close_window_is_not_given_the_whole_cap(self):
        # the enclosing cap of a 160x45 window is twice as tall as the
        # window; walking the border instead is what keeps a close
        # terrain view on the tiles it always fetched
        lat, lon, zoom = 46.8, 8.2, 2.0
        box = _globe.bounds(lat, lon, zoom, GW, HC)
        scale = _globe.scale_bbox(lat, lon, zoom, GW, HC)
        assert (box[3] - box[1]) < 1.25 * (scale[3] - scale[1])
        assert (box[2] - box[0]) < 1.25 * (scale[2] - scale[0])

    def test_a_pole_in_the_window_takes_every_longitude(self):
        box = _globe.bounds(89.0, 0.0, 40.0, GW, HC)
        assert box[0] <= -180.0 and box[2] >= 180.0
        assert box[3] == 90.0

    def test_the_scale_bbox_is_the_flat_window(self):
        for lat in (0.0, 46.8, -60.0):
            assert (_globe.scale_bbox(lat, 8.2, 2.0, GW, HC)
                    == bbox_for(lat, 8.2, 2.0, GW, HC))


class TestLocalTiles:
    def test_it_flips_where_the_footprint_says(self):
        # the tile sources serve wherever the flat view did, and the
        # flat view's own hand-off widens with 1/cos(lat)
        assert _globe.local_tiles(0.0, 44.0, GW, HC)
        assert not _globe.local_tiles(0.0, 46.0, GW, HC)
        assert _globe.local_tiles(46.8, 30.0, GW, HC)
        assert not _globe.local_tiles(46.8, 32.0, GW, HC)
        # a window reaching past the Mercator edge is the planet's
        assert not _globe.local_tiles(80.0, 20.0, GW, HC)
        # and a dot spanning more than the vector source's own detail
        # is refused whatever the zoom says: eight rows of map
        assert not _globe.local_tiles(0.0, 40.0, 40, 8)
        assert _globe.local_tiles(0.0, 40.0, 160, 45)

    def test_the_register_predicate_follows_it(self):
        assert not maps.wide_source("terrain", 0.0, 44.0, GW, HC)
        assert maps.wide_source("terrain", 0.0, 46.0, GW, HC)
        # street still crosses the projection at ZOOM_DEG
        assert not maps.wide_source("street", 0.0, 40.0, 40, 8)


class TestOneGeometryAcrossTheHandOff:
    def test_a_zoom_about_the_centre_is_a_uniform_scaling(self):
        # 44.9 and 45.1 are either side of the old hand-off; under one
        # camera the same ground lands at the same place, scaled
        lat, lon = 46.8, 8.2
        a = _globe.Camera(lat, lon, 44.9, GW, HC)
        b = _globe.Camera(lat, lon, 45.1, GW, HC)
        ratio = 44.9 / 45.1
        dw, dh = GW * 2, HC * 4
        for plat, plon in ((50.0, 12.0), (30.0, -4.0), (60.0, 40.0),
                           (46.8, 8.2)):
            ax, ay = a.project(plon, plat, dw, dh)
            bx, by = b.project(plon, plat, dw, dh)
            assert ax - dw / 2 == pytest.approx(
                (bx - dw / 2) / ratio, abs=1e-9)
            assert ay - dh / 2 == pytest.approx(
                (by - dh / 2) / ratio, abs=1e-9)

    def test_both_sides_are_drawn_by_the_one_renderer(self, monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("terrain must not reach the globe renderer")

        monkeypatch.setattr(maps, "_render_globe", refuse)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (60, 20))
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: None)
        maps._last_terrain[0] = None
        for zoom in (44.9, 45.1):
            assert maps.render_map(46.8, 8.2, "Alps", zoom, block=False,
                                   view="terrain")
        maps._last_terrain[0] = None

    def test_the_crop_out_of_an_overscan_is_the_window_exactly(self):
        # the terrain margin sits evenly on every side, so the wider
        # grid samples the very same plane points — the crop is not
        # close to the window's geometry, it is the window's geometry
        lat, lon, zoom = 46.8, 8.2, 2.0
        gw, hc = 40, 12
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        frame, at = over.plan(bbox, gw, hc)
        pw, ph = over.padding(gw, hc)
        assert at == (pw, ph)
        fcam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        wide = _globe.geometry(fcam.lat, fcam.lon, fcam.zoom,
                               frame.gw, frame.hc * 2)[0]
        window = _globe.geometry(lat, lon, zoom, gw, hc * 2)[0]
        crop = over.crop_grid(wide, pw, ph * 2, gw, hc * 2)
        for a_row, b_row in zip(crop, window):
            for a, b in zip(a_row, b_row):
                assert a[0] == pytest.approx(b[0], abs=1e-11)
                assert a[1] == pytest.approx(b[1], abs=1e-11)

    def test_the_turn_is_what_a_slice_is_out_by(self):
        # two orthographic views at different centres are not a
        # translation of one another: move the centre east and the
        # picture turns with the meridians, by the offset times the
        # sine of the latitude.  That term carries the error, and it
        # is what crop_dots has to say
        gw, hc = 160, 43
        zoom, dcol = 10.0, 9
        cap = _globe.cap(zoom, gw, hc)
        # the turn, worked out from the window's own geometry: a column
        # in radians of longitude, times sin(lat), across the corner
        colw = math.radians(zoom) / (2 * hc * _globe._aspect()
                                     * math.cos(math.radians(46.8)))
        turn = (dcol * colw * math.sin(math.radians(46.8))
                * math.hypot(gw, 2 * hc))
        claimed = _globe.crop_dots(46.8, cap, gw, hc, dcol, 0)
        assert claimed == pytest.approx(
            turn + _globe.crop_dots(0.0, cap, gw, hc, dcol, 0), rel=1e-9)
        assert turn > 3.0                       # dots, not hundredths
        # at the equator the meridians do not converge and only the
        # sphere's own curve is left, which is the term this used to
        # carry alone
        assert _globe.crop_dots(0.0, cap, gw, hc, dcol, 0) < 0.5
        # and the turn grows with the latitude
        assert (_globe.crop_dots(60.0, cap, gw, hc, dcol, 0)
                > _globe.crop_dots(30.0, cap, gw, hc, dcol, 0)
                > _globe.crop_dots(0.0, cap, gw, hc, dcol, 0))

    def test_a_crop_too_far_off_centre_is_refused(self):
        # What the gate turns away has changed with what a crop is: a
        # window at rest is resampled and is out by nothing whatever
        # its offset, so what is left to refuse is a slice — the frames
        # under a hand — swimming far enough for a reader to see it.
        # At the equator that takes a long way, because there is no
        # turn and only the curve is left.
        gw, hc = 40, 12
        frame = over.Frame(bbox_for(0.0, 0.0, 30.0, gw, hc), gw, hc)
        colw, _rowh = frame.cell
        cap = _globe.cap(30.0, gw, hc)

        def at(cols):
            box = (frame.bbox[0] + cols * colw, frame.bbox[1],
                   frame.bbox[2] + cols * colw, frame.bbox[3])
            return over.locate(frame, box, gw, hc, inside=False, cap=cap)

        assert at(4) == (4, 0)
        assert at(40) is None
        # off the equator the turn carries it, and the same window is
        # refused a quarter of the way out
        north = over.Frame(bbox_for(60.0, 0.0, 30.0, gw, hc), gw, hc)
        ncolw, _ = north.cell
        far = (north.bbox[0] + 10 * ncolw, north.bbox[1],
               north.bbox[2] + 10 * ncolw, north.bbox[3])
        assert over.locate(north, far, gw, hc, inside=False) == (10, 0)
        assert over.locate(north, far, gw, hc, inside=False,
                           cap=cap) is None
        # a cell or two off centre is still a crop at either latitude
        near = (frame.bbox[0] + colw, frame.bbox[1],
                frame.bbox[2] + colw, frame.bbox[3])
        assert over.locate(frame, near, gw, hc, inside=False,
                           cap=cap) == (1, 0)
        # and a window at the built view's own centre always is one
        assert over.locate(frame, frame.bbox, gw, hc, cap=cap) == (0, 0)


class TestTheLoaderPicksItsSource:
    def test_tiles_inside_and_the_planet_beyond(self, monkeypatch):
        seen = []
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: seen.append("tiles"))
        monkeypatch.setattr(maps, "_get_globe",
                            lambda *a, **k: seen.append("planet"))
        maps._get_terrain(bbox_for(46.8, 8.2, 2.0, GW, HC), GW, HC, True)
        maps._get_terrain(bbox_for(46.8, 8.2, 60.0, GW, HC), GW, HC, True)
        assert seen == ["tiles", "planet"]


class TestBordersThroughTheCamera:
    def test_a_border_off_screen_costs_no_dots(self, monkeypatch):
        walked = []
        real = _basemap._bresenham

        def counted(*a):
            walked.append(1)
            return real(*a)

        monkeypatch.setattr(_basemap, "_bresenham", counted)
        # the middle of the South Pacific: the nearest border is
        # thousands of kilometres away, and a disk this size is bigger
        # than the planet's own circle of them
        empty = _globe.border_layer(-30.0, -140.0, 2.0, GW, HC,
                                    (1, 2, 3))
        assert not any(any(row) for row in empty.dots)
        assert walked == []
        # the same zoom over a border draws one
        drawn = _globe.border_layer(49.0, 7.0, 2.0, GW, HC, (1, 2, 3))
        assert any(any(row) for row in drawn.dots)

    def test_the_cull_keeps_every_dot_it_used_to_draw(self):
        # a rejection may only ever drop ink that was never on screen
        DotLayer = _basemap.DotLayer
        for lat, lon, zoom in ((49.0, 7.0, 6.0), (0.0, 20.0, 120.0),
                               (20.0, 78.0, 40.0)):
            layer = _globe.border_layer(lat, lon, zoom, 60, 18, (9, 9, 9))
            ref = DotLayer((0.0, 0.0, 1.0, 1.0), 60, 18)
            r = _globe._radius(zoom, 18 * 4)
            rx = r * _globe._aspect()
            cx, cy = 60.0, 36.0
            for coords in _globe._load_data()["borders"]:
                prev = None
                for plon, plat in coords:
                    ux, uy, cos_c = _globe.forward(plat, plon, lat, lon)
                    if cos_c <= 0.02:
                        prev = None
                        continue
                    p = (cx + ux * rx, cy - uy * r, ux, uy, cos_c)
                    if prev is not None:
                        arc = prev[2] * ux + prev[3] * uy + prev[4] * cos_c
                        if arc > 0.34:
                            ref._dot_line(prev[0], prev[1], p[0], p[1],
                                          (9, 9, 9))
                    prev = p
            assert layer.dots == ref.dots


class TestElevationThroughTheCamera:
    """A synthetic tile source, so what is compared is the sampling."""

    def _patch(self, monkeypatch):
        def decoded(z, x, y, timeout):
            size = 256
            rgba = bytearray(size * size * 4)
            for py in range(size):
                for px in range(size):
                    # a smooth ramp in world pixels: metres = wx + 2*wy
                    v = int(32768 + (x * size + px) + 2 * (y * size + py))
                    i = (py * size + px) * 4
                    rgba[i] = (v >> 8) & 0xFF
                    rgba[i + 1] = v & 0xFF
                    rgba[i + 3] = 255
            return (size, size, rgba)

        monkeypatch.setattr(_elevation, "_decoded_tile", decoded)

    def test_it_matches_the_flat_grid_where_the_bound_holds(self,
                                                            monkeypatch):
        self._patch(monkeypatch)
        lat, lon, zoom = 46.8, 8.2, 0.02
        gw, hc = 20, 6
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        flat = _elevation.elevation_grid(bbox, gw * 2, hc * 4)
        turned = _elevation.elevation_grid(bbox, gw * 2, hc * 4, camera=cam)
        # the source is one metre per tile pixel and a dot here is far
        # under a tile pixel, so the two grids differ by the geometry
        # alone — which the bound says is a twentieth of a dot
        worst = max(abs(a - b) for ra, rb in zip(flat, turned)
                    for a, b in zip(ra, rb))
        assert worst < 1.0

    def test_the_camera_grid_is_the_camera_s(self, monkeypatch):
        # far enough out that the two part company, and in the
        # direction the parallel bends
        self._patch(monkeypatch)
        lat, lon, zoom = 46.8, 8.2, 2.0
        gw, hc = 20, 6
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        flat = _elevation.elevation_grid(bbox, gw * 2, hc * 4)
        turned = _elevation.elevation_grid(bbox, gw * 2, hc * 4, camera=cam)
        assert flat != turned
        # the centre sample is the one place they must agree
        mid_y, mid_x = hc * 2, gw
        assert turned[mid_y][mid_x] == pytest.approx(flat[mid_y][mid_x],
                                                     abs=2.0)


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _braille(frame):
    body = "\n".join(ANSI.sub("", frame).split("\n")[1:-1])
    return sum(1 for ch in body if 0x2800 <= ord(ch) <= 0x28FF)


class TestTheTransitionIsInked:
    COLS, ROWS = 60, 20

    def test_every_frame_of_a_zoom_through_the_hand_off_has_ink(
            self, monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        spy = hc * 2
        view = _globe.GlobeView(
            [[100.0] * gw for _ in range(spy)],
            [[0xFF] * gw for _ in range(hc)],
            [[1.0] * gw for _ in range(spy)],
            [[0.0] * gw for _ in range(spy)],
            None, None,
            fill=[[(180, 90, 40)] * gw for _ in range(spy)])
        maps._last_terrain[0] = None

        def loaded(bbox, ogw, ohc, block, window=None):
            # a built view is the overscan's size, not the window's
            return maps.TerrainView(
                [[100.0] * ogw for _ in range(ohc * 2)],
                [[0xFF] * ogw for _ in range(ohc)], None, None, None)

        monkeypatch.setattr(maps, "_get_elevation", loaded)
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: view)
        # a real frame on the way in, so there is something to carry
        maps.render_map(0.0, 8.2, "Gulf of Guinea", 30.0, block=False,
                        view="terrain")
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: None)
        # the ease out through the hand-off, every step a stand-in
        for zoom in (33.0, 36.0, 40.0, 44.0, 45.0, 46.0, 50.0):
            frame = maps.render_map(0.0, 8.2, "Gulf of Guinea", zoom,
                                    block=False, view="terrain")
            assert _braille(frame), f"blank frame at {zoom} deg"
        maps._last_terrain[0] = None


class TestTheSourcesStayWithinReach:
    """The tile sources are refused wherever they would be asked for a
    hemisphere, and the margin cannot carry a view past them."""

    def test_a_window_whose_corner_leaves_the_disk_is_the_planet_s(self):
        # a terminal five times wider than it is tall shows the limb
        # well before is_globe hands over; stitching tiles behind a
        # limb would mean every tile on the planet
        gw, hc = maps.map_cells((250, 30))
        assert _globe.local_tiles(0.0, 20.0, gw, hc)
        assert _globe.cap_sine(30.0, gw, hc) > 1.0
        assert not _globe.is_globe(30.0, 0.0)
        assert not _globe.local_tiles(0.0, 30.0, gw, hc)
        # and where the tiles are still asked, the footprint is a strip
        # of the sphere, not the whole of it
        box = _globe.bounds(0.0, 0.0, 20.0, gw, hc)
        assert box[2] - box[0] < 180.0 and box[3] - box[1] < 40.0

    def test_the_margin_is_stitched_from_the_window_s_own_source(
            self, monkeypatch):
        # the last few degrees before the hand-off: the window is on
        # the tiles and its overscan, a quarter again as wide, would be
        # sent to the planet.  The window decides, and the margin is
        # stitched from the tiles with it
        seen = []
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: seen.append("tiles"))
        monkeypatch.setattr(maps, "_get_globe",
                            lambda *a, **k: seen.append("planet"))
        maps._last_terrain[0] = None
        lat, lon, zoom = 46.8, 8.2, 28.0
        assert _globe.local_tiles(lat, zoom, GW, HC)
        bbox = bbox_for(lat, lon, zoom, GW, HC)
        frame, at, _source = maps._flat_frame(
            "terrain", bbox, GW, HC, False, (0, 0),
            cap=_globe.cap(zoom, GW, HC))
        assert (frame.gw, frame.hc) != (GW, HC)
        fcam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        assert not fcam.local_tiles
        maps._get_terrain(frame.bbox, frame.gw, frame.hc, True,
                          over.window_hint(frame, GW, HC))
        assert seen == ["tiles"]
        maps._last_terrain[0] = None

    def test_a_margin_whose_corner_would_leave_the_disk_is_dropped(self):
        # a window a degree short of the hand-off at the equator: its
        # own corners are on the disk, its margin's are not, and a
        # stitch behind a limb is every tile on the planet
        maps._last_terrain[0] = None
        gw, hc = 200, 45
        lat, lon, zoom = 0.0, 8.2, 44.5
        assert _globe.local_tiles(lat, zoom, gw, hc)
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        planned, _at = over.plan(bbox, gw, hc)
        assert _globe.cap_sine(planned.hc * planned.cell[1], planned.gw,
                               planned.hc) > 1.0
        frame, at, _source = maps._flat_frame(
            "terrain", bbox, gw, hc, False, (0, 0),
            cap=_globe.cap(zoom, gw, hc))
        assert (frame.gw, frame.hc) == (gw, hc) and at == (0, 0)
        maps._last_terrain[0] = None


class TestEveryLayerIsTheCameras:
    def test_the_climate_families_follow_the_camera(self, monkeypatch):
        asked = []
        monkeypatch.setattr(_climate, "grid_for_lls",
                            lambda lls: asked.append("lls") or None)
        monkeypatch.setattr(_climate, "grid_for_bbox",
                            lambda *a: asked.append("bbox") or None)
        gw, hc = 20, 6
        for zoom, expect in ((0.02, ["bbox"]), (2.0, ["lls"])):
            asked.clear()
            bbox = bbox_for(46.8, 8.2, zoom, gw, hc)
            view = maps.TerrainView(
                [[500.0] * gw for _ in range(hc * 2)], None, None, None,
                None)
            _views._terrain_cache.clear()
            maps._terrain_buffer(view, bbox, gw, hc)
            assert asked == expect, zoom

    def test_the_route_is_placed_by_the_camera_where_the_fill_is(self):
        gw, hc = 40, 12
        lat, lon, zoom = 46.8, 8.2, 10.0
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        cam = _globe.Camera.for_bbox(bbox, gw, hc)
        assert not _globe.affine_ok(cam.lat, cam.zoom, gw, hc)
        # a line along the parallel three degrees north of the centre:
        # flat, it is a row; on the sphere it bows toward the pole
        coords = [(lon - 8.0 + i, lat + 3.0) for i in range(17)]
        route = Route(coords, 1.0, 1.0, [], "car")
        flat = maps._get_route_layer(route, bbox, gw, hc)
        maps._route_layer_cache.clear()
        route2 = Route(coords, 1.0, 1.0, [], "car")
        turned = maps._get_route_layer(
            route2, bbox, gw, hc,
            lambda plon, plat: cam.project(plon, plat, gw * 2, hc * 4))
        assert flat.dots != turned.dots
        # the camera's own placement of the end of the line
        x, y = cam.project(coords[0][0], coords[0][1], gw * 2, hc * 4)
        assert turned.dots[int(y) // 4][int(x) // 2]

    def test_render_map_hands_the_terrain_route_to_the_camera(
            self, monkeypatch):
        seen = []

        def capture(route, bbox, gw, hc, project=None):
            seen.append(project)
            return None

        monkeypatch.setattr(maps, "_get_route_layer", capture)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (80, 24))
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        maps._last_terrain[0] = None
        route = Route([(8.0, 46.0), (9.0, 47.0)], 1.0, 1.0, [], "car")
        maps.render_map(46.8, 8.2, "Alps", 10.0, block=False,
                        view="terrain", route=route)
        maps.render_map(46.8, 8.2, "Alps", 0.02, block=False,
                        view="terrain", route=route)
        assert seen[0] is not None and seen[1] is None
        maps._last_terrain[0] = None


class TestTheRestingCropIsTheWindow:
    """A pan inside the margin, once it comes to rest.

    The crop is free and the margin is what makes it free, but under
    one camera a crop taken off the built view's centre is the right
    ground in the wrong place: the built view has turned with the
    meridians, and a slice of it puts the coastline dots off their own
    shore.  At rest the window's samples are fetched out of the built
    view instead, through the rotation between the two cameras, and
    the picture is the one the window would have built.

    A synthetic elevation source, so what is measured is the sampling
    and not the network: a smooth field of two sines in the world's own
    coordinates, which crosses sea level often enough to put a long
    shoreline on the screen and is the same field at every zoom.
    """

    GW, HC = 160, 43            # a 160x45 terminal's map

    def _patch(self, monkeypatch):
        def decoded(z, x, y, timeout):
            size = 256
            world = float(size << z)
            cols = [math.sin(2 * math.pi * 40.0 * (x * size + px) / world)
                    for px in range(size)]
            rgba = bytearray(size * size * 4)
            for py in range(size):
                down = math.sin(2 * math.pi * 40.0
                                * (y * size + py) / world)
                base = py * size * 4
                for px in range(size):
                    v = int(32768 + 2000 * (cols[px] + down))
                    i = base + px * 4
                    rgba[i] = (v >> 8) & 0xFF
                    rgba[i + 1] = v & 0xFF
                    rgba[i + 3] = 255
            return (size, size, rgba)

        monkeypatch.setattr(_elevation, "_decoded_tile", decoded)
        monkeypatch.setattr(_views, "_tile_water",
                            lambda *a, **k: (None, None, None, None))
        monkeypatch.setattr(_views, "_builtup_layer", lambda *a, **k: None)
        _views._elev_cache.clear()

    def _pan(self, lat, lon, zoom, dcol):
        """(built overscan, its frame, the window, the view built for it)."""
        gw, hc = self.GW, self.HC
        bbox = bbox_for(lat, lon, zoom, gw, hc)
        frame, at = over.plan(bbox, gw, hc)
        colw, _rowh = frame.cell
        window = (bbox[0] + dcol * colw, bbox[1],
                  bbox[2] + dcol * colw, bbox[3])
        built = _views._get_elevation(frame.bbox, frame.gw, frame.hc, True,
                                      over.window_hint(frame, gw, hc))
        real = _views._get_elevation(window, gw, hc, True)
        return built, frame, (at[0] + dcol, at[1]), window, real

    @staticmethod
    def _lit(grid):
        return {(cx * 2 + sx, cy * 4 + sy)
                for cy, row in enumerate(grid)
                for cx, v in enumerate(row) if v
                for sx in (0, 1) for sy in range(4) if v & _BITS[sx][sy]}

    @classmethod
    def _on_shore(cls, grid, real, reach=1):
        """The share of a shoreline's dots within `reach` dots of the
        shoreline the window's own view drew — `reach` 0 for the dots
        that are on it."""
        near = {(x + dx, y + dy) for x, y in cls._lit(real)
                for dx in range(-reach, reach + 1)
                for dy in range(-reach, reach + 1)}
        dots = cls._lit(grid)
        assert dots
        return sum(1 for d in dots if d in near) / len(dots)

    @pytest.mark.parametrize("lat,lon,zoom,dcol", [
        (46.8, 8.2, 2.0, 20),      # the Alps, the whole margin
        (46.8, 8.2, 10.0, 9),      # and wide enough for the turn to bite
        (-34.0, 18.5, 4.0, 20),    # Cape Town, the turn the other way
    ])
    def test_the_resting_shoreline_lands_on_the_real_one(
            self, monkeypatch, lat, lon, zoom, dcol):
        self._patch(monkeypatch)
        gw, hc = self.GW, self.HC
        built, frame, (dx, dy), window, real = self._pan(lat, lon, zoom,
                                                         dcol)
        # the crop the gate accepts today
        assert over.locate(frame, window, gw, hc,
                           cap=_globe.cap(zoom, gw, hc)) == (dx, dy)
        sliced = over.crop_grid(built.coast, dx, dy, gw, hc)
        cut = over.Resample(frame, window, gw, hc)
        exact = _edge_dots(cut.bits(built.shore, _views.SHORE_LAND),
                           cut.bits(built.shore, _views.SHORE_WATER),
                           gw, hc)
        # every dot of the resampled shore is on the real one or next
        # to it, at every one of these views; the slice is not
        assert self._on_shore(exact, real.coast) > 0.995
        # and on it, dot for dot, two to four times as often.  Not
        # every dot: a mask resampled onto another grid of the same
        # pitch rounds to the nearest sample, which can carry a shore
        # dot to the dot beside it — the residual this leaves, and the
        # reason the looser measure above is the one that has to be
        # exhaustive
        on = self._on_shore(exact, real.coast, 0)
        slid = self._on_shore(sliced, real.coast, 0)
        assert on > 0.6 and slid < 0.4 and on > 1.8 * slid

    def test_the_readout_under_the_crosshair_is_the_real_view_s(
            self, monkeypatch):
        self._patch(monkeypatch)
        gw, hc = self.GW, self.HC
        built, frame, (dx, dy), window, real = self._pan(46.8, 8.2, 10.0, 9)
        cut = over.Resample(frame, window, gw, hc)
        elev = cut.grid(built.elev, None)
        sliced = over.crop_grid(built.elev, dx, dy * 2, gw, hc * 2)

        def astray(grid):
            """Probes outside the range of the real view's own sample
            and the eight around it — a reading off by more than the
            rounding of picking the nearest sample."""
            out = 0
            for y in range(1, hc * 2 - 1):
                for x in range(1, gw - 1):
                    near = [real.elev[y + j][x + i]
                            for j in (-1, 0, 1) for i in (-1, 0, 1)]
                    if not min(near) <= grid[y][x] <= max(near):
                        out += 1
            return out

        inner = (hc * 2 - 2) * (gw - 2)
        # the crosshair sits on the middle sample, and the readout it
        # takes is the real view's — bar fewer than one probe in a
        # thousand, where the ground turns over between two samples and
        # the nearest one is outside the range of its own neighbours
        assert astray(elev) < inner // 1000
        cy, cx = hc, gw // 2                        # under the crosshair
        at_cross = [real.elev[cy + j][cx + i]
                    for j in (-1, 0, 1) for i in (-1, 0, 1)]
        assert min(at_cross) <= elev[cy][cx] <= max(at_cross)
        # the slice reads a different place on the mountain a hundred
        # times as often, which is the readout under the crosshair
        # naming the height of somewhere else
        assert astray(sliced) > 50 * max(1, astray(elev))
        assert astray(sliced) > inner // 100

    def test_a_frame_in_motion_still_slices(self, monkeypatch):
        self._patch(monkeypatch)
        gw, hc = self.GW, self.HC
        _built, frame, at, window, _real = self._pan(46.8, 8.2, 10.0, 9)
        assert maps._exact_crop(frame, window, gw, hc, at, True) is None
        assert maps._exact_crop(frame, window, gw, hc, at, False) is not None

    def test_a_window_at_the_built_view_s_centre_is_a_slice(self):
        gw, hc = self.GW, self.HC
        bbox = bbox_for(46.8, 8.2, 10.0, gw, hc)
        frame, at = over.plan(bbox, gw, hc)
        assert maps._exact_crop(frame, bbox, gw, hc, at, False) is None
        # and so is a street-scale window, where the ground was drawn
        # on a box linear in longitude and latitude and a crop of that
        # box is the window's own picture
        close = bbox_for(46.8, 8.2, 0.02, gw, hc)
        cframe, cat = over.plan(close, gw, hc)
        colw, _rowh = cframe.cell
        moved = (close[0] + 20 * colw, close[1],
                 close[2] + 20 * colw, close[3])
        assert maps._exact_crop(cframe, moved, gw, hc,
                               (cat[0] + 20, cat[1]), False) is None

    def test_a_name_in_the_resting_crop_sits_on_its_city(self, monkeypatch):
        self._patch(monkeypatch)
        gw, hc = self.GW, self.HC
        _built, frame, (dx, dy), window, _real = self._pan(46.8, 8.2, 10.0,
                                                           9)
        cut = over.Resample(frame, window, gw, hc)
        basemap = _get_basemap(frame.bbox, frame.gw, frame.hc)
        kept = over.crop_overlays(
            basemap.city_overlays(project=cut.place(dx, dy)), dx, dy, gw, hc)
        marks = [cell for cell, (ch, _ink) in kept.items() if ch == "•"]
        assert marks
        # every dot is on a city, by the window's own camera
        cam = _globe.Camera.for_bbox(window, gw, hc)
        here = {(int(x), int(y)) for x, y in
                (cam.cell(e[0], e[1])
                 for e in _globe._load_data()["cities"])}
        assert all(cell in here for cell in marks)
        # and the built view's own placement is not the same answer:
        # that is the drift the names would have had
        wide = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        moved = over.crop_overlays(
            basemap.city_overlays(project=wide.cell), dx, dy, gw, hc)
        assert [cell for cell, (ch, _i) in moved.items()
                if ch == "•"] != marks
