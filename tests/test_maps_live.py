"""MapApp: the live map's state and the hooks that move it.

The terminal is a fixed 100 by 42, the globe canvas is never warm
unless a test says so, render_map only records its keyword arguments,
and no thread or request ever starts.
"""

import math
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe, _maps_live, _maps_route, _maps_ui, maps
from linecast._maps_live import MapApp
from linecast._maps_search import Result
from linecast._radar_render import bbox_for
from linecast.maps import MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP

COLS, ROWS = 100, 42
GW, HC = COLS, ROWS - 2


class FakeThread:
    started = []

    def __init__(self, target=None, args=(), daemon=False):
        self.target, self.args = target, tuple(args)
        FakeThread.started.append(self)

    def start(self):
        pass


class FakeTimer(FakeThread):
    def __init__(self, delay, fn, args=()):
        super().__init__(target=fn, args=args)

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    FakeThread.started = []
    fake = types.SimpleNamespace(Thread=FakeThread, Timer=FakeTimer,
                                 Lock=threading.Lock)
    monkeypatch.setattr(_maps_live, "threading", fake)
    monkeypatch.setattr(_maps_ui, "threading", fake)
    monkeypatch.setattr(maps, "get_terminal_size", lambda: (COLS, ROWS))
    monkeypatch.setattr(_globe, "warm", lambda zoom, h: False)
    monkeypatch.setattr(_maps_live, "_zoom_hold",
                        types.SimpleNamespace(hold=lambda: None))


@pytest.fixture
def frames(monkeypatch):
    seen = []

    def fake_render_map(lat, lon, name, zoom, **kw):
        seen.append(dict(kw, lat=lat, lon=lon, name=name, zoom=zoom))
        return "frame"

    monkeypatch.setattr(_maps_live, "render_map", fake_render_map)
    return seen


def make(zoom=1.0, view="terrain", sky=False, lat=43.68, lon=-70.37,
         origin=None, dest=None):
    runtime = types.SimpleNamespace(lang="en", live=True)
    return MapApp(runtime, lat, lon, "Westbrook", zoom, view, sky, "car",
                  origin=origin, dest=dest)


def point_under(app, col, row):
    """The geographic point under a 1-based terminal cell, by the
    flat map's own projection."""
    fx, fy = (col - 1 + 0.5) / GW, (row - 2 + 0.5) / HC
    lon_span = app.zoom * (GW / (HC * 2)) / math.cos(math.radians(app.lat))
    return (app.lat + app.zoom * (0.5 - fy), app.lon + lon_span * (fx - 0.5))


class TestConstruction:
    def test_the_app_starts_where_main_left_it(self):
        app = make(zoom=2.0, view="street", sky=True)
        assert (app.lat, app.lon) == app.home == (43.68, -70.37)
        assert app.zoom == 2.0 and app.view == "street"
        assert app.sun and app.clouds and app.show_labels
        assert not app.helping and app.pan_preview == (0, 0)
        assert app.drag_base is None and not app.drag_sync
        assert app.spinning == 0 and app.spin_seq == 0
        assert app.interval == 3600 and app.mouse is True
        assert FakeThread.started == []

    def test_endpoints_seed_the_routes_without_a_request(self):
        origin = Result("A", "", 1.0, 2.0, "city")
        dest = Result("B", "", 3.0, 4.0, "city")
        app = make(origin=origin, dest=dest)
        assert app.routes.origin == (1.0, 2.0, "A")
        assert app.routes.dest == (3.0, 4.0, "B")
        assert app.routes.status == "" and FakeThread.started == []

    def test_run_requests_the_route_and_starts_the_sky_clock(self, monkeypatch):
        monkeypatch.setattr(_maps_live.LiveApp, "run", lambda self: None)
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        app.run()
        assert app.routes.status == "pending"
        assert [t.target for t in FakeThread.started][-1] == app.cloud_tick

    def test_the_hooks_reach_the_loop(self):
        hooks = make().hooks()
        assert set(hooks) == {"on_action", "on_drag", "on_wheel",
                              "intercept", "on_click", "text_mode"}


