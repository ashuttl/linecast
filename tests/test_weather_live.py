"""WeatherApp: the live weather view's refresh and alert opening."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast.weather import view as weather
from linecast.weather.view import WeatherApp


def _app(clock, alerts=None):
    runtime = SimpleNamespace(lang="en")
    with patch("time.monotonic", side_effect=clock):
        return WeatherApp(
            {"v": 1}, alerts or [], {"aqi": 1}, 43.0, -70.0, runtime,
            location_name="Westbrook", historical={"h": 1}, country="US",
        )


class TestRender:
    def test_render_inside_the_interval_uses_the_cached_data(self):
        app = _app(lambda: 1000.0)
        with patch.object(weather, "fetch_forecast") as forecast, \
             patch.object(weather, "fetch_alerts") as alerts, \
             patch.object(weather, "fetch_aqi") as aqi, \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch("time.monotonic", return_value=1299.0):
            assert app.render(offset_minutes=30, mouse_pos=(2, 3)) == ("out", {})
        assert not forecast.called and not alerts.called and not aqi.called
        args, kwargs = render.call_args
        assert args == ({"v": 1}, [], app.runtime)
        assert kwargs == {
            "location_name": "Westbrook", "offset_minutes": 30,
            "mouse_pos": (2, 3), "active_alert": None, "modal_scroll": 0,
            "aqi_data": {"aqi": 1}, "historical": {"h": 1},
            "notice": None,   # today's data carries no stale-forecast line
            "country_code": "US", "location_menu": True,
        }

    def test_render_after_the_interval_refreshes_in_the_background(self):
        app = _app(lambda: 1000.0)
        release = threading.Event()

        def slow_forecast(*a, **k):
            release.wait(1.0)
            return {"v": 2}

        with patch.object(weather, "fetch_forecast",
                          side_effect=slow_forecast) as forecast, \
             patch.object(weather, "fetch_alerts",
                          return_value=[{"url": "u"}]) as alerts, \
             patch.object(weather, "fetch_aqi", return_value={"aqi": 2}) as aqi, \
             patch.object(weather, "_reverse_geocode",
                          return_value=("Westbrook", "US", {"state": "Maine"})), \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch("time.monotonic", return_value=1300.0):
            app.render()
            # this repaint painted the data it had, without waiting
            assert render.call_args[0][:2] == ({"v": 1}, [])
            release.set()
            app._worker.join(1.0)
        forecast.assert_called_once_with(43.0, -70.0, app.runtime)
        alerts.assert_called_once_with(43.0, -70.0, "US", lang="en",
                                       address={"state": "Maine"})
        aqi.assert_called_once_with(43.0, -70.0)
        assert app.data == {"v": 2}
        assert app.alerts == [{"url": "u"}]
        assert app.aqi == {"aqi": 2}
        assert app.fetched == 1300.0
        assert not app._worker.is_alive()

    def test_one_refresh_in_flight_at_a_time(self):
        app = _app(lambda: 1000.0)
        release = threading.Event()

        def slow_forecast(*a, **k):
            release.wait(1.0)
            return {"v": 2}

        with patch.object(weather, "fetch_forecast", side_effect=slow_forecast), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "_reverse_geocode", return_value=("", "US", {})), \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})), \
             patch("time.monotonic", return_value=1300.0):
            app.render()
            worker = app._worker
            app.render()
            assert app._worker is worker   # no second worker
            release.set()
            worker.join(1.0)
        assert app.data == {"v": 2}

    def test_a_failed_forecast_refresh_keeps_the_old_data(self):
        app = _app(lambda: 1000.0)
        with patch.object(weather, "fetch_forecast", return_value=None), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "_reverse_geocode", return_value=("", "US", {})), \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch("time.monotonic", return_value=2000.0):
            app.render()
            app._worker.join(1.0)
        assert app.data == {"v": 1}
        assert app.fetched == 2000.0   # a dead network waits out the interval
        assert render.call_args[0][0] == {"v": 1}


class TestRefreshAddress:
    """The live refresh matches alerts against an address, as the
    one-shot path does; without one every text-only warning in the
    country is the reader's (issue: MeteoAlarm tier three)."""

    def _refresh(self, geocode, country="NL", lat=52.1, lng=5.2):
        app = _app(lambda: 0.0)
        app.lat, app.lng, app.country = lat, lng, country
        with patch.object(weather, "fetch_forecast", return_value={"v": 2}), \
             patch.object(weather, "fetch_alerts", return_value=[]) as alerts, \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "_reverse_geocode", **geocode) as geocoded:
            app._refresh(app._generation, app.lat, app.lng, app.country)
        return app, alerts, geocoded

    def test_the_refresh_passes_the_address_it_geocoded(self):
        address = {"state": "Utrecht", "country_code": "nl"}
        app, alerts, geocoded = self._refresh(
            dict(return_value=("Utrecht", "NL", address)))
        # No language: the address comes in the country's own, which is
        # what the feeds' area names are matched against.
        geocoded.assert_called_once_with(52.1, 5.2)
        alerts.assert_called_once_with(52.1, 5.2, "NL", lang="en", address=address)
        assert app.data == {"v": 2}

    def test_the_geocoded_country_wins_over_the_stale_one(self):
        _app_, alerts, _ = self._refresh(
            dict(return_value=("Utrecht", "NL", {"state": "Utrecht"})), country="")
        assert alerts.call_args[0][2] == "NL"

    def test_a_geocoder_that_answers_with_nothing_still_refreshes(self):
        app, alerts, _ = self._refresh(dict(return_value=("", "", {})))
        assert alerts.call_args == ((52.1, 5.2, "NL"), {"lang": "en", "address": {}})
        assert app.data == {"v": 2}

    def test_a_geocoder_that_raises_still_refreshes(self):
        app, alerts, _ = self._refresh(dict(side_effect=OSError("network down")))
        assert alerts.call_args == ((52.1, 5.2, "NL"), {"lang": "en", "address": {}})
        assert app.data == {"v": 2}

    def test_the_address_follows_the_location_the_refresh_was_given(self):
        seen = {}

        def geocode(lat, lng):
            seen[(lat, lng)] = {"state": "Friesland"}
            return "Leeuwarden", "NL", seen[(lat, lng)]

        _app_, alerts, _ = self._refresh(dict(side_effect=geocode),
                                         lat=53.2, lng=5.8)
        assert list(seen) == [(53.2, 5.8)]
        assert alerts.call_args[1]["address"] == {"state": "Friesland"}


