"""MoonApp: the live moon view's keys, drag and clicks, with no terminal
behind them."""

from datetime import datetime, timedelta, timezone

import pytest

from linecast._runtime import RuntimeConfig
from linecast.moon import live as _moon_live
from linecast.moon.live import MoonApp
from linecast.terminal import live as _live
from linecast.terminal import textwidth

ET = timezone(timedelta(hours=-4))
NOW = datetime(2026, 9, 1, 14, 30, tzinfo=ET)


def _runtime(lang="en"):
    return RuntimeConfig(live=True, icons="emoji", lang=lang, oneline=False)


@pytest.fixture
def app():
    return MoonApp(lambda: NOW, 43.7, -70.3, _runtime(), place="Westbrook")


@pytest.fixture
def discs(monkeypatch):
    """What each render asked of the disc view."""
    seen = []
    monkeypatch.setattr(_moon_live, "render",
                        lambda *a, **k: seen.append((a, k)) or "disc")
    return seen


def _grid(app, monkeypatch, cols=100, rows=32):
    """Render the calendar for real, so clicks have a grid to land on."""
    monkeypatch.setattr("linecast.moon.calendar.get_terminal_size",
                        lambda: (cols, rows))
    app.render()
    from linecast.moon import calendar as moon_calendar
    return moon_calendar._last_grid


class TestScrub:
    def test_the_disc_moves_a_quarter_hour(self, app, discs):
        assert app.on_wheel(1, 10, 10) is True
        assert app.intercept("fwd") is True
        assert app.intercept("back") is True
        assert app.minutes == 15 and app.months == 0
        app.render()
        (moment, *_rest), kw = discs[-1]
        assert moment == NOW + timedelta(minutes=15)
        assert kw["offset_minutes"] == 15

    def test_the_calendar_moves_a_month(self, app):
        app.on_action("v")
        assert app.on_wheel(-1, 10, 10) is True
        assert app.intercept("back") is True
        assert app.months == -2 and app.minutes == 0

    def test_space_returns_the_view_on_screen_to_now(self, app):
        app.intercept("fwd")
        app.on_action("v")
        app.intercept("fwd")
        assert app.intercept("reset") is True
        assert app.months == 0 and app.minutes == 15
        app.on_action("v")
        app.intercept("reset")
        assert app.minutes == 0


class TestKeys:
    def test_v_flips_and_each_view_keeps_its_place(self, app):
        app.intercept("fwd")
        assert app.on_action("v") is True and app.month
        app.intercept("fwd")
        assert app.on_action("v") is True and not app.month
        assert app.minutes == 15 and app.months == 1

    def test_t_puts_the_text_away_and_back(self, app, discs):
        assert app.on_action("t") is True and not app.text
        app.render()
        assert discs[-1][1]["show_text"] is False
        assert app.on_action("t") is True and app.text

    def test_t_does_nothing_on_the_calendar(self, app):
        app.on_action("v")
        assert app.on_action("t") is False
        assert app.text

    def test_other_keys_pass_through(self, app):
        assert app.on_action("x") is False
        assert app.intercept("key:t") is False
        assert app.intercept("quit") is False

    def test_opened_on_the_month(self, monkeypatch):
        app = MoonApp(lambda: NOW, 43.7, -70.3, _runtime(), month=True)
        grid = _grid(app, monkeypatch)
        days_in, first = grid[6], grid[7]
        assert first == NOW.date().replace(day=1) and days_in == 30


class TestDrag:
    def test_a_drag_turns_the_disc_and_letting_go_settles_it(self, app):
        assert app.turn.matrix() is None
        assert app.on_drag(6, 2, False) is True
        assert app.turn.matrix() is not None
        assert app.on_drag(6, 2, True) is True
        assert app.turn._settle is not None

    def test_the_hand_turns_it_the_same_way_in_a_mirrored_view(self, app, monkeypatch):
        seen = []
        monkeypatch.setattr(app.turn, "drag", lambda dcol, drow: seen.append((dcol, drow)))
        app.on_drag(6, 2, False)
        monkeypatch.setattr(_moon_live._bidi, "mirrored", lambda: True)
        app.on_drag(6, 2, False)
        assert seen == [(6, 2), (-6, 2)]

    def test_the_calendar_has_nothing_to_drag(self, app):
        app.on_action("v")
        assert app.on_drag(6, 2, False) is False
        assert app.on_drag(6, 2, True) is False
        assert app.turn.matrix() is None


class TestClick:
    def test_a_day_opens_the_disc_view_on_it(self, app, monkeypatch, discs):
        app.on_action("v")
        left, row0, cell_w, cell_h, weeks, lead, *_rest = _grid(app, monkeypatch)
        day = 16
        wk, c = divmod(lead + day - 1, 7)
        col = left + c * cell_w + 2 + 1     # 1-based, inside the day's cell
        row = row0 + wk * cell_h + 1 + 1
        assert app.on_click(col, row) is True
        assert not app.month
        assert app.minutes == 15 * 1440
        app.render()
        assert discs[-1][0][0] == NOW + timedelta(days=15)
        # ...and space is the way back to now
        app.intercept("reset")
        assert app.minutes == 0

    def test_off_the_grid_nothing_happens(self, app, monkeypatch):
        app.on_action("v")
        _grid(app, monkeypatch)
        assert app.on_click(1, 1) is False
        assert app.month and app.minutes == 0

    def test_the_disc_view_takes_no_clicks(self, app, monkeypatch):
        app.on_action("v")
        _grid(app, monkeypatch)
        app.on_action("v")
        assert app.on_click(30, 12) is False


class TestInterval:
    def test_once_a_minute(self, app):
        assert app.interval() == 60

    def test_every_second_in_the_last_day_of_the_solar_hijri_year(self):
        from linecast.astro.calendars import solar_hijri
        turn = solar_hijri.nowruz_utc(1406)
        now = (turn - timedelta(hours=3)).astimezone(ET)
        assert MoonApp(lambda: now, 35.7, 51.4, _runtime("fa")).interval() == 1
        assert MoonApp(lambda: now, 35.7, 51.4, _runtime("en")).interval() == 60
        earlier = now - timedelta(days=2)
        assert MoonApp(lambda: earlier, 35.7, 51.4, _runtime("fa")).interval() == 60


class TestHelp:
    def test_help_follows_the_view_and_credits_the_place(self, app):
        from linecast.moon.view import place_credit
        from linecast.terminal.help import entries
        panel = app.help_panel()
        credit = place_credit(43.7, -70.3, "Westbrook", app.runtime)
        assert panel.content(100, 30) == entries("moon", "en", credits=(credit,))
        app.on_action("v")
        assert panel.content(100, 30) == entries("moon_calendar", "en", credits=(credit,))

    def test_the_place_named_later_is_credited(self, app, monkeypatch):
        monkeypatch.setattr("linecast._geocode.place_label",
                            lambda lat, lng, label, lang: "Westbrook, Maine")
        panel = app.help_panel()
        app.name_the_place()
        assert any("Westbrook, Maine" in row[1] for row in panel.content(100, 30) if row)


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
        assert seen["interval"]() == 60 and seen["mouse"] is True
        assert {"intercept", "on_wheel", "on_action", "on_drag", "on_click"} <= set(seen)
