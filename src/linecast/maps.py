#!/usr/bin/env python3
"""Maps — a street map and a terrain map in the terminal.

`--view street` (the default) is in _maps_streets and friends: vector
tiles rasterised into fills, braille strokes and labels.  Only a handful
of things on it can afford a label, so the pointer is the other half of
reading it: hover names whatever owns the ink under it and lights that
whole feature up (_maps_hover).

`--view terrain` lives here, drawn in a schematic register: colour is
categorical (flat land-cover fields, flat hypsometric bands climbing
green through straw and ochre into mauve, lavender and summit white)
while a multidirectional hillshade underneath carries everything
physical — the grammar of a geologic map rather than a photograph.
The sea is the one smooth gradient, falling to a near-black navy
abyss.  Lakes and rivers are the one thing elevation cannot tell you —
a terrarium sample over a lake is just the height of its surface — so
the inland water comes from the street tiles and joins the shoreline
the elevation already draws.
Geography keeps the radar view's braille identity: the coastline is the
sea-level contour of the elevation data itself (so it always matches
the fill), borders are Natural Earth braille strokes, cities are
labelled dots.  Drag to pan, +/- to zoom, and hover to read the
elevation under the pointer.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--view MODE]
            [--print] [--search CITY]
"""

import functools
import math
import os
import sys
import threading
from collections import namedtuple

from linecast import (
    _builtup, _globe, _globe_now, _maps_hover, _maps_route, _maps_streets,
    _maps_style, _maps_ui,
)
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
from linecast._theme import lerp_rgb, themed
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, debug_log, maps_parser
from linecast.radar import (
    CROSSHAIR, DIM, MARKER, MUTED,
    _ShiftedBasemap, _get_basemap, _panned_place, _shift_grid,
)

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
# past _globe.ZOOM_DEG the terrain view is an orthographic globe; at
# the ceiling the whole planet fits the screen's height with a margin
# (the disk's diameter is 2·(180/π) ≈ 114.6 zoom-degrees)
MAX_ZOOM_DEG = 130.0
ZOOM_STEP = 1.5          # matches radar, so the two views feel the same
ZOOM_SETTLE = 0.3        # seconds of zoom quiet before a fetch may start

# geography over terrain: dark strokes cut into the colour fill (the
# radar palette's dim-on-dark strokes vanish against light terrain).
# Every terrain ink below passes through _theme.themed once, at import:
# the calibrated luminance ladder stays, the hue family follows the
# terminal's own theme.
COAST_STROKE = themed((22, 32, 52))
BORDER_STROKE = themed((52, 48, 66))
LABEL_DARK = themed((28, 32, 44))
LABEL_LIGHT = themed((232, 232, 240))

# the marker is radar's, re-inked: on any theme it should be the
# theme's own bright accent, not an absolute yellow
MARKER = themed(MARKER)
_BADGE = themed((110, 168, 96))     # the header's "⬤ maps" green

# Inland water: lakes and rivers are *not* on the bathymetric ramp.  A
# terrarium sample reports the elevation of the water's surface, so a
# lake is indistinguishable from the meadow beside it — the polygons
# come from the same vector tiles street mode uses, and the ramps never
# have to guess.  One flat tint, because a lake surface is flat.
LAKE_FILL = themed((74, 118, 156))
RIVER_STROKE = themed((108, 152, 190))

# Hypsometric bands above sea level (meters) — *bands*, not a gradient:
# land takes the flat colour of its band and the boundaries read as
# contours, the way a geologic map draws provinces.  The run climbs out
# of the greens through straw and ochre into mauve and pale lavender
# before summit white — high country earns the purples.
HYPSO_STOPS = [
    (0, (96, 138, 92)),
    (150, (124, 152, 88)),
    (400, (156, 168, 92)),
    (800, (190, 178, 104)),
    (1300, (198, 162, 106)),
    (2000, (176, 140, 118)),
    (2800, (160, 140, 158)),
    (3600, (196, 182, 208)),
    (4600, (240, 240, 248)),
]
HYPSO_STOPS = [(m, themed(c)) for m, c in HYPSO_STOPS]

# Bathymetric tint below sea level — deliberately a smooth gradient
# where the land is banded: the sea is the one continuous field on the
# map, falling away to a near-black navy abyss.
BATHY_STOPS = [
    (-8000, (6, 12, 30)),
    (-5000, (12, 22, 48)),
    (-3500, (18, 34, 68)),
    (-2000, (30, 56, 98)),
    (-1000, (44, 80, 124)),
    (-200, (66, 112, 152)),
    (-50, (96, 148, 178)),
    (0, (120, 170, 194)),
]
BATHY_STOPS = [(m, themed(c)) for m, c in BATHY_STOPS]


