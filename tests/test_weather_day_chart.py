"""The daily hover's curve uses the day's clock, even with missing hours."""

from datetime import datetime, timedelta
import re

import pytest

from linecast._runtime import WeatherRuntime
from linecast.terminal.braille import DOT_BITS
from linecast.terminal.textwidth import visible_len
from linecast.weather.day_chart import temperature_chip
from linecast.weather.view import _build_daily_tooltip


DAY = datetime(2026, 10, 7)


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def runtime(use_24h=True):
    return WeatherRuntime(live=False, icons="plain", lang="en", oneline=False,
                          celsius=False, use_24h=use_24h)


def hourly(hours=range(25)):
    return {"time": [(DAY + timedelta(hours=h)).isoformat() for h in hours],
            "temperature_2m": [40 + 40 * (1 - abs(h - 12) / 12) for h in hours]}


def chart(data=None, cols=60, rows=24, use_24h=True):
    return temperature_chip(hourly() if data is None else data, DAY.date().isoformat(),
                            40, 80, cols, rows, runtime(use_24h))


def dots(lines):
    """Raised dots indexed by x, reading the rendered graph after its scale."""
    columns = {}
    for row, line in enumerate(lines[:-1]):
        for col, char in enumerate(strip_ansi(line)[5:-1]):
            if not "\u2800" <= char <= "\u28ff":
                continue
            for x in range(2):
                for y in range(4):
                    if (ord(char) - 0x2800) & DOT_BITS[x][y]:
                        columns.setdefault(col * 2 + x, set()).add(row * 4 + y)
    return columns


def test_curve_runs_between_midnights_with_noon_in_the_middle():
    lines = chart()
    curve = dots(lines)
    assert len(lines) == 4
    assert curve[0] == curve[49] == {11}
    assert 0 in curve[24]
    assert strip_ansi(lines[0]).startswith(" 80° ")
    assert strip_ansi(lines[2]).startswith(" 40° ")
    assert strip_ansi(lines[-1]).split() == ["00", "06", "12", "18", "00"]


def test_midnight_endpoint_does_not_include_the_following_day():
    data = hourly(range(27))
    data["temperature_2m"][-2:] = [150, 160]
    assert chart(data) == chart()


def test_last_hour_is_not_stretched_to_midnight():
    curve = dots(chart(hourly(range(24))))
    assert max(curve) == 47
    assert 0 in curve[24]


def test_partial_day_keeps_its_hours():
    curve = dots(chart(hourly(range(12, 25))))
    assert min(curve) == 24
    assert max(curve) == 49


@pytest.mark.parametrize("omit_stamps", [False, True])
def test_missing_hours_leave_a_gap(omit_stamps):
    data = hourly()
    if omit_stamps:
        data = hourly([h for h in range(25) if not 8 <= h <= 13])
    else:
        data["temperature_2m"][8:14] = [None] * 6
    curve = dots(chart(data))
    assert not any(x in curve for x in range(16, 28))
    assert min(curve) == 0 and max(curve) == 49


@pytest.mark.parametrize("hours", [
    [h for h in range(25) if h != 2],
    [0, 1, 1, *range(2, 25)],
])
def test_clock_changes_keep_noon_at_noon(hours):
    curve = dots(chart(hourly(hours)))
    assert 0 in curve[24]
    assert curve[0] == curve[49] == {11}


def test_a_constant_temperature_is_a_flat_line():
    data = hourly()
    data["temperature_2m"] = [60] * 25
    lines = temperature_chip(data, DAY.date().isoformat(), 60, 60, 60, 24,
                             runtime())
    curve = dots(lines)
    assert len(curve) == 50
    assert len({y for ys in curve.values() for y in ys}) == 1
    assert sum(strip_ansi(line).count("60°") for line in lines) == 1


def test_axis_respects_the_clock_preference():
    assert strip_ansi(chart(use_24h=False)[-1]).split() == ["12a", "6a", "12p", "6p", "12a"]


@pytest.mark.parametrize("cols,rows", [(60, 24), (25, 5), (21, 5)])
def test_small_terminals_keep_both_midnight_labels(cols, rows):
    lines = chart(cols=cols, rows=rows, use_24h=False)
    assert lines and len(lines) + 2 <= rows  # heading and shadow
    assert all(visible_len(line) + 1 <= cols for line in lines)
    labels = strip_ansi(lines[-1]).split()
    assert labels[0] == labels[-1] == "12a"


@pytest.mark.parametrize("data", [{}, {"time": None, "temperature_2m": None},
                                  hourly([12]), {"time": ["bad", None]}])
def test_no_usable_hourly_curve_leaves_the_daily_values(data):
    date = DAY.date().isoformat()
    chip = _build_daily_tooltip(
        {"hourly": data, "daily": {"time": [date], "temperature_2m_min": [40],
                                    "temperature_2m_max": [80]}},
        10, 10, 9, [{"index": 0, "cols": {"bar": (0, 40)}}], 60, 24,
        runtime(), now=DAY)
    plain = strip_ansi(chip)
    assert "40°" in plain and "80°" in plain
    assert not any("\u2800" <= ch <= "\u28ff" for ch in plain)


@pytest.mark.parametrize("cols,rows", [(17, 24), (60, 4)])
def test_too_little_space_uses_the_daily_values(cols, rows):
    assert chart(cols=cols, rows=rows) == []
