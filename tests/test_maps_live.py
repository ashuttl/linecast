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

from linecast import maps
from linecast._maps import globe as _globe
from linecast._maps import globe_texture
from linecast._maps import live as _maps_live
from linecast._maps import route as _maps_route
from linecast._maps import ui
from linecast._maps import views
from linecast._maps.live import (
    COAST_CEILING, Camera, MapApp, ZOOM_EASE,
)
from linecast._maps.motion import lon_span
from linecast._maps.search import Result
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
    """The camera's clock, turned by hand."""

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
    monkeypatch.setattr(ui, "threading", fake)
    monkeypatch.setattr(maps, "get_terminal_size", lambda: (COLS, ROWS))
    monkeypatch.setattr(_globe, "warm", lambda zoom, h: False)
    monkeypatch.setattr(globe_texture, "ready", lambda *a, **k: False)
    monkeypatch.setattr(_maps_live, "_zoom_hold",
                        types.SimpleNamespace(hold=lambda: None))
    monkeypatch.setattr(_maps_live, "prefetch_view", lambda *a, **k: None)
    yield
    views.hold_motion(False)


@pytest.fixture
def frames(monkeypatch):
    seen = []

    def fake_render_map(lat, lon, name, zoom, **kw):
        seen.append(dict(kw, lat=lat, lon=lon, name=name, zoom=zoom))
        return "frame"

    monkeypatch.setattr(_maps_live, "render_map", fake_render_map)
    return seen


def make(zoom=1.0, view="terrain", sky=False, lat=43.68, lon=-70.37,
         origin=None, dest=None, fit=False):
    runtime = types.SimpleNamespace(lang="en", live=True)
    app = MapApp(runtime, lat, lon, "Westbrook", zoom, view, sky, "car",
                 origin=origin, dest=dest, fit=fit)
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
    span = lon_span(app.lat, app.zoom, GW, HC)
    return (app.lat + app.zoom * (0.5 - fy), app.lon + span * (fx - 0.5))