def _hypso_band(e):
    """The flat colour of the band `e` falls in."""
    for lim, c in reversed(HYPSO_STOPS):
        if e >= lim:
            return c
    return HYPSO_STOPS[0][1]

# land-cover tints by grid index (0 = no cover, stays on the ramp)
_COVER_RGB = [None] + [_maps_style.COVER_COLOR[k]
                       for k in _maps_style.COVER_ORDER]

# A north-west sun 45° up, with two flanking lights a quarter turn to
# either side: one azimuth lights every NW-SE ridge identically and
# drops every SE face into the same flat dark — the flanks are what let
# a spur read differently from the ridge it leaves.  Weights sum to 1,
# so the tonal range is the single sun's.
_ZENITH = math.radians(45.0)
_SUNS = tuple((wgt, math.cos(math.radians(az)), math.sin(math.radians(az)))
              for wgt, az in ((0.55, 315.0), (0.225, 270.0), (0.225, 360.0)))

# aerial perspective on land: shadow does not just darken, it cools
# toward slate; full light warms faintly toward sun-colour.  Both are
# small nudges after the multiply — the ramp still owns the hue.
_SHADOW_TINT = themed((40, 48, 72))
_LIGHT_TINT = themed((255, 248, 228))

_elev_cache = {}     # (bbox, w, h) -> (elevation grid, coast dot masks)
_elev_pending = set()
_elev_lock = threading.Lock()
_globe_cache = {}    # (lat, lon, zoom, w, h) -> GlobeView
_globe_pending = set()
_terrain_cache = {}  # (bbox, w, h) -> sub-pixel colour buffer
_street_cache = {}   # (bbox, w, h) -> (fills, ranked DotLayer)
_street_pending = set()
_street_lock = threading.Lock()
_live_refresh = False
_fetch_hold = [0.0]  # monotonic deadline; live zoom taps push it forward


def _fetch_held():
    """True while a live zoom gesture is still in flight."""
    import time
    return time.monotonic() < _fetch_hold[0]


def _hold_fetches():
    """Zoom taps repaint instantly, but only the view you stop on fetches.

    Each intermediate zoom is its own cache key, so without a hold a
    run of `-` presses from the default view out to the planet spawns a
    full tile fetch per step — and they all fight the one view actually
    asked for.  Each tap pushes the deadline instead; a timer nudges a
    repaint once the last deadline passes, and that repaint is the one
    that reaches the network.
    """
    import time
    deadline = time.monotonic() + ZOOM_SETTLE
    _fetch_hold[0] = deadline

    def settle():
        import signal
        time.sleep(ZOOM_SETTLE + 0.02)
        if _fetch_hold[0] == deadline:
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=settle, daemon=True).start()


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


def _coast_dots(fine, gw, hc, water=None):
    """Braille masks stroking the shoreline of the elevation data.

    The coastline is *derived from the fill*: land is a sample above sea
    level, water is a sample at or below it, and a missing sample (None)
    is neither, so a hole in the elevation data never fakes a shoreline
    from either side.

    `water` is the tiles' inland mask at the same dot resolution, and it
    joins the same two masks rather than getting a stroke pass of its
    own — one union, one boundary, so a lake shore is drawn by exactly
    the rule that draws a sea shore and the two can never disagree where
    a river meets the sea.
    """
    is_land, is_water = [], []
    for dy, row in enumerate(fine):
        wet = water[dy] if water is not None else None
        is_land.append([v is not None and v > 0 and not (wet and wet[dx])
                        for dx, v in enumerate(row)])
        is_water.append([(v is not None and v <= 0) or bool(wet and wet[dx])
                         for dx, v in enumerate(row)])
    return _edge_dots(is_land, is_water, gw, hc)


def _water_subpixels(water, gw, hc):
    """The dot-resolution inland mask reduced to the fill's sub-pixels.

    A sub-pixel spans 2x2 dots and counts as water on the same >=2-of-4
    rule street mode's fills use, so a pond too small to hold a
    half-block does not tint one.
    """
    out = []
    for spy in range(hc * 2):
        top, bot = water[spy * 2], water[spy * 2 + 1]
        out.append([top[x * 2] + top[x * 2 + 1]
                    + bot[x * 2] + bot[x * 2 + 1] >= 2 for x in range(gw)])
    return out


def _tile_water(bbox, gw, hc):
    """(inland water dot mask, river layer) for the view, or (None, None).

    Terrain mode's one network dependency beyond the elevation tiles,
    and an optional one: every failure degrades to the sea-level-only
    map this used to be, never to an error.
    """
    try:
        band, tiles = _maps_streets.fetch_view(bbox, hc)
        if not any(tiles.values()):
            return None, None, None, None
        return _maps_streets.build_water_view(bbox, gw, hc, tiles, band,
                                              RIVER_STROKE)
    except Exception as exc:
        debug_log(f"terrain inland water unavailable: {exc}")
        return None, None, None, None


