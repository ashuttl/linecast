"""TidesApp: the live tide view's window expansion and location menu."""

import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast._runtime import TidesRuntime
from linecast.tides import harmonic
from linecast.tides import live as _tides_live
from linecast.tides import view as tides
from linecast.tides.common import computed_hilo, computed_range
from linecast.tides.live import TidesApp

NOW = datetime(2026, 3, 5, 12, 0, 0)
TODAY = NOW.date()


class FakeProvider:
    year_view = True

    def __init__(self):
        self.calls = []
        self.answer = None   # None answers a real range; [] a failed fetch
        self.gate = None     # an Event holds the fetch until the test says go

    def tides_range(self, station_id, start, end, tz):
        if self.gate is not None:
            self.gate.wait(1.0)
        self.calls.append(("tides", station_id, start, end, tz))
        return [(start, 1.0), (end, 2.0)] if self.answer is None else self.answer

    def hilo_range(self, station_id, start, end, tz):
        self.calls.append(("hilo", station_id, start, end, tz))
        return [(start, "H")] if self.answer is None else self.answer


def _app():
    provider = FakeProvider()
    app = TidesApp(
        provider, "8418150", "Portland, ME", {"name": "Portland"}, "tz",
        SimpleNamespace(lang="en"), [("p", 0.0)], [("h", "L")],
        TODAY - timedelta(days=7), TODAY + timedelta(days=7),
        y_range=(0, 4), marine_data={"m": 1},
    )
    return app, provider


class TestExpand:
    def test_no_expansion_while_the_window_is_inside_the_range(self):
        app, provider = _app()
        with patch.object(_tides_live, "_station_now", return_value=NOW):
            app.expand_for(0)
            app.expand_for(24 * 60)
            app.expand_for(-24 * 60)
        assert provider.calls == []
        assert app._worker is None
        assert app.predictions == [("p", 0.0)]
        assert app.fetched_start == TODAY - timedelta(days=7)

    def test_scrolling_near_the_end_expands_a_week_past_the_view(self):
        app, provider = _app()
        with patch.object(_tides_live, "_station_now", return_value=NOW):
            app.expand_for(6 * 24 * 60)
            app._worker.join(1.0)
        view_start = tides._live_window_start(
            NOW, offset_minutes=6 * 24 * 60, hours_shown=tides.LIVE_WINDOW_HOURS)
        view_end_date = (view_start + timedelta(hours=tides.LIVE_WINDOW_HOURS)).date()
        new_end = view_end_date + timedelta(days=7)
        old_start = TODAY - timedelta(days=7)
        assert provider.calls == [
            ("tides", "8418150", old_start, new_end, "tz"),
            ("hilo", "8418150", old_start, new_end, "tz"),
        ]
        assert app.fetched_start == old_start
        assert app.fetched_end == new_end
        assert app.predictions == [(old_start, 1.0), (new_end, 2.0)]
        assert app.hilo == [(old_start, "H")]

    def test_scrolling_near_the_start_expands_a_week_before_the_view(self):
        app, provider = _app()
        with patch.object(_tides_live, "_station_now", return_value=NOW):
            app.expand_for(-6 * 24 * 60)
            app._worker.join(1.0)
        view_start = tides._live_window_start(
            NOW, offset_minutes=-6 * 24 * 60, hours_shown=tides.LIVE_WINDOW_HOURS)
        new_start = view_start.date() - timedelta(days=7)
        old_end = TODAY + timedelta(days=7)
        assert provider.calls[0] == ("tides", "8418150", new_start, old_end, "tz")
        assert app.fetched_start == new_start
        assert app.fetched_end == old_end
        assert isinstance(app.fetched_start, date)

    def test_an_empty_fetch_keeps_the_range_and_waits_before_retrying(self):
        app, provider = _app()
        provider.answer = []   # the providers answer empty on a dead network
        with patch.object(_tides_live, "_station_now", return_value=NOW):
            app.expand_for(6 * 24 * 60)
            app._worker.join(1.0)
            calls = len(provider.calls)
            app.expand_for(6 * 24 * 60)   # inside the retry pause
        assert app.predictions == [("p", 0.0)]
        assert app.hilo == [("h", "L")]
        assert app.fetched_end == TODAY + timedelta(days=7)
        assert app._retry_at > 0
        assert len(provider.calls) == calls


