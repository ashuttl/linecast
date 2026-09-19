"""A hover chip goes when the mouse has been still for a while."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _framebuffer, _live


def run_loop(monkeypatch, script, render_fn=None, coalesce=False, **hooks):
    """Run live_loop on a fake terminal and clock.

    script is a list of (seconds of stillness, action): the terminal
    waits that long, then hands the loop the action.  Returns the
    mouse_pos of each frame.
    """
    clock = [1000.0]
    steps = iter(script)
    pending = [next(steps)]

    def wait(timeout):
        still, _ = pending[0]
        if still > timeout:
            pending[0] = (still - timeout, pending[0][1])
            clock[0] += timeout
            return 'timeout'
        clock[0] += still
        return 'input'

    def read(fd, text=False):
        action = pending[0][1]
        pending[0] = next(steps, (1e9, 'quit'))
        return action

    terminal = SimpleNamespace(fd=0, install=lambda: None, set_cbreak=lambda: None,
                               drain=lambda: None, close=lambda: None,
                               settle=lambda timeout, replies=1: None, wait=wait)
    monkeypatch.setattr(_live._term, 'LiveTerminal', lambda fd: terminal)
    monkeypatch.setenv('LINECAST_FRAME_SYNC', '0')
    monkeypatch.setattr(_live._term, 'wait_readable',
                        lambda fd, timeout: coalesce and pending[0][0] == 0)
    monkeypatch.setattr(_live, '_read_key', read)
    monkeypatch.setattr(_live, '_time', SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0]))
    monkeypatch.setattr(_live.sys, 'stdin', SimpleNamespace(fileno=lambda: 0))
    monkeypatch.setattr(_live.sys, 'stdout', io.StringIO())
    monkeypatch.setattr(_framebuffer, 'get_terminal_size', lambda: (80, 24))
    frames = []

    def render(mouse_pos=None, **_):
        frames.append(mouse_pos)
        return "."

    _live.live_loop(render_fn or render, interval=3600, mouse=True, **hooks)
    return frames


MOVE = ('mouse', 35, 4, 5, False)   # motion, no button


def test_chip_goes_after_the_mouse_is_still(monkeypatch):
    frames = run_loop(monkeypatch, [(0, MOVE), (_live._HOVER_IDLE_S + 1, 'quit')])
    assert frames == [None, (4, 5), None]


def test_chip_stays_while_the_mouse_moves(monkeypatch):
    frames = run_loop(monkeypatch, [(0, MOVE), (6, MOVE), (6, MOVE), (0, 'quit')])
    assert frames == [None, (4, 5), (4, 5), (4, 5)]


def test_chip_waits_out_a_drag(monkeypatch):
    press = ('mouse', 0, 4, 5, False)
    frames = run_loop(monkeypatch, [(0, press), (30, 'quit')],
                      on_drag=lambda *args: False)
    assert frames[-1] == (4, 5)
