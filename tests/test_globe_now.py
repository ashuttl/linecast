"""Tests for the sky overlays: subsolar point, daylight, clouds, lights."""

from linecast import _globe_now
from linecast._scenes import Memo


class TestSubsolar:
    def test_equinox_noon_sun_over_the_meridian(self):
        # 2026-03-20 12:00 UTC — the sun stands near (0, 0)
        t = 1774008000
        lat, lon = _globe_now.subsolar(t)
        assert abs(lat) < 1.5
        assert abs(lon) < 3.0  # the equation of time is small in March

    def test_june_solstice_sun_over_the_tropic(self):
        # 2026-06-21 12:00 UTC
        t = 1782043200
        lat, _lon = _globe_now.subsolar(t)
        assert abs(lat - 23.4) < 1.0

    def test_evening_sun_stands_west(self):
        # 18:00 UTC puts solar noon three time zones west of Greenwich
        t = 1774008000 + 6 * 3600
        _lat, lon = _globe_now.subsolar(t)
        assert -95.0 < lon < -85.0


class TestDaylight:
    def test_noon_night_and_space(self):
        sun = (0.0, 0.0)
        lls = [[(0.0, 0.0), (0.0, 180.0), None]]
        (day,) = _globe_now.daylight(lls, sun)
        assert day[0] == 1.0
        assert day[1] == 0.0
        assert day[2] is None

    def test_the_terminator_is_a_band(self):
        sun = (0.0, 0.0)
        # the sun on the horizon: inside the twilight ramp, not a cliff
        (day,) = _globe_now.daylight([[(0.0, 90.0)]], sun)
        assert 0.0 < day[0] < 1.0


class TestFlatLls:
    def test_corners_read_the_bbox(self):
        lls = _globe_now.flat_lls((-10.0, 40.0, 10.0, 50.0), 4, 2)
        assert len(lls) == 2 and len(lls[0]) == 4
        lat, lon = lls[0][0]
        assert 47.5 == lat and -7.5 == lon
        lat, lon = lls[1][3]
        assert 42.5 == lat and 7.5 == lon


def _flat_canvas(alpha, size=256):
    buf = bytearray()
    for _ in range(size * size):
        buf += bytes((200, 200, 200, alpha))
    return (buf, size, size, 0, 0, size)


class TestClouds:
    def test_uniform_alpha_samples_uniformly(self):
        canvas = _flat_canvas(128)
        (row,) = _globe_now.clouds([[(45.0, -70.0), None]], canvas)
        assert abs(row[0] - 128 / 255.0) < 0.01
        assert row[1] == 0.0  # space is not weather


class TestCityLights:
    def test_globe_lights_land_on_the_near_side(self):
        lights = _globe_now.city_lights_globe(20.0, -30.0, 125.0, 80, 44)
        assert lights
        for (x, y), w in lights.items():
            assert 0 <= x < 80 and 0 <= y < 44
            assert 0.0 < w <= 1.0

    def test_same_view_is_served_from_the_memo(self, monkeypatch):
        monkeypatch.setattr(_globe_now, "_lights_cache",
                            Memo(keep=_globe_now._LIGHTS_KEEP))
        first = _globe_now.city_lights_globe(20.0, -30.0, 125.0, 80, 44)
        assert _globe_now.city_lights_globe(20.0, -30.0, 125.0, 80, 44) \
            is first
        for lon0 in (-31.0, -32.0, -33.0, -34.0):
            _globe_now.city_lights_globe(20.0, lon0, 125.0, 80, 44)
        assert len(_globe_now._lights_cache) == _globe_now._LIGHTS_KEEP


