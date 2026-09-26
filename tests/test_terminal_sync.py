"""linecast keeps pace with the terminal, and leaves nothing behind in it.

Every question linecast asks the terminal — the colour probe at
startup, and each frame of a live view — ends with a cursor position
query.  The terminal answers in order, so the reply says it has read
everything before it: the colour probe waits for that reply instead of
a fixed hundred milliseconds (issue #92: iTerm answering the sixteenth
colour after linecast had stopped listening, onto the shell's command
line), the live loop holds each frame until the last one was read, and
quitting drains what the terminal is still sending before the tty goes
back to the shell.
"""

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast.terminal import theme as _theme  # noqa: E402
from linecast.terminal import term as _term
from linecast.terminal.live import _read_key  # noqa: E402

needs_pty = pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pty")


@pytest.fixture
def pipe():
    r, w = os.pipe()
    yield r, w
    for fd in (r, w):
        try:
            os.close(fd)
        except OSError:
            pass


@pytest.fixture
def fresh_answer(monkeypatch):
    """Each test starts not knowing whether the terminal answers."""
    monkeypatch.setattr(_term, "answered", None)


class TestReadKey:
    def test_a_cursor_report_is_an_ack(self, pipe):
        r, w = pipe
        os.write(w, b"\033[24;80R")
        assert _read_key(r) == "ack"
        os.write(w, b"\033[1;1R")
        assert _read_key(r, text=True) == "ack"   # while typing too

    def test_the_key_after_it_is_still_a_key(self, pipe):
        r, w = pipe
        os.write(w, b"\033[24;80Rq")
        assert _read_key(r) == "ack"
        assert _read_key(r) == "quit"


class TestReadUntilReply:
    def test_returns_what_came_before_the_reply(self, pipe, fresh_answer):
        r, w = pipe
        os.write(w, b"\033]11;rgb:1e1e/1e1e/2e2e\007\033[3;1R")
        buf, answered = _term.read_until_reply(r, 1.0)
        assert answered is True
        assert buf.startswith(b"\033]11;")
        assert _term.answered is True

    def test_gives_up_at_the_timeout(self, pipe, fresh_answer):
        r, w = pipe
        os.write(w, b"\033]11;rgb:1e1e/1e1e/2e2e\007")   # no reply follows
        started = time.monotonic()
        buf, answered = _term.read_until_reply(r, 0.1)
        assert answered is False
        assert time.monotonic() - started < 1.0
        assert buf.startswith(b"\033]11;")
        assert _term.answered is False   # a pipe is not a tty: no flush, no error

    def test_a_late_answer_does_not_unmark_an_answering_terminal(self, pipe, monkeypatch):
        monkeypatch.setattr(_term, "answered", True)
        r, _w = pipe
        _term.read_until_reply(r, 0.05)
        assert _term.answered is True

    def test_waits_for_as_many_replies_as_are_owed(self, pipe, fresh_answer):
        """Two queries out, so the first reply is not the last word."""
        r, w = pipe
        os.write(w, b"\033[1;1R")
        threading.Timer(0.1, os.write, (w, b"\033[<35;3;3M\033[24;1R")).start()
        buf, answered = _term.read_until_reply(r, 1.0, replies=2)
        assert answered is True
        assert buf.endswith(b"\033[24;1R")
        assert _term.answered is True

    def test_one_reply_of_two_still_marks_the_terminal(self, pipe, fresh_answer):
        r, w = pipe
        os.write(w, b"\033[1;1R")
        _buf, answered = _term.read_until_reply(r, 0.1, replies=2)
        assert answered is False
        assert _term.answered is True


# ---------------------------------------------------------------------------
# The colour probe, against a terminal we play on a pty
# ---------------------------------------------------------------------------
def _reply_bytes(fg, bg, ansi):
    def hexpair(c):
        return "rgb:" + "/".join(f"{v:02x}{v:02x}" for v in c)
    out = [f"10;{hexpair(fg)}", f"11;{hexpair(bg)}"]
    out += [f"4;{i};{hexpair(c)}" for i, c in enumerate(ansi)]
    return b"".join(b"\033]" + r.encode() + b"\033\\" for r in out)


PALETTE = ((210, 210, 220), (18, 18, 24),
           tuple((i * 15, 40, 255 - i * 15) for i in range(16)))


