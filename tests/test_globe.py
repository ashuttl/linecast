"""The orthographic globe: projection math, sampling, and hand-off."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe


class TestProjection:
    def test_forward_center_is_origin(self):
        ux, uy, cos_c = _globe.forward(37.0, -100.0, 37.0, -100.0)
        assert abs(ux) < 1e-12 and abs(uy) < 1e-12
        assert abs(cos_c - 1.0) < 1e-12

    def test_antipode_is_hidden(self):
        _ux, _uy, cos_c = _globe.forward(-37.0, 80.0, 37.0, -100.0)
        assert cos_c < 0

    def test_geometry_roundtrips_through_forward(self):
        lat0, lon0, zoom, w, h = 37.0, -100.0, 90.0, 40, 40
        lls, zs, _rhos = _globe.geometry(lat0, lon0, zoom, w, h)
        r = _globe._radius(zoom, h)
        for y in (5, 20, 34):
            for x in (5, 20, 34):
                ll = lls[y][x]
                if ll is None:
                    continue
                ux, uy, cos_c = _globe.forward(ll[0], ll[1], lat0, lon0)
                assert cos_c > 0
                assert abs((w / 2.0 + ux * r) - (x + 0.5)) < 1e-6
                assert abs((h / 2.0 - uy * r) - (y + 0.5)) < 1e-6
                assert abs(zs[y][x] - cos_c) < 1e-9

    def test_space_is_none_and_rho_exceeds_one(self):
        # a full-planet view leaves the corners in space
        lls, zs, rhos = _globe.geometry(0.0, 0.0, 130.0, 40, 40)
        assert lls[0][0] is None and zs[0][0] is None
        assert rhos[0][0] > 1.0
        assert lls[20][20] is not None

    def test_limb_scale_matches_flat_map_at_center(self):
        # one grid row at the disk centre spans zoom/h degrees of arc —
        # the hand-off does not change the size of anything on screen
        lls, _zs, _rhos = _globe.geometry(0.0, 0.0, 90.0, 400, 400)
        a, b = lls[199][200], lls[200][200]
        assert abs((a[0] - b[0]) - 90.0 / 400) < 0.01


class TestMarkers:
    def test_center_marker_lands_center_cell(self):
        cell = _globe.marker_cell(20.0, -30.0, 125.0, 80, 22, 20.0, -30.0)
        assert cell == (40, 11)

    def test_far_hemisphere_marker_hides(self):
        assert _globe.marker_cell(20.0, -30.0, 125.0, 80, 22,
                                  -20.0, 150.0) is None


class TestElevation:
    def _flat_canvas(self, meters):
        # a one-tile world where every pixel decodes to `meters`
        v = int(meters + 32768)
        r, g = v >> 8, v & 0xFF
        canvas = bytearray()
        for _ in range(256 * 256):
            canvas += bytes((r, g, 0, 255))
        return (canvas, 256, 256, 0, 0, 256)

    def test_samples_visible_disk_only(self, monkeypatch):
        monkeypatch.setattr(_globe, "_world_canvas",
                            lambda z, timeout: self._flat_canvas(100))
        lls, _zs, _rhos = _globe.geometry(0.0, 0.0, 180.0, 20, 20)
        grid = _globe.elevation(lls, 180.0, 20)
        assert grid[0][0] is None  # space
        center = grid[10][10]
        assert center is not None and abs(center - 100.0) < 1.0

    def test_pole_clamps_to_mercator_edge(self, monkeypatch):
        monkeypatch.setattr(_globe, "_world_canvas",
                            lambda z, timeout: self._flat_canvas(-4000))
        # centred on the pole itself: every visible sample clamps
        lls, _zs, _rhos = _globe.geometry(89.0, 0.0, 125.0, 12, 12)
        grid = _globe.elevation(lls, 125.0, 12)
        assert grid[6][6] is not None

    def test_warm_tracks_the_stitched_canvas(self, monkeypatch):
        # warm() gates live drag rotation: it must agree with the
        # source zoom elevation() actually samples, and never fetch
        monkeypatch.setattr(_globe, "_canvas_cache", {})
        zoom, h = 125.0, 44 * 4
        assert not _globe.warm(zoom, h)
        _globe._canvas_cache[_globe._source_zoom(zoom, h)] = object()
        assert _globe.warm(zoom, h)
        assert not _globe.warm(zoom, h * 8)  # finer grid, colder zoom


class TestAtmosphere:
    def test_rim_hugs_the_limb(self):
        _lls, _zs, rhos = _globe.geometry(0.0, 0.0, 125.0, 80, 44)
        atmo = _globe.atmosphere(rhos, 125.0, 44)
        on_disk = sum(1 for row in atmo for a in row if a > 0)
        assert on_disk > 0  # some rim exists
        # nothing deep in space glows
        assert atmo[0][0] == 0.0

    def test_shade_buffer_darkens_limb_and_paints_rim(self):
        buf = [[(200, 100, 50), (200, 100, 50)]]
        shade = [[1.0, None]]
        atmo = [[0.0, 1.0]]
        _globe.shade_buffer(buf, shade, atmo, (10, 10, 10))
        assert buf[0][0] == (200, 100, 50)  # full-face: untouched
        assert buf[0][1] != (200, 100, 50)  # space rim: atmosphere tint
        assert buf[0][1][2] > buf[0][1][0]  # and it leans blue


class TestIce:
    def test_antarctica_and_greenland_dome_are_ice(self):
        lls = [[(-75.0, 0.0), (72.0, -40.0), (72.0, -40.0), (45.0, 7.0)]]
        elev = [[300.0, 2500.0, 900.0, 2500.0]]
        cover = _globe.ice_cover(lls, elev, 7)
        # Antarctic coast, Greenland dome: ice; Greenland's low coast
        # and an Alpine summit at 45N: not
        assert list(cover[0]) == [7, 7, 0, 0]

    def test_no_ice_in_view_means_no_grid(self):
        lls = [[(10.0, 0.0), None]]
        elev = [[500.0, None]]
        assert _globe.ice_cover(lls, elev, 7) is None


class TestLabelToggle:
    def test_globe_render_hides_city_text_when_toggled(self, monkeypatch):
        from linecast import maps
        gw, hc = 40, 12
        lls, zs, rhos = _globe.geometry(20.0, -30.0, 125.0, gw, hc * 2)
        elev = [[None if ll is None else 500.0 for ll in row]
                for row in lls]
        view = _globe.GlobeView(elev, [[0] * gw for _ in range(hc)], zs,
                                _globe.atmosphere(rhos, 125.0, hc * 2),
                                None, None)
        monkeypatch.setattr(maps, "_get_globe", lambda *a: view)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (gw, hc + 2))
        bbox = (-31.0, -42.5, -29.0, 82.5)  # centre (20, -30), zoom 125
        args = (bbox, gw, hc, True, (0, 0), None, None, None, None,
                "en", None)
        on, *_rest = maps._render_globe(*args, show_labels=True)
        off, *_rest = maps._render_globe(*args, show_labels=False)
        assert any("•" in line for line in on)
        assert not any("•" in line for line in off)

    def test_globe_render_hides_borders_when_toggled(self, monkeypatch):
        from linecast import maps
        gw, hc = 40, 12
        lls, zs, rhos = _globe.geometry(20.0, -30.0, 125.0, gw, hc * 2)
        elev = [[None if ll is None else 500.0 for ll in row]
                for row in lls]
        borders = maps.DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
        # near the disk centre, but clear of the centre crosshair's cell
        borders._set_dot(gw + 4, hc * 2, maps.BORDER_STROKE)
        view = _globe.GlobeView(elev, [[0] * gw for _ in range(hc)], zs,
                                _globe.atmosphere(rhos, 125.0, hc * 2),
                                None, borders)
        monkeypatch.setattr(maps, "_get_globe", lambda *a: view)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (gw, hc + 2))
        monkeypatch.setattr(_globe, "city_overlays", lambda *a, **k: {})
        bbox = (-31.0, -42.5, -29.0, 82.5)
        args = (bbox, gw, hc, True, (0, 0), None, None, None, None,
                "en", None)
        on, *_rest = maps._render_globe(*args, show_labels=True)
        off, *_rest = maps._render_globe(*args, show_labels=False)
        stroke = chr(0x2800 + borders.dots[hc // 2][gw // 2 + 2])
        assert any(stroke in line for line in on)
        assert not any(stroke in line for line in off)

    def test_terrain_render_hides_borders_when_toggled(self, monkeypatch):
        from linecast import maps
        gw, hc = 40, 12
        elev = [[500.0] * gw for _ in range(hc * 2)]
        terrain = maps.TerrainView(elev, None, None, None, None)
        monkeypatch.setattr(maps, "_get_elevation", lambda *a: terrain)

        class FakeBasemap:
            dots = [[0] * gw for _ in range(hc)]
            color = [[None] * gw for _ in range(hc)]
            # clear of the centre crosshair's cell
            dots[hc // 2][gw // 2 + 5] = 0x07
            color[hc // 2][gw // 2 + 5] = maps.BORDER

            def city_overlays(self, lang="en"):
                return {}

        monkeypatch.setattr(maps, "_get_basemap",
                            lambda *a: FakeBasemap())
        bbox = (-70.5, 43.5, -69.5, 44.5)
        args = (bbox, gw, hc, True, (0, 0), None, None, None, None,
                "en", None)
        on, *_rest = maps._render_terrain(*args, show_labels=True)
        off, *_rest = maps._render_terrain(*args, show_labels=False)
        assert any(chr(0x2800 + 0x07) in line for line in on)
        assert not any(chr(0x2800 + 0x07) in line for line in off)


class TestCities:
    def test_labels_stay_on_screen_and_visible_side(self):
        overlays = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22)
        assert overlays  # the Atlantic hemisphere has cities
        for (col, row) in overlays:
            assert 0 <= col < 80 and 0 <= row < 22

    def test_hidden_hemisphere_has_different_cities(self):
        near = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22)
        far = _globe.city_overlays(-20.0, 150.0, 125.0, 80, 22)
        near_dots = {p for p, (ch, _c) in near.items() if ch == "•"}
        far_dots = {p for p, (ch, _c) in far.items() if ch == "•"}
        assert near_dots != far_dots
