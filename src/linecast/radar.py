#!/usr/bin/env python3
"""Radar — terminal weather radar over a braille basemap.

Renders live base-reflectivity over a braille basemap: the sea is a braille
stipple, coastlines and state/national borders are braille strokes, and the
radar echoes are painted on top as a half-block colour fill.  In live mode,
scroll (or arrow keys) to rewind through the last few hours and watch a storm
approach.

Data: NEXRAD via Iowa Environmental Mesonet (IEM) for the continental US;
RainViewer (global, plus forecast frames) elsewhere. Basemap from Natural Earth.

Usage: radar [--location LAT,LNG | PLACE] [--zoom DEG] [--print] [--search CITY]
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from linecast._color import fg, RESET, BOLD
from linecast._framebuffer import get_terminal_size, fmt_time_dt
from linecast._location import get_location
from linecast._radar_basemap import Basemap
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for, build_radar_buffer, compose
from linecast._radar_source import FRAME_STEP
from linecast._radar_sources import get_source
from linecast._runtime import RuntimeConfig, radar_parser
from linecast._graphics import live_loop, visible_len

MUTED = (150, 155, 170)
DIM = (110, 114, 130)
MARKER = (255, 240, 120)
MAX_REWIND_MIN = 180  # how far back scrubbing can go
N_FRAMES = MAX_REWIND_MIN // 5 + 1  # frames in the rewind window

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


def _frame_key(bbox, gw, hc, frame):
    return (_bbox_key(bbox), gw, hc, frame.time.strftime("%Y%m%dT%H%M"))


def _load_frame(bbox, gw, hc, frame):
    """Return (radar_buffer, echo). Memoised; fetches + decodes on miss."""
    key = _frame_key(bbox, gw, hc, frame)
    with _frame_lock:
        hit = _frame_cache.get(key)
    if hit is not None:
        return hit
    pw, ph, rgba = _source.frame_rgba(bbox, gw, hc, frame)
    result = build_radar_buffer(rgba, pw, ph, gw, hc)
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


def _cached_frame(bbox, gw, hc, frame):
    """Cache-only lookup; never touches the network."""
    with _frame_lock:
        return _frame_cache.get(_frame_key(bbox, gw, hc, frame))


def _nearest_cached(bbox, gw, hc, when):
    """The cached frame for this view closest in time to `when`, or None."""
    prefix = (_bbox_key(bbox), gw, hc)
    want = when.strftime("%Y%m%dT%H%M")
    with _frame_lock:
        stamps = [k[3] for k in _frame_cache if k[:3] == prefix]
        if not stamps:
            return None
        best = min(stamps, key=lambda s: abs(int(s.replace("T", "")) -
                                             int(want.replace("T", ""))))
        return _frame_cache.get(prefix + (best,))


def _ensure_prefetch(bbox, gw, hc, start_idx=0):
    """Warm the frame window in the background, displayed frame first.

    A view change (pan/zoom/resize) bumps the generation so a superseded
    worker stops issuing fetches for a view nobody is looking at.
    """
    global _prefetch_key, _prefetch_gen
    key = (_bbox_key(bbox), gw, hc)
    if _prefetch_key == key:
        return
    _prefetch_key = key
    _prefetch_gen += 1
    gen = _prefetch_gen
    frames = _source.current_frames()
    ordered = frames[start_idx:] + frames[:start_idx]  # current frame first

    def worker():
        loaded = 0

        def load(f):
            nonlocal loaded
            if gen != _prefetch_gen:
                return  # view moved on; don't fetch for a stale bbox
            if _safe_load(bbox, gw, hc, f):
                loaded += 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(load, ordered))
        if gen == _prefetch_gen and loaded == 0:
            # nothing arrived (offline?) — allow a later render to retry
            global _prefetch_key
            _prefetch_key = None

    threading.Thread(target=worker, daemon=True).start()


def _safe_load(bbox, gw, hc, frame):
    try:
        _load_frame(bbox, gw, hc, frame)
        return True
    except Exception:
        return False


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


def _timeline_bar(idx, n, width):
    """A compact scrubber: ─ track with a ● playhead at frame idx."""
    if n <= 1 or width < 3:
        return ""
    pos = round(idx / (n - 1) * (width - 1))
    track = "".join(
        f"{fg(*MARKER)}●" if i == pos else f"{fg(*DIM)}─"
        for i in range(width)
    )
    return track + RESET


def render_radar(lat, lon, location_name, zoom, play_frame=0, playing=True,
                 marker=None, runtime=None, block=True, **_):
    lang = runtime.lang if runtime else "en"
    use_24h = runtime.use_24h if runtime else False
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    basemap = _get_basemap(bbox, graph_w, height_cells)

    frames = _source.current_frames()   # oldest → newest (UTC); may include future
    if not frames:
        msg = f"{fg(*DIM)}{rs('no_frames', lang)}{RESET}"
        return "\n".join([msg] + [""] * (height_cells + 1))

    idx = play_frame % len(frames)
    frame = frames[idx]
    when = frame.time
    present = max((f.time for f in frames if not f.future),
                  default=frames[-1].time)
    _ensure_prefetch(bbox, graph_w, height_cells, start_idx=idx)

    err = None
    loading = False
    if block:
        # static mode: fetch the displayed frame synchronously
        try:
            radar, echo = _load_frame(bbox, graph_w, height_cells, frame)
        except Exception as exc:
            radar = [[None] * graph_w for _ in range(height_cells * 2)]
            echo, err = 0.0, str(exc)
    else:
        # live mode: never block a render on the network — show the nearest
        # cached frame (radar pops in as the prefetcher lands frames)
        hit = _cached_frame(bbox, graph_w, height_cells, frame)
        if hit is None:
            hit = _nearest_cached(bbox, graph_w, height_cells, when)
            loading = True
        if hit is not None:
            radar, echo = hit
        else:
            radar, echo = [[None] * graph_w for _ in range(height_cells * 2)], 0.0

    overlays = dict(basemap.city_overlays())
    # "your location" marker, pinned geographically (panning can move it
    # off-centre or out of view entirely)
    m_lat, m_lon = marker if marker else (lat, lon)
    minlon, minlat, maxlon, maxlat = bbox
    mcol = int((m_lon - minlon) / (maxlon - minlon) * graph_w)
    mrow = int((maxlat - m_lat) / (maxlat - minlat) * height_cells)
    if 0 <= mcol < graph_w and 0 <= mrow < height_cells:
        overlays[(mcol, mrow)] = ("+", MARKER)

    map_lines = compose(basemap, radar, overlays, graph_w, height_cells)

    # header: play state, frame time, how old/ahead, echo coverage
    place = location_name or f"{lat:.2f}, {lon:.2f}"
    delta = round((when - present).total_seconds() / 60)
    age = (rs("now", lang) if delta == 0
           else (f"{delta}m" if delta < 0 else f"+{delta}m"))
    tag = f" {rs('forecast', lang)}" if frame.future else ""
    tag += f" · {rs('loading', lang)}" if loading else ""
    icon = "▶" if playing else "⏸"
    header = (f"{fg(*MARKER)}{BOLD}⬤ radar{RESET}  {fg(*MUTED)}{place}"
              f"{RESET}  {fg(*DIM)}{icon} {_fmt_local(when, use_24h)} · {age}{tag} "
              f"· {rs('echo_pct', lang, pct=f'{echo:.0f}')}{RESET}")
    header += " " * max(0, cols - visible_len(header))

    # footer: attribution + scrubber + controls
    if err:
        foot = f"{fg(*DIM)}{rs('radar_unavailable', lang, err=err[:40])}{RESET}"
    else:
        left = f"{fg(*DIM)}{_source.attribution}{RESET}"
        hint = (f"{fg(*DIM)}{rs('hint', lang)}{RESET}"
                if sys.stdout.isatty() else "")
        bar = _timeline_bar(idx, len(frames), min(28, max(10, cols // 3)))
        foot = f"{left}  {bar}  {hint}"
    foot += " " * max(0, cols - visible_len(foot))

    return "\n".join([header, *map_lines, foot])


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

    global _source
    _source = get_source(lat, lon, N_FRAMES)

    if runtime.live:
        import math
        from linecast._radar_sources import _in_conus

        global _live_refresh
        _live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]          # pans; marker stays at the true location
        region = [_in_conus(lat, lon)]

        def on_action(key):
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

        def on_drag(dcol, drow):
            # Dragging pulls the map: content follows the pointer, so the
            # view centre moves the opposite way.
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            lon_span = zoom[0] * (gw / (hc * 2)) / math.cos(math.radians(center[0]))
            center[0] = max(-80.0, min(80.0, center[0] + drow * zoom[0] / hc))
            center[1] += -dcol * lon_span / gw
            if center[1] > 180.0:
                center[1] -= 360.0
            elif center[1] < -180.0:
                center[1] += 360.0
            # crossing the CONUS boundary switches radar source (IEM ↔ RainViewer)
            r = _in_conus(center[0], center[1])
            if r != region[0]:
                region[0] = r
                global _source
                _source = get_source(center[0], center[1], N_FRAMES)
            return True

        live_loop(
            lambda play_frame=0, playing=True, **_: render_radar(
                center[0], center[1], location_name, zoom[0],
                play_frame=play_frame, playing=playing, marker=(lat, lon),
                runtime=runtime, block=False),
            interval=FRAME_STEP,   # pick up a new composite every 5 min
            mouse=True,
            auto_play=True,
            play_interval=0.2,     # animation frame rate (~5 fps)
            on_action=on_action,
            on_drag=on_drag,
        )
    else:
        # static: the present (newest observed) frame
        frames = _source.current_frames()
        present_idx = max((i for i, f in enumerate(frames) if not f.future),
                          default=len(frames) - 1) if frames else 0
        print(render_radar(lat, lon, location_name, args.zoom,
                           play_frame=present_idx, playing=False,
                           runtime=runtime))


if __name__ == "__main__":
    main()
