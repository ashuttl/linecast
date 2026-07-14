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


class TestBasemapLakes:
    """Lakes are carved out of the land fill (their islands staying land via
    even-odd fill) and their shorelines stroked like coastline."""

    BBOX = (-5.0, -5.0, 5.0, 5.0)
    GRAPH_W = 10
    HEIGHT_CELLS = 5

    def setup_method(self):
        self._original_data = basemap_mod._DATA
        square = lambda x0, y0, x1, y1: [
            [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        basemap_mod._DATA = {
            # land spans [-4,4]^2; the lake [-2,2]^2 has an island [0.5,1.5]^2
            "land": [[square(-4, -4, 4, 4)]],
            "lakes": [[square(-2, -2, 2, 2), square(0.5, 1.5, 1.5, 0.5)]],
            "borders": [],
            "cities": [],
        }

    def teardown_method(self):
        basemap_mod._DATA = self._original_data

    def _build(self):
        return Basemap(self.BBOX, self.GRAPH_W, self.HEIGHT_CELLS)

    def test_lake_interior_gets_sea_stipple(self):
        bm = self._build()
        # lon=-1, lat=0.5 is open lake water (clear of shore and island)
        # -> dot (8, 9) -> cell (4, 2)
        assert bm.dots[2][4] != 0
        assert bm.color[2][4] == SEA

    def test_land_between_lake_and_coast_stays_empty(self):
        bm = self._build()
        # lon=-3, lat=3 is on land, between the lake and the outer coast
        # -> dot (4, 4) -> cell (2, 1)
        assert bm.dots[1][2] == 0
        assert bm.color[1][2] is None

    def test_lake_shoreline_stroked_as_coast(self):
        bm = self._build()
        # lon=0, lat=2 sits on the lake's northern shoreline
        # -> dot (10, 6) -> cell (5, 1)
        assert bm.dots[1][5] != 0
        assert bm.color[1][5] == COAST

    def test_island_in_lake_is_land_in_mask(self):
        bm = self._build()
        land = bm._sea_mask()
        assert land[8][12] == 1   # island centre (lon=1, lat=0.75)
        assert land[9][8] == 0    # open lake (lon=-1, lat=0.25)
        assert land[4][4] == 1    # mainland (lon=-3, lat=2.75)
        assert land[19][19] == 0  # open sea outside the land square


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

    def test_great_lakes_are_named(self):
        assert marine_region(44.0, -87.0) == "Lake Michigan"
        assert marine_region(47.5, -87.5) == "Lake Superior"

    def test_caspian_sea_named_via_marine_layer(self):
        # the Caspian is carved out of NE's *land* layer (not the lakes
        # layer), so it must keep resolving through the marine polys
        assert marine_region(42.0, 50.5) == "Caspian Sea"

    def test_lakeside_city_is_not_water(self):
        assert marine_region(41.88, -87.63) is None  # Chicago

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
