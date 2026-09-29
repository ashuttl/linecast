"""The scene caches the live map's loaders share (the scaffold itself is
tested in test_scenes), and the one slot a moving view builds in.
"""

import threading
import types

import pytest

from linecast.maps import view as maps
from linecast.maps import views
from linecast.terminal.scenes import FetchHold, SceneCache


class TestMapScenes:
    def test_the_loaders_share_the_scaffold(self):
        assert isinstance(views._elev_cache, SceneCache)
        assert isinstance(views._street_cache, SceneCache)
        assert isinstance(views._globe_cache, SceneCache)
        assert views._elev_cache.empty is views._EMPTY_TERRAIN
        assert views._street_cache.empty == (None, None, None)
        assert views._globe_cache.empty is None

    def test_every_loader_waits_on_the_zoom_hold_and_on_motion(self):
        # the gate is a pair now — a zoom run and a camera in motion
        # both keep the loaders off the network
        assert isinstance(views._zoom_hold, FetchHold)
        assert views._zoom_hold.settle == views.ZOOM_SETTLE
        for cache in (views._elev_cache, views._street_cache,
                      views._globe_cache):
            assert cache.held is views._held

    def test_motion_holds_and_lets_go(self):
        assert views._held() is False
        views.hold_motion(True)
        try:
            assert views._held() is True
        finally:
            views.hold_motion(False)
        assert views._held() is False
        views._zoom_hold.hold()
        try:
            assert views._held() is True
        finally:
            views._zoom_hold._deadline = 0.0


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

    monkeypatch.setattr(views, "threading",
                        types.SimpleNamespace(Thread=Thread,
                                              Lock=threading.Lock))
    woke = []
    monkeypatch.setattr(views, "_nudge_repaint", lambda: woke.append(1))
    views.hold_motion(True)
    yield started, woke
    views.hold_motion(False)
    views._motion_out[0] = False
    views._motion_next[0] = None


def _cache():
    return SceneCache(empty=None, held=views._held, name="test")


class TestTheMotionSlot:
    """While the camera moves, one view builds at a time."""

    def test_one_at_a_time_and_the_newest_request_wins(self, motion):
        started, woke = motion
        cache, built = _cache(), []

        def load(name):
            return lambda: built.append(name) or name

        views._motion_build(cache, "a", load("a"))
        assert len(started) == 1
        views._motion_build(cache, "b", load("b"))
        views._motion_build(cache, "c", load("c"))
        assert len(started) == 1                  # still the one in flight
        assert views._motion_next[0][1] == "c"
        started[0].target()                       # "a" lands
        assert built == ["a"] and cache.peek("a") == "a"
        assert woke == [1]                        # and wakes the loop
        assert len(started) == 2                  # the newest takes the slot
        started[1].target()
        assert built == ["a", "c"]                # "b" was never asked for
        assert views._motion_out[0] is False
        assert views._motion_next[0] is None

    def test_a_view_at_rest_builds_the_ordinary_way(self, motion):
        started, _woke = motion
        views.hold_motion(False)
        views._motion_build(_cache(), "a", lambda: "a")
        assert started == []

    def test_a_zoom_run_keeps_its_hold(self, motion):
        started, _woke = motion
        views._zoom_hold.hold()
        try:
            views._motion_build(_cache(), "a", lambda: "a")
        finally:
            views._zoom_hold._deadline = 0.0
        assert started == []

    def test_a_view_on_its_way_is_not_asked_for_twice(self, motion):
        # the coast's destination goes to the network at the release;
        # a frame that asks for that same window while it is out waits
        started, _woke = motion
        cache, seen = _cache(), []

        def load():
            seen.append(cache.pending("a"))
            views._motion_build(cache, "a", load)
            return "a"

        views._motion_build(cache, "a", load)
        started[0].target()
        assert seen == [True] and len(started) == 1
        views._motion_build(cache, "a", load)   # nor once it has landed
        assert len(started) == 1

    def test_a_destination_on_its_way_stands_the_slot_down(self, motion):
        # two loaders do not take half as long each; the window the
        # reader will stop on is worth more than the ones they pass
        started, _woke = motion
        cache = _cache()
        views.fetch_destination(lambda: None)
        assert views._dest_out[0] == 1     # counted before it runs
        views._motion_build(cache, "a", lambda: "a")
        assert len(started) == 1                 # the destination's own
        started[0].target()                      # it lands
        assert views._dest_out[0] == 0
        views._motion_build(cache, "a", lambda: "a")
        assert len(started) == 2

    def test_a_flight_builds_nothing_it_passes_over(self, motion):
        started, _woke = motion
        views.hold_motion(True, passing=False)
        views._motion_build(_cache(), "a", lambda: "a")
        assert started == []

    def test_a_queued_view_is_dropped_when_the_motion_ends(self, motion):
        started, _woke = motion
        cache = _cache()
        views._motion_build(cache, "a", lambda: "a")
        views._motion_build(cache, "b", lambda: "b")
        views.hold_motion(False)
        started[0].target()
        assert len(started) == 1                  # the frame at rest asks
        assert views._motion_out[0] is False

    def test_a_build_that_fails_frees_the_slot(self, motion):
        started, woke = motion
        cache = _cache()

        def boom():
            raise RuntimeError("offline")

        views._motion_build(cache, "a", boom)
        started[0].target()
        assert cache.peek("a") is None and woke == [1]
        assert views._motion_out[0] is False
        views._motion_build(cache, "b", lambda: "b")
        assert len(started) == 2