class TestConstruction:
    def test_the_app_starts_where_main_left_it(self):
        app = make(zoom=2.0, view="street", sky=True)
        assert (app.lat, app.lon) == app.home == (43.68, -70.37)
        assert app.zoom == 2.0 and app.view == "street"
        assert app.sun and app.clouds and app.show_labels
        assert app.pan_preview == (0, 0)
        assert not app.camera.moving() and not app.camera.dragging()
        assert not app.camera.spinning
        assert app.interval == 3600 and app.mouse is True
        assert FakeThread.started == []

    def test_the_camera_knows_the_maps_size_and_ceiling(self):
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

    def test_a_fit_opens_on_both_endpoints(self):
        origin = Result("A", "", 43.66, -70.26, "city")
        dest = Result("B", "", 43.62, -70.21, "city")
        app = make(origin=origin, dest=dest, fit=True)
        assert (app.lat, app.lon, app.zoom) == maps.fit_view(
            [(43.66, -70.26), (43.62, -70.21)], GW, HC)
        assert app.fit_view == (app.lat, app.lon, app.zoom)
        assert app.home == (43.68, -70.37)   # the marker stays put

    def test_a_fit_needs_both_endpoints(self):
        app = make(dest=Result("B", "", 3.0, 4.0, "city"), fit=True)
        assert (app.lat, app.lon, app.zoom) == (43.68, -70.37, 1.0)
        assert app.fit_view is None
        assert make(fit=False).fit_view is None

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
    """The zoom eases now, so every landing is read after the clock has
    been turned past the ease."""

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
        # the anchor holds through the ease, not only at the end
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

    def test_a_zoom_across_the_hand_off_cuts_rather_than_eases(self):
        # neither side can stand in for the other, so every frame of
        # an ease across the hand-off would be blank: it snaps, as it
        # did before the camera, and the ticker is not started
        flat = _globe.ZOOM_DEG / 2
        app = make(zoom=flat, lat=0.0)
        assert app.zoom_to(flat * 4)
        assert app.zoom == flat * 4 and not app.camera.moving()
        assert FakeThread.started == []
        assert app.zoom_to(flat)
        assert app.zoom == flat and not app.camera.moving()
        # on one side it eases, whichever side that is
        assert app.zoom_to(flat / 2)
        assert app.zoom == flat and app.camera.moving()
        settle(app)
        app.zoom_to(flat * 4)
        assert app.zoom_to(flat * 8)
        assert app.zoom == flat * 4 and app.camera.moving()
        assert [t.target for t in FakeThread.started] == [app._tick, app._tick]

    def test_an_anchored_zoom_that_would_land_on_the_globe_cuts(self):
        # anchored at the bottom row, a zoom out carries the centre
        # toward the pole, and the hand-off is judged where the ease
        # would end rather than where it starts
        app = make(zoom=30.0, lat=20.0)
        assert not _globe.is_globe(30.0 * 1.4, 20.0)
        assert app.zoom_to(30.0 * 1.4, at=(50, ROWS - 1))
        assert not app.camera.moving()
        # and the cut is about the centre, as it is on the globe
        assert app.zoom == 30.0 * 1.4 and (app.lat, app.lon) == (20.0, -70.37)

    def test_an_anchored_zoom_wraps_the_longitude(self):
        app = make(zoom=20.0, lat=0.0, lon=179.9)
        assert app.zoom_to(10.0, at=(2, 20))
        settle(app)
        assert -180.0 <= app.lon <= 180.0

    def test_a_run_of_taps_compounds_before_the_first_lands(self):
        app = make(zoom=1.0)
        app.on_action('+')
        app.camera.clock.advance(ZOOM_EASE / 4)
        app.on_action('+')
        assert settle(app)[2] == pytest.approx(1.0 / ZOOM_STEP ** 2)

    def test_a_zoom_retargets_from_where_it_has_got_to(self):
        app = make(zoom=1.0)
        app.zoom_to(4.0)
        app.camera.clock.advance(ZOOM_EASE / 2)
        assert app.camera.view()[2] == pytest.approx(2.0)
        app.zoom_to(2.0)          # back from mid-way
        app.camera.clock.advance(ZOOM_EASE)
        assert app.camera.view()[2] == pytest.approx(2.0)

    def test_a_zoom_holds_the_fetches_and_wakes_the_ticker(self, monkeypatch):
        held = []
        monkeypatch.setattr(_maps_live, "_zoom_hold",
                            types.SimpleNamespace(hold=lambda: held.append(1)))
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.zoom_to(2.0)
        assert held == [1]
        assert [t.target for t in FakeThread.started] == [app._tick]

    def test_a_globe_zoom_asks_for_the_level_it_is_heading_for(self,
                                                              monkeypatch):
        # the texture is a file on disk or a bake of a canvas already
        # in hand, so it need not wait behind the motion gate: asked
        # for at the tap it is usually there before the ease ends
        asked = []
        monkeypatch.setattr(_maps_live, "warm_globe_texture",
                            lambda *a: asked.append(a))
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        assert asked == []                      # a flat zoom asks for nothing
        app = make(zoom=120.0)
        app.zoom_to(120.0 / ZOOM_STEP)
        assert asked == [(120.0 / ZOOM_STEP, HC, False)]
        app.view = "street"
        app.zoom_to(120.0 / ZOOM_STEP / ZOOM_STEP)
        assert asked[-1][2] is True             # the other register's texture

    def test_the_wheel_zooms_in_going_up(self):
        app = make(zoom=1.0)
        assert app.on_wheel(1, 50, 20)
        assert settle(app)[2] == pytest.approx(1.0 / ZOOM_STEP)
        assert app.on_wheel(-1, 50, 20)
        assert settle(app)[2] == pytest.approx(1.0)