class TerrainView(namedtuple("TerrainView", "elev coast water rivers cover")):
    """One view's ground truth: the averaged elevation grid, the braille
    shoreline, the sub-pixel inland water mask, the river layer and the
    sub-pixel land-cover grid.

    The last three are None whenever the vector tiles could not be read;
    every consumer treats that as "no inland water or cover known", which
    is exactly what terrain mode drew before them."""
    __slots__ = ()


_EMPTY_TERRAIN = TerrainView(None, None, None, None, None)


def _get_elevation(bbox, gw, hc, block):
    """A TerrainView for the view; live mode fetches in the background."""
    key = _view_key(bbox, gw, hc)
    with _elev_lock:
        hit = _elev_cache.get(key)
        if hit is not None:
            return hit
        if not block:
            if key in _elev_pending or _fetch_held():
                return _EMPTY_TERRAIN
            _elev_pending.add(key)

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines. The fine grid also yields
        # the braille coastline before it is averaged away.
        fine = elevation_grid(bbox, gw * 2, hc * 4)
        water, rivers, cover, ocean = _tile_water(bbox, gw, hc)
        if _builtup.enabled():
            # measured settlement fills wherever the vector story left
            # bare ground; the street-density proxy still runs, so the
            # two agree where both know and cover for each other's gaps
            try:
                bu = _builtup.builtup_grid(bbox, gw, hc * 2)
            except Exception as exc:
                debug_log(f"builtup layer unavailable: {exc}")
                bu = None
            if bu is not None:
                if cover is None:
                    cover = [bytearray(gw) for _ in range(hc * 2)]
                grades = [(lo, _maps_style.COVER_ORDER.index(k) + 1)
                          for lo, k in _maps_style.COVER_BUILTUP_GRADES]
                settlement = {gid for _, gid in grades}
                floor = grades[-1][0]
                for crow, brow in zip(cover, bu):
                    for x, f in enumerate(brow):
                        if f >= floor and (not crow[x]
                                           or crow[x] in settlement):
                            crow[x] = next(gid for lo, gid in grades
                                           if f >= lo)
        if ocean is not None:
            # The OSM coastline outranks the elevation data over the
            # sea, without appeal: coastal DEMs report tidal water as a
            # mudflat's metre, a pier's five, a bridge deck's forty —
            # thresholding on "clearly dry land" leaves every harbor
            # green-flecked.  Where the tiles say sea, the sample is
            # sea; real bathymetry (already merged in) stays, anything
            # else drops just under the waterline — and the fill, the
            # derived coastline and the readout all follow.
            for frow, orow in zip(fine, ocean):
                for dx, o in enumerate(orow):
                    if o:
                        e = frow[dx]
                        frow[dx] = -0.5 if e is None else min(e, -0.5)
        grid = []
        for y in range(hc * 2):
            r0, r1 = fine[y * 2], fine[y * 2 + 1]
            row = []
            for x in range(gw):
                vals = [v for v in (r0[x * 2], r0[x * 2 + 1],
                                    r1[x * 2], r1[x * 2 + 1])
                        if v is not None]
                if not vals:
                    row.append(None)
                    continue
                # a shoreline sub-pixel averages land and sea dots, and
                # the plain mean lands above zero — every coast bulges a
                # sub-pixel of low green into the water.  The same
                # >=2-of-4 rule as _water_subpixels: enough wet dots
                # make a wet sub-pixel, averaged over the wet dots only,
                # so the fill agrees with the coastline drawn at dot
                # resolution.
                wet = [v for v in vals if v <= 0]
                if len(wet) >= 2:
                    row.append(sum(wet) / len(wet))
                else:
                    row.append(sum(vals) / len(vals))
            grid.append(row)
        return TerrainView(
            grid, _coast_dots(fine, gw, hc, water),
            _water_subpixels(water, gw, hc) if water is not None else None,
            rivers, cover)

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
    return _EMPTY_TERRAIN


def _get_street(bbox, gw, hc, block, lang="en", reserved=()):
    """(fills, ranked layer, label overlays) for the view; live mode
    fetches in the background, exactly as the elevation path does."""
    key = _view_key(bbox, gw, hc) + (lang, tuple(sorted(reserved)))
    with _street_lock:
        hit = _street_cache.get(key)
        if hit is not None:
            return hit
        if not block:
            if key in _street_pending or _fetch_held():
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


