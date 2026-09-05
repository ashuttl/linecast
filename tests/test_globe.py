"""The orthographic globe: projection math, sampling, and hand-off."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe
from linecast._scenes import Memo


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


class TestHandOff:
    def test_equator_hands_off_at_zoom_deg(self):
        assert not _globe.is_globe(_globe.ZOOM_DEG - 1, 0.0)
        assert _globe.is_globe(_globe.ZOOM_DEG, 0.0)

    def test_poles_hand_off_by_width(self):
        # a 21° window at the Ross Sea is 220° of longitude wide — it
        # ran off the antimeridian as a flat map, so it goes round
        assert not _globe.is_globe(21.0, 0.0)
        assert _globe.is_globe(21.0, -78.0)
        assert not _globe.is_globe(7.0, -78.0)

    def test_reaching_past_the_tiles_hands_off(self):
        # the Mercator tiles end at the 85th parallel
        assert _globe.is_globe(3.0, -84.0)
        assert not _globe.is_globe(3.0, -80.0)


class TestGeometryCache:
    def test_cached_view_matches_a_fresh_projection(self, monkeypatch):
        monkeypatch.setattr(_globe, "_geometry_cache", Memo(keep=_globe._GEOMETRY_KEEP))
        lat0, zoom, w, h = 37.0, 90.0, 40, 40
        want = _globe.geometry(lat0, -100.0, zoom, w, h)
        # a second longitude over the same grid comes from the cache;
        # a fresh projection of it must agree exactly
        cached = _globe.geometry(lat0, 55.0, zoom, w, h)
        assert len(_globe._geometry_cache) == 1
        monkeypatch.setattr(_globe, "_geometry_cache", Memo(keep=_globe._GEOMETRY_KEEP))
        fresh = _globe.geometry(lat0, 55.0, zoom, w, h)
        assert cached[0] == fresh[0]
        assert cached[1] == fresh[1] and cached[2] == fresh[2]
        assert want[1] == fresh[1]  # zs never depended on lon0

    def test_offset_wraps_across_the_antimeridian(self, monkeypatch):
        monkeypatch.setattr(_globe, "_geometry_cache", Memo(keep=_globe._GEOMETRY_KEEP))
        _globe.geometry(0.0, 0.0, 125.0, 40, 40)
        lls, _zs, _rhos = _globe.geometry(0.0, 175.0, 125.0, 40, 40)
        lons = [ll[1] for row in lls for ll in row if ll is not None]
        assert all(-180.0 <= lon <= 180.0 for lon in lons)
        assert min(lons) < -170.0 and max(lons) > 170.0

    def test_cache_stays_small(self, monkeypatch):
        monkeypatch.setattr(_globe, "_geometry_cache", Memo(keep=_globe._GEOMETRY_KEEP))
        for lat0 in range(-40, 50, 10):
            _globe.geometry(float(lat0), 0.0, 125.0, 8, 8)
        assert len(_globe._geometry_cache) == _globe._GEOMETRY_KEEP


class TestMemoRaces:
    """The view workers share these memos; concurrent misses must not
    trip on each other's eviction."""

    @staticmethod
    def _hammer(fn, rounds=400):
        import random
        import threading
        errs = []

        def run(seed):
            rnd = random.Random(seed)
            try:
                for _ in range(rounds):
                    fn(rnd)
            except Exception as exc:  # noqa: BLE001 - the race is the point
                errs.append(repr(exc))

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            ts = [threading.Thread(target=run, args=(i,)) for i in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            sys.setswitchinterval(old)
        assert errs == []

    def test_geometry(self):
        self._hammer(lambda rnd: _globe.geometry(
            rnd.randint(-80, 80), 0.0, 60.0, 6, 4))

    @staticmethod
    def _few_cities(monkeypatch, module):
        # placement walks every city; a few dozen keep a miss cheap
        small = dict(module._load_data())
        small["cities"] = small["cities"][:40]
        monkeypatch.setattr(module, "_load_data", lambda: small)

    def test_city_overlays(self, monkeypatch):
        self._few_cities(monkeypatch, _globe)
        self._hammer(lambda rnd: _globe.city_overlays(
            rnd.randint(-80, 80), 0.0, 60.0, 12, 6), rounds=60)

    def test_city_lights(self, monkeypatch):
        from linecast import _globe_now
        self._few_cities(monkeypatch, _globe_now)
        self._hammer(lambda rnd: _globe_now.city_lights_globe(
            rnd.randint(-80, 80), 0.0, 60.0, 12, 12), rounds=60)


class TestWrapLon:
    def test_one_turn_either_way(self):
        from linecast._geo import wrap_lon
        assert wrap_lon(190.0) == -170.0
        assert wrap_lon(-190.0) == 170.0
        assert wrap_lon(180.0) == 180.0
        assert wrap_lon(-180.0) == -180.0
        assert wrap_lon(12.5) == 12.5

    def test_geometry_lon_stays_in_range_across_the_antimeridian(self):
        lls, _zs, _rhos = _globe.geometry(0.0, 179.0, 125.0, 40, 40)
        lons = [ll[1] for row in lls for ll in row if ll is not None]
        assert lons and all(-180.0 <= lon <= 180.0 for lon in lons)
        assert min(lons) < -170.0 and max(lons) > 170.0


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
        monkeypatch.setattr(_globe, "_canvas_cache", Memo(keep=1))
        zoom, h = 125.0, 44 * 4
        assert not _globe.warm(zoom, h)
        _globe._canvas_cache.put(_globe._source_zoom(zoom, h), object())
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


def _lake_square(lat, lon, half):
    """One square lake, as the vendored data spells a polygon."""
    return [[[(lon - half, lat - half), (lon + half, lat - half),
              (lon + half, lat + half), (lon - half, lat + half),
              (lon - half, lat - half)]]]


class TestLakes:
    # a planet-scale view over the Great Lakes, at the grid the fine
    # elevation samples use: two dots per cell each way
    VIEW = (45.0, -85.0, 82.0, 264, 164)

    def _wet(self, mask, lat, lon):
        lat0, lon0, zoom, dw, dh = self.VIEW
        ux, uy, cos_c = _globe.forward(lat, lon, lat0, lon0)
        r = _globe._radius(zoom, dh)
        return bool(mask[int(dh / 2 - uy * r)][int(dw / 2 + ux * r)])

    def test_the_great_lakes_are_water_and_michigan_is_not(self):
        mask = _globe.lake_mask(*self.VIEW)
        for lat, lon in ((47.7, -87.5), (44.0, -87.0), (44.8, -82.4),
                         (42.2, -81.2), (43.7, -77.9)):
            assert self._wet(mask, lat, lon)
        # the land the elevation data reports at the same height, a
        # dot or more clear of any shore
        for lat, lon in ((42.0, -93.6), (38.0, -85.0), (41.0, -100.0)):
            assert not self._wet(mask, lat, lon)

    def test_a_lake_on_the_far_side_is_not_drawn(self, monkeypatch):
        monkeypatch.setattr(_globe, "_LAKE_TRIG", (None, None))
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"lakes": _lake_square(-45.0, 95.0, 4.0)})
        assert _globe.lake_mask(*self.VIEW) is None

    def test_a_pond_under_a_dot_is_not_drawn(self, monkeypatch):
        monkeypatch.setattr(_globe, "_LAKE_TRIG", (None, None))
        lat0, lon0 = self.VIEW[0], self.VIEW[1]
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"lakes": _lake_square(lat0, lon0, 0.02)})
        assert _globe.lake_mask(*self.VIEW) is None
        # the same pond an order of magnitude wider does draw
        monkeypatch.setattr(_globe, "_LAKE_TRIG", (None, None))
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"lakes": _lake_square(lat0, lon0, 0.5)})
        mask = _globe.lake_mask(*self.VIEW)
        assert self._wet(mask, lat0, lon0)

    def test_an_island_in_a_lake_stays_dry(self, monkeypatch):
        monkeypatch.setattr(_globe, "_LAKE_TRIG", (None, None))
        lat0, lon0 = self.VIEW[0], self.VIEW[1]
        rings = (_lake_square(lat0, lon0, 4.0)[0]
                 + _lake_square(lat0, lon0, 1.0)[0])
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"lakes": [rings]})
        mask = _globe.lake_mask(*self.VIEW)
        assert self._wet(mask, lat0 + 2.5, lon0)   # the lake
        assert not self._wet(mask, lat0, lon0)     # its island

    def test_trig_follows_the_data(self, monkeypatch):
        monkeypatch.setattr(_globe, "_LAKE_TRIG", (None, None))
        before = _globe._lake_trig()
        assert _globe._lake_trig() is before  # same data: same trig
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"lakes": _lake_square(0.0, 0.0, 1.0)})
        after = _globe._lake_trig()
        assert after is not before and len(after) == 1

    def test_street_fills_paint_a_lake_as_water(self):
        elev = [[500.0, 500.0], [500.0, None]]
        wet = [[0, 1], [1, 0]]
        buf = _globe.fill_buffer(elev, (1, 1, 1), (9, 9, 9), (0, 0, 0), wet)
        # inland water takes the sea's fill, at either sign and over a
        # hole in the elevation data
        assert buf == [[(9, 9, 9), (1, 1, 1)], [(1, 1, 1), (0, 0, 0)]]


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
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: view)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (gw, hc + 2))
        bbox = (-31.0, -42.5, -29.0, 82.5)  # centre (20, -30), zoom 125
        args = (bbox, gw, hc, True, False, None, (None, None, None),
                "en", lambda: None)
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
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: view)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (gw, hc + 2))
        monkeypatch.setattr(_globe, "city_overlays", lambda *a, **k: {})
        bbox = (-31.0, -42.5, -29.0, 82.5)
        args = (bbox, gw, hc, True, False, None, (None, None, None),
                "en", lambda: None)
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
        monkeypatch.setattr(maps, "_get_elevation", lambda *a, **k: terrain)

        class FakeBasemap:
            dots = [[0] * gw for _ in range(hc)]
            color = [[None] * gw for _ in range(hc)]
            # clear of the centre crosshair's cell
            dots[hc // 2][gw // 2 + 5] = 0x07
            color[hc // 2][gw // 2 + 5] = maps.BORDER

            def city_overlays(self, lang="en"):
                return {}

        monkeypatch.setattr(maps, "_get_basemap",
                            lambda *a, **k: FakeBasemap())
        bbox = (-70.5, 43.5, -69.5, 44.5)
        args = (bbox, gw, hc, True, False, None, (None, None, None),
                "en", lambda: None)
        on, *_rest = maps._render_terrain(*args, show_labels=True)
        off, *_rest = maps._render_terrain(*args, show_labels=False)
        for stroke in (chr(0x2807), chr(0x2810), chr(0x2802)):
            assert any(stroke in line for line in on)
            assert not any(stroke in line for line in off)


def _reference_border_layer(lat0, lon0, zoom, gw, hc, color):
    """border_layer as it was before the trig was hoisted."""
    from linecast._radar_basemap import DotLayer, _load_data
    layer = DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
    r = _globe._radius(zoom, hc * 4)
    cx, cy = gw * 2 / 2.0, hc * 4 / 2.0
    for coords in _load_data()["borders"]:
        prev = None
        for lon, lat in coords:
            ux, uy, cos_c = _globe.forward(lat, lon, lat0, lon0)
            if cos_c <= 0.02:
                prev = None
                continue
            p = (cx + ux * r, cy - uy * r, ux, uy, cos_c)
            if prev is not None:
                arc = prev[2] * ux + prev[3] * uy + prev[4] * cos_c
                if arc > 0.34:
                    layer._dot_line(prev[0], prev[1], p[0], p[1], color)
            prev = p
    return layer


class TestBorders:
    def test_hoisted_trig_strokes_the_same_dots(self):
        ink = (1, 2, 3)
        for lat0, lon0 in ((44.0, -70.0), (-30.0, 150.0), (70.0, 179.5)):
            got = _globe.border_layer(lat0, lon0, 125.0, 80, 22, ink)
            want = _reference_border_layer(lat0, lon0, 125.0, 80, 22, ink)
            assert got.dots == want.dots
            assert got.color == want.color
        assert any(v for row in got.dots for v in row)

    def test_trig_follows_the_data(self, monkeypatch):
        # patch the globals _globe's _load_data actually reads: after
        # the test_oneline sys.modules purge, the basemap module a fresh
        # import returns can be a different object from the one whose
        # function _globe imported
        monkeypatch.setattr(_globe, "_BORDER_TRIG", (None, None))
        before = _globe._border_trig()
        assert _globe._border_trig() is before  # same data: same trig
        monkeypatch.setitem(_globe._load_data.__globals__, "_DATA",
                            {"borders": [[(0.0, 0.0), (10.0, 10.0)]]})
        after = _globe._border_trig()
        assert after is not before and len(after) == 1


class TestStreetRegister:
    """City lights are terrain's, in either projection; and past the
    hand-off the street register paints its own two fills."""

    @staticmethod
    def _view(gw, hc):
        lls, zs, rhos = _globe.geometry(20.0, -30.0, 125.0, gw, hc * 2)
        elev = [[None if ll is None else 500.0 for ll in row]
                for row in lls]
        return _globe.GlobeView(elev, [[0] * gw for _ in range(hc)], zs,
                                _globe.atmosphere(rhos, 125.0, hc * 2),
                                None, None, lls)

    def _render(self, monkeypatch, street):
        from linecast import _globe_now, maps
        gw, hc = 40, 12
        asked = []
        monkeypatch.setattr(maps, "_get_globe",
                            lambda *a: self._view(gw, hc))
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (gw, hc + 2))
        monkeypatch.setattr(_globe, "city_overlays", lambda *a, **k: {})

        def lights(*a, **k):
            asked.append(a)
            return {}

        monkeypatch.setattr(_globe_now, "city_lights_globe", lights)
        bbox = (-31.0, -42.5, -29.0, 82.5)  # centre (20, -30), zoom 125
        maps._render_globe(bbox, gw, hc, True, False, None,
                           (None, None, None), "en", lambda: None,
                           street=street, sun=True)
        return asked

    def test_the_street_planet_asks_for_no_city_lights(self, monkeypatch):
        assert self._render(monkeypatch, street=True) == []

    def test_the_terrain_planet_still_lights_its_cities(self, monkeypatch):
        assert self._render(monkeypatch, street=False) != []

    def test_the_flat_street_map_asks_for_none_either(self, monkeypatch):
        from linecast import _globe_now, maps
        gw, hc = 40, 12
        asked, shaded = [], []

        def lights(*a, **k):
            asked.append(a)
            return {}

        monkeypatch.setattr(_globe_now, "city_lights_flat", lights)
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k:
                            (None, None, None))
        # no remembered frame to stand in: the bare ground is shaded
        from linecast import _maps_motion
        _maps_motion.forget()
        real = maps._shade_now
        monkeypatch.setattr(maps, "_shade_now", lambda *a, **k:
                            shaded.append((a, k)) or real(*a, **k))
        maps._render_street((-71.0, 43.0, -70.0, 44.0), gw, hc, False,
                            False, None, (None, None, None), "en",
                            lambda: None, sun=True)
        assert asked == []
        assert shaded[0][0][4] == {}           # the lights argument
        assert shaded[0][1]["night"] == _globe_now.NIGHT_STREET

    def test_the_street_planet_wears_the_street_map_fills(self):
        # crossing the hand-off changes the curvature and nothing
        # else: no separate globe pair in either theme
        from linecast import _maps_style
        for p in (_maps_style.PALETTE_DARK, _maps_style.PALETTE_LIGHT):
            assert "globe_water" not in p and "globe_ground" not in p
            assert p["water"] and p["ground"]


class TestCities:
    def test_labels_stay_on_screen_and_visible_side(self):
        overlays = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22)
        assert overlays  # the Atlantic hemisphere has cities
        for (col, row) in overlays:
            assert 0 <= col < 80 and 0 <= row < 22

    def test_same_view_is_served_from_the_memo(self, monkeypatch):
        monkeypatch.setattr(_globe, "_overlay_cache", Memo(keep=_globe._OVERLAY_KEEP))
        first = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22)
        assert _globe.city_overlays(20.0, -30.0, 125.0, 80, 22) is first
        other = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22, lang="fr")
        assert other is not first
        for lon0 in (-31.0, -32.0, -33.0, -34.0):
            _globe.city_overlays(20.0, lon0, 125.0, 80, 22)
        assert len(_globe._overlay_cache) == _globe._OVERLAY_KEEP

    def test_hidden_hemisphere_has_different_cities(self):
        near = _globe.city_overlays(20.0, -30.0, 125.0, 80, 22)
        far = _globe.city_overlays(-20.0, 150.0, 125.0, 80, 22)
        near_dots = {p for p, (ch, _c) in near.items() if ch == "•"}
        far_dots = {p for p, (ch, _c) in far.items() if ch == "•"}
        assert near_dots != far_dots
