"""How the terrain map is painted: its inks, its palette, and the composers.

The inks and the hypsometric and bathymetric tables are here, each
passed through _theme.themed at import and again on a theme change.
build_terrain_buffer hillshades an elevation grid into sub-pixel
colours; compose_terrain and compose_map turn a fill and its braille
layers into terminal lines, one composer per register.
"""

import math

from linecast import _climate, _globe_now, _maps_hover, _maps_style, _theme
from linecast._color import (
    bg, fg, RESET, BOLD, color_mode, interp_stops, BG_PRIMARY,
)
from linecast._framebuffer import halfblock
from linecast._radar_basemap import BORDER
from linecast._theme import lerp_rgb, themed
from linecast._radar_ui import MARKER

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
_MARKER_RAW = MARKER
MARKER = themed(_MARKER_RAW)
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
# contours, the way a geologic map draws provinces.
#
# Four ramps, one per climate family, cross-blended-hypso fashion
# (Patterson): elevation picks the band, the vendored Köppen grid
# picks which ramp is climbing.  One ramp alone painted the low
# Sahara meadow-green and the dry Tibetan Plateau snow-white; climate
# is what tells a desert from a delta at the same three hundred
# metres.  All four converge in the high mauves and lavenders — high
# country earns the purples whatever the weather — and summit white
# belongs to the ramps whose summits are actually white.
_HYPSO_RAW = [
    # humid: out of the greens through straw and ochre
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
_HYPSO_SEMIARID_RAW = [
    # steppe: dry grass at the shore, straw all the way up
    (0, (140, 142, 84)),
    (150, (158, 152, 86)),
    (400, (176, 160, 92)),
    (800, (192, 168, 100)),
    (1300, (198, 162, 104)),
    (2000, (178, 142, 114)),
    (2800, (160, 140, 156)),
    (3600, (196, 182, 208)),
    (4600, (236, 234, 242)),
]
_HYPSO_ARID_RAW = [
    # desert: sand from the waterline, rock-red high desert
    (0, (186, 160, 104)),
    (150, (194, 168, 108)),
    (400, (202, 176, 112)),
    (800, (206, 178, 114)),
    (1300, (200, 164, 110)),
    (2000, (182, 144, 110)),
    (2800, (164, 140, 150)),
    (3600, (198, 184, 206)),
    (4600, (240, 240, 248)),
]
_HYPSO_POLAR_RAW = [
    # tundra: grey-green barrens paling toward ice, never lush —
    # this is what keeps the Tibetan interior stone instead of snow
    (0, (128, 132, 116)),
    (150, (140, 140, 122)),
    (400, (152, 148, 130)),
    (800, (166, 158, 140)),
    (1300, (178, 168, 152)),
    (2000, (188, 178, 166)),
    (2800, (200, 192, 186)),
    (3600, (216, 212, 212)),
    (4600, (238, 240, 246)),
]
_HYPSO_FAMILIES_RAW = (_HYPSO_RAW, _HYPSO_SEMIARID_RAW,
                       _HYPSO_ARID_RAW, _HYPSO_POLAR_RAW)
HYPSO_FAMILIES = [[(m, themed(c)) for m, c in fam]
                  for fam in _HYPSO_FAMILIES_RAW]

# Bathymetric tint below sea level — deliberately a smooth gradient
# where the land is banded: the sea is the one continuous field on the
# map, falling away to a near-black navy abyss.
_BATHY_RAW = [
    (-8000, (6, 12, 30)),
    (-5000, (12, 22, 48)),
    (-3500, (18, 34, 68)),
    (-2000, (30, 56, 98)),
    (-1000, (44, 80, 124)),
    (-200, (66, 112, 152)),
    (-50, (96, 148, 178)),
    (0, (120, 170, 194)),
]
BATHY_STOPS = [(m, themed(c)) for m, c in _BATHY_RAW]


def _hypso_band(e, fam=0):
    """The flat colour of the band `e` falls in, on family `fam`'s ramp."""
    stops = HYPSO_FAMILIES[fam]
    for lim, c in reversed(stops):
        if e >= lim:
            return c
    return stops[0][1]

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


@_theme.on_reload
def _rebuild_inks():
    # every themed() ink above, re-inked for the new theme
    global COAST_STROKE, BORDER_STROKE, LABEL_DARK, LABEL_LIGHT, MARKER, _BADGE
    global LAKE_FILL, RIVER_STROKE, HYPSO_FAMILIES, BATHY_STOPS, _SHADOW_TINT
    global _LIGHT_TINT
    COAST_STROKE = themed((22, 32, 52))
    BORDER_STROKE = themed((52, 48, 66))
    LABEL_DARK = themed((28, 32, 44))
    LABEL_LIGHT = themed((232, 232, 240))
    MARKER = themed(_MARKER_RAW)
    _BADGE = themed((110, 168, 96))
    LAKE_FILL = themed((74, 118, 156))
    RIVER_STROKE = themed((108, 152, 190))
    HYPSO_FAMILIES = [[(m, themed(c)) for m, c in fam]
                      for fam in _HYPSO_FAMILIES_RAW]
    BATHY_STOPS = [(m, themed(c)) for m, c in _BATHY_RAW]
    _SHADOW_TINT = themed((40, 48, 72))
    _LIGHT_TINT = themed((255, 248, 228))


def build_terrain_buffer(elev, bbox, w, h, water=None, cover=None,
                         climate=None):
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

    `climate` is the optional sub-pixel ramp-family grid (indices into
    HYPSO_FAMILIES).  None means "derive it from the bbox", which is
    right for the flat view; the globe's bbox is scale-only, so its
    caller passes a grid sampled from the disk's own lat/lons.
    """
    minlon, minlat, maxlon, maxlat = bbox
    if climate is None:
        climate = _climate.grid_for_bbox(bbox, w, h)
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
        cli_row = climate[y] if climate else None
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
                base = _hypso_band(e, cli_row[x] if cli_row is not None
                                   else 0)
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


def _cell_avg(top, bot):
    """A cell's one background colour: its two sub-pixels averaged."""
    return ((top[0] + bot[0]) // 2, (top[1] + bot[1]) // 2,
            (top[2] + bot[2]) // 2)


def _contrast_ink(cell_bg):
    """Dark ink on a light ground, light ink on a dark one."""
    lum = 0.2126 * cell_bg[0] + 0.7152 * cell_bg[1] + 0.0722 * cell_bg[2]
    return LABEL_DARK if lum > 120 else LABEL_LIGHT


def compose_terrain(basemap, terrain, overlays, graph_w, height_cells,
                    coast=None, strokes=None, coast_ink=None,
                    ink_dusk=None):
    """Terrain fill with braille geography *on top* (inverse of radar).

    The coastline comes from `coast` — sea-level contour masks derived
    from the elevation data itself, so stroke and fill always agree; the
    basemap's own generalized coast (and its sea stipple) are ignored.
    Natural Earth still supplies the border strokes.  Overlay glyphs pick
    a light or dark ink per cell for contrast; a truthy third tuple
    element renders the glyph bold.

    `coast_ink` overrides the terrain coastline colour — the street
    globe strokes its shore in the street map's own ink.  `ink_dusk`
    is a per-cell grid of RGB multipliers (_globe_now.ink_dusk) that
    dims braille strokes with the night; glyphs keep their ink.

    `strokes` is an ordered list of extra braille layers (anything with
    .dots and .color cell grids, e.g. streets, a route), lowest priority
    first: dot masks OR together, and the last layer with dots in a cell
    owns its ink — the same one-ink-per-cell rule the layers themselves
    resolve by draw order.
    """
    coast_stroke = coast_ink if coast_ink is not None else COAST_STROKE
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
                avg = _cell_avg(ut, ub)
                cell_bg = bg(*avg)
                if ov is not None:
                    ch, ink = ov[0], ov[1]
                    if ink is None:  # contrast-picked label ink
                        ink = _contrast_ink(avg)
                    if len(ov) > 2 and ov[2]:
                        parts.append(f"{cell_bg}{fg(*ink)}{BOLD}{ch}{RESET}")
                    else:
                        parts.append(f"{cell_bg}{fg(*ink)}{ch}")
                else:
                    if sink is not None:
                        stroke = sink
                    else:
                        stroke = coast_stroke if cmask else BORDER_STROKE
                    if ink_dusk is not None:
                        stroke = _globe_now.dim_ink(stroke,
                                                    ink_dusk[cy][cx])
                    parts.append(f"{cell_bg}{fg(*stroke)}"
                                 f"{chr(0x2800 + (bmask | cmask | smask))}")
                continue
            parts.append(halfblock(ut, ub))
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


def compose_map(fills, layer, overlays, graph_w, height_cells,
                strokes=None, hot=None, hot_glyphs=None, ink_dusk=None):
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
                avg = _cell_avg(ut, ub)
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
                    ink = _contrast_ink(avg)
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
            if ink_dusk is not None:
                stroke = _globe_now.dim_ink(stroke, ink_dusk[cy][cx])
            stroke_fg = fg(*stroke) if stroke is not None else ""
            parts.append(f"{cell_bg}{stroke_fg}{chr(0x2800 + mask)}")
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


_theme.track_imports(globals(), "linecast._color")
