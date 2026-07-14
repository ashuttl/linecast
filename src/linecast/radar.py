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
from linecast._framebuffer import get_terminal_size
from linecast._location import get_location
from linecast._radar_basemap import Basemap
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
    return result


def _ensure_prefetch(bbox, gw, hc):
    """Warm the whole frame window in the background, in playback order."""
    global _prefetch_key
    key = (_bbox_key(bbox), gw, hc)
    if _prefetch_key == key:
        return
    _prefetch_key = key
    frames = _source.current_frames()  # oldest → newest, matching playback

    def worker():
        with ThreadPoolExecutor(max_workers=4) as pool:
            pool.map(lambda f: _safe_load(bbox, gw, hc, f), frames)

    threading.Thread(target=worker, daemon=True).start()


def _safe_load(bbox, gw, hc, frame):
    try:
        _load_frame(bbox, gw, hc, frame)
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


def _fmt_local(dt_utc):
    return dt_utc.astimezone().strftime("%-I:%M %p").lstrip("0")


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


def render_radar(lat, lon, location_name, zoom, play_frame=0, playing=True, **_):
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    basemap = _get_basemap(bbox, graph_w, height_cells)

    frames = _source.current_frames()   # oldest → newest (UTC); may include future
    if not frames:
        msg = f"{fg(*DIM)}no radar frames available{RESET}"
        return "\n".join([msg] + [""] * (height_cells + 1))
    _ensure_prefetch(bbox, graph_w, height_cells)  # warm window in background

    idx = play_frame % len(frames)
    frame = frames[idx]
    when = frame.time
    present = max((f.time for f in frames if not f.future),
                  default=frames[-1].time)

    try:
        radar, echo = _load_frame(bbox, graph_w, height_cells, frame)
        err = None
    except Exception as exc:
        radar = [[None] * graph_w for _ in range(height_cells * 2)]
        echo, err = 0.0, str(exc)

    overlays = dict(basemap.city_overlays())
    overlays[(graph_w // 2, height_cells // 2)] = ("+", MARKER)  # your location

    map_lines = compose(basemap, radar, overlays, graph_w, height_cells)

    # header: play state, frame time, how old/ahead, echo coverage
    place = location_name or f"{lat:.2f}, {lon:.2f}"
    delta = round((when - present).total_seconds() / 60)
    age = "now" if delta == 0 else (f"{delta}m" if delta < 0 else f"+{delta}m")
    tag = " forecast" if frame.future else ""
    icon = "▶" if playing else "⏸"
    header = (f"{fg(*MARKER)}{BOLD}⬤ radar{RESET}  {fg(*MUTED)}{place}"
              f"{RESET}  {fg(*DIM)}{icon} {_fmt_local(when)} · {age}{tag} "
              f"· {echo:.0f}% echo{RESET}")
    header += " " * max(0, cols - visible_len(header))

    # footer: attribution + scrubber + controls
    if err:
        foot = f"{fg(*DIM)}radar unavailable ({err[:40]}){RESET}"
    else:
        left = f"{fg(*DIM)}{_source.attribution}{RESET}"
        hint = (f"{fg(*DIM)}space play/pause · scroll/←→ step · q quit{RESET}"
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
            location_name = _reverse_geocode(lat, lon)[0] or ""
        except Exception:
            location_name = ""

    global _source
    _source = get_source(lat, lon, N_FRAMES)

    if runtime.live:
        live_loop(
            lambda play_frame=0, playing=True, **_: render_radar(
                lat, lon, location_name, args.zoom,
                play_frame=play_frame, playing=playing),
            interval=FRAME_STEP,   # pick up a new composite every 5 min
            mouse=True,
            auto_play=True,
            play_interval=0.2,     # animation frame rate (~5 fps)
        )
    else:
        # static: the present (newest observed) frame
        frames = _source.current_frames()
        present_idx = max((i for i, f in enumerate(frames) if not f.future),
                          default=len(frames) - 1) if frames else 0
        print(render_radar(lat, lon, location_name, args.zoom,
                           play_frame=present_idx, playing=False))


if __name__ == "__main__":
    main()
