#!/usr/bin/env python3
"""Radar — terminal weather radar over a braille basemap.

Renders live base-reflectivity over a braille basemap: the sea is a solid
colour fill, coastlines and state/national borders are braille strokes, and
the radar echoes blend over it all as a half-block colour fill (labels and
braille keep the blended echo colour as their background).  In live mode,
scroll (or arrow keys) to rewind through the last few hours and watch a storm
approach.

Data: LibreWXR everywhere (global radar composites + model precipitation,
60-min forecast frames, selectable colour themes); falls back to NEXRAD via
Iowa Environmental Mesonet (IEM) in the continental US and RainViewer
elsewhere. Basemap from Natural Earth.

Usage: radar [--location LAT,LNG | PLACE] [--zoom DEG] [--theme NAME]
             [--print] [--search CITY]
"""

import datetime as _dt
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from linecast._color import fg, bg, RESET, BOLD
from linecast._framebuffer import get_terminal_size, fmt_time_dt
from linecast._theme import ensure_contrast
from linecast._weather_style import TOOLTIP_BG_RGB, TOOLTIP_TEXT_RGB
from linecast._location import get_location
from linecast import _radar_warnings
from linecast._radar_basemap import (
    Basemap, DotLayer, marine_region, nearest_city,
)
from linecast._radar_i18n import rs
from linecast._radar_render import (
    bbox_for, build_radar_buffer, compose, lerp_rgba, over_rgba,
)
from linecast._radar_source import FRAME_STEP
from linecast._radar_sources import DEFAULT_THEME, THEMES, get_source, theme_id
from linecast._runtime import RuntimeConfig, radar_parser
from linecast._graphics import live_loop, visible_len

MUTED = (150, 155, 170)
DIM = (110, 114, 130)
MARKER = (255, 240, 120)
CROSSHAIR = (215, 220, 232)
MAX_REWIND_MIN = 180  # how far back scrubbing can go (IEM; tile sources
                      # are limited to what their index publishes, ~2 h)
N_FRAMES = MAX_REWIND_MIN // 5 + 1  # frames in the rewind window

# display layers, in the order the s key cycles them: precipitation only,
# echoes over the satellite cloud mosaic, clouds alone (hourly timeline)
LAYERS = ("radar", "both", "sat")

_basemap_cache = {}
_source = None  # active RadarSource, chosen per location in main()

# in-memory cache of decoded frames: key -> (radar_buffer, echo_pct)
_frame_cache = {}
_frame_lock = threading.Lock()
_prefetch_key = None  # (bbox, w, h) currently being prefetched
_prefetch_gen = 0     # bumped when the view changes; stale workers stand down
_live_refresh = False  # live mode: prefetch completions nudge a repaint


def _bbox_key(bbox):
    return tuple(round(v, 3) for v in bbox)


def _view_key(bbox, gw, hc):
    # theme is part of the view: switching palettes must not serve old colours
    return (_bbox_key(bbox), gw, hc, getattr(_source, "theme", None))


SAT_STEP_MIN = 10  # synthesized cloud in-betweens in satellite-only mode


def _sat_bracket(when, layer):
    """The cloud state at `when` as (before, after, t); None when unused.

    The mosaic is hourly while the timeline steps in minutes, so the state
    between two mosaics is a cross-fade (`t` in [0,1] toward `after`).
    Before the first / past the newest mosaic there is nothing to fade to
    (no future clouds — nowcast covers echoes only), so the edge holds:
    (frame, None, 0).
    """
    if layer == "radar":
        return None
    sats = getattr(_source, "satellite_frames", lambda: [])()
    if not sats:
        return None
    if when <= sats[0].time:
        return (sats[0], None, 0.0)
    if when >= sats[-1].time:
        return (sats[-1], None, 0.0)
    for a, b in zip(sats, sats[1:]):
        if a.time <= when <= b.time:
            span = (b.time - a.time).total_seconds()
            return (a, b, (when - a.time).total_seconds() / span)
    return (sats[-1], None, 0.0)


def _sat_timeline():
    """Satellite-only frame list: hourly mosaics plus cross-faded in-betweens,
    so the cloud loop plays as smoothly as the radar loop."""
    sats = getattr(_source, "satellite_frames", lambda: [])()
    if len(sats) < 2:
        return list(sats)
    from linecast._radar_sources import Frame
    step = _dt.timedelta(minutes=SAT_STEP_MIN)
    out = []
    when = sats[0].time
    while when < sats[-1].time:
        out.append(Frame(when, "sat-blend"))
        when += step
    out.append(sats[-1])
    return out


