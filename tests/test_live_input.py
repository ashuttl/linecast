"""Tests for _read_key's text-entry mode and the new key bindings.

No terminal needed: bytes are written to an os.pipe() and the read end
is handed to _read_key, exactly as cbreak stdin would deliver them.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._live import _read_key


@pytest.fixture
def pipe():
    r, w = os.pipe()
    yield r, w
    for fd in (r, w):
        try:
            os.close(fd)
        except OSError:
            pass


def _key(pipe, data, text=False):
    r, w = pipe
    os.write(w, data)
    return _read_key(r, text=text)


class TestTextMode:
    def test_ascii_char(self, pipe):
        assert _key(pipe, b"a", text=True) == "char:a"

    def test_uppercase_and_punctuation(self, pipe):
        assert _key(pipe, b"Q", text=True) == "char:Q"  # not 'quit'
        os.write(pipe[1], b"/")
        assert _read_key(pipe[0], text=True) == "char:/"  # not 'key:/'

    def test_space_is_a_char_not_reset(self, pipe):
        assert _key(pipe, b" ", text=True) == "char: "

    def test_utf8_two_byte(self, pipe):
        assert _key(pipe, "é".encode(), text=True) == "char:é"

    def test_utf8_three_byte(self, pipe):
        assert _key(pipe, "東".encode(), text=True) == "char:東"

    def test_utf8_four_byte(self, pipe):
        # U+1F30D; width handling is the renderer's problem, capture works
        assert _key(pipe, "🌍".encode(), text=True) == "char:🌍"

    def test_backspace_both_encodings(self, pipe):
        assert _key(pipe, b"\x7f", text=True) == "key:backspace"
        os.write(pipe[1], b"\x08")
        assert _read_key(pipe[0], text=True) == "key:backspace"

    def test_ctrl_u_kills_line(self, pipe):
        assert _key(pipe, b"\x15", text=True) == "key:kill"

    def test_enter(self, pipe):
        assert _key(pipe, b"\r", text=True) == "key:enter"

    def test_other_control_bytes_dropped(self, pipe):
        assert _key(pipe, b"\x01", text=True) is None  # ctrl-A

    def test_stray_continuation_byte_dropped(self, pipe):
        # a continuation byte with no lead is invalid UTF-8
        assert _key(pipe, b"\x80", text=True) is None

    def test_truncated_utf8_dropped(self, pipe):
        # lead byte promising 2 more bytes, only lead arrives ->
        # the 50 ms continuation read times out and the key is dropped
        assert _key(pipe, b"\xe6", text=True) is None

    def test_arrows_still_navigate_while_typing(self, pipe):
        assert _key(pipe, b"\033[A", text=True) == "fwd"
        os.write(pipe[1], b"\033[B")
        assert _read_key(pipe[0], text=True) == "back"

    def test_mouse_still_decodes_while_typing(self, pipe):
        assert _key(pipe, b"\033[<0;12;7M", text=True) == \
            ("mouse", 0, 12, 7, False)


class TestNewBindings:
    def test_new_maps_keys(self, pipe):
        for data, action in ((b"v", "key:v"), (b"V", "key:v"),
                             (b"p", "key:p"), (b"P", "key:p"),
                             (b"d", "key:d"), (b"D", "key:d"),
                             (b"l", "key:l"), (b"L", "key:l"),
                             (b"r", "key:r"), (b"R", "key:r"),
                             (b"/", "key:/"), (b"?", "key:?")):
            os.write(pipe[1], data)
            assert _read_key(pipe[0]) == action

    def test_existing_bindings_untouched(self, pipe):
        for data, action in ((b"q", "quit"), (b"o", "open"),
                             (b" ", "reset"), (b"+", "key:+"),
                             (b"t", "key:t"), (b"s", "key:s"),
                             (b"\r", "key:enter")):
            os.write(pipe[1], data)
            assert _read_key(pipe[0]) == action

    def test_unbound_printables_still_dropped(self, pipe):
        # letters outside the whitelist return None with text off —
        # the pre-existing contract other commands rely on
        for data in (b"a", b"z", b"1", b"."):
            os.write(pipe[1], data)
            assert _read_key(pipe[0]) is None


class TestNudge:
    """_live.nudge repaints a running live loop and is a no-op otherwise."""

    def test_sends_sigwinch_only_while_a_loop_runs(self, monkeypatch):
        import signal
        from linecast import _live
        sent = []
        monkeypatch.setattr(_live.os, "kill", lambda pid, sig: sent.append((pid, sig)))
        monkeypatch.setattr(_live, "_running", False)
        _live.nudge()
        assert sent == []
        monkeypatch.setattr(_live, "_running", True)
        _live.nudge()
        assert sent == [(os.getpid(), signal.SIGWINCH)]

    def test_radar_frames_nudge_is_the_live_one(self):
        from linecast import _live, _radar_frames
        assert _radar_frames._nudge is _live.nudge


_LOOP_EXIT_CHILD = """
import json, os, signal, sys, tempfile
from linecast import _live
hits = []
def mine(*_):
    hits.append(1)
signal.signal(signal.SIGWINCH, mine)
_live.live_loop(lambda offset_minutes=0, **kw: ".", interval=5)
# the pipe's descriptor numbers are free again: the next two opens take
# them, as a cache file written by a late worker would
files = [open(os.path.join(os.environ["T"], name), "wb") for name in ("a", "b")]
_live.nudge()                             # a worker landing after the loop
os.kill(os.getpid(), signal.SIGWINCH)     # and a resize, for good measure
restored = signal.getsignal(signal.SIGWINCH) is mine
for f in files:
    f.close()
sizes = [os.path.getsize(f.name) for f in files]
print(json.dumps({"restored": restored, "hits": len(hits),
                  "running": _live._running, "sizes": sizes}),
      file=sys.stderr)
"""


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pty")
def test_loop_exit_puts_the_sigwinch_handler_back(tmp_path):
    """After live_loop returns, nudge() is a no-op, the handler installed
    before the loop is back, and nothing is written into whatever file
    now holds the wake pipe's descriptor numbers."""
    import json
    import select
    import subprocess
    import time
    master, slave = os.openpty()
    env = dict(os.environ, LINECAST_THEME="off", LINECAST_THEME_POLL="0",
               LINECAST_THEME_WATCH="", PYTHONPATH=_src, T=str(tmp_path))
    proc = subprocess.Popen([sys.executable, "-c", _LOOP_EXIT_CHILD],
                            stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                            env=env, close_fds=True)
    os.close(slave)
    seen = b""
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline and proc.poll() is None:
            ready, _, _ = select.select([master], [], [], 0.1)
            if master in ready:
                try:
                    seen += os.read(master, 65536)
                except OSError:
                    break
            if b"\x1b[?1049h" in seen and b"." in seen:
                os.write(master, b"q")   # the loop is up: quit it
                seen = b""
        err = proc.communicate(timeout=5)[1]
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)
    result = json.loads(err.decode().strip().splitlines()[-1])
    assert result == {"restored": True, "hits": 1, "running": False,
                      "sizes": [0, 0]}, err