class TestTheLoadersInMotion:
    def test_a_flat_loader_in_motion_asks_the_slot(self, monkeypatch):
        asked = []
        monkeypatch.setattr(views, "_motion_build",
                            lambda cache, key, load: asked.append((cache, key)))
        bbox = (11.25, 3.5, 11.75, 3.75)
        gw, hc = 8, 4
        views.hold_motion(True)
        try:
            assert views._get_elevation(bbox, gw, hc, False) is (
                views._EMPTY_TERRAIN)
            assert views._get_street_tiles(bbox, gw, hc, False) == (
                None, None, None)
        finally:
            views.hold_motion(False)
        key = views._view_key(bbox, gw, hc)
        assert [c for c, _k in asked] == [views._elev_cache,
                                          views._street_cache]
        assert [k for _c, k in asked] == [key, key + ("en", ())]

    def test_a_blocking_load_never_asks_the_slot(self, monkeypatch):
        # --print and the destination prefetch load on their own thread
        # and are not the loop's frame; the slot is the frames' own
        asked = []
        monkeypatch.setattr(views, "_motion_build",
                            lambda *a: asked.append(a))
        bbox = (11.25, 3.5, 11.75, 3.75)
        gw, hc = 8, 4
        cache = views._elev_cache
        views.hold_motion(True)
        try:
            cache.get(views._view_key(bbox, gw, hc), True,
                      lambda: views._EMPTY_TERRAIN)
            views._get_elevation(bbox, gw, hc, True)
        finally:
            views.hold_motion(False)
            cache.clear()
        assert asked == []


class TestLandings:
    def test_a_landed_view_is_taken_once(self):
        views._street_landed[0] = ("bbox", 8, 4, "fills", "layer")
        assert views.take_street()[0] == "bbox"
        assert views.take_street() is None
        views._terrain_landed[0] = ("bbox", 8, 4, "view")
        assert views.take_terrain()[3] == "view"
        assert views.take_terrain() is None


class TestDestinationFetches:
    def test_a_prefetch_is_counted_from_the_frame_that_asks(self, motion,
                                                            monkeypatch):
        started, _woke = motion
        seen = []
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: seen.append("loaded"))
        views.hold_motion(True)
        maps.prefetch_view(1.0, 2.0, 1.0, "terrain", 8, 4, "en")
        # counted on the caller's thread: the very next frame in motion
        # already knows to stand aside
        assert views._dest_out[0] == 1
        views._motion_build(_cache(), "a", lambda: "a")
        assert len(started) == 1                 # the destination alone
        seen.append(views._dest_out[0])
        started[0].target()                      # the prefetch lands
        assert views._dest_out[0] == 0
        assert seen == [1, "loaded"]


