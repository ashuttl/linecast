"""Tests for the wind and UV label rows under the hourly chart.

Both rows are laid out on a canvas covering the whole forecast, not just the
visible day, so the labels hold still while the chart scrolls under them. The
mapping back into the window has to move each label whole: sampling it column
by column dropped and doubled digits, turning a 22mph wind into "220".
"""

import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import WeatherRuntime
from linecast.weather.hourly import render_hourly
from linecast.weather.style import WIND_ARROWS

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_WIND_LABEL = re.compile(f"[{WIND_ARROWS}]" + r"\d+")
_UV_LABEL = re.compile(r"UV\d+", re.IGNORECASE)
_HOURS = 168
_T0 = datetime(2026, 3, 1, 0, 0)
_WIDTH = 100


def _forecast(night_wind_only=False, afternoon_gust_on_day=None):
    """A week of hourly data with windy spells and sunny afternoons.

    With night_wind_only the wind drops calm from 5am to 8pm, so no wind
    label can land beside a UV label; afternoon_gust_on_day adds one
    windy 3pm back on that day."""
    times = [(_T0 + timedelta(hours=i)).isoformat() for i in range(_HOURS)]
    temps = [10 + 8 * math.sin(i / 24 * 2 * math.pi) for i in range(_HOURS)]
    winds = [18 + 12 * math.sin(i / 17 * 2 * math.pi) + 4 * math.sin(i / 5)
             for i in range(_HOURS)]
    if night_wind_only:
        winds = [w if (i % 24) < 5 or (i % 24) >= 20 else 3.0 for i, w in enumerate(winds)]
    if afternoon_gust_on_day is not None:
        for h in (14, 15, 16):
            winds[afternoon_gust_on_day * 24 + h] = 30.0
    uv = [max(0.0, 9 * math.sin((i % 24 - 6) / 12 * math.pi)) for i in range(_HOURS)]
    return {
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "apparent_temperature": temps,
            "dew_point_2m": temps,
            "relative_humidity_2m": [80] * _HOURS,
            "precipitation_probability": [20] * _HOURS,
            "weather_code": [61] * _HOURS,
            "wind_speed_10m": winds,
            "wind_direction_10m": [(i * 37) % 360 for i in range(_HOURS)],
            "uv_index": uv,
        },
        "daily": {"time": [], "sunrise": [], "sunset": []},
    }


def _runtime():
    return WeatherRuntime(live=False, icons=True, lang="en", oneline=False, metric=False)


def _rows(offset_minutes, data=None):
    """Return the plain-text wind and UV rows at a given scroll offset."""
    lines = render_hourly(data or _forecast(), _WIDTH, now=_T0 + timedelta(hours=6),
                          runtime=_runtime(), offset_minutes=offset_minutes)
    wind = uv = ""
    for line in lines:
        plain = _ANSI.sub("", line)
        if "°" in plain:
            continue  # the temperature curve also carries arrows and digits
        if not wind and _WIND_LABEL.search(plain):
            wind = plain
        if not uv and _UV_LABEL.search(plain):
            uv = plain
    return wind, uv


def _labels(row, pattern):
    """Return (column, text) for every label in a row."""
    return [(m.start(), m.group()) for m in pattern.finditer(row)]


def _offsets(step=20, hours=48):
    return range(0, hours * 60, step)


def _assert_labels_creep(pattern, row_index):
    """A label away from the edges stays put, give or take a column.

    Scrolling by 20 minutes slides the chart under the labels by less than a
    column, so a label with room to spare on either side should still be there,
    and near enough to where it was, in the next frame. Labels at the edges are
    exempt: those are arriving or leaving.
    """
    previous = []
    for offset in _offsets(hours=24):
        current = _labels(_rows(offset)[row_index], pattern)
        for col, text in previous:
            if col < 4 or col + len(text) + 4 > _WIDTH:
                continue
            near = [c for c, t in current if t == text and abs(c - col) <= 2]
            assert near, f"{text} at column {col} moved or vanished at offset {offset}"
        previous = current


