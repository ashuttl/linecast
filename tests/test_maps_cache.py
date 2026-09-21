"""The scene caches the live map's loaders share (the scaffold itself is
tested in test_scenes), and the one slot a moving view builds in.
"""

import sys
import threading
import types
from pathlib import Path

import pytest

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

    def test_every_loader_waits_on_the_zoom_hold_and_on_motion(self):
        # the gate is a pair now — a zoom run and a camera in motion
        # both keep the loaders off the network
        assert isinstance(_maps_views._zoom_hold, FetchHold)
        assert _maps_views._zoom_hold.settle == _maps_views.ZOOM_SETTLE
        for cache in (_maps_views._elev_cache, _maps_views._street_cache,
                      _maps_views._globe_cache):
            assert cache.held is _maps_views._held

    def test_motion_holds_and_lets_go(self):
        assert _maps_views._held() is False
        _maps_views.hold_motion(True)
        try:
            assert _maps_views._held() is True
        finally:
            _maps_views.hold_motion(False)
        assert _maps_views._held() is False
        _maps_views._zoom_hold.hold()
        try:
            assert _maps_views._held() is True
        finally:
            _maps_views._zoom_hold._deadline = 0.0

    def test_maps_reaches_the_same_caches(self):
        # the bench scripts clear them through linecast.maps
        assert maps._elev_cache is _maps_views._elev_cache
        assert maps._street_cache is _maps_views._street_cache
        assert maps._globe_cache is _maps_views._globe_cache
        assert maps._terrain_cache is _maps_views._terrain_cache


@pytest.fixture
def motion(monkeypatch):
    """The camera moving, with the builds' threads left in hand."""
    started = []

    class Thread:
        def __init__(self, target=None, args=(), daemon=False):
            self.target = target
            started.append(self)

        def start(self):
            pass

    monkeypatch.setattr(_maps_views, "threading",
                        types.SimpleNamespace(Thread=Thread,
                                              Lock=threading.Lock))
    woke = []
    monkeypatch.setattr(_maps_views, "_nudge_repaint", lambda: woke.append(1))
    _maps_views.hold_motion(True)
    yield started, woke
    _maps_views.hold_motion(False)
    _maps_views._motion_out[0] = False
    _maps_views._motion_next[0] = None


def _cache():
    return SceneCache(empty=None, held=_maps_views._held, name="test")


class TestTheMotionSlot:
    """While the camera moves, one view builds at a time."""

    def test_one_at_a_time_and_the_newest_request_wins(self, motion):
        started, woke = motion
        cache, built = _cache(), []

        def load(name):
            return lambda: built.append(name) or name

        _maps_views._motion_build(cache, "a", load("a"))
        assert len(started) == 1
        _maps_views._motion_build(cache, "b", load("b"))
        _maps_views._motion_build(cache, "c", load("c"))
        assert len(started) == 1                  # still the one in flight
        assert _maps_views._motion_next[0][1] == "c"
        started[0].target()                       # "a" lands
        assert built == ["a"] and cache.peek("a") == "a"
        assert woke == [1]                        # and wakes the loop
        assert len(started) == 2                  # the newest takes the slot
        started[1].target()
        assert built == ["a", "c"]                # "b" was never asked for
        assert _maps_views._motion_out[0] is False
        assert _maps_views._motion_next[0] is None

    def test_a_view_at_rest_builds_the_ordinary_way(self, motion):
        started, _woke = motion
        _maps_views.hold_motion(False)
        _maps_views._motion_build(_cache(), "a", lambda: "a")
        assert started == []

    def test_a_zoom_run_keeps_its_hold(self, motion):
        started, _woke = motion
        _maps_views._zoom_hold.hold()
        try:
            _maps_views._motion_build(_cache(), "a", lambda: "a")
        finally:
            _maps_views._zoom_hold._deadline = 0.0
        assert started == []

    def test_a_view_on_its_way_is_not_asked_for_twice(self, motion):
        # the coast's destination goes to the network at the release;
        # a frame that asks for that same window while it is out waits
        started, _woke = motion
        cache, seen = _cache(), []

        def load():
            seen.append(cache.pending("a"))
            _maps_views._motion_build(cache, "a", load)
            return "a"

        _maps_views._motion_build(cache, "a", load)
        started[0].target()
        assert seen == [True] and len(started) == 1
        _maps_views._motion_build(cache, "a", load)   # nor once it has landed
        assert len(started) == 1

    def test_a_destination_on_its_way_stands_the_slot_down(self, motion):
        # two loaders do not take half as long each; the window the
        # reader will stop on is worth more than the ones they pass
        started, _woke = motion
        cache = _cache()
        _maps_views.fetch_destination(lambda: None)
        assert _maps_views._dest_out[0] == 1     # counted before it runs
        _maps_views._motion_build(cache, "a", lambda: "a")
        assert len(started) == 1                 # the destination's own
        started[0].target()                      # it lands
        assert _maps_views._dest_out[0] == 0
        _maps_views._motion_build(cache, "a", lambda: "a")
        assert len(started) == 2

    def test_a_flight_builds_nothing_it_passes_over(self, motion):
        started, _woke = motion
        _maps_views.hold_motion(True, passing=False)
        _maps_views._motion_build(_cache(), "a", lambda: "a")
        assert started == []

    def test_a_queued_view_is_dropped_when_the_motion_ends(self, motion):
        started, _woke = motion
        cache = _cache()
        _maps_views._motion_build(cache, "a", lambda: "a")
        _maps_views._motion_build(cache, "b", lambda: "b")
        _maps_views.hold_motion(False)
        started[0].target()
        assert len(started) == 1                  # the frame at rest asks
        assert _maps_views._motion_out[0] is False

    def test_a_build_that_fails_frees_the_slot(self, motion):
        started, woke = motion
        cache = _cache()

        def boom():
            raise RuntimeError("offline")

        _maps_views._motion_build(cache, "a", boom)
        started[0].target()
        assert cache.peek("a") is None and woke == [1]
        assert _maps_views._motion_out[0] is False
        _maps_views._motion_build(cache, "b", lambda: "b")
        assert len(started) == 2