class TestRender:
    def test_render_draws_what_it_has_while_the_expansion_lands(self):
        app, provider = _app()
        provider.gate = threading.Event()
        old_predictions, old_hilo = app.predictions, app.hilo
        with patch.object(_tides_live, "_station_now", return_value=NOW), \
             patch.object(_tides_live, "render", return_value="frame") as render:
            out = app.render(offset_minutes=6 * 24 * 60, mouse_pos=(4, 5))
            provider.gate.set()
            app._worker.join(1.0)
        assert out == ("frame", {})
        render.assert_called_once_with(
            "8418150", "Portland, ME", station_meta={"name": "Portland"},
            runtime=app.runtime, fullscreen=True,
            offset_minutes=6 * 24 * 60, mouse_pos=(4, 5),
            predictions=old_predictions, hilo=old_hilo,
            y_range=(0, 4), marine_data={"m": 1}, provider=app.provider,
            location_menu=True,
        )
        assert provider.calls           # the expansion still ran
        assert app.predictions != old_predictions  # and landed for the next frame


class TestLocations:
    def _place(self, name="Sydney"):
        from linecast.maps.search import Result
        return Result(name, "", -33.87, 151.21, "point")

    def test_a_chosen_place_brings_its_station(self):
        app, _provider = _app()
        app.lat, app.lng, app.place_label = 43.66, -70.25, "Portland, Maine"
        other = FakeProvider()
        fetched = (TODAY, TODAY, (0, 2), None, [("q", 1.0)], [("h", "H")])
        loaded = dict(provider=other, station_id="om:1", station_name="Sydney",
                      station_meta={"name": "Sydney"}, station_tz="tz2", country="AU",
                      fetched=fetched)
        app._location_result = (self._place(), loaded)
        app._finish_location()
        assert (app.provider, app.station_id, app.station_name) == (other, "om:1", "Sydney")
        assert app.predictions == [("q", 1.0)] and app.y_range == (0, 2)
        names = [p.name for p in app.locations.recent.places]
        assert names == ["Sydney", "Portland, Maine"]  # and the way back

    def test_a_place_without_tides_keeps_the_station_and_says_so(self):
        app, provider = _app()
        app._location_result = (self._place("Denver"), None)
        with patch.object(app, "flash") as flash:
            app._finish_location()
        flash.assert_called_once_with(["No tide predictions for Denver."], seconds=5)
        assert app.station_id == "8418150" and app.provider is provider

    def test_an_expansion_for_the_station_left_behind_is_dropped(self):
        app, provider = _app()
        provider.gate = threading.Event()
        old = app.predictions
        with patch.object(_tides_live, "_station_now", return_value=NOW):
            app.expand_for(6 * 24 * 60)
            app.station_id = "om:1"
            provider.gate.set()
            app._worker.join(1.0)
        assert app.predictions is old

    @pytest.mark.parametrize("color_mode, cols, width", [
        ("none", 110, 14),
        ("truecolor", 110, 18),
        ("truecolor", 32, 14),  # the title leaves room for Portland alone
        ("truecolor", 20, 0),   # no station pill fits beside the title
    ])
    def test_the_station_pill_opens_the_menu(self, monkeypatch, color_mode, cols, width):
        from linecast.terminal import color

        monkeypatch.setattr(color, "_COLOR_MODE", color_mode)
        monkeypatch.setattr(tides, "_pill_width", 0)
        app, _provider = _app()
        # Clicks follow the pill that was drawn, including its shortened
        # or hidden form when the month title needs the room.
        tides._render_header_line(cols, app.station_name, app.runtime,
                                  location_menu=True, right="September 2026")
        assert not app.on_click(width + 1, 1)
        if width:
            assert not app.on_click(width, 2)
            assert app.on_click(width, 1) and app.locations.active
        else:
            assert not app.locations.active