class Terminal:
    """The far side of a pty: reads what linecast writes and answers it
    the way `answer` says, from a thread."""

    def __init__(self, master, answer):
        self.master = master
        self.answer = answer
        self.seen = b""
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop:
            if not select.select([self.master], [], [], 0.02)[0]:
                continue
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.seen += chunk
            reply = self.answer(self.seen)
            if reply:
                self.seen = b""
                os.write(self.master, reply)

    def stop(self):
        self._stop = True
        self.thread.join(timeout=2)


class Pty:
    """A pty whose slave side stands in for sys.stdin and sys.stdout, and
    whose master the test plays the terminal on.  attach() is called from
    the test body: pytest puts its own capture back on sys.stdout between
    a fixture and the test, so a fixture cannot do it."""

    def __init__(self):
        self.master, slave = os.openpty()
        self.stdin = os.fdopen(os.dup(slave), "rb", buffering=0)
        self.stdout = os.fdopen(os.dup(slave), "w")
        os.close(slave)

    def attach(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", self.stdin)
        monkeypatch.setattr(sys, "stdout", self.stdout)
        monkeypatch.setenv("TERM", "xterm-256color")
        return self.master

    def close(self):
        self.stdin.close()
        self.stdout.close()
        os.close(self.master)


@pytest.fixture
def pty():
    pty = Pty()
    yield pty
    pty.close()


def _unread(fd):
    """Whatever is waiting on fd right now: what a shell would read next."""
    out = b""
    while select.select([fd], [], [], 0.2)[0]:
        try:
            out += os.read(fd, 4096)
        except OSError:
            break
    return out


@needs_pty
class TestColourProbe:
    def test_waits_for_a_slow_terminal_to_finish_answering(self, pty, fresh_answer,
                                                           monkeypatch):
        """The palette arrives well after the old fixed wait would have
        given up, and not one reply is left for the shell (issue #92)."""
        def answer(seen):
            if seen.endswith(_term.CPR_QUERY):
                time.sleep(0.3)
                return _reply_bytes(*PALETTE) + b"\033[1;1R"
        terminal = Terminal(pty.attach(monkeypatch), answer)
        try:
            started = time.monotonic()
            result = _theme._query_theme_via_osc(2.0)
            took = time.monotonic() - started
        finally:
            terminal.stop()
        assert result == PALETTE
        assert 0.3 <= took < 1.5
        assert _term.answered is True
        assert _unread(sys.stdin.fileno()) == b""

    def test_a_terminal_without_colour_queries_answers_at_once(self, pty, fresh_answer,
                                                               monkeypatch):
        """No palette, but no waiting out the timeout either."""
        def answer(seen):
            if seen.endswith(_term.CPR_QUERY):
                return b"\033[1;1R"
        terminal = Terminal(pty.attach(monkeypatch), answer)
        try:
            started = time.monotonic()
            result = _theme._query_theme_via_osc(2.0)
            took = time.monotonic() - started
        finally:
            terminal.stop()
        assert result is None
        assert took < 0.5
        assert _term.answered is True

    def test_a_mute_tty_costs_the_timeout_and_nothing_more(self, pty, fresh_answer,
                                                           monkeypatch):
        terminal = Terminal(pty.attach(monkeypatch), lambda seen: None)
        try:
            started = time.monotonic()
            result = _theme._query_theme_via_osc(0.2)
            took = time.monotonic() - started
        finally:
            terminal.stop()
        assert result is None
        assert 0.2 <= took < 1.0
        assert _term.answered is False

    def test_the_width_probe_skips_a_mute_tty(self, pty, monkeypatch):
        from linecast.terminal import textwidth as _textwidth
        monkeypatch.setattr(_term, "answered", False)
        monkeypatch.setattr(_textwidth, "_CALIBRATED", False)
        terminal = Terminal(pty.attach(monkeypatch), lambda seen: None)
        try:
            started = time.monotonic()
            _textwidth.calibrate_from_terminal(timeout_s=1.0)
            took = time.monotonic() - started
        finally:
            terminal.stop()
        assert took < 0.5
        assert terminal.seen == b""   # nothing was even asked


# ---------------------------------------------------------------------------
# The live loop, in a child process on a pty
# ---------------------------------------------------------------------------
_CHILD = """
import json, os, select, sys, termios, tty
from linecast.terminal import live as _live
def render(offset_minutes=0, **kw):
    sys.stderr.write("FRAME %d\\n" % offset_minutes)
    sys.stderr.flush()
    return "."
_live.live_loop(render, interval=5, mouse=True)
# What a shell would now find waiting on the tty: nothing, if the loop
# drained the terminal's last words before handing the tty back.
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setcbreak(fd)
left = b""
while select.select([fd], [], [], 0.3)[0]:
    left += os.read(fd, 4096)
termios.tcsetattr(fd, termios.TCSADRAIN, old)
print(json.dumps({"left": left.decode("latin-1")}), file=sys.stderr)
"""

WHEEL_UP = b"\033[<64;5;5M"
CPR_QUERY = _term.CPR_QUERY


# The same loop, run so a signal that escapes it is reported instead of
# ending the child, along with whether the tty came back as it was.
_SIGNAL_CHILD = """
import json, os, signal, sys, termios
from linecast.terminal import live as _live
fd = sys.stdin.fileno()
def settings():
    # BSD marks a tty put back into canonical mode with PENDIN until the
    # next read reprocesses its input, and reports the bit through
    # tcgetattr meanwhile; it says nothing about what was restored.
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~termios.PENDIN
    return attrs
before = settings()
def render(offset_minutes=0, **kw):
    sys.stderr.write("FRAME %d\\n" % offset_minutes)
    sys.stderr.flush()
    return "."
how = "returned"
try:
    _live.live_loop(render, interval=60, mouse=True)
except KeyboardInterrupt:
    how = "KeyboardInterrupt"
except SystemExit as exc:
    how = "SystemExit %s" % exc.code
after = settings()
print(json.dumps({"how": how, "tty_restored": after == before,
                  "winch_restored": signal.getsignal(signal.SIGWINCH) == signal.SIG_DFL}),
      file=sys.stderr)
"""


class Child:
    """live_loop in a child on a pty, with the test as its terminal."""

    def __init__(self, code=_CHILD):
        self.master, slave = os.openpty()
        env = dict(os.environ, LINECAST_THEME="off", LINECAST_THEME_POLL="0",
                   LINECAST_THEME_WATCH="", TERM="xterm-256color",
                   PYTHONPATH=_src)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", code], stdin=slave, stdout=slave,
            stderr=subprocess.PIPE, env=env, close_fds=True)
        os.close(slave)
        os.set_blocking(self.proc.stderr.fileno(), False)
        self.out = b""
        self.err = b""
        self.frames = []

    def pump(self, seconds):
        """Read the child's screen and stderr for `seconds`."""
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return
            ready, _, _ = select.select([self.master, self.proc.stderr], [], [], left)
            if self.master in ready:
                try:
                    self.out += os.read(self.master, 65536)
                except OSError:
                    pass   # EIO once the child has closed its side
            if self.proc.stderr in ready:
                chunk = self.proc.stderr.read()
                if chunk:
                    self.err += chunk
                    self.frames = [int(line.split()[1]) for line in self.err.splitlines()
                                   if line.startswith(b"FRAME ")]

    def until(self, predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.pump(0.05)
        assert predicate(), (self.out, self.err)

    def queries(self):
        return self.out.count(CPR_QUERY)

    def type(self, data):
        os.write(self.master, data)

    def finish(self):
        try:
            self.until(lambda: self.proc.poll() is not None)
            self.pump(0.2)
            rest = self.proc.stderr.read() or b""
            self.err += rest
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
            os.close(self.master)
        last = self.err.decode().strip().splitlines()[-1]
        return json.loads(last)


@needs_pty
def test_frames_wait_for_the_terminal_and_quitting_leaves_nothing_behind():
    child = Child()
    # The first frame, and a cursor query after it; answer it at once.
    child.until(lambda: child.frames == [0] and child.queries() == 1)
    child.type(b"\033[1;1R")
    child.pump(0.1)

    # A wheel notch: the second frame goes out, with its query.  This
    # time the terminal is slow: it says nothing while twenty more
    # notches arrive.  The loop holds the third frame for the reply.
    child.type(WHEEL_UP)
    child.until(lambda: child.frames == [0, 15] and child.queries() == 2)
    for _ in range(20):
        child.type(WHEEL_UP)
    child.pump(0.4)
    assert child.frames == [0, 15], child.err

    # The terminal catches up: the twenty notches paint once, together.
    child.type(b"\033[1;1R")
    child.until(lambda: child.queries() == 3)
    child.pump(0.2)
    assert child.frames == [0, 15, 315], child.err
    child.type(b"\033[1;1R")

    # q.  The loop restores the screen and asks once more; before the
    # terminal answers, it sends what a real one still would: a colour
    # reply from a probe in flight and a mouse report it emitted before
    # it read the escape turning reporting off.  None of it may remain
    # for the shell.
    child.type(b"q")
    child.until(lambda: b"\033[?1049l" + CPR_QUERY in child.out)
    child.type(b"\033]4;15;rgb:ffff/ffff/ffff\033\\\033[<35;3;3M\033[24;1R")
    result = child.finish()
    assert result == {"left": ""}, child.err


@needs_pty
def test_a_terminal_that_never_answers_is_asked_once():
    child = Child()
    child.until(lambda: child.frames == [0] and child.queries() == 1)
    # No reply, ever.  A notch still paints, after a short wait, and the
    # loop stops asking.
    child.type(WHEEL_UP)
    child.until(lambda: child.frames == [0, 15])
    assert child.queries() == 1
    child.type(WHEEL_UP)
    child.until(lambda: child.frames == [0, 15, 30])
    assert child.queries() == 1
    child.type(b"q")
    result = child.finish()
    assert child.queries() == 1   # and not on the way out either
    assert result == {"left": ""}


@needs_pty
def test_a_notch_ahead_of_the_reply_still_paints():
    """The terminal got a notch before it finished reading the frame, so
    the notch sits ahead of the frame's reply in the queue.  The notch
    is held for the input behind it, as any burst is; the reply behind
    it paints nothing of its own, so the held repaint must follow it,
    not wait for the idle interval."""
    child = Child()
    child.until(lambda: child.frames == [0] and child.queries() == 1)
    child.type(b"\033[1;1R")
    child.pump(0.1)
    child.type(WHEEL_UP)
    child.until(lambda: child.frames == [0, 15] and child.queries() == 2)
    child.type(WHEEL_UP + b"\033[1;1R")
    child.until(lambda: child.frames == [0, 15, 30], seconds=2)
    child.pump(0.3)
    assert child.frames == [0, 15, 30], child.err   # and the reply painted nothing
    child.type(b"\033[1;1R")
    child.type(b"q")
    assert child.finish() == {"left": ""}


@needs_pty
def test_quitting_with_a_reply_owed_waits_for_the_last_one():
    """q arrives while the last frame's query is still unanswered.  A
    terminal that is behind answers that query first and the exit query
    after; the drain must wait for the second, or the second is what
    the shell reads."""
    child = Child()
    child.until(lambda: child.frames == [0] and child.queries() == 1)
    child.type(b"\033[1;1R")
    child.pump(0.1)
    child.type(WHEEL_UP)
    child.until(lambda: child.frames == [0, 15] and child.queries() == 2)
    child.type(b"q")
    child.until(lambda: b"\033[?1049l" + CPR_QUERY in child.out)
    child.type(b"\033[1;1R")
    child.pump(0.15)
    child.type(b"\033[24;1R")
    assert child.finish() == {"left": ""}


@needs_pty
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_a_second_signal_during_the_drain_still_restores_the_tty(signum):
    """The first signal ends the loop; the drain then waits on a terminal
    that is slow to answer.  A second signal cuts the wait short, and
    the tty and the handlers still go back before the shell gets them."""
    child = Child(_SIGNAL_CHILD)
    child.until(lambda: child.frames == [0] and child.queries() == 1)
    child.type(b"\033[1;1R")     # answered once: the drain will wait for a reply
    child.pump(0.1)
    child.proc.send_signal(signum)
    child.until(lambda: b"\033[?1049l" + CPR_QUERY in child.out)
    child.pump(0.2)
    child.proc.send_signal(signum)
    result = child.finish()
    assert result["tty_restored"], result
    assert result["winch_restored"], result
    assert result["how"] != "returned", result   # the second signal did get through
