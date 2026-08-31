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
in the continental US and RainViewer elsewhere. Basemap from Natural Earth.
Condition layers from Open-Meteo.

Everything drawn is here: render_radar composes one frame.  What runs
when you type `radar` — the arguments, the source, the keys and the live
loop — is in _radar_live.

Usage: radar [--location LAT,LNG | PLACE] [--zoom DEG] [--theme NAME]
             [--layers temp,wind] [--source NAME] [--print] [--search CITY]
"""

import sys
import time as _time

from linecast._color import fg, RESET, BOLD
from linecast._framebuffer import get_terminal_size
from linecast import _theme
from linecast import _radar_frames
from linecast import _radar_layers
from linecast import _radar_warnings
from linecast._live import overlay
from linecast._radar_basemap import DotLayer, _point_in_rings  # noqa: F401 — re-exported
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for, _bbox_key, compose
# the frame cache and prefetcher; the benches reach the rest through here too
from linecast._radar_frames import (  # noqa: F401
    MAX_REWIND_MIN, N_FRAMES, PLAY_READY, _cached_frame, _ensure_prefetch,
    _frame_cache, _frame_key, _load_frame, _loaded_mask, _nearest_cached,
    _nudge, _play_gate, _safe_load, _sat_timeline, _view_key,
)
from linecast._radar_sources import has_radar
from linecast._scenes import Memo, SceneCache
# the tests reach the view helpers through this module
from linecast._radar_ui import (  # noqa: F401
    CROSSHAIR, DIM, MARKER, MUTED, _ShiftedBasemap, _build_warning_tooltip,
    _fmt_expire, _fmt_local, _get_basemap, _panned_place, _shift_grid,
    _theme_menu_overlay, _timeline_bar,
)
from linecast._runtime import log_failure, use_metric
from linecast._graphics import visible_len
from linecast._spinner import SPINNER_FRAMES

# display layers, toggled by the s key: precipitation (5-min frames) or
# the satellite cloud mosaic alone (hourly, deeper timeline)
LAYERS = ("radar", "sat")

# condition-layer state: fetched fields and rendered temp tints, both small
_field_cache = SceneCache(keep=5, max_age=1800, name="condition field")  # field_key -> Field
_temp_cache = Memo(keep=7)  # (bbox, w, h, field id, hour) -> sub-pixel tint buffer

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
    key = _radar_layers.field_key(bbox)
    try:
        return _field_cache.get(key, block,
                                lambda: _radar_layers.fetch_field(bbox))
    except Exception as exc:
        log_failure("radar/layers", "condition field", exc, fallback="temp/wind layers off")
        return None


def _temp_buffer(field, t_idx, bbox, graph_w, height_cells):
    """Memoised temperature tint; rebuilt only when view or hour changes."""
    key = (_bbox_key(bbox), graph_w, height_cells, id(field), t_idx,
           _theme.generation)
    return _temp_cache.get(
        key, lambda: _radar_layers.build_temp_buffer(field, t_idx, bbox,
                                                     graph_w, height_cells))


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

    if layer != "radar" and not _sat_timeline():
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
    if not block:
        # live mode warms the window behind the displayed frame; a static
        # render shows one frame and exits, so the rest would only cost
        # the tile servers requests nobody looks at
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
            log_failure(_radar_frames.source_tag(), "frame load", exc,
                        fallback="blank frame")
            radar = [[None] * graph_w for _ in range(height_cells * 2)]
            echo, err = 0.0, str(exc)
            # main() reads this to decide whether to fall down the source
            # chain and render once more
            _radar_frames.frame_load_failed = True
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
            except Exception as exc:
                log_failure("radar/warnings", "fetch", exc, url=_radar_warnings._URL,
                            fallback="no warning outlines")
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
        metric = runtime.metric if runtime else use_metric()
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
    floating = ""
    if theme_menu is not None:
        names, sel = theme_menu
        floating = _theme_menu_overlay(
            names, sel, getattr(source, "theme", None), lang, cols,
            rows)
    elif mouse_pos and warns and pan_offset == (0, 0):
        floating = _build_warning_tooltip(
            warns, mouse_pos, bbox, graph_w, height_cells, cols, rows, use_24h)
    return overlay(out, floating)


def main():
    # the live loop draws through render_radar, so _radar_live imports this
    # module; importing it here, at the call, keeps that one-way at load
    from linecast._radar_live import main as live_main
    live_main()


if __name__ == "__main__":
    main()