class TestKeys:
    @pytest.mark.parametrize('key,dlat,dlon', [
        ('w', 1, 0), ('a', 0, -1), ('s', -1, 0), ('d', 0, 1),
    ])
    @pytest.mark.parametrize('globe', [False, True])
    def test_wasd_pans_the_view_and_keeps_the_marker(self, monkeypatch, key,
                                                     dlat, dlon, globe):
        # the pan eases now, so the landing is read after the clock
        # has been turned past it; the projection is the drag's, on a
        # warm globe and a flat map alike
        monkeypatch.setattr(_globe, 'warm', lambda zoom, h: globe)
        app = make(zoom=60.0 if globe else 2.0, lat=0, lon=0)
        app.camera.spin(True)
        assert app.intercept('key:' + key) is False
        assert app.on_action(key)
        assert app.camera.moving()
        settle(app)
        assert app.lat == pytest.approx(dlat * app.zoom * 0.1)
        assert app.lon == pytest.approx(
            dlon * lon_span(0.0, app.zoom, GW, HC) * 0.1)
        assert app.home == (0, 0) and not app.sun and not app.routes.panel
        assert app.pan_preview == (0, 0) and not app.camera.dragging()
        assert not app.camera.spinning

    def test_a_keyed_pan_compounds_when_it_is_repeated(self):
        app = make(zoom=2.0, lat=0, lon=0)
        app.on_action('d')
        app.camera.clock.advance(ZOOM_EASE / 4)
        app.on_action('d')
        settle(app)
        assert app.lon == pytest.approx(
            2 * lon_span(0.0, 2.0, GW, HC) * 0.1)

    def test_keyboard_pan_wraps_and_clamps(self):
        app = make(zoom=60, lat=79, lon=179)
        app.on_action('d')
        settle(app)
        assert -180 <= app.lon < 0
        app.on_action('w')
        settle(app)
        assert app.lat == 80

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
        assert app.on_action('S') and app.sun is True
        assert app.on_action('c') and app.clouds is True

    def test_an_unknown_key_does_nothing(self):
        assert make().on_action('x') is False

    def test_r_spins_only_a_warm_globe(self, monkeypatch):
        # the spin rides the camera's clock now, so what r starts is
        # the ticker rather than a thread of its own
        app = make(zoom=1.0)
        assert app.on_action('r') is False and not app.camera.spinning
        app.zoom = _globe.ZOOM_DEG
        assert app.on_action('r') is False and not app.camera.spinning
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: h == HC * 4)
        assert app.on_action('r') is False
        assert app.camera.spinning and app.camera.moving()
        assert FakeThread.started[-1].target == app._tick

    def test_the_spin_turns_the_planet_a_degree_a_second(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG, lon=0.0)
        app.on_action('r')
        app.camera.clock.advance(2.0)
        assert app.camera.view()[1] == pytest.approx(-2.0)

    def test_the_spin_waits_while_a_drag_is_in_hand(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=60.0, lat=0.0, lon=0.0)
        app.on_action('r')
        app.on_drag(0, 0, False)
        app.camera.clock.advance(1.0)
        assert app.camera.view()[1] == 0.0
        app.on_drag(0, 0, True)
        app.camera.clock.advance(1.0)
        assert app.camera.view()[1] == pytest.approx(-1.0)

    def test_a_zoom_back_inside_the_hand_off_parks_the_spin(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_action('r')
        assert app.camera.spinning
        app.zoom_to(1.0)
        settle(app)
        assert not app.camera.spinning and not app.camera.moving()

    def test_r_parks_a_spin_already_running(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_action('r')
        assert app.on_action('r') is False
        assert not app.camera.spinning and not app.camera.moving()
        app.on_action('r')
        assert app.camera.spinning

    def test_stop_parks_the_camera(self):
        app = make()
        app.camera.spin(True)
        app.stop()
        assert not app.camera.spinning and not app.camera.moving()

    def test_text_mode_is_the_search_field(self):
        app = make()
        assert app.text_mode() is False
        app.search.start()
        assert app.text_mode() is True


class TestDrag:
    def test_a_flat_drag_follows_the_hand(self):
        # A flat view is built a margin wider than the window, so the
        # window at the dragged centre is a crop of what is already in
        # hand: the drag moves the camera on every motion event, as a
        # warm globe's does, instead of shifting the last frame and
        # taking its centre at the release.
        app = make(zoom=2.0)
        assert app.on_drag(10, 5, False)
        assert app.pan_preview == (0, 0)
        span = lon_span(43.68, 2.0, GW, HC)
        assert app.lat == pytest.approx(43.68 + 5 * 2.0 / HC)
        assert app.lon == pytest.approx(-70.37 - 10 * span / GW)
        assert app.on_drag(10, 5, False) is False  # nothing new
        assert app.on_drag(10, 5, True)
        assert app.pan_preview == (0, 0) and not app.camera.dragging()
        assert app.lat == pytest.approx(43.68 + 5 * 2.0 / HC)
        assert app.lon == pytest.approx(-70.37 - 10 * span / GW)

    def test_a_flat_drag_says_which_way_it_is_going(self):
        # the margin is built deep where the reader is heading: a hand
        # moving right carries the ground west, and a hand moving down
        # carries it north
        app = make(zoom=2.0)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.05)
        app.on_drag(12, 6, False)
        assert app.camera.heading() == (-1, -1)

    def test_a_commit_wraps_the_longitude(self):
        app = make(zoom=2.0, lat=0.0, lon=-179.99)
        app.on_drag(60, 0, True)
        assert app.lon > 0

    def test_a_release_after_a_drag_back_to_the_press_repaints(self):
        # a press and a release with nothing in between is a click; a
        # drag that comes back to where it started has still moved the
        # camera away and back, and the release commits it
        app = make(zoom=2.0)
        assert app.on_drag(0, 0, True) is False
        app.on_drag(3, 0, False)
        assert app.on_drag(0, 0, True) is True
        assert (app.lat, app.lon) == (43.68, -70.37)

    def test_a_cold_globe_shifts_its_last_frame(self):
        # the one idiom left that cannot follow the hand: a sphere has
        # no re-projection about a moved centre
        app = make(zoom=_globe.ZOOM_DEG)
        assert app.on_drag(4, 0, False)
        assert app.pan_preview == (4, 0) and app._drag_shift

    def test_a_warm_globe_rotates_under_the_cursor(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=60.0, lat=70.0, lon=0.0)
        assert app.on_drag(0, 0, True) is False  # a click, not a drag
        assert app.on_drag(10, 20, False)
        assert not app._drag_shift and app.camera.dragging()
        assert app.lat == 80.0  # clamped
        assert app.lon == pytest.approx(
            -(10 * lon_span(70.0, 60.0, GW, HC) / GW))
        assert app.on_drag(10, 20, False) is False  # nothing moved
        assert app.on_drag(10, 20, True) is True
        assert not app.camera.dragging()

    def test_a_flick_coasts_and_stops_for_good(self):
        app = make(zoom=2.0)
        clock = app.camera.clock
        app.on_drag(0, 0, False)
        clock.advance(0.05)
        app.on_drag(-10, 0, False)
        assert app.on_drag(-10, 0, True)
        lon_at_release = app.lon
        assert app.camera.moving()
        assert [t.target for t in FakeThread.started] == [app._tick]
        clock.advance(0.1)
        _lat, lon_soon, _zoom = app.camera.view()
        assert lon_soon > lon_at_release
        clock.advance(3.0)
        _lat, lon_rest, _zoom = app.camera.view()
        assert lon_rest > lon_soon
        assert not app.camera.moving()
        clock.advance(3.0)
        assert app.camera.view()[1] == lon_rest   # at rest for good

    def test_a_slow_release_does_not_coast(self):
        app = make(zoom=2.0)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(10, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(10, 0, True)
        assert not app.camera.moving()

    def test_a_hand_that_pauses_before_letting_go_does_not_coast(self):
        # the release is not a motion, so a hand brought to rest and
        # then lifted stops where it is
        app = make(zoom=2.0)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.05)
        app.on_drag(-10, 0, False)
        app.camera.clock.advance(0.4)
        app.on_drag(-10, 0, True)
        assert not app.camera.moving()

    def test_a_flick_on_a_warm_globe_coasts_too(self, monkeypatch):
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=60.0, lat=0.0, lon=0.0)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.05)
        app.on_drag(-10, 0, False)
        app.on_drag(-10, 0, True)
        assert app.camera.moving()

    def test_a_flick_asks_for_where_it_will_stop(self, frames, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append((a, k)))
        app = make(zoom=2.0, view="street")
        clock = app.camera.clock
        app.on_drag(0, 0, False)
        clock.advance(0.05)
        app.on_drag(-10, 0, False)
        app.on_drag(-10, 0, True)
        assert app.camera.moving() and len(asked) == 1
        (lat, lon, zoom, view, gw, hc, lang), kw = asked[0]
        assert (zoom, view, gw, hc, lang) == (2.0, "street", GW, HC, "en")
        assert kw == {"marker": (43.68, -70.37)}
        assert lon > app.lon                     # east, where the flick went
        # and it is where the coast actually comes to rest, so the
        # frame at rest draws what is already on its way
        app.render()
        settle(app)
        app.render()
        assert app.lat == pytest.approx(lat, abs=1e-9)
        assert app.lon == pytest.approx(lon, abs=1e-9)
        assert len(asked) == 1                   # at the release, once

    def test_a_hand_brought_to_rest_asks_for_nothing(self, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=2.0, view="street")
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(-10, 0, False)
        app.camera.clock.advance(0.5)
        app.on_drag(-10, 0, True)
        assert not app.camera.moving() and asked == []

    def test_a_flick_on_a_globe_asks_for_nothing(self, monkeypatch):
        # a cold globe pans with the flat idiom, but its view is still
        # a planet: nothing here fetches a window
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.05)
        app.on_drag(-10, 0, False)
        app.on_drag(-10, 0, True)
        assert app.camera.moving() and asked == []

    def test_a_coast_builds_what_it_passes_over_and_a_flight_does_not(
            self, frames):
        app = make(zoom=2.0, view="street")
        app.on_drag(0, 0, False)
        app.camera.clock.advance(0.05)
        app.on_drag(-10, 0, False)
        app.on_drag(-10, 0, True)
        app.render()
        assert views._in_motion[0] and views._build_passing[0]
        app.camera.fly_to(44.0, -71.0, 0.5)
        app.render()
        assert views._in_motion[0] and not views._build_passing[0]
        settle(app)
        app.render()
        assert not views._in_motion[0] and views._build_passing[0]

    def test_a_press_stops_a_coast_and_a_flight(self):
        app = make(zoom=2.0)
        app.camera.fly_to(44.0, -71.0, 1.0)
        assert app.camera.moving()
        app.on_drag(1, 0, False)
        assert not app.camera.moving()

    def test_a_key_a_zoom_and_a_panel_all_stop_a_coast(self, frames):
        for stop in (lambda a: a.on_action('d'),
                     lambda a: a.zoom_to(1.0),
                     lambda a: (a.search.start(), a.render())):
            app = make(zoom=2.0)
            app.camera.fly_to(44.0, -71.0, 1.0)
            assert app.camera.moving()
            stop(app)
            assert not app.camera._flight and not app.camera._coast


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
        assert ui.TILE_ATTRIBUTION in help_panel.render(100, 42)
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

    def test_the_panel_takes_the_arrows_and_the_map_flies_along(self):
        # a step is flown to rather than cut to, so the view is read
        # once the flight has run out
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
        assert app.intercept('key:D') is True
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
        app.pan_preview = (3, 1)
        assert app.render(mouse_pos=(4, 5)) == "frame"
        f = frames[-1]
        assert (f["lat"], f["lon"], f["zoom"]) == (43.68, -70.37, 2.0)
        assert f["name"] == "Westbrook" and f["marker"] == (43.68, -70.37)
        assert f["runtime"] is app.runtime and f["block"] is False
        assert f["pan_offset"] == (3, 1) and f["mouse_pos"] == (4, 5)
        assert f["view"] == "street" and f["search"] is app.search
        assert f["directions"] is app.routes and f["route"] is None
        assert f["show_labels"] is True
        assert f["sun"] is True and f["clouds"] is True

    def test_a_warm_globe_renders_blocking_moving_or_at_rest(self, frames,
                                                            monkeypatch):
        # a warm globe frame is cheap, and the frame where a coast runs
        # out is at a centre the moving frames never drew: rendered
        # through the cache it would be a blank disk before the planet
        # settles
        monkeypatch.setattr(_globe, "warm", lambda zoom, h: True)
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_drag(4, 0, False)
        app.render()
        assert frames[-1]["block"] is True
        app.on_drag(4, 0, True)
        settle(app)
        app.render()
        assert not app.camera.moving()
        assert frames[-1]["block"] is True

    def test_a_cold_globe_never_blocks(self, frames):
        app = make(zoom=_globe.ZOOM_DEG)
        app.on_drag(4, 0, False)
        app.render()
        assert frames[-1]["block"] is False

    def test_a_flat_view_never_blocks(self, frames):
        app = make(zoom=1.0)
        app.on_drag(4, 0, False)
        app.render()
        assert frames[-1]["block"] is False

    def test_a_frame_in_motion_holds_the_fetches_and_drops_the_pointer(
            self, frames):
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.render(mouse_pos=(4, 5))
        assert views._in_motion[0] is True
        assert frames[-1]["mouse_pos"] is None
        settle(app, ZOOM_EASE + 0.01)
        app.render(mouse_pos=(4, 5))
        assert views._in_motion[0] is False
        assert frames[-1]["mouse_pos"] == (4, 5)

    def test_a_frame_advances_the_motion(self, frames):
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.camera.clock.advance(ZOOM_EASE + 0.01)
        app.render()
        assert frames[-1]["zoom"] == 2.0
        assert not app.camera.moving()

    def test_the_opening_route_reframes_the_view_once(self, frames):
        origin = Result("A", "", 43.66, -70.26, "city")
        dest = Result("B", "", 43.62, -70.21, "city")
        app = make(origin=origin, dest=dest, fit=True)
        app.render()                      # still pending: nothing moves
        assert app.fit_view is not None
        # the route bulges west of the endpoints' box
        coords = [(-70.26, 43.66), (-70.30, 43.64), (-70.21, 43.62)]
        app.routes.route = _maps_route.Route(coords, 9000.0, 1800.0, [], "bike")
        app.render()
        assert (app.lat, app.lon, app.zoom) == maps.fit_view(
            [(43.66, -70.26), (43.64, -70.30), (43.62, -70.21)], GW, HC)
        assert app.fit_view is None
        assert (frames[-1]["lat"], frames[-1]["zoom"]) == (app.lat, app.zoom)
        # a later route leaves the view alone
        app.routes.route = _maps_route.Route(coords[:1] + coords[2:], 1.0, 1.0, [], "car")
        app.render()
        assert app.lon == maps.fit_view(
            [(43.66, -70.26), (43.64, -70.30), (43.62, -70.21)], GW, HC)[1]

    def test_a_moved_view_is_not_reframed_by_the_route(self, frames):
        origin = Result("A", "", 43.66, -70.26, "city")
        dest = Result("B", "", 43.62, -70.21, "city")
        app = make(origin=origin, dest=dest, fit=True)
        app.zoom_to(app.zoom * ZOOM_STEP)
        settle(app)
        moved = (app.lat, app.lon, app.zoom)
        app.routes.route = _maps_route.Route(
            [(-70.26, 43.66), (-70.30, 43.64), (-70.21, 43.62)], 1.0, 1.0, [], "bike")
        app.render()
        assert (app.lat, app.lon, app.zoom) == moved
        assert app.fit_view is None

    def test_a_parked_search_result_is_flown_to(self, frames):
        # a result is flown to rather than jumped to, so the view
        # arrives once the flight has run out
        app = make(zoom=1.0)
        app.search.start()
        app.search.chosen = Result("Portland", "", 43.66, -70.25, "city")
        app.render()
        assert app.camera.moving()
        settle(app)
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


