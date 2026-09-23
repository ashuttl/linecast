"""Provider requests stay spaced even when a sleep lasts longer than asked."""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _rate_limit
from linecast.maps import route
from linecast.maps import search
from linecast._rate_limit import RateLimit


@pytest.mark.parametrize("module", [route, search])
def test_delayed_wakeup_starts_a_full_interval(module, monkeypatch):
    now = [1000.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds + 5.0  # the scheduler did not wake us on time

    monkeypatch.setattr(_rate_limit, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=sleep))
    monkeypatch.setattr(module._throttle, "_last", None)
    module._throttle()
    module._throttle()
    module._throttle()
    assert slept == [1.0, 1.0]


def test_concurrent_workers_get_separate_deadlines(monkeypatch):
    now = [1000.0]
    deadlines = []
    clock_lock = threading.Lock()

    def sleep(seconds):
        with clock_lock:
            deadline = now[0] + seconds
            deadlines.append(deadline)
        # Give other workers a chance to enter the gate while this one
        # sleeps. A gate without a lock sends them to the same deadline.
        threading.Event().wait(0.005)
        with clock_lock:
            now[0] = max(now[0], deadline)

    monkeypatch.setattr(_rate_limit, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=sleep))
    gate = RateLimit(1.0, "test")
    gate()
    ready = threading.Barrier(8)

    def worker():
        ready.wait(timeout=5)
        gate()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker) for _ in range(8)]
        for future in futures:
            future.result(timeout=5)
    assert deadlines == list(range(1001, 1009))


def test_first_request_does_not_wait_at_clock_zero(monkeypatch):
    slept = []
    monkeypatch.setattr(_rate_limit, "time", SimpleNamespace(
        monotonic=lambda: 0.0, sleep=slept.append))
    RateLimit(1.0, "test")()
    assert slept == []
