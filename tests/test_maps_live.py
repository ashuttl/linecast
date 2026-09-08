"""Map input moves one camera; data preparation never runs in an input hook.

The fixed terminal, manual clock and queued threads keep these regressions
offline while exercising targets, displayed motion and retained scene choice.
"""

import math
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _globe, _maps_live, _maps_motion, _maps_route, _maps_ui, _theme, maps
from linecast._maps_preview import PreparedMap
from linecast._maps_scene import Scene
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


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = [100.0]
    fake = types.SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(_maps_live, "time", fake)
    monkeypatch.setattr(_maps_motion, "time", fake)
    return now


@pytest.fixture
def frames(monkeypatch):
    seen = []

    def fake_render_map(camera, prepared, name, **kw):
        seen.append(dict(kw, camera=camera, prepared=prepared, name=name,
                         lat=camera.lat, lon=camera.lon, zoom=camera.zoom))
        return "frame"

    monkeypatch.setattr(_maps_live, "render_map", fake_render_map)
    return seen


def make(zoom=1.0, view="terrain", sky=False, lat=43.68, lon=-70.37,
         origin=None, dest=None):
    runtime = types.SimpleNamespace(lang="en", live=True)
    return MapApp(runtime, lat, lon, "Westbrook", zoom, view, sky, "car",
                  origin=origin, dest=dest)


def point_under(camera, col, row):
    """Geography at the centre of a 1-based terminal cell."""
    return camera.unproject(col - .5, row - 1.5, camera.gw, camera.hc)


class TestConstruction:
    def test_the_app_starts_where_main_left_it(self):
        app = make(zoom=2.0, view="street", sky=True)
        assert (app.lat, app.lon) == app.home == (43.68, -70.37)
        assert app.zoom == 2.0 and app.view == "street"
        assert app.sun and app.clouds and app.show_labels
        assert app.drag_base is None and app._worker is None
        assert app.displayed_camera() == app.target_camera()
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

    def test_the_ceiling_opens_up_on_a_narrow_terminal(self, monkeypatch):
        app = make(zoom=MAX_ZOOM_DEG)
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (54, 47))
        assert app.zoom_to(1e9)
        assert app.zoom == maps.max_zoom(*maps.map_cells())
        assert app.zoom > MAX_ZOOM_DEG

    @pytest.mark.parametrize("zoom", [0.0024, 2.0, 30.0, 125.0])
    def test_an_anchored_zoom_keeps_the_point_through_the_motion(self, zoom, clock):
        app = make(zoom=zoom)
        start = app.displayed_camera()
        before = point_under(start, 56, 18)
        assert app.zoom_to(zoom / 1.2, at=(56, 18))
        target = app.target_camera()
        assert point_under(target, 56, 18) == pytest.approx(before, abs=1e-9)
        assert app.displayed_camera().key == start.key
        clock[0] += app._motion.duration / 2
        midway = app.displayed_camera()
        assert midway.zoom == pytest.approx(math.sqrt(start.zoom * target.zoom))
        assert point_under(midway, 56, 18) == pytest.approx(before, abs=1e-9)
        clock[0] += app._motion.duration
        assert app.displayed_camera() == target

    def test_a_zoom_about_the_centre_keeps_it(self):
        app = make(zoom=2.0)
        assert app.zoom_to(1.0)
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_the_former_projection_boundary_does_not_change_wheel_behavior(self):
        app = make(zoom=45.0 / 1.2)
        before = point_under(app.target_camera(), 30, 12)
        assert app.zoom_to(45.0 * 1.2, at=(30, 12))
        assert point_under(app.target_camera(), 30, 12) == pytest.approx(before, abs=1e-9)
        assert (app.lat, app.lon) != app.home

    def test_an_anchored_zoom_wraps_the_longitude(self):
        app = make(zoom=20.0, lat=0.0, lon=179.9)
        assert app.zoom_to(10.0, at=(2, 20))
        assert -180.0 <= app.lon <= 180.0

    def test_zoom_starts_one_ticker_and_no_source_worker(self):
        app = make(zoom=1.0)
        assert app.zoom_to(2.0)
        assert not app.zoom_to(2.0)
        assert app.zoom_to(3.0)
        assert app._worker is None
        assert [t.target for t in FakeThread.started] == [app._tick]

    def test_the_wheel_zooms_in_going_up(self):
        app = make(zoom=1.0)
        assert app.on_wheel(1, 50, 20)
        assert app.zoom == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_wheel(-1, 50, 20)
        assert app.zoom == pytest.approx(1.0)


