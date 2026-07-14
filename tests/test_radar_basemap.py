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
    Basemap, _project, SEA, COAST, CITY, CITY_LABEL,
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
        # one square land polygon spanning lon/lat [-2,2]x[-2,2] (closed ring)
        land_ring = [(-2, -2), (2, -2), (2, 2), (-2, 2), (-2, -2)]
        # a coastline north of the square, well clear of it
        coast_line = [(-2, 3), (2, 3)]
        cities = [
            [0.0, 0.0, 1_000_000, "Testville"],   # inside bbox
            [100.0, 100.0, 5_000_000, "FarCity"],  # outside bbox
        ]
        basemap_mod._DATA = {
            "land": [[land_ring]],
            "coast": [coast_line],
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
        # lon=4, lat=4 is inside the bbox but far from the land square and
        # coastline -> dot (18, 2) -> cell (9, 0)
        assert bm.dots[0][9] != 0
        assert bm.color[0][9] == SEA

    def test_coastline_sets_coast_color(self):
        bm = self._build()
        # lon=0, lat=3 sits on the coastline -> dot (10, 4) -> cell (5, 1)
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
