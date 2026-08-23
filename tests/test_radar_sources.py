"""Tests for radar source selection and frame bookkeeping.

No network access: tile sources are only exercised with fetch_index
monkeypatched to a stub, never the real HTTP call.
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_tiles as tiles
from linecast._radar_source import _floor_step, frame_times
from linecast._radar_sources import (
    DEFAULT_THEME, Frame, IEMSource, LibreWXRSource, RainViewerSource, THEMES,
    _in_conus, get_source, theme_id,
)

UTC = datetime.timezone.utc

_INDEX = {
    "host": "https://h",
    "radar": {
        "past": [{"time": 1000, "path": "/p1"},
                 {"time": 2000, "path": "/p2"}],
        "nowcast": [{"time": 3000, "path": "/f1"}],
    },
}


def _stub_index(by_provider):
    """fetch_index stub: provider.name → index dict or Exception to raise."""
    def stub(provider, *a, **k):
        result = by_provider.get(provider.name)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise RuntimeError("network disabled in tests")
        return result
    return stub


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


class TestThemeId:
    def test_names_resolve(self):
        assert theme_id("universal-blue") == 2
        assert theme_id("rainbow") == 7
        assert theme_id("Rainbow ") == 7  # case/space tolerant

    def test_local_palettes_resolve_to_their_name(self):
        assert theme_id("terminal") == "terminal"
        assert theme_id("Ember") == "ember"

    def test_numeric_ids_accepted_when_known(self):
        assert theme_id("7") == 7
        assert theme_id(0) == 0

    def test_unknown_rejected(self):
        assert theme_id("plasma") is None
        assert theme_id("255") is None  # raw scheme reserved for a future pass
        assert theme_id(None) is None

    def test_default_theme_is_dark_sky(self):
        assert THEMES[DEFAULT_THEME] == 8


class TestGetSource:
    def _patch(self, by_provider):
        original = tiles.fetch_index
        tiles.fetch_index = _stub_index(by_provider)
        return original

    def test_librewxr_primary_in_conus(self):
        original = self._patch({"lwxr": _INDEX})
        try:
            src = get_source(38.5, -97.0, 5)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, LibreWXRSource)
        assert src.theme == THEMES[DEFAULT_THEME]

    def test_theme_threads_through_to_provider(self):
        original = self._patch({"lwxr": _INDEX})
        try:
            src = get_source(38.5, -97.0, 5, theme=7)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, LibreWXRSource)
        assert src.theme == 7
        assert src.provider.color == 7

    def test_conus_falls_back_to_iem(self):
        original = self._patch({})
        try:
            src = get_source(38.5, -97.0, 5)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, IEMSource)
        assert src.n_frames == 5

    def test_non_conus_falls_back_to_rainviewer(self):
        original = self._patch({"rv": _INDEX})
        try:
            src = get_source(51.5, -0.12, 4)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, RainViewerSource)

    def test_non_conus_last_resort_is_iem(self):
        original = self._patch({})
        try:
            src = get_source(51.5, -0.12, 4)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, IEMSource)

    def test_conus_skips_rainviewer_leg(self):
        # IEM covers CONUS with deeper history; RainViewer adds nothing there
        original = self._patch({"rv": _INDEX})
        try:
            src = get_source(38.5, -97.0, 5)
        finally:
            tiles.fetch_index = original
        assert isinstance(src, IEMSource)


class TestTileSourceFrames:
    def _stub(self, index):
        original = tiles.fetch_index
        tiles.fetch_index = lambda *a, **k: index
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
            src = LibreWXRSource()
            frames = src.current_frames()
        finally:
            tiles.fetch_index = original

        assert len(frames) == 3
        times = [f.time for f in frames]
        assert times == sorted(times)
        assert frames[0].token == "/p1"
        assert frames[0].future is False
        assert frames[1].token == "/p2"
        assert frames[1].future is False
        assert frames[2].token == "/f1"
        assert frames[2].future is True

    def test_only_librewxr_advertises_themes(self):
        original = self._stub(_INDEX)
        try:
            assert getattr(LibreWXRSource(), "themes", None) is THEMES
            assert getattr(RainViewerSource(), "themes", None) is None
        finally:
            tiles.fetch_index = original
        assert getattr(IEMSource(4), "themes", None) is None


class TestIEMSource:
    def test_current_frames_oldest_first_all_past(self):
        src = IEMSource(4)
        frames = src.current_frames()
        assert len(frames) == 4
        assert all(f.future is False for f in frames)
        assert all(isinstance(f, Frame) for f in frames)
        times = [f.time for f in frames]
        assert times == sorted(times)
