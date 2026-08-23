"""The live map: what runs when you type `maps`.

main() settles the arguments, resolves the location and the --to and
--from endpoints, then runs render_map under live_loop with the
closures that give the view its hands: zoom, drag, wheel, the keys,
the search and directions panels, the spin.  --print renders once and
exits.  Everything drawn is in maps; everything fetched is in
_maps_views.
"""

import math
import os
import sys
import threading

from linecast import (
    _globe, _globe_now, _maps_route, _maps_style, _maps_ui, _maps_views,
)
from linecast._framebuffer import get_terminal_size
from linecast._graphics import live_loop
from linecast._location import get_location
from linecast._maps_i18n import ms
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._maps_views import _hold_fetches, _nudge_repaint
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, maps_parser
from linecast.maps import (
    MAX_ZOOM_DEG, MIN_ZOOM_DEG, ZOOM_STEP, render_map,
)


def main():
    args = maps_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)
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

    override = args.location or os.environ.get("WEATHER_LOCATION", "").strip()
    location_name = ""
    if override:
        try:
            parts = override.split(",")
            lat, lon = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            from linecast._weather_sources import geocode_first
            hit = geocode_first(override, lang=runtime.lang)
            if hit is None:
                print(f'No locations matching "{override}".', file=sys.stderr)
                sys.exit(1)
            lat, lon, location_name = hit
    else:
        lat, lon, _cc = get_location()
        if lat is None:
            print("Could not determine location.", file=sys.stderr)
            sys.exit(1)

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
        _maps_views._live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]
        pan_preview = [0, 0]
        drag_base = [None]   # centre at globe-drag start, or None
        drag_sync = [False]  # next repaint renders the globe blocking
        spinning = [0]       # active spin generation; 0 = parked
        spin_seq = [0]       # last generation ever started
        view = [args.view]
        show_labels = [True]
        sun = [sky]          # s: daylight shading + night city lights
        clouds = [sky]       # c: this hour's cloud cover
        search = _maps_ui.SearchState()
        helping = [False]
        routes = _maps_ui.RouteState(profile=args.profile, home=(lat, lon))
        if origin is not None:
            routes.set_origin(origin.lat, origin.lon, origin.name)
        if dest is not None:
            routes.select(dest.lat, dest.lon, dest.name)
            routes.request()

        def zoom_to(new_zoom, at=None):
            """Apply a clamped zoom, keeping the point under `at` fixed.

            `at` is a terminal (col, row) in the same 1-based frame as
            mouse_pos; None zooms about the view centre.  Anchoring is
            the difference between a wheel that explores and one that
            makes you chase the thing you were looking at.
            """
            new_zoom = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, new_zoom))
            if new_zoom == zoom[0]:
                return False
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            pcol, prow = (at[0] - 1, at[1] - 2) if at else (-1, -1)
            # anchored zoom is a flat-map identity — on either side of
            # the globe hand-off, zoom about the centre instead
            if (zoom[0] >= _globe.ZOOM_DEG or new_zoom >= _globe.ZOOM_DEG):
                pcol = -1
            if 0 <= pcol < gw and 0 <= prow < hc:
                fx, fy = (pcol + 0.5) / gw, (prow + 0.5) / hc
                lon_span = (zoom[0] * (gw / (hc * 2))
                            / math.cos(math.radians(center[0])))
                plat = center[0] + zoom[0] * (0.5 - fy)
                plon = center[1] + lon_span * (fx - 0.5)
                lat_c = max(-80.0, min(80.0, plat - new_zoom * (0.5 - fy)))
                new_span = (new_zoom * (gw / (hc * 2))
                            / math.cos(math.radians(lat_c)))
                center[0] = lat_c
                center[1] = plon - new_span * (fx - 0.5)
                if center[1] > 180.0:
                    center[1] -= 360.0
                elif center[1] < -180.0:
                    center[1] += 360.0
            zoom[0] = new_zoom
            _hold_fetches()
            return True

        def spin(gen):
            """The r screensaver: the planet turns while you watch.

            Each tick walks the centre meridian westward and repaints
            through the same warm-canvas blocking path a drag uses, so
            the geography drifts eastward the way it actually does —
            about a degree a second, six minutes to the revolution.
            The spin yields to a drag in progress and parks itself the
            moment a zoom crosses back inside the hand-off.
            """
            import time
            while spinning[0] == gen:
                time.sleep(0.4)
                if spinning[0] != gen:
                    break
                if zoom[0] < _globe.ZOOM_DEG:
                    spinning[0] = 0
                    break
                if drag_base[0] is not None:
                    continue  # a drag steers; the spin waits its turn
                center[1] = (center[1] - 0.4 + 180.0) % 360.0 - 180.0
                drag_sync[0] = True
                _nudge_repaint()

        def cloud_tick():
            """The sky's slow heartbeat.

            Every half hour while the sky is switched on: the newest
            mosaic frame if clouds are showing, the sun where it now
            is, one repaint.  Never an animation — a view left running
            all evening simply stays true.
            """
            import time
            while True:
                time.sleep(1800)
                if not (sun[0] or clouds[0]):
                    continue
                if clouds[0]:
                    cols, rows = get_terminal_size()
                    try:
                        _globe_now.refresh(zoom[0], max(8, rows - 2) * 4)
                    except Exception:
                        pass
                _nudge_repaint()

        threading.Thread(target=cloud_tick, daemon=True).start()

        def on_action(key):
            if key == '+':
                return zoom_to(zoom[0] / ZOOM_STEP)
            if key == '-':
                return zoom_to(zoom[0] * ZOOM_STEP)
            if key == 'v':
                nxt = _maps_style.MODES.index(view[0]) + 1
                view[0] = _maps_style.MODES[nxt % len(_maps_style.MODES)]
                return True
            if key == 'l':
                show_labels[0] = not show_labels[0]
                return True
            if key == 's':
                sun[0] = not sun[0]
                return True
            if key == 'c':
                clouds[0] = not clouds[0]
                return True
            if key == 'r':
                if spinning[0]:
                    spinning[0] = 0
                    return False
                cols, rows = get_terminal_size()
                hc = max(8, rows - 2)
                if (zoom[0] < _globe.ZOOM_DEG
                        or not _globe.warm(zoom[0], hc * 4)):
                    return False  # only a warm globe spins
                spin_seq[0] += 1
                spinning[0] = spin_seq[0]
                threading.Thread(target=spin, args=(spinning[0],),
                                 daemon=True).start()
                return False  # the first tick is the repaint
            return False

        def on_wheel(direction, col, row):
            return zoom_to(zoom[0] * (ZOOM_STEP if direction < 0
                                      else 1.0 / ZOOM_STEP), at=(col, row))

        def fly_to(result):
            """Jump to a search result and frame it, instantly.

            No animation and no mode change: searching an address in
            terrain mode gives terrain at that address.  Predictability
            beats cleverness, and there is nothing to restore.
            """
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            center[0], center[1] = result.lat, result.lon
            zoom[0] = max(MIN_ZOOM_DEG, min(
                MAX_ZOOM_DEG, fly_to_zoom(result, (hc * 2) / gw)))

        def fly_to_step(step):
            """Frame one maneuver: centre on it, zoomed to roughly the
            distance the step covers, so a highway leg shows its whole
            run and a city turn shows its corner."""
            loc = step.get("location")
            if loc is None:
                return
            span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
            zoom[0] = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, span))
            center[0] = max(-80.0, min(80.0, loc[1]))
            center[1] = loc[0]

        def intercept(action):
            """Maps owns dispatch: the search panel eats every key while
            it is open, the directions panel takes the arrows, and
            nothing else here consumes one."""
            if search.open:
                cols, rows = get_terminal_size()
                bbox = bbox_for(center[0], center[1], zoom[0],
                                max(20, cols), max(8, rows - 2))
                z = int(_maps_style.z_eff(bbox, max(8, rows - 2)))
                return search.handle(action, center[0], center[1], z,
                                     runtime.lang)
            if helping[0]:
                # Any key closes the panel; anything but the three
                # dismiss keys is then handled as usual, so `/` from
                # help opens search in one press.
                helping[0] = False
                if action in ('key:?', 'escape', 'quit'):
                    return True
            if action == 'key:?':
                helping[0] = True
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
                        fly_to_step(step)
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

        def on_click(col, row):
            """A click on the directions panel acts on the row it hit —
            fields open their search or cycle the mode, a step takes
            the focus and the map flies to it.  Anywhere else, a click
            stays what it always was: nothing."""
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
                fly_to_step(routes.route.steps[act[1]])
            else:
                return False
            return True

        def on_drag(dcol, drow, done):
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            # On the globe the disk stays put and the geography turns
            # under the cursor: every motion event recentres the view
            # from the drag-start centre and the repaint re-projects the
            # sphere, so the drag *is* the rotation rather than a
            # shifted snapshot of it.  Only a warm view rotates live —
            # until the world canvas is stitched there is nothing to
            # re-project without blocking on the network — and a drag
            # keeps whichever idiom it started with.
            globing = drag_base[0] is not None or (
                not (pan_preview[0] or pan_preview[1])
                and zoom[0] >= _globe.ZOOM_DEG
                and _globe.warm(zoom[0], hc * 4))
            if globing:
                if drag_base[0] is None:
                    if done:
                        return False  # a click, not a drag
                    drag_base[0] = (center[0], center[1])
                base_lat, base_lon = drag_base[0]
                lat = max(-80.0, min(80.0,
                                     base_lat + drow * zoom[0] / hc))
                lon = base_lon - (dcol * (zoom[0] / (hc * 2))
                                  / math.cos(math.radians(base_lat)))
                lon = (lon + 180.0) % 360.0 - 180.0
                changed = center != [lat, lon]
                center[0], center[1] = lat, lon
                drag_sync[0] = drag_sync[0] or changed
                if done:
                    drag_base[0] = None
                return changed or done
            if not done:
                changed = pan_preview != [dcol, drow]
                pan_preview[0], pan_preview[1] = dcol, drow
                return changed
            had_preview = pan_preview[0] or pan_preview[1]
            pan_preview[0] = pan_preview[1] = 0
            if not (dcol or drow):
                return bool(had_preview)
            lon_span = (zoom[0] * (gw / (hc * 2))
                        / math.cos(math.radians(center[0])))
            center[0] = max(-80.0, min(80.0, center[0] + drow * zoom[0] / hc))
            center[1] += -dcol * lon_span / gw
            if center[1] > 180.0:
                center[1] -= 360.0
            elif center[1] < -180.0:
                center[1] += 360.0
            return True

        def render(mouse_pos=None, **_):
            # A search committed from a background reply lands here: the
            # worker cannot move the view itself, so it parks the result
            # and the next repaint applies it.
            hit = search.take_chosen()
            if hit is not None:
                fly_to(hit)
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
            sync = drag_sync[0] and zoom[0] >= _globe.ZOOM_DEG
            drag_sync[0] = False
            return render_map(
                center[0], center[1], location_name, zoom[0],
                marker=(lat, lon), runtime=runtime, block=sync,
                pan_offset=(pan_preview[0], pan_preview[1]),
                mouse_pos=mouse_pos, view=view[0], search=search,
                route=routes.route, dest=routes.dest,
                origin=routes.origin, directions=routes,
                note=_maps_ui.route_note(routes, runtime.lang),
                helping=helping[0], show_labels=show_labels[0],
                sun=sun[0], clouds=clouds[0])

        live_loop(
            render,
            interval=3600,  # elevation doesn't change; repaint on input only
            mouse=True,
            on_action=on_action,
            on_drag=on_drag,
            on_wheel=on_wheel,
            intercept=intercept,
            text_mode=lambda: search.open,
            on_click=on_click,
        )
        spinning[0] = 0  # the loop is over; let the spin thread park
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
