"""The live map: what runs when you type `maps`.

main() settles the arguments, resolves the location and the --to and
--from endpoints, then puts a MapApp on screen.  --print renders once
and exits.  MapApp is the view's hands: its state is the centre, the
zoom, the mode and the toggles, plus the search and directions panels;
its methods are the hooks live_loop calls — zoom, drag, wheel, the
keys, the clicks — and render, which draws the frame through
render_map.  Everything drawn is in maps; everything fetched is in
_maps_views.
"""

import math
import sys
import threading
import time

from linecast import (
    _globe, _globe_now, _maps_route, _maps_style, _maps_ui,
)
from linecast._geo import wrap_lon
from linecast._live import LiveApp, nudge as _nudge_repaint
from linecast._location import location_overridden, resolve_location
from linecast._maps_i18n import ms
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._maps_views import _zoom_hold
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, log_failure, maps_parser, set_current
from linecast.maps import (
    MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP, map_cells, render_map,
)


class MapApp(LiveApp):
    """The live map: its state, and the hooks that move it.

    The constructor takes what main() has already settled — the
    runtime, the home point and its name, the opening zoom and view,
    whether the sky is on, the travel profile and the --from and --to
    endpoints — and starts nothing: no thread, no request.  run() seeds
    the route request, starts the sky's clock and hands the app to the
    loop; stop() parks the spin.
    """

    interval = 3600  # elevation doesn't change; repaint on input only
    mouse = True

    def __init__(self, runtime, lat, lon, location_name, zoom, view, sky,
                 profile, origin=None, dest=None):
        self.runtime = runtime
        self.home = (lat, lon)      # the marker
        self.location_name = location_name
        self.lat, self.lon = lat, lon   # the view centre
        self.zoom = zoom
        self.pan_preview = (0, 0)
        self.drag_base = None   # centre at globe-drag start, or None
        self.drag_sync = False  # next repaint renders the globe blocking
        self.spinning = 0       # active spin generation; 0 = parked
        self.spin_seq = 0       # last generation ever started
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

    def zoom_to(self, new_zoom, at=None):
        """Apply a clamped zoom, keeping the point under `at` fixed.

        `at` is a terminal (col, row) in the same 1-based frame as
        mouse_pos; None zooms about the view centre.  Anchoring is
        the difference between a wheel that explores and one that
        makes you chase the thing you were looking at.
        """
        new_zoom = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, new_zoom))
        if new_zoom == self.zoom:
            return False
        gw, hc = map_cells()
        pcol, prow = (at[0] - 1, at[1] - 2) if at else (-1, -1)
        # anchored zoom is a flat-map identity — on either side of
        # the globe hand-off, zoom about the centre instead
        if (self.zoom >= _globe.ZOOM_DEG or new_zoom >= _globe.ZOOM_DEG):
            pcol = -1
        if 0 <= pcol < gw and 0 <= prow < hc:
            fx, fy = (pcol + 0.5) / gw, (prow + 0.5) / hc
            lon_span = (self.zoom * (gw / (hc * 2))
                        / math.cos(math.radians(self.lat)))
            plat = self.lat + self.zoom * (0.5 - fy)
            plon = self.lon + lon_span * (fx - 0.5)
            lat_c = max(-80.0, min(80.0, plat - new_zoom * (0.5 - fy)))
            new_span = (new_zoom * (gw / (hc * 2))
                        / math.cos(math.radians(lat_c)))
            self.lat = lat_c
            self.lon = wrap_lon(plon - new_span * (fx - 0.5))
        self.zoom = new_zoom
        _zoom_hold.hold()
        return True

    def spin(self, gen):
        """The r screensaver: the planet turns while you watch.

        Each tick walks the centre meridian westward and repaints
        through the same warm-canvas blocking path a drag uses, so
        the geography drifts eastward the way it actually does —
        about a degree a second, six minutes to the revolution.
        The spin yields to a drag in progress and parks itself the
        moment a zoom crosses back inside the hand-off.
        """
        while self.spinning == gen:
            time.sleep(0.4)
            if self.spinning != gen:
                break
            if self.zoom < _globe.ZOOM_DEG:
                self.spinning = 0
                break
            if self.drag_base is not None:
                continue  # a drag steers; the spin waits its turn
            self.lon = (self.lon - 0.4 + 180.0) % 360.0 - 180.0
            self.drag_sync = True
            _nudge_repaint()

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
            return self.zoom_to(self.zoom / ZOOM_STEP)
        if key == '-':
            return self.zoom_to(self.zoom * ZOOM_STEP)
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
            if self.spinning:
                self.spinning = 0
                return False
            gw, hc = map_cells()
            if (self.zoom < _globe.ZOOM_DEG
                    or not _globe.warm(self.zoom, hc * 4)):
                return False  # only a warm globe spins
            self.spin_seq += 1
            self.spinning = self.spin_seq
            threading.Thread(target=self.spin, args=(self.spinning,),
                             daemon=True).start()
            return False  # the first tick is the repaint
        return False

    def on_wheel(self, direction, col, row):
        return self.zoom_to(self.zoom * (ZOOM_STEP if direction < 0
                                         else 1.0 / ZOOM_STEP),
                            at=(col, row))

    def fly_to(self, result):
        """Jump to a search result and frame it, instantly.

        No animation and no mode change: searching an address in
        terrain mode gives terrain at that address.  Predictability
        beats cleverness, and there is nothing to restore.
        """
        gw, hc = map_cells()
        self.lat, self.lon = result.lat, result.lon
        self.zoom = max(MIN_ZOOM_DEG, min(
            MAX_ZOOM_DEG, fly_to_zoom(result, (hc * 2) / gw)))

    def fly_to_step(self, step):
        """Frame one maneuver: centre on it, zoomed to roughly the
        distance the step covers, so a highway leg shows its whole
        run and a city turn shows its corner."""
        loc = step.get("location")
        if loc is None:
            return
        span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
        self.zoom = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, span))
        self.lat = max(-80.0, min(80.0, loc[1]))
        self.lon = loc[0]

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
        gw, hc = map_cells()
        # On the globe the disk stays put and the geography turns
        # under the cursor: every motion event recentres the view
        # from the drag-start centre and the repaint re-projects the
        # sphere, so the drag *is* the rotation rather than a
        # shifted snapshot of it.  Only a warm view rotates live —
        # until the world canvas is stitched there is nothing to
        # re-project without blocking on the network — and a drag
        # keeps whichever idiom it started with.
        globing = self.drag_base is not None or (
            not (self.pan_preview[0] or self.pan_preview[1])
            and self.zoom >= _globe.ZOOM_DEG
            and _globe.warm(self.zoom, hc * 4))
        if globing:
            if self.drag_base is None:
                if done:
                    return False  # a click, not a drag
                self.drag_base = (self.lat, self.lon)
            base_lat, base_lon = self.drag_base
            lat = max(-80.0, min(80.0,
                                 base_lat + drow * self.zoom / hc))
            lon = base_lon - (dcol * (self.zoom / (hc * 2))
                              / math.cos(math.radians(base_lat)))
            lon = (lon + 180.0) % 360.0 - 180.0
            changed = (self.lat, self.lon) != (lat, lon)
            self.lat, self.lon = lat, lon
            self.drag_sync = self.drag_sync or changed
            if done:
                self.drag_base = None
            return changed or done
        if not done:
            changed = self.pan_preview != (dcol, drow)
            self.pan_preview = (dcol, drow)
            return changed
        had_preview = self.pan_preview[0] or self.pan_preview[1]
        self.pan_preview = (0, 0)
        if not (dcol or drow):
            return bool(had_preview)
        lon_span = (self.zoom * (gw / (hc * 2))
                    / math.cos(math.radians(self.lat)))
        self.lat = max(-80.0, min(80.0, self.lat + drow * self.zoom / hc))
        self.lon = wrap_lon(self.lon + -dcol * lon_span / gw)
        return True

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
        # A rotating globe repaints synchronously: its canvas is
        # warm, so "blocking" is ~a tenth of a second of arithmetic,
        # and the alternative is a blank disk between frames.
        sync = self.drag_sync and self.zoom >= _globe.ZOOM_DEG
        self.drag_sync = False
        return render_map(
            self.lat, self.lon, self.location_name, self.zoom,
            marker=self.home, runtime=self.runtime, block=sync,
            pan_offset=self.pan_preview,
            mouse_pos=mouse_pos, view=self.view, search=search,
            route=routes.route, dest=routes.dest,
            origin=routes.origin, directions=routes,
            note=_maps_ui.route_note(routes, self.runtime.lang),
            helping=self.helping, show_labels=self.show_labels,
            sun=self.sun, clouds=self.clouds)

    def run(self):
        if self.routes.dest is not None:
            self.routes.request()
        threading.Thread(target=self.cloud_tick, daemon=True).start()
        super().run()

    def stop(self):
        self.spinning = 0  # the loop is over; let the spin thread park


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
            args.zoom = MAX_ZOOM_DEG
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

    lat, lon, country, location_name = resolve_location(
        args.location, lang=runtime.lang, return_label=True)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    # With no override the resolved location is the user's own; let the
    # units default follow its country before the first render (a cold
    # cache resolved without one)
    if country and not location_overridden(args.location):
        runtime = RuntimeConfig.from_sources(args, country=country)
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
