#!/usr/bin/env python3
"""Maps — terrain and bathymetry rendered in the terminal.

Elevation from the AWS/Mapzen terrain tiles is painted as a half-block
colour fill: a hypsometric ramp (lowland green through alpine white) shaded
by a north-west sun above sea level, a bathymetric blue ramp below it.
Geography keeps the radar view's braille identity — coastlines and borders
are dark braille strokes over the fill, cities are labelled dots.  Drag to
pan, +/- to zoom, and hover to read the elevation under the pointer.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--print]
            [--search CITY]
"""

import math
import os
import sys
import threading

from linecast._color import bg, fg, RESET, BOLD, interp_stops, BG_PRIMARY
from linecast._elevation import ATTRIBUTION, elevation_grid
from linecast._framebuffer import get_terminal_size, halfblock
from linecast._graphics import live_loop, visible_len
from linecast._location import get_location
from linecast._maps_i18n import ms
from linecast._radar_basemap import BORDER, SEA
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, maps_parser
from linecast.radar import (
    CROSSHAIR, DIM, MARKER, MUTED,
    _ShiftedBasemap, _get_basemap, _panned_place, _shift_grid,
)

# geography over terrain: dark strokes cut into the colour fill (the
# radar palette's dim-on-dark strokes vanish against light terrain)
COAST_STROKE = (22, 32, 52)
BORDER_STROKE = (52, 48, 66)
LABEL_DARK = (28, 32, 44)
LABEL_LIGHT = (232, 232, 240)

# hypsometric tint above sea level (meters)
HYPSO_STOPS = [
    (0, (58, 102, 66)),
    (150, (78, 120, 70)),
    (400, (120, 142, 78)),
    (800, (168, 158, 96)),
    (1300, (178, 142, 94)),
    (2000, (160, 116, 86)),
    (2800, (150, 126, 118)),
    (3600, (190, 180, 175)),
    (4600, (240, 240, 245)),
]

# bathymetric tint below sea level
BATHY_STOPS = [
    (-8000, (12, 20, 48)),
    (-5000, (18, 32, 70)),
    (-3000, (26, 46, 92)),
    (-1500, (36, 62, 112)),
    (-500, (48, 82, 132)),
    (-120, (62, 104, 150)),
    (-20, (80, 130, 168)),
    (0, (96, 150, 180)),
]

# north-west sun, 45° up
_AZIMUTH = math.radians(315.0)
_ZENITH = math.radians(45.0)

_elev_cache = {}     # (bbox, w, h) -> elevation grid
_elev_pending = set()
_elev_lock = threading.Lock()
_terrain_cache = {}  # (bbox, w, h) -> sub-pixel colour buffer
_live_refresh = False


def _view_key(bbox, gw, hc):
    return (tuple(round(v, 4) for v in bbox), gw, hc)


def _get_elevation(bbox, gw, hc, block):
    """Elevation grid for the view; live mode fetches in the background."""
    key = _view_key(bbox, gw, hc)
    with _elev_lock:
        grid = _elev_cache.get(key)
        if grid is not None:
            return grid
        if not block:
            if key in _elev_pending:
                return None
            _elev_pending.add(key)

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines
        fine = elevation_grid(bbox, gw * 2, hc * 4)
        grid = []
        for y in range(hc * 2):
            r0, r1 = fine[y * 2], fine[y * 2 + 1]
            row = []
            for x in range(gw):
                vals = [v for v in (r0[x * 2], r0[x * 2 + 1],
                                    r1[x * 2], r1[x * 2 + 1])
                        if v is not None]
                row.append(sum(vals) / len(vals) if vals else None)
            grid.append(row)
        return grid

    if block:
        grid = load()
        with _elev_lock:
            _elev_cache[key] = grid
        return grid

    def worker():
        try:
            grid = load()
        except Exception:
            grid = None
        with _elev_lock:
            _elev_pending.discard(key)
            if grid is not None:
                if len(_elev_cache) > 3:
                    _elev_cache.clear()
                _elev_cache[key] = grid
        if grid is not None and _live_refresh:
            import signal
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=worker, daemon=True).start()
    return None