class TestKeys:
    @pytest.mark.parametrize('key,delta', [
        ('w', (0, HC * .1)), ('a', (GW * .1, 0)),
        ('s', (0, -HC * .1)), ('d', (-GW * .1, 0)),
    ])
    @pytest.mark.parametrize('zoom', [0.01, 2, 60])
    def test_wasd_sets_a_target_and_eases_the_display(self, key, delta, zoom, clock):
        app = make(zoom=zoom, lat=0, lon=0)
        start = app.displayed_camera()
        expected = start.pan(*delta)
        app.spinning = 1
        assert app.intercept('key:' + key) is False
        assert app.on_action(key)
        assert app.target_camera() == expected
        assert app.displayed_camera() == start
        assert app.home == (0, 0) and not app.sun and not app.routes.panel
        assert app.drag_base is None and app.spinning == 0
        assert app._worker is None
        clock[0] += app._motion.duration / 2
        assert app.displayed_camera() not in (start, expected)
        clock[0] += app._motion.duration
        assert app.displayed_camera() == expected

    def test_keyboard_pan_wraps_longitude_and_can_cross_a_pole(self, clock):
        app = make(zoom=60, lat=79, lon=179)
        app.on_action('d')
        assert -180 <= app.lon < 0
        clock[0] += 1
        app.lat, app.lon = 89, 0
        app.on_action('w')
        assert app.lat < 89 and abs(app.lon) == pytest.approx(180)

    @pytest.mark.parametrize("zoom", [.0012, 2, 125])
    def test_reversing_wasd_turns_from_the_displayed_view_without_finishing_queued_pan(
            self, zoom, clock):
        app = make(zoom=zoom, lat=0, lon=0)
        app.on_action('d')
        first = app.target_camera()
        app.on_action('d')
        assert app.target_camera() == first.pan(-GW * .1, 0)
        clock[0] += app._motion.duration / 4
        displayed = app.displayed_camera()
        assert 0 < displayed.lon < app.lon
        app.on_action('a')
        assert app.displayed_camera() == displayed
        assert app.target_camera() == displayed.pan(GW * .1, 0)
        clock[0] += app._motion.duration / 4
        assert app.displayed_camera().lon < displayed.lon

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
        assert app.on_action('S') and app.sun is True
        assert app.on_action('c') and app.clouds is True

    def test_an_unknown_key_does_nothing(self):
        assert make().on_action('x') is False

    def test_r_spins_only_a_warm_globe(self, monkeypatch):
        app = make(zoom=1.0)
        assert app.on_action('r') is False and app.spinning == 0
        app.zoom = 45.0
        assert app.on_action('r') is False and app.spinning == 0
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: h == HC * 4)
        assert app.on_action('r') is True
        assert app.spinning == app.spin_seq == 1
        assert FakeThread.started[-1].target == app._tick
        assert app._worker is None

    def test_r_parks_a_spin_already_running(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=45.0)
        app.on_action('r')
        assert app.on_action('r') is True
        assert app.spinning == 0 and app.spin_seq == 1
        app.on_action('r')
        assert app.spinning == app.spin_seq == 2

    def test_stop_parks_the_spin(self):
        app = make()
        app.spinning = 3
        app.stop()
        assert app.spinning == 0 and app._stopped

    def test_text_mode_is_the_search_field(self):
        app = make()
        assert app.text_mode() is False
        app.search.start()
        assert app.text_mode() is True


