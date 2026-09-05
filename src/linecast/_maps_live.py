"""The live map: what runs when you type `maps`.

main() settles the arguments, resolves the location and the --to and
--from endpoints, then puts a MapApp on screen.  --print renders once
and exits.  MapApp is the view's hands: its state is the camera — the
centre, the zoom and whatever motion they are in — plus the mode and
the toggles and the search and directions panels; its methods are the
hooks live_loop calls — zoom, drag, wheel, the keys, the clicks — and
render, which draws the frame through render_map.  Everything drawn
is in maps; everything fetched is in _maps_views; how a frame in
motion is cut from the last real one is in _maps_motion.
"""

import math
import sys
import threading
import time

from linecast import (
    _globe, _globe_now, _maps_motion, _maps_route, _maps_style, _maps_ui,
)
from linecast._geo import wrap_lon
from linecast._live import LiveApp, nudge as _nudge_repaint
from linecast._location import country_for_defaults, resolve_location
from linecast._maps_i18n import ms
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._maps_views import _zoom_hold
from linecast._radar_render import bbox_for
from linecast._radar_ui import _panned_place
from linecast._runtime import RuntimeConfig, log_failure, maps_parser, set_current
from linecast.maps import (
    MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP, map_cells, max_zoom,
    prefetch_view, render_map,
)


TICK = 1 / 30
SWITCH_INTERVAL = 0.001   # seconds between thread switches while moving
ZOOM_EASE = 0.28          # seconds for a zoom step to land
COAST_HALF_LIFE = 0.22    # seconds for a flick's speed to halve
COAST_FLOOR = 0.5         # cells per second below which a coast stops
COAST_CEILING = 4.0       # screens per second a flick may start at
SPIN_RATE = 1.0           # degrees of longitude per second, r
LAT_LIMIT = 80.0          # how far toward a pole the centre may go


