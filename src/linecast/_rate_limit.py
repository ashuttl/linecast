"""Space provider requests across all workers in this process."""

import threading
import time

from linecast._runtime import debug_log


class RateLimit:
    """A callable gate with at least `interval` seconds between admissions.

    Each provider keeps one gate. Hold the lock through the wait so
    concurrent workers cannot sleep toward the same deadline. Measure
    the next interval from the actual wakeup, which may be much later
    than requested when the machine is busy or has been suspended.
    """

    def __init__(self, interval, name):
        self.interval = interval
        self.name = name
        self._last = None
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            now = time.monotonic()
            if self._last is not None:
                wait = self.interval - (now - self._last)
                if wait > 0:
                    debug_log(f"{self.name}: waiting {wait:.2f}s for the rate limit")
                    time.sleep(wait)
                    now = time.monotonic()
            self._last = now