def build_terrain_buffer(elev, bbox, w, h):
    """Hillshaded hypsometric/bathymetric colours per sub-pixel.

    `elev` is meters at w×h (h = 2 rows per cell); None renders as plain
    background.  Lambertian shading against a NW sun, with slopes
    exaggerated relative to the pixel size so relief reads at any zoom.
    """
    minlon, minlat, maxlon, maxlat = bbox
    lat_c = (minlat + maxlat) / 2
    px_m = max(1.0, (maxlon - minlon) * 111320.0
               * math.cos(math.radians(lat_c)) / w)
    py_m = max(1.0, (maxlat - minlat) * 110540.0 / h)
    # vertical exaggeration grows with pixel footprint, so wide views still
    # show relief and close views don't saturate to black/white
    zf = min(24.0, max(2.5, px_m / 150.0))

    cos_zen, sin_zen = math.cos(_ZENITH), math.sin(_ZENITH)
    buf = []
    for y in range(h):
        row = elev[y]
        up = elev[y - 1] if y > 0 else row
        down = elev[y + 1] if y < h - 1 else row
        out = []
        for x in range(w):
            e = row[x]
            if e is None:
                out.append(BG_PRIMARY)
                continue
            left = row[x - 1] if x > 0 else e
            right = row[x + 1] if x < w - 1 else e
            above = up[x]
            below = down[x]
            dzdx = ((right if right is not None else e)
                    - (left if left is not None else e)) / (2 * px_m)
            dzdy = ((below if below is not None else e)
                    - (above if above is not None else e)) / (2 * py_m)
            slope = math.atan(zf * math.hypot(dzdx, dzdy))
            aspect = math.atan2(dzdy, -dzdx)
            shade = (cos_zen * math.cos(slope)
                     + sin_zen * math.sin(slope) * math.cos(_AZIMUTH - aspect))
            shade = max(0.0, min(1.0, shade))
            if e <= 0:
                base = interp_stops(BATHY_STOPS, e)
                m = 0.82 + 0.18 * shade  # water: keep the ramp readable
            else:
                base = interp_stops(HYPSO_STOPS, e)
                m = 0.52 + 0.55 * shade
            out.append((min(255, int(base[0] * m)),
                        min(255, int(base[1] * m)),
                        min(255, int(base[2] * m))))
        buf.append(out)
    return buf


def _terrain_buffer(elev, bbox, gw, hc):
    key = _view_key(bbox, gw, hc)
    buf = _terrain_cache.get(key)
    if buf is None:
        buf = build_terrain_buffer(elev, bbox, gw, hc * 2)
        if len(_terrain_cache) > 3:
            _terrain_cache.clear()
        _terrain_cache[key] = buf
    return buf