class TestOpen:
    def test_open_launches_the_alert_url(self):
        app = _app(lambda: 0.0, alerts=[{"url": "https://x.test/a"}])
        with patch("webbrowser.open") as opened:
            app.on_open(0)
        opened.assert_called_once_with("https://x.test/a")

    def test_open_ignores_an_index_out_of_range(self):
        app = _app(lambda: 0.0, alerts=[{"url": "https://x.test/a"}])
        with patch("webbrowser.open") as opened:
            app.on_open(1)
            app.on_open(-1)
        assert not opened.called

    def test_open_ignores_an_alert_without_a_url(self):
        app = _app(lambda: 0.0, alerts=[{"url": ""}, {}])
        with patch("webbrowser.open") as opened:
            app.on_open(0)
            app.on_open(1)
        assert not opened.called


class TestTuning:
    def test_the_loop_settings_are_the_weather_ones(self):
        assert WeatherApp.interval == 300
        assert WeatherApp.scroll_step == 60
        assert WeatherApp.mouse is True
        assert set(_app(lambda: 0.0).hooks()) == {
            "on_open", "on_action", "intercept", "text_mode", "on_click", "on_drag", "on_wheel",
            "clamp_offset",
        }


class TestHoverTooltip:
    """The tooltip keeps clear of the pointer glyph (issue #48)."""

    def _rows_used(self, mouse_row, rows):
        import json
        import re
        from datetime import datetime
        from linecast._runtime import WeatherRuntime

        data = json.loads(
            (Path(__file__).parent / "fixtures" / "open_meteo_forecast.json")
            .read_text(encoding="utf-8"))
        runtime = WeatherRuntime(live=False, icons="emoji", lang="en",
                                 oneline=False, celsius=False, metric=False)
        with patch.object(weather, "_local_now_for_data",
                          return_value=datetime(2026, 3, 5, 14, 30)):
            overlay = weather._build_hover_tooltip(
                data, 40, mouse_row, 2, rows - 1, 80, rows, runtime)
        assert overlay
        return [int(m) for m in re.findall(r"\x1b\[(\d+);\d+H", overlay)]

    def test_sits_below_the_pointer_with_a_clear_row(self):
        assert min(self._rows_used(mouse_row=5, rows=40)) == 7

    def test_flips_above_when_there_is_no_room_below(self):
        assert max(self._rows_used(mouse_row=22, rows=24)) == 21
