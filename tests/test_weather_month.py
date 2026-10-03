"""The month's real hours, comparison scale, and cached requests."""

import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from linecast._runtime import WeatherRuntime
from linecast.terminal import color
from linecast.terminal.textwidth import visible_len

from linecast.weather import month


def payload(start, values, zone="UTC"):
    return {"timezone": zone, "hourly": {
        "time": [(start + timedelta(hours=k)).timestamp() for k in range(len(values))],
        "temperature_2m": values}}


def runtime(**kwargs):
    return replace(WeatherRuntime.defaults(), **kwargs)


def test_real_hours_preserve_the_spring_gap_and_average_the_autumn_fold():
    spring = payload(datetime(2025, 3, 9, 5, tzinfo=timezone.utc), [0, 2, 4, 6],
                     "America/New_York")
    fall = payload(datetime(2025, 11, 2, 4, tzinfo=timezone.utc), [0, 2, 4, 6],
                   "America/New_York")
    series = month.Temperatures.build([spring, fall], (2016, 2025))
    assert series.days[date(2025, 3, 9)][:5] == (0, 2, None, 4, 6)
    assert series.at(date(2025, 3, 9), 1.5) is None
    assert series.at(date(2025, 3, 9), 2.5) is None
    assert series.days[date(2025, 11, 2)][:3] == (0, 3, 6)
    assert (date(2025, 11, 2), 1) in series.repeated


def test_missing_nonfinite_and_overlapping_samples_do_not_bias_the_average():
    first = payload(datetime(2020, 1, 1, tzinfo=timezone.utc), [10, None, float("nan")])
    second = payload(datetime(2021, 1, 1, tzinfo=timezone.utc), [20, 30, float("inf")])
    current = payload(datetime(2026, 1, 1, tzinfo=timezone.utc), [100, 100, 100])
    series = month.Temperatures.build([first, first, second, current], (2016, 2025))
    assert series.at(date(2026, 1, 1), 0, normal=True) == 15
    assert series.at(date(2026, 1, 1), 1, normal=True) == 30
    assert series.at(date(2026, 1, 1), 2, normal=True) is None
    assert series.at(date(2026, 1, 1), 0) == 100
    assert not series.repeated


def test_seasonal_window_wraps_new_year_and_keeps_clock_hours_separate():
    a = payload(datetime(2020, 12, 31, tzinfo=timezone.utc), [10, 30])
    b = payload(datetime(2021, 1, 2, tzinfo=timezone.utc), [20, 40])
    outside = payload(datetime(2021, 1, 9, tzinfo=timezone.utc), [100, 100])
    series = month.Temperatures.build([a, b, outside], (2016, 2025))
    assert series.at(date(2026, 1, 1), 0, normal=True) == 15
    assert series.at(date(2026, 1, 1), 1, normal=True) == 35


def test_interpolation_crosses_midnight_but_not_missing_samples():
    p = payload(datetime(2025, 9, 30, 23, tzinfo=timezone.utc), [10, 20, None])
    series = month.Temperatures.build([p], (2016, 2025))
    assert series.at(date(2025, 9, 30), 23.5) == 15
    assert series.at(date(2025, 10, 1), 0.5) is None


def test_fahrenheit_differences_are_converted_without_an_offset():
    rt = runtime(celsius=False)
    assert month.shown_temperature(10, rt) == 50
    assert month.shown_temperature(10, rt, difference=True) == 18
    assert month.temperature_text(-0.001, rt, difference=True) == "0.0°F"


@pytest.mark.parametrize("size", [(100, 40), (80, 24), (54, 23)])
@pytest.mark.parametrize("difference", [False, True])
def test_month_fits_and_preserves_the_last_day_and_complete_color_escapes(size, difference):
    values = [10 + k % 24 / 2 for k in range(32 * 24)]
    p = payload(datetime(2025, 10, 1, tzinfo=timezone.utc), values)
    series = month.Temperatures.build([p], (2016, 2025))
    rt = runtime(celsius=False)
    with patch.object(month, "get_terminal_size", return_value=size), \
         patch.object(color, "color_mode", return_value="truecolor"):
        rendered = month.render_month(series, date(2025, 10, 1), rt, 43, -70,
                                      "Portland", difference=difference)
    lines = rendered.splitlines()
    assert len(lines) <= size[1]
    assert max(map(visible_len, lines)) <= size[0]
    assert "Fri 31" in rendered
    assert "Open-Meteo" in lines[-1]
    assert "\x1b" not in re.sub(r"\x1b\[[0-9;]*m", "", rendered)


@pytest.mark.parametrize('lang', ['en', 'fr', 'de', 'ja', 'zh-Hant', 'ar', 'fa'])
@pytest.mark.parametrize('size', [(100, 40), (80, 24), (54, 23)])
def test_localized_layout_keeps_heading_with_chart_and_legend_within_window(lang, size):
    from linecast.weather.i18n import _s
    p = payload(datetime(2025, 10, 1, tzinfo=timezone.utc), [10.234] * (32 * 24))
    series = month.Temperatures.build([p], (2016, 2025))
    rt = runtime(lang=lang, celsius=False)
    with patch.object(month, 'get_terminal_size', return_value=size):
        output = month.render_month(series, date(2025, 10, 1), rt, 43, -70,
                                    'A very long location name for this view', location_menu=True)
    lines = re.sub(r'\x1b\[[0-9;]*m', '', output).splitlines()
    assert len(lines) <= size[1]
    assert max(map(visible_len, lines)) <= size[0]
    title = next(i for i, line in enumerate(lines) if _s('month_temperature', rt) in line)
    assert '─' in lines[title + 1]
    first_day = title + 2 + (not lines[title + 2].strip())
    assert '1' in lines[first_day]  # at most one blank row beneath the rule
    if size == (100, 40):
        assert not lines[title + 2].strip()
    legends = [line for line in lines if '50°F' in line]
    assert len(legends) == 1
    assert '.4°F' not in legends[0]
    if lang == 'en' and size[0] == 100:
        assert 'sunrise / sunset' in legends[0]


def test_new_strings_exist_in_every_language_with_matching_placeholders():
    import importlib
    from string import Formatter
    from linecast._i18n import LANGUAGE_CODES
    reference = importlib.import_module('linecast.locales.en')
    for code in LANGUAGE_CODES:
        locale = importlib.import_module('linecast.locales.' + code.replace('-', '_'))
        for table in ['WEATHER', 'HELP']:
            for key, english in getattr(reference, table).items():
                if key.startswith('month_') or key in ('weather_views', 'history_refresh'):
                    translated = getattr(locale, table)[key]
                    def fields(value):
                        return {f for _, f, _, _ in Formatter().parse(value) if f}
                    assert fields(translated) == fields(english), (code, key)
