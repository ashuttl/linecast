"""The live map: what runs when you type `maps`.

main() settles the arguments, resolves the location and the --to and
--from endpoints, then puts a MapApp on screen.  --print renders once
and exits.  MapApp is the view's hands: its state is the camera — the
centre, the zoom and whatever motion they are in — plus the mode, the
toggles and the search and directions panels; its methods are the
hooks live_loop calls — zoom, drag, wheel, the keys, the clicks — and
render, which draws the frame through render_map.  Everything drawn is
in maps; everything fetched is in views; the easing and the
flight path are in _maps_motion.
"""

import math
import sys
import threading
import time

from linecast._maps import globe as _globe
from linecast._maps import globe_now
from linecast._maps import route as _maps_route
from linecast._maps import style
from linecast._maps import ui
from linecast._maps import views as _maps_views
from linecast._geo import wrap_lon
from linecast._live import LiveApp, nudge as _nudge_repaint, print_frame
from linecast._location import country_for_defaults, resolve_location
from linecast._maps.i18n import ms
from linecast._maps.motion import Flight, ease_in_out, lon_delta, lon_span
from linecast._maps.search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast import _vtiles
from linecast._maps.views import _zoom_hold, globe_warm, warm_globe_texture
from linecast._radar.render import bbox_for
from linecast._runtime import RuntimeConfig, log_failure, maps_parser, set_current
from linecast.maps import (
    MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP, fit_view, map_cells, max_zoom,
    prefetch_view, render_map,
)


TICK = 1 / 30             # seconds between the ticker's nudges
ZOOM_EASE = 0.28          # seconds for a zoom step or a key pan to land
COAST_HALF_LIFE = 0.22    # seconds for a flick's speed to halve
COAST_REACH = COAST_HALF_LIFE / math.log(2.0)   # a coast's whole run, in
# seconds of its starting speed: the integral of the halving decay
COAST_FLOOR = 0.5         # cells a second below which a coast stops
COAST_CEILING = 4.0       # screens a second a flick may start at
COAST_GRACE = 0.12        # how stale the last motion may be and still coast
TRAIL = 0.25              # seconds of drag the flick's speed is read from
SPIN_RATE = 1.0           # degrees of longitude a second, r
LAT_LIMIT = 80.0          # how far toward a pole the centre may go
PAN_STEP = 0.1            # of the map, per w/a/s/d press