class TestDrag:
    @pytest.mark.parametrize("zoom", [0.01, 2.0, 60.0, 125.0])
    @pytest.mark.parametrize("warm", [False, True])
    def test_drag_is_immediate_and_cumulative_at_every_scale(self, monkeypatch, zoom, warm):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: warm)
        app = make(zoom=zoom)
        base = app.target_camera()
        assert app.on_drag(4, 2, False)
        assert app.drag_base == base
        assert app.target_camera() == base.pan(4, 2)
        assert app.displayed_camera() == app.target_camera()
        assert app.on_drag(10, 5, False)
        assert app.target_camera() == base.pan(10, 5)
        assert app.on_drag(10, 5, False) is False
        assert app.on_drag(10, 5, True)
        assert app.drag_base is None
        assert app.target_camera() == base.pan(10, 5)
        assert app.home == (43.68, -70.37)
        assert app._worker is None and FakeThread.started == []

    def test_a_commit_wraps_the_longitude(self):
        app = make(zoom=2.0, lat=0.0, lon=-179.99)
        app.on_drag(60, 0, True)
        assert app.lon > 0

    def test_a_release_with_no_delta_repaints_only_after_a_drag(self):
        app = make(zoom=2.0)
        base = app.target_camera()
        assert app.on_drag(0, 0, True) is False
        app.on_drag(3, 0, False)
        assert app.on_drag(0, 0, True) is True
        assert app.target_camera() == base
        assert app.drag_base is None

    def test_drag_takes_over_from_the_current_display_during_animation(self, clock):
        app = make(zoom=2)
        app.on_action('d')
        clock[0] += app._motion.duration / 2
        displayed = app.displayed_camera()
        assert displayed != app.target_camera()
        assert app.on_drag(5, 3, False)
        assert app.drag_base == displayed
        assert app.target_camera() == displayed.pan(5, 3)
        assert app.displayed_camera() == app.target_camera()
        assert not app._motion.moving


