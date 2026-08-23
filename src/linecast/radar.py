#!/usr/bin/env python3
"""Radar — terminal weather radar over a braille basemap.

Renders live base-reflectivity over a braille basemap: the sea is a solid
colour fill, coastlines and state/national borders are braille strokes, and
the radar echoes blend over it all as a half-block colour fill (labels and
braille keep the blended echo colour as their background).  In live mode,
scroll (or arrow keys) to rewind through the last few hours and watch a storm
approach.

Optional condition layers ride along: a temperature tint painted beneath the
geography, and neutral wind arrows whose contrast rises with speed (calm air
draws nothing) — both sampled from Open-Meteo and time-synced to the
displayed frame, so rewinding rewinds them too.

Data: LibreWXR everywhere (radar composites where a public network has
one, model precipitation elsewhere, 60-min forecast frames, selectable
colour themes); falls back to NEXRAD via Iowa Environmental Mesonet (IEM)
in the continental US and RainViewer elsewhere. Basemap from Natural Earth. Condition layers from Open-Meteo.

Usage: radar [--location LAT,LNG | PLACE] [--zoom DEG] [--theme NAME]
             [--layers temp,wind] [--print] [--search CITY]
"""

import math
import os
import sys
import threading
import time as _time

from linecast._color import fg, RESET, BOLD
from linecast._framebuffer import get_terminal_size
from linecast import _theme
from linecast._location import get_location
from linecast import _radar_frames
from linecast import _radar_layers
from linecast import _radar_warnings
from linecast._radar_basemap import DotLayer, _point_in_rings
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for, _bbox_key, compose
# the frame cache and prefetcher; the benches reach the rest through here too
from linecast._radar_frames import (
    MAX_REWIND_MIN, N_FRAMES, PLAY_READY, _cached_frame, _ensure_prefetch,
    _frame_cache, _frame_key, _load_frame, _loaded_mask, _nearest_cached,
    _nudge, _play_gate, _safe_load, _sat_timeline, _view_key,
)
from linecast._radar_source import FRAME_STEP
from linecast import _radar_sources
from linecast._radar_sources import (DEFAULT_THEME, THEMES, get_source,
                                     has_radar, theme_id)
# maps and the tests reach the view helpers through this module
from linecast._radar_ui import (
    CROSSHAIR, DIM, MARKER, MUTED, _ShiftedBasemap, _build_warning_tooltip,
    _fmt_expire, _fmt_local, _get_basemap, _panned_place, _shift_grid,
    _theme_menu_overlay, _timeline_bar,
)
from linecast._runtime import RuntimeConfig, radar_parser, use_metric
from linecast._graphics import live_loop, visible_len
from linecast._spinner import SPINNER_FRAMES, Spinner

# display layers, toggled by the s key: precipitation (5-min frames) or
# the satellite cloud mosaic alone (hourly, deeper timeline)
LAYERS = ("radar", "sat")

# condition-layer state: fetched fields and rendered temp tints, both small
_field_cache = {}    # field_key -> (fetched_at, Field)
_field_pending = set()
_field_lock = threading.Lock()
_temp_cache = {}     # (bbox, w, h, field id, hour) -> sub-pixel tint buffer

LAYER_NAMES = {"temp": "temp", "temperature": "temp", "t": "temp",
               "wind": "wind", "w": "wind"}


def parse_layers(value):
    """'temp,wind' (any aliases) -> frozenset, or None on an unknown name."""
    layers = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip().lower()
        if not part:
            continue
        name = LAYER_NAMES.get(part)
        if name is None:
            return None
        layers.add(name)
    return frozenset(layers)


def _get_field(bbox, block):
    """The condition Field covering `bbox`; may spawn a background fetch.

    Static mode (block=True) fetches synchronously; live mode returns None
    on a miss and nudges a repaint when the background fetch lands, same as
    radar frames.
    """
    import time
    key = _radar_layers.field_key(bbox)
    with _field_lock:
        hit = _field_cache.get(key)
        if hit is not None and time.time() - hit[0] < 1800:
            return hit[1]
        if not block:
            if key in _field_pending:
                return None
            _field_pending.add(key)

    def load():
        return time.time(), _radar_layers.fetch_field(bbox)

    if block:
        try:
            stamp, field = load()
        except Exception:
            return None
        with _field_lock:
            _field_cache[key] = (stamp, field)
        return field

    def worker():
        try:
            stamp, field = load()
        except Exception:
            stamp = field = None
        with _field_lock:
            _field_pending.discard(key)
            if field is not None:
                if len(_field_cache) > 4:
                    _field_cache.clear()
                _field_cache[key] = (stamp, field)
        if field is not None:
            _nudge()

    threading.Thread(target=worker, daemon=True).start()
    return None


