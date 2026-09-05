"""MapApp: the live map's state and the hooks that move it.

The terminal is a fixed 100 by 42, the globe canvas is never warm
unless a test says so, render_map only records its keyword arguments,
nothing is prefetched, and no thread or request ever starts.  The
camera's clock is a number the tests turn by hand.
"""

import math
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe, _maps_live, _maps_route, _maps_ui, maps
from linecast._maps_live import Camera, MapApp, ZOOM_EASE
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

    def is_alive(self):
        return False


class FakeTimer(FakeThread):
    def __init__(self, delay, fn, args=()):
        super().__init__(target=fn, args=args)

    def cancel(self):
        pass


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


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
    monkeypatch.setattr(_maps_live, "prefetch_view", lambda *a, **k: None)


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
    app = MapApp(runtime, lat, lon, "Westbrook", zoom, view, sky, "car",
                 origin=origin, dest=dest)
    app.camera.clock = Clock()
    return app


def settle(app, seconds=5.0):
    """Let every motion run out, and read the view."""
    app.camera.clock.advance(seconds)
    return app.camera.view()


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
        assert not app.helping
        assert not app.camera.moving() and not app.camera.dragging()
        assert not app.camera.spinning
        assert app.interval == 3600 and app.mouse is True
        assert FakeThread.started == []

    def test_the_camera_knows_the_maps_size(self):
        app = make()
        assert (app.camera.gw, app.camera.hc) == (GW, HC)
        assert app.camera.zoom_max == maps.max_zoom(GW, HC)

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
        assert [t.target for t in FakeThread.started][-2:] == [app.cloud_tick, app._warm]

    def test_the_hooks_reach_the_loop(self):
        hooks = make().hooks()
        assert set(hooks) == {"on_action", "on_drag", "on_wheel",
                              "intercept", "on_click", "text_mode"}


class TestZoom:
    def test_zoom_eases_to_the_clamped_limits(self):
        app = make(zoom=1.0)
        assert app.zoom_to(0.0)
        assert app.camera.moving()
        assert settle(app)[2] == MIN_ZOOM_DEG
        assert not app.camera.moving()
        assert app.zoom_to(1e9)
        assert settle(app)[2] == MAX_ZOOM_DEG

    def test_the_zoom_moves_in_log_space(self):
        app = make(zoom=1.0)
        app.zoom_to(4.0)
        app.camera.clock.advance(ZOOM_EASE / 2)
        assert app.camera.view()[2] == pytest.approx(2.0)

    def test_a_zoom_that_changes_nothing_says_so(self):
        app = make(zoom=MAX_ZOOM_DEG)
        assert app.zoom_to(MAX_ZOOM_DEG * 2) is False
        assert app.zoom_to(MAX_ZOOM_DEG) is False
        assert not app.camera.moving()

    def test_the_ceiling_opens_up_on_a_narrow_terminal(self, monkeypatch):
        app = make(zoom=MAX_ZOOM_DEG)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (54, 47))
        assert app.zoom_to(1e9)
        assert settle(app)[2] == maps.max_zoom(*maps.map_cells())
        assert app.zoom > MAX_ZOOM_DEG

    def test_an_anchored_zoom_keeps_the_point_under_the_pointer(self):
        app = make(zoom=2.0)
        before = point_under(app, 30, 12)
        assert app.zoom_to(1.0, at=(30, 12))
        app.camera.clock.advance(ZOOM_EASE / 3)
        app.camera.view()
        assert point_under(app, 30, 12) == pytest.approx(before, abs=1e-9)
        settle(app)
        assert app.zoom == 1.0
        assert point_under(app, 30, 12) == pytest.approx(before, abs=1e-9)
        assert (app.lat, app.lon) != (43.68, -70.37)

    def test_a_zoom_about_the_centre_keeps_it(self):
        app = make(zoom=2.0)
        assert app.zoom_to(1.0)
        settle(app)
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_a_zoom_across_the_hand_off_keeps_the_centre(self):
        app = make(zoom=_globe.ZOOM_DEG / 1.2)
        assert app.zoom_to(_globe.ZOOM_DEG * 1.2, at=(30, 12))
        settle(app)
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_an_anchored_zoom_wraps_the_longitude(self):
        app = make(zoom=20.0, lat=0.0, lon=179.9)
        assert app.zoom_to(10.0, at=(2, 20))
        settle(app)
        assert -180.0 <= app.lon <= 180.0

    def test_a_zoom_holds_the_fetches_and_wakes_the_ticker(self, monkeypatch):
        held = []
        monkeypatch.setattr(_maps_live, "_zoom_hold",
                            types.SimpleNamespace(hold=lambda: held.append(1)))
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.zoom_to(2.0)
        assert held == [1]
        assert [t.target for t in FakeThread.started] == [app._tick]

    def test_the_wheel_zooms_in_going_up(self):
        app = make(zoom=1.0)
        assert app.on_wheel(1, 50, 20)
        assert settle(app)[2] == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_wheel(-1, 50, 20)
        assert settle(app)[2] == pytest.approx(1.0)

    def test_a_run_of_taps_compounds_before_the_first_lands(self):
        app = make(zoom=1.0)
        app.on_action('+')
        app.camera.clock.advance(ZOOM_EASE / 4)
        app.on_action('+')
        assert settle(app)[2] == pytest.approx(1.0 / ZOOM_STEP ** 2)