class Camera:
    """Where the map looks, and how it is getting there.

    The centre and the zoom used to be three numbers a key or a drag
    assigned to, and every gesture arrived as a cut.  Here they are the
    state of something in motion: a zoom easing toward its target, a
    coast running out after a flick, a keyboard pan on its way, a
    flight to a searched place, the planet turning.  `view()` gives the
    (lat, lon, zoom) for this instant and advances every motion to it;
    `moving()` says whether the ticker should keep waking the loop.
    Nothing here paints or fetches, and nothing here reads the
    terminal.  The clock is an attribute so a test can turn it by hand.

    The ground the camera moves over is the renderer's: a column is
    `lon_span`'s share of the window, which asks bbox_for rather than
    assuming a cell twice as tall as it is wide, and the zoom is
    clamped to the same ceiling the keys walk to.
    """

    def __init__(self, lat, lon, zoom, clock=time.monotonic):
        self.lat, self.lon, self.zoom = lat, lon, zoom
        self.clock = clock
        self.gw, self.hc = 80, 22         # the map's cells, from the app
        self.zoom_min, self.zoom_max = MIN_ZOOM_DEG, MAX_ZOOM_DEG
        self.spinning = False
        self._drag_base = None            # (lat, lon) at the press
        self._trail = []                  # (time, lat, lon) through the drag
        self._coast = None                # (vlat, vlon, last time)
        self._zoom = None                 # (from, to, anchor, started)
        self._pan = None                  # (from, to, started)
        self._flight = None               # (Flight, started)
        self._spin_mark = None            # clock at the last spin step

    # -- reading ---------------------------------------------------------
    def moving(self):
        """Whether the view is still changing of its own accord."""
        return bool(self._coast or self._zoom or self._pan or self._flight
                    or self.spinning)

    def dragging(self):
        return self._drag_base is not None

    def coast_destination(self):
        """(lat, lon) a running coast will come to rest at, or None.

        The speed halves on a fixed clock, so the ground still to cover
        is the integral of that decay — a finite distance, known the
        moment the flick leaves the hand.  _advance_coast takes exactly
        this much and no more, the tail included, so the view named
        here is the view the coast stops on and can be fetched now.
        A coast cut short — by a hand, a key, a panel — never reaches
        it, and what was fetched is simply a view nobody asked for.
        """
        if self._coast is None:
            return None
        vlat, vlon, _last = self._coast
        return (self._clamp_lat(self.lat + vlat * COAST_REACH),
                wrap_lon(self.lon + vlon * COAST_REACH))

    def heading(self):
        """(east, south) the view is travelling, each -1, 0 or 1.

        Which side of the next view is built deep and which shallow: a
        view is built a margin wider than the window shows, and the
        margin is worth most where the reader is going
        (_maps_overscan.plan).  A drag reads its own trail, a coast
        what is left of its velocity, a keyed pan the ground it has
        still to cover; a view at rest is going nowhere and takes its
        margin evenly.  Under a cell either way is a hand shaking
        rather than a view moving, and reads as still.
        """
        if self._coast is not None:
            vlat, vlon, _last = self._coast
        elif self._drag_base is not None and len(self._trail) >= 2:
            (_t0, lat0, lon0), (_t1, lat1, lon1) = self._trail[0], self._trail[-1]
            vlat, vlon = lat1 - lat0, lon_delta(lon0, lon1)
        elif self._pan is not None:
            _from, (to_lat, to_lon), _started = self._pan
            vlat, vlon = to_lat - self.lat, lon_delta(self.lon, to_lon)
        else:
            return (0, 0)
        cell_lat = self.zoom / self.hc
        cell_lon = self._span(self.zoom, self.lat) / self.gw
        east = 0 if abs(vlon) < cell_lon else (1 if vlon > 0 else -1)
        # a rising latitude is the view climbing the screen, which is
        # north, which is up
        south = 0 if abs(vlat) < cell_lat else (-1 if vlat > 0 else 1)
        return (east, south)

    def _span(self, zoom, lat):
        return lon_span(lat, zoom, self.gw, self.hc)

    def _clamp_zoom(self, zoom):
        return max(self.zoom_min, min(self.zoom_max, zoom))

    def _clamp_lat(self, lat):
        return max(-LAT_LIMIT, min(LAT_LIMIT, lat))

    def view(self):
        """(lat, lon, zoom) for now, every motion advanced to it.

        The order is the one a reader would compose them in: a flight
        overrides everything, a coast and a keyed pan move the centre,
        an anchored zoom has the last word on where the centre must be
        for the ground under the pointer to stay put, and the spin adds
        its degree a second on top of whatever is left.
        """
        now = self.clock()
        if self._flight is not None:
            flight, started = self._flight
            t = now - started
            self.lat, self.lon, zoom = flight.at(t)
            self.zoom = self._clamp_zoom(zoom)
            if t >= flight.duration:
                self._flight = None
        if self._coast is not None:
            self._advance_coast(now)
        if self._pan is not None:
            (from_lat, from_lon), (to_lat, to_lon), started = self._pan
            s = (now - started) / ZOOM_EASE
            if s >= 1.0:
                self.lat, self.lon = to_lat, to_lon
                self._pan = None
            else:
                e = ease_in_out(s)
                self.lat = from_lat + (to_lat - from_lat) * e
                self.lon = wrap_lon(from_lon + lon_delta(from_lon, to_lon) * e)
        if self._zoom is not None:
            from_zoom, to_zoom, anchor, started = self._zoom
            s = (now - started) / ZOOM_EASE
            if s >= 1.0:
                zoom = to_zoom
                self._zoom = None
            else:
                # eased in log space: a step from 8° to 4° and one from
                # 4° to 2° are the same gesture, and should look it
                e = ease_in_out(s)
                zoom = math.exp(math.log(from_zoom)
                                + (math.log(to_zoom) - math.log(from_zoom)) * e)
            self._apply_zoom(zoom, anchor)
        if self.spinning:
            if not _globe.is_globe(self.zoom, self.lat):
                # a zoom has crossed back inside the hand-off, and
                # there is no planet left to turn
                self.spinning = False
                self._spin_mark = None
            else:
                if self._spin_mark is not None and self._drag_base is None:
                    self.lon = wrap_lon(
                        self.lon - SPIN_RATE * (now - self._spin_mark))
                self._spin_mark = now
        return self.lat, self.lon, self.zoom

    def _advance_coast(self, now):
        """Carry the flick's speed forward, and let it run out."""
        vlat, vlon, last = self._coast
        dt = now - last
        decay = 0.5 ** (dt / COAST_HALF_LIFE)
        # the integral of the decaying speed across the step, so the
        # ground covered is the same however often the camera is asked
        step = COAST_REACH * (1.0 - decay)
        self.lat = self._clamp_lat(self.lat + vlat * step)
        self.lon = wrap_lon(self.lon + vlon * step)
        vlat, vlon = vlat * decay, vlon * decay
        floor = COAST_FLOOR * self.zoom / self.hc
        if math.hypot(vlat, vlon * math.cos(math.radians(self.lat))) < floor:
            # Slower than the eye follows.  What is left of the decay
            # is a fraction of a cell, and the coast takes it now
            # rather than dropping it: it lands on the centre
            # coast_destination() named at the release, which is the
            # view already fetched for it, rather than a hair short of
            # it — which at street zoom is another window, and another
            # fetch, for a stop the reader cannot see.
            self.lat = self._clamp_lat(self.lat + vlat * COAST_REACH)
            self.lon = wrap_lon(self.lon + vlon * COAST_REACH)
            self._coast = None
        elif abs(self.lat) >= LAT_LIMIT:
            self._coast = None   # ashore
        else:
            self._coast = (vlat, vlon, now)

    def _apply_zoom(self, zoom, anchor):
        """Set the zoom, keeping the anchored ground under its cell."""
        if anchor is not None:
            plat, plon, fx, fy = anchor
            lat_c = self._clamp_lat(plat - zoom * (0.5 - fy))
            self.lat = lat_c
            self.lon = wrap_lon(plon - self._span(zoom, lat_c) * (fx - 0.5))
        self.zoom = zoom

    # -- the hand --------------------------------------------------------
    def press(self):
        """A hand on the map: whatever it was doing stops, and every
        motion from here is measured from where it now is."""
        self._drag_base = (self.lat, self.lon)
        self._trail = []
        self._coast = self._zoom = self._pan = self._flight = None

    def _centre_at(self, dcol, drow):
        base_lat, base_lon = self._drag_base
        lat = self._clamp_lat(base_lat + drow * self.zoom / self.hc)
        lon = wrap_lon(base_lon
                       - dcol * self._span(self.zoom, base_lat) / self.gw)
        return lat, lon

    def _mark(self, lat, lon):
        now = self.clock()
        self._trail.append((now, lat, lon))
        self._trail = [p for p in self._trail if now - p[0] < TRAIL]

    def drag(self, dcol, drow):
        """The pointer is this far from the press, in cells: be there
        now.  The globe's idiom — the geography turns under the hand."""
        lat, lon = self._centre_at(dcol, drow)
        changed = (self.lat, self.lon) != (lat, lon)
        self.lat, self.lon = lat, lon
        self._mark(lat, lon)
        return changed

    def track(self, dcol, drow):
        """The same motion noted but not taken: the flat map shows the
        last frame shifted while the hand is down and moves its centre
        on the release, but the flick that may follow needs the speed,
        so the trail is kept either way."""
        self._mark(*self._centre_at(dcol, drow))

    def settle(self, dcol, drow):
        """Where the hand let go, taken as the centre.  Not marked: a
        release is not a motion, and counting it would read a hand
        that had already come to rest as a flick."""
        lat, lon = self._centre_at(dcol, drow)
        changed = (self.lat, self.lon) != (lat, lon)
        self.lat, self.lon = lat, lon
        return changed

    def release(self):
        """The button is up; a flick coasts, a hand at rest stops dead."""
        if self._drag_base is None:
            return False
        self._drag_base = None
        trail, self._trail = self._trail, []
        now = self.clock()
        if len(trail) >= 2 and now - trail[-1][0] < COAST_GRACE:
            (t0, lat0, lon0), (t1, lat1, lon1) = trail[0], trail[-1]
            dt = t1 - t0
            if dt >= 0.03:
                vlat = (lat1 - lat0) / dt
                vlon = lon_delta(lon0, lon1) / dt
                cos_lat = math.cos(math.radians(self.lat))
                speed = math.hypot(vlat, vlon * cos_lat)
                # a hand leaves the trackpad faster than any map should
                # move; past a few screens a second it reads as a fault
                ceiling = COAST_CEILING * self.zoom
                if speed > ceiling:
                    vlat, vlon = vlat * ceiling / speed, vlon * ceiling / speed
                    speed = ceiling
                if speed >= COAST_FLOOR * self.zoom / self.hc:
                    self._coast = (vlat, vlon, now)
        return True

    # -- the keys and the panels -----------------------------------------
    def zoom_to(self, target, at=None):
        """Ease the zoom to `target`, about the ground fraction `at`
        ((fx, fy) of the map, or None for the centre).  Truthy when
        anything will move."""
        target = self._clamp_zoom(target)
        if abs(target - self.zoom_heading()) < 1e-12:
            return False
        anchor = None
        lat_end = self.lat
        # anchored zoom is a flat-map identity; on the globe, zoom
        # about the centre instead
        if at is not None and not _globe.is_globe(self.zoom, self.lat):
            fx, fy = at
            plat = self.lat + self.zoom * (0.5 - fy)
            plon = self.lon + self._span(self.zoom, self.lat) * (fx - 0.5)
            anchor = (plat, plon, fx, fy)
            lat_end = self._clamp_lat(plat - target * (0.5 - fy))
        self._coast = self._flight = None
        if (_globe.is_globe(self.zoom, self.lat)
                != _globe.is_globe(target, lat_end)):
            # The hand-off is crossed in one cut.  Neither side can
            # stand in for the other — a globe cannot be re-projected
            # into a flat window, nor a flat view onto the sphere — so
            # every frame of an ease across it would be blank.  About
            # the centre, as the anchor is a flat-map identity.
            self._zoom = self._pan = None
            self.zoom = target
            return True
        if anchor is not None:
            self._pan = None      # an anchored zoom owns the centre
        self._zoom = (self.zoom, target, anchor, self.clock())
        return True

    def zoom_heading(self):
        """Where the zoom is going: a run of taps compounds rather than
        each restarting from wherever the last one had got to."""
        return self._zoom[1] if self._zoom is not None else self.zoom

    def pan_by(self, dcol, drow):
        """Ease the centre by a number of cells.  Pressed again before
        the last one lands the steps add up, so holding `d` walks east
        instead of shuffling in place."""
        self._coast = self._flight = None
        self.spinning = False
        from_lat, from_lon = self.lat, self.lon
        base_lat, base_lon = (self._pan[1] if self._pan is not None
                              else (from_lat, from_lon))
        to_lat = self._clamp_lat(base_lat + drow * self.zoom / self.hc)
        to_lon = wrap_lon(base_lon
                          - dcol * self._span(self.zoom, base_lat) / self.gw)
        self._pan = ((from_lat, from_lon), (to_lat, to_lon), self.clock())
        return True

    def fly_to(self, lat, lon, zoom):
        """Fly to a view: out, across and in, along van Wijk's path."""
        zoom = self._clamp_zoom(zoom)
        lat = self._clamp_lat(lat)
        lon = wrap_lon(lon)
        self._coast = self._zoom = self._pan = None
        self.spinning = False
        if (abs(lat - self.lat) < 1e-9 and abs(lon_delta(self.lon, lon)) < 1e-9
                and abs(zoom - self.zoom) < 1e-12):
            return False
        self._flight = (Flight(self.lat, self.lon, self.zoom, lat, lon, zoom),
                        self.clock())
        return True

    def flying(self):
        return self._flight is not None

    def destination(self):
        """Where the flight will land, or None when not flying."""
        if self._flight is None:
            return None
        flight = self._flight[0]
        return flight.lat1, flight.lon1, flight.w1

    def flight_progress(self):
        """How far through the flight, 0 to 1; 1 when not flying."""
        if self._flight is None:
            return 1.0
        flight, started = self._flight
        return min(1.0, (self.clock() - started) / flight.duration)

    def jump_to(self, lat, lon, zoom):
        """Be there now, no motion: an opening frame has nowhere to
        come from."""
        self.halt()
        self.lat = self._clamp_lat(lat)
        self.lon = wrap_lon(lon)
        self.zoom = self._clamp_zoom(zoom)

    def halt(self):
        """Stop everything the camera is doing of its own accord: a
        panel opening in front of the map ends the motion behind it."""
        self._coast = self._zoom = self._pan = self._flight = None
        self.spinning = False
        self._spin_mark = None

    def spin(self, on):
        self.spinning = bool(on)
        self._spin_mark = self.clock() if on else None