class TestFlights:
    def test_a_search_result_is_prefetched_from_the_descent(self, frames,
                                                            monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append((a, k)))
        app = make(zoom=1.0)
        app.search.start()
        # the commit path parks the result and closes the field
        app.search.chosen = Result("Portland", "", 43.66, -70.25, "city")
        app.search.open = False
        app.render()
        assert app.camera.moving()
        # the destination is asked for from the descent, not at take-off
        assert asked == []
        duration = app.camera._flight[0].duration
        app.camera.clock.advance(duration * 0.4)
        app.render()
        assert asked == []
        app.camera.clock.advance(duration * 0.2)
        app.render()
        (lat, lon, zoom, view, gw, hc, lang), kw = asked[0]
        assert (lat, lon, view, gw, hc, lang) == (43.66, -70.25, "terrain",
                                                  GW, HC, "en")
        assert zoom != 1.0 and kw == {"marker": (43.68, -70.37)}
        settle(app)
        app.render()
        assert len(asked) == 1          # asked for once, not every frame
        assert (app.lat, app.lon) == (43.66, -70.25) and app.zoom == zoom

    def test_a_flight_to_where_you_already_are_is_nothing(self, frames,
                                                          monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=1.0)
        app.fly_to(Result("Here", "", 43.68, -70.37, "city"))
        assert app.camera.moving()   # the zoom differs, so it flies
        app.camera.clock.advance(app.camera._flight[0].duration * 0.6)
        app.render()
        settle(app)
        app.render()
        app.fly_to(Result("Here", "", 43.68, -70.37, "city"))
        assert not app.camera.moving() and len(asked) == 1

    def test_a_flight_cut_short_does_not_fetch_where_it_was_going(
            self, frames, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=1.0)
        app.fly_to(Result("Portland", "", 43.66, -70.25, "city"))
        app.camera.clock.advance(0.1)
        app.on_drag(1, 0, False)          # a hand on the map ends it
        app.render()
        assert asked == [] and app._destination is None
        app.on_drag(1, 0, True)
        app.fly_to(Result("Portland", "", 43.66, -70.25, "city"))
        app.camera.clock.advance(0.1)
        app.on_action('+')                # so does a zoom tap
        app.render()
        assert asked == [] and app._destination is None

    def test_a_flight_that_lands_unseen_leaves_the_fetch_to_the_frame(
            self, frames, monkeypatch):
        # a slow terminal may paint no frame between the top of the
        # flight and its end; the resting frame then fetches for itself
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=1.0)
        app.fly_to(Result("Portland", "", 43.66, -70.25, "city"))
        settle(app)
        app.render()
        assert asked == [] and app._destination is None
        assert views._in_motion[0] is False

    def test_the_destination_fetched_is_the_one_the_flight_lands_on(
            self, monkeypatch):
        asked = []
        monkeypatch.setattr(_maps_live, "prefetch_view",
                            lambda *a, **k: asked.append(a))
        app = make(zoom=1.0)
        app.fly_to(Result("Alert", "", 82.5, 190.0, "city"))
        assert app._destination[:2] == (80.0, -170.0)
        settle(app)
        assert (app.lat, app.lon, app.zoom) == app._destination

    def test_the_opening_fit_still_jumps(self):
        origin = Result("A", "", 43.66, -70.26, "city")
        dest = Result("B", "", 43.62, -70.21, "city")
        app = make(origin=origin, dest=dest, fit=True)
        assert not app.camera.moving()