def _frame_key(bbox, gw, hc, frame, layer="radar", sat=None):
    stamp = frame.time.strftime("%Y%m%dT%H%M")
    if frame.future:
        # nowcast frames are re-predicted under the same timestamp; a token
        # digest keeps a superseded prediction from being served forever
        import hashlib
        stamp += ":" + hashlib.sha1(str(frame.token).encode()).hexdigest()[:8]
    key = _view_key(bbox, gw, hc) + (layer, stamp)
    if sat is not None:
        # a fresh index can re-bracket a timestamp with a newer mosaic
        a, b, _t = sat
        key += (a.time.strftime("%Y%m%dT%H%M"),
                b.time.strftime("%Y%m%dT%H%M") if b else "")
    return key


def _sat_rgba(bbox, gw, hc, bracket):
    """The (possibly cross-faded) cloud RGBA for a bracket."""
    a, b, t = bracket
    pw, ph, ra = _source.satellite_rgba(bbox, gw, hc, a)
    if b is None or t <= 0.0:
        return pw, ph, ra
    _, _, rb = _source.satellite_rgba(bbox, gw, hc, b)
    return pw, ph, lerp_rgba(ra, rb, t, pw, ph)


def _load_frame(bbox, gw, hc, frame, layer="radar"):
    """Return (radar_buffer, echo). Memoised; fetches + decodes on miss."""
    sat = _sat_bracket(frame.time, layer)
    key = _frame_key(bbox, gw, hc, frame, layer, sat)
    with _frame_lock:
        hit = _frame_cache.get(key)
    if hit is not None:
        return hit
    if layer == "sat":
        pw, ph, rgba = _sat_rgba(bbox, gw, hc, sat)
    else:
        pw, ph, rgba = _source.frame_rgba(bbox, gw, hc, frame)
        if sat is not None:
            sw, sh, srgba = _sat_rgba(bbox, gw, hc, sat)
            rgba = over_rgba(srgba, rgba, pw, ph)  # echoes over the clouds
    result = build_radar_buffer(rgba, pw, ph, gw, hc,
                                sea=_get_basemap(bbox, gw, hc).sea)
    with _frame_lock:
        _frame_cache[key] = result
        if len(_frame_cache) > N_FRAMES + 8:  # bound to the rewind window
            for old in list(_frame_cache)[:len(_frame_cache) - (N_FRAMES + 8)]:
                _frame_cache.pop(old, None)
    if _live_refresh:
        # nudge the live loop to repaint now that a frame is ready (SIGWINCH
        # rides the loop's existing self-pipe wakeup; harmless if coalesced)
        import signal
        os.kill(os.getpid(), signal.SIGWINCH)
    return result


def _cached_frame(bbox, gw, hc, frame, layer="radar"):
    """Cache-only lookup; never touches the network."""
    key = _frame_key(bbox, gw, hc, frame, layer,
                     _sat_bracket(frame.time, layer))
    with _frame_lock:
        return _frame_cache.get(key)


def _nearest_cached(bbox, gw, hc, when, layer="radar"):
    """The cached frame for this view closest in time to `when`, or None."""
    prefix = _view_key(bbox, gw, hc) + (layer,)
    want = int(when.strftime("%Y%m%d%H%M"))
    with _frame_lock:
        keys = [k for k in _frame_cache if k[:len(prefix)] == prefix]
        if not keys:
            return None
        best = min(keys, key=lambda k: abs(
            int(k[len(prefix)].split(":")[0].replace("T", "")) - want))
        return _frame_cache.get(best)


def _ensure_prefetch(bbox, gw, hc, frames, start_idx=0, layer="radar"):
    """Warm the frame window in the background, displayed frame first.

    A view change (pan/zoom/resize/theme) bumps the generation so a
    superseded worker stops issuing fetches for a view nobody is looking
    at. The key also covers the frame window itself, so a long-running
    session re-warms whenever the index publishes a new frame (or
    re-predicts a nowcast) — cached frames hit instantly, only the new
    images fetch.
    """
    global _prefetch_key, _prefetch_gen
    key = (_view_key(bbox, gw, hc), layer,
           tuple((f.time, str(f.token)) for f in frames))
    if _prefetch_key == key:
        return
    _prefetch_key = key
    _prefetch_gen += 1
    gen = _prefetch_gen
    ordered = frames[start_idx:] + frames[:start_idx]  # current frame first
    want_warnings = _radar_warnings.covers(bbox)

    def worker():
        loaded = 0

        def load(f):
            nonlocal loaded
            if gen != _prefetch_gen:
                return  # view moved on; don't fetch for a stale bbox
            if _safe_load(bbox, gw, hc, f, layer):
                loaded += 1
            if want_warnings and not f.future:
                _warm_warnings(f)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(load, ordered))
        if gen == _prefetch_gen and loaded == 0:
            # nothing arrived (offline?) — allow a later render to retry
            global _prefetch_key
            _prefetch_key = None

    threading.Thread(target=worker, daemon=True).start()