class MapApp(LiveApp):
    """The live map: its state, and the hooks that move it.

    The constructor takes what main() has already settled — the
    runtime, the home point and its name, the opening zoom and view,
    whether the sky is on, the travel profile and the --from and --to
    endpoints — and starts nothing: no thread, no request.  run() seeds
    the route request, starts the sky's clock and hands the app to the
    loop; stop() parks the camera.

    The centre and the zoom live in the camera, and `lat`, `lon` and
    `zoom` here read and write it.  One ticker thread wakes the loop at
    30 Hz for as long as anything is in motion and exits when the
    camera comes to rest — the loop paces itself to the terminal's
    acknowledgements, so the nudges coalesce and a slow terminal is
    never handed more frames than it can take.
    """

    interval = 3600  # elevation doesn't change; repaint on input only
    mouse = True

    help_view = 'maps'

    def __init__(self, runtime, lat, lon, location_name, zoom, view, sky,
                 profile, origin=None, dest=None, fit=False):
        self.runtime = runtime
        self.home = (lat, lon)      # the marker
        self.location_name = location_name
        self.camera = Camera(lat, lon, zoom)
        self.pan_preview = (0, 0)
        # whether this drag shows the last frame shifted rather than
        # moving the camera: a globe that is not warm, and nothing else
        self._drag_shift = False
        self._dragged = False      # whether this gesture has moved at all
        self.view = view
        self.show_labels = True
        self.sun = sky          # S: daylight shading + night city lights
        self.clouds = sky       # c: this hour's cloud cover
        self.search = ui.SearchState()
        self.routes = ui.RouteState(profile=profile, home=(lat, lon))
        if origin is not None:
            self.routes.set_origin(origin.lat, origin.lon, origin.name)
        if dest is not None:
            self.routes.select(dest.lat, dest.lon, dest.name)
        self._ticker = None
        self._lock = threading.Lock()
        self._running = True
        self._help = None          # the loop's help panel, once it is made
        self._destination = None   # a flight's end, until it is asked for
        self._fit()
        # --from and --to without --location: open on the whole route.
        # The endpoints frame the view now, while the route is still
        # on its way; the route itself reframes it once, when it
        # lands, unless the reader has moved in the meantime.
        self.fit_view = None
        if fit and origin is not None and dest is not None:
            self.camera.jump_to(*fit_view(
                [(origin.lat, origin.lon), (dest.lat, dest.lon)], *map_cells()))
            self.fit_view = (self.lat, self.lon, self.zoom)

    # -- the view centre and zoom, on the camera -------------------------
    @property
    def lat(self):
        return self.camera.lat

    @lat.setter
    def lat(self, value):
        self.camera.lat = value

    @property
    def lon(self):
        return self.camera.lon

    @lon.setter
    def lon(self, value):
        self.camera.lon = value

    @property
    def zoom(self):
        return self.camera.zoom

    @zoom.setter
    def zoom(self, value):
        self.camera.zoom = value

    def _fit(self):
        """Tell the camera the map's size and the zoom ceiling it sets."""
        gw, hc = map_cells()
        cam = self.camera
        cam.gw, cam.hc = gw, hc
        cam.zoom_max = max_zoom(gw, hc)
        return gw, hc

    # -- the ticker ------------------------------------------------------
    def _wake(self):
        """Start the ticker, if something is moving and it is not up."""
        with self._lock:
            if self._ticker is None or not self._ticker.is_alive():
                self._ticker = threading.Thread(target=self._tick, daemon=True)
                self._ticker.start()

    def _tick(self):
        """Wake the loop thirty times a second while the camera moves.

        It asks for frames rather than making them: the loop holds each
        one until the terminal says it read the last, so a terminal
        that cannot keep up simply gets fewer, and a nudge that arrives
        during the wait is absorbed into the frame already coming.
        """
        while self._running:
            time.sleep(TICK)
            _nudge_repaint()
            if not self.camera.moving():
                return

    def cloud_tick(self):
        """The sky's slow heartbeat.

        Every half hour while the sky is switched on: the newest
        mosaic frame if clouds are showing, the sun where it now
        is, one repaint.  Never an animation — a view left running
        all evening simply stays true.
        """
        while True:
            time.sleep(1800)
            if not (self.sun or self.clouds):
                continue
            if self.clouds:
                gw, hc = map_cells()
                try:
                    globe_now.refresh(self.zoom, hc * 4)
                except Exception as exc:
                    log_failure("maps/clouds", "scheduled refresh", exc,
                                fallback="previous canvas kept")
            _nudge_repaint()

    # -- the keys --------------------------------------------------------
    def zoom_to(self, new_zoom, at=None):
        """Ease to a clamped zoom, keeping the point under `at` fixed.

        `at` is a terminal (col, row) in the same 1-based frame as
        mouse_pos; None zooms about the view centre.  Anchoring is
        the difference between a wheel that explores and one that
        makes you chase the thing you were looking at.
        """
        gw, hc = self._fit()
        frac = None
        if at is not None:
            pcol, prow = at[0] - 1, at[1] - 2
            if 0 <= pcol < gw and 0 <= prow < hc:
                frac = ((pcol + 0.5) / gw, (prow + 0.5) / hc)
        if not self.camera.zoom_to(new_zoom, frac):
            return False
        _zoom_hold.hold()
        heading = self.camera.zoom_heading()
        if _globe.is_globe(heading, self.camera.lat):
            warm_globe_texture(heading, hc, self.view == "street")
        if self.camera.moving():
            self._wake()
        return True

    def on_action(self, key):
        if key in ('w', 'a', 's', 'd'):
            gw, hc = self._fit()
            dcol, drow = {'w': (0, hc * PAN_STEP), 'a': (gw * PAN_STEP, 0),
                          's': (0, -hc * PAN_STEP),
                          'd': (-gw * PAN_STEP, 0)}[key]
            self.camera.pan_by(dcol, drow)
            self._wake()
            return True
        if key == '+':
            return self.zoom_to(self.camera.zoom_heading() / ZOOM_STEP)
        if key == '-':
            return self.zoom_to(self.camera.zoom_heading() * ZOOM_STEP)
        if key == 'v':
            nxt = style.MODES.index(self.view) + 1
            self.view = style.MODES[nxt % len(style.MODES)]
            return True
        if key == 'l':
            self.show_labels = not self.show_labels
            return True
        if key == 'S':
            self.sun = not self.sun
            return True
        if key == 'c':
            self.clouds = not self.clouds
            return True
        if key == 'r':
            # The screensaver: the planet turns while you watch, about
            # a degree a second, six minutes to the revolution, riding
            # the same clock every other motion does.  Only a warm
            # globe spins — until the planet is warm there is nothing
            # to re-project without blocking on the network.
            if self.camera.spinning:
                self.camera.spin(False)
                return False
            gw, hc = self._fit()
            if (not _globe.is_globe(self.zoom, self.lat)
                    or not globe_warm(self.zoom, hc, self.view == "street")):
                return False
            self.camera.spin(True)
            self._wake()
            return False  # the first tick is the repaint
        return False

    def on_wheel(self, direction, col, row):
        heading = self.camera.zoom_heading()
        return self.zoom_to(heading * (ZOOM_STEP if direction < 0
                                       else 1.0 / ZOOM_STEP),
                            at=(col, row))

    # -- flights ---------------------------------------------------------
    def fly_to(self, result):
        """Fly to a search result and frame it.

        No mode change: searching an address in terrain mode gives
        terrain at that address.  The flight is what keeps the reader
        oriented — a cut to somewhere else is a reader who has to work
        out where they now are — and the destination starts loading
        from the descent, so the landing is usually on the real map.
        """
        gw, hc = self._fit()
        self._fly(result.lat, result.lon,
                  max(MIN_ZOOM_DEG,
                      min(max_zoom(gw, hc), fly_to_zoom(result, (hc * 2) / gw))))

    def fly_to_step(self, step):
        """Frame one maneuver: centre on it, zoomed to roughly the
        distance the step covers, so a highway leg shows its whole
        run and a city turn shows its corner."""
        loc = step.get("location")
        if loc is None:
            return
        span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
        gw, hc = self._fit()
        self._fly(loc[1], loc[0],
                  max(MIN_ZOOM_DEG, min(max_zoom(gw, hc), span)))

    def _fly(self, lat, lon, zoom):
        if self.camera.fly_to(lat, lon, zoom):
            self._destination = self.camera.destination()
            self._wake()

    def _prefetch_if_descending(self):
        """Ask for the destination once the flight is over the top.

        Not at take-off: the loaders are pure Python for seconds at a
        time, and with the interpreter lock to share they would take
        the frames' turn through the whole climb — the part of the
        flight where the picture is at its best.
        """
        if self._destination is None:
            return
        if not self.camera.flying():
            # cut short by a key, a press or a panel, or already landed
            # before a frame saw the descent: the view at rest fetches
            # for itself, and a view nobody is going to is not fetched
            self._destination = None
            return
        if self.camera.flight_progress() < 0.5:
            return
        lat, lon, zoom = self._destination
        self._destination = None
        gw, hc = map_cells()
        prefetch_view(lat, lon, zoom, self.view, gw, hc, self.runtime.lang,
                      marker=self.home)

    def _prefetch_coast(self):
        """Ask for where a flick will stop, the moment it is let go.

        A coast's end is a destination like a flight's, and known
        earlier: at the release, not over the top.  It is the one view
        in the whole glide the reader will actually stop on, so it
        goes to the network at once, past the motion gate, and the
        frames in between are free to ask for their own.  A coast the
        hand interrupts leaves the fetch running; it lands in the
        cache, where the next view of that window will find it.
        """
        dest = self.camera.coast_destination()
        if dest is None or _globe.is_globe(self.zoom, dest[0]):
            return   # the globe paints every frame from a warm planet
        gw, hc = map_cells()
        prefetch_view(dest[0], dest[1], self.zoom, self.view, gw, hc,
                      self.runtime.lang, marker=self.home)

    def help_panel(self):
        from linecast._help import HelpPanel
        self._help = HelpPanel(
            'maps', self.runtime.lang, content=lambda cols, rows:
            ui.help_rows(cols, rows, self.runtime.lang,
                               self.routes.route is not None))
        return self._help

    def intercept(self, action):
        """Maps owns dispatch: the search panel eats every key while
        it is open, the directions panel takes the arrows, and
        nothing else here consumes one."""
        search, routes = self.search, self.routes
        if search.open:
            gw, hc = map_cells()
            bbox = bbox_for(self.lat, self.lon, self.zoom, gw, hc)
            z = int(style.z_eff(bbox, hc))
            return search.handle(action, self.lat, self.lon, z,
                                 self.runtime.lang)
        if routes.panel:
            # The directions panel: arrows walk the maneuvers and
            # the map flies along; the field rows name their own
            # keys, and `D` — its opening job done — edits the
            # destination its row promises.  Everything else
            # (zoom, v, n) still reaches the map underneath.
            if action in ('escape', 'quit'):
                return routes.close_panel()
            if action in ('fwd', 'back', 'key:enter'):
                # live_loop's time-scrub names: 'back' is the down
                # arrow, which walks down the list — onward through
                # the maneuvers.  Enter steps onward too.
                step = routes.step_move(
                    -1 if action == 'fwd' else 1)
                if step is not None:
                    self.fly_to_step(step)
                return True
            if action == 'key:D':
                search.start("route")
                return True
        if action == 'key:/':
            search.start()
            return True
        if action == 'key:D':
            if routes.press() == "search":
                search.start("route")
            return True
        if action == 'open':
            # o: re-point the origin, panel open or not.
            search.start("origin")
            return True
        if action == 'key:p':
            return routes.cycle_profile()
        if action == 'reset':
            # n / space: the one deliberately destructive key.
            routes.clear()
            return False        # and the loop still recentres
        return False

    def on_click(self, col, row):
        """A click on the directions panel acts on the row it hit —
        fields open their search or cycle the mode, a step takes
        the focus and the map flies to it.  Anywhere else, a click
        stays what it always was: nothing."""
        search, routes = self.search, self.routes
        if search.open or not routes.panel or routes.panel_rows is None:
            return False
        width, acts = routes.panel_rows
        act = acts.get(row) if col <= width else None
        if act == 'from':
            search.start("origin")
        elif act == 'to':
            search.start("route")
        elif act == 'mode':
            routes.cycle_profile()
        elif isinstance(act, tuple):
            routes.step = act[1]
            self.fly_to_step(routes.route.steps[act[1]])
        else:
            return False
        return True

    def on_drag(self, dcol, drow, done):
        """The ground follows the hand; let go moving and it coasts.

        Which idiom a drag uses is settled at the press and kept for
        its whole length.  Nearly every drag now recentres the view
        from the drag-start centre on every motion event, so the drag
        *is* the pan rather than a shifted snapshot of one: a warm
        globe turns the geography under the cursor, and a flat view is
        built a margin wider than the window, so the window at the new
        centre is a crop of what is already in hand — the real map,
        painted to every edge, rather than the last one dragged clear
        of its own picture.

        The one idiom left that cannot is a globe not yet warm: there
        is no re-projection of a sphere about a moved centre, so it
        shows the last frame shifted and takes its centre when the hand
        lets go.
        """
        gw, hc = self._fit()
        cam = self.camera
        if not cam.dragging():
            warm = (_globe.is_globe(cam.zoom, cam.lat)
                    and globe_warm(cam.zoom, hc, self.view == "street"))
            if done and warm and not (self.pan_preview[0]
                                      or self.pan_preview[1]):
                return False  # a click, not a drag
            self._drag_shift = (_globe.is_globe(cam.zoom, cam.lat)
                                and not warm)
            self._dragged = False
            cam.press()
        if not self._drag_shift:
            if done:
                # a release repaints when this gesture was a drag at
                # all, even one that came back to where it started: the
                # camera has moved away and back, and the frame under
                # it is not the frame the press began on
                moved = cam.settle(dcol, drow) or self._dragged
                self._dragged = False
                cam.release()
                if cam.moving():
                    self._prefetch_coast()
                    self._wake()
                return bool(moved)
            self._dragged = True
            return cam.drag(dcol, drow)
        if not done:
            cam.track(dcol, drow)
            changed = self.pan_preview != (dcol, drow)
            self.pan_preview = (dcol, drow)
            return changed
        had_preview = self.pan_preview[0] or self.pan_preview[1]
        self.pan_preview = (0, 0)
        changed = cam.settle(dcol, drow)
        cam.release()
        if cam.moving():
            self._prefetch_coast()
            self._wake()
        return bool(changed or had_preview)

    def text_mode(self):
        return self.search.open

    def render(self, mouse_pos=None, **_):
        search, routes = self.search, self.routes
        if search.open or (self._help is not None and self._help.open):
            # something is in front of the map now; a view still
            # coasting behind a field you are typing into is noise
            self.camera.halt()
        # The motions are advanced first, so everything below reads the
        # view as this frame will draw it rather than as the last one
        # left it.
        gw, hc = self._fit()
        self.camera.view()
        # A search committed from a background reply lands here: the
        # worker cannot move the view itself, so it parks the result
        # and the next repaint applies it.
        hit = search.take_chosen()
        if hit is not None:
            self.fly_to(hit)
            if search.purpose == "route":
                routes.select(hit.lat, hit.lon, hit.name)
                routes.request()
            elif search.purpose == "origin":
                routes.set_origin(hit.lat, hit.lon, hit.name)
                if routes.dest is not None:
                    routes.request()
        # The opening route lands from its worker: frame it, once,
        # if the view is still where the endpoints put it.  A jump,
        # not a flight — this is still the opening frame.
        if self.fit_view is not None and routes.route is not None:
            if (self.lat, self.lon, self.zoom) == self.fit_view:
                self.camera.jump_to(*fit_view(
                    [(la, lo) for lo, la in routes.route.coords],
                    *map_cells()))
            self.fit_view = None
        lat, lon, zoom = self.camera.lat, self.camera.lon, self.camera.zoom
        self._prefetch_if_descending()
        moving = self.camera.moving() or self.camera.dragging()
        # The loaders' own path is closed while the view is passing
        # through; the frames in between are cut from the newest real
        # one (maps._reproject_street, maps._reproject_terrain), and
        # one window at a time is still built behind them — except
        # under a flight, whose frames are the picture and whose
        # destination is already on its way, and under a hand.
        #
        # A hand for the same reason as a flight, and a better one: the
        # frames are what the reader is steering, and a build is a
        # second of pure Python holding the interpreter lock, which
        # measured at 160x45 takes a drag from thirty frames a second
        # to three.  A drag has the margin to pan inside and nothing to
        # wait for — it ends either at a stop, which fetches its own
        # view, or in a coast, whose destination goes to the network at
        # the release.
        _maps_views.hold_motion(moving, passing=not (self.camera.flying()
                                                     or self.camera.dragging()))
        # A warm globe repaints synchronously, moving or at rest: the
        # frame is a few hundredths of a second of arithmetic, and the
        # alternative is a blank disk — between frames while it turns,
        # and once more where a coast runs out, since the resting
        # centre is never quite the last moving one.
        sync = (_globe.is_globe(zoom, lat)
                and globe_warm(zoom, hc, self.view == "street"))
        return render_map(
            lat, lon, self.location_name, zoom,
            marker=self.home, runtime=self.runtime, block=sync,
            pan_offset=self.pan_preview,
            mouse_pos=None if moving else mouse_pos,
            view=self.view, search=search,
            route=routes.route, dest=routes.dest,
            origin=routes.origin, directions=routes,
            note=ui.route_note(routes, self.runtime.lang),
            show_labels=self.show_labels,
            sun=self.sun, clouds=self.clouds,
            motion=self.camera.heading())

    def run(self):
        if self.routes.dest is not None:
            self.routes.request()
        threading.Thread(target=self.cloud_tick, daemon=True).start()
        super().run()

    def stop(self):
        self._running = False   # the loop is over; let the ticker park
        self.camera.halt()
        _maps_views.hold_motion(False)
        # tile workers are not daemons, so a queue of prefetched tiles
        # would be a wait between q and the shell
        _vtiles.shutdown()


