"""Fetches run side by side, on threads that never hold up the exit.

A view that asks several providers at once -- weather's forecast, air,
alerts and climate; a tide station's curve, extremes, axis and waves --
submits each fetch to a Fanout, which starts it on a daemon thread of
its own and hands back a Future, then settles each future in turn.
A concurrent.futures pool would do the same, but its workers are joined
when the pool shuts down and again at interpreter exit, so a provider
stuck in a thirty-second timeout keeps Ctrl-C waiting for it. A daemon
thread is left behind.

Settling is the second of the two tiers of failure (docs/architecture.md,
"Diagnostics"): a provider absorbs its own transport failures, and what
it raises beyond them is caught here, logged with its traceback, and
answered with the fallback, so it costs the view that one entry.
"""

import threading
import time
from concurrent.futures import Future, TimeoutError
from typing import Any, Callable

from linecast._log import log_failure


class Fanout:
    """Fetches started side by side, sharing one deadline.

    `deadline` is how long, in seconds from now, the whole fan-out may
    take: a fetch submitted after it is not started, and settling stops
    waiting at it; results already in are kept. None waits for every
    fetch for as long as it takes.
    """

    def __init__(self, deadline: float | None = None) -> None:
        self._deadline = None if deadline is None else time.monotonic() + deadline

    def submit(self, fetch: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """fetch(*args, **kwargs), started on a daemon thread."""
        future: Future = Future()
        if self._deadline is not None and time.monotonic() >= self._deadline:
            future.set_exception(TimeoutError("fetch deadline reached"))
            return future

        def run():
            try:
                future.set_result(fetch(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

        threading.Thread(target=run, daemon=True).start()
        return future

    def settle(self, future: Future, what: str, fallback: Any = None,
               patience: float | None = None, tag: str = "worker",
               note: str = "omitted") -> Any:
        """The future's result, or `fallback` with one debug line.

        `patience` waits less than the deadline for a fetch the caller
        can do without for now. A fetch that raised is logged under
        `tag` with its traceback, and `note` saying what the view does
        without it: a worker that failed is the one thing a --debug
        transcript exists to explain.
        """
        wait = None if self._deadline is None else max(0, self._deadline - time.monotonic())
        why = "omitted after fetch deadline"
        if patience is not None and (wait is None or patience < wait):
            wait, why = patience, "left for the live view to fill in"
        try:
            return future.result(timeout=wait)
        except TimeoutError as exc:
            log_failure(tag, what, exc, fallback=why)
            return fallback
        except Exception as exc:
            log_failure(tag, what, exc, fallback=note, trace=True)
            return fallback