def _safe_load(bbox, gw, hc, frame, layer="radar"):
    try:
        _load_frame(bbox, gw, hc, frame, layer)
        return True
    except Exception:
        return False


def _warm_warnings(frame):
    """Prefetch the warning polygons valid at a frame's time (best-effort)."""
    try:
        if _radar_warnings.cached_at(frame.time) is None:
            _radar_warnings.warnings_at(frame.time)
            if _live_refresh:
                import signal
                os.kill(os.getpid(), signal.SIGWINCH)
    except Exception:
        pass


def _get_basemap(bbox, graph_w, height_cells):
    key = (tuple(round(v, 3) for v in bbox), graph_w, height_cells)
    bm = _basemap_cache.get(key)
    if bm is None:
        bm = Basemap(bbox, graph_w, height_cells)
        _basemap_cache.clear()  # only need the current view
        _basemap_cache[key] = bm
    return bm


def _fmt_local(dt_utc, use_24h=False):
    return fmt_time_dt(dt_utc.astimezone(), use_24h=use_24h)


_place_cache = {}


def _panned_place(lat, lon, lang):
    """Friendly name for a panned view centre, from the offline basemap data.

    Layered: "23 km NE of Boston" while a city is close (localized); the
    water body ("Gulf of Maine") once offshore; a distant city again where
    the water is unnamed; bare coordinates in the middle of nowhere.
    """
    key = (round(lat, 3), round(lon, 3), lang)
    hit = _place_cache.get(key)
    if hit is not None:
        return hit

    def city_phrase(name, km, bearing):
        metric = lang != "en" or os.environ.get(
            "WEATHER_UNITS", "").lower() == "metric"
        dist = km if metric else km * 0.621371
        if dist < 2:
            return name
        compass = rs("compass", lang).split()
        return rs("near", lang, dist=round(dist),
                  unit="km" if metric else "mi",
                  dir=compass[round(bearing / 45) % 8], name=name)

    city = nearest_city(lat, lon, lang)
    if city and city[1] < 100:  # coastal waters still read by the city
        place = city_phrase(*city)
    else:
        water = marine_region(lat, lon)
        if water:
            place = water
        elif city and city[1] <= 1000:
            place = city_phrase(*city)
        else:
            place = f"{lat:.2f}, {lon:.2f}"

    if len(_place_cache) > 64:
        _place_cache.clear()
    _place_cache[key] = place
    return place


class _ShiftedBasemap:
    """Duck-typed stand-in for Basemap during a drag preview."""
    __slots__ = ("dots", "color", "sea")

    def __init__(self, dots, color, sea=None):
        self.dots = dots
        self.color = color
        self.sea = sea


def _shift_grid(rows, dx, dy, fill):
    """Shift a 2D grid's content by (dx right, dy down), backfilling `fill`."""
    h = len(rows)
    w = len(rows[0]) if h else 0
    blank = [fill] * w
    out = []
    for y in range(h):
        sy = y - dy
        if 0 <= sy < h:
            src = rows[sy]
            if dx >= 0:
                out.append(([fill] * min(dx, w) + src[:max(0, w - dx)]))
            else:
                out.append((src[-dx:] + [fill] * min(-dx, w))[:w])
        else:
            out.append(blank[:])
    return out


