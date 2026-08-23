"""The view cache every live map loader shares."""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_views, maps


def _settle(cache, key, timeout=2.0):
    """Wait for a background load of `key` to land."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with cache._lock:
            if key not in cache._pending:
                return
        time.sleep(0.005)
    raise AssertionError("worker never finished")


class TestViewCache:
    @pytest.fixture(autouse=True)
    def _no_hold(self, monkeypatch):
        monkeypatch.setattr(_maps_views, "_fetch_held", lambda: False)
        monkeypatch.setattr(_maps_views, "_nudge_repaint", lambda: None)

    def test_blocking_loads_on_the_caller_and_caches(self):
        cache = _maps_views._ViewCache(empty="empty")
        calls = []
        assert cache.get("k", True, lambda: calls.append(1) or "view") \
            == "view"
        assert cache.get("k", True, lambda: calls.append(1) or "again") \
            == "view"
        assert calls == [1]

    def test_blocking_raises_what_the_loader_raises(self):
        cache = _maps_views._ViewCache()

        def boom():
            raise RuntimeError("offline")

        with pytest.raises(RuntimeError):
            cache.get("k", True, boom)
        assert cache.get("k", True, lambda: "ok") == "ok"

    def test_live_answers_empty_and_loads_once_in_the_background(self):
        cache = _maps_views._ViewCache(empty="empty")
        calls = []
        started = threading.Event()

        def load():
            calls.append(1)
            started.wait(1.0)
            return "view"

        assert cache.get("k", False, load) == "empty"
        assert cache.get("k", False, load) == "empty"   # already pending
        started.set()
        _settle(cache, "k")
        assert cache.get("k", False, load) == "view"
        assert calls == [1]

    def test_a_failed_background_load_leaves_nothing_behind(self):
        cache = _maps_views._ViewCache(empty=None)

        def boom():
            raise RuntimeError("offline")

        assert cache.get("k", False, boom) is None
        _settle(cache, "k")
        assert cache.get("k", True, lambda: "ok") == "ok"

    def test_a_landed_view_nudges_a_repaint(self, monkeypatch):
        nudged = []
        monkeypatch.setattr(_maps_views, "_nudge_repaint", lambda: nudged.append(1))
        cache = _maps_views._ViewCache()
        cache.get("k", False, lambda: "view")
        _settle(cache, "k")
        assert nudged == [1]

    def test_no_fetch_starts_while_a_zoom_gesture_is_in_flight(
            self, monkeypatch):
        monkeypatch.setattr(_maps_views, "_fetch_held", lambda: True)
        cache = _maps_views._ViewCache(empty="empty")
        calls = []
        assert cache.get("k", False, lambda: calls.append(1)) == "empty"
        assert not calls and not cache._pending

    def test_the_cache_clears_past_a_handful_of_views(self):
        cache = _maps_views._ViewCache(keep=3)
        for i in range(4):
            cache.get(i, True, lambda: "v")
        assert len(cache._views) == 4
        cache.get(4, True, lambda: "v")
        assert list(cache._views) == [4]
        cache.clear()
        assert not cache._views

    def test_the_loaders_share_the_scaffold(self):
        assert isinstance(_maps_views._elev_cache, _maps_views._ViewCache)
        assert isinstance(_maps_views._street_cache, _maps_views._ViewCache)
        assert isinstance(_maps_views._globe_cache, _maps_views._ViewCache)
        assert _maps_views._elev_cache.empty is _maps_views._EMPTY_TERRAIN
        assert _maps_views._street_cache.empty == (None, None, None)
        assert _maps_views._globe_cache.empty is None

    def test_maps_reaches_the_same_caches(self):
        # the bench scripts clear them through linecast.maps
        assert maps._elev_cache is _maps_views._elev_cache
        assert maps._street_cache is _maps_views._street_cache
        assert maps._globe_cache is _maps_views._globe_cache
        assert maps._terrain_cache is _maps_views._terrain_cache