class Camera:
    """Where the map looks, and how it is moving.

    The sky's camera, on a map: the centre and the zoom, plus whatever
    motion is under way — a drag in hand, a coast after a flick, a
    zoom easing about its anchor, a flight to a searched place, the
    planet spinning.  `view()` gives the (lat, lon, zoom) for this
    instant and advances the motions to it; `moving()` says whether
    the ticker should keep waking the loop.  The clock is an
    attribute so a test can turn it by hand.
    """

    def __init__(self, lat, lon, zoom, clock=time.monotonic):
        self.lat, self.lon, self.zoom = lat, lon, zoom
        self.clock = clock
        self.gw, self.hc = 80, 22          # the map's cells, from the app
        self.zoom_min, self.zoom_max = MIN_ZOOM_DEG, MAX_ZOOM_DEG
        self.spinning = False
        self._drag_base = None            # (lat, lon) at the press
        self._drag_trail = []             # (time, lat, lon) through the drag
        self._coast = None                # (vlat, vlon, last_time)
        self._zoom = None                 # (from, to, anchor, started)
        self._flight = None               # (Flight, started)
        self._spin_mark = None            # clock at the last spin step

    # -- reading ---------------------------------------------------------
    def moving(self):
        return any((self._coast, self._zoom, self._flight)) or self.spinning

    def dragging(self):
        return self._drag_base is not None

    def _lon_span(self, zoom, lat):
        return zoom * (self.gw / (self.hc * 2)) / math.cos(math.radians(lat))

    def _clamp_zoom(self, zoom):
        return max(self.zoom_min, min(self.zoom_max, zoom))

    def view(self):
        """(lat, lon, zoom) for now, motions advanced."""
        now = self.clock()
        if self._flight is not None:
            flight, started = self._flight
            t = now - started
            self.lat, self.lon, zoom = flight.at(t)
            self.zoom = self._clamp_zoom(zoom)
            if t >= flight.duration:
                self._flight = None
        if self._coast is not None:
            vlat, vlon, last = self._coast
            dt = now - last
            decay = 0.5 ** (dt / COAST_HALF_LIFE)
            # integrate the exponentially decaying speed over the step
            step = COAST_HALF_LIFE / math.log(2.0) * (1.0 - decay)
            self.lat = max(-LAT_LIMIT, min(LAT_LIMIT, self.lat + vlat * step))
            self.lon = wrap_lon(self.lon + vlon * step)
            vlat, vlon = vlat * decay, vlon * decay
            floor = COAST_FLOOR * self.zoom / self.hc
            if (math.hypot(vlat, vlon * math.cos(math.radians(self.lat)))
                    < floor or abs(self.lat) >= LAT_LIMIT):
                self._coast = None
            else:
                self._coast = (vlat, vlon, now)
        if self._zoom is not None:
            from_zoom, to_zoom, anchor, started = self._zoom
            s = (now - started) / ZOOM_EASE
            if s >= 1.0:
                zoom = to_zoom
                self._zoom = None
            else:
                # eased in log space, so each step feels the same
                e = _ease_in_out(s)
                zoom = math.exp(math.log(from_zoom)
                                + (math.log(to_zoom) - math.log(from_zoom)) * e)
            self._apply_zoom(zoom, anchor)
        if self.spinning:
            if self._spin_mark is not None and self._drag_base is None:
                self.lon = wrap_lon(self.lon - SPIN_RATE * (now - self._spin_mark))
            self._spin_mark = now
        return self.lat, self.lon, self.zoom

    def _apply_zoom(self, zoom, anchor):
        """Set the zoom, keeping the anchored ground under its cell."""
        if anchor is not None:
            plat, plon, fx, fy = anchor
            lat_c = max(-LAT_LIMIT, min(LAT_LIMIT, plat - zoom * (0.5 - fy)))
            self.lat = lat_c
            self.lon = wrap_lon(plon - self._lon_span(zoom, lat_c) * (fx - 0.5))
        self.zoom = zoom

    # -- moving ----------------------------------------------------------
    def drag(self, dcol, drow):
        """The pointer has moved this far, in cells, since the press.
        The ground follows the hand, on the flat map and on the globe
        alike: every event recentres from the drag-start centre."""
        if self._drag_base is None:
            self._drag_base = (self.lat, self.lon)
            self._drag_trail = []
            self._coast = self._flight = None
        base_lat, base_lon = self._drag_base
        lat = max(-LAT_LIMIT, min(LAT_LIMIT, base_lat + drow * self.zoom / self.hc))
        lon = wrap_lon(base_lon - dcol * self._lon_span(self.zoom, base_lat) / self.gw)
        changed = (self.lat, self.lon) != (lat, lon)
        self.lat, self.lon = lat, lon
        now = self.clock()
        self._drag_trail.append((now, lat, lon))
        self._drag_trail = [t for t in self._drag_trail if now - t[0] < 0.25]
        return changed

    def release(self):
        """The button is up; a flick coasts, a hold stops dead."""
        if self._drag_base is None:
            return False
        self._drag_base = None
        trail = self._drag_trail
        self._drag_trail = []
        now = self.clock()
        if len(trail) >= 2 and now - trail[-1][0] < 0.12:
            (t0, lat0, lon0), (t1, lat1, lon1) = trail[0], trail[-1]
            dt = t1 - t0
            if dt >= 0.03:
                vlat = (lat1 - lat0) / dt
                vlon = _maps_motion._lon_delta(lon0, lon1) / dt
                cos_lat = math.cos(math.radians(self.lat))
                speed = math.hypot(vlat, vlon * cos_lat)
                ceiling = COAST_CEILING * self.zoom
                if speed > ceiling:
                    vlat, vlon = vlat * ceiling / speed, vlon * ceiling / speed
                    speed = ceiling
                if speed >= COAST_FLOOR * self.zoom / self.hc:
                    self._coast = (vlat, vlon, now)
        return True

    def zoom_to(self, target, at=None):
        """Ease the zoom to `target`, about the ground fraction `at`
        ((fx, fy) of the map, or None for the centre).  Truthy if
        anything will move."""
        target = self._clamp_zoom(target)
        current_target = self._zoom[1] if self._zoom is not None else self.zoom
        if abs(target - current_target) < 1e-12:
            return False
        anchor = None
        # anchored zoom is a flat-map identity — on either side of the
        # globe hand-off, zoom about the centre instead
        if (at is not None and not _globe.is_globe(self.zoom, self.lat)
                and not _globe.is_globe(target, self.lat)):
            fx, fy = at
            plat = self.lat + self.zoom * (0.5 - fy)
            plon = self.lon + self._lon_span(self.zoom, self.lat) * (fx - 0.5)
            anchor = (plat, plon, fx, fy)
        self._coast = self._flight = None
        self._zoom = (self.zoom, target, anchor, self.clock())
        return True

    def zoom_by(self, factor, at=None):
        target = self._zoom[1] if self._zoom is not None else self.zoom
        return self.zoom_to(target * factor, at)

    def fly_to(self, lat, lon, zoom):
        """Fly to a view: out, across and in, along van Wijk's path."""
        zoom = self._clamp_zoom(zoom)
        lat = max(-LAT_LIMIT, min(LAT_LIMIT, lat))
        self._coast = self._zoom = None
        self.spinning = False
        if (abs(lat - self.lat) < 1e-9 and abs(_maps_motion._lon_delta(self.lon, lon)) < 1e-9
                and abs(zoom - self.zoom) < 1e-12):
            return False
        flight = _maps_motion.Flight(self.lat, self.lon, self.zoom, lat, lon, zoom)
        self._flight = (flight, self.clock())
        return True

    def flight_progress(self):
        """How far through the flight, 0..1; 1 when not flying."""
        if self._flight is None:
            return 1.0
        flight, started = self._flight
        return min(1.0, (self.clock() - started) / flight.duration)

    def jump_to(self, lat, lon, zoom):
        """Be there now, no motion."""
        self._coast = self._zoom = self._flight = None
        self.lat = max(-LAT_LIMIT, min(LAT_LIMIT, lat))
        self.lon = wrap_lon(lon)
        self.zoom = self._clamp_zoom(zoom)

    def spin(self, on):
        self.spinning = on
        self._spin_mark = self.clock() if on else None