class TestZoom:
    def test_zoom_clamps_to_the_limits(self):
        app = make(zoom=1.0)
        assert app.zoom_to(0.0)
        assert app.zoom == MIN_ZOOM_DEG
        assert app.zoom_to(1e9)
        assert app.zoom == MAX_ZOOM_DEG

    def test_a_zoom_that_changes_nothing_says_so(self):
        app = make(zoom=MAX_ZOOM_DEG)
        assert app.zoom_to(MAX_ZOOM_DEG * 2) is False
        assert app.zoom_to(MAX_ZOOM_DEG) is False

    def test_an_anchored_zoom_keeps_the_point_under_the_pointer(self):
        app = make(zoom=2.0)
        before = point_under(app, 30, 12)
        assert app.zoom_to(1.0, at=(30, 12))
        after = point_under(app, 30, 12)
        assert after == pytest.approx(before, abs=1e-9)
        assert (app.lat, app.lon) != (43.68, -70.37)

    def test_a_zoom_about_the_centre_keeps_it(self):
        app = make(zoom=2.0)
        assert app.zoom_to(1.0)
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_a_zoom_across_the_hand_off_keeps_the_centre(self):
        app = make(zoom=_globe.ZOOM_DEG / 1.2)
        assert app.zoom_to(_globe.ZOOM_DEG * 1.2, at=(30, 12))
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_an_anchored_zoom_wraps_the_longitude(self):
        app = make(zoom=20.0, lat=0.0, lon=179.9)
        assert app.zoom_to(10.0, at=(2, 20))
        assert -180.0 <= app.lon <= 180.0

    def test_a_zoom_holds_the_fetches(self, monkeypatch):
        held = []
        monkeypatch.setattr(_maps_live, "_zoom_hold",
                            types.SimpleNamespace(hold=lambda: held.append(1)))
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.zoom_to(2.0)
        assert held == [1]

    def test_the_wheel_zooms_in_going_up(self):
        app = make(zoom=1.0)
        assert app.on_wheel(1, 50, 20)
        assert app.zoom == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_wheel(-1, 50, 20)
        assert app.zoom == pytest.approx(1.0)


