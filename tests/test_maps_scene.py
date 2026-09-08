"""Detail preparation stays bounded and never owns the displayed camera."""

import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_scene
from linecast._maps_camera import MapCamera
from linecast._maps_scene import Scene, SceneWorker


class DeferredThreads:
    """Deterministically run a worker after input has queued its requests."""

    def __init__(self):
        self.jobs = []

    def __call__(self, *, target, daemon):
        assert daemon
        return SimpleNamespace(start=lambda: self.jobs.append(target))

    def run(self):
        self.jobs.pop(0)()


class ManualTimer:
    def __init__(self, delay, callback):
        self.delay, self.callback = delay, callback
        self.started = self.cancelled = False

    def start(self):
        assert self.daemon
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture(autouse=True)
def timers(monkeypatch):
    created = []

    def factory(delay, callback):
        timer = ManualTimer(delay, callback)
        created.append(timer)
        return timer

    monkeypatch.setattr(_maps_scene.threading, "Timer", factory)
    return created


def _scene(key):
    return Scene(exact=key, overscan=(key, "overscan"))


def _camera_scene(camera, surface=None):
    frame = SimpleNamespace(camera=camera, surface=surface)
    return Scene(frame, frame)


def test_one_active_build_and_only_the_latest_pending_request():
    started, release = threading.Event(), threading.Event()
    wakes = queue.Queue()
    built, threads = [], []

    def factory(**kwargs):
        thread = threading.Thread(**kwargs)
        threads.append(thread)
        return thread

    worker = SceneWorker(wake=lambda: wakes.put(True), thread_factory=factory)

    def first():
        built.append("first")
        started.set()
        assert release.wait(2)
        return _scene("first")

    def detail(index):
        built.append(index)
        return _scene(index)

    try:
        worker.request("first", "terrain", first)
        assert started.wait(2)
        for index in range(100):
            scene, refining, error = worker.request(index, "terrain",
                                                    lambda index=index: detail(index))
            assert scene is None and refining and error is None
        assert built == ["first"]
        assert len(threads) == 1
        release.set()
        wakes.get(timeout=2)
        wakes.get(timeout=2)
        assert built == ["first", 99]
        assert worker.request(99, "terrain", lambda: None) == (_scene(99), False, None)
    finally:
        release.set()
        worker.stop()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)


def test_not_yet_started_work_is_replaced_without_spawning_more_threads():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    built = []
    for index in range(100):
        worker.request(index, "terrain", lambda index=index: built.append(index) or _scene(index))
    assert len(threads.jobs) == 1
    threads.run()
    assert built == [99]


def test_compatible_scene_is_retained_but_never_crosses_style_groups():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    old = _scene("old camera")
    worker.request("old", "terrain", lambda: old)
    threads.run()
    assert worker.request("new", "terrain", lambda: _scene("new")) == (old, True, None)
    assert worker.request("streets", "street", lambda: _scene("streets")) == (None, True, None)
    threads.run()
    assert worker.request("old", "terrain", lambda: None) == (old, False, None)


def test_returning_to_active_target_discards_a_queued_reverse_target():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    built = []

    def first():
        built.append("first")
        worker.request("reverse", "terrain", lambda: built.append("reverse") or _scene("reverse"))
        worker.request("first", "terrain", lambda: None)
        return _scene("first")

    worker.request("first", "terrain", first)
    threads.run()
    assert built == ["first"]
    assert worker.request("first", "terrain", lambda: None) == (_scene("first"), False, None)


def test_late_reply_does_not_replace_the_exact_scene_the_user_returned_to():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    home = _scene("home camera")
    worker.request("home", "terrain", lambda: home)
    threads.run()
    obsolete = []

    def away():
        worker.request("third", "terrain", lambda: obsolete.append(True) or _scene("third"))
        assert worker.request("home", "terrain", lambda: None) == (home, False, None)
        return _scene("away camera")

    worker.request("away", "terrain", away)
    threads.run()
    assert not obsolete
    assert worker.request("home", "terrain", lambda: None) == (home, False, None)