@pytest.fixture
def mending(monkeypatch):
    """A live loop on screen, with the rebuilds' threads left in hand
    and their waits skipped."""
    started = []

    class Thread:
        def __init__(self, target=None, args=(), daemon=False):
            self.target = target
            started.append(self)

        def start(self):
            pass

    monkeypatch.setattr(views, "threading",
                        types.SimpleNamespace(Thread=Thread,
                                              Lock=threading.Lock))
    monkeypatch.setattr(views, "time",
                        types.SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(views._live, "_running", True)
    woke = []
    monkeypatch.setattr(views, "_nudge_repaint", lambda: woke.append(1))
    monkeypatch.setattr(views.streets, "prefetch_around", lambda *a: None)
    views._street_cache.clear()
    views._mends.clear()
    yield started, woke
    views._street_cache.clear()
    views._mends.clear()
    views._street_built[0] = None
    views._street_landed[0] = None


class TestAViewShortOfATileIsBuiltAgain:
    """A tile that did not arrive is asked for again, later, rather than
    leaving a gap for as long as the view is on screen."""

    BBOX = (-70.3, 43.6, -70.2, 43.7)

    def _street(self, monkeypatch, answers):
        keys = [(14, 1, 1), (14, 2, 1)]
        monkeypatch.setattr(views.streets, "view_tiles",
                            lambda *a, **k: (7, 14, keys))
        asked = []

        def fetch(want):
            asked.append(list(want))
            return dict(zip(want, answers.pop(0)))

        monkeypatch.setattr(views.streets, "fetch_tiles", fetch)
        monkeypatch.setattr(
            views.streets, "build_street_view",
            lambda bbox, gw, hc, tiles, *a: (dict(tiles), "layer", {}))
        return asked

    def test_the_gap_is_filled_by_a_later_build(self, mending, monkeypatch):
        started, woke = mending
        asked = self._street(monkeypatch,
                             [[b"a", None], [b"a", b"b"]])
        first = views._get_street_tiles(self.BBOX, 8, 4, True)
        assert first[0][(14, 2, 1)] is None
        assert len(started) == 1
        started[0].target()
        key = views._view_key(self.BBOX, 8, 4) + ("en", ())
        mended = views._street_cache.peek(key)
        assert mended[0] == {(14, 1, 1): b"a", (14, 2, 1): b"b"}
        # it lands as any view does, and wakes a loop at rest
        assert views.take_street()[3] is mended[0]
        assert woke == [1]
        assert len(asked) == 2
        assert len(started) == 1        # whole now: nothing more to ask

    def test_a_whole_view_is_not_built_again(self, mending, monkeypatch):
        started, _woke = mending
        self._street(monkeypatch, [[b"a", b"b"]])
        views._get_street_tiles(self.BBOX, 8, 4, True)
        assert started == []

    def test_a_view_left_behind_is_forgotten_instead(self, mending,
                                                     monkeypatch):
        started, woke = mending
        asked = self._street(monkeypatch,
                             [[b"a", None], [b"a", b"b"]])
        views._get_street_tiles(self.BBOX, 8, 4, True)
        views._get_street_tiles((-70.2, 43.6, -70.1, 43.7), 8, 4, True)
        started[0].target()
        key = views._view_key(self.BBOX, 8, 4) + ("en", ())
        # coming back to it is a load of its own, not the gap again
        assert views._street_cache.peek(key) is None
        assert len(asked) == 2 and woke == []

    def test_it_stops_asking_after_the_last_try(self, mending, monkeypatch):
        started, _woke = mending
        tries = len(views.MEND_AFTER)
        self._street(monkeypatch, [[b"a", None]] * (tries + 1))
        views._get_street_tiles(self.BBOX, 8, 4, True)
        for i in range(tries):
            started[i].target()
        assert len(started) == tries
        assert views._mends == {}

    def test_print_never_waits_to_build_again(self, mending, monkeypatch):
        started, _woke = mending
        monkeypatch.setattr(views._live, "_running", False)
        self._street(monkeypatch, [[b"a", None]])
        views._get_street_tiles(self.BBOX, 8, 4, True)
        assert started == []

    def test_a_terrain_view_short_of_elevation_is_shaded_afresh(
            self, mending, monkeypatch):
        started, _woke = mending
        tiles = [None, 12.0]

        def grid(bbox, w, h, camera=None, missing=None):
            value = tiles.pop(0)
            if value is None:
                missing.append((8, 1, 1))
            return [[value] * w for _ in range(h)]

        monkeypatch.setattr(views, "elevation_grid", grid)
        monkeypatch.setattr(views, "_tile_water",
                            lambda *a: (None, None, None, None))
        monkeypatch.setattr(views, "_builtup_layer", lambda *a: None)
        views._elev_cache.clear()
        try:
            first = views._get_elevation(self.BBOX, 8, 4, True)
            assert first.elev[0][0] is None
            views._terrain_cache.put("shaded with the gap", [])
            started[0].target()
            key = views._view_key(self.BBOX, 8, 4)
            assert views._elev_cache.peek(key).elev[0][0] == 12.0
            # the buffer shaded from the gap is not the one it keeps
            assert "shaded with the gap" not in views._terrain_cache
        finally:
            views._elev_cache.clear()
            views._terrain_built[0] = None
            views._terrain_landed[0] = None