def _theme_menu_overlay(names, sel, current, lang, cols, rows):
    """Cursor-addressed theme list, drawn over the map via live_loop's \\x00
    overlay channel. `sel` is the highlighted row, `current` the active id."""
    inner = min(cols - 4, max(len(n) for n in names) + 4)
    top = max(1, (rows - (len(names) + 2)) // 2)
    left = max(0, (cols - inner - 2) // 2)
    title = f" {rs('theme', lang)} "
    lines = [f"┌{title.center(inner, '─')}┐"]
    for i, name in enumerate(names):
        mark = "●" if THEMES.get(name) == current else " "
        body = f" {mark} {name}"[:inner].ljust(inner)
        if i == sel:
            body = f"\033[7m{body}\033[27m"  # reverse-video highlight
        lines.append(f"│{body}│")
    lines.append(f"└{'─' * inner}┘")
    return "".join(
        f"\033[{top + 1 + i};{left + 1}H{fg(*MUTED)}{line}{RESET}"
        for i, line in enumerate(lines))


def _point_in_rings(lon, lat, rings):
    """Even-odd ray cast across all of a warning's rings (same rule as the
    basemap's marine containment). True if the point falls inside."""
    inside = False
    for ring in rings:
        for i in range(len(ring) - 1):
            (x0, y0), (x1, y1) = ring[i], ring[i + 1]
            if (y0 <= lat < y1) or (y1 <= lat < y0):
                if lon < x0 + (lat - y0) / (y1 - y0) * (x1 - x0):
                    inside = not inside
    return inside


def _fmt_expire(iso, use_24h):
    """"2026-07-17T05:00:00Z" → localised time-of-day, or None."""
    if not iso:
        return None
    try:
        exp = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return _fmt_local(exp, use_24h)


def _build_warning_tooltip(warns, mouse_pos, bbox, graph_w, height_cells,
                           cols, rows, use_24h):
    """A floating chip naming the warning(s) under the cursor, drawn over the
    map via live_loop's \\x00 overlay channel. Empty string when the pointer
    isn't over a warned area.

    The warned *area* is hoverable, not just its braille outline: we invert
    the cell → lon/lat projection and point-in-polygon test the raw rings, so
    the whole polygon interior surfaces its alert.
    """
    mcol, mrow = mouse_pos
    cx, cy = mcol - 1, mrow - 2  # 1-based terminal → 0-based cell (row 1 = header)
    if not (0 <= cx < graph_w and 0 <= cy < height_cells):
        return ""
    minlon, minlat, maxlon, maxlat = bbox
    lon = minlon + (cx + 0.5) / graph_w * (maxlon - minlon)
    lat = maxlat - (cy + 0.5) / height_cells * (maxlat - minlat)

    # most-severe-first (warns is least-severe-first), so the deadliest
    # overlapping warning heads the list
    hits = [(color, info) for _sev, color, rings, info in warns
            if _point_in_rings(lon, lat, rings)]
    if not hits:
        return ""
    hits.reverse()

    TBG = bg(*TOOLTIP_BG_RGB)
    lines = []
    for color, info in hits[:4]:
        name = info.get("name", "")
        if info.get("emergency"):
            name += " ‼"
        elif info.get("pds"):
            name += " (PDS)"
        until = _fmt_expire(info.get("expire"), use_24h)
        tail = f"  {fg(*MUTED)}→ {until}" if until else ""
        cfg = fg(*ensure_contrast(color, TOOLTIP_BG_RGB, 3.0))
        lines.append(f"{TBG} {cfg}{name}{tail} ")
    if len(hits) > 4:
        lines.append(f"{TBG} {fg(*MUTED)}+{len(hits) - 4} ")

    width = max(visible_len(ln) for ln in lines)
    padded = [f"{ln}{TBG}{' ' * (width - visible_len(ln))}{RESET}"
              for ln in lines]

    # anchor below-right of the pointer, pulled inward at the screen edges
    col = mcol + 1
    row = mrow + 1
    if col + width - 1 > cols:
        col = max(1, mcol - width)
    if row + len(padded) - 1 > rows:
        row = max(1, mrow - len(padded))
    return "".join(f"\033[{row + i};{col}H{ln}" for i, ln in enumerate(padded))


def _timeline_bar(idx, n, width, present=None):
    """A compact scrubber: ─ track, ┼ notch at the present frame, ● playhead."""
    if n <= 1 or width < 3:
        return ""
    pos = round(idx / (n - 1) * (width - 1))
    now = (round(present / (n - 1) * (width - 1))
           if present is not None else None)
    track = "".join(
        f"{fg(*MARKER)}●" if i == pos else
        f"{fg(*MUTED)}┼" if i == now else
        f"{fg(*DIM)}─"
        for i in range(width)
    )
    return track + RESET


def render_radar(lat, lon, location_name, zoom, play_frame=0, playing=True,
                 marker=None, runtime=None, block=True, pan_offset=(0, 0),
                 theme_menu=None, mouse_pos=None, layer="radar", **_):
    lang = runtime.lang if runtime else "en"
    use_24h = runtime.use_24h if runtime else False
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    basemap = _get_basemap(bbox, graph_w, height_cells)

    if layer != "radar" and not getattr(_source, "satellite_frames",
                                        lambda: [])():
        layer = "radar"  # source has no cloud mosaic (IEM fallback)

    # oldest → newest (UTC). The cloud mosaic is hourly, so satellite-only
    # mode scrubs its own (deeper) timeline; radar frames may include future
    frames = _sat_timeline() if layer == "sat" else _source.current_frames()
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
                        warnings=warn_layer)

    # header: play state, frame time, how old/ahead, echo coverage.
    # Both header and footer must never exceed the terminal width: a wrapped
    # line adds a row, scrolling the whole frame up by one.
    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    delta = round((when - present).total_seconds() / 60)
    age = (rs("now", lang) if delta == 0
           else (f"{delta}m" if delta < 0 else f"+{delta}m"))
    tag = f" {rs('forecast', lang)}" if frame.future else ""
    tag += f" · {rs('loading', lang)}" if loading else ""
    icon = "▶" if playing else "⏸"
    # with the cloud layer in, the coverage figure is cloud, not echo
    pct = rs("echo_pct" if layer == "radar" else "cloud_pct",
             lang, pct=f"{echo:.0f}")
    brand = "radar" if layer == "radar" else "radar ☁"

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
        left = f"{fg(*DIM)}{_source.attribution}{RESET}"
        hint = (f"{fg(*DIM)}{rs('hint', lang)}{RESET}"
                if sys.stdout.isatty() else "")
        bar = _timeline_bar(idx, len(frames), min(28, max(10, cols // 3)),
                            present=present_idx)
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
            names, sel, getattr(_source, "theme", None), lang, cols, rows)
    elif mouse_pos and warns and pan_offset == (0, 0):
        overlay = _build_warning_tooltip(
            warns, mouse_pos, bbox, graph_w, height_cells, cols, rows, use_24h)
    if overlay:
        out += "\x00" + overlay
    return out


def main():
    args = radar_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)

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

    theme_arg = (args.theme
                 or os.environ.get("LINECAST_RADAR_THEME", "").strip()
                 or DEFAULT_THEME)
    theme = theme_id(theme_arg)
    if theme is None:
        print(f'Unknown radar theme "{theme_arg}". '
              f'Themes: {", ".join(THEMES)}.', file=sys.stderr)
        sys.exit(2)

    layer = {"radar": "radar", "satellite": "sat", "sat": "sat",
             "both": "both"}.get(
        (args.layer or os.environ.get("LINECAST_RADAR_LAYER", "").strip()
         or "radar").lower())
    if layer is None:
        print('Unknown radar layer. Layers: radar, both, satellite.',
              file=sys.stderr)
        sys.exit(2)

    global _source
    _source = get_source(lat, lon, N_FRAMES, theme)

    if runtime.live:
        import math
        from linecast._radar_sources import _in_conus

        global _live_refresh
        _live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]          # pans; marker stays at the true location
        region = [_in_conus(lat, lon)]

        layer_sel = [layer]

        def on_action(key):
            if key == 's':
                # cycle layers; a no-op on sources without a cloud mosaic
                if not getattr(_source, "satellite_frames", lambda: [])():
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
            global _source
            themes = getattr(_source, "themes", None)
            names = list(themes) if themes else []
            if menu_sel[0] is None:
                if action == 'key:t' and names:
                    ids = list(themes.values())
                    cur = getattr(_source, "theme", None)
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
                if choice != getattr(_source, "theme", None):
                    theme_sel[0] = choice
                    _source = get_source(center[0], center[1], N_FRAMES,
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
            # crossing the CONUS boundary re-picks the source (and is the
            # natural moment to retry LibreWXR after a fallback)
            r = _in_conus(center[0], center[1])
            if r != region[0]:
                region[0] = r
                global _source
                _source = get_source(center[0], center[1], N_FRAMES,
                                     theme_sel[0])
            return True

        live_loop(
            lambda play_frame=0, playing=True, mouse_pos=None, **_: render_radar(
                center[0], center[1], location_name, zoom[0],
                play_frame=play_frame, playing=playing, marker=(lat, lon),
                runtime=runtime, block=False, mouse_pos=mouse_pos,
                pan_offset=(pan_preview[0], pan_preview[1]),
                layer=layer_sel[0],
                theme_menu=((list(_source.themes), menu_sel[0])
                            if menu_sel[0] is not None
                            and getattr(_source, "themes", None) else None)),
            interval=FRAME_STEP,   # pick up a new composite every 5 min
            mouse=True,
            auto_play=True,
            play_interval=0.2,     # animation frame rate (~5 fps)
            on_action=on_action,
            on_drag=on_drag,
            intercept=intercept,
        )
    else:
        # static: play_frame 0 is the present (newest observed) frame
        print(render_radar(lat, lon, location_name, args.zoom,
                           play_frame=0, playing=False,
                           runtime=runtime, layer=layer))


if __name__ == "__main__":
    main()
