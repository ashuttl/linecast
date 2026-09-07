"""The rain thresholds are the same amount of rain in either unit."""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._weather_daily import render_daily
from linecast._weather_sections import _past_precip_line

_MM_PER_INCH = 25.4


def _runtime(metric):
    from linecast._runtime import WeatherRuntime
    return WeatherRuntime(live=False, icons="plain", lang="en", oneline=False,
                          celsius=False, metric=metric, shading=False)


def _past_line(mm, metric):
    """The past-precipitation line for `mm` of rain an hour ago."""
    hourly = {
        "time": ["2026-09-06T05:00"],
        "precipitation": [mm if metric else mm / _MM_PER_INCH],
        "snowfall": [0],
        "weather_code": [61],
    }
    runtime = SimpleNamespace(lang="en", metric=metric)
    return _past_precip_line(hourly, datetime(2026, 9, 6, 6), runtime)


def _today_row(mm, metric):
    """The daily row for today, given `mm` of rain forecast for it."""
    amount = mm if metric else mm / _MM_PER_INCH
    data = {
        "daily": {
            # index 0 is yesterday, 1 today, 2 on the forecast
            "time": ["2026-09-05", "2026-09-06", "2026-09-07"],
            "temperature_2m_max": [70, 72, 74],
            "temperature_2m_min": [50, 52, 54],
            "precipitation_sum": [0, amount, 0],
            "precipitation_probability_max": [0, 60, 0],
            "weather_code": [61, 61, 61],
            "wind_speed_10m_max": [5, 5, 5],
        },
    }
    lines = render_daily(data, 100, _runtime(metric), now=datetime(2026, 9, 6, 12))
    return lines[0]


class TestPastPrecipThreshold:
    """The "rain in the last 24 hours" line, above and below 0.01"."""

    def test_a_trace_goes_unreported_in_either_unit(self):
        assert _past_line(0.2, metric=True) == ""
        assert _past_line(0.2, metric=False) == ""

    def test_a_measurable_amount_is_reported_in_either_unit(self):
        assert _past_line(0.3, metric=True) != ""
        assert _past_line(0.3, metric=False) != ""


class TestDailyPrecipThreshold:
    """The amount beside a day in the daily list, above and below 1 mm."""

    def test_under_a_millimetre_is_unnamed_in_either_unit(self):
        assert "Rain" not in _today_row(0.8, metric=True)
        assert "Rain" not in _today_row(0.8, metric=False)

    def test_over_a_millimetre_is_named_in_either_unit(self):
        assert "Rain" in _today_row(1.2, metric=True)
        assert "Rain" in _today_row(1.2, metric=False)