def main():
    args = maps_parser().parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)
    # --view now is launch sugar, not a register: the terrain planet
    # with the sky switched on — daylight (s) and clouds (c), both
    # toggleable once inside
    sky = args.view == "now"
    if sky:
        args.view = "terrain"
        if args.zoom is None:
            args.zoom = max_zoom(*map_cells())
    # a route given by both ends and no --location opens on the whole
    # route, unless a --zoom (or the planet of --view now) pins the scale
    fit = (args.location is None and args.zoom is None
           and args.from_ is not None and args.to is not None)
    if args.zoom is None:
        args.zoom = style.DEFAULT_ZOOM[args.view]

    if args.profile not in _maps_route.PROFILES:
        print(f"maps: invalid profile '{args.profile}' — choose "
              f"{', '.join(_maps_route.PROFILES)}", file=sys.stderr)
        sys.exit(2)

    if args.search:
        from linecast._weather.sources import _search_locations
        _search_locations(args.search, lang=runtime.lang)
        return

    from linecast._textwidth import calibrate_from_terminal
    calibrate_from_terminal()

    # Sweep the tile cache before this session adds to it: dead
    # vector-tile versions first, then back under the size cap. Map tiles
    # never go stale, so nothing here goes by age alone. After --search,
    # which adds no tiles and should not wait on a tilejson fetch.
    from linecast._maps.tile_cache import prune_maps_cache
    prune_maps_cache()

    lat, lon, country, location_name = resolve_location(
        args.location, lang=runtime.lang, return_label=True)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    # Re-resolve a countryless first-run runtime consistently with the
    # other views. An explicit location only stands in when the user's own
    # country is not known yet; country_for_defaults keeps that distinction.
    own = country_for_defaults(args.location, country, lat, lon)
    if own:
        runtime = RuntimeConfig.from_sources(args, country=own)
        set_current(runtime)

    if not location_name:
        try:
            from linecast._weather.sources import _reverse_geocode
            location_name = _reverse_geocode(lat, lon, lang=runtime.lang)[0] or ""
        except Exception:
            location_name = ""

    # --to and --from resolve through the map's own geocoders, never
    # the weather one: that is settlement-level only and exits the
    # process when the network is down, which is no way to fail a
    # lighthouse.
    def _endpoint(query, flag):
        try:
            hit = resolve_place(query, runtime.lang, near=(lat, lon))
        except SearchUnavailable:
            print(f"maps: could not reach a geocoder for {flag}",
                  file=sys.stderr)
            sys.exit(1)
        if hit is None:
            print(f'No locations matching "{query}".', file=sys.stderr)
            sys.exit(1)
        return hit

    dest = _endpoint(args.to, "--to") if args.to else None
    origin = _endpoint(args.from_, "--from") if args.from_ else None

    if runtime.live:
        MapApp(runtime, lat, lon, location_name, args.zoom, args.view, sky,
               args.profile, origin=origin, dest=dest, fit=fit).run()
    else:
        found = note = None
        start = (origin.lat, origin.lon) if origin else (lat, lon)
        if dest is not None:
            try:
                found = _maps_route.route(args.profile, start,
                                          (dest.lat, dest.lon))
            except _maps_route.NoRoute:
                note = ms('dir_none', runtime.lang)
            except _maps_route.RouteUnavailable:
                note = ms('dir_unavailable', runtime.lang)
        if fit:
            points = ([(la, lo) for lo, la in found.coords] if found is not None
                      else [start, (dest.lat, dest.lon)])
            lat, lon, args.zoom = fit_view(points, *map_cells())
        print_frame(render_map(lat, lon, location_name, args.zoom,
                               runtime=runtime, view=args.view, route=found,
                               dest=(dest.lat, dest.lon) if dest else None,
                               origin=((origin.lat, origin.lon, origin.name)
                                       if origin else None),
                               note=note or "", sun=sky, clouds=sky))
        if found is not None:
            # the turn-by-turn list rides below the map: --print asked
            # for directions, so it gets the directions
            print()
            for line in ui.steps_text(
                    found, runtime.lang,
                    origin_label=origin.name if origin else location_name,
                    dest_label=dest.name):
                print(line)
