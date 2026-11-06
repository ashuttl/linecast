"""A second interpreter that builds the flat views.

A street or terrain view is a second and more of pure Python, and the
frames are Python too.  On one interpreter the two share a lock, and a
build under a drag was measured at 160x45 to take the frames from
thirty a second to three — which is why the live map built nothing
while a hand was on it, and a drag past the overscan margin showed
bare ground until the hand let go.

So the live map starts a child interpreter at launch and hands it
every flat build.  The child imports the same loaders, takes up the
parent's runtime, theme and text-width calibration (none of which it
could ask a terminal for), and answers over a pipe; the parent's
loader threads block on the pipe rather than on the lock, and the
frames go on at their own pace.  The tile cache is a directory both
write atomically, so neither reads a tile the other is half way
through.

Nothing here decides what to build.  `loaders._build` asks `run` with
a pure build's name and arguments and gets the view back, and falls
through to building in-process when there is no child: `--print`, a
platform that cannot spawn one, or a child that has died.  The
protocol is pickles behind a four-byte length, one request and one
reply each, with the parent's settled state riding on every request so
a theme that changes under the live map reaches the child on its next
build.
"""

import os
import pickle
import struct
import subprocess
import sys
import threading

from linecast._log import debug_enabled, debug_log, log_failure

_LEN = struct.Struct(">I")
# how many builds the child runs at once: a destination and a view the
# camera is passing over, the two the parent's gating lets through
_CHILD_THREADS = 2
_BOOT = ("import sys; sys.path[:0] = {paths!r}; "
         "from linecast.maps.worker import serve; serve()")


class Unavailable(Exception):
    """There is no child to build this, or it went while building."""


def enabled():
    """Whether a child may be started at all (LINECAST_MAPS_WORKER=0 says no)."""
    raw = os.environ.get("LINECAST_MAPS_WORKER", "1").strip().lower()
    return raw not in ("0", "false", "off", "no", "none")


# -- the pipe -------------------------------------------------------------
def _write(stream, lock, obj):
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    with lock:
        stream.write(_LEN.pack(len(data)) + data)
        stream.flush()


def _read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _read(stream):
    head = _read_exact(stream, _LEN.size)
    if head is None:
        return None
    body = _read_exact(stream, _LEN.unpack(head)[0])
    if body is None:
        return None
    return pickle.loads(body)


# -- the parent's side ----------------------------------------------------
def snapshot():
    """What the child has to take up before it builds anything."""
    from linecast._runtime import current_runtime
    from linecast.terminal import term as _term
    from linecast.terminal import textwidth, theme
    return {
        "runtime": current_runtime(),
        "theme": theme.state(),
        "widths": textwidth.state(),
        "terminal": _term.terminal_name,
        "debug": debug_enabled(),
    }


def child_env():
    """The environment the child is started in: this one, plus what the
    terminal told this interpreter and cannot tell the child.

    The child's stdout is a pipe, so asked itself it would find no
    colour at all and bake the street fills in the no-colour palette;
    and its size in pixels is nobody's, so it would take the fallback
    cell shape and draw every view a sixth wider than the terminal's
    font does.  Both have overrides the program already honours, and
    the child is given the parent's answers through them.
    """
    from linecast.terminal.color import color_mode
    from linecast.terminal.framebuffer import cell_aspect
    env = dict(os.environ)
    env["LINECAST_COLOR"] = color_mode()
    env["LINECAST_CELL_ASPECT"] = f"{cell_aspect():.6f}"
    return env