class TestTuning:
    def test_the_loop_settings_are_the_tide_ones(self):
        assert TidesApp.interval == 60
        assert TidesApp.scroll_step == 30
        assert TidesApp.mouse is True
        # The location menu's hooks; the wheel still scrubs time while it is shut.
        assert set(_app()[0].hooks()) == {
            "on_action", "on_drag", "on_wheel", "intercept", "on_click", "text_mode"}


# ---------------------------------------------------------------------------
# The month, year and makeup views
# ---------------------------------------------------------------------------
ZONE = ZoneInfo("America/New_York")
NOON = datetime(2026, 3, 5, 12, 0, tzinfo=ZONE)


class TidalProvider(FakeProvider):
    """A source whose water is predicted here, so the longer views have
    a month and a year to draw."""

    observed_label = "measured"
    TIDE = harmonic.Tide([("M2", 1.40, 100.0), ("S2", 0.21, 135.0), ("N2", 0.28, 70.0),
                          ("K1", 0.14, 200.0), ("O1", 0.11, 180.0)], z0=1.5)

    def __init__(self):
        super().__init__()
        self.fail = False

    def tides_range(self, station_id, start, end, tz):
        self.calls.append(("tides", station_id, start, end, tz))
        return computed_range(self.TIDE, start, end, tz)

    def hilo_range(self, station_id, start, end, tz):
        self.calls.append(("hilo", station_id, start, end, tz))
        if self.fail:
            raise OSError("the network is down")
        return computed_hilo(self.TIDE, start, end, tz)

    def observed_extremes(self, station_id, year, today):
        self.calls.append(("observed", station_id, year, today))
        return {date(year, 1, 2): (0.1, 9.9)}

    def flood_stage(self, station_id):
        return 12.0

    def footer_label(self, runtime):
        return "Test Harbour"


def _tidal_app(view="day"):
    provider = TidalProvider()
    runtime = TidesRuntime(live=True, icons="nerd", lang="en", metric=False, oneline=False,
                           use_24h=False)
    app = TidesApp(provider, "8418150", "Portland, ME",
                   {"name": "Portland", "lat": "43.66", "lng": "-70.25"}, ZONE, runtime,
                   [], [], TODAY - timedelta(days=7), TODAY + timedelta(days=7), y_range=(0, 4))
    app.view = view
    return app, provider


@pytest.fixture
def window(monkeypatch):
    """A terminal 110 columns by 40 rows, and the station's clock stopped."""
    monkeypatch.setenv("COLUMNS", "110")
    monkeypatch.setenv("LINES", "40")
    monkeypatch.setattr(_tides_live, "_station_now", lambda *a, **k: NOON)


def _lines(frame):
    return frame.partition("\x00")[0].split("\n")


@pytest.fixture
def cli_station(monkeypatch, window):
    app, provider = _tidal_app()
    monkeypatch.setattr(_tides_live, "provider_for_id", lambda station: provider)
    monkeypatch.setattr(provider, "name_for_id", lambda station: app.station_name, raising=False)
    monkeypatch.setattr(_tides_live, "resolve_location", lambda *a, **k: (43.66, -70.25, "US"))
    monkeypatch.setattr(_tides_live, "country_for_defaults", lambda *a: "US")
    monkeypatch.setattr(_tides_live, "_station_details", lambda *a: (
        app.station_meta, app.station_name, app.station_tz))
    monkeypatch.setattr(_tides_live, "_fetch_station", lambda *a: (
        app.fetched_start, app.fetched_end, app.y_range, None, [(NOON, 1.0)], []))
    return provider


