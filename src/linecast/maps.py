#!/usr/bin/env python3
"""Maps — terrain and bathymetry rendered in the terminal.

Elevation from the AWS/Mapzen terrain tiles is painted as a half-block
colour fill: a hypsometric ramp (lowland green through alpine white) shaded
by a north-west sun above sea level, a bathymetric blue ramp below it.
Geography keeps the radar view's braille identity — the coastline is the
sea-level contour of the elevation data itself (so it always matches the
fill), borders are Natural Earth braille strokes, cities are labelled
dots.  Drag to pan, +/- to zoom, and hover to read the elevation under
the pointer.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--print]
            [--search CITY]
"""

import math
import os
import sys
import threading

from linecast import _maps_route, _maps_streets, _maps_style, _maps_ui
from linecast._color import (
    bg, fg, RESET, BOLD, color_mode, interp_stops, BG_PRIMARY,
)
from linecast._elevation import ATTRIBUTION, elevation_grid
from linecast._framebuffer import get_terminal_size, halfblock
from linecast._graphics import live_loop, visible_len
from linecast._location import get_location
from linecast._maps_i18n import ms
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._radar_basemap import (
    _BITS, BORDER, DotLayer, _edge_dots,
)
from linecast._theme import lerp_rgb
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, maps_parser
from linecast.radar import (
    CROSSHAIR, DIM, MARKER, MUTED,
    _ShiftedBasemap, _get_basemap, _panned_place, _shift_grid,
)

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
MAX_ZOOM_DEG = 60.0
ZOOM_STEP = 1.5          # matches radar, so the two views feel the same

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

_elev_cache = {}     # (bbox, w, h) -> (elevation grid, coast dot masks)
_elev_pending = set()
_elev_lock = threading.Lock()
_terrain_cache = {}  # (bbox, w, h) -> sub-pixel colour buffer
_street_cache = {}   # (bbox, w, h) -> (fills, ranked DotLayer)
_street_pending = set()
_street_lock = threading.Lock()
_live_refresh = False


def _view_key(bbox, gw, hc):
    """Cache key for a view, at a precision that scales with the zoom.

    A flat 4 dp is ~11 m: ample at a degree or more, but street mode
    reaches 0.0012 deg, where a one-cell pan moves the bbox by less than
    the rounding quantum — every pan would serve the previous grid, and
    min/max latitude can even round to the same number.  Rounding three
    places finer than the span keeps the quantum an order of magnitude
    below a single cell at any zoom, and is exactly today's 4 dp from
    1 deg up (so existing caches and their tests do not move).
    """
    span = bbox[3] - bbox[1]
    nd = 4 if span <= 0 else max(4, 3 + math.ceil(-math.log10(span)))
    return (tuple(round(v, nd) for v in bbox), gw, hc)


def _coast_dots(fine, gw, hc):
    """Braille masks stroking the sea-level contour of the elevation data.

    The coastline is *derived from the fill*: land is a sample above sea
    level, water is a sample at or below it, and a missing sample (None)
    is neither, so a hole in the elevation data never fakes a shoreline
    from either side.
    """
    is_land = [[v is not None and v > 0 for v in row] for row in fine]
    is_water = [[v is not None and v <= 0 for v in row] for row in fine]
    return _edge_dots(is_land, is_water, gw, hc)


def _get_elevation(bbox, gw, hc, block):
    """(elevation grid, coast masks) for the view; live mode fetches in the
    background."""
    key = _view_key(bbox, gw, hc)
    with _elev_lock:
        hit = _elev_cache.get(key)
        if hit is not None:
            return hit
        if not block:
            if key in _elev_pending:
                return None, None
            _elev_pending.add(key)

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines. The fine grid also yields
        # the braille coastline before it is averaged away.
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
        return grid, _coast_dots(fine, gw, hc)

    if block:
        hit = load()
        with _elev_lock:
            _elev_cache[key] = hit
        return hit

    def worker():
        try:
            hit = load()
        except Exception:
            hit = None
        with _elev_lock:
            _elev_pending.discard(key)
            if hit is not None:
                if len(_elev_cache) > 3:
                    _elev_cache.clear()
                _elev_cache[key] = hit
        if hit is not None and _live_refresh:
            import signal
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=worker, daemon=True).start()
    return None, None


