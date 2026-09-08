"""Deterministic live-loop scheduling checks, without a real terminal."""

from collections import deque
import io
from types import SimpleNamespace

import pytest

from linecast import _live, _theme


GAP = object()


@pytest.fixture
def loop(monkeypatch):
    class Harness:
        def __init__(self):
            self.actions = deque()
            self.now = 0.0
            self.state = 0
            self.frames = []
            self.gestures = []
            self.woken = False
            self.on_render = None
            self.output = io.StringIO()

        def drain(self):
            self.woken = False

        def readable(self, *_):
            return bool(self.actions and self.actions[0] is not GAP)

        def wait(self, timeout):
            self.now += min(0.001, timeout)
            if self.readable():
                return 'input'
            if self.woken:
                self.woken = False
                return 'wake'
            assert self.actions, 'test ran out of scheduled input'
            assert self.actions.popleft() is GAP
            return 'timeout'

        def render(self, **frame):
            self.frames.append((self.now, self.state, frame))
            body = str(self.state)
            if self.on_render is not None:
                self.on_render()
            return body

        def action(self, key):
            self.state += 1
            return True

        def drag(self, dc, dr, done):
            self.state = dc
            self.gestures.append(('drag', dc, dr, done))
            return True

        def click(self, col, row):
            self.gestures.append(('click', col, row))
            return True

        def run(self, actions, **hooks):
            self.actions.extend(actions)
            defaults = dict(on_action=self.action, on_drag=self.drag,
                            on_click=self.click)
            defaults.update(hooks)
            _live.live_loop(self.render, mouse=True, interval=3600, **defaults)

    harness = Harness()
    terminal = SimpleNamespace(fd=0, install=lambda: None, set_cbreak=lambda: None,
                               drain=harness.drain, close=lambda: None,
                               wait=harness.wait)
    monkeypatch.setattr(_live._term, 'LiveTerminal', lambda fd: terminal)
    monkeypatch.setattr(_live._term, 'wait_readable', harness.readable)
    monkeypatch.setattr(_live.sys, 'stdin', SimpleNamespace(fileno=lambda: 0))
    monkeypatch.setattr(_live.sys, 'stdout', harness.output)
    monkeypatch.setattr(_live, '_read_key', lambda fd, text=False: harness.actions.popleft())
    monkeypatch.setattr(_live._time, 'monotonic', lambda: harness.now)
    monkeypatch.setattr(_theme, 'poll_interval', lambda: 0)
    monkeypatch.setattr(_theme, 'watch_path', lambda: None)
    monkeypatch.setattr(_theme, 'can_reprobe', lambda: False)
    return harness


def test_changed_key_followed_by_ignored_input_still_paints(loop):
    loop.run(['key:d', None, GAP, 'quit'])
    assert [frame[1] for frame in loop.frames] == [0, 1]


def test_changed_wheel_followed_by_clamped_wheel_still_paints(loop):
    def wheel(direction, col, row):
        if loop.state:
            return False
        loop.state = 1
        return True

    up = ('mouse', 64, 5, 5, False)
    loop.run([up, up, GAP, 'quit'], on_wheel=wheel)
    assert [frame[1] for frame in loop.frames] == [0, 1]


def test_continuous_drag_yields_to_painting_and_preserves_release(loop):
    motions = [('mouse', 32, x + 1, 1, False) for x in range(1, 101)]
    loop.run([('mouse', 0, 1, 1, False), *motions,
              ('mouse', 0, 101, 1, True), GAP, 'quit'])
    assert any(0 < frame[1] < 100 for frame in loop.frames)
    assert loop.frames[-1][1] == 100
    assert loop.gestures[-1] == ('drag', 100, 0, True)
    assert sum(gesture[-1] is True for gesture in loop.gestures) == 1
    # One input event may straddle the budget; the synthetic event costs 1 ms.
    assert max(b[0] - a[0] for a, b in zip(loop.frames, loop.frames[1:])) <= (
        _live._INPUT_BATCH_SECONDS + 0.001001)


def test_queued_motion_release_and_click_keep_semantic_order(loop):
    loop.run([('mouse', 0, 1, 1, False), ('mouse', 32, 4, 2, False),
              ('mouse', 0, 4, 2, True), ('mouse', 0, 7, 3, False),
              ('mouse', 0, 7, 3, True), GAP, 'quit'])
    assert loop.gestures == [('drag', 3, 1, False), ('drag', 3, 1, True),
                             ('click', 7, 3), ('drag', 0, 0, True)]


def test_worker_wakeup_during_render_survives_until_next_frame(loop):
    def complete_once():
        if len(loop.frames) == 1:
            loop.state = 1
            loop.woken = True

    loop.on_render = complete_once
    loop.run([GAP, 'quit'])
    assert [frame[1] for frame in loop.frames] == [0, 1]


def test_frame_scheduling_does_not_use_wall_clock(loop, monkeypatch):
    def wall_clock():
        raise AssertionError('wall-clock adjustment must not affect scheduling')

    monkeypatch.setattr(_live._time, 'time', wall_clock)
    loop.run(['key:d', GAP, 'quit'])
    assert loop.frames[-1][1] == 1


def test_left_press_interrupts_before_queued_motion_and_paints_the_stop(loop):
    loop.state = 1  # autonomous motion is active
    events = []

    def interrupt():
        events.append('interrupt')
        loop.state = 0
        return True

    def drag(dc, dr, done):
        assert loop.state == 0
        events.append(('drag', dc, dr, done))
        return True

    loop.run([('mouse', 35, 1, 1, False),  # hover cannot interrupt
              ('mouse', 0, 1, 1, False), None,
              ('mouse', 32, 4, 2, False), ('mouse', 32, 5, 2, False),
              ('mouse', 0, 5, 2, True), GAP, 'quit'],
             on_interrupt=interrupt, on_drag=drag)
    assert [frame[1] for frame in loop.frames[:2]] == [1, 0]
    assert events == ['interrupt', ('drag', 3, 1, False),
                      ('drag', 4, 1, False), ('drag', 4, 1, True)]


def test_help_interrupts_after_synthetic_release_and_does_not_restart_on_close(loop):
    from linecast._help import HelpPanel

    help_panel = HelpPanel('sky')
    events, painted = [], []

    def interrupt():
        events.append('interrupt')
        loop.state = 0
        return True

    def drag(dc, dr, done):
        events.append(('drag', dc, dr, done))
        loop.state = int(done)  # releasing starts autonomous motion
        return True

    loop.on_render = lambda: painted.append((help_panel.open, loop.state))
    loop.run([('mouse', 0, 1, 1, False), ('mouse', 32, 4, 2, False),
              'key:?', ('mouse', 35, 9, 9, False), 'escape',
              ('mouse', 0, 4, 2, True), GAP, 'quit'],
             on_interrupt=interrupt, on_drag=drag, help_panel=help_panel)
    assert events == ['interrupt', ('drag', 3, 1, False),
                      ('drag', 3, 1, True), 'interrupt']
    assert (True, 0) in painted
    assert all(state == 0 for _, state in painted)
    assert not help_panel.open


def test_opening_help_interrupts_without_a_drag_callback(loop):
    from linecast._help import HelpPanel

    interrupts = []
    loop.run(['key:?', 'key:?', GAP, 'quit'], help_panel=HelpPanel('sky'),
             on_drag=None, on_interrupt=lambda: interrupts.append(True))
    assert interrupts == [True]
