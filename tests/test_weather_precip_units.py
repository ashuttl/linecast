"""The rain thresholds are the same amount of rain in either unit."""

import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast.weather.daily import render_daily
from linecast.weather.sections import _past_precip_line

_MM_PER_INCH = 25.4
_CM_PER_INCH = 2.54


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


def _past_snow_line(cm, metric):
    """The past-precipitation line for `cm` of snow an hour ago, in the
    unit Open-Meteo sends it: cm, or inches alongside inches of rain."""
    hourly = {
        "time": ["2026-09-06T05:00"],
        "precipitation": [0],
        "snowfall": [cm if metric else cm / _CM_PER_INCH],
        "weather_code": [73],
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
    """The "rain in the last 24 hours" line, above and below a tenth of
    an inch, which is 2.5 mm."""

    def test_a_damp_pavement_goes_unreported_in_either_unit(self):
        assert _past_line(2.0, metric=True) == ""
        assert _past_line(2.0, metric=False) == ""

    def test_an_amount_worth_a_sentence_is_reported_in_either_unit(self):
        assert _past_line(3.0, metric=True) != ""
        assert _past_line(3.0, metric=False) != ""


class TestPastSnow:
    """Snowfall arrives in the requested unit and is reported as it came."""

    def test_ten_centimetres_read_as_ten_centimetres(self):
        assert "10.0" in _past_snow_line(10, metric=True)

    def test_ten_centimetres_read_as_their_inches(self):
        assert "3.9" in _past_snow_line(10, metric=False)

    def test_under_a_centimetre_goes_unreported_in_either_unit(self):
        assert _past_snow_line(0.8, metric=True) == ""
        assert _past_snow_line(0.8, metric=False) == ""

    def test_a_centimetre_and_more_is_reported_in_either_unit(self):
        assert _past_snow_line(1.2, metric=True) != ""
        assert _past_snow_line(1.2, metric=False) != ""


class TestDailyPrecipThreshold:
    """The amount beside a day in the daily list, above and below 1 mm."""

    # "Rain" with its amount: the condition beside the icon names it too
    def test_under_a_millimetre_is_unnamed_in_either_unit(self):
        assert not re.search(r"Rain \d", _today_row(0.8, metric=True))
        assert not re.search(r"Rain \d", _today_row(0.8, metric=False))

    def test_over_a_millimetre_is_named_in_either_unit(self):
        assert re.search(r"Rain \d", _today_row(1.2, metric=True))
        assert re.search(r"Rain \d", _today_row(1.2, metric=False))


def _snow_row(cm, mm, metric, with_snowfall=True):
    """The daily row for a snowy today: `cm` of snow from `mm` of water,
    each in the unit Open-Meteo sends it."""
    daily = {
        "time": ["2026-01-24", "2026-01-25", "2026-01-26"],
        "temperature_2m_max": [20, 18, 22],
        "temperature_2m_min": [5, 3, 8],
        "precipitation_sum": [0, mm if metric else mm / _MM_PER_INCH, 0],
        "precipitation_probability_max": [0, 90, 0],
        "weather_code": [3, 75, 3],
        "wind_speed_10m_max": [5, 5, 5],
    }
    if with_snowfall:
        daily["snowfall_sum"] = [0, cm if metric else cm / _CM_PER_INCH, 0]
    lines = render_daily({"daily": daily}, 100, _runtime(metric),
                         now=datetime(2026, 1, 25, 12))
    return lines[0]


class TestDailySnow:
    """A snowy day's amount is the snow, not the water it melts to."""

    def test_a_snowy_day_gives_its_snow_in_inches(self):
        # 8.9 cm of snow from 12.7 mm of water: 3.5 in, not 0.50 in
        row = _snow_row(8.9, 12.7, metric=False)
        assert re.search(r"Snow 3\.5″", row)
        assert "0.50″" not in row

    def test_a_snowy_day_gives_its_snow_in_centimetres(self):
        row = _snow_row(8.9, 12.7, metric=True)
        assert re.search(r"Snow 8\.9 ?cm", row)
        assert "13" not in row.split("Snow")[1][:8]

    def test_ten_and_more_go_without_their_tenth(self):
        assert re.search(r"Snow 12″", _snow_row(30.5, 43.2, metric=False))

    def test_a_forecast_without_snowfall_keeps_the_water(self):
        # A forecast cached before the snowfall was asked for
        assert re.search(r"Snow 0\.50″", _snow_row(8.9, 12.7, metric=False,
                                                    with_snowfall=False))


class TestDailyDates:
    """The day of the month beside each day is in the reader's calendar."""

    def _dates(self, lang):
        from linecast._runtime import WeatherRuntime
        daily = {
            "time": ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"],
            "temperature_2m_max": [80, 82, 84, 83],
            "temperature_2m_min": [60, 62, 64, 63],
            "precipitation_sum": [0, 0, 0, 0],
            "precipitation_probability_max": [0, 0, 0, 0],
            "weather_code": [1, 1, 1, 1],
            "wind_speed_10m_max": [5, 5, 5, 5],
        }
        runtime = WeatherRuntime(live=False, icons="plain", lang=lang, oneline=False,
                                 celsius=False, metric=False, shading=False)
        lines = render_daily({"daily": daily}, 110, runtime, now=datetime(2026, 9, 27, 12))
        # Persian digits read as their numbers
        return "\n".join(lines).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))

    def test_persian_gives_the_solar_hijri_day(self):
        # 28 and 29 September 2026 are 6 and 7 Mehr 1405
        text = self._dates("fa")
        assert re.search(r"\b6\b", text) and re.search(r"\b7\b", text)
        assert not re.search(r"\b2[89]\b", text)

    def test_english_gives_the_gregorian_day(self):
        text = self._dates("en")
        assert re.search(r"\b28\b", text) and re.search(r"\b29\b", text)


class TestCalmDays:
    """A day with nothing in its rain or wind columns has its condition
    muted; a day with odds, an amount, or wind keeps it in full ink."""

    MUTED = "\x1b[2m"

    def _rows(self, width=110):
        from unittest.mock import patch
        from linecast.weather import daily as daily_mod
        daily = {
            "time": ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"],
            "temperature_2m_max": [60, 59, 72, 80],
            "temperature_2m_min": [50, 55, 57, 57],
            "precipitation_sum": [0, 1.07, 0, 0],
            "precipitation_probability_max": [0, 93, 2, 2],
            "weather_code": [65, 65, 3, 3],
            "wind_speed_10m_max": [5, 10, 5, 30],
        }
        # the tests run without color, where MUTED is empty
        with patch.object(daily_mod, "MUTED", self.MUTED):
            return render_daily({"daily": daily}, width, _runtime(False),
                                now=datetime(2026, 9, 27, 12))

    def test_calm_day_is_muted(self):
        lines = self._rows()
        assert re.search(re.escape(self.MUTED) + r"[^\x1b]*Overcast", lines[1])

    def test_wet_and_windy_days_are_not(self):
        lines = self._rows()
        assert "Heavy rain" in lines[0] and self.MUTED not in lines[0]
        assert "Wind" in lines[2] and self.MUTED not in lines[2]

    def test_calm_is_the_day_not_the_width(self):
        # narrow enough that the wind column is dropped: the windy day
        # still is not calm
        lines = self._rows(width=28)
        assert "mph" not in lines[2]
        assert self.MUTED in lines[1] and self.MUTED not in lines[2]