class TestKeys:
    def test_plus_and_minus_step_the_zoom(self):
        app = make(zoom=1.0)
        assert app.on_action('+')
        assert settle(app)[2] == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_action('-')
        assert settle(app)[2] == pytest.approx(1.0)

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
        assert app.on_action('r') is False and not app.camera.spinning
        app.zoom = _globe.ZOOM_DEG
        assert app.on_action('r') is False and not app.camera.spinning
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: h == HC * 4)
        assert app.on_action('r') is False
        assert app.camera.spinning and app.camera.moving()
        assert FakeThread.started[-1].target == app._tick

    def test_the_spin_turns_the_planet_eastward_a_degree_a_second(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG, lon=0.0)
        app.on_action('r')
        app.camera.clock.advance(2.0)
        assert app.camera.view()[1] == pytest.approx(-2.0)

    def test_r_parks_a_spin_already_running(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_action('r')
        assert app.on_action('r') is False
        assert not app.camera.spinning and not app.camera.moving()
        app.on_action('r')
        assert app.camera.spinning

    def test_stop_parks_the_spin(self):
        app = make()
        app.camera.spin(True)
        app.stop()
        assert not app.camera.spinning

    def test_text_mode_is_the_search_field(self):
        app = make()
        assert app.text_mode() is False
        app.search.start()
        assert app.text_mode() is True


class TestDrag:
    def test_the_ground_follows_the_hand(self):
        app = make(zoom=2.0)
        assert app.on_drag(10, 5, False)
        assert app.camera.dragging()
        lon_span = 2.0 * (GW / (HC * 2)) / math.cos(math.radians(43.68))
        assert app.lat == pytest.approx(43.68 + 5 * 2.0 / HC)
        assert app.lon == pytest.approx(-70.37 - 10 * lon_span / GW)
        assert app.on_drag(10, 5, False) is False  # nothing new
        assert app.on_drag(10, 5, True)
        assert not app.camera.dragging() and not app.camera.moving()
        assert app.lat == pytest.approx(43.68 + 5 * 2.0 / HC)

    def test_a_drag_wraps_the_longitude(self):
        app = make(zoom=2.0, lat=0.0, lon=-179.99)
        app.on_drag(60, 0, False)
        assert app.lon > 0

    def test_a_release_without_a_press_is_nothing(self):
        app = make(zoom=2.0)
        assert app.on_drag(0, 0, True) is False
        app.on_drag(3, 0, False)
        assert app.on_drag(0, 0, False) is True
        assert app.on_drag(0, 0, True) is True
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_the_globe_turns_under_the_cursor_the_same_way(self):
        app = make(zoom=60.0, lat=70.0, lon=0.0)
        assert app.on_drag(10, 20, False)
        assert app.lat == 80.0  # clamped
        assert app.lon == pytest.approx(
            -(10 * (60.0 / (HC * 2)) / math.cos(math.radians(70.0))))
        assert app.on_drag(10, 20, False) is False  # nothing moved
        assert app.on_drag(10, 20, True) is True

    def test_a_flick_coasts_and_slows_to_a_stop(self):
        app = make(zoom=2.0)
        clock = app.camera.clock
        app.on_drag(0, 0, False)
        clock.advance(0.05)
        app.on_drag(10, 0, False)
        lon_at_release = app.lon
        assert app.on_drag(10, 0, True)
        assert app.camera.moving()
        assert [t.target for t in FakeThread.started] == [app._tick]
        clock.advance(0.1)
        _lat, lon_soon, _zoom = app.camera.view()
        assert lon_soon < lon_at_release
        clock.advance(3.0)
        _lat, lon_rest, _zoom = app.camera.view()
        assert lon_rest < lon_soon
        assert not app.camera.moving()
        assert app.camera.view()[1] == lon_rest  # at rest for good

    def test_a_slow_release_does_not_coast(self):
        app = make(zoom=2.0)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(10, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(10, 0, True)
        assert not app.camera.moving()

    def test_a_press_stops_a_coast_and_a_flight(self):
        app = make(zoom=2.0)
        app.camera.fly_to(44.0, -71.0, 1.0)
        assert app.camera.moving()
        app.on_drag(1, 0, False)
        assert not app.camera.moving()


class TestFlights:
    def test_a_search_result_is_flown_to_and_prefetched(self, frames, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append((a, k)))
        app = make(zoom=1.0)
        app.search.start()
        app.search.chosen = Result("Portland", "", 43.66, -70.25, "city")
        app.render()
        assert app.camera.moving()
        assert frames[-1]["moving"] is True
        assert app.search.take_chosen() is None
        assert app.routes.dest is None
        assert [t.target for t in FakeThread.started] == [app._tick]
        # the destination is asked for from the descent, not at take-off
        assert asked == []
        duration = app.camera._flight[0].duration
        app.camera.clock.advance(duration * 0.6)
        app.render()
        (lat, lon, zoom, view, gw, hc, lang), kw = asked[0]
        assert (lat, lon, view, gw, hc, lang) == (43.66, -70.25, "terrain", GW, HC, "en")
        assert zoom != 1.0 and kw == {"marker": (43.68, -70.37)}
        settle(app)
        app.render()
        assert len(asked) == 1
        assert (app.lat, app.lon) == (43.66, -70.25)
        assert app.zoom == zoom and frames[-1]["moving"] is False

    def test_a_flight_to_where_you_are_is_nothing(self, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=1.0)
        app.fly_to(Result("Here", "", 43.68, -70.37, "", extent=None))
        assert app.camera.moving()  # the zoom differs, so it flies
        settle(app)
        app.render()
        app.fly_to(Result("Here", "", 43.68, -70.37, "", extent=None))
        assert not app.camera.moving() and len(asked) == 1


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

    def test_the_panel_takes_the_arrows_and_the_map_flies_along(self):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        steps = [{"location": (4.0, 3.0), "distance_m": 11054.0},
                 {"location": (5.0, 3.5), "distance_m": 100.0}]
        app.routes.route = types.SimpleNamespace(steps=steps)
        app.routes.panel = True
        assert app.intercept('back') is True
        assert app.routes.step == 0
        assert app.camera.moving()
        settle(app)
        assert (app.lat, app.lon) == (3.0, 4.0)
        assert app.zoom == pytest.approx(11054.0 * 2.4 / 110540.0)
        assert app.intercept('key:enter') is True
        settle(app)
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
        assert app.camera.moving()
        settle(app)
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
        assert app.render(mouse_pos=(4, 5)) == "frame"
        f = frames[-1]
        assert (f["lat"], f["lon"], f["zoom"]) == (43.68, -70.37, 2.0)
        assert f["name"] == "Westbrook" and f["marker"] == (43.68, -70.37)
        assert f["runtime"] is app.runtime and f["block"] is False
        assert f["moving"] is False and f["mouse_pos"] == (4, 5)
        assert f["view"] == "street" and f["search"] is app.search
        assert f["directions"] is app.routes and f["route"] is None
        assert f["helping"] is False and f["show_labels"] is True
        assert f["sun"] is True and f["clouds"] is True

    def test_a_frame_in_motion_says_so_and_drops_the_pointer(self, frames):
        app = make(zoom=2.0)
        app.on_drag(3, 1, False)
        app.render(mouse_pos=(4, 5))
        assert frames[-1]["moving"] is True and frames[-1]["mouse_pos"] is None
        app.on_drag(3, 1, True)
        app.render(mouse_pos=(4, 5))
        assert frames[-1]["moving"] is False and frames[-1]["mouse_pos"] == (4, 5)

    def test_a_frame_advances_the_motion(self, frames):
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.camera.clock.advance(ZOOM_EASE + 0.01)
        app.render()
        assert frames[-1]["zoom"] == 2.0 and frames[-1]["moving"] is False

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


class TestCamera:
    """The camera on its own, at a fixed 100 by 40."""

    def _camera(self, lat=43.68, lon=-70.37, zoom=2.0):
        cam = Camera(lat, lon, zoom, clock=Clock())
        cam.gw, cam.hc = GW, HC
        return cam

    def test_a_flight_ends_where_it_was_sent(self):
        cam = self._camera()
        assert cam.fly_to(44.0, -71.0, 0.5)
        assert cam.moving()
        cam.clock.advance(0.1)
        lat, lon, zoom = cam.view()
        assert lat != 43.68 or zoom != 2.0
        cam.clock.advance(5.0)
        assert cam.view() == (44.0, -71.0, 0.5)
        assert not cam.moving()

    def test_a_flight_keeps_inside_the_zoom_limits(self):
        cam = self._camera(zoom=0.05)
        cam.zoom_max = 10.0
        cam.fly_to(35.7, 139.7, 0.05)
        zooms = []
        for _ in range(40):
            cam.clock.advance(0.1)
            zooms.append(cam.view()[2])
        assert max(zooms) == 10.0

    def test_a_jump_is_immediate_and_clamped(self):
        cam = self._camera()
        cam.zoom_to(1.0)
        cam.jump_to(89.0, 200.0, 1e9)
        assert not cam.moving()
        assert cam.view() == (80.0, -160.0, cam.zoom_max)

    def test_a_zoom_retargets_from_where_it_is(self):
        cam = self._camera(zoom=1.0)
        cam.zoom_to(4.0)
        cam.clock.advance(ZOOM_EASE / 2)
        assert cam.view()[2] == pytest.approx(2.0)
        cam.zoom_by(0.5)          # 4.0 → 2.0: back from mid-way
        cam.clock.advance(ZOOM_EASE)
        assert cam.view()[2] == pytest.approx(2.0)

    def test_a_coast_stops_at_the_polar_limit(self):
        cam = self._camera(lat=79.0, zoom=10.0)
        cam.drag(0, 0)
        cam.clock.advance(0.05)
        cam.drag(0, 40)
        cam.release()
        cam.clock.advance(3.0)
        assert cam.view()[0] == 80.0
        assert not cam.moving()

    def test_the_spin_waits_while_a_drag_is_in_hand(self):
        cam = self._camera(lon=0.0, zoom=60.0)
        cam.spin(True)
        cam.drag(0, 0)
        cam.clock.advance(1.0)
        assert cam.view()[1] == 0.0
        cam.release()
        cam.clock.advance(1.0)
        assert cam.view()[1] == pytest.approx(-1.0)


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
