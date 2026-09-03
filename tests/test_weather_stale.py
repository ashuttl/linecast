"""A forecast from an earlier day: how it is detected, what the view says
about it, and how a newer one is asked for (issue #68)."""

import json
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _weather_sources, weather
from linecast._weather_sources import forecast_date, forecast_is_todays
from linecast.weather import WeatherApp, forecast_notice

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())
# The fixture's daily series starts 2026-03-04, so it calls 2026-03-05 today.
MADE = datetime(2026, 3, 5, 14, 30)      # a Thursday
LATER = datetime(2026, 3, 7, 9, 0)       # the Saturday after


def _strip(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _runtime(lang="en", use_24h=False):
    return SimpleNamespace(lang=lang, use_24h=use_24h)


class TestForecastDate:
    def test_is_the_second_daily_entry(self):
        assert forecast_date(FIXTURE) == MADE.date()

    def test_none_without_a_daily_series(self):
        assert forecast_date({}) is None
        assert forecast_date({"daily": {"time": ["2026-03-04"]}}) is None
        assert forecast_date({"daily": {"time": ["x", "not a date"]}}) is None


class TestForecastIsTodays:
    def test_true_on_the_day_it_was_made(self):
        with patch.object(_weather_sources, "_local_now_for_data", return_value=MADE):
            assert forecast_is_todays(FIXTURE)

    def test_false_on_a_later_day(self):
        with patch.object(_weather_sources, "_local_now_for_data", return_value=LATER):
            assert not forecast_is_todays(FIXTURE)

    def test_false_at_midnight_after(self):
        with patch.object(_weather_sources, "_local_now_for_data",
                          return_value=datetime(2026, 3, 6, 0, 0)):
            assert not forecast_is_todays(FIXTURE)

    def test_false_for_a_payload_without_days(self):
        assert not forecast_is_todays({"timezone": "UTC"})

    def test_is_the_cache_test_for_the_forecast(self):
        runtime = SimpleNamespace(celsius=True, metric=True)
        with patch.object(_weather_sources, "fetch_json_cached",
                          return_value={"ok": 1}) as cached:
            assert _weather_sources.fetch_forecast(43.0, -70.0, runtime) == {"ok": 1}
        assert cached.call_args.kwargs["fresh"] is forecast_is_todays


class TestForecastNotice:
    def test_nothing_on_the_day_it_was_made(self):
        with patch.object(weather, "_local_now_for_data", return_value=MADE):
            assert forecast_notice(FIXTURE, _runtime()) is None

    def test_nothing_for_data_without_days(self):
        assert forecast_notice({"timezone": "UTC"}, _runtime()) is None

    def test_names_the_day_and_says_to_run_again(self):
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(FIXTURE, _runtime()))
        assert line == ("This forecast is from Thursday; a newer one could not be "
                        "fetched. Run again to retry.")

    def test_live_offers_the_key(self):
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(FIXTURE, _runtime(), live=True))
        assert line.endswith("Press r to retry.")

    def test_a_failed_retry_shows_when(self):
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(
                FIXTURE, _runtime(), live=True, failed_at=datetime(2026, 3, 7, 14, 32)))
        assert "could not be fetched at 2:32p." in line
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(
                FIXTURE, _runtime(use_24h=True), live=True,
                failed_at=datetime(2026, 3, 7, 14, 32)))
        assert "could not be fetched at 14:32." in line

    def test_while_fetching_says_so(self):
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(FIXTURE, _runtime(), live=True, fetching=True))
        assert line == "Fetching a newer forecast…"

    def test_a_week_or_more_ago_gives_the_date(self):
        with patch.object(weather, "_local_now_for_data",
                          return_value=datetime(2026, 3, 12, 9, 0)):
            line = _strip(forecast_notice(FIXTURE, _runtime()))
        assert line.startswith("This forecast is from 2026-03-12".replace("12", "05"))

    def test_the_day_is_in_the_users_language(self):
        with patch.object(weather, "_local_now_for_data", return_value=LATER):
            line = _strip(forecast_notice(FIXTURE, _runtime(lang="fr")))
        assert "jeudi" in line

    def test_the_line_sits_under_the_header(self):
        runtime = weather.WeatherRuntime.defaults()
        with patch("linecast.weather.get_terminal_size", return_value=(100, 30)), \
             patch("linecast.weather._local_now_for_data", return_value=LATER), \
             patch("linecast._weather_hourly._local_now_for_data", return_value=LATER):
            notice = forecast_notice(FIXTURE, runtime)
            output, _ = weather.render_from_data(FIXTURE, [], runtime,
                                                 location_name="Toronto", notice=notice)
        lines = _strip(output).split("\n")
        assert lines[1].startswith("This forecast is from Thursday")
        assert lines[2] == ""