class TestViewFlags:
    @pytest.mark.parametrize("view", ["month", "year", "makeup"])
    def test_live_opens_on_the_requested_view(self, monkeypatch, cli_station, view):
        monkeypatch.setattr("sys.argv", ["tides", "--station", "8418150", f"--{view}",
                                         "--live"])
        seen = []
        monkeypatch.setattr(TidesApp, "run", lambda app: seen.append(app.view))
        _tides_live.main()
        assert seen == [view]

    @pytest.mark.parametrize("view", ["month", "year", "makeup"])
    @pytest.mark.parametrize("mode", [[], ["--print"]])
    def test_static_waits_for_the_requested_data(self, monkeypatch, cli_station, view, mode):
        monkeypatch.setattr("sys.argv", ["tides", "--station", "8418150", f"--{view}", *mode])
        frames = []
        monkeypatch.setattr(_tides_live._live, "print_frame", frames.append)
        render = TidesApp._render_long

        def loaded_frame(app, mouse_pos):
            assert app.view == view
            assert app._long_key() in app._long
            assert not app._long_worker.is_alive()
            return render(app, mouse_pos)

        monkeypatch.setattr(TidesApp, "_render_long", loaded_frame)
        _tides_live.main()
        assert len(frames) == 1 and isinstance(frames[0], str)
        assert "Portland" in frames[0] and "2026" in frames[0]

    @pytest.mark.parametrize("view", ["month", "year", "makeup"])
    @pytest.mark.parametrize("mode", ["--json", "--oneline"])
    def test_alternate_views_refuse_current_conditions_output(self, monkeypatch, capsys,
                                                             view, mode):
        monkeypatch.setattr("sys.argv", ["tides", f"--{view}", mode])
        with pytest.raises(SystemExit) as exc:
            _tides_live.main()
        assert exc.value.code == 2
        assert f"--{view} has no {mode} output" in capsys.readouterr().err

    @pytest.mark.parametrize("view", ["year", "makeup"])
    def test_short_range_source_refuses_year_views(self, monkeypatch, capsys, cli_station, view):
        cli_station.year_view = False
        monkeypatch.setattr("sys.argv", ["tides", "--station", "8418150", f"--{view}"])
        with pytest.raises(SystemExit) as exc:
            _tides_live.main()
        assert exc.value.code == 2
        assert f"--{view} is unavailable" in capsys.readouterr().err
        assert not cli_station.calls

    @pytest.mark.parametrize("flags", [("--month", "--year"), ("--month", "--makeup"),
                                       ("--year", "--makeup")])
    def test_view_flags_are_mutually_exclusive(self, flags, capsys):
        from linecast._parsers import tides_parser
        with pytest.raises(SystemExit) as exc:
            tides_parser().parse_args(flags)
        assert exc.value.code == 2
        assert "not allowed with argument" in capsys.readouterr().err


class TestViews:
    def test_v_goes_round_the_four_views(self):
        app, _provider = _tidal_app()
        seen = []
        for _ in range(5):
            assert app.on_action("v")
            seen.append(app.view)
        assert seen == ["month", "year", "makeup", "day", "month"]

    def test_a_source_that_cannot_fill_a_year_has_two(self):
        app, provider = _tidal_app()
        provider.year_view = False
        assert app.views == ("day", "month")
        seen = []
        for _ in range(3):
            app.on_action("v")
            seen.append(app.view)
        assert seen == ["month", "day", "month"]

    def test_each_view_has_its_own_help(self):
        app, provider = _tidal_app()
        pages = {}
        for view in app.VIEWS:
            app.view = view
            pages[view] = app.help_view
        assert pages == {"day": "tides", "month": "tides_month", "year": "tides_year",
                         "makeup": "tides_makeup"}
        provider.year_view = False
        app.view = "day"
        assert app.help_view == "tides_no_year"
        app.view = "month"
        assert app.help_view == "tides_month_no_year"

    def test_every_help_page_named_exists(self):
        from linecast.terminal import help as _help
        names = {"tides", "tides_month", "tides_year", "tides_makeup", "tides_no_year",
                 "tides_month_no_year"}
        assert names <= set(_help.CONTROLS)

    def test_another_key_is_not_taken(self):
        app, _provider = _tidal_app()
        assert not app.on_action("x")
        assert app.view == "day"


