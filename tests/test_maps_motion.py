"""The map in motion: one frame re-projected into the next, and the
flight path between two views."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_motion as mm
from linecast._radar_render import bbox_for
from linecast._radar_ui import _shift_grid

GW, HC = 40, 12


def flat(lat, lon, zoom, gw=GW, hc=HC):
    return mm.Geom(lat, lon, zoom, gw, hc, globe=False)


def globe(lat, lon, zoom, gw=GW, hc=HC):
    return mm.Geom(lat, lon, zoom, gw, hc, globe=True)


def numbered(w, h):
    """A grid whose every cell says where it is."""
    return [[(x, y) for x in range(w)] for y in range(h)]


def cell_shift(geom, dcol, drow):
    """The geom recentred so the picture moves (dcol, drow) cells."""
    minlon, minlat, maxlon, maxlat = geom.bbox
    lon = geom.lon - dcol * (maxlon - minlon) / geom.gw
    lat = geom.lat + drow * (maxlat - minlat) / geom.hc
    return flat(lat, lon, geom.zoom, geom.gw, geom.hc)


class TestGeom:
    def test_a_flat_window_is_the_renderers_bbox(self):
        g = flat(43.68, -70.37, 2.0)
        assert g.bbox == bbox_for(43.68, -70.37, 2.0, GW, HC)
        assert not g.globe

    def test_the_projection_follows_the_zoom_unless_told(self):
        assert mm.Geom(43.68, -70.37, 60.0, GW, HC).globe
        assert not mm.Geom(43.68, -70.37, 2.0, GW, HC).globe

    def test_overlap_is_the_covered_fraction(self):
        g = flat(43.68, -70.37, 2.0)
        assert g.overlap(g) == pytest.approx(1.0)
        assert g.overlap(flat(0.0, 100.0, 2.0)) == 0.0
        half = cell_shift(g, GW // 2, 0)
        assert g.overlap(half) == pytest.approx(0.5, abs=1e-6)

    def test_overlap_folds_the_source_round_the_planet(self):
        g = flat(0.0, 179.5, 2.0)
        assert g.overlap(flat(0.0, -179.5, 2.0)) > 0.0


class TestSampleMap:
    def test_a_whole_cell_pan_is_the_drag_previews_shift(self):
        # on the equator, where a row's worth of latitude leaves the
        # window's width alone; elsewhere the columns rescale a hair
        src = flat(0.0, -70.37, 2.0)
        for dcol, drow in ((3, 0), (0, 2), (-5, -1), (7, 4)):
            m = mm.sample_map(src, cell_shift(src, dcol, drow))
            assert m.cols is not None and m.same_scale
            grid = numbered(GW, HC)
            assert m.grid(grid, None) == _shift_grid(grid, dcol, drow, None)
            sub = numbered(GW, HC * 2)
            assert m.grid(sub, None, sub=True) == _shift_grid(
                sub, dcol, drow * 2, None)

    def test_a_zoom_in_scales_about_the_centre(self):
        src = flat(43.68, -70.37, 2.0)
        m = mm.sample_map(src, flat(43.68, -70.37, 1.0))
        assert not m.same_scale
        # the target's edge column reads a quarter of the way in
        assert m.cols[0] == GW // 4
        assert m.cols[-1] == GW - GW // 4 - 1
        assert m.rows_sub[0] == HC * 2 // 4

    def test_a_zoom_out_leaves_the_margins_empty(self):
        src = flat(43.68, -70.37, 1.0)
        m = mm.sample_map(src, flat(43.68, -70.37, 2.0))
        assert m.cols[0] == -1 and m.cols[-1] == -1
        assert m.cols[GW // 2] == 0 or m.cols[GW // 2 - 1] >= 0
        grid = m.grid(numbered(GW, HC), "x")
        assert grid[0][0] == "x" and grid[HC // 2][GW // 2] != "x"

    def test_a_pan_across_the_antimeridian_still_lands(self):
        src = flat(0.0, 179.9, 2.0)
        m = mm.sample_map(src, cell_shift(src, 4, 0))
        assert m.cols[4] == 0 and m.cols[3] == -1

    def test_different_sizes_cannot_be_sampled(self):
        assert mm.sample_map(flat(0, 0, 2.0), flat(0, 0, 2.0, 41, HC)) is None

    def test_the_globe_scales_about_its_centre(self):
        src = globe(20.0, -30.0, 100.0)
        m = mm.sample_map(src, globe(20.0, -30.0, 50.0))
        assert m.cols is not None and not m.same_scale
        assert m.cols[GW // 2] == GW // 2
        assert m.cols[0] == GW // 4

    def test_a_turn_of_the_globe_is_a_per_cell_map(self):
        src = globe(20.0, -30.0, 100.0)
        m = mm.sample_map(src, globe(20.0, -20.0, 100.0))
        assert m.cols is None and not m.same_scale
        assert m.glyphs({(GW // 2, HC // 2): ("x", None)}) == {}
        # the target's centre is 10° east on the source: to the right
        at = m.cell[HC // 2][GW // 2]
        assert at is not None and at[0] > GW // 2
        # space stays space
        assert m.cell[0][0] is None

    def test_a_flat_window_reads_from_the_globe_and_back(self):
        g = globe(20.0, -30.0, 30.0)
        f = flat(20.0, -30.0, 30.0)
        onto_flat = mm.sample_map(g, f)
        assert onto_flat.cell[HC // 2][GW // 2] == (GW // 2, HC // 2)
        assert not onto_flat.same_scale
        onto_globe = mm.sample_map(f, g)
        assert onto_globe.cell[HC // 2][GW // 2] == (GW // 2, HC // 2)

    def test_glyphs_ride_a_pan_and_drop_out_of_a_zoom(self):
        src = flat(43.68, -70.37, 2.0)
        glyphs = {(10, 5): ("A", None), (11, 5): ("b", None)}
        pan = mm.sample_map(src, cell_shift(src, 3, 1))
        assert pan.glyphs(glyphs) == {(13, 6): ("A", None), (14, 6): ("b", None)}
        zoom = mm.sample_map(src, flat(43.68, -70.37, 1.0))
        assert zoom.glyphs(glyphs) == {}

    def test_the_ribbon_follows_its_cells(self):
        src = flat(43.68, -70.37, 2.0)
        m = mm.sample_map(src, cell_shift(src, 2, 0))
        assert m.cells({(5, 5), (GW - 1, 5)}) == {(7, 5)}
        assert m.cells(set()) == set()


def keyframe(geom, register="terrain", generation=1):
    fill = numbered(geom.gw, geom.hc * 2)
    dots = [[0] * geom.gw for _ in range(geom.hc)]
    color = [[None] * geom.gw for _ in range(geom.hc)]
    dots[3][4] = 0x3F
    color[3][4] = (1, 2, 3)
    return mm.Keyframe(geom, register, "terrain", fill,
                       [(dots, color, {(4, 3)})], coast=dots,
                       basemap=(dots, color), glyphs={(4, 3): ("x", None)},
                       generation=generation)


class TestPlaceholder:
    def test_every_part_moves_together(self):
        src = flat(43.68, -70.37, 2.0)
        out = mm.placeholder(keyframe(src), cell_shift(src, 2, 1))
        assert out.fill[2][2] == (0, 0) and out.fill[0][0] is None
        dots, color, ribbon = out.layers[0]
        assert dots[4][6] == 0x3F and color[4][6] == (1, 2, 3)
        assert ribbon == {(6, 4)}
        assert out.coast[4][6] == 0x3F and out.basemap[0][4][6] == 0x3F
        assert out.glyphs == {(6, 4): ("x", None)}
        assert out.register == "terrain" and out.composer == "terrain"

    def test_a_different_size_gives_nothing(self):
        src = flat(43.68, -70.37, 2.0)
        assert mm.placeholder(keyframe(src), flat(43.68, -70.37, 2.0, 41, HC)) is None


class TestMemory:
    @pytest.fixture(autouse=True)
    def _clear(self):
        mm.forget()
        yield
        mm.forget()

    def test_the_best_cover_wins_and_the_rest_are_filtered(self):
        near = flat(43.68, -70.37, 2.0)
        far = flat(0.0, 100.0, 2.0)
        mm.remember(keyframe(near, register="street"))
        mm.remember(keyframe(near, generation=2))
        mm.remember(keyframe(flat(43.68, -70.37, 2.0, GW + 1, HC)))
        assert mm.best(near, "terrain", 1) is None
        assert mm.best(near, "street", 1).register == "street"
        assert mm.best(near, "terrain", 2).generation == 2
        kf = keyframe(near)
        mm.remember(kf)
        assert mm.best(near, "terrain", 1) is kf
        assert mm.best(far, "terrain", 1) is None

    def test_the_greater_cover_wins_whatever_the_order(self):
        near = flat(43.68, -70.37, 2.0)
        close = keyframe(cell_shift(near, 2, 0))
        closer = keyframe(cell_shift(near, 1, 0))
        mm.remember(closer)
        mm.remember(close)
        assert mm.best(near, "terrain", 1) is closer

    def test_only_a_few_frames_are_kept(self):
        for i in range(mm.KEEP + 2):
            mm.remember(keyframe(flat(float(i), 0.0, 2.0)))
        assert mm.best(flat(0.0, 0.0, 2.0), "terrain", 1) is None
        assert mm.best(flat(float(mm.KEEP + 1), 0.0, 2.0), "terrain", 1)

    def test_a_disjoint_frame_never_serves(self):
        mm.remember(keyframe(flat(0.0, 100.0, 2.0)))
        assert mm.best(flat(43.68, -70.37, 2.0), "terrain", 1) is None


class TestFlight:
    def test_the_ends_are_exact(self):
        f = mm.Flight(43.68, -70.37, 0.05, 43.66, -70.25, 0.02)
        assert f.at(0.0) == (43.68, -70.37, 0.05)
        assert f.at(f.duration) == (43.66, -70.25, 0.02)
        assert f.at(f.duration + 5.0) == (43.66, -70.25, 0.02)

    def test_a_hop_rises_to_see_both_ends_then_settles(self):
        f = mm.Flight(43.68, -70.37, 0.05, 44.0, -71.0, 0.05)
        peak = max(f.at(f.duration * k / 20)[2] for k in range(21))
        assert peak > 0.05
        assert peak < 2.0   # but not to the planet for a short hop
        mid = f.at(f.duration / 2)
        assert 43.68 < mid[0] < 44.0

    def test_a_long_flight_goes_up_to_the_globe(self):
        f = mm.Flight(51.5, -0.1, 0.05, 35.7, 139.7, 0.05)
        peak = max(f.at(f.duration * k / 40)[2] for k in range(41))
        assert peak > 45.0
        assert f.duration == mm.FLIGHT_MAX

    def test_a_pure_zoom_is_exponential(self):
        f = mm.Flight(10.0, 20.0, 1.0, 10.0, 20.0, 4.0)
        lat, lon, zoom = f.at(f.duration / 2)
        assert (lat, lon) == (10.0, 20.0)
        assert zoom == pytest.approx(2.0)
        assert f.duration >= mm.FLIGHT_MIN

    def test_the_longitude_takes_the_short_way_round(self):
        f = mm.Flight(0.0, 170.0, 1.0, 0.0, -170.0, 1.0)
        lat, lon, _zoom = f.at(f.duration / 2)
        assert abs(abs(lon) - 180.0) < 1e-6

    def test_position_and_zoom_move_monotonically_on_a_pure_pan(self):
        f = mm.Flight(0.0, 0.0, 1.0, 0.0, 5.0, 1.0)
        lons = [f.at(f.duration * k / 30)[1] for k in range(31)]
        assert lons == sorted(lons)
        zooms = [f.at(f.duration * k / 30)[2] for k in range(31)]
        top = zooms.index(max(zooms))
        assert zooms[:top + 1] == sorted(zooms[:top + 1])
        assert zooms[top:] == sorted(zooms[top:], reverse=True)
        assert math.isclose(zooms[0], zooms[-1])
