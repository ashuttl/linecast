"""WeatherApp: the live weather view's refresh and alert opening."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import weather
from linecast.weather import WeatherApp


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
        }

    def test_render_after_the_interval_refreshes_all_three_fetches(self):
        app = _app(lambda: 1000.0)
        with patch.object(weather, "fetch_forecast",
                          return_value={"v": 2}) as forecast, \
             patch.object(weather, "fetch_alerts",
                          return_value=[{"url": "u"}]) as alerts, \
             patch.object(weather, "fetch_aqi", return_value={"aqi": 2}) as aqi, \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch("time.monotonic", return_value=1300.0):
            app.render()
        forecast.assert_called_once_with(43.0, -70.0, app.runtime)
        alerts.assert_called_once_with(43.0, -70.0, "US", lang="en")
        aqi.assert_called_once_with(43.0, -70.0)
        assert app.data == {"v": 2}
        assert app.alerts == [{"url": "u"}]
        assert app.aqi == {"aqi": 2}
        assert app.fetched == 1300.0
        args, kwargs = render.call_args
        assert args[:2] == ({"v": 2}, [{"url": "u"}])
        assert kwargs["aqi_data"] == {"aqi": 2}

    def test_a_failed_forecast_refresh_keeps_the_old_data(self):
        app = _app(lambda: 1000.0)
        with patch.object(weather, "fetch_forecast", return_value=None), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "render_from_data",
                          return_value=("out", {})) as render, \
             patch("time.monotonic", return_value=2000.0):
            app.render()
        assert app.data == {"v": 1}
        assert render.call_args[0][0] == {"v": 1}


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
        assert set(_app(lambda: 0.0).hooks()) == {"on_open"}


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