class TestSteps:
    def test_the_days_view_keeps_its_own_time_scrub(self, window):
        app, _provider = _tidal_app("day")
        assert not app.intercept("fwd")
        assert (app.months, app.years) == (0, 0)

    def test_the_month_and_the_makeup_step_by_months(self, window):
        for view in ("month", "makeup"):
            app, _provider = _tidal_app(view)
            assert app.intercept("fwd") and app.intercept("fwd") and app.intercept("back")
            assert (app.months, app.years) == (1, 0)
            assert app._long_key() == (view, "8418150", date(2026, 4, 1))

    def test_the_year_steps_by_years(self, window):
        app, _provider = _tidal_app("year")
        assert app.intercept("back")
        assert (app.months, app.years) == (0, -1)
        assert app._long_key() == ("year", "8418150", 2025)

    def test_a_step_back_crosses_the_years_start(self, window):
        app, _provider = _tidal_app("month")
        for _ in range(3):
            app.intercept("back")
        assert app._long_key() == ("month", "8418150", date(2025, 12, 1))

    def test_reset_returns_to_this_month_and_this_year(self, window):
        app, _provider = _tidal_app("month")
        app.months, app.years = 7, -2
        assert app.intercept("reset")
        assert (app.months, app.years) == (0, 0)

    def test_the_wheel_steps_too(self, window):
        app, _provider = _tidal_app("year")
        assert app.on_wheel(1, 40, 10)
        assert app.years == 1
        app.view = "month"
        app.on_wheel(-1, 40, 10)
        assert app.months == -1


class TestLongViews:
    def _settle(self, app):
        app._start_long()
        if app._long_worker is not None:
            app._long_worker.join(10.0)

    def test_a_month_is_its_curve_and_its_turns_with_a_day_either_side(self, window):
        app, provider = _tidal_app("month")
        self._settle(app)
        first, last = date(2026, 3, 1), date(2026, 3, 31)
        assert provider.calls == [
            ("tides", "8418150", first, last, ZONE),
            ("hilo", "8418150", first - timedelta(days=1), last + timedelta(days=1), ZONE)]
        predictions, hilo = app._long[("month", "8418150", first)]
        assert predictions[0][0].date() == first and hilo

    def test_a_year_is_its_daily_ranges_the_gauge_and_the_flood_stage(self, window):
        app, provider = _tidal_app("year")
        self._settle(app)
        assert provider.calls == [
            ("hilo", "8418150", date(2026, 1, 1), date(2026, 12, 31), ZONE),
            ("observed", "8418150", 2026, NOON.date())]
        predicted, observed, flood = app._long[("year", "8418150", 2026)]
        assert len(predicted) == 365 and flood == 12.0
        assert observed == {date(2026, 1, 2): (0.1, 9.9)}

    def test_the_makeup_fetches_once_and_fits(self, window):
        app, provider = _tidal_app("makeup")
        self._settle(app)
        assert provider.calls == [("hilo", "8418150", date(2026, 1, 1), date(2026, 12, 31), ZONE)]
        fit, month, year, long_, marks, counted_from = app._long[
            ("makeup", "8418150", date(2026, 3, 1))]
        assert [key for key, _a, _s in fit.twice] == [
            "makeup_moon", "makeup_sun", "makeup_distance"]
        assert len(month[0]) == 31 * 4 + 1 and len(year[0]) == 365 and counted_from == 2026
        assert fit.gain                                   # the station's latitude was read

    def test_with_the_fit_in_hand_another_month_is_made_where_it_is_asked_for(self, window):
        app, provider = _tidal_app("makeup")
        self._settle(app)
        worker, calls = app._long_worker, list(provider.calls)
        for _ in range(11):                               # on into next year
            app.intercept("fwd")
            app._start_long()
            assert app._long_key() in app._long           # at once, with no frame between
        assert app._long_worker is worker and provider.calls == calls
        made = app._long[("makeup", "8418150", date(2027, 2, 1))]
        assert len(made[1][0]) == 28 * 4 + 1 and len(made[2][0]) == 365
        assert made[5] == 2026                            # the nineteen years stay put

    def test_a_fetch_that_fails_waits_before_it_is_tried_again(self, window):
        app, provider = _tidal_app("year")
        provider.fail = True
        self._settle(app)
        assert ("year", "8418150", 2026) not in app._long
        assert app._long_retry_at > 0
        calls, worker = len(provider.calls), app._long_worker
        app._start_long()                                 # inside the pause
        assert len(provider.calls) == calls and app._long_worker is worker

    def test_what_is_made_is_kept(self, window):
        app, provider = _tidal_app("month")
        self._settle(app)
        calls = len(provider.calls)
        self._settle(app)
        app.intercept("fwd")
        app.intercept("back")
        self._settle(app)
        assert len(provider.calls) == calls

    @pytest.mark.parametrize("view", ["month", "year", "makeup"])
    def test_each_view_fills_the_window_before_and_after_its_data_lands(self, window, view):
        app, _provider = _tidal_app(view)
        before, _ = app.render()
        app._long_worker.join(10.0)
        after, _ = app.render()
        assert len(_lines(before)) == len(_lines(after)) == 40
        assert "Portland, ME" in _lines(after)[0]
        assert "Test Harbour" in _lines(after)[-1]

    def test_the_years_header_names_its_highest_water(self, window):
        app, _provider = _tidal_app("year")
        self._settle(app)
        frame, _ = app.render()
        assert "2026" in _lines(frame)[0] and "highest 9.9′ Jan 2" in _lines(frame)[0]
        assert "measured" in _lines(frame)[-1] and "predicted" in _lines(frame)[-1]