class TestApply:
    def test_day_leaves_the_ground_alone(self):
        buf = [[(90, 110, 60)]]
        _globe_now.apply(buf, [[1.0]], None, {})
        assert buf == [[(90, 110, 60)]]

    def test_night_dims_toward_blue(self):
        buf = [[(90, 110, 60)]]
        _globe_now.apply(buf, [[0.0]], None, {})
        r, g, b = buf[0][0]
        assert r < 90 and g < 110 and b < 60
        assert b / 60 > r / 90  # the floor leans blue

    def test_clouds_whiten_the_day(self):
        buf = [[(90, 110, 60)]]
        _globe_now.apply(buf, None, [[1.0]], {})
        r, g, b = buf[0][0]
        assert r > 200 and g > 200 and b > 200

    def test_night_clouds_stay_faintly_visible(self):
        clear = [[(90, 110, 60)]]
        cloudy = [[(90, 110, 60)]]
        _globe_now.apply(clear, [[0.0]], [[0.0]], {})
        _globe_now.apply(cloudy, [[0.0]], [[1.0]], {})
        assert sum(cloudy[0][0]) > sum(clear[0][0])

    def test_city_burns_through_the_night(self):
        buf = [[(20, 25, 35)]]
        _globe_now.apply(buf, [[0.0]], None, {(0, 0): 1.0})
        r, g, b = buf[0][0]
        assert r > 150 and r > b  # warm, not blue

    def test_a_higher_night_floor_keeps_more_of_the_ground(self):
        # the street planet's night: no lights to carry it, so the two
        # fills have to survive the dark themselves
        default = [[(90, 110, 60)]]
        street = [[(90, 110, 60)]]
        _globe_now.apply(default, [[0.0]], None, {})
        _globe_now.apply(street, [[0.0]], None, {},
                         night=_globe_now.NIGHT_STREET)
        assert sum(street[0][0]) > sum(default[0][0])
        assert sum(street[0][0]) < 90 + 110 + 60  # still night

    def test_the_street_floor_keeps_land_off_sea(self):
        # what the floor is for: a dark grey land and a black sea stay
        # two different colours after the terminator passes
        land, sea = [[(58, 62, 72)]], [[(7, 9, 14)]]
        for buf in (land, sea):
            _globe_now.apply(buf, [[0.0]], None, {},
                             night=_globe_now.NIGHT_STREET)
        assert sum(land[0][0]) - sum(sea[0][0]) > 30

    def test_daylit_city_stays_dark(self):
        buf = [[(90, 110, 60)]]
        _globe_now.apply(buf, [[1.0]], None, {(0, 0): 1.0})
        assert buf == [[(90, 110, 60)]]

    def test_none_pixels_survive(self):
        buf = [[None, (90, 110, 60)]]
        _globe_now.apply(buf, [[0.0, 0.0]], [[0.5, 0.5]], {(0, 0): 1.0})
        assert buf[0][0] is None


class TestRefresh:
    def _index(self, paths):
        return {"host": "https://example.invalid",
                "satellite": {"infrared": [{"time": 0, "path": p}
                                           for p in paths]}}

    def test_new_frame_stitches_and_repeat_is_free(self, monkeypatch):
        # patch tiles *through* _globe_now: after the test_oneline
        # sys.modules purge, a fresh `from linecast import _radar_tiles`
        # here would be a different module than the one it calls
        tiles = _globe_now.tiles
        monkeypatch.setattr(_globe_now, "_cloud",
                            {"stamp": None, "canvas": None, "checked": 0.0})
        monkeypatch.setattr(tiles, "fetch_index",
                            lambda prov, timeout=15: self._index(["/v2/s/1"]))
        monkeypatch.setattr(tiles, "_fetch_tile", lambda *a, **k: None)
        assert _globe_now.refresh(130.0, 208) is True
        assert _globe_now.peek() is not None
        assert not _globe_now.stale()
        assert _globe_now.refresh(130.0, 208) is False

    def test_no_satellite_section_keeps_calm(self, monkeypatch):
        tiles = _globe_now.tiles
        monkeypatch.setattr(_globe_now, "_cloud",
                            {"stamp": None, "canvas": None, "checked": 0.0})
        monkeypatch.setattr(tiles, "fetch_index",
                            lambda prov, timeout=15: {"host": "h"})
        assert _globe_now.refresh(130.0, 208) is False
        assert _globe_now.peek() is None


