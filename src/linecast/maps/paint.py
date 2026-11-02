"""How the terrain map is painted: its inks, its palette, and the composers.

The inks and the hypsometric and bathymetric tables are here, each
passed through _theme.themed at import and again on a theme change.
build_terrain_buffer hillshades an elevation grid into sub-pixel
colours; compose_terrain and compose_map turn a fill and its braille
layers into terminal lines, one composer per register.
"""

import math
import re

from linecast.terminal import theme as _theme
from linecast.maps import climate as _climate
from linecast.maps import globe_now
from linecast.maps import hover
from linecast.maps import style as _style
from linecast.terminal.color import (
    RESET, BOLD, color_mode, escape_tables, interp_stops, BG_PRIMARY,
)
from linecast.terminal.framebuffer import HALF_BLOCK
from linecast.radar.basemap import BORDER
from linecast.terminal.theme import lerp_rgb, themed
from linecast.radar.ui import MARKER as _MARKER_RAW


# A colour setter we can compare, or any other escape, taken whole: the
# second group is "38" or "48" only for a standalone foreground or
# background, which is the shape both halves of every half-block cell
# come in.  Anything else falls through to the third alternative, which
# takes a complete CSI, or the fourth, which takes ESC and one byte of
# whatever came after it.
_MAP_ESCAPE = re.compile(
    r'\x1b(?:\[([34]8);(?:2;[0-9]+;[0-9]+;[0-9]+|5;[0-9]+)m'
    r'|\[[0-?]*[ -/]*[@-~]|[\s\S]?)')


def compact_colors(output):
    """Omit repeated map colours, with no state shared between frames.

    The half-block fills set a foreground and a background on nearly
    every cell, and a run of ground the same colour sets each of them to
    what it already is.  Dropping the repeats leaves the frame painting
    exactly as it did: the rendered string stays canonical, and this is
    a pass over it on the way to the terminal.

    Only standalone truecolor and indexed-colour escapes are shortened.
    Every other CSI -- a reset, a bold, a cursor move, an erase -- stays
    intact and forgets both colours, since it may have changed either;
    an unfamiliar terminal control leaves the whole output untouched.
    A newline is not a barrier: the live loop reaches the next row with
    a cursor address and an erase, neither of which resets the
    rendition, and it resets only after the last row.  Anything past a
    NUL is the overlay channel (see terminal.live.overlay), which is addressed
    over the body and is copied through as it stands.
    """
    body, sep, floating = output.partition('\x00')
    packed = _compact_into(body, {})
    return output if packed is None else f'{packed}{sep}{floating}'


def _compact_into(text, colors):
    """`text` with the colour setters that repeat `colors` dropped.

    `colors` is the escape in effect per slot ("38" or "48") on the way
    in, and is left as it stands on the way out, so a pass over one
    stretch of a frame can seed the pass over the next.  None instead
    when `text` holds an escape this pass does not know.
    """
    unfamiliar = False

    def compact(match):
        nonlocal unfamiliar
        code, slot = match[0], match[1]
        if slot is not None:
            if colors.get(slot) == code:
                return ''
            colors[slot] = code
        else:
            colors.clear()
            unfamiliar |= len(code) < 3 or not code.startswith('\x1b[')
        return code

    packed = _MAP_ESCAPE.sub(compact, text)
    return None if unfamiliar else packed


def compact_frame(header, lines, foot):
    """`header`, the map `lines` and `foot` joined, as compact_colors
    would leave them, given lines a composer has already compacted.

    The composers leave out the repeats inside the map, which is nearly
    all of a frame.  What remains is the header and the footer, which
    are short, and the colours that cross from one stretch into the
    next: the header's last colour into the first map row, and the
    map's into the footer.  A composed row ends with RESET, so while
    there is a RESET to end it nothing crosses out of the map.

    One difference from the pass over the whole frame: an unfamiliar
    escape in the header or the footer leaves that line untouched,
    where compact_colors would have left the whole frame untouched,
    map and all.  Neither line is built from anything that could hold
    one.
    """
    colors = {}
    packed = _compact_into(header, colors)
    header = header if packed is None else packed
    if colors and lines:
        packed = _compact_into(lines[0], colors)
        if packed is not None:
            lines = [packed, *lines[1:]]
    if lines and RESET:
        colors.clear()
    packed = _compact_into(foot, colors)
    foot = foot if packed is None else packed
    return "\n".join([header, *lines, foot])


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


