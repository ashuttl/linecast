"""Tests for radar source selection and frame bookkeeping.

No network access: RainViewerSource is only exercised with fetch_index
monkeypatched to a stub, never the real HTTP call.
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_rainviewer as rv
from linecast._radar_source import _floor_step, frame_times
from linecast._radar_sources import (
    Frame, IEMSource, RainViewerSource, _in_conus, get_source,
)

UTC = datetime.timezone.utc


class TestFloorStep:
    def test_floors_to_5_minute_boundary(self):
        dt = datetime.datetime(2024, 1, 1, 10, 7, 33, 123, tzinfo=UTC)
        floored = _floor_step(dt)
        assert floored == datetime.datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)

    def test_already_on_boundary_unchanged(self):
        dt = datetime.datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC)
        assert _floor_step(dt) == dt

    def test_just_before_next_boundary(self):
        dt = datetime.datetime(2024, 1, 1, 10, 9, 59, tzinfo=UTC)
        assert _floor_step(dt) == datetime.datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)


class TestFrameTimes:
    def test_n_ascending_5_minutes_apart(self):
        end = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        times = frame_times(5, end=end)
        assert len(times) == 5
        assert times[-1] == end
        for a, b in zip(times, times[1:]):
            assert b - a == datetime.timedelta(minutes=5)
        assert times == sorted(times)

    def test_default_end_uses_now(self):
        times = frame_times(3)
        assert len(times) == 3
        assert times == sorted(times)
        for a, b in zip(times, times[1:]):
            assert b - a == datetime.timedelta(minutes=5)


class TestInConus:
    def test_kansas_is_conus(self):
        assert _in_conus(38.5, -97.0) is True

    def test_london_is_not_conus(self):
        assert _in_conus(51.5, -0.12) is False

    def test_honolulu_is_not_conus(self):
        assert _in_conus(21.3, -157.8) is False


class TestGetSource:
    def test_conus_uses_iem(self):
        src = get_source(38.5, -97.0, 5)
        assert isinstance(src, IEMSource)
        assert src.n_frames == 5

    def test_non_conus_falls_back_to_iem_on_rainviewer_failure(self):
        original = rv.fetch_index

        def boom(*a, **k):
            raise RuntimeError("network disabled in tests")

        rv.fetch_index = boom
        try:
            src = get_source(51.5, -0.12, 4)
        finally:
            rv.fetch_index = original
        assert isinstance(src, IEMSource)

    def test_non_conus_uses_rainviewer_when_available(self):
        original = rv.fetch_index

        def stub(*a, **k):
            return {
                "host": "https://h",
                "radar": {
                    "past": [{"time": 1000, "path": "/p1"},
                             {"time": 2000, "path": "/p2"}],
                    "nowcast": [{"time": 3000, "path": "/f1"}],
                },
            }

        rv.fetch_index = stub
        try:
            src = get_source(51.5, -0.12, 4)
        finally:
            rv.fetch_index = original
        assert isinstance(src, RainViewerSource)


class TestRainViewerSource:
    def _stub(self, index):
        original = rv.fetch_index
        rv.fetch_index = lambda *a, **k: index
        return original

    def test_frames_sorted_and_flagged(self):
        original = self._stub({
            "host": "https://h",
            "radar": {
                "past": [{"time": 2000, "path": "/p2"},
                         {"time": 1000, "path": "/p1"}],
                "nowcast": [{"time": 3000, "path": "/f1"}],
            },
        })
        try:
            src = RainViewerSource()
            frames = src.current_frames()
        finally:
            rv.fetch_index = original

        assert len(frames) == 3
        times = [f.time for f in frames]
        assert times == sorted(times)
        assert frames[0].token == "/p1"
        assert frames[0].future is False
        assert frames[1].token == "/p2"
        assert frames[1].future is False
        assert frames[2].token == "/f1"
        assert frames[2].future is True


class TestIEMSource:
    def test_current_frames_oldest_first_all_past(self):
        src = IEMSource(4)
        frames = src.current_frames()
        assert len(frames) == 4
        assert all(f.future is False for f in frames)
        assert all(isinstance(f, Frame) for f in frames)
        times = [f.time for f in frames]
        assert times == sorted(times)
