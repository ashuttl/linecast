"""Braille loading spinner shown while blocking on the network."""

import sys
import threading

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧"
_MUTED = (150, 155, 170)


class Spinner:
    """Animated braille spinner on stdout while work happens elsewhere.

    Use as a context manager, or via start()/stop() when the blocking work
    doesn't fit one lexical block. A no-op when stdout isn't a TTY. stop()
    is idempotent and clears the spinner line.
    """

    def __init__(self, label="Loading"):
        self._label = label
        self._stop = None
        self._thread = None

    def start(self):
        if self._thread is not None or not sys.stdout.isatty():
            return self
        from linecast._color import fg, RESET
        self._stop = threading.Event()
        stop = self._stop

        def spin():
            i = 0
            while not stop.wait(0.08):
                sys.stdout.write(
                    f"\r {fg(*_MUTED)}{SPINNER_FRAMES[i % len(SPINNER_FRAMES)]}"
                    f" {self._label}{RESET} ")
                sys.stdout.flush()
                i += 1

        self._thread = threading.Thread(target=spin, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