class TestCamera:
    """The camera on its own, at the map's 100 by 40."""

    def _camera(self, lat=43.68, lon=-70.37, zoom=2.0):
        cam = Camera(lat, lon, zoom, clock=Clock())
        cam.gw, cam.hc = GW, HC
        cam.zoom_max = maps.max_zoom(GW, HC)
        return cam

    def test_a_flight_ends_where_it_was_sent(self):
        cam = self._camera()
        assert cam.fly_to(44.0, -71.0, 0.5)
        assert cam.moving()
        cam.clock.advance(0.1)
        lat, _lon, zoom = cam.view()
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
        assert min(zooms) >= cam.zoom_min

    def test_a_jump_is_immediate_and_clamped(self):
        cam = self._camera()
        cam.zoom_to(1.0)
        cam.jump_to(89.0, 200.0, 1e9)
        assert not cam.moving()
        assert cam.view() == (80.0, -160.0, cam.zoom_max)

    def test_a_coast_stops_at_the_polar_limit(self):
        cam = self._camera(lat=79.0, zoom=10.0)
        cam.press()
        cam.drag(0, 0)
        cam.clock.advance(0.05)
        cam.drag(0, 40)
        cam.release()
        cam.clock.advance(3.0)
        assert cam.view()[0] == 80.0
        assert not cam.moving()

    def _flick(self, cam, dcol, drow):
        cam.press()
        cam.drag(0, 0)
        cam.clock.advance(0.05)
        cam.drag(dcol, drow)
        cam.release()
        assert cam._coast is not None
        return cam.coast_destination()

    def test_the_destination_is_where_a_flick_east_stops(self):
        cam = self._camera(lat=0.0, lon=0.0)
        lat, lon = self._flick(cam, -20, 0)
        cam.clock.advance(5.0)
        rest_lat, rest_lon, _zoom = cam.view()
        assert not cam.moving()
        assert rest_lat == pytest.approx(lat, abs=1e-6)
        assert rest_lon == pytest.approx(lon, abs=1e-6)
        assert lon > 0                    # the ground came west, the view east

    def test_the_destination_is_clamped_at_the_polar_limit(self):
        cam = self._camera(lat=79.0, lon=0.0, zoom=10.0)
        lat, lon = self._flick(cam, -6, 40)
        cam.clock.advance(5.0)
        rest_lat, rest_lon, _zoom = cam.view()
        assert not cam.moving()
        assert lat == 80.0                # clamped, as the coast clamps
        assert rest_lat == pytest.approx(lat, abs=1e-6)
        assert rest_lon == pytest.approx(lon, abs=1e-6)

    def test_the_destination_wraps_across_the_antimeridian(self):
        cam = self._camera(lat=0.0, lon=179.9, zoom=2.0)
        lat, lon = self._flick(cam, -40, 0)
        cam.clock.advance(5.0)
        rest_lat, rest_lon, _zoom = cam.view()
        assert not cam.moving()
        assert lon < 0                    # over the seam
        assert rest_lat == pytest.approx(lat, abs=1e-6)
        assert rest_lon == pytest.approx(lon, abs=1e-6)

    def test_a_coast_stopped_by_hand_has_no_destination(self):
        cam = self._camera()
        self._flick(cam, -20, 0)
        cam.halt()
        assert cam.coast_destination() is None

    def test_a_flick_is_capped_however_fast_the_hand(self):
        def flick(cols):
            cam = self._camera(lon=0.0)
            cam.press()
            cam.drag(0, 0)
            cam.clock.advance(0.05)
            cam.drag(-cols, 0)
            cam.release()
            return cam, abs(cam._coast[1]) * math.cos(math.radians(cam.lat))

        gentle, gentle_speed = flick(8)
        hurled, hurled_speed = flick(4000)
        ceiling = COAST_CEILING * gentle.zoom
        assert gentle_speed < ceiling          # under the cap, untouched
        assert hurled_speed == pytest.approx(ceiling)

    def test_halt_stops_everything_but_keeps_the_view(self):
        cam = self._camera()
        cam.fly_to(44.0, -71.0, 0.5)
        cam.clock.advance(0.1)
        lat, lon, zoom = cam.view()
        cam.halt()
        assert not cam.moving()
        assert cam.view() == (lat, lon, zoom)