def test_distant_late_reply_cannot_displace_the_scene_covering_the_displayed_camera():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    home_camera = MapCamera(0, 0, 1, 80, 30)
    home = _camera_scene(home_camera)
    distant = _camera_scene(MapCamera(0, 179, 1, 80, 30))
    current_camera = home_camera.pan(1, 0)
    current = _camera_scene(current_camera)
    worker.request("home", "terrain", lambda: home, camera=home_camera)
    threads.run()

    def current_build():
        # The distant reply has landed, but its hemisphere has no geography
        # for the foreground's new nearby target while this build proceeds.
        retained, refining, error = worker.request("current", "terrain", lambda: None,
                                                  camera=current_camera)
        assert retained is home and refining and error is None
        return current

    def distant_build():
        worker.request("current", "terrain", current_build, camera=current_camera)
        return distant

    worker.request("distant", "terrain", distant_build, camera=distant.exact.camera)
    threads.run()
    assert worker.request("current", "terrain", lambda: None,
                          camera=current_camera) == (current, False, None)


def test_ready_target_detail_does_not_blank_the_camera_during_its_animation():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    start = _camera_scene(MapCamera(0, 0, 1, 80, 30))
    target = _camera_scene(MapCamera(0, 179, 1, 80, 30))
    worker.request("start", "terrain", lambda: start)
    threads.run()
    worker.request("target", "terrain", lambda: target)
    threads.run()
    for displayed in (start.exact.camera, start.exact.camera.pan(1, 0)):
        # The requested target is already ready, while the visible view has
        # only begun moving. Ready-target priority would select empty space.
        assert worker.request("target", "terrain", lambda: None,
                              camera=displayed) == (start, False, None)
    assert worker.request("target", "terrain", lambda: None,
                          camera=target.exact.camera) == (target, False, None)


def test_equal_coverage_prefers_closest_physical_resolution_over_newest_reply():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    displayed = MapCamera(0, 0, 1, 80, 30)
    padded = _camera_scene(MapCamera(0, 0, 2, 160, 60))
    coarse = _camera_scene(MapCamera(0, 0, 2, 80, 30))
    worker.request("padded", "terrain", lambda: padded)
    threads.run()
    worker.request("coarse", "terrain", lambda: coarse)
    threads.run()
    assert worker.request("moving", "terrain", lambda: None,
                          camera=displayed)[0] is padded
    assert worker.request("different style", "street", lambda: None,
                          camera=displayed)[0] is None
    worker.stop()


def test_complete_surface_beats_a_local_frame_for_a_broad_antipodal_view():
    displayed = MapCamera(43, -70, 130, 80, 30)
    local = _camera_scene(MapCamera(43, -70, .01, 80, 30))
    world = _camera_scene(MapCamera(-43, 110, 130, 80, 30), surface=object())
    scenes = [local, world]
    # The local frame covers the centre probe. The world's old visible
    # hemisphere covers none, but its prepared surface covers the entire disk.
    assert _maps_scene._best_scene(scenes, displayed) is world
    # Full-world coverage does not displace exact or equally complete local
    # detail when its physical resolution matches the displayed view better.
    assert _maps_scene._best_scene(scenes, local.exact.camera) is local
    assert _maps_scene._best_scene(scenes, local.exact.camera.pan(.1, 0)) is local


def test_error_backoff_cancels_obsolete_pending_work_and_allows_a_later_retry(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(_maps_scene.time, "monotonic", lambda: clock[0])
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)

    def fail():
        raise RuntimeError("offline\nprivate secondary detail")

    worker.request("failed", "terrain", fail)
    threads.run()
    assert worker.request("failed", "terrain", fail) == (None, False, "offline")
    assert not threads.jobs
    obsolete = []

    def current():
        worker.request("obsolete", "terrain", lambda: obsolete.append(True) or _scene("obsolete"))
        assert worker.request("failed", "terrain", fail) == (None, False, "offline")
        return _scene("current")

    worker.request("current", "terrain", current)
    threads.run()
    assert not obsolete
    clock[0] = 13.0
    assert worker.request("failed", "terrain", lambda: _scene("recovered")) == (
        _scene("current"), True, "offline")
    threads.run()
    assert worker.request("failed", "terrain", fail) == (_scene("recovered"), False, None)


def test_an_exception_without_a_message_does_not_wedge_the_worker():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)

    def fail():
        raise RuntimeError()

    worker.request("failed", "terrain", fail)
    threads.run()
    assert worker.request("failed", "terrain", fail) == (None, False, "RuntimeError")
    worker.request("next", "terrain", lambda: _scene("next"))
    assert len(threads.jobs) == 1
    threads.run()
    assert worker.request("next", "terrain", fail) == (_scene("next"), False, None)