class SlowProvider(TidalProvider):
    """A source that keeps the longer views waiting until the test lets go."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()

    def tides_range(self, station_id, start, end, tz):
        self.gate.wait(10.0)
        return super().tides_range(station_id, start, end, tz)

    def hilo_range(self, station_id, start, end, tz):
        self.gate.wait(10.0)
        return super().hilo_range(station_id, start, end, tz)


class TestLoadingToast:
    """While a month or a year is on its way the view says so, with the
    toast the location menu shows for a place."""

    @pytest.fixture
    def waiting(self, window):
        """(app, let go): a view whose fetch is held, and its release."""
        apps = []

        def make(view):
            app, _provider = _tidal_app(view)
            app.provider = SlowProvider()
            apps.append(app)
            return app

        yield make
        for app in apps:
            app.provider.gate.set()
            if app._long_worker is not None:
                app._long_worker.join(10.0)
            app.clear_flash()

    @staticmethod
    def _floating(app):
        frame, _ = app.render()
        return frame.partition("\x00")[2]

    @pytest.mark.parametrize("view, awaited", [
        ("month", "Loading March 2026…"),
        ("year", "Loading 2026…"),
        ("makeup", "Loading Portland, ME…"),
    ])
    def test_a_fetch_still_out_after_a_moment_is_named_in_a_toast(self, waiting, view, awaited):
        app = waiting(view)
        assert "Loading" not in self._floating(app)       # it has only just set out
        app._long_started -= app.LONG_GRACE
        assert awaited in self._floating(app)
        app.provider.gate.set()
        app._long_worker.join(10.0)
        assert "Loading" not in self._floating(app)
        assert app._long_key() in app._long

    def test_the_toast_turns(self, waiting):
        app = waiting("year")
        self._floating(app)
        app._long_started = 0.0
        with patch.object(_tides_live._live._time, "monotonic", return_value=100.0):
            first = self._floating(app)
        with patch.object(_tides_live._live._time, "monotonic", return_value=100.08):
            second = self._floating(app)
        assert first != second and "Loading 2026…" in first and "Loading 2026…" in second

    def test_a_month_in_hand_shows_none(self, window):
        app, _provider = _tidal_app("month")
        app.render()
        app._long_worker.join(10.0)
        app._long_started -= app.LONG_GRACE
        assert "Loading" not in self._floating(app)

    def test_the_month_stepped_to_is_the_one_named(self, waiting):
        app = waiting("month")
        self._floating(app)
        app._long_started -= app.LONG_GRACE
        app.intercept("fwd")              # March's fetch is still out
        assert "Loading April 2026…" in self._floating(app)

    def test_a_note_already_up_is_not_covered(self, waiting):
        app = waiting("month")
        self._floating(app)
        app._long_started -= app.LONG_GRACE
        app.flash(["Saved Portland as the default"])
        floating = self._floating(app)
        assert "Saved Portland" in floating and "Loading" not in floating

    def test_the_days_chart_has_no_toast(self, waiting):
        app = waiting("month")
        self._floating(app)
        app._long_started -= app.LONG_GRACE
        app.view = "day"
        with patch.object(app, "expand_for"):
            frame, _ = app.render()
        assert "Loading" not in frame
