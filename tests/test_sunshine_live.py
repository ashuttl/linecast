"""SunshineApp: the live sunshine view's keys and state, with no
terminal behind them."""

from datetime import datetime, timedelta, timezone

import pytest

from linecast._runtime import RuntimeConfig
from linecast.sunshine import live as _sun_live
from linecast.sunshine.live import SunshineApp
from linecast.terminal import live as _live
from linecast.terminal import textwidth

ET = timezone(timedelta(hours=-4))
NOW = datetime(2026, 9, 1, 14, 30, tzinfo=ET)


@pytest.fixture
def frames(monkeypatch):
    """What each render asked of the day and the year views."""
    seen = []
    monkeypatch.setattr(_sun_live, "render",
                        lambda *a, **k: seen.append(("day", a, k)) or "day")
    monkeypatch.setattr("linecast.sunshine.year.render_year",
                        lambda *a, **k: seen.append(("year", a, k)) or "year")
    return seen


@pytest.fixture
def app():
    runtime = RuntimeConfig(live=True, icons="emoji", lang="en", oneline=False)
    return SunshineApp(lambda: NOW, 43.7, -70.3, runtime, location_label="Westbrook")


class TestScrub:
    def test_the_wheel_and_arrows_move_the_day_a_quarter_hour(self, app, frames):
        assert app.on_wheel(1, 10, 10) is True
        assert app.intercept("fwd") is True
        assert app.intercept("back") is True
        assert app.minutes == 15
        app.render()
        kind, (_lat, _lng, doy, now_hour), kw = frames[-1]
        assert kind == "day" and kw["offset_minutes"] == 15
        assert kw["now"] == NOW + timedelta(minutes=15)
        assert now_hour == pytest.approx(14.75) and doy == 244

    def test_space_returns_to_now(self, app):
        app.on_wheel(-1, 10, 10)
        assert app.intercept("reset") is True
        assert app.minutes == 0

    def test_the_year_view_takes_them_without_moving(self, app, frames):
        app.on_wheel(1, 10, 10)
        assert app.on_action("v") is True and app.year
        assert app.on_wheel(1, 10, 10) is True
        assert app.intercept("back") is True
        assert app.minutes == 15
        app.render(mouse_pos=(40, 12))
        kind, _args, kw = frames[-1]
        assert kind == "year" and kw["mouse_pos"] == (40, 12)

    def test_the_day_is_where_it_was_left(self, app, frames):
        app.intercept("fwd")
        app.on_action("v")
        assert app.on_action("y") is True and not app.year
        app.render()
        assert frames[-1][2]["offset_minutes"] == 15


class TestKeys:
    def test_v_and_y_flip_the_view(self, app):
        assert app.on_action("v") is True and app.year
        assert app.on_action("v") is True and not app.year
        assert app.on_action("y") is True and app.year

    def test_other_keys_pass_through(self, app):
        assert app.on_action("t") is False
        assert app.intercept("key:t") is False
        assert app.intercept("quit") is False
        assert not app.year and app.minutes == 0

    def test_opened_with_year(self, frames):
        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        app = SunshineApp(lambda: NOW, 43.7, -70.3, runtime, year=True, dst=True)
        app.render()
        kind, _args, kw = frames[-1]
        assert kind == "year" and kw["dst"] is True and kw["fullscreen"] is False

    def test_the_traditional_hours_are_read_at_the_shown_moment(self, frames):
        runtime = RuntimeConfig(live=True, icons="emoji", lang="en", oneline=False)
        asked = []
        app = SunshineApp(lambda: NOW, 43.7, -70.3, runtime,
                          hours_at=lambda moment: asked.append(moment) or "hours")
        app.intercept("fwd")
        app.render()
        assert asked == [NOW + timedelta(minutes=15)]
        assert frames[-1][2]["hours"] == "hours"


class TestHelp:
    def test_help_follows_the_view(self, app):
        panel = app.help_panel()
        assert panel.view() == "sunshine"
        app.on_action("v")
        assert panel.view() == "sunshine_year"


class TestRun:
    def test_run_measures_the_glyphs_then_opens_the_loop(self, app, monkeypatch):
        order = []
        monkeypatch.setattr(textwidth, "calibrate_from_terminal",
                            lambda *a, **k: order.append("calibrate"))
        seen = {}

        def fake_loop(render_fn, **kw):
            order.append("loop")
            seen.update(kw, render=render_fn)

        monkeypatch.setattr(_live, "live_loop", fake_loop)
        app.run()
        assert order == ["calibrate", "loop"]
        assert seen["render"].__self__ is app
        assert seen["mouse"] is True and seen["interval"] == 60
        # No drag hook, so the loop tracks no press and there are no clicks
        assert {"intercept", "on_wheel", "on_action"} <= set(seen)
        assert "on_drag" not in seen and "on_click" not in seen
