from datetime import datetime, timedelta, timezone
import re
from types import SimpleNamespace

from linecast._tides_render import (
    compute_moon_labels,
    render_day_label_line,
    render_tide_ticks,
)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _canvas(line):
    plain = _ANSI_RE.sub("", line)
    return plain[1:] if plain.startswith(" ") else plain


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


def test_compute_moon_labels_contains_rise_and_set_over_two_days():
    runtime = SimpleNamespace(use_24h=False, emoji=False)
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
            24: ("\u263D\u21916:30a", True),   # ☽↑6:30a
            42: ("\u263E\u21937:10p", False),  # ☾↓7:10p
        },
    )
    canvas = _canvas(line)

    assert "Friday" in canvas
    assert "\u263D\u21916:30a" in canvas
    assert "\u263E\u21937:10p" in canvas


def test_render_day_label_line_shifts_moon_label_when_overlapping_day_name():
    line = render_day_label_line(
        {10: "Friday"},
        graph_w=48,
        moon_labels={
            10: ("\u263D\u21916:30a", True),  # preferred start collides with "Friday"
        },
    )
    canvas = _canvas(line)

    day_start = canvas.index("Friday")
    moon_start = canvas.index("\u263D\u21916:30a")
    assert moon_start >= day_start + len("Friday") + 1