class TestPolarCap:
    def _cover(self, north=1.0, south=0.0):
        """Ring cover: a solid deck up north, clear skies down south."""
        n = [north] * _globe_now._CAP_SECT
        s = [south] * _globe_now._CAP_SECT
        return {True: (n, north), False: (s, south)}

    def test_clouds_fill_the_cap_and_fade_at_the_edge(self, monkeypatch):
        monkeypatch.setitem(_globe_now._cloud, "cover", self._cover())
        monkeypatch.setitem(_globe_now._cloud, "white", None)
        canvas = (bytes(4 * 4 * 4), 4, 4, 0, 0, 4)  # empty mosaic
        lls = [[(85.0, 0.0), (66.5, 0.0), (-85.0, 0.0), None]]
        out = _globe_now.clouds(lls, canvas)
        assert out[0][0] > 0.35     # deep in the cloudy cap: a deck
        assert out[0][1] == 0.0     # equatorward of the seeding: untouched
        assert out[0][2] == 0.0     # the clear hemisphere stays clear
        assert out[0][3] == 0.0     # off the disk

    def test_no_measure_leaves_the_mosaic_alone(self, monkeypatch):
        monkeypatch.setitem(_globe_now._cloud, "cover", None)
        canvas = (bytes(4 * 4 * 4), 4, 4, 0, 0, 4)
        out = _globe_now.clouds([[(85.0, 0.0)]], canvas)
        assert out[0][0] == 0.0

    def test_the_deck_is_billowed_not_flat(self, monkeypatch):
        # a solid deck must not paint one flat sheet: the noise gives
        # it grain, held under the mosaic's own white
        monkeypatch.setitem(_globe_now._cloud, "cover", self._cover())
        monkeypatch.setitem(_globe_now._cloud, "white", 0.6)
        canvas = (bytes(4 * 4 * 4), 4, 4, 0, 0, 4)
        lls = [[(80.0, -180.0 + k * 1.7) for k in range(200)]]
        (row,) = _globe_now.clouds(lls, canvas)
        assert max(row) - min(row) > 0.1
        assert max(row) <= 0.6 * 1.25 + 1e-9
        assert min(row) > 0.0

    def test_a_clear_ring_keeps_its_cap_clear(self, monkeypatch):
        # the noise invents texture, never cloud where the ring is dark
        monkeypatch.setitem(_globe_now._cloud, "cover",
                            self._cover(north=0.0))
        canvas = (bytes(4 * 4 * 4), 4, 4, 0, 0, 4)
        lls = [[(74.0 + k % 15, -180.0 + k * 3.7) for k in range(100)]]
        (row,) = _globe_now.clouds(lls, canvas)
        assert max(row) == 0.0

    def test_the_cap_continues_the_ring_sector_by_sector(self, monkeypatch):
        # a cloudy west and a clear east, and the cap follows each
        half = _globe_now._CAP_SECT // 2
        ring = [1.0] * half + [0.0] * half
        monkeypatch.setitem(_globe_now._cloud, "cover",
                            {True: (ring, 0.5), False: (ring, 0.5)})
        monkeypatch.setitem(_globe_now._cloud, "white", 0.6)
        canvas = (bytes(4 * 4 * 4), 4, 4, 0, 0, 4)
        cloudy = [[(75.0, -90.0 + k * 0.7) for k in range(100)]]
        clear = [[(75.0, 90.0 + k * 0.7) for k in range(100)]]
        (cl,) = _globe_now.clouds(cloudy, canvas)
        (cr,) = _globe_now.clouds(clear, canvas)
        assert sum(cl) / len(cl) > 0.3
        assert max(cr) == 0.0

    def test_noise_is_stable_and_bounded(self):
        tab = _globe_now._noise_grid()
        assert len(tab) == _globe_now._NOISE_ROWS * _globe_now._NOISE_COLS
        assert min(tab) >= 0.0 and max(tab) <= 1.0
        assert _globe_now._noise_grid() is tab

    def test_the_sphere_noise_has_no_antimeridian_seam(self):
        assert abs(_globe_now._fbm(80.0, -180.0)
                   - _globe_now._fbm(80.0, 180.0)) < 1e-6

    def test_the_pole_wears_billows_not_a_pinch(self):
        # every point within a tenth of a degree of the pole is nearly
        # the same point in space, so the noise must nearly agree —
        # the failure mode this guards is a texture anchored to the
        # graticule, whose longitudes pinch to slivers at 90°
        vals = [_globe_now._fbm(89.9, -180.0 + k * 10.0)
                for k in range(36)]
        assert max(vals) - min(vals) < 0.15

    def test_white_follows_the_mosaic(self):
        size = 256
        cloudy = (bytearray(bytes((200, 200, 200, 180)) * size * size),
                  size, size, 0, 0, size)
        w = _globe_now._mosaic_white(cloudy)
        assert abs(w - 180 / 255.0) < 0.02
        empty = (bytearray(size * size * 4), size, size, 0, 0, size)
        assert _globe_now._mosaic_white(empty) is None

    def test_ring_cover_reads_the_band(self):
        size = 256
        cloudy = (bytearray(bytes((200, 200, 200, 180)) * size * size),
                  size, size, 0, 0, size)
        cover = _globe_now._ring_cover(cloudy, 180 / 255.0)
        for northern in (True, False):
            sectors, mean = cover[northern]
            assert len(sectors) == _globe_now._CAP_SECT
            assert all(abs(s - 1.0) < 1e-6 for s in sectors)
            assert abs(mean - 1.0) < 1e-6
        empty = (bytearray(size * size * 4), size, size, 0, 0, size)
        assert _globe_now._ring_cover(empty, 0.7)[True][1] == 0.0


class TestInkDusk:
    def test_ink_fades_by_the_fills_night_factor(self):
        # a 2x2-cell view: left column at the subsolar point (noon),
        # right column at its antipode (night); space on the top row
        sun = (0.0, 0.0)
        lls = [[None, None], [None, None],
               [(0.0, 0.0), (0.0, 180.0)], [(0.0, 0.0), (0.0, 180.0)]]
        night = (0.5, 0.5, 0.5)
        dusk = _globe_now.ink_dusk(lls, sun, night, 2, 2)
        assert dusk[0] == [None, None]           # space is not dark
        assert dusk[1][0] is None                # noon keeps the ink
        assert dusk[1][1] == (0.5, 0.5, 0.5)     # night takes the floor
        assert _globe_now.dim_ink((100, 140, 180), dusk[1][1]) == (50, 70, 90)
        assert _globe_now.dim_ink((100, 140, 180), None) == (100, 140, 180)
        assert _globe_now.dim_ink(None, dusk[1][1]) is None