def _get_street(bbox, gw, hc, block, lang="en", reserved=()):
    """(fills, ranked layer, label overlays) for the view; live mode
    fetches in the background, exactly as the elevation path does."""
    key = _view_key(bbox, gw, hc) + (lang, tuple(sorted(reserved)))
    with _street_lock:
        hit = _street_cache.get(key)
        if hit is not None:
            return hit
        if not block:
            if key in _street_pending:
                return None, None, None
            _street_pending.add(key)

    def load():
        band, tiles = _maps_streets.fetch_view(bbox, hc)
        if not any(tiles.values()):
            raise RuntimeError(ms('offline', 'en'))
        return _maps_streets.build_street_view(bbox, gw, hc, tiles, band,
                                               lang, reserved)

    if block:
        hit = load()
        with _street_lock:
            _street_cache[key] = hit
        return hit

    def worker():
        try:
            hit = load()
        except Exception:
            hit = None
        with _street_lock:
            _street_pending.discard(key)
            if hit is not None:
                if len(_street_cache) > 3:
                    _street_cache.clear()
                _street_cache[key] = hit
        if hit is not None and _live_refresh:
            import signal
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=worker, daemon=True).start()
    return None, None, None


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


def compose_terrain(basemap, terrain, overlays, graph_w, height_cells,
                    coast=None, strokes=None):
    """Terrain fill with braille geography *on top* (inverse of radar).

    The coastline comes from `coast` — sea-level contour masks derived
    from the elevation data itself, so stroke and fill always agree; the
    basemap's own generalized coast (and its sea stipple) are ignored.
    Natural Earth still supplies the border strokes.  Overlay glyphs pick
    a light or dark ink per cell for contrast; a truthy third tuple
    element renders the glyph bold.

    `strokes` is an ordered list of extra braille layers (anything with
    .dots and .color cell grids, e.g. streets, a route), lowest priority
    first: dot masks OR together, and the last layer with dots in a cell
    owns its ink — the same one-ink-per-cell rule the layers themselves
    resolve by draw order.
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
            bmask = (basemap.dots[cy][cx]
                     if basemap.color[cy][cx] == BORDER else 0)
            cmask = coast[cy][cx] if coast is not None else 0
            smask, sink = 0, None
            if strokes is not None:
                for layer in strokes:
                    m = layer.dots[cy][cx]
                    if m:
                        smask |= m
                        c = layer.color[cy][cx]
                        if c is not None:
                            sink = c
            if ov is not None or bmask or cmask or smask:
                avg = ((ut[0] + ub[0]) // 2, (ut[1] + ub[1]) // 2,
                       (ut[2] + ub[2]) // 2)
                cell_bg = bg(*avg)
                if ov is not None:
                    ch, ink = ov[0], ov[1]
                    if ink is None:  # contrast-picked label ink
                        lum = (0.2126 * avg[0] + 0.7152 * avg[1]
                               + 0.0722 * avg[2])
                        ink = LABEL_DARK if lum > 120 else LABEL_LIGHT
                    if len(ov) > 2 and ov[2]:
                        parts.append(f"{cell_bg}{fg(*ink)}{BOLD}{ch}{RESET}")
                    else:
                        parts.append(f"{cell_bg}{fg(*ink)}{ch}")
                else:
                    if sink is not None:
                        stroke = sink
                    else:
                        stroke = COAST_STROKE if cmask else BORDER_STROKE
                    parts.append(f"{cell_bg}{fg(*stroke)}"
                                 f"{chr(0x2800 + (bmask | cmask | smask))}")
                continue
            parts.append(halfblock(ut, ub))
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


def compose_map(fills, layer, overlays, graph_w, height_cells,
                strokes=None):
    """Street-mode composer: area fills under one ranked braille layer.

    fills:    (hc*2) x gw sub-pixel RGB grid.  An entry may be None,
              meaning "unpainted — the terminal's own background"; the
              16-colour and `none` palettes paint no ground at all.
    layer:    a ranked DotLayer (.dots/.color/.ribbon), one per view.
              Every stroke class has already settled its ink contest by
              rank, so the composer just reads the winner.
    overlays: {(col, row): (char, ink_or_None[, bold])}; ink None picks
              for contrast, a truthy third element renders bold.
    strokes:  extra braille layers over the top (the route), lowest
              priority first — the same ordered-list rule
              compose_terrain uses, because these arrive from outside
              the view's own rank contest.

    A sibling of compose_terrain, not a replacement: terrain resolves a
    basemap, a coast mask and an ordered strokes list per cell, street
    resolves one pre-ranked layer plus the motorway ribbon, and neither
    shape fits the other without a pile of mode conditionals.

    Two degradation rules live here so the rest of street mode never
    thinks about colour depth.  A cell with an unpainted sub-pixel is
    left unpainted entirely — that is the 16-colour "mixed land/water
    cell" rule, where the coast stroke carries the boundary instead of
    a half-and-half block.  And in `none` mode every cell without a
    glyph or a braille dot is a literal space: halfblock() with empty
    escapes returns a bare ▄ that would flood the screen, and the line
    map that results is the mode's whole character.
    """
    plain = color_mode() == "none"
    ribbon_ink = _maps_style.ink("motorway")
    lines = []
    for cy in range(height_cells):
        top_row = fills[cy * 2]
        bot_row = fills[cy * 2 + 1]
        parts = []
        for cx in range(graph_w):
            ut, ub = top_row[cx], bot_row[cx]
            if (cx, cy) in layer.ribbon:
                # Blend toward the motorway ink itself, never the cell's
                # winning stroke — a route crossing here must not tint
                # the ribbon cyan.
                if ut is not None:
                    ut = lerp_rgb(ut, ribbon_ink, _maps_style.RIBBON_BLEND)
                if ub is not None:
                    ub = lerp_rgb(ub, ribbon_ink, _maps_style.RIBBON_BLEND)
            ov = overlays.get((cx, cy))
            mask = layer.dots[cy][cx]
            stroke = layer.color[cy][cx]
            for extra in (strokes or ()):
                m = extra.dots[cy][cx]
                if m:
                    mask |= m
                    if extra.color[cy][cx] is not None:
                        stroke = extra.color[cy][cx]
            painted = ut is not None and ub is not None
            if ov is None and not mask:
                parts.append(halfblock(ut, ub) if painted and not plain
                             else " ")
                continue
            if painted:
                avg = ((ut[0] + ub[0]) // 2, (ut[1] + ub[1]) // 2,
                       (ut[2] + ub[2]) // 2)
                cell_bg = bg(*avg)
            else:
                avg, cell_bg = BG_PRIMARY, ""
            if ov is not None:                  # a glyph always beats braille
                ch, ink = ov[0], ov[1]
                if ink is None:                 # contrast-picked label ink
                    lum = (0.2126 * avg[0] + 0.7152 * avg[1]
                           + 0.0722 * avg[2])
                    ink = LABEL_DARK if lum > 120 else LABEL_LIGHT
                if len(ov) > 2 and ov[2]:
                    parts.append(f"{cell_bg}{fg(*ink)}{BOLD}{ch}{RESET}")
                else:
                    parts.append(f"{cell_bg}{fg(*ink)}{ch}")
                continue
            stroke_fg = fg(*stroke) if stroke is not None else ""
            parts.append(f"{cell_bg}{stroke_fg}{chr(0x2800 + mask)}")
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


def _fmt_elev(meters, lang):
    """The elevation readout — one units heuristic, in _maps_style."""
    return _maps_style.fmt_elev(meters, lang)


_route_layer_cache = {}   # one slot: (route id, view key) -> DotLayer


def _get_route_layer(route, bbox, gw, hc):
    """The route as its own ranked braille layer, memoized per view.

    Cool cyan, deliberately not the marker's yellow and never the
    motorway's amber: two UI accents in total, yellow for your points
    and cyan for your route, so a route can never read as a road.
    """
    if route is None:
        return None
    key = (id(route), _view_key(bbox, gw, hc))
    hit = _route_layer_cache.get(key)
    if hit is not None:
        return hit
    layer = DotLayer(bbox, gw, hc)
    ink = _maps_style.palette().get("route", _maps_style.PALETTE_DARK["route"])
    rank = _maps_style.LINE_STYLES["route"][3]
    layer._draw_lines([route.coords], ink, width=2, rank=rank)
    _route_layer_cache.clear()
    _route_layer_cache[key] = layer
    return layer


def _scale_bar(bbox, graph_w, lang):
    """`├────────┤ 500 m`, or "" when no nice distance fits the view.

    Lives at the left of the footer, ahead of the attribution: it is the
    one piece of furniture that tells you what the map *means*, and it
    is cheaper than a grid.
    """
    best = _maps_style.scale_bar(bbox, graph_w,
                                 _maps_style.use_metric(lang))
    if best is None:
        return ""
    cells, label = best
    return (f"{fg(*DIM)}├{'─' * cells}┤{RESET} "
            f"{fg(*MUTED)}{label}{RESET}  ")


class _ShiftedLayer:
    """Duck-typed stand-in for a ranked DotLayer during a drag preview."""
    __slots__ = ("dots", "color", "ribbon")

    def __init__(self, dots, color, ribbon=()):
        self.dots = dots
        self.color = color
        self.ribbon = set(ribbon)


def _render_terrain(bbox, graph_w, height_cells, block, pan_offset,
                    mouse_pos, marker_cell, dest_cell, lang, route_layer):
    """(map lines, readout, loading, err) for the hillshaded view."""
    basemap = _get_basemap(bbox, graph_w, height_cells)
    err = None
    loading = False
    elev = coast = None
    if block:
        try:
            elev, coast = _get_elevation(bbox, graph_w, height_cells, True)
        except Exception as exc:
            err = str(exc)
    else:
        elev, coast = _get_elevation(bbox, graph_w, height_cells, False)
        loading = elev is None

    if elev is not None:
        terrain = _terrain_buffer(elev, bbox, graph_w, height_cells)
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

    overlays = {}
    for pos, (ch, _color) in basemap.city_overlays().items():
        overlays[pos] = (ch, None)  # None ink = per-cell contrast pick
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, False)
    if dest_cell is not None:
        overlays[dest_cell] = _mark("●", MARKER, False)

    dx, dy = pan_offset
    if dx or dy:
        basemap = _ShiftedBasemap(_shift_grid(basemap.dots, dx, dy, 0),
                                  _shift_grid(basemap.color, dx, dy, None))
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        route_layer = _shift_layer(route_layer, dx, dy)
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}
    overlays = _crosshair(overlays, marker_cell, dx, dy, graph_w,
                          height_cells, False)

    # elevation readout: under the pointer when hovering, else view centre
    readout = ""
    if elev is not None:
        probe = None
        if mouse_pos is not None:
            pcol, prow = mouse_pos[0] - 1 - dx, mouse_pos[1] - 2 - dy
            if 0 <= pcol < graph_w and 0 <= prow < height_cells:
                probe = elev[prow * 2][pcol]
        if probe is None:
            probe = elev[height_cells][graph_w // 2]  # centre sub-pixel row
        if probe is not None:
            readout = f" · {_fmt_elev(probe, lang)}"

    strokes = [route_layer] if route_layer is not None else None
    lines = compose_terrain(basemap, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes)
    return lines, readout, loading, err


def _render_street(bbox, graph_w, height_cells, block, pan_offset,
                   mouse_pos, marker_cell, dest_cell, lang, route_layer):
    """(map lines, readout, loading, err) for the vector-tile view."""
    err = None
    loading = False
    fills = layer = labels = None
    centre = (graph_w // 2, height_cells // 2)
    reserved = (marker_cell, centre) if marker_cell else (centre,)
    if block:
        try:
            fills, layer, labels = _get_street(bbox, graph_w, height_cells,
                                               True, lang, reserved)
        except Exception as exc:
            err = str(exc)
    else:
        fills, layer, labels = _get_street(bbox, graph_w, height_cells,
                                           False, lang, reserved)
        loading = fills is None

    palette = _maps_style.palette()
    if fills is None:
        ground = palette.get("ground")
        fills = [[ground] * graph_w for _ in range(height_cells * 2)]
        layer = _ShiftedLayer([[0] * graph_w for _ in range(height_cells)],
                              [[None] * graph_w for _ in range(height_cells)])
        labels = {}

    overlays = dict(labels)
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, True)
    if dest_cell is not None:
        overlays[dest_cell] = _mark("●", MARKER, True)
    dx, dy = pan_offset
    if dx or dy:
        layer = _ShiftedLayer(
            _shift_grid(layer.dots, dx, dy, 0),
            _shift_grid(layer.color, dx, dy, None),
            {(c + dx, r + dy) for c, r in layer.ribbon})
        fills = _shift_grid(fills, dx, dy * 2, None)
        route_layer = _shift_layer(route_layer, dx, dy)
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}
    overlays = _crosshair(overlays, marker_cell, dx, dy, graph_w,
                          height_cells, True)

    strokes = [route_layer] if route_layer is not None else None
    lines = compose_map(fills, layer, overlays, graph_w, height_cells,
                        strokes=strokes)
    return lines, "", loading, err


def _shift_layer(layer, dx, dy):
    """A braille layer moved with the drag preview, or None."""
    if layer is None:
        return None
    return _ShiftedLayer(_shift_grid(layer.dots, dx, dy, 0),
                         _shift_grid(layer.color, dx, dy, None),
                         {(c + dx, r + dy) for c, r in layer.ribbon})


def _marker_cell(bbox, graph_w, height_cells, m_lat, m_lon):
    """The home marker's cell, or None when it is off view."""
    minlon, minlat, maxlon, maxlat = bbox
    mcol = int((m_lon - minlon) / (maxlon - minlon) * graph_w)
    mrow = int((maxlat - m_lat) / (maxlat - minlat) * height_cells)
    if 0 <= mcol < graph_w and 0 <= mrow < height_cells:
        return mcol, mrow
    return None


