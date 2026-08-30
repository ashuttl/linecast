"""RadarApp and the theme picker: the live radar's keys and state, with
no terminal and no network behind them."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_frames as rf
from linecast import _radar_live
from linecast._radar_live import RadarApp
from linecast._radar_ui import ThemePicker


class FakeSource:
    """Enough of a RadarSource for the keys: a theme, a palette list, and
    the kind get_source would know it by."""

    def __init__(self, themes=None, theme=None, kind="lwxr"):
        self.themes = themes
        self.theme = theme
        self.kind = kind
        self.swapped = []

    def with_theme(self, theme):
        self.swapped.append(theme)
        return FakeSource(self.themes, theme, self.kind)


THEMES = {"Classic": "classic", "Rainbow": "rainbow", "Mono": "mono"}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(_radar_live, "get_terminal_size", lambda: (80, 26))
    monkeypatch.setattr(_radar_live, "_sat_timeline", lambda: [])
    monkeypatch.setattr(rf, "_source", FakeSource(THEMES, "classic"))
    monkeypatch.setattr(rf, "_buffering", False)
    return RadarApp(None, 43.7, -70.3, "Westbrook", 10.0, frozenset(),
                    "radar", "classic")


class TestActions:
    def test_c_and_w_toggle_the_condition_layers(self, app):
        assert app.on_action('c') is True
        assert app.layers == {"temp"}
        assert app.on_action('w') is True
        assert app.layers == {"temp", "wind"}
        assert app.on_action('c') is True
        assert app.layers == {"wind"}

    def test_s_cycles_the_layer_only_with_a_satellite_timeline(
            self, app, monkeypatch):
        assert app.on_action('s') is False
        assert app.layer == "radar"
        monkeypatch.setattr(_radar_live, "_sat_timeline", lambda: ["hourly"])
        assert app.on_action('s') is True
        assert app.layer == "sat"
        assert app.on_action('s') is True
        assert app.layer == "radar"

    def test_zoom_keys_clamp_and_stop_repainting_at_the_limit(self, app):
        assert app.on_action('-') is True
        assert app.zoom == 15.0
        while app.on_action('-'):
            pass
        assert app.zoom == 60.0
        assert app.on_action('-') is False
        while app.on_action('+'):
            pass
        assert app.zoom == 1.0
        assert app.on_action('+') is False

    def test_other_keys_pass_through(self, app):
        assert app.on_action('x') is False


class TestThemePicker:
    def test_t_opens_only_when_the_source_has_themes(self, app, monkeypatch):
        monkeypatch.setattr(rf, "_source", FakeSource(None))
        assert app.intercept('key:t') is False
        assert not app.picker.is_open
        monkeypatch.setattr(rf, "_source", FakeSource(THEMES, "rainbow"))
        assert app.intercept('key:t') is True
        assert app.picker.is_open and app.picker.sel == 1

    def test_the_highlight_wraps_both_ways(self, app):
        app.intercept('key:t')
        assert app.picker.sel == 0
        assert app.intercept('fwd') is True
        assert app.picker.sel == 2
        assert app.intercept('back') is True
        assert app.picker.sel == 0
        app.intercept('back')
        app.intercept('back')
        app.intercept('back')
        assert app.picker.sel == 0

    def test_enter_applies_a_different_theme_and_closes(self, app):
        old = rf._source
        app.intercept('key:t')
        app.intercept('back')
        assert app.intercept('key:enter') is True
        assert not app.picker.is_open
        assert old.swapped == ["rainbow"]
        assert rf._source.theme == "rainbow"
        assert app.theme == "rainbow"

    def test_enter_on_the_current_theme_fetches_nothing(self, app):
        old = rf._source
        app.intercept('key:t')
        assert app.intercept('key:enter') is True
        assert not app.picker.is_open
        assert old.swapped == []
        assert rf._source is old
        assert app.theme == "classic"

    @pytest.mark.parametrize("action", ['escape', 'key:t', 'quit'])
    def test_escape_t_and_quit_close_it(self, app, action):
        app.intercept('key:t')
        assert app.intercept(action) is True
        assert not app.picker.is_open

    def test_every_key_is_consumed_while_open(self, app):
        app.intercept('key:t')
        assert app.intercept('key:c') is True
        assert app.intercept('space') is True
        assert app.picker.is_open

    def test_a_source_that_lost_its_themes_closes_it(self, app, monkeypatch):
        app.intercept('key:t')
        monkeypatch.setattr(rf, "_source", FakeSource(None))
        assert app.intercept('fwd') is True
        assert not app.picker.is_open

    def test_the_picker_alone_reports_a_choice_once(self):
        picker = ThemePicker()
        assert picker.handle('fwd', THEMES, "classic") is False
        picker.handle('key:t', THEMES, "mono")
        assert picker.sel == 2
        picker.handle('fwd', THEMES, "mono")
        picker.handle('key:enter', THEMES, "mono")
        assert picker.take_chosen() == "rainbow"
        assert picker.take_chosen() is None


class TestDrag:
    def test_a_preview_repaints_only_when_the_offset_changes(self, app):
        assert app.on_drag(3, 1, False) is True
        assert app.pan_preview == (3, 1)
        assert app.on_drag(3, 1, False) is False
        assert app.on_drag(0, 0, True) is True   # release clears the preview
        assert app.pan_preview == (0, 0)
        assert app.on_drag(0, 0, True) is False  # a plain click

    def test_a_commit_moves_the_centre_against_the_drag(self, app):
        lat0, lon0 = app.lat, app.lon
        assert app.on_drag(8, -2, True) is True
        assert app.lat < lat0 and app.lon < lon0
        assert app.pan_preview == (0, 0)
        assert app.home == (43.7, -70.3)  # the marker stays put

    def test_the_longitude_wraps(self, app):
        app.lon = 179.9
        app.on_drag(-40, 0, True)
        assert -180.0 <= app.lon < 0.0
        app.lon = -179.9
        app.on_drag(40, 0, True)
        assert 0.0 < app.lon <= 180.0

    def test_leaving_conus_repicks_a_fallback_source(
            self, app, monkeypatch):
        picks = []
        monkeypatch.setattr(_radar_live, "get_source",
                            lambda *a: picks.append(a) or FakeSource(None))
        monkeypatch.setattr(rf, "_source", FakeSource(None, kind="iem"))
        monkeypatch.setattr(_radar_live, "_in_conus",
                            lambda lat, lon: lon < -60)
        app.region = True
        app.on_drag(-40, 0, True)   # eastwards, out over the Atlantic
        assert app.region is False
        assert len(picks) == 1
        assert picks[0][2:] == (rf.N_FRAMES, "classic")

    def test_librewxr_is_left_alone_across_the_boundary(
            self, app, monkeypatch):
        picks = []
        monkeypatch.setattr(_radar_live, "get_source",
                            lambda *a: picks.append(a))
        monkeypatch.setattr(_radar_live, "_in_conus",
                            lambda lat, lon: lon < -60)
        app.region = True
        app.on_drag(-40, 0, True)
        assert app.region is False
        assert picks == []

    def test_a_themed_rainviewer_is_still_a_fallback_to_retry(
            self, app, monkeypatch):
        picks = []
        monkeypatch.setattr(_radar_live, "get_source",
                            lambda *a: picks.append(a) or FakeSource(None))
        monkeypatch.setattr(rf, "_source", FakeSource({"terminal": "terminal"},
                                                      "terminal", kind="rv"))
        monkeypatch.setattr(_radar_live, "_in_conus",
                            lambda lat, lon: lon < -60)
        app.region = True
        app.on_drag(-40, 0, True)
        assert len(picks) == 1


class TestPlayGate:
    def test_follows_the_buffering_flag(self, app, monkeypatch):
        assert app.play_gate() is True
        monkeypatch.setattr(rf, "_buffering", True)
        assert app.play_gate() is False


class TestRender:
    def test_passes_the_state_through(self, app, monkeypatch):
        seen = {}
        monkeypatch.setattr(_radar_live, "render_radar",
                            lambda *a, **k: seen.update(args=a, **k) or "f")
        app.layers.add("wind")
        app.pan_preview = (2, -1)
        assert app.render(play_frame=3, playing=False,
                          mouse_pos=(4, 5), offset_minutes=0) == "f"
        assert seen["args"] == (43.7, -70.3, "Westbrook", 10.0)
        assert seen["play_frame"] == 3 and seen["playing"] is False
        assert seen["marker"] == (43.7, -70.3)
        assert seen["block"] is False and seen["mouse_pos"] == (4, 5)
        assert seen["pan_offset"] == (2, -1)
        assert seen["layers"] == frozenset({"wind"})
        assert seen["layer"] == "radar"
        assert seen["theme_menu"] is None

    def test_the_theme_menu_rides_along_while_the_picker_is_open(
            self, app, monkeypatch):
        seen = {}
        monkeypatch.setattr(_radar_live, "render_radar",
                            lambda *a, **k: seen.update(k) or "f")
        app.intercept('key:t')
        app.intercept('back')
        app.render()
        assert seen["theme_menu"] == (["Classic", "Rainbow", "Mono"], 1)
        app.intercept('escape')
        app.render()
        assert seen["theme_menu"] is None

    def test_the_loop_gets_the_radar_tuning(self):
        assert RadarApp.interval == _radar_live.FRAME_STEP
        assert RadarApp.mouse is True and RadarApp.auto_play is True
        assert RadarApp.play_interval == 0.2