class TestTheLoadersInMotion:
    def test_a_flat_loader_in_motion_asks_the_slot(self, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_views, "_motion_build",
                            lambda cache, key, load: asked.append((cache, key)))
        bbox = (11.25, 3.5, 11.75, 3.75)
        gw, hc = 8, 4
        _maps_views.hold_motion(True)
        try:
            assert _maps_views._get_elevation(bbox, gw, hc, False) is (
                _maps_views._EMPTY_TERRAIN)
            assert _maps_views._get_street(bbox, gw, hc, False) == (
                None, None, None)
        finally:
            _maps_views.hold_motion(False)
        key = _maps_views._view_key(bbox, gw, hc)
        assert [c for c, _k in asked] == [_maps_views._elev_cache,
                                          _maps_views._street_cache]
        assert [k for _c, k in asked] == [key, key + ("en", ())]

    def test_a_blocking_load_never_asks_the_slot(self, monkeypatch):
        # --print and the destination prefetch load on their own thread
        # and are not the loop's frame; the slot is the frames' own
        asked = []
        monkeypatch.setattr(_maps_views, "_motion_build",
                            lambda *a: asked.append(a))
        bbox = (11.25, 3.5, 11.75, 3.75)
        gw, hc = 8, 4
        cache = _maps_views._elev_cache
        _maps_views.hold_motion(True)
        try:
            cache.get(_maps_views._view_key(bbox, gw, hc), True,
                      lambda: _maps_views._EMPTY_TERRAIN)
            _maps_views._get_elevation(bbox, gw, hc, True)
        finally:
            _maps_views.hold_motion(False)
            cache.clear()
        assert asked == []


class TestLandings:
    def test_a_landed_view_is_taken_once(self):
        _maps_views._street_landed[0] = ("bbox", 8, 4, "fills", "layer")
        assert _maps_views.take_street()[0] == "bbox"
        assert _maps_views.take_street() is None
        _maps_views._terrain_landed[0] = ("bbox", 8, 4, "view")
        assert _maps_views.take_terrain()[3] == "view"
        assert _maps_views.take_terrain() is None


class TestDestinationFetches:
    def test_a_prefetch_is_counted_from_the_frame_that_asks(self, motion,
                                                            monkeypatch):
        started, _woke = motion
        seen = []
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: seen.append("loaded"))
        _maps_views.hold_motion(True)
        maps.prefetch_view(1.0, 2.0, 1.0, "terrain", 8, 4, "en")
        # counted on the caller's thread: the very next frame in motion
        # already knows to stand aside
        assert _maps_views._dest_out[0] == 1
        _maps_views._motion_build(_cache(), "a", lambda: "a")
        assert len(started) == 1                 # the destination alone
        seen.append(_maps_views._dest_out[0])
        started[0].target()                      # the prefetch lands
        assert _maps_views._dest_out[0] == 0
        assert seen == [1, "loaded"]
