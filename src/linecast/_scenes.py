"""What a live view keeps between repaints: memos and scenes.

Every live command paints from data it did not fetch on this repaint.
Two kinds of keeping cover all of it.

A Memo is a small dict that answers or builds on the caller's thread and
forgets its oldest entries past a handful.  Basemaps, place names, shaded
terrain buffers and route layers are memos: cheap enough to rebuild, and
of no use once the view has moved on.

A SceneCache holds a view's worth of fetched data — a terrain grid, a
street layer, a radar field.  Blocking, a miss loads on the caller and
raises what the loader raises.  Live, a miss starts one background load
per key, answers `empty` so the frame can say "loading", and nudges the
live loop to repaint when the data lands.  A FetchHold can gate it:
while a zoom gesture is still in flight no fetch starts, and the hold
nudges one repaint after the last tap settles, so the view you stop on
is the one that reaches the network.
"""

import threading
import time

from linecast._live import nudge
from linecast._runtime import log_failure


class Memo:
    """A bounded, synchronous memo: `get(key, build)` answers or builds.

    Past `keep` entries the oldest go first, so a pan back to a
    neighbour still hits while a long-gone view does not.  `keep=1` is a
    one-slot memo: the current view and nothing else.  Not locked —
    callers that share a memo across threads hold their own lock; a
    put that races another one may keep an entry too many, but never
    raises.
    """
    __slots__ = ("keep", "_items")

    def __init__(self, keep=4):
        self.keep = keep
        self._items = {}

    def get(self, key, build=None):
        """The value under `key`; with `build`, make and keep it on a miss."""
        hit = self._items.get(key)
        if hit is None and build is not None:
            hit = build()
            self.put(key, hit)
        return hit

    def put(self, key, value):
        items = self._items
        items.pop(key, None)
        items[key] = value
        over = len(items) - self.keep
        if over > 0:
            for old in list(items)[:over]:
                items.pop(old, None)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)

    def __contains__(self, key):
        return key in self._items


class FetchHold:
    """No fetch starts while a gesture is still in flight.

    Each `hold()` pushes a deadline `settle` seconds out, and `held()` is
    true until it passes.  Every hold also arms a timer that nudges one
    repaint just past its own deadline; only the last one still holds
    the deadline by then, so exactly one repaint follows the last tap —
    the repaint that reaches the network.  Zoom taps repaint at once
    either way; each intermediate zoom is its own cache key, and without
    the hold a run of `-` presses would spawn a fetch per step, all of
    them fighting the one view actually asked for.
    """
    __slots__ = ("settle", "_deadline")

    def __init__(self, settle=0.3):
        self.settle = settle
        self._deadline = 0.0

    def held(self):
        return time.monotonic() < self._deadline

    def hold(self):
        deadline = time.monotonic() + self.settle
        self._deadline = deadline
        # Bound now: a timer still sleeping when the tests swap nudge out
        # under the next test should fire the one it was armed with.
        poke = nudge

        def settled():
            time.sleep(self.settle + 0.02)
            if self._deadline == deadline:
                poke()

        threading.Thread(target=settled, daemon=True).start()


class SceneCache:
    """A few built views, loaded in the background when live.

    `get(key, block, load)` answers from the cache.  Blocking, a miss
    runs `load` on the calling thread and raises what it raises.  Live,
    a miss starts one daemon worker per key — none while `held()` says a
    gesture is still in flight — and answers `empty` until the worker's
    view lands and nudges a repaint; a worker that fails leaves nothing
    behind, so the next repaint asks again.  With `max_age`, a view
    older than that many seconds of wall-clock time is a miss — wall
    clock, not monotonic, so a laptop that slept through the age wakes
    to a miss.  The cache keeps `keep` views, oldest out first: a pan
    is a few neighbours, and a view older than that is not coming back.
    `name` is what the debug log calls a worker that failed.
    """

    def __init__(self, empty=None, keep=4, held=None, max_age=None, name="scene"):
        self.empty = empty
        self.keep = keep
        self.held = held
        self.max_age = max_age
        self.name = name
        self._views = {}      # key -> (time.time() stamp, view)
        self._pending = set()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._views.clear()

    def _put(self, key, view):
        views = self._views
        views.pop(key, None)
        views[key] = (time.time(), view)
        over = len(views) - self.keep
        if over > 0:
            for old in list(views)[:over]:
                views.pop(old, None)

    def _fresh(self, key):
        hit = self._views.get(key)
        if hit is None:
            return None
        stamp, view = hit
        if self.max_age is not None and time.time() - stamp >= self.max_age:
            del self._views[key]
            return None
        return view

    def peek(self, key):
        """The cached view under `key`, or None; never loads."""
        with self._lock:
            return self._fresh(key)

    def get(self, key, block, load):
        with self._lock:
            hit = self._fresh(key)
            if hit is not None:
                return hit
            if not block:
                if key in self._pending or (self.held is not None
                                            and self.held()):
                    return self.empty
                self._pending.add(key)

        if block:
            hit = load()
            with self._lock:
                self._put(key, hit)
            return hit

        def worker():
            try:
                hit = load()
            except Exception as exc:
                log_failure("worker", f"{self.name} load", exc, fallback="view stays empty")
                hit = None
            with self._lock:
                self._pending.discard(key)
                if hit is not None:
                    self._put(key, hit)
            if hit is not None:
                nudge()

        threading.Thread(target=worker, daemon=True).start()
        return self.empty
