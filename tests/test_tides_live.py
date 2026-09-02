"""TidesApp: the live tide view's window expansion."""

import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import tides
from linecast.tides import TidesApp

NOW = datetime(2026, 3, 5, 12, 0, 0)
TODAY = NOW.date()


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.answer = None   # None answers a real range; [] a failed fetch
        self.gate = None     # an Event holds the fetch until the test says go

    def tides_range(self, station_id, start, end, tz):
        if self.gate is not None:
            self.gate.wait(1.0)
        self.calls.append(("tides", station_id, start, end, tz))
        return [(start, 1.0), (end, 2.0)] if self.answer is None else self.answer

    def hilo_range(self, station_id, start, end, tz):
        self.calls.append(("hilo", station_id, start, end, tz))
        return [(start, "H")] if self.answer is None else self.answer


def _app():
    provider = FakeProvider()
    app = TidesApp(
        provider, "8418150", "Portland, ME", {"name": "Portland"}, "tz",
        SimpleNamespace(), [("p", 0.0)], [("h", "L")],
        TODAY - timedelta(days=7), TODAY + timedelta(days=7),
        y_range=(0, 4), marine_data={"m": 1},
    )
    return app, provider


class TestExpand:
    def test_no_expansion_while_the_window_is_inside_the_range(self):
        app, provider = _app()
        with patch.object(tides, "_station_now", return_value=NOW):
            app.expand_for(0)
            app.expand_for(24 * 60)
            app.expand_for(-24 * 60)
        assert provider.calls == []
        assert app._worker is None
        assert app.predictions == [("p", 0.0)]
        assert app.fetched_start == TODAY - timedelta(days=7)

    def test_scrolling_near_the_end_expands_a_week_past_the_view(self):
        app, provider = _app()
        with patch.object(tides, "_station_now", return_value=NOW):
            app.expand_for(6 * 24 * 60)
            app._worker.join(1.0)
        view_start = tides._live_window_start(
            NOW, offset_minutes=6 * 24 * 60, hours_shown=tides.LIVE_WINDOW_HOURS)
        view_end_date = (view_start + timedelta(hours=tides.LIVE_WINDOW_HOURS)).date()
        new_end = view_end_date + timedelta(days=7)
        old_start = TODAY - timedelta(days=7)
        assert provider.calls == [
            ("tides", "8418150", old_start, new_end, "tz"),
            ("hilo", "8418150", old_start, new_end, "tz"),
        ]
        assert app.fetched_start == old_start
        assert app.fetched_end == new_end
        assert app.predictions == [(old_start, 1.0), (new_end, 2.0)]
        assert app.hilo == [(old_start, "H")]

    def test_scrolling_near_the_start_expands_a_week_before_the_view(self):
        app, provider = _app()
        with patch.object(tides, "_station_now", return_value=NOW):
            app.expand_for(-6 * 24 * 60)
            app._worker.join(1.0)
        view_start = tides._live_window_start(
            NOW, offset_minutes=-6 * 24 * 60, hours_shown=tides.LIVE_WINDOW_HOURS)
        new_start = view_start.date() - timedelta(days=7)
        old_end = TODAY + timedelta(days=7)
        assert provider.calls[0] == ("tides", "8418150", new_start, old_end, "tz")
        assert app.fetched_start == new_start
        assert app.fetched_end == old_end
        assert isinstance(app.fetched_start, date)

    def test_an_empty_fetch_keeps_the_range_and_waits_before_retrying(self):
        app, provider = _app()
        provider.answer = []   # the providers answer empty on a dead network
        with patch.object(tides, "_station_now", return_value=NOW):
            app.expand_for(6 * 24 * 60)
            app._worker.join(1.0)
            calls = len(provider.calls)
            app.expand_for(6 * 24 * 60)   # inside the retry pause
        assert app.predictions == [("p", 0.0)]
        assert app.hilo == [("h", "L")]
        assert app.fetched_end == TODAY + timedelta(days=7)
        assert app._retry_at > 0
        assert len(provider.calls) == calls


class TestRender:
    def test_render_draws_what_it_has_while_the_expansion_lands(self):
        app, provider = _app()
        provider.gate = threading.Event()
        old_predictions, old_hilo = app.predictions, app.hilo
        with patch.object(tides, "_station_now", return_value=NOW), \
             patch.object(tides, "render", return_value="frame") as render:
            out = app.render(offset_minutes=6 * 24 * 60, mouse_pos=(4, 5))
            provider.gate.set()
            app._worker.join(1.0)
        assert out == ("frame", {})
        render.assert_called_once_with(
            "8418150", "Portland, ME", station_meta={"name": "Portland"},
            runtime=app.runtime, fullscreen=True,
            offset_minutes=6 * 24 * 60, mouse_pos=(4, 5),
            predictions=old_predictions, hilo=old_hilo,
            y_range=(0, 4), marine_data={"m": 1}, provider=app.provider,
        )
        assert provider.calls           # the expansion still ran
        assert app.predictions != old_predictions  # and landed for the next frame


class TestTuning:
    def test_the_loop_settings_are_the_tide_ones(self):
        assert TidesApp.interval == 60
        assert TidesApp.scroll_step == 30
        assert TidesApp.mouse is True
        assert _app()[0].hooks() == {}
