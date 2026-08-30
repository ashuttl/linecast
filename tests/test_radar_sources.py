"""Tests for radar source selection and frame bookkeeping.

No network access: tile sources are only exercised with fetch_index
monkeypatched to a stub, never the real HTTP call.
"""

import datetime
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_sources as sources
from linecast import _radar_tiles as tiles
from linecast._radar_source import _floor_step, frame_times
from linecast._radar_sources import (
    DEFAULT_THEME, Frame, IEMSource, LibreWXRSource, RainViewerSource,
    RV_THEMES, THEMES, _in_conus, get_source, has_radar, theme_id,
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


class TestHasRadar:
    def test_radar_regions(self):
        assert has_radar(40.4, -80.0)    # Pittsburgh
        assert has_radar(55.9, -4.3)     # Glasgow
        assert has_radar(35.7, 139.7)    # Tokyo
        assert has_radar(14.6, 121.0)    # Manila

    def test_model_regions(self):
        assert not has_radar(-37.8, 175.3)  # Hamilton, NZ
        assert not has_radar(-33.9, 151.2)  # Sydney
        assert not has_radar(-23.5, -46.6)  # São Paulo


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

    def test_default_theme_is_terminal(self):
        assert THEMES[DEFAULT_THEME] == "terminal"

    def test_local_themes_listed_before_server_themes(self):
        kinds = [isinstance(v, str) for v in THEMES.values()]
        assert kinds == sorted(kinds, reverse=True) and True in kinds \
            and False in kinds


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

    def test_theme_survives_the_fall_back_to_rainviewer(self):
        original = self._patch({"rv": _INDEX})
        try:
            src = get_source(51.5, -0.12, 5, theme="dusk")
        finally:
            tiles.fetch_index = original
        assert isinstance(src, RainViewerSource)
        assert src.theme == "dusk"
        assert src.palette is not None
        assert src.provider.options == "0_1"  # exact colours to decode

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

    def _counting_stub(self, indexes, gate=None):
        """fetch_index stub returning indexes[n] on the n-th call; calls
        after the first wait on `gate` (a refresh held in flight)."""
        calls = []

        def stub(*a, **k):
            calls.append(1)
            if gate is not None and len(calls) > 1:
                gate.wait(5)
            result = indexes[min(len(calls), len(indexes)) - 1]
            if isinstance(result, Exception):
                raise result
            return result
        original = tiles.fetch_index
        tiles.fetch_index = stub
        return original, calls

    def _wait_idle(self, src):
        for _ in range(500):
            if not src._refreshing:
                return
            time.sleep(0.01)
        raise AssertionError("background refresh never finished")

    def test_fresh_list_served_without_refetch(self):
        original, calls = self._counting_stub([_INDEX])
        try:
            src = LibreWXRSource()
            first = src.current_frames()
            assert src.current_frames() is first
            assert src.satellite_frames() == []
        finally:
            tiles.fetch_index = original
        assert len(calls) == 1

    def test_stale_list_served_while_refresh_runs_in_background(self):
        newer = {"host": "https://h", "radar": {
            "past": _INDEX["radar"]["past"] + [{"time": 2500, "path": "/p3"}],
            "nowcast": _INDEX["radar"]["nowcast"]}}
        gate, landed = threading.Event(), threading.Event()
        original, calls = self._counting_stub([_INDEX, newer], gate)
        sources.on_index_refresh = landed.set
        try:
            src = LibreWXRSource()
            first = src.current_frames()
            src._checked_at = 0  # a minute passes
            assert src.current_frames() is first  # no wait on the network
            assert src._refreshing  # ...but it is running
            gate.set()
            assert landed.wait(5)
            self._wait_idle(src)
            frames = src.current_frames()
        finally:
            tiles.fetch_index = original
            sources.on_index_refresh = None
        assert len(calls) == 2
        assert [f.token for f in frames] == ["/p1", "/p2", "/p3", "/f1"]

    def test_failed_refresh_keeps_frames_and_backs_off(self):
        original, calls = self._counting_stub([_INDEX, OSError("offline")])
        try:
            src = LibreWXRSource()
            first = src.current_frames()
            src._checked_at = 0
            assert src.current_frames() is first
            self._wait_idle(src)
            assert src.current_frames() is first  # not retried every tick
        finally:
            tiles.fetch_index = original
        assert len(calls) == 2
        assert time.time() - src._checked_at < 5

    def test_with_theme_reuses_the_index(self):
        original, calls = self._counting_stub([_INDEX])
        try:
            src = LibreWXRSource("terminal")
            dusk = src.with_theme("dusk")
            server = src.with_theme(7)
        finally:
            tiles.fetch_index = original
        assert len(calls) == 1
        assert dusk.current_frames() is src.current_frames()
        assert dusk.host == src.host
        assert (dusk.theme, dusk.provider.color) == ("dusk", tiles.RAW_COLOR)
        assert (server.theme, server.provider.color) == (7, 7)
        assert server.palette is None and server.smooth is False

    def test_advertised_themes_match_what_each_source_can_draw(self):
        original = self._stub(_INDEX)
        try:
            assert getattr(LibreWXRSource(), "themes", None) is THEMES
            assert getattr(RainViewerSource(), "themes", None) is RV_THEMES
        finally:
            tiles.fetch_index = original
        assert getattr(IEMSource(4), "themes", None) is None
        # RainViewer draws the local palettes plus its one server scheme
        assert set(RV_THEMES) == {n for n, v in THEMES.items()
                                  if isinstance(v, str)} | {"universal-blue"}

    def test_rainviewer_with_theme_reuses_the_index(self):
        calls = []
        original = tiles.fetch_index
        tiles.fetch_index = lambda *a, **k: calls.append(1) or _INDEX
        try:
            src = RainViewerSource("terminal")
            blue = src.with_theme(2)
        finally:
            tiles.fetch_index = original
        assert len(calls) == 1
        assert blue.current_frames() is src.current_frames()
        assert src.transform is not None and src.smooth is True
        assert blue.transform is None and blue.smooth is False
        assert blue.provider.options == "1_1"


class TestIEMSource:
    def test_current_frames_oldest_first_all_past(self):
        src = IEMSource(4)
        frames = src.current_frames()
        assert len(frames) == 4
        assert all(f.future is False for f in frames)
        assert all(isinstance(f, Frame) for f in frames)
        times = [f.time for f in frames]
        assert times == sorted(times)
