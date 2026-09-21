"""Scrubbing must reverse immediately at either end of the hourly chart."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_live_hover import run_loop
from linecast import weather
from linecast._weather.hourly import _prepare_hourly_window


def make_app(monkeypatch, count=120, width=80):
    start = datetime(2026, 9, 18)
    now = start + timedelta(hours=12, minutes=30)
    hourly = {
        "time": [(start + timedelta(hours=i)).isoformat() for i in range(count)],
        "temperature_2m": list(range(count)),
    }
    monkeypatch.setattr(weather, "_local_now_for_data", lambda data: now)
    monkeypatch.setattr(weather, "get_terminal_size", lambda: (width, 24))
    app = weather.WeatherApp({"hourly": hourly}, [], None, 43, -70,
                             SimpleNamespace(lang="en"))
    return app, hourly, now


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("keyboard", [False, True])
@pytest.mark.parametrize("coalesce", [False, True])
def test_reverse_after_overscrolling(monkeypatch, direction, keyboard, coalesce):
    app, hourly, now = make_app(monkeypatch)
    frames = []

    def action(step):
        if keyboard:
            return 'fwd' if step > 0 else 'back'
        return ('mouse', 64 if step > 0 else 65, 40, 10, False)

    def render(offset_minutes=0, **_):
        window = _prepare_hourly_window(hourly, now, 80, offset_minutes)
        frames.append(window['start_idx'])
        return '.'

    # Go far beyond the data, then reverse one notch in the same input burst.
    script = [(0, action(direction))] * 150
    script += [(0, action(-direction)), (0.01, 'quit')]
    run_loop(monkeypatch, script, render_fn=render, coalesce=coalesce,
             scroll_step=app.scroll_step, **app.hooks())
    # At 80 columns the window spans 40 hours: its last start is hour 79.
    assert frames[-1] == (78 if direction > 0 else 1)
    if coalesce:
        assert len(frames) == 2


@pytest.mark.parametrize("width, last_start", [(40, 95), (80, 79), (120, 71)])
def test_bounds_follow_chart_width(monkeypatch, width, last_start):
    app, _, _ = make_app(monkeypatch, width=width)
    assert app.clamp_offset(-100000) == -12 * 60
    assert app.clamp_offset(100000) == (last_start - 12) * 60


def test_resize_reclamps_before_reversing(monkeypatch):
    app, hourly, now = make_app(monkeypatch, width=40)
    frames = []

    def render(offset_minutes=0, **_):
        width = weather.get_terminal_size()[0]
        frames.append(_prepare_hourly_window(hourly, now, width, offset_minutes)['start_idx'])
        if len(frames) == 2:
            monkeypatch.setattr(weather, 'get_terminal_size', lambda: (120, 24))
        return '.'

    script = [(0, 'fwd')] * 150 + [(0.01, 'back'), (0.01, 'quit')]
    run_loop(monkeypatch, script, render_fn=render, coalesce=True,
             scroll_step=app.scroll_step, **app.hooks())
    assert frames == [12, 95, 70]


@pytest.mark.parametrize("count", [0, 1, 12])
def test_short_or_missing_forecast_cannot_accumulate_offset(monkeypatch, count):
    app, _, _ = make_app(monkeypatch, count=count)
    assert app.clamp_offset(100000) == app.clamp_offset(-100000)