class TestIntercept:
    def test_the_search_panel_eats_every_key(self):
        app = make()
        app.search.start()
        assert app.intercept('key:?') is True
        assert app.intercept('char:a') is True
        assert app.search.query == "a"

    def test_help_uses_the_shared_panel_with_map_credits(self):
        app = make()
        help_panel = app.help_panel()
        assert help_panel.handle('key:?') and help_panel.open
        assert _maps_ui.TILE_ATTRIBUTION in help_panel.render(100, 42)
        assert help_panel.handle('escape') and not help_panel.open

    def test_slash_opens_search_and_o_the_origin(self):
        app = make()
        assert app.intercept('key:/') is True
        assert app.search.open and app.search.purpose == "go"
        app.search.close()
        assert app.intercept('open') is True
        assert app.search.purpose == "origin"

    def test_d_opens_the_panel_and_asks_for_a_destination(self):
        app = make()
        assert app.intercept('key:D') is True
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
        assert app.intercept('key:D') is True
        assert app.search.open and app.search.purpose == "route"
        app.search.close()
        assert app.intercept('escape') is True and not app.routes.panel

    def test_p_cycles_the_profile(self):
        app = make()
        assert app.intercept('key:p') is True
        assert app.routes.profile == _maps_route.PROFILES[1]

    def test_reset_clears_routes_and_eases_back_to_home(self, clock):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"))
        app.routes.panel = True
        app.lat, app.lon, app.zoom = 40, -60, 3
        displaced = app.displayed_camera()
        assert app.intercept('reset') is True
        assert app.routes.dest is None and not app.routes.panel
        assert (app.lat, app.lon) == app.home
        assert app.zoom == 3
        assert app.displayed_camera() == displaced
        clock[0] += app._motion.duration + .01
        assert app.displayed_camera() == app.target_camera()

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
        assert app.render(mouse_pos=(4, 5)) == "frame"
        f = frames[-1]
        assert (f["lat"], f["lon"], f["zoom"]) == (43.68, -70.37, 2.0)
        assert f["name"] == "Westbrook" and f["marker"] == (43.68, -70.37)
        assert f["runtime"] is app.runtime
        assert f["mouse_pos"] == (4, 5)
        assert f["camera"] == app.displayed_camera()
        assert f["refining"] and f["prepared"] is None
        assert f["view"] == "street" and f["search"] is app.search
        assert f["directions"] is app.routes and f["route"] is None
        assert f["sun"] is True and f["clouds"] is True

    @pytest.mark.parametrize("zoom", [0.01, 2, 60, 125])
    def test_each_foreground_drag_frame_is_nonblocking(self, frames, monkeypatch, zoom):
        app = make(zoom=zoom)
        monkeypatch.setattr(app, "_prepare", lambda *a: pytest.fail("foreground source build"))
        app.on_drag(5, 2, False)
        assert app._worker is None
        for _ in range(3):
            app.render()
            assert frames[-1]["prepared"] is None
        assert [t.target for t in FakeThread.started] == [app._worker._run]

    def test_spin_uses_elapsed_time_only_when_the_foreground_renders(self, frames,
                                                                   monkeypatch, clock):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=125, lon=179.5)
        assert app.on_action('r')
        clock[0] += 2.5
        assert app.lon == 179.5
        app.render()
        assert app.lon == pytest.approx(177)
        clock[0] += .1
        app.render()
        assert app.lon == pytest.approx(176.9)
        assert app.displayed_camera() == app.target_camera()
        assert [t.target for t in FakeThread.started].count(app._tick) == 1

    def test_completed_detail_does_not_move_the_displayed_camera(self, frames, clock):
        app = make(zoom=2)
        app.on_action('d')
        clock[0] += app._motion.duration / 2
        midway = app.displayed_camera()
        exact = types.SimpleNamespace(camera=app.target_camera())
        overscan = object()
        scene = Scene(exact, overscan)
        app._worker = types.SimpleNamespace(request=lambda *a, **kw: (scene, False, None))
        app.render()
        assert frames[-1]["camera"] == midway
        assert frames[-1]["prepared"] is overscan
        clock[0] += app._motion.duration
        app.render()
        assert frames[-1]["camera"] == app.target_camera()
        assert frames[-1]["prepared"] is exact

    @pytest.mark.parametrize("zoom", [2, 15])
    def test_preparation_adds_bounded_coverage_without_losing_local_detail(self, monkeypatch,
                                                                       zoom):
        app = make(zoom=zoom)
        camera = app.target_camera()
        seen = []

        def prepare(source, **kw):
            seen.append(source)
            fills = [[(0, 0, 0)] * source.gw for _ in range(source.hc * 2)]
            return PreparedMap(source, fills)

        monkeypatch.setattr(_maps_live, "prepare_map", prepare)
        scene = app._prepare(camera, {}, _theme.generation)
        source, = seen
        full_gw, full_hc = GW + 2 * ((GW + 3) // 4), HC + 2 * ((HC + 3) // 4)
        assert camera.local_tiles and source.local_tiles
        if zoom == 2:
            assert (source.gw, source.hc) == (full_gw, full_hc)
        else:
            assert GW <= source.gw < full_gw
            assert HC <= source.hc < full_hc
        assert source.zoom / source.hc == pytest.approx(camera.zoom / camera.hc)
        assert source.gw * source.hc < camera.gw * camera.hc * 2.5
        assert scene.exact.camera == camera and scene.overscan.camera == source
        assert len(scene.exact.fills) == camera.hc * 2
        assert len(scene.exact.fills[0]) == camera.gw

    def test_retained_render_transforms_without_asking_sources(self, monkeypatch):
        app = make(zoom=2)
        base = app.target_camera()
        frame = PreparedMap(base, [[(10, 20, 30)] * GW for _ in range(HC * 2)])
        scene = Scene(frame, frame)
        app._worker = types.SimpleNamespace(request=lambda *a, **kw: (scene, True, None))
        for name in ('_get_elevation', '_get_street', '_get_globe', '_get_clouds',
                     '_get_route_layer'):
            monkeypatch.setattr(maps, name, lambda *a, **k: pytest.fail("source in preview"))
        monkeypatch.setattr(maps, "_panned_place", lambda *a: "Westbrook")
        app.on_drag(3, 2, False)
        moved = []
        transform = PreparedMap.transformed

        def record(self, camera):
            moved.append(camera)
            return transform(self, camera)

        monkeypatch.setattr(PreparedMap, "transformed", record)
        output = app.render()
        assert moved == [app.target_camera()]
        assert len(output.splitlines()) == ROWS

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


@pytest.mark.parametrize('failure', [None, OSError(), RuntimeError('offline\nextra row')])
def test_print_builds_once_then_uses_the_same_renderer(monkeypatch, capsys, failure):
    from linecast import _maps_tile_cache

    monkeypatch.setattr(sys, 'argv', ['linecast-maps', '--print', '--view', 'now',
                                      '--zoom', '130', '--location', '43,-70'])
    monkeypatch.setattr(_maps_tile_cache, 'prune_maps_cache', lambda: None)
    monkeypatch.setattr(_maps_live, 'resolve_location', lambda *a, **kw:
                        (43, -70, None, 'Home'))
    monkeypatch.setattr(_maps_live, 'country_for_defaults', lambda *a: None)
    monkeypatch.setattr(maps._climate, 'available', lambda: False)
    monkeypatch.setattr(maps._globe_now, 'subsolar', lambda: (0, 0))
    monkeypatch.setattr(maps, '_panned_place', lambda *a: 'Equator')
    builds, frames = [], []
    draw = _maps_live.render_map

    def prepare(camera, **options):
        builds.append((camera, options))
        if failure is not None:
            raise failure
        return PreparedMap(camera, [[(10, 20, 30)] * camera.gw
                                    for _ in range(camera.hc * 2)], world=True)

    def render(camera, prepared, name, **options):
        frames.append((camera, prepared, options))
        return draw(camera, prepared, name, **options)

    monkeypatch.setattr(_maps_live, 'prepare_map', prepare)
    monkeypatch.setattr(_maps_live, 'render_map', render)
    _maps_live.main()
    output = capsys.readouterr().out
    assert len(builds) == len(frames) == 1
    assert builds[0][0] == frames[0][0]
    assert builds[0][1]['wait_for_clouds']
    assert builds[0][1]['sun'] and builds[0][1]['clouds']
    assert len(output.splitlines()) == ROWS
    assert '\x1b[?1003' not in output
    if failure is not None:
        assert frames[0][1] is None
        assert frames[0][2]['error'] == ('offline' if str(failure) else 'OSError')
        assert frames[0][2]['error'] in output.splitlines()[-1]
        assert 'extra row' not in output


def test_live_world_prepares_complete_surface_on_its_existing_worker(monkeypatch):
    from linecast import _maps_globe

    app = make(zoom=130)
    camera = app.target_camera()
    builds = []
    surface = object()

    def prepare(camera, **options):
        builds.append(('detail', camera))
        return PreparedMap(camera, [[(10, 20, 30)] * camera.gw
                                    for _ in range(camera.hc * 2)], world=True)

    def coverage(camera, **options):
        builds.append(('surface', camera))
        return surface

    monkeypatch.setattr(_maps_live, 'prepare_map', prepare)
    monkeypatch.setattr(_maps_globe, 'prepare_surface', coverage)
    app.render()
    assert builds == []
    assert [thread.target for thread in FakeThread.started] == [app._worker._run]
    app._worker._run()
    assert builds == [('detail', camera), ('surface', camera)]
    scene = next(iter(app._worker._ready.values()))[1]
    assert scene.exact.surface is scene.overscan.surface is surface
    app.stop()
