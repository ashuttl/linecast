"""The memos and scene caches every live view keeps between repaints."""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _scenes
from linecast._scenes import FetchHold, Memo, SceneCache


def _settle(cache, key, timeout=2.0):
    """Wait for a background load of `key` to land."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with cache._lock:
            if key not in cache._pending:
                return
        time.sleep(0.005)
    raise AssertionError("worker never finished")


class TestMemo:
    def test_answers_or_builds(self):
        memo = Memo()
        calls = []
        assert memo.get("k", lambda: calls.append(1) or "v") == "v"
        assert memo.get("k", lambda: calls.append(1) or "again") == "v"
        assert calls == [1]
        assert memo.get("missing") is None

    def test_oldest_goes_first(self):
        memo = Memo(keep=2)
        memo.put("a", 1)
        memo.put("b", 2)
        memo.put("c", 3)
        assert "a" not in memo and "b" in memo and "c" in memo
        assert len(memo) == 2

    def test_rewriting_a_key_makes_it_newest(self):
        memo = Memo(keep=2)
        memo.put("a", 1)
        memo.put("b", 2)
        memo.put("a", 3)
        memo.put("c", 4)
        assert list(memo._items) == ["a", "c"]
        assert memo.get("a") == 3

    def test_one_slot(self):
        memo = Memo(keep=1)
        memo.get("a", lambda: 1)
        memo.get("b", lambda: 2)
        assert list(memo._items) == ["b"]
        memo.clear()
        assert len(memo) == 0


class TestFetchHold:
    def test_holds_until_the_deadline(self, monkeypatch):
        monkeypatch.setattr(_scenes, "nudge", lambda: None)
        hold = FetchHold(settle=0.05)
        assert not hold.held()
        hold.hold()
        assert hold.held()
        time.sleep(0.07)
        assert not hold.held()

    def test_only_the_last_hold_nudges(self, monkeypatch):
        nudged = []
        monkeypatch.setattr(_scenes, "nudge", lambda: nudged.append(1))
        hold = FetchHold(settle=0.03)
        for _ in range(3):
            hold.hold()
            time.sleep(0.01)
        time.sleep(0.15)
        assert nudged == [1]


class TestSceneCache:
    @pytest.fixture(autouse=True)
    def _no_nudge(self, monkeypatch):
        monkeypatch.setattr(_scenes, "nudge", lambda: None)

    def test_blocking_loads_on_the_caller_and_caches(self):
        cache = SceneCache(empty="empty")
        calls = []
        assert cache.get("k", True, lambda: calls.append(1) or "view") \
            == "view"
        assert cache.get("k", True, lambda: calls.append(1) or "again") \
            == "view"
        assert calls == [1]
        assert cache.peek("k") == "view"
        assert cache.peek("other") is None

    def test_blocking_raises_what_the_loader_raises(self):
        cache = SceneCache()

        def boom():
            raise RuntimeError("offline")

        with pytest.raises(RuntimeError):
            cache.get("k", True, boom)
        assert cache.get("k", True, lambda: "ok") == "ok"

    def test_live_answers_empty_and_loads_once_in_the_background(self):
        cache = SceneCache(empty="empty")
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
        cache = SceneCache(empty=None)

        def boom():
            raise RuntimeError("offline")

        assert cache.get("k", False, boom) is None
        _settle(cache, "k")
        assert cache.get("k", True, lambda: "ok") == "ok"

    def test_a_landed_view_nudges_a_repaint(self, monkeypatch):
        nudged = []
        monkeypatch.setattr(_scenes, "nudge", lambda: nudged.append(1))
        cache = SceneCache()
        cache.get("k", False, lambda: "view")
        _settle(cache, "k")
        assert nudged == [1]

    def test_no_fetch_starts_while_a_gesture_is_in_flight(self):
        cache = SceneCache(empty="empty", held=lambda: True)
        calls = []
        assert cache.get("k", False, lambda: calls.append(1)) == "empty"
        assert not calls and not cache._pending
        # a blocking get is never held: the caller asked to wait
        assert cache.get("k", True, lambda: "v") == "v"

    def test_the_oldest_view_goes_first_past_keep(self):
        cache = SceneCache(keep=3)
        for i in range(4):
            cache.get(i, True, lambda: "v")
        assert list(cache._views) == [1, 2, 3]
        cache.clear()
        assert not cache._views

    def test_a_view_past_max_age_is_a_miss(self, monkeypatch):
        cache = SceneCache(max_age=10)
        now = [1000.0]
        monkeypatch.setattr(_scenes.time, "monotonic", lambda: now[0])
        calls = []
        cache.get("k", True, lambda: calls.append(1) or "v")
        now[0] += 9
        assert cache.peek("k") == "v"
        now[0] += 2
        assert cache.peek("k") is None
        cache.get("k", True, lambda: calls.append(1) or "v")
        assert calls == [1, 1]