def build_terrain_buffer(elev, bbox, w, h, water=None, cover=None):
    """Hillshaded hypsometric/bathymetric colours per sub-pixel.

    `elev` is meters at w×h (h = 2 rows per cell); None renders as plain
    background.  Lambertian shading against a NW sun, with slopes
    exaggerated relative to the pixel size so relief reads at any zoom.

    `water` is the optional sub-pixel inland mask.  It wins over both
    ramps, at either sign: a lake takes the lake tint whether it sits on
    a mountainside or four hundred metres below the sea, because it is
    inland water in both cases and the bathymetric ramp would read as
    open ocean.  Its shading is nearly flat — a lake surface is flat,
    and the land slope underneath it is not its slope.

    `cover` is the optional sub-pixel land-cover grid (indices into
    style.COVER_ORDER, 0 = none).  A covered land sub-pixel blends the
    class tint over its hypsometric base — hillshade carries the relief,
    colour carries the ground.  Cover never touches water at either
    sign: a forest polygon generalised over a fjord stays the fjord's.
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
    blend = _maps_style.COVER_BLEND
    buf = []
    for y in range(h):
        row = elev[y]
        up = elev[y - 1] if y > 0 else row
        down = elev[y + 1] if y < h - 1 else row
        wet_row = water[y] if water is not None else None
        cov_row = cover[y] if cover is not None else None
        out = []
        for x in range(w):
            e = row[x]
            wet = wet_row is not None and wet_row[x]
            if e is None:
                # known water over unknown ground still reads as water
                out.append(LAKE_FILL if wet else BG_PRIMARY)
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
            cos_sl, sin_sl = math.cos(slope), math.sin(slope)
            ca, sa = math.cos(aspect), math.sin(aspect)
            shade = 0.0
            for wgt, c_az, s_az in _SUNS:
                s_ = cos_zen * cos_sl + sin_zen * sin_sl * (c_az * ca
                                                            + s_az * sa)
                if s_ > 0.0:
                    shade += wgt * s_
            shade = min(1.0, shade)
            if wet:
                base = LAKE_FILL
                m = 0.92 + 0.08 * shade
            elif e <= 0:
                base = interp_stops(BATHY_STOPS, e)
                m = 0.82 + 0.18 * shade  # water: keep the ramp readable
            else:
                base = _hypso_band(e)
                if cov_row is not None and cov_row[x]:
                    cc = _COVER_RGB[cov_row[x]]
                    base = (base[0] + (cc[0] - base[0]) * blend,
                            base[1] + (cc[1] - base[1]) * blend,
                            base[2] + (cc[2] - base[2]) * blend)
                m = 0.58 + 0.50 * shade
                r, g, b = base[0] * m, base[1] * m, base[2] * m
                t = (1.0 - shade) * 0.22
                r += (_SHADOW_TINT[0] - r) * t
                g += (_SHADOW_TINT[1] - g) * t
                b += (_SHADOW_TINT[2] - b) * t
                t = (shade - 0.72) * 0.45
                if t > 0.0:
                    r += (_LIGHT_TINT[0] - r) * t
                    g += (_LIGHT_TINT[1] - g) * t
                    b += (_LIGHT_TINT[2] - b) * t
                out.append((min(255, int(r)), min(255, int(g)),
                            min(255, int(b))))
                continue
            out.append((min(255, int(base[0] * m)),
                        min(255, int(base[1] * m)),
                        min(255, int(base[2] * m))))
        buf.append(out)
    return buf


def _terrain_buffer(elev, bbox, gw, hc, water=None, cover=None):
    # the tile flags are part of the key: the same view rendered once
    # offline and once with tiles is two different pictures
    key = _view_key(bbox, gw, hc) + (water is not None, cover is not None)
    buf = _terrain_cache.get(key)
    if buf is None:
        buf = build_terrain_buffer(elev, bbox, gw, hc * 2, water, cover)
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
            bmask = (basemap.dots[cy][cx] if basemap is not None
                     and basemap.color[cy][cx] == BORDER else 0)
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
                strokes=None, hot=None, hot_glyphs=None):
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
    hot:      cells whose *braille* draws the feature under the pointer.
              They keep their own ink, lifted toward the top of its
              ladder and set bold — no fourth accent, and bold is the
              same lift one rung coarser once the palette is 16 colours.
    hot_glyphs: cells whose *character* names that same feature — its
              own label, or the glyph if the pointer is on one.  Kept
              apart from `hot` because a label crossing a hovered road
              shares cells with it while belonging to something else
              entirely: lighting a cell asks what is printed in it.

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
            lit = hot is not None and (cx, cy) in hot
            if ov is not None:                  # a glyph always beats braille
                # The cell is a character, so it answers to the glyph
                # half of the highlight and not to the ink half: a road
                # passing behind someone else's label lights the road,
                # never the letter it happens to run under.
                lit = hot_glyphs is not None and (cx, cy) in hot_glyphs
                ch, ink = ov[0], ov[1]
                if ink is None:                 # contrast-picked label ink
                    lum = (0.2126 * avg[0] + 0.7152 * avg[1]
                           + 0.0722 * avg[2])
                    ink = LABEL_DARK if lum > 120 else LABEL_LIGHT
                if lit:
                    ink = _maps_hover.highlight(ink)
                if lit or (len(ov) > 2 and ov[2]):
                    parts.append(f"{cell_bg}{fg(*ink)}{BOLD}{ch}{RESET}")
                else:
                    parts.append(f"{cell_bg}{fg(*ink)}{ch}")
                continue
            if lit:
                lift = _maps_hover.highlight(stroke)
                parts.append(f"{cell_bg}{fg(*lift) if lift else ''}{BOLD}"
                             f"{chr(0x2800 + mask)}{RESET}")
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
                    mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                    route_layer, show_labels=True, sun=False, clouds=False):
    """(map lines, readout, hover, loading, err) for the hillshaded view.

    Terrain's readout is its own probe — the elevation under the pointer
    — and it carries no hover slot: the braille here is geography rather
    than a network of named things, and "coastline" under the cursor
    would tell a reader less than the metres already there.
    """
    basemap = _get_basemap(bbox, graph_w, height_cells)
    err = None
    loading = False
    view = _EMPTY_TERRAIN
    if block:
        try:
            view = _get_elevation(bbox, graph_w, height_cells, True)
        except Exception as exc:
            err = str(exc)
    else:
        view = _get_elevation(bbox, graph_w, height_cells, False)
        loading = view.elev is None

    elev, coast, rivers = view.elev, view.coast, view.rivers
    if elev is not None:
        terrain = _terrain_buffer(elev, bbox, graph_w, height_cells,
                                  view.water, view.cover)
        if sun or clouds:
            # the flat earth as it is: same sun, same clouds, same
            # city lights, shaded through the same functions the
            # globe uses — only the projection differs
            terrain = _shade_now(
                terrain,
                _globe_now.flat_lls(bbox, graph_w, height_cells * 2), sun,
                (_get_clouds(bbox[3] - bbox[1], height_cells, block)
                 if clouds else None),
                _globe_now.city_lights_flat(bbox, graph_w,
                                            height_cells * 2)
                if sun else {})
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

    overlays = {}
    if show_labels:
        for pos, (ch, _color) in basemap.city_overlays().items():
            overlays[pos] = (ch, None)  # None ink = per-cell contrast pick
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, False)
    if origin_cell is not None:
        overlays[origin_cell] = _mark("○", MARKER, False)
    if dest_cell is not None:
        overlays[dest_cell] = _mark("●", MARKER, False)

    dx, dy = pan_offset
    if dx or dy:
        basemap = _ShiftedBasemap(_shift_grid(basemap.dots, dx, dy, 0),
                                  _shift_grid(basemap.color, dx, dy, None))
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        rivers = _shift_layer(rivers, dx, dy)
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

    # rivers under the route, which is the order the strokes list means:
    # a route along a river valley owns the cells it shares.
    strokes = [s for s in (rivers, route_layer) if s is not None] or None
    lines = compose_terrain(basemap, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes)
    return lines, readout, "", loading, err


def _get_globe(lat0, lon0, zoom, gw, hc, block):
    """A GlobeView for the view; live mode fetches in the background."""
    key = (round(lat0, 2), round(lon0, 2), round(zoom, 1), gw, hc)
    with _elev_lock:
        hit = _globe_cache.get(key)
        if hit is not None:
            return hit
        if not block:
            if key in _globe_pending or _fetch_held():
                return None
            _globe_pending.add(key)

    def load():
        # the fine grid feeds the coastline and box-averages into the
        # fill, exactly as the flat view does; the sub-pixel geometry
        # adds what only a sphere has — a viewing angle and a limb
        flls, _zs, _rhos = _globe.geometry(lat0, lon0, zoom, gw * 2, hc * 4)
        fine = _globe.elevation(flls, zoom, hc * 4)
        lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
        grid = []
        for y in range(hc * 2):
            r0, r1 = fine[y * 2], fine[y * 2 + 1]
            row = []
            for x in range(gw):
                vals = [v for v in (r0[x * 2], r0[x * 2 + 1],
                                    r1[x * 2], r1[x * 2 + 1])
                        if v is not None]
                if not vals:
                    row.append(None)
                    continue
                # the same >=2-of-4 wet rule as the flat view, for the
                # same reason: a shoreline sub-pixel averaged across the
                # waterline bulges low green into every sea
                wet = [v for v in vals if v <= 0]
                if len(wet) >= 2:
                    row.append(sum(wet) / len(wet))
                else:
                    row.append(sum(vals) / len(vals))
            grid.append(row)
        return _globe.GlobeView(
            grid, _coast_dots(fine, gw, hc), zs,
            _globe.atmosphere(rhos, zoom, hc * 2),
            _globe.ice_cover(lls, grid,
                             _maps_style.COVER_ORDER.index("ice") + 1),
            _globe.border_layer(lat0, lon0, zoom, gw, hc, BORDER_STROKE),
            lls)

    if block:
        hit = load()
        with _elev_lock:
            if len(_globe_cache) > 3:
                _globe_cache.clear()
            _globe_cache[key] = hit
        return hit

    def worker():
        try:
            hit = load()
        except Exception:
            hit = None
        with _elev_lock:
            _globe_pending.discard(key)
            if hit is not None:
                if len(_globe_cache) > 3:
                    _globe_cache.clear()
                _globe_cache[key] = hit
        if hit is not None and _live_refresh:
            import signal
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=worker, daemon=True).start()
    return None


_clouds_pending = [False]


def _get_clouds(zoom, hc, block):
    """The stitched cloud canvas for the now register, or None.

    Blocking mode fetches only when no canvas exists at all — a
    drag-synchronous repaint must never wait on the network, and a
    stale canvas is still this hour's weather.  Freshening always
    happens in the background, nudging a repaint when it lands.
    """
    canvas = _globe_now.peek()
    if block and canvas is None:
        try:
            _globe_now.refresh(zoom, hc * 4)
        except Exception:
            pass
        return _globe_now.peek()
    if canvas is not None and not _globe_now.stale():
        return canvas
    with _elev_lock:
        if _clouds_pending[0]:
            return canvas
        _clouds_pending[0] = True

    def worker():
        try:
            changed = _globe_now.refresh(zoom, hc * 4)
        except Exception:
            changed = False
        with _elev_lock:
            _clouds_pending[0] = False
        if changed and _live_refresh:
            import signal
            os.kill(os.getpid(), signal.SIGWINCH)

    threading.Thread(target=worker, daemon=True).start()
    return canvas


def _shade_now(buf, lls, sun, canvas, lights):
    """A copy of `buf` shaded into the present moment.

    The cached buffer stays pristine — daylight moves with the clock,
    so the moment is applied per repaint, never memoised.
    """
    buf = [row[:] for row in buf]
    day = (_globe_now.daylight(lls, _globe_now.subsolar())
           if sun else None)
    cloud = _globe_now.clouds(lls, canvas) if canvas is not None else None
    _globe_now.apply(buf, day, cloud, lights if sun else {})
    return buf


def _render_globe(bbox, graph_w, height_cells, block, pan_offset,
                  mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                  route_layer, show_labels=True, street=False, sun=False,
                  clouds=False):
    """Either view past the hand-off: the planet, orthographic.

    Everything downstream of the geometry belongs to the flat views —
    terrain keeps its shader, street keeps its two quiet fills, both
    keep the coastline rule, the Natural Earth borders and the city
    labels with their contrast-picked ink — so crossing the projection
    boundary changes the shape of the world, not the look of it.
    """
    lat0 = (bbox[1] + bbox[3]) / 2
    lon0 = (bbox[0] + bbox[2]) / 2
    zoom = bbox[3] - bbox[1]
    err = None
    loading = False
    view = None
    if block:
        try:
            view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, True)
        except Exception as exc:
            err = str(exc)
    else:
        view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, False)
        loading = view is None

    elev = view.elev if view is not None else None
    coast = view.coast if view is not None else None
    borders = view.borders if view is not None else None
    if elev is not None:
        key = (round(lat0, 2), round(lon0, 2), round(zoom, 1),
               graph_w, height_cells, street)
        terrain = _terrain_cache.get(key)
        if terrain is None:
            if street:
                p = _maps_style.palette()
                terrain = _globe.fill_buffer(elev, p.get("water"),
                                             p.get("ground"), BG_PRIMARY)
            else:
                # a scale-only bbox: the shader needs metres per
                # sub-pixel, which on the disk is the hand-off zoom's
                # scale everywhere (the limb compresses beyond it, and
                # the falloff owns that)
                spy_h = height_cells * 2
                sbbox = (0.0, -zoom / 2, zoom * graph_w / spy_h, zoom / 2)
                terrain = build_terrain_buffer(elev, sbbox, graph_w, spy_h,
                                               cover=view.cover)
            _globe.shade_buffer(terrain, view.shade, view.atmo, BG_PRIMARY)
            if len(_terrain_cache) > 2:
                _terrain_cache.clear()
            _terrain_cache[key] = terrain
        if (sun or clouds) and view.lls is not None:
            terrain = _shade_now(
                terrain, view.lls, sun,
                _get_clouds(zoom, height_cells, block) if clouds else None,
                _globe_now.city_lights_globe(lat0, lon0, zoom, graph_w,
                                             height_cells * 2) if sun else {})
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

    overlays = {}
    if show_labels:
        for pos, (ch, _color) in _globe.city_overlays(
                lat0, lon0, zoom, graph_w, height_cells, lang).items():
            overlays[pos] = (ch, None)  # None ink = per-cell contrast pick
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, False)
    if origin_cell is not None:
        overlays[origin_cell] = _mark("○", MARKER, False)
    if dest_cell is not None:
        overlays[dest_cell] = _mark("●", MARKER, False)

    dx, dy = pan_offset
    if dx or dy:
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        borders = _shift_layer(borders, dx, dy)
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}
    overlays = _crosshair(overlays, marker_cell, dx, dy, graph_w,
                          height_cells, False)

    # the elevation probe is terrain's idiom; the street planet, like
    # the street map, answers with places rather than metres
    readout = ""
    if elev is not None and not street:
        probe = None
        if mouse_pos is not None:
            pcol, prow = mouse_pos[0] - 1 - dx, mouse_pos[1] - 2 - dy
            if 0 <= pcol < graph_w and 0 <= prow < height_cells:
                probe = elev[prow * 2][pcol]
        if probe is None:
            probe = elev[height_cells][graph_w // 2]
        if probe is not None:
            readout = f" · {_fmt_elev(probe, lang)}"

    strokes = [borders] if borders is not None else None
    lines = compose_terrain(None, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes)
    return lines, readout, "", loading, err


def _hover(layer, mouse_pos, pan_offset, lang):
    """(readout, lit ink cells, lit glyph cells), or ("", None, None).

    Nothing is resolved mid-drag: the index is built for the view as it
    was fetched, and during a pan preview what is on screen is that view
    shifted.  A pointer over a shifted map would be answered about the
    cell it used to be over, which is worse than not answering.
    """
    index = getattr(layer, "hover", None)
    if index is None or mouse_pos is None or pan_offset[0] or pan_offset[1]:
        return "", None, None
    # the same 1-based frame the elevation probe reads: one column of
    # left margin, one header row above the map
    hit = index.at(mouse_pos[0] - 1, mouse_pos[1] - 2)
    if hit is None:
        return "", None, None
    text = _maps_hover.readout(hit, lang)
    return ((f" · {text}" if text else ""),
            set(hit.cells) or None, set(hit.glyphs) or None)


def _render_street(bbox, graph_w, height_cells, block, pan_offset,
                   mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                   route_layer, show_labels=True, sun=False, clouds=False):
    """(map lines, readout, hover, loading, err) for the vector view."""
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
    if sun or clouds:
        # the sky over the streets: the fills darken and cloud over,
        # the strokes and glyphs stay ink — a lit window is ink too
        fills = _shade_now(
            fills, _globe_now.flat_lls(bbox, graph_w, height_cells * 2),
            sun,
            (_get_clouds(bbox[3] - bbox[1], height_cells, block)
             if clouds else None),
            _globe_now.city_lights_flat(bbox, graph_w, height_cells * 2)
            if sun else {})

    hover, hot, hot_glyphs = _hover(layer, mouse_pos, pan_offset, lang)

    overlays = dict(labels) if show_labels else {}
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, True)
    if origin_cell is not None:
        overlays[origin_cell] = _mark("○", MARKER, True)
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
                        strokes=strokes, hot=hot, hot_glyphs=hot_glyphs)
    return lines, "", hover, loading, err


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
               origin=None, directions=None,
               note="", helping=False, show_labels=True, sun=False,
               clouds=False, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    m_lat, m_lon = marker if marker else (lat, lon)
    globe = zoom >= _globe.ZOOM_DEG
    if globe:
        # markers live on a sphere now: project them orthographically,
        # and let the far hemisphere hide what it hides
        cell = _globe.marker_cell(lat, lon, zoom, graph_w, height_cells,
                                  m_lat, m_lon)
        dest_cell = (_globe.marker_cell(lat, lon, zoom, graph_w,
                                        height_cells, dest[0], dest[1])
                     if dest is not None else None)
        origin_cell = (_globe.marker_cell(lat, lon, zoom, graph_w,
                                          height_cells, origin[0], origin[1])
                       if origin is not None else None)
        route_layer = None
        draw = functools.partial(_render_globe, street=(view == "street"),
                                 sun=sun, clouds=clouds)
    else:
        cell = _marker_cell(bbox, graph_w, height_cells, m_lat, m_lon)
        dest_cell = (_marker_cell(bbox, graph_w, height_cells,
                                  dest[0], dest[1])
                     if dest is not None else None)
        origin_cell = (_marker_cell(bbox, graph_w, height_cells,
                                    origin[0], origin[1])
                       if origin is not None else None)
        route_layer = _get_route_layer(route, bbox, graph_w, height_cells)
        draw = functools.partial(
            _render_street if view == "street" else _render_terrain,
            sun=sun, clouds=clouds)
    map_lines, readout, hover, loading, err = draw(
        bbox, graph_w, height_cells, block, pan_offset, mouse_pos,
        cell, dest_cell, origin_cell, lang, route_layer,
        show_labels=show_labels)

    # A note is a reply to something you asked for and outranks
    # everything; hover is what you are pointing at *now*, so it beats
    # the standing route summary, which beats the view's own probe.
    if note:
        readout = f" · {note}"
    elif hover:
        readout = hover
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
        return (f"{fg(*_BADGE)}{BOLD}⬤ maps{RESET}  {fg(*MUTED)}"
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
        # once a route stands, the footer teaches the route keys instead
        hint_key = 'hint_route' if route is not None else 'hint'
        hint = (f"{fg(*DIM)}{ms(hint_key, lang)}{RESET}"
                if sys.stdout.isatty() else "")
        if globe:
            # either register's globe draws from the elevation tiles
            # alone (borders and cities are vendored Natural Earth);
            # showing this hour's clouds adds their credit
            attribs = ((f"{ATTRIBUTION} · {_globe_now.ATTRIBUTION}",
                        ATTRIBUTION) if clouds
                       else (ATTRIBUTION,))
        elif view == "street":
            attribs = ((f"{_maps_style.ATTRIB_TILES_LONG} · "
                        f"{_globe_now.ATTRIBUTION}",
                        _maps_style.ATTRIB_TILES_LONG,
                        _maps_style.ATTRIB_TILES_SHORT) if clouds
                       else (_maps_style.ATTRIB_TILES_LONG,
                             _maps_style.ATTRIB_TILES_SHORT))
        else:
            # terrain's lakes and rivers come from the tiles too, so the
            # first rung credits both sources and the fallbacks shorten;
            # the settlement raster earns its CC-BY credit when in use
            both = f"{ATTRIBUTION} · {_maps_style.ATTRIB_TILES_SHORT}"
            if clouds:
                attribs = (f"{both} · {_globe_now.ATTRIBUTION}", both,
                           ATTRIBUTION)
            elif _builtup.enabled():
                attribs = (f"{both} · {_builtup.ATTRIBUTION}", both,
                           ATTRIBUTION)
            else:
                attribs = (both, ATTRIBUTION)
        scale = (_scale_bar(bbox, graph_w, lang)
                 if view == "street" and not globe else "")
        # first rung that fits wins: long+hint, short+hint, short, bare
        ladder = [f"{scale}{fg(*DIM)}{a}{RESET}  {hint}" for a in attribs]
        ladder += [f"{scale}{fg(*DIM)}{attribs[-1]}{RESET}",
                   f"{fg(*DIM)}{attribs[-1]}{RESET}", ""]
        for foot in ladder:
            if visible_len(foot) <= cols:
                break
    foot += " " * max(0, cols - visible_len(foot))

    out = "\n".join([header, *map_lines, foot])
    # One floating thing at a time, through the one overlay channel;
    # search beats help beats the steps panel.
    if search is not None and search.open:
        # Any-motion mouse reporting is what makes a torn escape
        # sequence likely, and a torn sequence looks like ESC — which is
        # exactly the key guarding a text buffer.  Turn 1003 off for as
        # long as the field is open, and back on when it closes.
        return out + ("\x00\033[?1003l"
                      + _maps_ui.search_overlay(search, cols, rows, lang))
    if helping:
        overlay = _maps_ui.help_overlay(cols, rows, lang, route is not None)
        if overlay:
            return out + "\x00\033[?1003h" + overlay
    if directions is not None and directions.panel:
        overlay = _maps_ui.directions_overlay(directions, cols, rows, lang,
                                              home_label=location_name)
        if overlay:
            return out + "\x00\033[?1003h" + overlay
    if not block:
        out += "\x00\033[?1003h"
    return out


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
        global _live_refresh
        _live_refresh = True
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
            import signal
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
                os.kill(os.getpid(), signal.SIGWINCH)

        def cloud_tick():
            """The sky's slow heartbeat.

            Every half hour while the sky is switched on: the newest
            mosaic frame if clouds are showing, the sun where it now
            is, one repaint.  Never an animation — a view left running
            all evening simply stays true.
            """
            import signal
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
                os.kill(os.getpid(), signal.SIGWINCH)

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


if __name__ == "__main__":
    main()