class TestDailyLabels:
    def _rows(self, now):
        from linecast._weather_daily import render_daily
        runtime = weather.WeatherRuntime.defaults()
        lines = render_daily(FIXTURE, 100, runtime, now=now)
        return [_strip(line).split()[0] for line in lines]

    def test_the_first_row_is_today_on_the_day_it_was_made(self):
        assert self._rows(MADE)[:3] == ["Tod", "Fri", "Sat"]

    def test_the_first_row_is_its_weekday_on_a_later_day(self):
        # The forecast's days keep their names; none of them is today.
        assert self._rows(LATER)[:3] == ["Thu", "Fri", "Sat"]


def _app(clock=lambda: 1000.0):
    with patch("time.monotonic", side_effect=clock):
        return WeatherApp({"v": 1}, [], None, 43.0, -70.0, _runtime(),
                          location_name="Westbrook", historical=None, country="US")


class TestRetryKey:
    def test_r_asks_for_a_newer_forecast_now(self):
        app = _app()
        with patch.object(weather, "fetch_forecast", return_value={"v": 2}) as forecast, \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch("time.monotonic", return_value=1001.0):
            assert app.on_action("r")     # well inside the interval
            app._worker.join(1.0)
        forecast.assert_called_once_with(43.0, -70.0, app.runtime)
        assert app.data == {"v": 2}

    def test_a_refresh_that_still_gets_an_old_forecast_records_when(self):
        app = _app()
        with patch.object(weather, "fetch_forecast", return_value=FIXTURE), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(_weather_sources, "datetime") as dt:
            dt.now.return_value = LATER
            app.on_action("r")
            app._worker.join(1.0)
        assert app.attempted == LATER    # the notice can say when it was tried

    def test_a_refresh_that_gets_todays_forecast_records_nothing(self):
        # At midnight the forecast stops being today's; the line must not
        # then report the fetch that got it, which succeeded, as a failed one.
        app = _app()
        with patch.object(weather, "fetch_forecast", return_value=FIXTURE), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(_weather_sources, "datetime") as dt:
            dt.now.return_value = MADE
            app.on_action("r")
            app._worker.join(1.0)
        assert app.attempted is None

    def test_other_keys_are_not_ours(self):
        app = _app()
        assert not app.on_action("x")
        assert app._worker is None

    def test_r_during_a_refresh_starts_no_second_one(self):
        app = _app()
        release = threading.Event()

        def slow_forecast(*a, **k):
            release.wait(1.0)
            return {"v": 2}

        with patch.object(weather, "fetch_forecast", side_effect=slow_forecast), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None):
            app.on_action("r")
            worker = app._worker
            app.on_action("r")
            assert app._worker is worker
            release.set()
            worker.join(1.0)

    def test_render_passes_the_notice(self):
        app = _app()
        app.data = FIXTURE
        with patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch.object(weather, "_local_now_for_data", return_value=LATER), \
             patch("time.monotonic", return_value=1001.0):
            app.render()
        notice = _strip(render.call_args.kwargs["notice"])
        assert notice.startswith("This forecast is from Thursday")
        assert notice.endswith("Press r to retry.")
