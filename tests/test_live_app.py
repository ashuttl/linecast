"""LiveApp: the class an app with keys subclasses to run under live_loop."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _live
from linecast._live import LiveApp, overlay


class TestOverlay:
    def test_nothing_floating_is_the_body_itself(self):
        assert overlay("body") == "body"

    def test_a_floating_thing_rides_the_channel(self):
        assert overlay("body", "\033[3;4Hhi") == "body\x00\033[3;4Hhi"

    def test_motion_switches_ride_ahead_of_it(self):
        assert overlay("b", "x", motion=False) == "b\x00\033[?1003lx"
        assert overlay("b", "x", motion=True) == "b\x00\033[?1003hx"
        assert overlay("b", motion=True) == "b\x00\033[?1003h"


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
