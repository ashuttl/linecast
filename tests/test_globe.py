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


def _varied_canvas(size=64):
    """A one-tile world of rolling terrain with a transparent hole.

    Elevation varies with both axes so a sampler that swapped its taps
    would be caught; the hole exercises the weight-only-what-has-data
    rule and its zero-weight corner."""
    canvas = bytearray()
    for y in range(size):
        for x in range(size):
            meters = 3000.0 * math.sin(x / 5.0) * math.cos(y / 7.0)
            v = int(meters + 32768)
            alpha = 0 if (20 <= x < 26 and 30 <= y < 34) else 255
            canvas += bytes((v >> 8, v & 0xFF, (x * 37 + y * 11) & 0xFF,
                             alpha))
    return (canvas, size, size, 0, 0, size)


def _reference_elevation(lls, canvas):
    """_globe.elevation as it was before the straight-line rewrite."""
    from linecast._elevation import decode_meters
    from linecast._radar_tiles import _lonlat_to_world
    canvas, cw, ch, org_x, org_y, world = canvas
    grid = []
    for ll_row in lls:
        row = []
        for ll in ll_row:
            if ll is None:
                row.append(None)
                continue
            lat = min(85.05, max(-85.05, ll[0]))
            wx, wy = _lonlat_to_world(ll[1], lat)
            fx = wx * world - org_x - 0.5
            fy = min(max(wy * world - org_y - 0.5, 0.0), ch - 1.0)
            x0 = int(fx) % cw
            x1 = (x0 + 1) % cw
            y0 = int(fy)
            y1 = min(y0 + 1, ch - 1)
            tx, ty = fx - int(fx), fy - y0
            vals = []
            for yy, wgt_y in ((y0, 1.0 - ty), (y1, ty)):
                base = yy * cw * 4
                for xx, wgt in ((x0, wgt_y * (1.0 - tx)),
                                (x1, wgt_y * tx)):
                    j = base + xx * 4
                    if canvas[j + 3]:
                        vals.append((decode_meters(
                            canvas[j], canvas[j + 1], canvas[j + 2]), wgt))
            if not vals:
                row.append(None)
            else:
                wsum = sum(wgt for _, wgt in vals)
                row.append(sum(v * wgt for v, wgt in vals) / wsum
                           if wsum > 0 else vals[0][0])
        grid.append(row)
    return grid


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

    def test_matches_the_reference_sampler(self, monkeypatch):
        # the straight-line sampler is the old one with its temporaries
        # written out; it must agree with that reference to the metre's
        # last bits, holes and the pole clamp included
        canvas = _varied_canvas()
        monkeypatch.setattr(_globe, "_world_canvas",
                            lambda z, timeout: canvas)
        lls, _zs, _rhos = _globe.geometry(70.0, 160.0, 120.0, 48, 36)
        got = _globe.elevation(lls, 120.0, 36)
        want = _reference_elevation(lls, canvas)
        assert len(got) == len(want)
        seen = 0
        for g_row, w_row in zip(got, want):
            for g, w in zip(g_row, w_row):
                if w is None:
                    assert g is None
                    continue
                seen += 1
                assert abs(g - w) < 1e-9
        assert seen > 300

    def test_zero_weight_beside_a_hole_keeps_the_neighbour(self,
                                                          monkeypatch):
        # a sample exactly on pixel (x0, y0) weights its three other taps
        # at zero; when only those carry data, the sampler returns the
        # first of them undiluted rather than nothing (as it always has)
        size = 8

        def px(meters, alpha=255):
            v = int(meters + 32768)
            return bytes((v >> 8, v & 0xFF, 0, alpha))

        canvas = bytearray(px(500.0) * (size * size))
        canvas[(0 * size + 2) * 4:(0 * size + 3) * 4] = px(0.0, alpha=0)
        canvas[(0 * size + 3) * 4:(0 * size + 4) * 4] = px(700.0)
        canvas[(1 * size + 2) * 4:(1 * size + 3) * 4] = px(900.0)
        hit = (canvas, size, size, 0, 0, size)
        # lon -67.5 lands on column 2 exactly (tx == 0); a latitude past
        # the mercator edge clamps to the top row exactly (ty == 0)
        lls = [[(89.0, -67.5)]]
        (tap,) = _globe.bilinear_taps(lls[0], hit)
        assert tap[0] == (0 * size + 2) * 4 and tap[4:] == (0.0, 0.0)
        monkeypatch.setattr(_globe, "_world_canvas", lambda z, t: hit)
        assert _globe.elevation(lls, 125.0, size) == [[700.0]]
        assert _reference_elevation(lls, hit) == [[700.0]]

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

    def test_limb_lls_lie_on_the_visible_limb(self):
        lat0, lon0, zoom, w, h = 37.0, -100.0, 125.0, 80, 44
        _lls, _zs, rhos = _globe.geometry(lat0, lon0, zoom, w, h)
        atmo = _globe.atmosphere(rhos, zoom, h)
        glow = _globe.limb_lls(lat0, lon0, zoom, w, h, atmo)
        seen = 0
        for a_row, g_row in zip(atmo, glow):
            for a, ll in zip(a_row, g_row):
                if a <= 0.0:
                    assert ll is None
                    continue
                seen += 1
                ux, uy, cos_c = _globe.forward(ll[0], ll[1], lat0, lon0)
                assert abs(math.hypot(ux, uy) - 1.0) < 1e-9
                assert abs(cos_c) < 1e-9
        assert seen > 0

    def test_gate_glow_keeps_day_dims_night(self):
        from linecast import _globe_now
        # sun over 90E, view centred on 0: east limb noon, west midnight
        lat0, lon0, zoom, w, h = 0.0, 0.0, 125.0, 80, 48
        _lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, w, h)
        atmo = _globe.atmosphere(rhos, zoom, h)
        glow = _globe.limb_lls(lat0, lon0, zoom, w, h, atmo)
        bg = (30, 32, 48)
        buf = [[bg] * w for _ in range(h)]
        _globe.shade_buffer(buf, zs, atmo, bg)
        before = [row[:] for row in buf]
        day = _globe_now.daylight(glow, (0.0, 90.0))
        _globe.gate_glow(buf, atmo, day, bg)
        y = h // 2
        east = max(x for x in range(w) if atmo[y][x] > 0.5)
        west = min(x for x in range(w) if atmo[y][x] > 0.5)
        assert buf[y][east] == before[y][east]  # noon limb: untouched
        night = buf[y][west]
        assert night != before[y][west]  # midnight limb: gated
        # ...down to a whisper above background, leaning airglow green
        assert all(abs(c - b) <= 6 for c, b in zip(night, bg))
        assert night[1] - bg[1] >= night[2] - bg[2]


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

    def test_globe_render_hides_linework_when_toggled(self, monkeypatch):
        from linecast import maps
        gw, hc = 40, 12
        lls, zs, rhos = _globe.geometry(20.0, -30.0, 125.0, gw, hc * 2)
        elev = [[None if ll is None else 500.0 for ll in row]
                for row in lls]
        borders = maps.DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
        # near the disk centre, but clear of the centre crosshair's cell
        borders._set_dot(gw + 4, hc * 2, maps.BORDER_STROKE)
        coast = [[0] * gw for _ in range(hc)]
        coast[hc // 2][gw // 2 - 3] = 0x10
        view = _globe.GlobeView(elev, coast, zs,
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
        border = chr(0x2800 + borders.dots[hc // 2][gw // 2 + 2])
        for stroke in (border, chr(0x2810)):
            assert any(stroke in line for line in on)
            assert not any(stroke in line for line in off)

    def test_terrain_render_hides_linework_when_toggled(self, monkeypatch):
        from linecast import maps
        gw, hc = 40, 12
        elev = [[500.0] * gw for _ in range(hc * 2)]
        coast = [[0] * gw for _ in range(hc)]
        coast[hc // 2][gw // 2 - 5] = 0x10
        rivers = maps.DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
        rivers._set_dot((gw // 2 - 8) * 2, hc // 2 * 4 + 1, (0, 0, 255))
        terrain = maps.TerrainView(elev, coast, None, rivers, None)
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
        for stroke in (chr(0x2807), chr(0x2810), chr(0x2802)):
            assert any(stroke in line for line in on)
            assert not any(stroke in line for line in off)


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
