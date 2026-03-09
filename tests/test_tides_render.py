from datetime import datetime
import re
from types import SimpleNamespace

from linecast._tides_render import render_tide_ticks


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