def _marker_ink(ink, street):
    """Street mode's motorway takes ANSI 3, leaving bright yellow as the
    only yellow for the marker; terrain mode's inks are unchanged."""
    if street and color_mode() in ("16", "none"):
        return _maps_style.MARKER_16
    return ink


def _mark(glyph, ink, street):
    """A marker/crosshair/destination overlay tuple.  Street mode draws
    them bold: bold silver reads as bright white almost everywhere, so
    the user stays the brightest mark on screen even in a degraded
    palette."""
    if street:
        return (glyph, _marker_ink(ink, True), True)
    return (glyph, ink)


def _crosshair(overlays, cell, dx, dy, graph_w, height_cells, street):
    """Add the centre crosshair unless the marker already sits there."""
    centre = (graph_w // 2, height_cells // 2)
    at = (cell[0] + dx, cell[1] + dy) if cell else None
    if at != centre:
        overlays[centre] = _mark("+", CROSSHAIR, street)
    return overlays


def render_map(lat, lon, location_name, zoom, marker=None, runtime=None,
               block=True, pan_offset=(0, 0), mouse_pos=None,
               view="terrain", search=None, route=None, dest=None,
               note="", helping=False, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    m_lat, m_lon = marker if marker else (lat, lon)
    cell = _marker_cell(bbox, graph_w, height_cells, m_lat, m_lon)

    dest_cell = (_marker_cell(bbox, graph_w, height_cells, dest[0], dest[1])
                 if dest is not None else None)
    route_layer = _get_route_layer(route, bbox, graph_w, height_cells)
    draw = _render_street if view == "street" else _render_terrain
    map_lines, readout, loading, err = draw(
        bbox, graph_w, height_cells, block, pan_offset, mouse_pos,
        cell, dest_cell, lang, route_layer)

    if note:
        readout = f" · {note}"
    elif route is not None:
        readout = f" · {_maps_ui.route_summary(route, lang)}"

    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    tag = f" · {rs('loading', lang)}" if loading else ""
    # The mode word is the affordance that tells the reader modes exist;
    # the footer hint supplies the key.
    mode = f" · {ms('mode_' + view, lang)}"

    def _header(place_str):
        return (f"{fg(110, 168, 96)}{BOLD}⬤ maps{RESET}  {fg(*MUTED)}"
                f"{place_str}{RESET}{fg(*DIM)}{mode}{readout}{tag}{RESET}")

    header = _header(place)
    over = visible_len(header) - cols
    if over > 0 and len(place) > over + 1:
        header = _header(place[:len(place) - over - 1] + "…")
    header += " " * max(0, cols - visible_len(header))

    if err:
        key = 'streets_unavailable' if view == "street" else 'unavailable'
        foot = f"{fg(*DIM)}{ms(key, lang, err=err[:40])}{RESET}"
    else:
        hint = (f"{fg(*DIM)}{ms('hint', lang)}{RESET}"
                if sys.stdout.isatty() else "")
        if view == "street":
            attribs = (_maps_style.ATTRIB_TILES_LONG,
                       _maps_style.ATTRIB_TILES_SHORT)
        else:
            attribs = (ATTRIBUTION,)
        scale = _scale_bar(bbox, graph_w, lang) if view == "street" else ""
        # first rung that fits wins: long+hint, short+hint, short, bare
        ladder = [f"{scale}{fg(*DIM)}{a}{RESET}  {hint}" for a in attribs]
        ladder += [f"{scale}{fg(*DIM)}{attribs[-1]}{RESET}",
                   f"{fg(*DIM)}{attribs[-1]}{RESET}", ""]
        for foot in ladder:
            if visible_len(foot) <= cols:
                break
    foot += " " * max(0, cols - visible_len(foot))

    out = "\n".join([header, *map_lines, foot])
    # Exactly two floating things, one at a time, through the one
    # overlay channel; search wins when both could show.
    if helping and not (search is not None and search.open):
        panel = _maps_ui.help_overlay(cols, rows, lang, route is not None)
        if panel:
            return out + "\x00\033[?1003h" + panel
    if search is not None and search.open:
        # Any-motion mouse reporting is what makes a torn escape
        # sequence likely, and a torn sequence looks like ESC — which is
        # exactly the key guarding a text buffer.  Turn 1003 off for as
        # long as the field is open, and back on when it closes.
        out += ("\x00\033[?1003l"
                + _maps_ui.search_overlay(search, cols, rows, lang))
    elif not block:
        out += "\x00\033[?1003h"
    return out


def main():
    args = maps_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)
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

    # --to resolves through the map's own geocoders, never the weather
    # one: that is settlement-level only and exits the process when the
    # network is down, which is no way to fail a lighthouse.
    dest = None
    if args.to:
        try:
            hit = resolve_place(args.to, runtime.lang, near=(lat, lon))
        except SearchUnavailable:
            print("maps: could not reach a geocoder for --to",
                  file=sys.stderr)
            sys.exit(1)
        if hit is None:
            print(f'No locations matching "{args.to}".', file=sys.stderr)
            sys.exit(1)
        dest = hit

    if runtime.live:
        global _live_refresh
        _live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]
        pan_preview = [0, 0]
        view = [args.view]
        search = _maps_ui.SearchState()
        helping = [False]
        routes = _maps_ui.RouteState(profile=args.profile)
        if dest is not None:
            routes.select(dest.lat, dest.lon, dest.name)
            routes.request((lat, lon))

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
            return True

        def on_action(key):
            if key == '+':
                return zoom_to(zoom[0] / ZOOM_STEP)
            if key == '-':
                return zoom_to(zoom[0] * ZOOM_STEP)
            if key == 'v':
                nxt = _maps_style.MODES.index(view[0]) + 1
                view[0] = _maps_style.MODES[nxt % len(_maps_style.MODES)]
                return True
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

        def intercept(action):
            """Maps owns dispatch: the search panel eats every key while
            it is open, and nothing else here consumes one."""
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
            if action == 'key:/':
                search.start()
                return True
            if action == 'key:d':
                if routes.press((lat, lon)) == "search":
                    search.start("route")
                return True
            if action == 'reset':
                # n / space: the one deliberately destructive key.
                routes.clear()
                return False        # and the loop still recentres
            return False

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

        def render(mouse_pos=None, **_):
            # A search committed from a background reply lands here: the
            # worker cannot move the view itself, so it parks the result
            # and the next repaint applies it.
            hit = search.take_chosen()
            if hit is not None:
                fly_to(hit)
                if search.purpose == "route":
                    routes.select(hit.lat, hit.lon, hit.name)
                    routes.request((lat, lon))
            return render_map(
                center[0], center[1], location_name, zoom[0],
                marker=(lat, lon), runtime=runtime, block=False,
                pan_offset=(pan_preview[0], pan_preview[1]),
                mouse_pos=mouse_pos, view=view[0], search=search,
                route=routes.route, dest=routes.dest,
                note=_maps_ui.route_note(routes, runtime.lang),
                helping=helping[0])

        live_loop(
            render,
            interval=3600,  # elevation doesn't change; repaint on input only
            mouse=True,
            on_action=on_action,
            on_drag=on_drag,
            on_wheel=on_wheel,
            intercept=intercept,
            text_mode=lambda: search.open,
        )
    else:
        found = note = None
        if dest is not None:
            try:
                found = _maps_route.route(args.profile, (lat, lon),
                                          (dest.lat, dest.lon))
            except _maps_route.NoRoute:
                note = ms('dir_none', runtime.lang)
            except _maps_route.RouteUnavailable:
                note = ms('dir_unavailable', runtime.lang)
        print(render_map(lat, lon, location_name, args.zoom,
                         runtime=runtime, view=args.view, route=found,
                         dest=(dest.lat, dest.lon) if dest else None,
                         note=note or ""))


if __name__ == "__main__":
    main()
