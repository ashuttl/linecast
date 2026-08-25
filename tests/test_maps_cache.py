"""The scene caches the live map's loaders share (the scaffold itself is
tested in test_scenes)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_views, maps
from linecast._scenes import FetchHold, SceneCache


class TestMapScenes:
    def test_the_loaders_share_the_scaffold(self):
        assert isinstance(_maps_views._elev_cache, SceneCache)
        assert isinstance(_maps_views._street_cache, SceneCache)
        assert isinstance(_maps_views._globe_cache, SceneCache)
        assert _maps_views._elev_cache.empty is _maps_views._EMPTY_TERRAIN
        assert _maps_views._street_cache.empty == (None, None, None)
        assert _maps_views._globe_cache.empty is None

    def test_every_loader_waits_on_the_zoom_hold(self):
        assert isinstance(_maps_views._zoom_hold, FetchHold)
        assert _maps_views._zoom_hold.settle == _maps_views.ZOOM_SETTLE
        for cache in (_maps_views._elev_cache, _maps_views._street_cache,
                      _maps_views._globe_cache):
            assert cache.held.__self__ is _maps_views._zoom_hold

    def test_maps_reaches_the_same_caches(self):
        # the bench scripts clear them through linecast.maps
        assert maps._elev_cache is _maps_views._elev_cache
        assert maps._street_cache is _maps_views._street_cache
        assert maps._globe_cache is _maps_views._globe_cache
        assert maps._terrain_cache is _maps_views._terrain_cache
