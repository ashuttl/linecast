"""How the weather dashboard spends a short or tall window."""
import json
import math
import re
from pathlib import Path
from unittest.mock import patch

from linecast import weather
from linecast._runtime import WeatherRuntime
from linecast._weather.render import WIND_ARROWS

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_forecast.json"


def _rows(rows, cols=100, live=True):
    data = json.loads(FIXTURE.read_text())
    runtime = WeatherRuntime(live=live, icons="nerd", lang="en", oneline=False, metric=False)
    with patch.object(weather, "get_terminal_size", lambda: (cols, rows)), \
            patch.object(weather, "install_banner", lambda: None):
        output, _ = weather.render_from_data(data, [], runtime, "Test")
    return [_ANSI.sub("", line).rstrip() for line in output.split("\n")]


def _blank_positions(lines):
    return [i for i, line in enumerate(lines) if line == ""]


def test_a_tall_window_keeps_every_spacing_row():
    lines = _rows(40)
    assert len(lines) <= 40
    blanks = _blank_positions(lines)
    assert 1 in blanks                       # under the header
    assert len(lines) - 2 in blanks          # above the credit row
    assert len(blanks) >= 3                  # and one before the daily rows


def test_a_short_window_gives_up_the_spacing_rows_first():
    lines = _rows(18)
    assert len(lines) <= 18
    assert _blank_positions(lines) == []
    assert "\u2575" in lines[2]   # the tick row sits right under the day line
    assert any("°" in line and "─" in line for line in lines)   # daily rows survive


def test_the_window_is_never_overrun():
    for rows in (12, 16, 20, 24, 30, 50):
        assert len(_rows(rows)) <= rows


def _rows_with_peak_rain(rows, peak_inches):
    data = json.loads(FIXTURE.read_text())
    amounts = data["hourly"]["precipitation"]
    scale = peak_inches / max(amounts)
    data["hourly"]["precipitation"] = [a * scale for a in amounts]
    runtime = WeatherRuntime(live=True, icons="nerd", lang="en", oneline=False, metric=False)
    with patch.object(weather, "get_terminal_size", lambda: (100, rows)), \
            patch.object(weather, "install_banner", lambda: None):
        output, _ = weather.render_from_data(data, [], runtime, "Test")
    return [_ANSI.sub("", line).rstrip() for line in output.split("\n")]


def _curve_rows(lines):
    return sum(1 for line in lines if any("⠀" <= ch <= "⣿" for ch in line))


def test_a_drizzle_gives_its_bar_rows_to_the_curve():
    downpour = _rows_with_peak_rain(40, 1.0)
    shower = _rows_with_peak_rain(40, 0.1)
    drizzle = _rows_with_peak_rain(40, 0.01)
    assert len(downpour) <= 40 and len(drizzle) <= 40
    assert _curve_rows(shower) == _curve_rows(downpour) + 1
    assert _curve_rows(drizzle) == _curve_rows(downpour) + 2


def test_a_short_window_still_keeps_one_bar_row():
    assert len(_rows_with_peak_rain(14, 1.0)) <= 14
    assert len(_rows_with_peak_rain(14, 0.01)) <= 14


# The rows under the curve, and the order they give way in as the window
# shrinks: the UV labels first, then the wind row, then the cloud strip.

_UV = re.compile(r"UV\d")
_WIND_ROW = re.compile(r"[\s\u2502]*(?:[" + "".join(WIND_ARROWS) + r"]\d+[\s\u2502]*)+")
_CURVE = re.compile("[⠀-⣿]")


def _data_with_rows(wind="midday"):
    """The fixture with UV, cloud cover and a chosen wind: gusts at midday,
    which would collide with the UV labels, gusts at night, which share
    their row, or none."""
    data = json.loads(FIXTURE.read_text())
    hourly = data["hourly"]
    n = len(hourly["time"])
    hourly["uv_index"] = [max(0.0, 8 * math.sin((i % 24 - 6) / 12 * math.pi)) for i in range(n)]
    hourly["cloud_cover"] = [60 + 40 * math.sin(i / 7) for i in range(n)]   # never clear
    windy = {"midday": (12, 13, 14), "night": (0, 1, 2), "none": ()}[wind]
    hourly["wind_speed_10m"] = [30.0 if (i % 24) in windy else 3.0 for i in range(n)]
    return data


def _under_the_curve(rows, wind="midday"):
    """What the hourly section holds at this height: the curve's rows, and
    whether the UV labels, the wind row and the cloud strip are in."""
    runtime = WeatherRuntime(live=True, icons="nerd", lang="en", oneline=False, metric=False)
    with patch.object(weather, "get_terminal_size", lambda: (100, rows)), \
            patch.object(weather, "install_banner", lambda: None):
        output, _ = weather.render_from_data(_data_with_rows(wind), [], runtime, "Test")
    lines = [_ANSI.sub("", line).rstrip() for line in output.split("\n")]
    assert len(lines) == rows, f"{len(lines)} lines in {rows} rows"
    cloud = any(len(line) > 90 and set(line) <= {"▄", "│"} for line in lines)
    return {
        "curve": sum(1 for line in lines if _CURVE.search(line)),
        "uv": any(_UV.search(line) for line in lines),
        "wind": any(_WIND_ROW.fullmatch(_UV.sub("", line)) for line in lines),
        "cloud": cloud,
    }


def _leaving_order(wind):
    """The rows under the curve as each one leaves, from a tall window
    down to a short one: a list of (uv, wind, cloud) with the repeats
    dropped."""
    states = []
    for rows in range(30, 12, -1):
        got = _under_the_curve(rows, wind)
        state = (got["uv"], got["wind"], got["cloud"])
        if got["uv"] or got["wind"] or got["cloud"]:
            assert got["curve"] >= weather.MIN_CURVE_ROWS_WITH_CLOUD, f"{rows} rows: {got}"
        if not states or states[-1] != state:
            states.append(state)
    return states


def test_the_uv_row_leaves_first_then_the_wind_then_the_cloud_strip():
    assert _leaving_order("midday") == [
        (True, True, True),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ]


def test_uv_labels_on_the_wind_row_leave_with_it():
    assert _leaving_order("night") == [
        (True, True, True),
        (False, False, True),
        (False, False, False),
    ]


def test_without_wind_the_uv_row_still_leaves_before_the_cloud_strip():
    assert _leaving_order("none") == [
        (True, False, True),
        (False, False, True),
        (False, False, False),
    ]