class TestWindLabels:
    def test_every_label_is_an_arrow_and_a_plausible_speed(self):
        data = _forecast()
        fastest = max(data["hourly"]["wind_speed_10m"])
        for offset in _offsets():
            wind, _ = _rows(offset)
            for _, text in _labels(wind, _WIND_LABEL):
                speed = int(text[1:])
                assert speed <= fastest + 1, f"{text} at offset {offset}"

    def test_no_stray_digits_beside_a_label(self):
        # A doubled digit shows up as a run of characters longer than the
        # label that produced it.
        for offset in _offsets():
            wind, _ = _rows(offset)
            for run in re.findall(r"[^ │╵]+", wind):
                if run[0] in WIND_ARROWS:
                    assert _WIND_LABEL.fullmatch(run), f"{run!r} at offset {offset}"

    def test_labels_hold_still_while_scrolling(self):
        # Scrolling by 20 minutes moves the chart under the labels by about
        # one column; a label that survives the step should move with it.
        _assert_labels_creep(_WIND_LABEL, 0)


class TestNowMarker:
    """A line marks the current time, like the midnight dividers (issue #49)."""

    def _tick_line(self, now, offset_minutes):
        lines = render_hourly(_forecast(), _WIDTH, now=now, runtime=_runtime(),
                              offset_minutes=offset_minutes)
        return _ANSI.sub("", lines[1])

    def test_marks_now_when_scrolled_into_the_past(self):
        # Window starts 10 hours before now; the marker lands mid-chart, in
        # the same column the divider formula gives.
        now = _T0 + timedelta(hours=20)
        tick = self._tick_line(now, offset_minutes=-600)
        graph_w = _WIDTH
        col = int(10 / 48 * (graph_w - 1))
        assert tick[col] == "│", f"no now marker at column {col}: {tick!r}"
        assert tick[col + 1] == " "  # not a midnight "│00" label

    def test_no_marker_once_now_is_behind_the_window(self):
        # Scrolled 10 hours ahead, now is left of the window; only the two
        # midnight "│00" labels remain.
        now = _T0 + timedelta(hours=20)
        tick = self._tick_line(now, offset_minutes=600)
        assert tick.count("│") == 2


class TestUVLabels:
    def test_every_label_is_a_plausible_index(self):
        for offset in _offsets():
            _, uv = _rows(offset)
            for _, text in _labels(uv, _UV_LABEL):
                assert 3 <= int(text[2:]) <= 15, f"{text} at offset {offset}"

    def test_labels_hold_still_while_scrolling(self):
        _assert_labels_creep(_UV_LABEL, 1)


class TestSharedRow:
    """Wind and UV share a row when no label of one would meet one of the
    other anywhere in the week; otherwise each keeps its own."""

    def _line_count(self, data, offset=0):
        return len(render_hourly(data, _WIDTH, now=_T0 + timedelta(hours=6),
                                 runtime=_runtime(), offset_minutes=offset))

    def test_share_a_row_when_they_never_meet(self):
        data = _forecast(night_wind_only=True)
        for offset in _offsets():
            wind, uv = _rows(offset, data)
            if wind and uv:
                assert wind == uv, f"two rows at offset {offset}"
        assert self._line_count(data) == self._line_count(_forecast()) - 1

    def test_shared_labels_keep_a_gap_between_kinds(self):
        data = _forecast(night_wind_only=True)
        for offset in _offsets():
            row, _ = _rows(offset, data)
            for run in re.findall(r"[^ │╵]+", row):
                assert _WIND_LABEL.fullmatch(run) or _UV_LABEL.fullmatch(run), \
                    f"{run!r} at offset {offset}"

    def test_keep_two_rows_when_they_would_collide(self):
        for offset in _offsets():
            wind, uv = _rows(offset)
            assert wind and uv and wind != uv, f"offset {offset}"
            assert not _UV_LABEL.search(wind) and not _WIND_LABEL.search(uv)

    def test_the_choice_holds_for_the_whole_forecast(self):
        # One windy afternoon on day five is enough to keep two rows all
        # week, so the chart does not change height on the way there.
        data = _forecast(night_wind_only=True, afternoon_gust_on_day=5)
        two_rows = self._line_count(_forecast())
        for offset in _offsets():
            assert self._line_count(data, offset) == two_rows, f"offset {offset}"
            wind, uv = _rows(offset, data)
            assert not _UV_LABEL.search(wind) and not _WIND_LABEL.search(uv)