def compose_terrain(basemap, terrain, overlays, graph_w, height_cells):
    """Terrain fill with braille geography *on top* (inverse of radar).

    The sea's braille stipple is skipped — bathymetry colour is the sea —
    but coast and border strokes stay, cut dark into the fill.  Overlay
    glyphs pick a light or dark ink per cell for contrast.
    """
    lines = []
    for cy in range(height_cells):
        top_row = terrain[cy * 2]
        bot_row = terrain[cy * 2 + 1]
        parts = []
        for cx in range(graph_w):
            ut = top_row[cx] or BG_PRIMARY
            ub = bot_row[cx] or BG_PRIMARY
            ov = overlays.get((cx, cy))
            mask = basemap.dots[cy][cx]
            color = basemap.color[cy][cx]
            if ov is not None or (mask and color != SEA):
                avg = ((ut[0] + ub[0]) // 2, (ut[1] + ub[1]) // 2,
                       (ut[2] + ub[2]) // 2)
                cell_bg = bg(*avg)
                if ov is not None:
                    ch, ink = ov
                    if ink is None:  # contrast-picked label ink
                        lum = (0.2126 * avg[0] + 0.7152 * avg[1]
                               + 0.0722 * avg[2])
                        ink = LABEL_DARK if lum > 120 else LABEL_LIGHT
                    parts.append(f"{cell_bg}{fg(*ink)}{ch}")
                else:
                    stroke = (BORDER_STROKE if color == BORDER
                              else COAST_STROKE)
                    parts.append(f"{cell_bg}{fg(*stroke)}{chr(0x2800 + mask)}")
                continue
            parts.append(halfblock(ut, ub))
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


def _fmt_elev(meters, lang):
    metric = lang != "en" or os.environ.get(
        "WEATHER_UNITS", "").lower() == "metric"
    if metric:
        return f"{round(meters):,} m"
    return f"{round(meters * 3.28084):,} ft"


def render_map(lat, lon, location_name, zoom, marker=None, runtime=None,
               block=True, pan_offset=(0, 0), mouse_pos=None, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    basemap = _get_basemap(bbox, graph_w, height_cells)

    err = None
    loading = False
    elev = None
    if block:
        try:
            elev = _get_elevation(bbox, graph_w, height_cells, True)
        except Exception as exc:
            err = str(exc)
    else:
        elev = _get_elevation(bbox, graph_w, height_cells, False)
        loading = elev is None

    if elev is not None:
        terrain = _terrain_buffer(elev, bbox, graph_w, height_cells)
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

    overlays = {}
    for pos, (ch, _color) in basemap.city_overlays().items():
        overlays[pos] = (ch, None)  # None ink = per-cell contrast pick

    m_lat, m_lon = marker if marker else (lat, lon)
    minlon, minlat, maxlon, maxlat = bbox
    mcol = int((m_lon - minlon) / (maxlon - minlon) * graph_w)
    mrow = int((maxlat - m_lat) / (maxlat - minlat) * height_cells)
    if 0 <= mcol < graph_w and 0 <= mrow < height_cells:
        overlays[(mcol, mrow)] = ("+", MARKER)

    dx, dy = pan_offset
    if dx or dy:
        basemap = _ShiftedBasemap(_shift_grid(basemap.dots, dx, dy, 0),
                                  _shift_grid(basemap.color, dx, dy, None))
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}

    ccol, crow = graph_w // 2, height_cells // 2
    if (mcol + dx, mrow + dy) != (ccol, crow):
        overlays[(ccol, crow)] = ("+", CROSSHAIR)

    map_lines = compose_terrain(basemap, terrain, overlays, graph_w,
                                height_cells)

    # elevation readout: under the pointer when hovering, else view centre
    elev_note = ""
    if elev is not None:
        probe = None
        if mouse_pos is not None:
            pcol, prow = mouse_pos[0] - 1 - dx, mouse_pos[1] - 2 - dy
            if 0 <= pcol < graph_w and 0 <= prow < height_cells:
                probe = elev[prow * 2][pcol]
        if probe is None:
            probe = elev[height_cells][graph_w // 2]  # centre sub-pixel row
        if probe is not None:
            elev_note = f" · {_fmt_elev(probe, lang)}"

    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    tag = f" · {rs('loading', lang)}" if loading else ""

    def _header(place_str):
        return (f"{fg(110, 168, 96)}{BOLD}⬤ maps{RESET}  {fg(*MUTED)}"
                f"{place_str}{RESET}{fg(*DIM)}{elev_note}{tag}{RESET}")

    header = _header(place)
    over = visible_len(header) - cols
    if over > 0 and len(place) > over + 1:
        header = _header(place[:len(place) - over - 1] + "…")
    header += " " * max(0, cols - visible_len(header))

    if err:
        foot = f"{fg(*DIM)}{ms('unavailable', lang, err=err[:40])}{RESET}"
    else:
        left = f"{fg(*DIM)}{ATTRIBUTION}{RESET}"
        hint = (f"{fg(*DIM)}{ms('hint', lang)}{RESET}"
                if sys.stdout.isatty() else "")
        for foot in (f"{left}  {hint}", left):
            if visible_len(foot) <= cols:
                break
    foot += " " * max(0, cols - visible_len(foot))

    return "\n".join([header, *map_lines, foot])


def main():
    args = maps_parser().parse_args()
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

    if runtime.live:
        global _live_refresh
        _live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]
        pan_preview = [0, 0]

        def on_action(key):
            if key == '+':
                new_zoom = max(0.1, zoom[0] / 1.5)
            elif key == '-':
                new_zoom = min(60.0, zoom[0] * 1.5)
            else:
                return False
            if new_zoom == zoom[0]:
                return False
            zoom[0] = new_zoom
            return True

        def on_drag(dcol, drow, done):
            if not done:
                changed = pan_preview != [dcol, drow]
                pan_preview[0], pan_preview[1] = dcol, drow
                return changed
            had_preview = pan_preview[0] or pan_preview[1]
            pan_preview[0] = pan_preview[1] = 0
            if not (dcol or drow):
                return bool(had_preview)
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            lon_span = (zoom[0] * (gw / (hc * 2))
                        / math.cos(math.radians(center[0])))
            center[0] = max(-80.0, min(80.0, center[0] + drow * zoom[0] / hc))
            center[1] += -dcol * lon_span / gw
            if center[1] > 180.0:
                center[1] -= 360.0
            elif center[1] < -180.0:
                center[1] += 360.0
            return True

        live_loop(
            lambda mouse_pos=None, **_: render_map(
                center[0], center[1], location_name, zoom[0],
                marker=(lat, lon), runtime=runtime, block=False,
                pan_offset=(pan_preview[0], pan_preview[1]),
                mouse_pos=mouse_pos),
            interval=3600,  # elevation doesn't change; repaint on input only
            mouse=True,
            on_action=on_action,
            on_drag=on_drag,
        )
    else:
        print(render_map(lat, lon, location_name, args.zoom,
                         runtime=runtime))


if __name__ == "__main__":
    main()