def _rebuild():
    """Ink the terrain for the theme now in force.

    Every ink passes through terminal.theme.themed: the calibrated
    luminance ladder stays, and the hue family follows the terminal's
    own theme.  Run once at import and again on each theme change.
    """
    global COAST_STROKE, BORDER_STROKE, LABEL_DARK, LABEL_LIGHT, MARKER
    global LAKE_FILL, RIVER_STROKE, HYPSO_FAMILIES, BATHY_STOPS
    global _COVER_RGB, _SHADOW_TINT, _LIGHT_TINT
    # geography over terrain: dark strokes cut into the colour fill (the
    # radar palette's dim-on-dark strokes vanish against light terrain)
    COAST_STROKE = themed((22, 32, 52))
    BORDER_STROKE = themed((52, 48, 66))
    LABEL_DARK = themed((28, 32, 44))
    LABEL_LIGHT = themed((232, 232, 240))

    # the marker is radar's, re-inked: on any theme it should be the
    # theme's own bright accent, not an absolute yellow
    MARKER = themed(_MARKER_RAW)

    # Inland water: lakes and rivers are *not* on the bathymetric ramp.  A
    # terrarium sample reports the elevation of the water's surface, so a
    # lake is indistinguishable from the meadow beside it — the polygons
    # come from the same vector tiles street mode uses, and the ramps never
    # have to guess.  One flat tint, because a lake surface is flat.
    LAKE_FILL = themed((74, 118, 156))
    RIVER_STROKE = themed((108, 152, 190))

    HYPSO_FAMILIES = [[(m, themed(c)) for m, c in fam]
                      for fam in _HYPSO_FAMILIES_RAW]
    BATHY_STOPS = [(m, themed(c)) for m, c in _BATHY_RAW]

    # land-cover tints by grid index (0 = no cover, stays on the ramp),
    # as style has already inked them: its hook was registered first,
    # when paint imported it, and so runs first
    _COVER_RGB = [None] + [_style.COVER_COLOR[k]
                           for k in _style.COVER_ORDER]

    # aerial perspective on land: shadow does not just darken, it cools
    # toward slate; full light warms faintly toward sun-colour.  Both are
    # small nudges after the multiply — the ramp still owns the hue.
    _SHADOW_TINT = themed((40, 48, 72))
    _LIGHT_TINT = themed((255, 248, 228))


_rebuild()
_theme.on_reload(_rebuild)


def _hypso_band(e, fam=0):
    """The flat colour of the band `e` falls in, on family `fam`'s ramp."""
    stops = HYPSO_FAMILIES[fam]
    for lim, c in reversed(stops):
        if e >= lim:
            return c
    return stops[0][1]

# A north-west sun 45° up, with two flanking lights a quarter turn to
# either side: one azimuth lights every NW-SE ridge identically and
# drops every SE face into the same flat dark — the flanks are what let
# a spur read differently from the ridge it leaves.  Weights sum to 1,
# so the tonal range is the single sun's.
_ZENITH = math.radians(45.0)
_SUNS = tuple((wgt, math.cos(math.radians(az)), math.sin(math.radians(az)))
              for wgt, az in ((0.55, 315.0), (0.225, 270.0), (0.225, 360.0)))


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
    blend = _style.COVER_BLEND
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


def _contrast_ink(cell_bg):
    """Dark ink on a light ground, light ink on a dark one."""
    lum = 0.2126 * cell_bg[0] + 0.7152 * cell_bg[1] + 0.0722 * cell_bg[2]
    return LABEL_DARK if lum > 120 else LABEL_LIGHT


def _by_row(cells):
    """`cells`, keyed by (col, row), regrouped by row.

    A dict comes back as {row: {col: value}} and a set as {row: set of
    cols}, so a composer's inner loop asks for a column of the row in
    hand instead of building a (col, row) key for every cell.
    """
    rows = {}
    if isinstance(cells, dict):
        for (cx, cy), value in cells.items():
            row = rows.get(cy)
            if row is None:
                row = rows[cy] = {}
            row[cx] = value
    else:
        for cx, cy in cells:
            row = rows.get(cy)
            if row is None:
                row = rows[cy] = set()
            row.add(cx)
    return rows


# Both composers write a row the way compact_colors would leave it.
# The foreground and background escape in effect are kept in hand, and
# a cell's escape is written only when it is not the one in effect; a
# BOLD or a RESET forgets both, as any other CSI does in that pass.
# Only the standalone truecolor and 256-colour setters are tracked at
# all: a 16-colour SGR is one of the escapes that pass keeps and
# forgets on, so in that mode every escape is written.  Each row ends
# with RESET, so no colour crosses from one row into the next, and
# compact_frame can treat the rows as settled.
#
# The escapes come from the tables behind fg and bg, indexed by the
# colour tuple a cell already holds; `fgs[rgb]` is fg(*rgb) without the
# call, and these loops make tens of thousands of them a frame.