def test_failed_stationary_target_wakes_and_recovers_without_input(monkeypatch, timers):
    clock = [10.0]
    monkeypatch.setattr(_maps_scene.time, "monotonic", lambda: clock[0])
    threads, wakes = DeferredThreads(), queue.Queue()
    worker = SceneWorker(wake=lambda: wakes.put(True), thread_factory=threads)
    attempts = []

    def build():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("offline")
        return _scene("recovered")

    worker.request("stationary", "terrain", build)
    threads.run()
    wakes.get_nowait()  # failure asks for the error frame
    assert len(timers) == 1 and timers[0].started and timers[0].delay == 3
    for _ in range(100):
        assert worker.request("stationary", "terrain", build) == (None, False, "offline")
    assert len(timers) == 1 and not threads.jobs
    clock[0] += 3
    timers[0].callback()
    wakes.get_nowait()  # only the timer, with no input, asks for the retry frame
    worker.request("stationary", "terrain", build)
    threads.run()
    assert worker.request("stationary", "terrain", build) == (_scene("recovered"), False, None)
    assert len(attempts) == 2 and worker._retry_timer is None
    worker.stop()


def test_retry_timers_are_replaced_by_latest_target_and_ignore_stale_callbacks(monkeypatch, timers):
    clock = [10.0]
    monkeypatch.setattr(_maps_scene.time, "monotonic", lambda: clock[0])
    threads, wakes = DeferredThreads(), []
    worker = SceneWorker(wake=lambda: wakes.append(True), thread_factory=threads)

    def fail():
        raise RuntimeError("offline")

    for key in ("first", "second"):
        worker.request(key, "terrain", fail)
        threads.run()
    first, second = timers
    assert first.cancelled and not second.cancelled
    wakes.clear()
    first.callback()  # a cancelled timer that was already entering its callback
    assert not wakes and not threads.jobs
    clock[0] += 1
    worker.request("first", "terrain", fail)
    third = timers[-1]
    assert second.cancelled and third.delay == 2
    second.callback()
    first.callback()  # revisiting the same key does not revive its old token
    assert not wakes and worker._retry_timer is third
    clock[0] += 2
    third.callback()
    assert wakes == [True]
    assert worker._retry_timer is None
    worker.stop()


def test_stopping_cancels_the_retry_timer_and_suppresses_late_wakeup(timers):
    threads, wakes = DeferredThreads(), []
    worker = SceneWorker(wake=lambda: wakes.append(True), thread_factory=threads)

    def fail():
        raise RuntimeError("offline")

    worker.request("failed", "terrain", fail)
    threads.run()
    timer = timers[0]
    wakes.clear()
    worker.stop()
    assert timer.cancelled
    timer.callback()
    assert not wakes and worker._retry_timer is None


def test_ready_scenes_and_errors_have_bounded_retention():
    threads = DeferredThreads()
    worker = SceneWorker(wake=lambda: None, thread_factory=threads)
    for index in range(12):
        worker.request(index, "terrain", lambda index=index: _scene(index))
        threads.run()
    assert len(worker._ready) == 4
    assert worker.request(0, "terrain", lambda: _scene(0)) == (_scene(11), True, None)
    threads.run()

    def fail():
        raise RuntimeError("offline")

    for index in range(20, 32):
        worker.request(index, "terrain", fail)
        threads.run()
    assert len(worker._errors) == 8
    assert worker.request(20, "terrain", fail) == (_scene(0), True, None)
    worker.stop()


def test_stop_discards_queued_work_and_rejects_future_requests():
    threads = DeferredThreads()
    wakes, built = [], []
    worker = SceneWorker(wake=lambda: wakes.append(True), thread_factory=threads)
    worker.request("queued", "terrain", lambda: built.append(True) or _scene("queued"))
    worker.stop()
    threads.run()
    assert not built and not wakes
    assert worker.request("later", "terrain", lambda: None) == (None, False, None)


def test_stop_during_build_prevents_publication_wakeup_and_followup_work():
    threads = DeferredThreads()
    wakes, built = [], []
    worker = SceneWorker(wake=lambda: wakes.append(True), thread_factory=threads)

    def active():
        worker.request("pending", "terrain", lambda: built.append(True) or _scene("pending"))
        worker.stop()
        return _scene("too late")

    worker.request("active", "terrain", active)
    threads.run()
    assert not built and not wakes and not worker._ready
    assert worker.request("active", "terrain", lambda: None) == (None, False, None)
