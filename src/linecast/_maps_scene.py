"""Bounded background preparation of map detail.

The foreground owns the camera. A detail reply can replace its source layers,
but never its position. At most one build runs and one latest request waits;
rapid input cannot leave a queue of obsolete views to work through.
"""

from collections import OrderedDict
from dataclasses import dataclass
import math
import threading
import time

from linecast._live import nudge
from linecast._runtime import log_failure


@dataclass(frozen=True)
class Scene:
    exact: object
    overscan: object


def _best_scene(scenes, camera):
    """Choose retained geography for the displayed camera, not request age."""
    if not scenes:
        return None
    exact = next((scene for scene in scenes if scene.exact.camera.key == camera.key), None)
    if exact is not None:
        return exact
    # Probe the visible Earth, excluding empty space around a complete disk.
    # The center is always included, even on an extremely wide terminal.
    radius = 180.0 / math.pi / camera.zoom * camera.hc
    x0, x1 = max(0, camera.gw / 2 - 2 * radius), min(camera.gw, camera.gw / 2 + 2 * radius)
    y0, y1 = max(0, camera.hc / 2 - radius), min(camera.hc, camera.hc / 2 + radius)
    fractions = (.025, .2625, .5, .7375, .975)
    points = [ll for fy in fractions for fx in fractions
              if (ll := camera.unproject(x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy,
                                         camera.gw, camera.hc)) is not None]

    def score(scene):
        source = scene.overscan.camera
        if scene.overscan.surface is not None:
            covered = len(points)  # the surface includes the unseen hemisphere
        else:
            covered = 0
            for lat, lon in points:
                if source.visible(lon, lat):
                    x, y = source.project(lon, lat, source.gw, source.hc)
                    covered += 0 <= x < source.gw and 0 <= y < source.hc
        # Padding increases zoom and height together. Compare degrees per
        # physical pixel so a padded scene retains its true source resolution.
        resolution = abs(math.log((source.zoom / source.hc) / (camera.zoom / camera.hc)))
        return covered, -resolution

    # Callers give most recent first, making recency the last tie-breaker.
    return max(scenes, key=score)


class SceneWorker:
    def __init__(self, wake=nudge, thread_factory=threading.Thread, timer_factory=None):
        self._wake = wake
        self._thread_factory = thread_factory
        self._timer_factory = timer_factory or threading.Timer
        self._lock = threading.Lock()
        self._active = None
        self._pending = None
        self._running = False
        self._stopped = False
        self._ready = OrderedDict()
        self._errors = OrderedDict()
        self._latest = object()
        self._latest_token = object()
        self._retry_timer = None
        self._retry_token = None

    def _cancel_retry(self):
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        self._retry_token = None

    def _schedule_retry(self, deadline):
        """Called under the lock; return the one new timer to start outside it."""
        if self._retry_timer is not None:
            return None
        token = self._latest_token
        timer = self._timer_factory(max(0.0, deadline - time.monotonic()),
                                    lambda: self._retry_ready(token))
        timer.daemon = True
        self._retry_timer, self._retry_token = timer, token
        return timer

    def _retry_ready(self, token):
        with self._lock:
            if (self._stopped or token is not self._latest_token
                    or token is not self._retry_token):
                return
            self._retry_timer = self._retry_token = None
        # The foreground requests its current target again. A timer never
        # owns a camera or starts a build for an obsolete request.
        self._wake()

    def request(self, key, group, build, *, camera=None):
        """Request the latest target, returning a compatible retained scene."""
        start = False
        timer = None
        with self._lock:
            if self._stopped:
                return None, False, None
            if key != self._latest:
                self._latest, self._latest_token = key, object()
                self._cancel_retry()
            error = self._errors.get(key)
            retry = error is None or time.monotonic() - error[0] >= 3.0
            if key in self._ready:
                self._cancel_retry()
                self._pending = None
                self._ready.move_to_end(key)
            elif key != self._active and retry:
                self._cancel_retry()
                self._pending = (key, group, build)
                if not self._running:
                    self._running = True
                    start = True
            else:
                # The newest target is already running or is waiting for
                # its error backoff. Neither case should leave an older
                # target queued behind the active build.
                self._pending = None
                if key == self._active:
                    self._cancel_retry()
                elif error is not None:
                    timer = self._schedule_retry(error[0] + 3.0)
            candidates = [scene for value_group, scene in reversed(self._ready.values())
                          if value_group == group]
            match = self._ready.get(key)
            scene = match[1] if match is not None else next(iter(candidates), None)
            refining = key not in self._ready and (retry or key == self._active)
            message = error[1] if error is not None else None
        if camera is not None:
            scene = _best_scene(candidates, camera)
        if start:
            self._thread_factory(target=self._run, daemon=True).start()
        if timer is not None:
            timer.start()
        return scene, refining, message

    def _run(self):
        while True:
            timer = None
            with self._lock:
                if self._stopped or self._pending is None:
                    self._active = None
                    self._running = False
                    return
                key, group, build = self._pending
                self._pending = None
                self._active = key
            try:
                scene = build()
                if scene is None:
                    raise RuntimeError("map detail unavailable")
                error = None
            except Exception as exc:
                log_failure("maps", "prepare detail", exc,
                            fallback="previous map retained")
                lines = str(exc).splitlines()
                scene, error = None, (lines[0] if lines else type(exc).__name__)[:120]
            with self._lock:
                if self._stopped:
                    self._active = None
                    self._running = False
                    return
                if scene is not None:
                    self._ready[key] = (group, scene)
                    self._ready.move_to_end(key)
                    while len(self._ready) > 4:
                        self._ready.popitem(last=False)
                    self._errors.pop(key, None)
                else:
                    self._errors[key] = (time.monotonic(), error)
                    while len(self._errors) > 8:
                        self._errors.popitem(last=False)
                    if key == self._latest:
                        timer = self._schedule_retry(self._errors[key][0] + 3.0)
                self._active = None
            if timer is not None:
                timer.start()
            self._wake()

    def stop(self):
        """Discard waiting work and prevent a late reply from repainting."""
        with self._lock:
            self._stopped = True
            self._pending = None
            self._ready.clear()
            self._cancel_retry()
