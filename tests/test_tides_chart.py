from datetime import datetime, timedelta, timezone
import re
from types import SimpleNamespace

from linecast.tides.chart import (
    compute_daylight_window,
    compute_moon_labels,
    render_day_label_line,
    render_tide_ticks,
)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _canvas(line):
    return _ANSI_RE.sub("", line)


def _first_tick_idx(canvas):
    return next(i for i, ch in enumerate(canvas) if ch in ("\u2502", "\u2575"))


def test_render_tide_ticks_shift_with_scroll():
    runtime = SimpleNamespace(use_24h=False)
    graph_w = 80
    total_hours = 24

    baseline = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 0),
        total_hours,
        graph_w,
        runtime,
    ))
    shifted = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 30),
        total_hours,
        graph_w,
        runtime,
    ))

    assert _first_tick_idx(shifted) > _first_tick_idx(baseline)


def test_render_tide_ticks_anchor_to_clock_boundaries():
    runtime = SimpleNamespace(use_24h=True)
    graph_w = 80
    total_hours = 24

    canvas = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 1, 0),
        total_hours,
        graph_w,
        runtime,
    ))
    first_tick = _first_tick_idx(canvas)

    assert canvas[first_tick:first_tick + 3] == "\u257503"


def test_wider_time_window_keeps_hour_labels_spaced():
    canvas = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 0), 48, 192,
        SimpleNamespace(use_24h=True),
    ))
    ticks = [i for i, ch in enumerate(canvas) if ch in ("│", "╵")]
    assert len(ticks) == 16
    assert min(b - a for a, b in zip(ticks, ticks[1:])) >= 11
    assert canvas[ticks[1]:ticks[1] + 3] == "╵03"


def test_night_shading_follows_summer_time():
    # Portland, Maine, on 28 September: sunrise 6:34 and sunset 18:27
    # EDT. NOAA's metadata gives the standard offset, -5.
    from zoneinfo import ZoneInfo
    meta = {"lat": 43.658, "lng": -70.244, "timezonecorr": -5}
    start = datetime(2026, 9, 28, tzinfo=ZoneInfo("America/New_York"))
    daylight = compute_daylight_window(24 * 60, start, 24, meta)
    lit = [minute for minute, factor in enumerate(daylight) if factor >= 0.5]
    assert abs(lit[0] - (6 * 60 + 34)) < 25
    assert abs(lit[-1] - (18 * 60 + 27)) < 25


def test_aleutian_stations_keep_summer_time():
    from zoneinfo import ZoneInfo
    from linecast.tides.stations import _station_tzinfo
    adak = {"timezone_abbr": "HAST", "timezonecorr": -10, "observedst": True, "state": "AK"}
    assert _station_tzinfo(adak) == ZoneInfo("America/Adak")


def test_compute_moon_labels_contains_rise_and_set_over_two_days():
    runtime = SimpleNamespace(use_24h=False, icons="nerd")
    station_meta = {"lat": "44.3876", "lng": "-68.2039", "timezonecorr": -5}
    window_start = datetime(2026, 3, 5, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    graph_w = 120

    labels = compute_moon_labels(
        window_start,
        total_hours=48,
        graph_w=graph_w,
        station_meta=station_meta,
        runtime=runtime,
    )

    assert labels
    assert any(is_rise for _label, is_rise in labels.values())
    assert any(not is_rise for _label, is_rise in labels.values())
    assert all(0 < col < graph_w - 1 for col in labels)


def test_render_day_label_line_with_moon_labels():
    line = render_day_label_line(
        {10: "Friday"},
        graph_w=64,
        moon_labels={
            24: ("☽↑6:30a", True),   # ☽↑6:30a
            42: ("☾↓7:10p", False),  # ☾↓7:10p
        },
    )
    canvas = _canvas(line)

    assert "Friday" in canvas
    assert "☽↑6:30a" in canvas
    assert "☾↓7:10p" in canvas


def test_render_day_label_line_shifts_moon_label_when_overlapping_day_name():
    line = render_day_label_line(
        {10: "Friday"},
        graph_w=48,
        moon_labels={
            10: ("☽↑6:30a", True),  # preferred start collides with "Friday"
        },
    )
    canvas = _canvas(line)

    day_start = canvas.index("Friday")
    moon_start = canvas.index("☽↑6:30a")
    assert moon_start >= day_start + len("Friday") + 1