class TestKeys:
    def test_plus_and_minus_step_the_zoom(self):
        app = make(zoom=1.0)
        assert app.on_action('+')
        assert app.zoom == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_action('-')
        assert app.zoom == pytest.approx(1.0)

    def test_v_cycles_the_view(self):
        app = make(view="street")
        assert app.on_action('v') and app.view == "terrain"
        assert app.on_action('v') and app.view == "street"

    def test_the_toggles(self):
        app = make()
        assert app.on_action('l') and app.show_labels is False
        assert app.on_action('s') and app.sun is True
        assert app.on_action('c') and app.clouds is True

    def test_an_unknown_key_does_nothing(self):
        assert make().on_action('x') is False

    def test_r_spins_only_a_warm_globe(self, monkeypatch):
        app = make(zoom=1.0)
        assert app.on_action('r') is False and app.spinning == 0
        app.zoom = _globe.ZOOM_DEG
        assert app.on_action('r') is False and app.spinning == 0
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: h == HC * 4)
        assert app.on_action('r') is False
        assert app.spinning == app.spin_seq == 1
        assert FakeThread.started[-1].target == app.spin
        assert FakeThread.started[-1].args == (1,)

    def test_r_parks_a_spin_already_running(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_action('r')
        assert app.on_action('r') is False
        assert app.spinning == 0 and app.spin_seq == 1
        app.on_action('r')
        assert app.spinning == app.spin_seq == 2

    def test_stop_parks_the_spin(self):
        app = make()
        app.spinning = 3
        app.stop()
        assert app.spinning == 0

    def test_text_mode_is_the_search_field(self):
        app = make()
        assert app.text_mode() is False
        app.search.start()
        assert app.text_mode() is True


class TestDrag:
    def test_a_flat_drag_previews_then_commits(self):
        app = make(zoom=2.0)
        assert app.on_drag(10, 5, False)
        assert app.pan_preview == (10, 5)
        assert app.on_drag(10, 5, False) is False  # nothing new
        assert app.on_drag(10, 5, True)
        assert app.pan_preview == (0, 0)
        lon_span = 2.0 * (GW / (HC * 2)) / math.cos(math.radians(43.68))
        assert app.lat == pytest.approx(43.68 + 5 * 2.0 / HC)
        assert app.lon == pytest.approx(-70.37 - 10 * lon_span / GW)

    def test_a_commit_wraps_the_longitude(self):
        app = make(zoom=2.0, lat=0.0, lon=-179.99)
        app.on_drag(60, 0, True)
        assert app.lon > 0

    def test_a_release_with_no_delta_repaints_only_after_a_preview(self):
        app = make(zoom=2.0)
        assert app.on_drag(0, 0, True) is False
        app.on_drag(3, 0, False)
        assert app.on_drag(0, 0, True) is True
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_a_cold_globe_pans_like_the_flat_map(self):
        app = make(zoom=_globe.ZOOM_DEG)
        assert app.on_drag(4, 0, False)
        assert app.pan_preview == (4, 0) and app.drag_base is None

    def test_a_warm_globe_rotates_under_the_cursor(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=60.0, lat=70.0, lon=0.0)
        assert app.on_drag(0, 0, True) is False  # a click, not a drag
        assert app.on_drag(10, 20, False)
        assert app.drag_base == (70.0, 0.0)
        assert app.drag_sync is True
        assert app.lat == 80.0  # clamped
        assert app.lon == pytest.approx(
            -(10 * (60.0 / (HC * 2)) / math.cos(math.radians(70.0))))
        assert app.on_drag(10, 20, False) is False  # nothing moved
        assert app.on_drag(10, 20, True) is True
        assert app.drag_base is None


class TestIntercept:
    def test_the_search_panel_eats_every_key(self):
        app = make()
        app.search.start()
        assert app.intercept('key:?') is True
        assert app.helping is False
        assert app.intercept('char:a') is True
        assert app.search.query == "a"

    def test_help_toggles_and_any_key_closes_it(self):
        app = make()
        assert app.intercept('key:?') is True and app.helping
        assert app.intercept('key:?') is True and not app.helping
        app.intercept('key:?')
        assert app.intercept('escape') is True and not app.helping
        app.intercept('key:?')
        assert app.intercept('key:/') is True
        assert not app.helping and app.search.open

    def test_slash_opens_search_and_o_the_origin(self):
        app = make()
        assert app.intercept('key:/') is True
        assert app.search.open and app.search.purpose == "go"
        app.search.close()
        assert app.intercept('open') is True
        assert app.search.purpose == "origin"

    def test_d_opens_the_panel_and_asks_for_a_destination(self):
        app = make()
        assert app.intercept('key:d') is True
        assert app.routes.panel and app.search.purpose == "route"

    def test_the_panel_takes_the_arrows(self):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        steps = [{"location": (4.0, 3.0), "distance_m": 11054.0},
                 {"location": (5.0, 3.5), "distance_m": 100.0}]
        app.routes.route = types.SimpleNamespace(steps=steps)
        app.routes.panel = True
        assert app.intercept('back') is True
        assert app.routes.step == 0
        assert (app.lat, app.lon) == (3.0, 4.0)
        assert app.zoom == pytest.approx(11054.0 * 2.4 / 110540.0)
        assert app.intercept('key:enter') is True
        assert app.routes.step == 1 and (app.lat, app.lon) == (3.5, 5.0)
        assert app.zoom == 0.004  # the floor of a short step
        assert app.intercept('fwd') is True and app.routes.step == 0
        assert app.intercept('key:d') is True
        assert app.search.open and app.search.purpose == "route"
        app.search.close()
        assert app.intercept('escape') is True and not app.routes.panel

    def test_p_cycles_the_profile(self):
        app = make()
        assert app.intercept('key:p') is True
        assert app.routes.profile == _maps_route.PROFILES[1]

    def test_reset_clears_the_routes_and_lets_the_loop_recentre(self):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        app.routes.panel = True
        assert app.intercept('reset') is False
        assert app.routes.dest is None and not app.routes.panel

    def test_anything_else_passes_through(self):
        assert make().intercept('key:x') is False


class TestClick:
    def make_panel(self):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        app.routes.route = types.SimpleNamespace(
            steps=[{"location": (4.0, 3.0), "distance_m": 500.0}])
        app.routes.panel = True
        app.routes.panel_rows = (30, {3: 'from', 4: 'to', 5: 'mode',
                                      8: ('step', 0)})
        return app

    def test_the_field_rows_act(self):
        app = self.make_panel()
        assert app.on_click(5, 3) is True
        assert app.search.purpose == "origin"
        app.search.close()
        assert app.on_click(5, 4) is True
        assert app.search.purpose == "route"
        app.search.close()
        assert app.on_click(5, 5) is True
        assert app.routes.profile == _maps_route.PROFILES[1]

    def test_a_step_row_takes_the_focus_and_flies(self):
        app = self.make_panel()
        assert app.on_click(5, 8) is True
        assert app.routes.step == 0
        assert (app.lat, app.lon) == (3.0, 4.0)

    def test_clicks_elsewhere_are_nothing(self):
        app = self.make_panel()
        assert app.on_click(5, 20) is False
        assert app.on_click(31, 3) is False  # past the panel's width
        app.search.start()
        assert app.on_click(5, 3) is False
        app.search.close()
        app.routes.panel = False
        assert app.on_click(5, 3) is False


class TestRender:
    def test_the_state_reaches_render_map(self, frames):
        app = make(zoom=2.0, view="street", sky=True)
        app.pan_preview = (3, 1)
        assert app.render(mouse_pos=(4, 5)) == "frame"
        f = frames[-1]
        assert (f["lat"], f["lon"], f["zoom"]) == (43.68, -70.37, 2.0)
        assert f["name"] == "Westbrook" and f["marker"] == (43.68, -70.37)
        assert f["runtime"] is app.runtime and f["block"] is False
        assert f["pan_offset"] == (3, 1) and f["mouse_pos"] == (4, 5)
        assert f["view"] == "street" and f["search"] is app.search
        assert f["directions"] is app.routes and f["route"] is None
        assert f["helping"] is False and f["show_labels"] is True
        assert f["sun"] is True and f["clouds"] is True

    def test_a_globe_drag_renders_blocking_once(self, frames):
        app = make(zoom=_globe.ZOOM_DEG)
        app.drag_sync = True
        app.render()
        assert frames[-1]["block"] is True and app.drag_sync is False
        app.render()
        assert frames[-1]["block"] is False

    def test_a_flat_drag_sync_never_blocks(self, frames):
        app = make(zoom=1.0)
        app.drag_sync = True
        app.render()
        assert frames[-1]["block"] is False and app.drag_sync is False

    def test_a_parked_search_result_is_applied(self, frames):
        app = make(zoom=1.0)
        app.search.start()
        app.search.chosen = Result("Portland", "", 43.66, -70.25, "city")
        app.render()
        assert (app.lat, app.lon) == (43.66, -70.25)
        assert app.zoom != 1.0
        assert app.search.take_chosen() is None
        assert app.routes.dest is None

    def test_a_route_result_selects_and_requests(self, frames):
        app = make()
        app.search.start("route")
        app.search.chosen = Result("B", "", 3.0, 4.0, "city")
        app.render()
        assert app.routes.dest == (3.0, 4.0, "B")
        assert app.routes.status == "pending"

    def test_an_origin_result_requests_only_with_a_destination(self, frames):
        app = make()
        app.search.start("origin")
        app.search.chosen = Result("A", "", 1.0, 2.0, "city")
        app.render()
        assert app.routes.origin == (1.0, 2.0, "A")
        assert app.routes.status == ""
        app.routes.select(3.0, 4.0, "B")
        app.search.chosen = Result("A2", "", 1.5, 2.5, "city")
        app.render()
        assert app.routes.status == "pending"


class TestMapCells:
    def test_the_map_has_a_floor(self, monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (10, 5))
        assert maps.map_cells() == (20, 8)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (COLS, ROWS))
        assert maps.map_cells() == (GW, HC)

    def test_search_uses_the_effective_zoom_of_the_view(self, monkeypatch):
        app = make(zoom=1.0)
        seen = {}

        def handle(action, lat, lon, z, lang="en"):
            seen.update(lat=lat, lon=lon, z=z, lang=lang)
            return True

        app.search.open = True
        monkeypatch.setattr(app.search, "handle", handle)
        assert app.intercept('char:a') is True
        bbox = bbox_for(43.68, -70.37, 1.0, GW, HC)
        from linecast._maps_style import z_eff
        assert seen == dict(lat=43.68, lon=-70.37, z=int(z_eff(bbox, HC)),
                            lang="en")


class TestStartupPrune:
    """Maps sweeps its tile cache before the session adds to it."""

    def _argv(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["linecast-maps", *args])

    def test_the_sweep_runs_before_anything_is_fetched(self, monkeypatch):
        from linecast import _maps_tile_cache

        calls = []

        class Bail(Exception):
            pass

        def bail(*a, **k):
            calls.append("resolve")
            raise Bail

        self._argv(monkeypatch)
        monkeypatch.setattr(_maps_tile_cache, "prune_maps_cache",
                            lambda *a, **k: calls.append("prune"))
        monkeypatch.setattr(_maps_live, "resolve_location", bail)

        with pytest.raises(Bail):
            _maps_live.main()

        assert calls == ["prune", "resolve"]

    def test_search_adds_no_tiles_so_it_does_not_wait(self, monkeypatch):
        from linecast import _maps_tile_cache, _weather_sources

        calls = []
        self._argv(monkeypatch, "--search", "leith")
        monkeypatch.setattr(_maps_tile_cache, "prune_maps_cache",
                            lambda *a, **k: calls.append("prune"))
        monkeypatch.setattr(_weather_sources, "_search_locations",
                            lambda *a, **k: calls.append("search"))

        _maps_live.main()

        assert calls == ["search"]
