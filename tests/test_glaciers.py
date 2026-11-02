"""The vendored glacier grid, and the terrain views that take their ice from it."""

import pytest

from linecast.maps import glaciers as _glaciers
from linecast.maps import loaders
from linecast.maps import style as _style

ICE = _style.COVER_ORDER.index("ice") + 1


class TestGrid:
    def test_the_ice_is_where_the_glaciers_are(self):
        ice = [(-75.0, 0.0),        # the Antarctic coast
               (72.0, -40.0),       # the Greenland ice sheet
               (58.75, -134.25),    # the Juneau Icefield
               (64.4, -16.8),       # Vatnajökull
               (-49.5, -73.4)]      # the Southern Patagonian Icefield
        bare = [(61.2, -149.9),     # Anchorage
                (64.18, -51.72),    # Nuuk, on Greenland's ice-free coast
                (71.29, -156.79),   # Utqiaġvik, on the tundra
                (33.0, 88.0),       # the Tibetan interior
                (25.0, 10.0)]       # the Sahara
        rows = _glaciers.grid_for_lls([ice + bare + [None]], ICE)
        assert list(rows[0]) == [ICE] * len(ice) + [0] * len(bare) + [0]

    def test_no_ice_in_view_means_no_grid(self):
        assert _glaciers.grid_for_lls([[(25.0, 10.0), None]], ICE) is None
        assert _glaciers.grid_for_bbox((0.0, 20.0, 20.0, 30.0), 8, 4,
                                       ICE) is None

    def test_a_flat_view_runs_north_to_south(self):
        # rows centred on 7.5°N, 17.5°S, 42.5°S and 67.5°S: only the
        # last is Antarctic
        rows = _glaciers.grid_for_bbox((0.0, -80.0, 10.0, 20.0), 2, 4, ICE)
        assert [row[0] for row in rows] == [0, 0, 0, ICE]


class TestFlatView:
    """One source of ice per view: the grid below GLACIER_TILE_ZOOM,
    the tiles from it up."""

    @pytest.fixture
    def asked(self, monkeypatch):
        asked = []

        def tile_water(bbox, gw, hc, window=None, camera=None, missing=None,
                       tile_ice=True):
            asked.append(tile_ice)
            return None, None, None, None

        monkeypatch.setattr(
            loaders, "elevation_grid",
            lambda bbox, w, h, camera=None, missing=None:
                [[1500.0] * w for _ in range(h)])
        monkeypatch.setattr(loaders, "_tile_water", tile_water)
        monkeypatch.setattr(loaders, "_builtup_layer", lambda *a, **k: None)
        loaders._elev_cache.clear()
        yield asked
        loaders._elev_cache.clear()

    def test_a_wide_view_paints_the_grid_and_leaves_the_tiles_ice_out(
            self, asked):
        # eight degrees over the Juneau Icefield, offline: the grid is
        # vendored, so the ice is there without a tile
        view = loaders._get_elevation((-140.0, 55.0, -128.0, 63.0), 40, 10,
                                      True)
        assert asked == [False]
        assert any(ICE in row for row in view.cover)

    def test_a_close_view_leaves_the_ice_to_the_tiles(self, asked):
        view = loaders._get_elevation((-134.5, 58.6, -134.0, 58.9), 40, 10,
                                      True)
        assert asked == [True]
        assert view.cover is None