class TestTicker:
    def test_the_ticker_wakes_the_loop_and_stops_at_rest(self, monkeypatch):
        woke = []
        monkeypatch.setattr(_maps_live, "_nudge_repaint",
                            lambda: woke.append(1))
        monkeypatch.setattr(_maps_live.time, "sleep", lambda s: None)
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        # the camera is moving, so the ticker keeps asking; once a
        # frame has advanced it past the ease, the next tick returns
        app.camera.clock.advance(ZOOM_EASE + 0.01)
        app.camera.view()
        app._tick()
        assert woke == [1] and not app.camera.moving()

    def test_the_ticker_parks_when_a_hand_takes_the_map(self, monkeypatch):
        # a drag repaints on its own events; the ticker would only
        # send the same frame again between them
        woke = []
        monkeypatch.setattr(_maps_live, "_nudge_repaint",
                            lambda: woke.append(1))
        monkeypatch.setattr(_maps_live.time, "sleep", lambda s: None)
        app = make(zoom=1.0)
        app.zoom_to(2.0)
        app.on_drag(1, 0, False)
        app._tick()
        assert woke == [1] and app.camera.dragging()

    def test_the_ticker_is_started_once_while_it_lives(self, monkeypatch):
        app = make(zoom=1.0)
        live = [True]
        monkeypatch.setattr(app, "_ticker",
                            types.SimpleNamespace(is_alive=lambda: live[0]))
        app.zoom_to(2.0)
        assert FakeThread.started == []     # one is already up
        live[0] = False
        app.zoom_to(4.0)
        assert [t.target for t in FakeThread.started] == [app._tick]


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
        from linecast._maps.style import z_eff
        assert seen == dict(lat=43.68, lon=-70.37, z=int(z_eff(bbox, HC)),
                            lang="en")


class TestStartupPrune:
    """Maps sweeps its tile cache before the session adds to it."""

    def _argv(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["linecast-maps", *args])

    def test_the_sweep_runs_before_anything_is_fetched(self, monkeypatch):
        from linecast._maps import tile_cache

        calls = []

        class Bail(Exception):
            pass

        def bail(*a, **k):
            calls.append("resolve")
            raise Bail

        self._argv(monkeypatch)
        monkeypatch.setattr(tile_cache, "prune_maps_cache",
                            lambda *a, **k: calls.append("prune"))
        monkeypatch.setattr(_maps_live, "resolve_location", bail)

        with pytest.raises(Bail):
            _maps_live.main()

        assert calls == ["prune", "resolve"]

    def test_search_adds_no_tiles_so_it_does_not_wait(self, monkeypatch):
        from linecast._maps import tile_cache
        from linecast._weather import sources

        calls = []
        self._argv(monkeypatch, "--search", "leith")
        monkeypatch.setattr(tile_cache, "prune_maps_cache",
                            lambda *a, **k: calls.append("prune"))
        monkeypatch.setattr(sources, "_search_locations",
                            lambda *a, **k: calls.append("search"))

        _maps_live.main()

        assert calls == ["search"]
