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

from dataclasses import replace
import sys
import threading
import time

from linecast import (
    _globe, _globe_now, _maps_route, _maps_style, _maps_ui, _theme,
)
from linecast._live import LiveApp, nudge as _nudge_repaint
from linecast._location import country_for_defaults, resolve_location
from linecast._maps_camera import MapCamera
from linecast._maps_i18n import ms
from linecast._maps_motion import CameraMotion
from linecast._maps_scene import Scene, SceneWorker
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, log_failure, maps_parser, set_current
from linecast.maps import (
    MIN_ZOOM_DEG, ZOOM_STEP, map_cells, max_zoom, prepare_map, render_map,
)


class MapApp(LiveApp):
    """The live map: its state, and the hooks that move it.

    The constructor takes what main() has already settled — the
    runtime, the home point and its name, the opening zoom and view,
    whether the sky is on, the travel profile and the --from and --to
    endpoints — and starts nothing: no thread, no request.  run() seeds
    the route request, starts the sky's clock and hands the app to the
    loop; stop() parks animation, pending preparation and retry wakes.
    """

    interval = 3600  # elevation doesn't change; repaint on input only
    mouse = True

    help_view = 'maps'

    def __init__(self, runtime, lat, lon, location_name, zoom, view, sky,
                 profile, origin=None, dest=None):
        self.runtime = runtime
        self.home = (lat, lon)      # the marker
        self.location_name = location_name
        self.lat, self.lon = lat, lon   # the view centre
        self.zoom = zoom
        self.drag_base = None
        self._drag_trail = []
        self._drag_cancelled = False
        self._motion = CameraMotion(self.target_camera())
        self._ticker_lock = threading.Lock()
        self._ticker_running = False
        self._stopped = False
        self._worker = None
        self._sky_revision = 0
        self._spin_mark = None
        self._pan_key = None
        self.spinning = 0       # active spin generation; 0 = parked
        self.spin_seq = 0       # last generation ever started
        self.view = view
        self.show_labels = True
        self.sun = sky          # S: daylight shading + night city lights
        self.clouds = sky       # c: this hour's cloud cover
        self.search = _maps_ui.SearchState()
        self.routes = _maps_ui.RouteState(profile=profile, home=(lat, lon))
        if origin is not None:
            self.routes.set_origin(origin.lat, origin.lon, origin.name)
        if dest is not None:
            self.routes.select(dest.lat, dest.lon, dest.name)

    def target_camera(self):
        return MapCamera(self.lat, self.lon, self.zoom, *map_cells())

    def displayed_camera(self, now=None):
        target = self.target_camera()
        # Search, directions and terminal resize may replace the view outright.
        if target.key != self._motion.target.key:
            previous = self._motion.target
            if ((target.lat, target.lon, target.zoom) ==
                    (previous.lat, previous.lon, previous.zoom)):
                # A resize stops at the displayed position, not the coast's
                # future destination. Old drag coordinates no longer apply.
                target = replace(self._motion.sample(now), gw=target.gw, hc=target.hc)
                self.lat, self.lon, self.zoom = target.lat, target.lon, target.zoom
                self._cancel_drag()
            self._motion.move(target, animate=False, now=now)
        return self._motion.sample(now)

    def _cancel_drag(self):
        self._drag_cancelled |= self.drag_base is not None
        self.drag_base = None
        self._drag_trail = []

    def _stop_motion(self):
        camera = self.displayed_camera()
        changed = self._motion.moving or bool(self.spinning)
        self._move(camera, animate=False)
        self.spinning = 0
        self._cancel_drag()
        return changed

    def on_interrupt(self):
        """A new grab or Help catches the camera where it is displayed."""
        changed = self._stop_motion()
        self._drag_cancelled = False
        return changed

    def _move(self, camera, *, animate=True, anchor=None, now=None):
        self.lat, self.lon, self.zoom = camera.lat, camera.lon, camera.zoom
        self._pan_key = None
        self._motion.move(camera, animate=animate, anchor=anchor, now=now)
        if animate:
            self._wake_animation()

    def _wake_animation(self):
        with self._ticker_lock:
            if self._stopped or self._ticker_running:
                return
            self._ticker_running = True
            threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self):
        # Only input and render own the camera; the ticker merely asks for
        # another frame. There is no competing worker writing its position.
        while True:
            time.sleep(1 / 30)
            with self._ticker_lock:
                if self._stopped or not (self._motion.moving or self.spinning):
                    self._ticker_running = False
                    return
            _nudge_repaint()

    def zoom_to(self, new_zoom, at=None):
        """Ease logarithmically to a scale, anchored under the wheel pointer."""
        gw, hc = map_cells()
        new_zoom = max(MIN_ZOOM_DEG, min(max_zoom(gw, hc), new_zoom))
        if new_zoom == self.zoom:
            if self._motion.coasting or self.spinning or self.drag_base is not None:
                return self._stop_motion()
            return False
        now = time.monotonic()
        current = self.displayed_camera(now)
        anchor = None
        if at is not None and 1 <= at[0] <= gw and 2 <= at[1] < hc + 2:
            anchor = (at[0] - .5, at[1] - 1.5)
        target = current.zoom_at(new_zoom, *(anchor or ()))
        if anchor is not None:
            before = current.unproject(*anchor, gw, hc)
            after = target.unproject(*anchor, gw, hc)
            if before is None or after is None or not (
                    abs(before[0] - after[0]) < 1e-7
                    and abs((before[1] - after[1] + 180) % 360 - 180) < 1e-7):
                # A north-up camera cannot retain every polar/limb anchor.
                # Use one centre zoom throughout, rather than losing the
                # anchor partway through an otherwise anchored transition.
                anchor = None
                target = current.zoom_at(new_zoom)
        self.spinning = 0
        self._cancel_drag()
        self._move(target, anchor=anchor, now=now)
        return True

    def cloud_tick(self):
        """The sky's slow heartbeat.

        Every half hour while the sky is switched on: the newest
        mosaic frame if clouds are showing, the sun where it now
        is, one repaint.  Never an animation — a view left running
        all evening simply stays true.
        """
        while not self._stopped:
            time.sleep(1800)
            if self._stopped:
                return
            if not (self.sun or self.clouds):
                continue
            if self.clouds:
                gw, hc = map_cells()
                try:
                    _globe_now.refresh(self.zoom, hc * 4)
                except Exception as exc:
                    log_failure("maps/clouds", "scheduled refresh", exc,
                                fallback="previous canvas kept")
            self._sky_revision += 1
            _nudge_repaint()

    def on_action(self, key):
        if key in ('w', 'a', 's', 'd'):
            gw, hc = map_cells()
            dcol, drow = {'w': (0, hc * 0.1), 'a': (gw * 0.1, 0),
                         's': (0, -hc * 0.1), 'd': (-gw * 0.1, 0)}[key]
            self.spinning = 0
            self._cancel_drag()
            current = self.displayed_camera()
            base = self.target_camera() if self._pan_key == key else current
            self._move(base.pan(dcol, drow))
            self._pan_key = key
            return True
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
        if key == 'S':
            self.sun = not self.sun
            return True
        if key == 'c':
            self.clouds = not self.clouds
            return True
        if key == 'r':
            if self.spinning:
                self.spinning = 0
                return True
            stopped = self._stop_motion()
            gw, hc = map_cells()
            if (self.target_camera().local_tiles
                    or not _globe.warm(self.zoom, hc * 4)):
                return stopped
            self.spin_seq += 1
            self.spinning = self.spin_seq
            self._spin_mark = time.monotonic()
            self._wake_animation()
            return True
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
        self._stop_motion()
        gw, hc = map_cells()
        zoom = max(MIN_ZOOM_DEG, min(
            max_zoom(gw, hc), fly_to_zoom(result, (hc * 2) / gw)))
        self._move(MapCamera(result.lat, result.lon, zoom, gw, hc), animate=False)

    def fly_to_step(self, step):
        """Frame one maneuver: centre on it, zoomed to roughly the
        distance the step covers, so a highway leg shows its whole
        run and a city turn shows its corner."""
        loc = step.get("location")
        if loc is None:
            return
        self._stop_motion()
        span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
        zoom = max(MIN_ZOOM_DEG, min(max_zoom(*map_cells()), span))
        self._move(MapCamera(max(-80.0, min(80.0, loc[1])), loc[0], zoom,
                             *map_cells()), animate=False)

    def help_panel(self):
        from linecast._help import HelpPanel
        return HelpPanel('maps', self.runtime.lang, content=lambda cols, rows:
                         _maps_ui.help_rows(cols, rows, self.runtime.lang,
                                            self.routes.route is not None))

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
                self._stop_motion()
                search.start("route")
                return True
        if action == 'key:/':
            self._stop_motion()
            search.start()
            return True
        if action == 'key:D':
            self._stop_motion()
            if routes.press() == "search":
                search.start("route")
            return True
        if action == 'open':
            # o: re-point the origin, panel open or not.
            self._stop_motion()
            search.start("origin")
            return True
        if action == 'key:p':
            return routes.cycle_profile()
        if action == 'reset':
            # n / space: the one deliberately destructive key.
            routes.clear()
            self.spinning = 0
            self._cancel_drag()
            self._move(MapCamera(*self.home, self.zoom, *map_cells()))
            return True
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
        if act is not None:
            self._stop_motion()
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
        # A drag uses its starting camera and the cumulative cell delta. This
        # is the same spherical motion at street scale and planetary scale.
        if self._drag_cancelled or self.search.open:
            if done:
                self._drag_cancelled = False
            return False
        had_drag = self.drag_base is not None
        if not had_drag and not (dcol or drow):
            return False
        now = time.monotonic()
        if self.drag_base is None:
            self.drag_base = self.displayed_camera(now)
            self._drag_trail = []
        camera = self.drag_base.pan(dcol, drow)
        changed = camera.key != self.target_camera().key
        self.spinning = 0
        self._move(camera, animate=False, now=now)
        if changed:
            trail = self._drag_trail
            if len(trail) >= 2:
                _, ax, ay = trail[-2]
                _, bx, by = trail[-1]
                if (bx - ax) * (dcol - bx) + 4 * (by - ay) * (drow - by) < 0:
                    trail = trail[-1:]  # a reversal sheds the old direction
            self._drag_trail = [p for p in trail if now - p[0] <= .15][-7:]
            self._drag_trail.append((now, dcol, drow))
        if done:
            base = self.drag_base
            self.drag_base = None
            trail, self._drag_trail = self._drag_trail, []
            # Motion reports have processing times, not device timestamps.
            # Ignore bursts and stale motion; a stationary release is not a
            # fresh sample and must not turn a pause into a fling.
            if len(trail) >= 2 and now - trail[-1][0] < .12:
                t0, x0, y0 = trail[0]
                t1 = trail[-1][0]
                previous = base.pan(x0, y0)
                if t1 - t0 >= .03 and camera.visible(previous.lon, previous.lat):
                    # A pole crossing changes the north-up screen basis.
                    # Measure actual movement in the release view, where the
                    # earlier centre lies opposite the continuing camera turn.
                    x, y = camera.project(previous.lon, previous.lat, camera.gw, camera.hc)
                    if self._motion.coast((x - camera.gw / 2) / (t1 - t0),
                                          (y - camera.hc / 2) / (t1 - t0), now=now):
                        target = self._motion.target
                        self.lat, self.lon, self.zoom = target.lat, target.lon, target.zoom
                        self._wake_animation()
        return changed or (done and had_drag)

    def _prepare(self, camera, options, generation):
        # A half-step around the frame covers a full zoom-out step and short
        # pans while the next scene is being built. Sample density is unchanged.
        px, py = max(1, (camera.gw + 3) // 4), max(1, (camera.hc + 3) // 4)
        source = MapCamera(camera.lat, camera.lon,
                           camera.zoom * (camera.hc + 2 * py) / camera.hc,
                           camera.gw + 2 * px, camera.hc + 2 * py)
        while camera.local_tiles and not source.local_tiles:
            # Extra coverage must not push an otherwise local view onto
            # coarser world data. Keep as much padding as its sources allow.
            px, py = px // 2, py // 2
            source = MapCamera(camera.lat, camera.lon,
                               camera.zoom * (camera.hc + 2 * py) / camera.hc,
                               camera.gw + 2 * px, camera.hc + 2 * py)
        if (_globe._radius(camera.zoom, camera.hc * 2) * 1.08
                <= min(camera.gw / 2, camera.hc)):
            # Padding a complete planet only prepares more empty space.
            source = camera
        frame = prepare_map(source, **options)
        if frame.world:
            from linecast._maps_globe import prepare_surface
            # Full-world coverage is prepared by the same worker. Static
            # output needs only its exact frame and never builds this texture.
            frame = replace(frame, surface=prepare_surface(
                source, street=frame.street, sun=options.get("sun", False),
                clouds=options.get("clouds", False)))
        if generation != _theme.generation:
            return None
        frame.prime()
        return Scene(frame.cropped(camera), frame)

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
        now = time.monotonic()
        if self.spinning:
            elapsed = now - (self._spin_mark if self._spin_mark is not None else now)
            self._spin_mark = now
            camera = self.displayed_camera(now)
            self._move(MapCamera(camera.lat, camera.lon - elapsed, camera.zoom,
                                 camera.gw, camera.hc), animate=False, now=now)
        camera = self.displayed_camera(now)
        target = self.target_camera()
        if self._worker is None:
            self._worker = SceneWorker(wake=_nudge_repaint, thread_factory=threading.Thread)
        generation = _theme.generation
        group = (self.view, self.show_labels, self.sun, self.clouds,
                 self.runtime.lang, generation, id(routes.route))
        revision = (self._sky_revision, _globe_now.revision() if self.clouds else None)
        options = dict(marker=self.home, lang=self.runtime.lang, view=self.view,
                       route=routes.route, show_labels=self.show_labels,
                       sun=self.sun, clouds=self.clouds)
        scene, refining, error = self._worker.request(
            (target.key, group, revision), group,
            lambda: self._prepare(target, options, generation), camera=camera)
        prepared = None
        if scene is not None:
            prepared = (scene.exact if scene.exact.camera.key == camera.key
                        else scene.overscan)
        return render_map(
            camera, prepared, self.location_name, marker=self.home,
            runtime=self.runtime, view=self.view, sun=self.sun, clouds=self.clouds,
            refining=refining, error=error, mouse_pos=mouse_pos,
            search=search, directions=routes, route=routes.route,
            dest=routes.dest, origin=routes.origin,
            note=_maps_ui.route_note(routes, self.runtime.lang))

    def run(self):
        if self.routes.dest is not None:
            self.routes.request()
        threading.Thread(target=self.cloud_tick, daemon=True).start()
        super().run()

    def stop(self):
        self._stop_motion()
        self._stopped = True
        self.spinning = 0
        if self._worker is not None:
            self._worker.stop()


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
        camera = MapCamera(lat, lon, args.zoom, *map_cells())
        prepared, error = None, None
        try:
            prepared = prepare_map(camera, view=args.view, lang=runtime.lang,
                                   route=found, sun=sky, clouds=sky, wait_for_clouds=True)
        except Exception as exc:
            log_failure("maps", "prepare print", exc, fallback="unavailable map")
            lines = str(exc).splitlines()
            error = (lines[0] if lines else type(exc).__name__)[:120]
        print(render_map(camera, prepared, location_name, error=error,
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
