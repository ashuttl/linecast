"""Tests for the braille geography basemap layer.

Basemap loads real vendored data lazily and caches it in the module-level
_DATA global. Tests that need synthetic data monkeypatch that global directly
and restore whatever was there beforehand, so other tests (which rely on the
real data/basemap.json) aren't affected regardless of test order.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import linecast._radar_basemap as basemap_mod
from linecast._radar_basemap import (
    Basemap, _project, marine_region, nearest_city,
    SEA, COAST, CITY, CITY_LABEL,
)


class TestProject:
    BBOX = (-10.0, -5.0, 10.0, 5.0)  # minlon, minlat, maxlon, maxlat
    W, H = 100, 50

    def test_top_left_corner(self):
        x, y = _project(-10.0, 5.0, self.BBOX, self.W, self.H)
        assert x == 0
        assert y == 0

    def test_bottom_right_corner(self):
        x, y = _project(10.0, -5.0, self.BBOX, self.W, self.H)
        assert x == self.W
        assert y == self.H

    def test_center(self):
        x, y = _project(0.0, 0.0, self.BBOX, self.W, self.H)
        assert x == self.W / 2
        assert y == self.H / 2


class TestBasemapSyntheticData:
    """Uses a small synthetic land/coast/city dataset instead of the real
    (large, whole-world) vendored basemap.json.
    """

    BBOX = (-5.0, -5.0, 5.0, 5.0)
    GRAPH_W = 10
    HEIGHT_CELLS = 5

    def setup_method(self):
        self._original_data = basemap_mod._DATA
        # one square land polygon spanning lon/lat [-2,2]x[-2,2] (closed ring);
        # its outline doubles as the coastline stroke at build time
        land_ring = [(-2, -2), (2, -2), (2, 2), (-2, 2), (-2, -2)]
        cities = [
            [0.0, 0.0, 1_000_000, "Testville"],   # inside bbox
            [100.0, 100.0, 5_000_000, "FarCity"],  # outside bbox
        ]
        basemap_mod._DATA = {
            "land": [[land_ring]],
            "borders": [],
            "cities": cities,
        }

    def teardown_method(self):
        basemap_mod._DATA = self._original_data

    def _build(self):
        return Basemap(self.BBOX, self.GRAPH_W, self.HEIGHT_CELLS)

    def test_land_interior_has_no_sea_stipple(self):
        bm = self._build()
        # lon=0, lat=0 is deep inside the land square -> dot (10,10) ->
        # cell (dot_x//2, dot_y//4) = (5, 2)
        assert bm.dots[2][5] == 0
        assert bm.color[2][5] is None

    def test_sea_outside_land_has_stipple(self):
        bm = self._build()
        # lon=4, lat=4 is inside the bbox but far from the land square
        # -> dot (18, 2) -> cell (9, 0)
        assert bm.dots[0][9] != 0
        assert bm.color[0][9] == SEA

    def test_land_outline_sets_coast_color(self):
        bm = self._build()
        # lon=0, lat=2 sits on the land square's top edge, whose outline is
        # the coastline stroke -> dot (10, 6) -> cell (5, 1)
        assert bm.dots[1][5] != 0
        assert bm.color[1][5] == COAST

    def test_city_overlays_marker_and_label(self):
        bm = self._build()
        overlays = bm.city_overlays(max_cities=1)
        # Testville projects to cell col=5, row=2 (cell resolution, not dots)
        assert overlays[(5, 2)] == ("•", CITY)
        assert overlays[(6, 2)] == ("T", CITY_LABEL)
        assert overlays[(7, 2)] == ("e", CITY_LABEL)
        assert overlays[(8, 2)] == ("s", CITY_LABEL)
        assert overlays[(9, 2)] == ("t", CITY_LABEL)
        # column 10 would be the next label char but is out of graph_w (10)
        assert (10, 2) not in overlays

    def test_city_outside_bbox_excluded(self):
        bm = self._build()
        overlays = bm.city_overlays(max_cities=8)
        # FarCity (lon=100, lat=100) is outside the bbox, so no marker/label
        # for it should appear anywhere, regardless of max_cities.
        assert ("F", CITY_LABEL) not in overlays.values()
        # only Testville's marker + up to 4 label letters ("Test") exist
        assert len(overlays) == 5

    def test_data_restored_after_teardown_is_isolated_per_test(self):
        # sanity: synthetic data is active only inside this class's tests
        assert basemap_mod._DATA["cities"][0][3] == "Testville"


class TestCityLocalization:
    """Localized placenames on the map, incl. CJK double-width alignment."""

    BBOX = (-5.0, -5.0, 5.0, 5.0)
    GRAPH_W = 10
    HEIGHT_CELLS = 5

    def setup_method(self):
        self._original_data = basemap_mod._DATA
        basemap_mod._DATA = {
            "land": [], "borders": [],
            # default Latin name + a translations dict (5th element)
            "cities": [[0.0, 0.0, 1_000_000, "Beijing",
                        {"zh": "北京", "fr": "Pékin"}]],
        }

    def teardown_method(self):
        basemap_mod._DATA = self._original_data

    def _build(self):
        return Basemap(self.BBOX, self.GRAPH_W, self.HEIGHT_CELLS)

    def test_translation_used_when_present(self):
        ov = self._build().city_overlays(max_cities=1, lang="fr")
        assert ov[(5, 2)] == ("•", CITY)
        # "Pékin" — the 5th char runs off the 10-wide grid, leaving "Péki"
        assert "".join(ov[(6 + i, 2)][0] for i in range(4)) == "Péki"
        assert (10, 2) not in ov

    def test_falls_back_to_default_name(self):
        # no translation for German -> default Latin name
        ov = self._build().city_overlays(max_cities=1, lang="de")
        assert ov[(6, 2)] == ("B", CITY_LABEL)

    def test_default_when_no_translations_dict(self):
        basemap_mod._DATA["cities"] = [[0.0, 0.0, 1_000_000, "Plainville"]]
        ov = self._build().city_overlays(max_cities=1, lang="zh")
        assert ov[(6, 2)] == ("P", CITY_LABEL)

    def test_cjk_reserves_trailing_column(self):
        ov = self._build().city_overlays(max_cities=1, lang="zh")
        # "北京" -> wide glyph then a consumed sentinel, twice
        assert ov[(6, 2)] == ("北", CITY_LABEL)
        assert ov[(7, 2)] == ("", None)   # sentinel: covered by 北
        assert ov[(8, 2)] == ("京", CITY_LABEL)
        assert ov[(9, 2)] == ("", None)   # sentinel: covered by 京

    def test_cjk_rows_stay_column_aligned(self):
        from linecast._radar_render import compose
        from linecast._framebuffer import visible_len
        bm = self._build()
        ov = bm.city_overlays(max_cities=1, lang="zh")
        radar = [[None] * self.GRAPH_W for _ in range(self.HEIGHT_CELLS * 2)]
        lines = compose(bm, radar, ov, self.GRAPH_W, self.HEIGHT_CELLS)
        # every line must occupy exactly graph_w display columns despite the
        # double-width CJK glyphs on the labelled row
        assert all(visible_len(ln) == self.GRAPH_W for ln in lines)


class TestNearestCity:
    """nearest_city against a synthetic city list (same isolation pattern
    as TestBasemapSyntheticData)."""

    def setup_method(self):
        self._original_data = basemap_mod._DATA
        basemap_mod._DATA = {
            "land": [],
            "borders": [],
            "cities": [
                [0.0, 0.0, 1_000_000, "Origin"],
                [10.0, 0.0, 5_000_000, "East City"],
                [179.5, 0.0, 2_000_000, "Dateline West"],
            ],
        }

    def teardown_method(self):
        basemap_mod._DATA = self._original_data

    def test_picks_closest_regardless_of_population(self):
        name, dist_km, _ = nearest_city(0.5, 0.5)
        assert name == "Origin"
        assert 70 < dist_km < 90  # ~78.6 km for 0.5deg x 0.5deg at equator

    def test_bearing_is_from_city_to_point(self):
        # due north of Origin -> bearing ~0
        _, _, bearing = nearest_city(1.0, 0.0)
        assert bearing < 1 or bearing > 359
        # due east of Origin -> bearing ~90
        _, _, bearing = nearest_city(0.0, 1.0)
        assert 89 < bearing < 91

    def test_dateline_wraparound(self):
        # -179.5 lon is 1 degree from Dateline West across the antimeridian,
        # far from everything else
        name, dist_km, _ = nearest_city(0.0, -179.5)
        assert name == "Dateline West"
        assert dist_km < 150

    def test_empty_city_list_returns_none(self):
        basemap_mod._DATA["cities"] = []
        assert nearest_city(0.0, 0.0) is None


class TestMarineRegion:
    """marine_region against synthetic water bodies."""

    def setup_method(self):
        self._original_data = basemap_mod._DATA
        square = lambda x0, y0, x1, y1: [
            [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        basemap_mod._DATA = {
            "land": [], "borders": [], "cities": [],
            # smallest-area-first, as the builder writes it; Big Sea has an
            # island hole (second ring) in its north-east corner
            "marine": [
                ["Little Gulf", 4.0, [square(0, 0, 2, 2)]],
                ["Big Sea", 100.0, [square(-5, -5, 5, 5),
                                    square(3, 3, 4, 4)]],
            ],
        }

    def teardown_method(self):
        basemap_mod._DATA = self._original_data

    def test_most_specific_name_wins(self):
        # (1, 1) is inside both; Little Gulf is listed first (smaller)
        assert marine_region(1.0, 1.0) == "Little Gulf"

    def test_enclosing_feature_outside_the_small_one(self):
        assert marine_region(-4.0, -4.0) == "Big Sea"

    def test_hole_is_outside(self):
        # (3.5, 3.5) sits in Big Sea's island hole (even-odd: 2 rings crossed)
        assert marine_region(3.5, 3.5) is None

    def test_outside_everything(self):
        assert marine_region(20.0, 20.0) is None


class TestVendoredDataLookups:
    """Guard the real vendored basemap data end-to-end."""

    def test_gulf_of_maine(self):
        assert marine_region(43.3, -68.4) == "Gulf of Maine"

    def test_open_atlantic(self):
        assert marine_region(35.0, -40.0) == "North Atlantic Ocean"

    def test_land_is_not_water(self):
        assert marine_region(42.36, -71.06) is None  # Boston

    def test_east_siberian_sea_survives_simplification(self):
        # regression: the old Douglas-Peucker dropped each split vertex, which
        # collapsed this sea's sparse 3-point northern boundary and left the
        # middle of it "outside"
        assert marine_region(75.0, 160.0) == "East Siberian Sea"

    def test_nearest_city_real_data(self):
        name, dist_km, bearing = nearest_city(42.6, -70.8)
        assert name == "Salem"
        assert 5 < dist_km < 20
        assert 20 < bearing < 70  # NE of Salem
