"""The cloud strip, the time lines through the lower hourly rows, and the
hover chips on the hourly chart and the daily rows."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from linecast import _color, _theme
from linecast._graphics import visible_len
from linecast._runtime import WeatherRuntime
from linecast._weather.daily import render_daily_mapped
from linecast._weather.hourly import (
    _build_precip_blocks, _indicator_row, _render_cloud_row, render_hourly,
)
from linecast._weather.sections import _prose
from linecast._weather.style import CLOUD_RGB, PRECIP_RAIN_RGB, TEXT
from linecast.weather import _build_daily_tooltip, _build_hover_tooltip

_FG = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_forecast.json"


def _runtime(metric=False):
    return WeatherRuntime(live=False, icons="nerd", lang="en", oneline=False, metric=metric,
                          use_24h=True)


def _plain(text):
    return _ANSI.sub("", text)


def _colors(line):
    return [tuple(int(v) for v in m.groups()) for m in _FG.finditer(line)]


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def test_cloud_strip_fades_with_cover():
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        line = _render_cloud_row([0, 50, 100], 3)
    assert _plain(line) == " ▄▄"
    half, full = _colors(line)
    assert full == tuple(CLOUD_RGB)
    assert _distance(half, _theme.theme_bg) < _distance(full, _theme.theme_bg)


def test_cloud_strip_carries_the_hover_line():
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        line = _render_cloud_row([0, 100, 100], 3, indicator_cols={0: (255, 0, 0), 2: (255, 0, 0)},
                                 through_col=2)
    assert _plain(line) == "│▄▄"
    hair, plain_cell, tinted = _colors(line)
    assert hair == (255, 0, 0)
    assert plain_cell == tuple(CLOUD_RGB)
    assert tinted != plain_cell
    assert _distance(tinted, (255, 0, 0)) < _distance(plain_cell, (255, 0, 0))


def test_fixed_time_lines_stop_behind_the_cloud():
    # A now line or midnight divider draws where the sky is clear and goes
    # behind the strip where there is cloud: a darker cell in a fixed
    # column would read as less cloud.
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        line = _render_cloud_row([0, 100, 100], 3, indicator_cols={0: (255, 0, 0), 2: (255, 0, 0)})
    assert _plain(line) == "│▄▄"
    hair, plain_cell, behind = _colors(line)
    assert hair == (255, 0, 0)
    assert plain_cell == behind == tuple(CLOUD_RGB)


def test_hover_line_tints_its_way_through_the_bar():
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        lines = _build_precip_blocks([5.0] * 3, [100] * 3, [61] * 3, 3, n_rows=1,
                                     indicator_cols={1: (255, 255, 255)}, full=5.0, through_col=1)
    assert _plain(lines[0]) == "███"
    left, middle, right = _colors(lines[0])
    assert left == right == tuple(PRECIP_RAIN_RGB)
    assert _distance(middle, (255, 255, 255)) < _distance(left, (255, 255, 255))


def test_fixed_time_lines_stop_behind_the_bar():
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        lines = _build_precip_blocks([5.0, 0.0, 5.0], [100] * 3, [61] * 3, 3, n_rows=1,
                                     indicator_cols={0: (255, 255, 255), 1: (255, 255, 255)},
                                     full=5.0)
    assert _plain(lines[0]) == "█│█"
    left, hair, right = _colors(lines[0])
    assert left == right == tuple(PRECIP_RAIN_RGB)
    assert hair == (255, 255, 255)


def test_indicator_row_is_only_the_lines():
    assert _indicator_row(5, {}) == ""
    row = _indicator_row(5, {1: (1, 2, 3), 4: (4, 5, 6)})
    assert _plain(row) == " │  │"


def _hourly_data(hours=72, wind=0.0, uv=0.0):
    start = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
    times = [(start + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(hours)]
    return {
        "hourly_units": {"precipitation": "inch"},
        "hourly": {
            "time": times,
            "temperature_2m": [70.0] * hours,
            "apparent_temperature": [70.0] * hours,
            "precipitation": [0.05] * hours,
            "precipitation_probability": [40] * hours,
            "weather_code": [61] * hours,
            "wind_speed_10m": [wind] * hours,
            "wind_direction_10m": [90] * hours,
            "relative_humidity_2m": [50] * hours,
            "dew_point_2m": [50.0] * hours,
            "uv_index": [uv] * hours,
            "cloud_cover": [80] * hours,
        },
        "daily": {"time": [], "sunrise": [], "sunset": []},
    }


def test_reserved_rows_carry_the_time_lines():
    """A wind row reserved for a gale later in the week, with none in
    this window, still shows the now line and midnight dividers."""
    data = _hourly_data(wind=0.0)
    data["hourly"]["wind_speed_10m"][-1] = 40.0
    now = datetime.fromisoformat(data["hourly"]["time"][24])
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        lines = render_hourly(data, 60, n_braille_rows=2, n_precip_rows=1, now=now,
                              runtime=_runtime())
    plain = [_plain(line) for line in lines]
    wind_row = plain[-3]  # wind, cloud, precip at the bottom
    assert set(wind_row) <= {" ", "│"}
    assert "│" in wind_row
    assert "▄" in plain[-2]


def test_hourly_chip_names_the_rain_and_the_cloud():
    data = _hourly_data()
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        chip = _build_hover_tooltip(data, 30, 5, 2, 12, 100, 40, _runtime())
    text = _plain(chip)
    assert "0.05″" in text
    assert "40% chance" in text
    assert "Cloud 80%" in text


def test_hourly_chip_shades_the_chance_like_the_bar():
    data = _hourly_data()
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        chip = _build_hover_tooltip(data, 30, 5, 2, 12, 100, 40, _runtime())
    expected = _theme.lerp_rgb(_theme.theme_bg, PRECIP_RAIN_RGB, 0.4)
    assert tuple(expected) in _colors(chip)


def test_daily_spans_cover_the_parts_they_name():
    data = json.loads(FIXTURE.read_text())
    lines, spans = render_daily_mapped(data, 100, _runtime())
    assert len(lines) == len(spans)
    assert all(0 < s["index"] < len(data["daily"]["time"]) for s in spans)
    for line, span in zip(lines, spans):
        plain = _plain(line)
        if "rain" in span["cols"]:
            a, b = span["cols"]["rain"]
            for mark in ("%", "″"):
                if mark in plain:
                    assert a <= visible_len(plain[:plain.rindex(mark)]) < b
        a, b = span["cols"]["bar"]
        assert visible_len(plain[:plain.index("°")]) >= a


def test_daily_chips_answer_for_each_part():
    data = json.loads(FIXTURE.read_text())
    runtime = _runtime()
    lines, spans = render_daily_mapped(data, 100, runtime)
    wet = next((k for k, s in enumerate(spans)
                if "rain" in s["cols"] and "″" in _plain(lines[k])), None)
    assert wet is not None, "the fixture should have a rainy day"
    daily_start = 20
    row = daily_start + wet + 1
    span = spans[wet]

    raw = {}
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        for field, (a, _b) in span["cols"].items():
            # A wide terminal, so the chip need not slide in from the edge.
            raw[field] = _build_daily_tooltip(data, a + 1, row, daily_start, spans,
                                              200, 40, runtime)
        off_row = _build_daily_tooltip(data, 1, daily_start + len(spans) + 1, daily_start, spans,
                                       100, 40, runtime)
    texts = {field: _plain(chip) for field, chip in raw.items()}
    assert off_row == ""
    day = datetime.fromisoformat(data["daily"]["time"][span["index"]]).strftime("%A")
    assert all(text.lstrip().startswith(day) for text in texts.values())
    assert re.search(r"\d+% chance of (rain|snow)", texts["rain"])
    assert re.search(r"\d\S*\u2033 between \d\d:\d\d and \d\d:\d\d", texts["rain"])
    assert re.search(r"heaviest around \d\d:\d\d", texts["rain"])
    assert texts["bar"].count("°") == 2
    assert "around" in texts["bar"]
    assert re.search(r"[A-Z][a-z]+", texts["day"].replace(day, ""))  # the conditions
    # The chip's left edge is at the pointer column, two rows below it.
    a = span["cols"]["rain"][0]
    assert f"\x1b[{row + 2};{a + 1}H" in raw["rain"]


def test_daily_rain_chip_says_through_the_day_for_all_day_rain():
    data = _hourly_data()
    times = data["hourly"]["time"]
    date = times[30][:10]
    data["hourly"]["precipitation"] = [0.02 if t.startswith(date) else 0.0 for t in times]
    data["daily"] = {
        "time": [times[0][:10], date, "2099-01-01"],
        "temperature_2m_max": [70, 70, 70],
        "temperature_2m_min": [60, 60, 60],
        "precipitation_sum": [0, 0.48, 0],
        "precipitation_probability_max": [0, 90, 0],
        "weather_code": [61, 61, 0],
        "wind_speed_10m_max": [5, 5, 5],
        "wind_gusts_10m_max": [8, 8, 8],
        "sunrise": [], "sunset": [],
    }
    runtime = _runtime()
    lines, spans = render_daily_mapped(data, 100, runtime)
    k = next(k for k, s in enumerate(spans) if s["index"] == 1)
    a = spans[k]["cols"]["rain"][0]
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        text = _plain(_build_daily_tooltip(data, a + 1, 21 + k, 20, spans, 100, 40, runtime))
    assert "90% chance of rain" in text
    assert "0.48″ through the day" in text
    assert "between" not in text


def test_hourly_chip_leaves_off_a_slim_chance():
    data = _hourly_data()
    data["hourly"]["precipitation_probability"] = [15] * len(data["hourly"]["time"])
    with patch.object(_color, "_COLOR_MODE", "truecolor"):
        text = _plain(_build_hover_tooltip(data, 30, 5, 2, 12, 100, 40, _runtime()))
    assert "0.05″" in text
    assert "chance" not in text


def test_prose_lines_are_in_the_text_color():
    assert _prose("Rain later.").startswith(TEXT)
    assert _prose("") == ""


def _daily_data(wind_on_rain_day):
    n = 8
    wind = [5.0] * n
    wind[2] = 18.0
    if wind_on_rain_day:
        wind[1] = 18.0
    return {"daily": {
        "time": [f"2026-09-{12 + i:02d}" for i in range(n)],
        "temperature_2m_max": [66, 65, 68, 67, 80, 69, 76, 68],
        "temperature_2m_min": [55, 55, 52, 46, 52, 58, 53, 51],
        "precipitation_sum": [0, 0.22, 0, 0, 0, 0.19, 0, 0],
        "precipitation_probability_max": [0, 74, 10, 10, 10, 32, 32, 30],
        "weather_code": [3, 61, 3, 3, 3, 61, 3, 3],
        "wind_speed_10m_max": wind,
    }}


def test_daily_rain_and_wind_share_a_column_when_no_day_has_both():
    lines, spans = render_daily_mapped(_daily_data(False), 90, _runtime())
    rain_row, wind_row = _plain(lines[0]), _plain(lines[1])
    assert rain_row.endswith("Rain 0.22″")
    assert wind_row.endswith("Wind 18mph")
    assert visible_len(rain_row) == visible_len(wind_row)
    assert spans[0]["cols"]["rain"][1] == spans[1]["cols"]["wind"][1]
    assert "wind" not in spans[0]["cols"]
    assert "rain" not in spans[1]["cols"]


def test_daily_rain_and_wind_keep_their_columns_when_a_day_has_both():
    lines, spans = render_daily_mapped(_daily_data(True), 90, _runtime())
    assert _plain(lines[0]).endswith("Rain 0.22″  Wind 18mph")
    assert spans[0]["cols"]["rain"][1] < spans[0]["cols"]["wind"][0]


def test_daily_words_go_before_the_bar_is_squeezed():
    wide, _ = render_daily_mapped(_daily_data(True), 70, _runtime())
    tight, spans = render_daily_mapped(_daily_data(True), 62, _runtime())
    assert "Rain" in _plain(wide[0]) and "Wind" in _plain(wide[0])
    assert _plain(tight[0]).endswith("74%  0.22″  18mph")
    a, b = spans[0]["cols"]["bar"]
    assert b - a >= 30