def _ease_in_out(s):
    return s * s * (3.0 - 2.0 * s)


class MapApp(LiveApp):
    """The live map: its state, and the hooks that move it.

    The constructor takes what main() has already settled — the
    runtime, the home point and its name, the opening zoom and view,
    whether the sky is on, the travel profile and the --from and --to
    endpoints — and starts nothing: no thread, no request.  run() seeds
    the route request, starts the sky's clock and hands the app to the
    loop; stop() parks the spin.

    The view's centre and zoom live in the camera; `lat`, `lon` and
    `zoom` here read and write it.  One ticker thread wakes the loop
    at 30 Hz while anything is in motion, the sky's way, and every
    frame is timed off the clock.
    """

    interval = 3600  # elevation doesn't change; repaint on input only
    mouse = True

    def __init__(self, runtime, lat, lon, location_name, zoom, view, sky,
                 profile, origin=None, dest=None):
        self.runtime = runtime
        self.home = (lat, lon)      # the marker
        self.location_name = location_name
        self.camera = Camera(lat, lon, zoom)
        self.view = view
        self.show_labels = True
        self.sun = sky          # s: daylight shading + night city lights
        self.clouds = sky       # c: this hour's cloud cover
        self.search = _maps_ui.SearchState()
        self.helping = False
        self.routes = _maps_ui.RouteState(profile=profile, home=(lat, lon))
        if origin is not None:
            self.routes.set_origin(origin.lat, origin.lon, origin.name)
        if dest is not None:
            self.routes.select(dest.lat, dest.lon, dest.name)
        self._ticker = None
        self._lock = threading.Lock()
        self._destination = None   # a flight's end, until it is asked for
        self._fit()

    # -- the view centre and zoom, on the camera ---------------------------
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
        """Start the ticker if anything is moving and it is not running."""
        with self._lock:
            if self._ticker is None or not self._ticker.is_alive():
                self._ticker = threading.Thread(target=self._tick, daemon=True)
                self._ticker.start()

    def _tick(self):
        # While frames are due, the interpreter hands the lock between
        # threads more often: a loader in the background is pure Python
        # for seconds at a time, and at the default interval it can keep
        # the repaint waiting for a tenth of one.
        interval = sys.getswitchinterval()
        sys.setswitchinterval(min(interval, SWITCH_INTERVAL))
        try:
            while True:
                time.sleep(TICK)
                _nudge_repaint()
                if not self.camera.moving():
                    return
        finally:
            sys.setswitchinterval(interval)

    # -- moving ----------------------------------------------------------
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
        self._wake()
        return True

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
                    _globe_now.refresh(self.zoom, hc * 4)
                except Exception as exc:
                    log_failure("maps/clouds", "scheduled refresh", exc,
                                fallback="previous canvas kept")
            _nudge_repaint()

    def on_action(self, key):
        if key == '+':
            return self.zoom_to(self._zoom_target() / ZOOM_STEP)
        if key == '-':
            return self.zoom_to(self._zoom_target() * ZOOM_STEP)
        if key == 'v':
            nxt = _maps_style.MODES.index(self.view) + 1
            self.view = _maps_style.MODES[nxt % len(_maps_style.MODES)]
            return True
        if key == 'l':
            self.show_labels = not self.show_labels
            return True
        if key == 's':
            self.sun = not self.sun
            return True
        if key == 'c':
            self.clouds = not self.clouds
            return True
        if key == 'r':
            # the screensaver: the planet turns while you watch, about
            # a degree a second, six minutes to the revolution — and
            # only a warm globe, whose frames are arithmetic
            if self.camera.spinning:
                self.camera.spin(False)
                return False
            gw, hc = map_cells()
            if (not _globe.is_globe(self.zoom, self.lat)
                    or not _globe.warm(self.zoom, hc * 4)):
                return False
            self.camera.spin(True)
            self._wake()
            return False  # the first tick is the repaint
        return False

    def _zoom_target(self):
        """Where the zoom is heading: a run of taps compounds."""
        easing = self.camera._zoom
        return easing[1] if easing is not None else self.zoom

    def on_wheel(self, direction, col, row):
        return self.zoom_to(self._zoom_target() * (ZOOM_STEP if direction < 0
                                                   else 1.0 / ZOOM_STEP),
                            at=(col, row))

    def fly_to(self, result):
        """Fly to a search result and frame it.

        No mode change: searching an address in terrain mode gives
        terrain at that address.  The destination view starts loading
        as the flight leaves, so with luck it is there on arrival.
        """
        gw, hc = self._fit()
        zoom = max(MIN_ZOOM_DEG, min(
            max_zoom(gw, hc), fly_to_zoom(result, (hc * 2) / gw)))
        self._fly(result.lat, result.lon, zoom)

    def fly_to_step(self, step):
        """Frame one maneuver: centre on it, zoomed to roughly the
        distance the step covers, so a highway leg shows its whole
        run and a city turn shows its corner."""
        loc = step.get("location")
        if loc is None:
            return
        span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
        self._fly(loc[1], loc[0], max(MIN_ZOOM_DEG, min(max_zoom(*map_cells()), span)))

    def _fly(self, lat, lon, zoom):
        self._fit()
        zoom = self.camera._clamp_zoom(zoom)
        if self.camera.fly_to(lat, lon, zoom):
            # the destination loads from the descent: the loaders are
            # pure Python for seconds at a time, and started at take-off
            # they would take the frames' share of the interpreter
            # through the whole climb, where the picture is at its best
            self._destination = (lat, lon, zoom)
            self._wake()

    def _prefetch_if_descending(self):
        if self._destination is None or self.camera.flight_progress() < 0.5:
            return
        lat, lon, zoom = self._destination
        self._destination = None
        gw, hc = map_cells()
        prefetch_view(lat, lon, zoom, self.view, gw, hc, self.runtime.lang,
                      marker=self.home)

    def intercept(self, action):
        """Maps owns dispatch: the search panel eats every key while
        it is open, the directions panel takes the arrows, and
        nothing else here consumes one."""
        search, routes = self.search, self.routes
        if search.open:
            gw, hc = map_cells()
            bbox = bbox_for(self.lat, self.lon, self.zoom, gw, hc)
            z = int(_maps_style.z_eff(bbox, hc))
            return search.handle(action, self.lat, self.lon, z,
                                 self.runtime.lang)
        if self.helping:
            # Any key closes the panel; anything but the three
            # dismiss keys is then handled as usual, so `/` from
            # help opens search in one press.
            self.helping = False
            if action in ('key:?', 'escape', 'quit'):
                return True
        if action == 'key:?':
            self.helping = True
            return True
        if routes.panel:
            # The directions panel: arrows walk the maneuvers and
            # the map flies along; the field rows name their own
            # keys, and `d` — its opening job done — edits the
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
            if action == 'key:d':
                search.start("route")
                return True
        if action == 'key:/':
            search.start()
            return True
        if action == 'key:d':
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
        """The ground follows the hand; let go moving and it coasts."""
        self._fit()
        if done:
            moved = self.camera.release()
            if self.camera.moving():
                self._wake()
            return moved
        return self.camera.drag(dcol, drow)

    def text_mode(self):
        return self.search.open

    def render(self, mouse_pos=None, **_):
        search, routes = self.search, self.routes
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
        self._fit()
        lat, lon, zoom = self.camera.view()
        self._prefetch_if_descending()
        moving = self.camera.moving() or self.camera.dragging()
        return render_map(
            lat, lon, self.location_name, zoom,
            marker=self.home, runtime=self.runtime, block=False,
            moving=moving,
            mouse_pos=None if moving else mouse_pos, view=self.view,
            search=search, route=routes.route, dest=routes.dest,
            origin=routes.origin, directions=routes,
            note=_maps_ui.route_note(routes, self.runtime.lang),
            helping=self.helping, show_labels=self.show_labels,
            sun=self.sun, clouds=self.clouds)

    def run(self):
        if self.routes.dest is not None:
            self.routes.request()
        threading.Thread(target=self.cloud_tick, daemon=True).start()
        # the header names a panned view from the offline gazetteer,
        # whose first answer builds its index: asked now, off the
        # frame's thread, so the first drag does not pay for it
        threading.Thread(target=self._warm, daemon=True).start()
        super().run()

    def _warm(self):
        try:
            _panned_place(self.home[0], self.home[1], self.runtime.lang)
        except Exception as exc:
            log_failure("maps/gazetteer", "warm-up", exc, fallback="on first use")

    def stop(self):
        self.camera.spin(False)  # the loop is over; let the ticker park


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
    if args.zoom is None:
        args.zoom = _maps_style.DEFAULT_ZOOM[args.view]

    if args.profile not in _maps_route.PROFILES:
        print(f"maps: invalid profile '{args.profile}' — choose "
              f"{', '.join(_maps_route.PROFILES)}", file=sys.stderr)
        sys.exit(2)

    if args.search:
        from linecast._weather_sources import _search_locations
        _search_locations(args.search, lang=runtime.lang)
        return

    # Sweep the tile cache before this session adds to it: dead
    # vector-tile versions first, then back under the size cap. Map tiles
    # never go stale, so nothing here goes by age alone. After --search,
    # which adds no tiles and should not wait on a tilejson fetch.
    from linecast._maps_tile_cache import prune_maps_cache
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
            from linecast._weather_sources import _reverse_geocode
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
               args.profile, origin=origin, dest=dest).run()
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
        print(render_map(lat, lon, location_name, args.zoom,
                         runtime=runtime, view=args.view, route=found,
                         dest=(dest.lat, dest.lon) if dest else None,
                         origin=((origin.lat, origin.lon, origin.name)
                                 if origin else None),
                         note=note or "", sun=sky, clouds=sky))
        if found is not None:
            # the turn-by-turn list rides below the map: --print asked
            # for directions, so it gets the directions
            print()
            for line in _maps_ui.steps_text(
                    found, runtime.lang,
                    origin_label=origin.name if origin else location_name,
                    dest_label=dest.name):
                print(line)
