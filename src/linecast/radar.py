#!/usr/bin/env python3
"""Radar — terminal NEXRAD weather radar (US).

Renders live NWS/NEXRAD base-reflectivity over a braille basemap: the sea is a
braille stipple, coastlines and state/national borders are braille strokes, and
the radar echoes are painted on top as a half-block colour fill.  In live mode,
scroll (or arrow keys) to rewind through the last few hours and watch a storm
approach.

Data: NEXRAD via Iowa Environmental Mesonet (IEM); basemap from Natural Earth.

Usage: radar [--location LAT,LNG | PLACE] [--zoom DEG] [--print] [--search CITY]
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from linecast._color import fg, RESET, BOLD
from linecast._framebuffer import get_terminal_size
from linecast._location import get_location
from linecast._png import decode_rgba
from linecast._radar_basemap import Basemap
from linecast._radar_render import bbox_for, build_radar_buffer, compose
from linecast._radar_source import fetch_frame, frame_times, FRAME_STEP
from linecast._runtime import RuntimeConfig, radar_parser
from linecast._graphics import live_loop, visible_len

MUTED = (150, 155, 170)
DIM = (110, 114, 130)
MARKER = (255, 240, 120)
MAX_REWIND_MIN = 180  # how far back scrubbing can go
N_FRAMES = MAX_REWIND_MIN // 5 + 1  # frames in the rewind window

_basemap_cache = {}

# in-memory cache of decoded frames: key -> (radar_buffer, echo_pct)
_frame_cache = {}
_frame_lock = threading.Lock()
_prefetch_key = None  # (bbox, w, h) currently being prefetched


def _bbox_key(bbox):
    return tuple(round(v, 3) for v in bbox)


def _frame_key(bbox, gw, hc, when):
    return (_bbox_key(bbox), gw, hc, when.strftime("%Y%m%dT%H%M"))


def _load_frame(bbox, gw, hc, when):
    """Return (radar_buffer, echo). Memoised; fetches + decodes on miss."""
    key = _frame_key(bbox, gw, hc, when)
    with _frame_lock:
        hit = _frame_cache.get(key)
    if hit is not None:
        return hit
    png = fetch_frame(bbox, gw, hc * 2, when=when)
    pw, ph, rgba = decode_rgba(png)
    result = build_radar_buffer(rgba, pw, ph, gw, hc)
    with _frame_lock:
        _frame_cache[key] = result
        if len(_frame_cache) > N_FRAMES + 8:  # bound to the rewind window
            for old in list(_frame_cache)[:len(_frame_cache) - (N_FRAMES + 8)]:
                _frame_cache.pop(old, None)
    return result


def _ensure_prefetch(bbox, gw, hc):
    """Warm the rewind window in the background (newest frames first)."""
    global _prefetch_key
    key = (_bbox_key(bbox), gw, hc)
    if _prefetch_key == key:
        return
    _prefetch_key = key
    times = frame_times(N_FRAMES)  # oldest → newest, matching playback order

    def worker():
        with ThreadPoolExecutor(max_workers=4) as pool:
            pool.map(lambda w: _safe_load(bbox, gw, hc, w), times)

    threading.Thread(target=worker, daemon=True).start()


def _safe_load(bbox, gw, hc, when):
    try:
        _load_frame(bbox, gw, hc, when)
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
    _ensure_prefetch(bbox, graph_w, height_cells)  # warm window in background

    frames = frame_times(N_FRAMES)     # oldest → latest (UTC)
    idx = play_frame % N_FRAMES
    when = frames[idx]

    try:
        radar, echo = _load_frame(bbox, graph_w, height_cells, when)
        err = None
    except Exception as exc:
        radar = [[None] * graph_w for _ in range(height_cells * 2)]
        echo, err = 0.0, str(exc)

    overlays = dict(basemap.city_overlays())
    overlays[(graph_w // 2, height_cells // 2)] = ("+", MARKER)  # your location

    map_lines = compose(basemap, radar, overlays, graph_w, height_cells)

    # header: play state, frame time, how old, echo coverage
    place = location_name or f"{lat:.2f}, {lon:.2f}"
    mins_ago = round((frames[-1] - when).total_seconds() / 60)
    age = "now" if mins_ago == 0 else f"-{mins_ago}m"
    icon = "▶" if playing else "⏸"
    header = (f"{fg(*MARKER)}{BOLD}⬤ radar{RESET}  {fg(*MUTED)}{place}"
              f"{RESET}  {fg(*DIM)}{icon} {_fmt_local(when)} · {age} "
              f"· {echo:.0f}% echo{RESET}")
    header += " " * max(0, cols - visible_len(header))

    # footer: attribution + scrubber + controls
    if err:
        foot = f"{fg(*DIM)}radar unavailable ({err[:40]}){RESET}"
    else:
        left = f"{fg(*DIM)}NEXRAD · IEM{RESET}"
        hint = (f"{fg(*DIM)}space play/pause · scroll/←→ step · q quit{RESET}"
                if sys.stdout.isatty() else "")
        bar = _timeline_bar(idx, N_FRAMES, min(28, max(10, cols // 3)))
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

    if not (-130 <= lon <= -60 and 20 <= lat <= 55):
        print("Note: NEXRAD radar covers the continental US; "
              f"{lat:.1f},{lon:.1f} is outside coverage.", file=sys.stderr)

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
        # static: newest frame
        print(render_radar(lat, lon, location_name, args.zoom,
                           play_frame=N_FRAMES - 1, playing=False))


if __name__ == "__main__":
    main()
