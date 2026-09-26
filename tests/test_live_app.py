"""LiveApp: the class an app with keys subclasses to run under live_loop."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast.terminal import live as _live
from linecast.terminal.live import LiveApp, menu_box, overlay


class TestOverlay:
    def test_nothing_floating_is_the_body_itself(self):
        assert overlay("body") == "body"

    def test_a_floating_thing_rides_the_channel(self):
        assert overlay("body", "\033[3;4Hhi") == "body\x00\033[3;4Hhi"

    def test_motion_switches_ride_ahead_of_it(self):
        assert overlay("b", "x", motion=False) == "b\x00\033[?1003lx"
        assert overlay("b", "x", motion=True) == "b\x00\033[?1003hx"
        assert overlay("b", motion=True) == "b\x00\033[?1003h"


class TestPointerChip:
    """The chip never sits under the pointer glyph, which hangs down-right."""

    def _rows_cols(self, out):
        import re
        return [(int(r), int(c)) for r, c in re.findall(r"\033\[(\d+);(\d+)H", out)]

    def test_sits_below_the_pointer_with_a_clear_row(self):
        pos = self._rows_cols(_live.pointer_chip(["a", "bb"], 10, 5, 80, 24))
        assert pos == [(7, 10), (8, 10)]

    def test_flips_above_when_there_is_no_room_below(self):
        pos = self._rows_cols(_live.pointer_chip(["a", "bb"], 10, 22, 80, 24))
        assert pos == [(20, 10), (21, 10)]

    def test_slides_inward_at_the_right_edge(self):
        pos = self._rows_cols(_live.pointer_chip(["abcd"], 79, 5, 80, 24))
        assert pos == [(7, 77)]

    def test_flip_at_ends_the_chip_left_of_the_anchor(self):
        pos = self._rows_cols(_live.pointer_chip(["abcd"], 79, 5, 80, 24, flip_at=78))
        assert pos == [(7, 74)]

    def test_pads_to_one_width_with_the_fill(self):
        out = _live.pointer_chip(["a", "bb"], 10, 5, 80, 24, pad_bg="<BG>")
        assert "a<BG> " in out

    def test_nothing_from_no_lines(self):
        assert _live.pointer_chip([], 10, 5, 80, 24) == ""


class TestMenuBox:
    def test_fits_a_screen_narrower_than_its_frame(self):
        """A box has nothing inside on three columns, and does not spin
        forever trimming an empty row to a negative width."""
        out = menu_box(["abc"], 3, 10)
        assert "┌┐" in out and "││" in out and "└┘" in out

    def test_trims_rows_to_the_screen(self):
        out = menu_box(["abcdef"], 8, 10, title="t")
        assert "│abcd│" in out


class TestHooks:
    def test_a_bare_app_hands_the_loop_nothing(self):
        assert LiveApp().hooks() == {}

    def test_only_overrides_are_handed_over(self):
        class App(LiveApp):
            def on_wheel(self, direction, col, row):
                return True

            def text_mode(self):
                return True

        app = App()
        hooks = app.hooks()
        assert set(hooks) == {"on_wheel", "text_mode"}
        assert hooks["on_wheel"](1, 1, 1) is True
        assert hooks["text_mode"].__self__ is app

    def test_the_defaults_do_nothing(self):
        app = LiveApp()
        assert app.on_action("x") is False
        assert app.on_drag(1, 1, True) is False
        assert app.on_wheel(1, 1, 1) is False
        assert app.intercept("quit") is False
        assert app.on_click(1, 1) is False
        assert app.on_open(0) is None
        assert app.play_gate() is True
        assert app.text_mode() is False
        assert app.stop() is None
        with pytest.raises(NotImplementedError):
            app.render()


class TestRun:
    def test_run_hands_the_loop_the_app(self, monkeypatch):
        seen = {}

        def fake_loop(render_fn, **kw):
            seen["render"] = render_fn
            seen.update(kw)

        monkeypatch.setattr(_live, "live_loop", fake_loop)

        class App(LiveApp):
            interval = 7
            auto_play = True
            play_interval = 0.2
            scroll_step = 30
            stopped = False

            def render(self, **frame):
                return "frame"

            def on_action(self, key):
                return key == "+"

            def stop(self):
                self.stopped = True

        app = App()
        app.run()
        assert seen["render"].__self__ is app
        assert seen["interval"] == 7 and seen["mouse"] is True
        assert seen["auto_play"] is True and seen["play_interval"] == 0.2
        assert seen["scroll_step"] == 30
        assert seen["on_action"]("+") is True
        assert "on_wheel" not in seen and "on_drag" not in seen
        assert app.stopped

    def test_stop_runs_even_when_the_loop_raises(self, monkeypatch):
        def fake_loop(render_fn, **kw):
            raise SystemExit(130)

        monkeypatch.setattr(_live, "live_loop", fake_loop)
        parked = []

        class App(LiveApp):
            def render(self, **frame):
                return ""

            def stop(self):
                parked.append(1)

        with pytest.raises(SystemExit):
            App().run()
        assert parked == [1]


class TestBusyToast:
    def test_animates_until_dismissed_and_keeps_one_repaint_pending(self, monkeypatch):
        from unittest.mock import Mock
        from linecast.terminal.spinner import SPINNER_FRAMES
        timer = Mock()
        make_timer = Mock(return_value=timer)
        monkeypatch.setattr(_live.threading, 'Timer', make_timer)
        clock = [0.0]
        monkeypatch.setattr(_live._time, 'monotonic', lambda: clock[0])
        view = LiveApp()
        view.flash(['Loading Kyoto…'], busy=True)
        first = view.flash_overlay(80, 24)
        clock[0] = 0.081
        second = view.flash_overlay(80, 24)
        assert SPINNER_FRAMES[0] in first and SPINNER_FRAMES[1] in second
        assert 'Loading Kyoto…' in second and '╭' in second
        assert make_timer.call_count == 1
        # Loading must outlive the ordinary three-second flash lifetime.
        clock[0] = 60
        assert view.flash_overlay(80, 24)
        view.clear_flash()
        timer.cancel.assert_called_once()
        assert view.flash_overlay(80, 24) == ''

    def test_repaint_rearms_even_when_render_happens_inside_wakeup(self, monkeypatch):
        from unittest.mock import Mock
        make_timer = Mock(side_effect=lambda *args: Mock())
        monkeypatch.setattr(_live.threading, 'Timer', make_timer)
        view = LiveApp()
        monkeypatch.setattr(_live, 'nudge', lambda: view.flash_overlay(80, 24))
        view.flash(['Loading Paris…'], busy=True)
        callback = make_timer.call_args.args[1]
        callback()
        assert make_timer.call_count == 2
        # A replaced or cancelled timer cannot resurrect itself.
        view.clear_flash()
        callback()
        assert make_timer.call_count == 2

    @pytest.mark.parametrize('cols,rows', [(1, 1), (7, 3), (8, 4), (20, 8), (80, 24)])
    def test_toast_fits_small_screens_and_wide_place_names(self, cols, rows):
        import re
        from linecast.terminal.graphics import visible_len
        output = _live.toast_box('Loading ' + '京都' * 50, cols, rows, icon='⠋')
        positions = re.findall(r'\033\[(\d+);(\d+)H(.*?)(?=\033\[\d+;\d+H|$)', output)
        assert positions
        for row, col, text in positions:
            assert 1 <= int(row) <= rows
            assert 1 <= int(col) <= cols
            assert int(col) - 1 + visible_len(text) <= cols