def _temp_buffer(field, t_idx, bbox, graph_w, height_cells):
    """Memoised temperature tint; rebuilt only when view or hour changes."""
    key = (_bbox_key(bbox), graph_w, height_cells, id(field), t_idx,
           _theme.generation)
    buf = _temp_cache.get(key)
    if buf is None:
        buf = _radar_layers.build_temp_buffer(field, t_idx, bbox, graph_w,
                                              height_cells)
        if len(_temp_cache) > 6:
            _temp_cache.clear()
        _temp_cache[key] = buf
    return buf


def render_radar(lat, lon, location_name, zoom, play_frame=0, playing=True,
                 marker=None, runtime=None, block=True, pan_offset=(0, 0),
                 theme_menu=None, mouse_pos=None, layer="radar",
                 layers=frozenset(), **_):
    lang = runtime.lang if runtime else "en"
    use_24h = runtime.use_24h if runtime else False
    source = _radar_frames._source
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    basemap = _get_basemap(bbox, graph_w, height_cells)

    if layer != "radar" and not getattr(source, "satellite_frames",
                                        lambda: [])():
        layer = "radar"  # source has no cloud mosaic (IEM fallback)

    # oldest → newest (UTC). The cloud mosaic is hourly, so satellite-only
    # mode scrubs its own (deeper) timeline; radar frames may include future
    frames = (_sat_timeline() if layer == "sat"
              else source.current_frames())
    if not frames:
        msg = f"{fg(*DIM)}{rs('no_frames', lang)}{RESET}"
        return "\n".join([msg] + [""] * (height_cells + 1))

    # play_frame counts from the "home" frame — the present (newest observed):
    # 0 = now, so pausing (which homes the counter) always lands on now
    present_idx = max((i for i, f in enumerate(frames) if not f.future),
                      default=len(frames) - 1)
    idx = (present_idx + play_frame) % len(frames)
    frame = frames[idx]
    when = frame.time
    present = frames[present_idx].time
    _ensure_prefetch(bbox, graph_w, height_cells, frames, start_idx=idx,
                     layer=layer)

    err = None
    loading = False
    buffering = False
    mask = n_loaded = None
    if not block:
        mask, buffering = _play_gate(bbox, graph_w, height_cells, frames,
                                     layer, playing)
        n_loaded = sum(mask)
    if block:
        # static mode: fetch the displayed frame synchronously
        try:
            radar, echo = _load_frame(bbox, graph_w, height_cells, frame,
                                      layer)
        except Exception as exc:
            radar = [[None] * graph_w for _ in range(height_cells * 2)]
            echo, err = 0.0, str(exc)
    else:
        # live mode: never block a render on the network — show the nearest
        # cached frame (radar pops in as the prefetcher lands frames)
        hit = _cached_frame(bbox, graph_w, height_cells, frame, layer)
        if hit is None:
            hit = _nearest_cached(bbox, graph_w, height_cells, when, layer)
            loading = True
        if hit is not None:
            radar, echo = hit
        else:
            radar, echo = [[None] * graph_w for _ in range(height_cells * 2)], 0.0

    # condition layers (temperature tint, wind arrows) follow the scrubbed
    # frame's hour, so rewinding shows the field as it was
    field = t_idx = under = wind_ov = None
    if layers:
        field = _get_field(bbox, block)
        if field is None:
            loading = loading or not block
        else:
            t_idx = field.nearest_time_idx(when)
            if "temp" in layers:
                under = _temp_buffer(field, t_idx, bbox, graph_w,
                                     height_cells)
            if "wind" in layers:
                wind_ov = _radar_layers.wind_overlays(
                    field, t_idx, bbox, graph_w, height_cells)

    # storm-based warning outlines valid at the displayed frame's time
    # (live mode: cache-only, the prefetcher warms them alongside frames)
    warn_layer = None
    warns = None
    if _radar_warnings.covers(bbox) and not frame.future:
        if block:
            try:
                warns = _radar_warnings.warnings_at(when)
            except Exception:
                warns = None
        else:
            warns = _radar_warnings.cached_at(when)
        if warns:
            warn_layer = DotLayer(bbox, graph_w, height_cells)
            for _sev, color, rings, _info in warns:  # least-severe-first: TO wins
                warn_layer._draw_lines(rings, color, width=2)

    overlays = dict(basemap.city_overlays(lang=lang))
    if wind_ov:
        for pos, (ch, color) in wind_ov.items():  # city labels win the cell
            # third element marks the colour as fixed: arrow contrast IS the
            # wind-speed encoding, so compose() must not adjust it
            overlays.setdefault(pos, (ch, color, True))
    # "your location" marker, pinned geographically (panning can move it
    # off-centre or out of view entirely)
    m_lat, m_lon = marker if marker else (lat, lon)
    minlon, minlat, maxlon, maxlat = bbox
    mcol = int((m_lon - minlon) / (maxlon - minlon) * graph_w)
    mrow = int((maxlat - m_lat) / (maxlat - minlat) * height_cells)
    if 0 <= mcol < graph_w and 0 <= mrow < height_cells:
        overlays[(mcol, mrow)] = ("+", MARKER)

    dx, dy = pan_offset
    if dx or dy:
        # mid-drag preview: slide the already-composed layers in screen space
        # (no re-projection, no fetches); the real re-render lands on release
        basemap = _ShiftedBasemap(_shift_grid(basemap.dots, dx, dy, 0),
                                  _shift_grid(basemap.color, dx, dy, None),
                                  _shift_grid(basemap.sea, dx, dy * 2, False))
        radar = _shift_grid(radar, dx, dy * 2, None)  # sub-pixel rows: 2/cell
        if under is not None:
            under = _shift_grid(under, dx, dy * 2, None)
        if warn_layer is not None:
            warn_layer = _ShiftedBasemap(
                _shift_grid(warn_layer.dots, dx, dy, 0),
                _shift_grid(warn_layer.color, dx, dy, None))
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}

    # centre crosshair: marks where a pan release will centre the view;
    # omitted while the home marker itself sits on the centre cell
    ccol, crow = graph_w // 2, height_cells // 2
    if (mcol + dx, mrow + dy) != (ccol, crow):
        overlays[(ccol, crow)] = ("+", CROSSHAIR)

    map_lines = compose(basemap, radar, overlays, graph_w, height_cells,
                        warnings=warn_layer, under=under)

    # header: play state, frame time, how old/ahead, echo coverage.
    # Both header and footer must never exceed the terminal width: a wrapped
    # line adds a row, scrolling the whole frame up by one.
    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    delta = round((when - present).total_seconds() / 60)
    # sat-mode frames sit whole hours back; "-9h" reads, "-540m" doesn't
    mag, sign = abs(delta), "-" if delta < 0 else "+"
    span = (f"{sign}{mag // 60}h" if mag >= 60 and mag % 60 == 0
            else f"{sign}{mag}m")
    age = rs("now", lang) if delta == 0 else span
    tag = f" {rs('forecast', lang)}" if frame.future else ""
    if buffering:
        # spinner + frame-window progress while auto-play waits to start
        # (the loop re-renders every play_interval, animating the spinner)
        spin_ch = SPINNER_FRAMES[int(_time.monotonic() * 5)
                                 % len(SPINNER_FRAMES)]
        tag += f" · {spin_ch} {rs('loading', lang)} {n_loaded}/{len(frames)}"
    elif loading:
        tag += f" · {rs('loading', lang)}"
    if field is not None and "temp" in layers:
        # temperature at the view centre, in the units _panned_place uses
        tc = field.sample_temp(t_idx, lon, lat)
        metric = use_metric(lang)
        tag += (f" · {round(tc)}°C" if metric
                else f" · {round(tc * 9 / 5 + 32)}°F")
    icon = "▶" if playing else "⏸"
    # with the cloud layer in, the coverage figure is cloud, not echo
    pct = rs("echo_pct" if layer == "radar" else "cloud_pct",
             lang, pct=f"{echo:.0f}")
    brand = "radar" if layer == "radar" else "satellite ☁"

    def _header(place_str):
        return (f"{fg(*MARKER)}{BOLD}⬤ {brand}{RESET}  {fg(*MUTED)}{place_str}"
                f"{RESET}  {fg(*DIM)}{icon} {_fmt_local(when, use_24h)} · {age}{tag} "
                f"· {pct}{RESET}")

    header = _header(place)
    over = visible_len(header) - cols
    if over > 0 and len(place) > over + 1:  # squeeze the place name first
        header = _header(place[:len(place) - over - 1] + "…")
    header += " " * max(0, cols - visible_len(header))

    # footer: attribution + scrubber + controls, dropping pieces that don't fit
    if err:
        foot = f"{fg(*DIM)}{rs('radar_unavailable', lang, err=err[:40])}{RESET}"
    else:
        credit = source.attribution
        if not has_radar(lat, lon):  # model-derived here; say so
            credit = getattr(source, "model_attribution", credit)
        left = f"{fg(*DIM)}{credit}{RESET}"
        hint = (f"{fg(*DIM)}{rs('hint', lang)}{RESET}"
                if sys.stdout.isatty() else "")
        bar = _timeline_bar(idx, len(frames), min(28, max(10, cols // 3)),
                            present=present_idx, loaded=mask)
        for foot in (f"{left}  {bar}  {hint}",
                     f"{left}  {hint}",
                     f"{left}  {bar}",
                     left):
            if visible_len(foot) <= cols:
                break
    foot += " " * max(0, cols - visible_len(foot))

    out = "\n".join([header, *map_lines, foot])
    # a single \x00 overlay channel: the theme picker (modal) wins it while
    # open; otherwise a hover tooltip names any warning under the cursor
    overlay = ""
    if theme_menu is not None:
        names, sel = theme_menu
        overlay = _theme_menu_overlay(
            names, sel, getattr(source, "theme", None), lang, cols,
            rows)
    elif mouse_pos and warns and pan_offset == (0, 0):
        overlay = _build_warning_tooltip(
            warns, mouse_pos, bbox, graph_w, height_cells, cols, rows, use_24h)
    if overlay:
        out += "\x00" + overlay
    return out


def main():
    args = radar_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)

    # Sweep day-old frame tiles before fetching new ones — they're keyed by
    # frame timestamp and will never be asked for again.
    from linecast._radar_tiles import prune_tile_cache
    prune_tile_cache()

    if args.search:
        from linecast._weather_sources import _search_locations
        _search_locations(args.search, lang=runtime.lang)
        return

    theme_arg = (args.theme
                 or os.environ.get("LINECAST_RADAR_THEME", "").strip()
                 or DEFAULT_THEME)
    theme = theme_id(theme_arg)
    if theme is None:
        print(f'Unknown radar theme "{theme_arg}". '
              f'Themes: {", ".join(THEMES)}.', file=sys.stderr)
        sys.exit(2)

    layer_arg = (args.layers
                 or os.environ.get("LINECAST_RADAR_LAYERS", "")).strip()
    layers = parse_layers(layer_arg)
    if layers is None:
        print(f'Unknown radar layer in "{layer_arg}". Layers: temp, wind.',
              file=sys.stderr)
        sys.exit(2)

    layer = {"radar": "radar", "satellite": "sat", "sat": "sat"}.get(
        (args.layer or os.environ.get("LINECAST_RADAR_LAYER", "").strip()
         or "radar").lower())
    if layer is None:
        print('Unknown radar layer. Layers: radar, satellite.',
              file=sys.stderr)
        sys.exit(2)

    # everything from here to the first paint may block on the network
    # (geocoding, the frame index, static-mode frame fetches) — spin
    override = args.location or os.environ.get("WEATHER_LOCATION", "").strip()
    location_name = ""
    spin = Spinner(rs("loading", runtime.lang))
    spin.start()
    try:
        if override:
            try:
                parts = override.split(",")
                lat, lon = float(parts[0]), float(parts[1])
            except (ValueError, IndexError):
                from linecast._weather_sources import geocode_first
                hit = geocode_first(override, lang=runtime.lang)
                if hit is None:
                    spin.stop()
                    print(f'No locations matching "{override}".',
                          file=sys.stderr)
                    sys.exit(1)
                lat, lon, location_name = hit
        else:
            lat, lon, _cc = get_location()
            if lat is None:
                spin.stop()
                print("Could not determine location.", file=sys.stderr)
                sys.exit(1)

        if not location_name:
            try:
                from linecast._weather_sources import _reverse_geocode
                location_name = _reverse_geocode(
                    lat, lon, lang=runtime.lang)[0] or ""
            except Exception:
                location_name = ""

        _radar_frames._source = get_source(lat, lon, N_FRAMES, theme)

        if not runtime.live:
            # static: play_frame 0 is the present (newest observed) frame
            static_out = render_radar(lat, lon, location_name, args.zoom,
                                      play_frame=0, playing=False,
                                      runtime=runtime, layers=layers,
                                      layer=layer)
    finally:
        spin.stop()

    if not runtime.live:
        print(static_out)
        return

    from linecast._radar_sources import _in_conus

    _radar_frames._live_refresh = True
    # a background index refresh that adds a frame repaints the timeline
    _radar_sources.on_index_refresh = _nudge
    zoom = [args.zoom]
    center = [lat, lon]          # pans; marker stays at the true location
    region = [_in_conus(lat, lon)]

    layer_state = set(layers)
    layer_sel = [layer]

    def on_action(key):
        if key in ('c', 'w'):
            layer_state.symmetric_difference_update(
                {'temp' if key == 'c' else 'wind'})
            return True
        if key == 's':
            # cycle layers; a no-op on sources without a cloud mosaic
            if not getattr(_radar_frames._source, "satellite_frames",
                           lambda: [])():
                return False
            i = LAYERS.index(layer_sel[0])
            layer_sel[0] = LAYERS[(i + 1) % len(LAYERS)]
            return True
        if key == '+':
            new_zoom = max(1.0, zoom[0] / 1.5)
        elif key == '-':
            new_zoom = min(60.0, zoom[0] * 1.5)
        else:
            return False
        if new_zoom == zoom[0]:
            return False
        zoom[0] = new_zoom
        return True

    pan_preview = [0, 0]  # live cell offset while a drag is in progress
    theme_sel = [theme]   # active theme id (the picker updates it)
    menu_sel = [None]     # picker: None = closed, else highlighted row

    def intercept(action):
        """Route keys to the theme picker; everything else passes through."""
        themes = getattr(_radar_frames._source, "themes", None)
        names = list(themes) if themes else []
        if menu_sel[0] is None:
            if action == 'key:t' and names:
                ids = list(themes.values())
                cur = getattr(_radar_frames._source, "theme", None)
                menu_sel[0] = ids.index(cur) if cur in ids else 0
                return True
            return False
        if not names:  # source lost its themes (fallback) — just close
            menu_sel[0] = None
            return True
        if action == 'fwd':
            menu_sel[0] = (menu_sel[0] - 1) % len(names)
        elif action == 'back':
            menu_sel[0] = (menu_sel[0] + 1) % len(names)
        elif action == 'key:enter':
            choice = themes[names[menu_sel[0]]]
            menu_sel[0] = None
            if choice != getattr(_radar_frames._source, "theme", None):
                theme_sel[0] = choice
                # same index, no fetch
                _radar_frames._source = _radar_frames._source.with_theme(
                    choice)
        elif action in ('escape', 'key:t', 'quit'):
            menu_sel[0] = None
        return True  # while the menu is open, no key reaches the map

    def on_drag(dcol, drow, done):
        if not done:
            # mid-drag: update the screen-space preview offset only
            changed = pan_preview != [dcol, drow]
            pan_preview[0], pan_preview[1] = dcol, drow
            return changed
        had_preview = pan_preview[0] or pan_preview[1]
        pan_preview[0] = pan_preview[1] = 0
        if not (dcol or drow):
            return bool(had_preview)  # zero-delta release = plain click
        # commit: dragging pulls the map, so the view centre moves the
        # opposite way; the release re-render re-projects for real
        cols, rows = get_terminal_size()
        gw, hc = max(20, cols), max(8, rows - 2)
        lon_span = zoom[0] * (gw / (hc * 2)) / math.cos(math.radians(center[0]))
        center[0] = max(-80.0, min(80.0, center[0] + drow * zoom[0] / hc))
        center[1] += -dcol * lon_span / gw
        if center[1] > 180.0:
            center[1] -= 360.0
        elif center[1] < -180.0:
            center[1] += 360.0
        # crossing the CONUS boundary re-picks the source: the natural
        # moment to retry LibreWXR after a fallback (a source that offers
        # themes is LibreWXR already, and would only be re-picked as itself)
        r = _in_conus(center[0], center[1])
        if r != region[0]:
            region[0] = r
            if getattr(_radar_frames._source, "themes", None) is None:
                _radar_frames._source = get_source(
                    center[0], center[1], N_FRAMES, theme_sel[0])
        return True

    live_loop(
        lambda play_frame=0, playing=True, mouse_pos=None, **_: render_radar(
            center[0], center[1], location_name, zoom[0],
            play_frame=play_frame, playing=playing, marker=(lat, lon),
            runtime=runtime, block=False, mouse_pos=mouse_pos,
            pan_offset=(pan_preview[0], pan_preview[1]),
            layers=frozenset(layer_state),
            layer=layer_sel[0],
            theme_menu=((list(_radar_frames._source.themes), menu_sel[0])
                        if menu_sel[0] is not None
                        and getattr(_radar_frames._source, "themes", None)
                        else None)),
        interval=FRAME_STEP,   # pick up a new composite every 5 min
        mouse=True,
        auto_play=True,
        play_interval=0.2,     # animation frame rate (~5 fps)
        on_action=on_action,
        on_drag=on_drag,
        intercept=intercept,
        play_gate=lambda: not _radar_frames._buffering,
    )


if __name__ == "__main__":
    main()