def compose_terrain(basemap, terrain, overlays, graph_w, height_cells,
                    coast=None, strokes=None, borders=None, *, compact=True):
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

    `borders` is the Natural Earth stroke as its own braille layer, and
    it takes the place the basemap's border cells hold — under the
    coastline and under everything in `strokes`.  A border is the one
    line on this map that is a convention rather than a thing on the
    ground, and it yields to anything that is.

    `compact` False writes every cell's escapes in full.  The default
    leaves out the ones that repeat the colour in effect, which is what
    compact_colors would do to the joined rows.
    """
    fgs, bgs = escape_tables()
    reset, bold = RESET, BOLD
    tracked = compact and color_mode() in ("truecolor", "256")
    forgets = bool(bold or reset)   # the bold idiom is a barrier in the pass
    half = HALF_BLOCK
    bg_primary = BG_PRIMARY
    border = BORDER
    ov_rows = _by_row(overlays) if overlays else {}
    lines = []
    cur_fg = cur_bg = None
    for cy in range(height_cells):
        top_row = terrain[cy * 2]
        bot_row = terrain[cy * 2 + 1]
        ov_row = ov_rows.get(cy)
        bm_dots = bm_color = None
        if basemap is not None:
            bm_dots, bm_color = basemap.dots[cy], basemap.color[cy]
        bd_row = borders.dots[cy] if borders is not None else None
        coast_row = coast[cy] if coast is not None else None
        stroke_rows = ([(layer.dots[cy], layer.color[cy]) for layer in strokes]
                       if strokes else None)
        parts = []
        append = parts.append
        for cx in range(graph_w):
            if not tracked:
                cur_fg = cur_bg = None
            ut = top_row[cx] or bg_primary
            ub = bot_row[cx] or bg_primary
            ov = ov_row.get(cx) if ov_row is not None else None
            bmask = (bm_dots[cx] if bm_dots is not None
                     and bm_color[cx] == border else 0)
            if bd_row is not None:
                bmask |= bd_row[cx]
            cmask = coast_row[cx] if coast_row is not None else 0
            smask, sink = 0, None
            if stroke_rows is not None:
                for dots_row, color_row in stroke_rows:
                    m = dots_row[cx]
                    if m:
                        smask |= m
                        c = color_row[cx]
                        if c is not None:
                            sink = c
            if ov is None and not (bmask or cmask or smask):
                # the half-block cell: the top colour behind, the bottom
                # as the ▄, or a space when the two are the same
                code = bgs[ut]
                if code != cur_bg:
                    append(code)
                    cur_bg = code
                if ut == ub:
                    append(" ")
                else:
                    code = fgs[ub]
                    if code != cur_fg:
                        append(code)
                        cur_fg = code
                    append(half)
                continue
            # a glyph or a stroke sits on the cell's one average colour
            avg = ((ut[0] + ub[0]) // 2, (ut[1] + ub[1]) // 2,
                   (ut[2] + ub[2]) // 2)
            code = bgs[avg]
            if code != cur_bg:
                append(code)
                cur_bg = code
            if ov is not None:
                ch, ink = ov[0], ov[1]
                if ink is None:  # contrast-picked label ink
                    ink = _contrast_ink(avg)
                code = fgs[ink]
                if code != cur_fg:
                    append(code)
                    cur_fg = code
                if len(ov) > 2 and ov[2]:
                    append(f"{bold}{ch}{reset}")
                    if forgets:
                        cur_fg = cur_bg = None
                else:
                    append(ch)
                continue
            if sink is not None:
                stroke = sink
            else:
                stroke = COAST_STROKE if cmask else BORDER_STROKE
            code = fgs[stroke]
            if code != cur_fg:
                append(code)
                cur_fg = code
            append(chr(0x2800 + (bmask | cmask | smask)))
        append(reset)
        if reset:
            cur_fg = cur_bg = None
        lines.append("".join(parts))
    return lines


def compose_map(fills, layer, overlays, graph_w, height_cells,
                strokes=None, hot=None, hot_glyphs=None, ink_dusk=None, *,
                compact=True):
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
    compact:  False writes every cell's escapes in full; the default
              leaves out the ones that repeat the colour in effect,
              which is what compact_colors would do to the joined rows.

    A sibling of compose_terrain, not a replacement: terrain resolves a
    basemap, a coast mask and an ordered strokes list per cell, street
    resolves one pre-ranked layer plus the motorway ribbon, and neither
    shape fits the other without a pile of mode conditionals.

    Two degradation rules live here so the rest of street mode never
    thinks about colour depth.  A cell with an unpainted sub-pixel is
    left unpainted entirely — that is the 16-colour "mixed land/water
    cell" rule, where the coast stroke carries the boundary instead of
    a half-and-half block.  And in `none` mode every cell without a
    glyph or a braille dot is a literal space: a half-block with empty
    escapes is a bare ▄ that would flood the screen, and the line map
    that results is the mode's whole character.
    """
    plain = color_mode() == "none"
    ribbon_ink = _style.ink("motorway")
    ribbon_blend = _style.RIBBON_BLEND
    fgs, bgs = escape_tables()
    reset, bold = RESET, BOLD
    tracked = compact and color_mode() in ("truecolor", "256")
    forgets = bool(bold or reset)   # the bold idiom is a barrier in the pass
    half = HALF_BLOCK
    highlight = hover.highlight
    dim_ink = globe_now.dim_ink
    ov_rows = _by_row(overlays) if overlays else {}
    ribbon_rows = _by_row(layer.ribbon) if layer.ribbon else {}
    hot_rows = _by_row(hot) if hot else {}
    glyph_rows = _by_row(hot_glyphs) if hot_glyphs else {}
    lines = []
    cur_fg = cur_bg = None
    for cy in range(height_cells):
        top_row = fills[cy * 2]
        bot_row = fills[cy * 2 + 1]
        dots_row = layer.dots[cy]
        color_row = layer.color[cy]
        ov_row = ov_rows.get(cy)
        rib_row = ribbon_rows.get(cy)
        hot_row = hot_rows.get(cy)
        glyph_row = glyph_rows.get(cy)
        dusk_row = ink_dusk[cy] if ink_dusk is not None else None
        stroke_rows = ([(extra.dots[cy], extra.color[cy]) for extra in strokes]
                       if strokes else None)
        parts = []
        append = parts.append
        for cx in range(graph_w):
            if not tracked:
                cur_fg = cur_bg = None
            ut, ub = top_row[cx], bot_row[cx]
            if rib_row is not None and cx in rib_row:
                # Blend toward the motorway ink itself, never the cell's
                # winning stroke — a route crossing here must not tint
                # the ribbon cyan.
                if ut is not None:
                    ut = lerp_rgb(ut, ribbon_ink, ribbon_blend)
                if ub is not None:
                    ub = lerp_rgb(ub, ribbon_ink, ribbon_blend)
            ov = ov_row.get(cx) if ov_row is not None else None
            mask = dots_row[cx]
            stroke = color_row[cx]
            if stroke_rows is not None:
                for extra_dots, extra_color in stroke_rows:
                    m = extra_dots[cx]
                    if m:
                        mask |= m
                        c = extra_color[cx]
                        if c is not None:
                            stroke = c
            painted = ut is not None and ub is not None
            if ov is None and not mask:
                if painted and not plain:
                    code = bgs[ut]
                    if code != cur_bg:
                        append(code)
                        cur_bg = code
                    if ut == ub:
                        append(" ")
                    else:
                        code = fgs[ub]
                        if code != cur_fg:
                            append(code)
                            cur_fg = code
                        append(half)
                else:
                    append(" ")
                continue
            if painted:
                avg = ((ut[0] + ub[0]) // 2, (ut[1] + ub[1]) // 2,
                       (ut[2] + ub[2]) // 2)
                code = bgs[avg]
                if code != cur_bg:
                    append(code)
                    cur_bg = code
            else:
                avg = BG_PRIMARY
            if ov is not None:                  # a glyph always beats braille
                # The cell is a character, so it answers to the glyph
                # half of the highlight and not to the ink half: a road
                # passing behind someone else's label lights the road,
                # never the letter it happens to run under.
                lit = glyph_row is not None and cx in glyph_row
                ch, ink = ov[0], ov[1]
                if ink is None:                 # contrast-picked label ink
                    ink = _contrast_ink(avg)
                if lit:
                    ink = highlight(ink)
                code = fgs[ink]
                if code != cur_fg:
                    append(code)
                    cur_fg = code
                if lit or (len(ov) > 2 and ov[2]):
                    append(f"{bold}{ch}{reset}")
                    if forgets:
                        cur_fg = cur_bg = None
                else:
                    append(ch)
                continue
            if hot_row is not None and cx in hot_row:
                lift = highlight(stroke)
                if lift:
                    code = fgs[lift]
                    if code != cur_fg:
                        append(code)
                        cur_fg = code
                append(f"{bold}{chr(0x2800 + mask)}{reset}")
                if forgets:
                    cur_fg = cur_bg = None
                continue
            if dusk_row is not None:
                stroke = dim_ink(stroke, dusk_row[cx])
            if stroke is not None:
                code = fgs[stroke]
                if code != cur_fg:
                    append(code)
                    cur_fg = code
            append(chr(0x2800 + mask))
        append(reset)
        if reset:
            cur_fg = cur_bg = None
        lines.append("".join(parts))
    return lines


_theme.track_imports(globals(), "linecast.terminal.color")