class Builder:
    """One child interpreter and the requests out to it."""

    def __init__(self):
        self._proc = None
        self._dead = False
        self._lock = threading.Lock()        # the pending table
        self._write_lock = threading.Lock()  # one request on the pipe at a time
        self._pending = {}                   # rid -> (event, slot)
        self._next = 0

    def start(self):
        """Spawn the child, once.  Quiet when it cannot be."""
        with self._lock:
            if self._proc is not None or self._dead or not enabled():
                return
            paths = [p for p in sys.path if isinstance(p, str)]
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, "-c", _BOOT.format(paths=paths)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=None if debug_enabled() else subprocess.DEVNULL,
                    close_fds=True, env=child_env())
            except (OSError, ValueError) as exc:
                self._dead = True
                log_failure("maps/worker", "start", exc,
                            fallback="views build in-process")
                return
        threading.Thread(target=self._reader, daemon=True,
                         name="maps worker replies").start()
        debug_log(f"maps worker: child {self._proc.pid} started")

    def alive(self):
        proc = self._proc
        return proc is not None and not self._dead and proc.poll() is None

    def run(self, kind, *args):
        """Build `kind` with `args` in the child and return what it made.

        Blocks the calling thread — a loader's own, never the loop's —
        for as long as the build takes.  Raises Unavailable when there
        is no child or it goes while this is out, and re-raises a
        RuntimeError the build itself raised, with its message.
        """
        if not self.alive():
            raise Unavailable()
        event, slot = threading.Event(), [None]
        with self._lock:
            rid = self._next
            self._next += 1
            self._pending[rid] = (event, slot)
        try:
            _write(self._proc.stdin, self._write_lock,
                   (rid, kind, args, snapshot()))
        except (OSError, ValueError, pickle.PicklingError) as exc:
            with self._lock:
                self._pending.pop(rid, None)
            self._lost(exc)
            raise Unavailable() from exc
        event.wait()
        reply = slot[0]
        if reply is None:
            raise Unavailable()
        ok, payload = reply
        if ok:
            return payload
        raise RuntimeError(payload)

    def _reader(self):
        proc = self._proc
        try:
            while True:
                msg = _read(proc.stdout)
                if msg is None:
                    break
                rid, ok, payload = msg
                with self._lock:
                    waiting = self._pending.pop(rid, None)
                if waiting is not None:
                    event, slot = waiting
                    slot[0] = (ok, payload)
                    event.set()
        except Exception as exc:   # a torn frame, a pickle it cannot load
            self._lost(exc)
            return
        self._lost(None)

    def _lost(self, exc):
        """The child is gone: every request out to it comes back empty."""
        with self._lock:
            if self._dead:
                return
            self._dead = True
            waiting = list(self._pending.values())
            self._pending.clear()
        if exc is not None:
            log_failure("maps/worker", "child", exc,
                        fallback="views build in-process")
        else:
            debug_log("maps worker: child exited")
        for event, _slot in waiting:
            event.set()

    def stop(self):
        """Close the pipe; the child exits on it."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


_builder = Builder()


def start():
    _builder.start()


def alive():
    return _builder.alive()


def run(kind, *args):
    return _builder.run(kind, *args)


def stop():
    _builder.stop()


# -- the child's side -----------------------------------------------------
def _adopt(state, last):
    """Install the parent's settled state, where it has changed."""
    if state == last:
        return
    from linecast._log import set_debug
    from linecast._runtime import set_current
    from linecast.terminal import bidi as _bidi
    from linecast.terminal import term as _term
    from linecast.terminal import textwidth, theme
    set_debug(state.get("debug", False))
    if state.get("runtime") is not None:
        set_current(state["runtime"])
    theme.adopt(state["theme"])
    textwidth.adopt(state["widths"])
    if _term.terminal_name != state.get("terminal"):
        _term.terminal_name = state.get("terminal")
        _bidi.refresh_mode()


def _builds():
    from linecast.maps import loaders
    kinds = dict(loaders._BUILDS)
    kinds["echo"] = lambda *args: args
    kinds["echo_env"] = _echo_env
    return kinds


def _echo_env():
    """What this interpreter took from its environment: for a check that
    the parent handed over what its terminal told it."""
    from linecast.terminal.color import color_mode
    from linecast.terminal.framebuffer import cell_aspect
    return {"color": color_mode(), "aspect": cell_aspect()}


def serve(inp=None, out=None):
    """Answer build requests on stdin until it closes.

    stdout is the reply pipe and nothing else: it is taken at the
    start and the descriptor is pointed at stderr, so a stray print in
    a loader cannot tear a frame.
    """
    if inp is None:
        inp = sys.stdin.buffer
    if out is None:
        out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout = sys.stderr
    write_lock = threading.Lock()
    slots = threading.BoundedSemaphore(_CHILD_THREADS)
    kinds = _builds()
    last = [None]

    def answer(rid, kind, args):
        try:
            try:
                build = kinds[kind]
            except KeyError:
                raise RuntimeError(f"no build called {kind!r}") from None
            reply = (rid, True, build(*args))
        except Exception as exc:
            reply = (rid, False, str(exc) or type(exc).__name__)
        try:
            _write(out, write_lock, reply)
        except (OSError, ValueError, pickle.PicklingError) as exc:
            try:
                _write(out, write_lock,
                       (rid, False, f"{type(exc).__name__}: {exc}"))
            except (OSError, ValueError):
                pass
        finally:
            slots.release()

    while True:
        msg = _read(inp)
        if msg is None:
            return
        rid, kind, args, state = msg
        try:
            _adopt(state, last[0])
        except Exception as exc:
            log_failure("maps/worker", "adopt", exc, fallback="builds go on")
        last[0] = state
        slots.acquire()
        threading.Thread(target=answer, args=(rid, kind, args),
                         daemon=True, name=f"build {kind}").start()
