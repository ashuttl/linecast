"""Street mode — OpenMapTiles vector tiles rasterised for the terminal.

The half of street mode that turns tiles into pixels: pick the source
zoom for a view, decode the tiles, and paint their polygons into a
dot-resolution class grid that becomes both the area fills and the
coastline.  Line work, labels and POI arrive in later stages; this
module owns the ground the rest of them stand on.

Two rules shape everything here.  **Fills are solid half-blocks and
braille is reserved for line work**, because a braille cell holds
exactly one foreground colour — a stipple fill and a road stroke in the
same cell would have to fight for the ink, and that failure is total
rather than cosmetic.  And **the coastline is the boundary of the fill
mask that produced it**, never a second dataset, so the stroke and the
colour edge cannot disagree at any zoom.

Style decisions (which classes, which colours, which bands) all live in
_maps_style; this module only asks it questions.
"""

import math

from linecast import _maps_hover, _maps_labels, _maps_style as style
from linecast._mvt import assemble_polygons, decode_tile
from linecast._radar_basemap import DotLayer, _bresenham, _edge_dots
from linecast._runtime import debug_log
from linecast._theme import lerp_rgb
from linecast._vtiles import (
    fetch_tiles, projector as _projector, tile_info, tiles_for_bbox,
)

# Fill ids double as indices into style.FILL_ORDER, so the id order *is*
# the stacking order: water over park (a pond in a park), park over
# urban, buildings on everything.
GROUND, URBAN, PARK, WATER, BUILDING = 0, 1, 2, 3, 4

# The only layers with polygons worth painting. `landcover` is admitted
# for parks alone — no grass, wood, farmland, wetland or sand, because
# green-washing a rural view buys the reader nothing.
FILL_LAYERS = ("water", "park", "landcover", "landuse", "building")

# Every layer with strokes worth walking. Terrain mode keeps the
# Natural Earth borders; street mode takes admin lines from the tile so
# they are generalised to the same zoom as everything around them.
LINE_LAYERS = ("transportation", "waterway", "aeroway", "boundary")

# Dot-space margin for the stroke clip. Wide enough that a w2 offset or
# a rail crosstie just off the edge still lands on screen.
CLIP_MARGIN = 8

_MAX_TILES = 16          # a view needs ~4; more means a pathological window
_DEFAULT_EXTENT = 4096
_MIN_BUILDING_DOTS = 4.0  # one sub-pixel is 2x2 dots


# ---------------------------------------------------------------------------
# Which tiles a view needs
# ---------------------------------------------------------------------------
def view_tiles(bbox, height_cells):
    """(band, z_src, [(z, x, y), ...]) for a view.

    The source zoom comes from the style model, which runs ahead of the
    view's own zoom (style.z_src) so the tile carries names and detail
    the band can choose from.  It only ever lands on or below
    OpenMapTiles' generalisation floors, so the band table can never ask
    for a class the tile does not carry.

    A window wide enough to need more than _MAX_TILES tiles is coarsened
    a zoom at a time rather than silently truncated — and says so in the
    debug log.  That is a guard against pathological windows and not the
    routine arbiter of the lookahead: measured across every street view
    size, the lookahead lands on 8-12 tiles and never wakes it.
    """
    z = style.z_eff(bbox, height_cells)
    band = style.band_for(z)
    info = tile_info()
    maxzoom = info[2] if info else 14
    z_src = min(style.z_src(z, band), maxzoom)
    keys = tiles_for_bbox(bbox, z_src)
    while len(keys) > _MAX_TILES and z_src > 0:
        debug_log(f"street view needs {len(keys)} tiles at z{z_src}; "
                  f"coarsening to z{z_src - 1}")
        z_src -= 1
        keys = tiles_for_bbox(bbox, z_src)
    return band, z_src, keys


def fetch_view(bbox, height_cells):
    """(band, {(z, x, y): bytes|None}) — the network half of a view."""
    band, _z_src, keys = view_tiles(bbox, height_cells)
    return band, fetch_tiles(keys)


# ---------------------------------------------------------------------------
# Projection and rasterisation
# ---------------------------------------------------------------------------
def _fill_rings(grid, rings, value, dw, dh):
    """Even-odd scanline fill of projected, closed rings into a grid.

    The algorithm is the basemap's, verbatim: even-odd across a group's
    rings means interior rings keep the opposite value, so a hole in a
    park (or an island in a lake) falls out for free.
    """
    ys = [p[1] for ring in rings for p in ring]
    if not ys:
        return
    y0 = max(0, int(min(ys)))
    y1 = min(dh - 1, int(max(ys)) + 1)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for ring in rings:
            for i in range(len(ring) - 1):
                ax, ay = ring[i]
                bx, by = ring[i + 1]
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) / (by - ay) * (bx - ax))
        xs.sort()
        row = grid[y]
        for i in range(0, len(xs) - 1, 2):
            xa = max(0, int(xs[i] + 0.5))
            xb = min(dw, int(xs[i + 1] + 0.5))
            for x in range(xa, xb):
                row[x] = value


def _closed(ring):
    """MVT rings arrive open; the scanline fill wants them closed."""
    return ring + [ring[0]] if ring and ring[0] != ring[-1] else ring


def _big_enough(rings):
    """False for a building footprint smaller than one sub-pixel."""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    return ((max(xs) - min(xs)) * (max(ys) - min(ys))) >= _MIN_BUILDING_DOTS


def fill_class(layer_name, props, band):
    """Which area fill a polygon belongs to at this band, or None.

    Only five classes are admitted, and the band gates are the style
    spec's: water from the start, parks once there is room to read
    them, the urban tint and cemeteries with the street grid, buildings
    only at the very bottom of the zoom range.
    """
    cls = props.get("class")
    if layer_name == "water":
        return None if cls == "swimming_pool" else WATER
    if layer_name == "park":
        return PARK if band >= style.FILL_DEBUT["park"] else None
    if layer_name == "landcover":
        if (band >= style.FILL_DEBUT["park_extra"]
                and props.get("subclass") in style.PARK_LANDCOVER_SUBCLASS):
            return PARK
        return None
    if layer_name == "landuse":
        if band < style.FILL_DEBUT["urban"]:
            return None
        if cls in style.PARK_LANDUSE_CLASS:
            return PARK
        if cls in style.URBAN_LANDUSE:
            return URBAN
        return None
    if layer_name == "building":
        return BUILDING if band >= style.FILL_DEBUT["building"] else None
    return None


def decode_view(tiles):
    """[((z, x, y), layers), ...] in tile-key order.

    Decoded once and shared by the fills, the strokes and the labels;
    walking in key order rather than arrival order is what keeps a slow
    tile from changing the picture.
    """
    view = []
    for key, data in sorted(tiles.items()):
        if not data:
            continue
        try:
            view.append((key, decode_tile(data)))
        except ValueError as exc:
            debug_log(f"street tile {key[0]}/{key[1]}/{key[2]} "
                      f"undecodable: {exc}")
    return view


def class_grid(view, bbox, graph_w, height_cells, band):
    """(fill class grid, water mask) at dot resolution.

    Both are (hc*4) x (gw*2).  The water mask is snapshotted before
    buildings are painted, so the coastline still traces the water
    polygon where a pier or a boathouse sits on top of it.
    """
    dw, dh = graph_w * 2, height_cells * 4
    grid = [bytearray(dw) for _ in range(dh)]
    groups = {URBAN: [], PARK: [], WATER: [], BUILDING: []}
    for (z, tx, ty), decoded in view:
        for name in FILL_LAYERS:
            layer = decoded.get(name)
            if layer is None:
                continue
            extent = layer.get("extent") or _DEFAULT_EXTENT
            project = _projector(z, tx, ty, extent, bbox, dw, dh)
            for feat in layer["features"]:
                if feat["type"] != 3:      # polygons only
                    continue
                cls = fill_class(name, feat["tags"], band)
                if cls is None:
                    continue
                for rings in assemble_polygons(feat["geometry"]):
                    pr = [_closed([project(x, y) for x, y in ring])
                          for ring in rings]
                    if cls == BUILDING and not _big_enough(pr):
                        continue
                    groups[cls].append(pr)

    for cls in (URBAN, PARK, WATER):
        for rings in groups[cls]:
            _fill_rings(grid, rings, cls, dw, dh)
    water = [bytearray(1 if v == WATER else 0 for v in row) for row in grid]
    for rings in groups[BUILDING]:
        _fill_rings(grid, rings, BUILDING, dw, dh)
    return grid, water


# Terrain mode's water, and deliberately not `ocean`: below sea level is
# bathymetry's job there, and OpenMapTiles' low-zoom ocean polygon is
# generalised well past the coastline the elevation data draws — OR-ing
# it in would swallow whole coastal lowlands at continental zoom.
INLAND_WATER_CLASS = ("lake", "river", "pond", "dock", "reservoir")


def inland_water_mask(view, bbox, graph_w, height_cells):
    """(hc*4) x (gw*2) 1/0 mask of the tiles' inland water polygons.

    The same polygons, the same scanline fill and the same dot grid
    street mode uses — terrain mode just wants them without the four
    other fill classes, and without the ocean.
    """
    dw, dh = graph_w * 2, height_cells * 4
    grid = [bytearray(dw) for _ in range(dh)]
    for (z, tx, ty), decoded in view:
        src = decoded.get("water")
        if src is None:
            continue
        extent = src.get("extent") or _DEFAULT_EXTENT
        project = _projector(z, tx, ty, extent, bbox, dw, dh)
        for feat in src["features"]:
            if feat["type"] != 3:      # polygons only
                continue
            if feat["tags"].get("class") not in INLAND_WATER_CLASS:
                continue
            for rings in assemble_polygons(feat["geometry"]):
                _fill_rings(grid, [_closed([project(x, y) for x, y in ring])
                                   for ring in rings], 1, dw, dh)
    return grid


def water_cells(water, graph_w, height_cells):
    """The dot-resolution water mask, reduced to whole cells.

    A cell counts as water when at least half its eight dots are, which
    is the same >=2-of-4 rule the fills use, applied twice over.  Label
    placement works in cells, so this is the grid it wants.
    """
    out = []
    for row in range(height_cells):
        rows = water[row * 4:row * 4 + 4]
        out.append([sum(r[col * 2] + r[col * 2 + 1] for r in rows) >= 4
                    for col in range(graph_w)])
    return out


def fill_cells(grid, graph_w, height_cells):
    """The dot-resolution class grid reduced to one class per cell.

    Hover's last resort, and `water_cells`' >=4-of-8 rule generalised
    past water: the topmost class holding at least half a cell.  A cell
    that is mostly ground reports GROUND, and hover says nothing there
    rather than naming the paper.
    """
    out = []
    for row in range(height_cells):
        rows = grid[row * 4:row * 4 + 4]
        line = bytearray(graph_w)
        for col in range(graph_w):
            dx = col * 2
            for cls in (BUILDING, WATER, PARK, URBAN):
                if sum((r[dx] == cls) + (r[dx + 1] == cls)
                       for r in rows) >= 4:
                    line[col] = cls
                    break
        out.append(line)
    return out


def fill_colors(grid, graph_w, height_cells, palette):
    """Dot-resolution classes -> the sub-pixel RGB grid compose_map wants.

    A sub-pixel spans 2x2 dots and takes the topmost class holding at
    least half of them — the same >=2-of-4 rule as the radar sea mask.
    An entry is None where the palette paints nothing, which is how the
    16-colour and `none` modes end up as line maps.
    """
    inks = [palette.get(key) for key in style.FILL_ORDER]
    out = []
    for spy in range(height_cells * 2):
        top, bot = grid[spy * 2], grid[spy * 2 + 1]
        row = [None] * graph_w
        for x in range(graph_w):
            dx = x * 2
            quad = (top[dx], top[dx + 1], bot[dx], bot[dx + 1])
            row[x] = inks[GROUND]
            for cls in (BUILDING, WATER, PARK, URBAN):
                if (quad[0] == cls) + (quad[1] == cls) \
                        + (quad[2] == cls) + (quad[3] == cls) >= 2:
                    row[x] = inks[cls]
                    break
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Strokes
# ---------------------------------------------------------------------------
def clip_segment(x0, y0, x1, y1, lo_x, lo_y, hi_x, hi_y):
    """Liang-Barsky clip to a window; integer endpoints, or None.

    Unclipped Bresenham is not merely slow on a dense road net, it is
    fatal: a single road vertex a few tiles off screen walks millions of
    dots that are all thrown away.  The cheap bbox reject in front
    handles the common case (most features in a tile are off view).
    """
    if (max(x0, x1) < lo_x or min(x0, x1) > hi_x
            or max(y0, y1) < lo_y or min(y0, y1) > hi_y):
        return None
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - lo_x), (dx, hi_x - x0),
                 (-dy, y0 - lo_y), (dy, hi_y - y0)):
        if p == 0:
            if q < 0:
                return None            # parallel to, and outside, an edge
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return (int(round(x0 + t0 * dx)), int(round(y0 + t0 * dy)),
            int(round(x0 + t1 * dx)), int(round(y0 + t1 * dy)))


def open_water(water, radius=None):
    """Dots where the water runs `radius` clear on all four sides.

    The water a centreline does not need to be drawn through.  Every
    river wide enough to matter arrives twice — a polygon in the `water`
    layer and a centreline in `waterway` — and OpenStreetMap carries the
    centreline the full length of a tidal estuary, so a Portland view
    draws a seam up the middle of the Fore River and another out of Back
    Cove.  The polygon and its coastline already say all of that, and say
    it in the right shape.

    The test is width rather than mere overlap, because a river narrower
    than a dot has no polygon at any zoom and one only a dot or two wide
    has a hairline the centreline is still doing the work of.  Erode the
    mask by `radius` in each direction and what is left is the water that
    can speak for itself.

    Beyond the view the run is assumed to continue: the mask holds only
    what is on screen, and truncating at the edge would leave a stub of
    centreline in the last few dots of the estuary that appears and
    disappears as you pan.
    """
    if radius is None:
        radius = style.WATERWAY_HIDE_DOTS
    dh = len(water)
    dw = len(water[0]) if dh else 0
    out = [bytearray(dw) for _ in range(dh)]
    for y in range(dh):
        src, dst = water[y], out[y]
        run = radius                    # off-screen counts as water
        for x in range(dw):
            run = run + 1 if src[x] else 0
            dst[x] = run > radius
        run = radius
        for x in range(dw - 1, -1, -1):
            run = run + 1 if src[x] else 0
            if run <= radius:
                dst[x] = 0
    for x in range(dw):
        run = radius
        for y in range(dh):
            run = run + 1 if water[y][x] else 0
            if run <= radius:
                out[y][x] = 0
        run = radius
        for y in range(dh - 1, -1, -1):
            run = run + 1 if water[y][x] else 0
            if run <= radius:
                out[y][x] = 0
    return out


def road_shadow(roads, radius):
    """Dots within `radius` of a road dot, Chebyshev.

    The ground a path is not drawn on.  `open_water` erodes a mask to
    find the water that can speak for itself; this dilates one to find
    the road that has already spoken for what lies beside it.

    Separable, like the erosion: a horizontal sweep then a vertical one
    over its result gives the square neighbourhood in two linear passes,
    which matters because the radius grows with the zoom and a naive
    box would be counting the same dots fifteen deep at street level.

    Unlike the erosion, nothing is assumed beyond the view: a road just
    off screen casts no shadow on screen.  It cannot — its own ink is
    clipped at the same edge, so honouring it would suppress a path in
    favour of a road the reader cannot see.
    """
    dh = len(roads)
    dw = len(roads[0]) if dh else 0
    wide = [bytearray(dw) for _ in range(dh)]
    for y in range(dh):
        src, dst = roads[y], wide[y]
        run = radius + 1                    # distance since the last road dot
        for x in range(dw):
            run = 0 if src[x] else run + 1
            if run <= radius:
                dst[x] = 1
        run = radius + 1
        for x in range(dw - 1, -1, -1):
            run = 0 if src[x] else run + 1
            if run <= radius:
                dst[x] = 1
    out = [bytearray(row) for row in wide]
    for x in range(dw):
        run = radius + 1
        for y in range(dh):
            run = 0 if wide[y][x] else run + 1
            if run <= radius:
                out[y][x] = 1
        run = radius + 1
        for y in range(dh - 1, -1, -1):
            run = 0 if wide[y][x] else run + 1
            if run <= radius:
                out[y][x] = 1
    return out


def stroke_polyline(layer, pts, color, rank, weight=1, dash=None,
                    tick_every=0, owner=None, hide=None, mark=None):
    """Walk one projected polyline into a ranked DotLayer.

    `pts` are dot-space floats.  Vertices that round onto the dot the
    walker is already standing on are dropped, so a heavily generalised
    line does not stutter.

    The dash counter runs on the dot index accumulated along the *whole*
    polyline, including spans clipped or rejected off screen, so dashes
    stay in phase through vertices and across the edge of the view — pan
    a dashed border and it slides rather than reshuffling.

    Weight 2 draws the line twice with a perpendicular offset chosen per
    segment from its dominant axis; the basemap's (0,0),(1,0),(0,1)
    triple is deliberately not reused, because it thickens diagonals and
    reads as fuzz.  Weight 3 adds every touched cell to `layer.ribbon`
    for the composer to tint — motorway only, deepest band only.

    `owner` rides along with the ink through the same rank contest, so
    whichever stroke a cell ends up showing is the one hover names.

    `hide` is a dot mask the stroke may not draw into — the one way a
    line yields to an area, and used for exactly that: a river centreline
    inside water already wide enough to draw itself.  The dash counter
    runs on through hidden dots, so a suppressed reach costs the pattern
    its phase no more than an off-screen one does.

    `mark` is the mirror: a dot mask the stroke records itself into, for
    a later stroke to be hidden by.  It is written for every dot the
    walker stands on, dashes and hidden reaches included, because it
    records where the *line* runs and not which of its dots got ink — a
    tunnelled road under a park is still a road the path beside it
    belongs to.
    """
    dots = []
    for x, y in pts:
        p = (int(round(x)), int(round(y)))
        if not dots or p != dots[-1]:
            dots.append(p)
    if len(dots) < 2:
        return

    lo_x, hi_x = -CLIP_MARGIN, layer.dw + CLIP_MARGIN
    lo_y, hi_y = -CLIP_MARGIN, layer.dh + CLIP_MARGIN
    period = (dash[0] + dash[1]) if dash else 0
    i = 0                                   # dot index along the polyline
    for k in range(len(dots) - 1):
        (x0, y0), (x1, y1) = dots[k], dots[k + 1]
        span = max(abs(x1 - x0), abs(y1 - y0))
        clip = clip_segment(x0, y0, x1, y1, lo_x, lo_y, hi_x, hi_y)
        if clip is None:
            i += span                       # off screen, but still counted
            continue
        cx0, cy0, cx1, cy1 = clip
        i += max(abs(cx0 - x0), abs(cy0 - y0))
        # the perpendicular for this segment: across the dominant axis
        ox, oy = (0, 1) if abs(x1 - x0) >= abs(y1 - y0) else (1, 0)
        walk = _bresenham(cx0, cy0, cx1, cy1)
        if k and (cx0, cy0) == (x0, y0):
            next(walk)                      # the previous segment's end
        for px, py in walk:
            on_grid = 0 <= py < layer.dh and 0 <= px < layer.dw
            if mark is not None and on_grid:
                mark[py][px] = 1
                if weight >= 2 and 0 <= py + oy < layer.dh \
                        and 0 <= px + ox < layer.dw:
                    mark[py + oy][px + ox] = 1
            if hide is not None and on_grid and hide[py][px]:
                i += 1
                continue
            if not period or (i % period) < dash[0]:
                layer._set_dot(px, py, color, rank, owner)
                if weight >= 2:
                    layer._set_dot(px + ox, py + oy, color, rank, owner)
                if weight >= 3:
                    layer.ribbon.add((px // 2, py // 4))
                if tick_every and i % tick_every == 0:
                    layer._set_dot(px + ox, py + oy, color, rank, owner)
                    layer._set_dot(px - ox, py - oy, color, rank, owner)
            i += 1
        i += max(abs(x1 - cx1), abs(y1 - cy1))


def line_style(layer_name, props):
    """LINE_STYLES key for a line feature, or None if it is dropped."""
    if layer_name == "transportation":
        return style.road_style(props)
    if layer_name == "waterway":
        return style.waterway_style(props)
    if layer_name == "aeroway":
        return style.aeroway_style(props)
    if layer_name == "boundary":
        return style.boundary_style(props)
    return None


def stroke_ink(key, props, palette):
    """(colour, dash) for one feature of a style class.

    A tunnel takes 45% of the ground and a one-on-one-off dash at its
    parent's rank.  It is the one brunnel rule worth having: a bridge
    casing needs to knock a hole in the layers underneath, which an
    OR-only dot mask cannot do, but a faded dashed line preserves
    network continuity and lets the eye complete it.
    """
    ink_key, _weights, dash, _rank = style.LINE_STYLES[key]
    color = palette.get(ink_key, style._PALETTE_16_DEFAULT)
    if props.get("brunnel") == "tunnel":
        ground = palette.get("ground")
        if ground is not None:
            color = lerp_rgb(ground, color, style.TUNNEL_BLEND)
        dash = style.DASH11
    return color, dash


def draw_lines(layer, view, bbox, graph_w, height_cells, band, palette,
               lang="en", feats=None, water=None):
    """Walk every admitted line feature into the view's one DotLayer.

    Feature order is irrelevant here — each stroke carries its class
    rank, so a motorway that arrives in the last tile still owns the
    cells it crosses.

    Returns the feature table hover reads: index -> (style key, name).
    Strokes sharing a class *and* a name merge into one entry, so
    hovering any reach of a river lights the river rather than the
    segment the tile happened to cut.  Only `waterway` carries names at
    all in these layers — the road net's are in a different layer
    entirely, and _maps_hover joins them back by cell.

    Nameless geometry is owned one *part* at a time, and that is not a
    detail.  A vector tile is not a list of roads: the encoder merges
    every line sharing a class and its attributes into a single
    multi-part feature, so all of a town's unnamed residential streets
    can arrive as one `feature` with four hundred linestrings in it.
    Owning that per feature makes hovering any back street light the
    whole town.  A part is the honest unit — one continuous run of the
    line, which is as much of a street as the tile is willing to say.

    `water` is the view's dot mask of the water fills.  Given it, a river
    centreline is suppressed wherever the polygon around it is wide
    enough to draw itself — see `open_water`.  The eroded mask is derived
    on the first waterway feature, because most views have none.

    Paths are the one class that cannot be walked in stride, because
    whether a path is drawn depends on where the roads went.  They are
    collected on the way past — owning their feats entries in the order
    they arrive, so nothing downstream can tell — and walked at the end
    against the finished road shadow.  The rank contest makes the delay
    free: a stroke's class decides the cells it keeps, never its turn.
    """
    feats = [] if feats is None else feats
    by_name = {(k, n): i for i, (k, n) in enumerate(feats) if n}
    dw, dh = graph_w * 2, height_cells * 4
    hide = None
    roads = [bytearray(dw) for _ in range(dh)]
    deferred = []
    for (z, tx, ty), decoded in view:
        for name in LINE_LAYERS:
            src = decoded.get(name)
            if src is None:
                continue
            extent = src.get("extent") or _DEFAULT_EXTENT
            project = _projector(z, tx, ty, extent, bbox, dw, dh)
            for feat in src["features"]:
                if feat["type"] != 2:       # linestrings only
                    continue
                props = feat["tags"]
                key = line_style(name, props)
                if key is None:
                    continue
                weight = style.LINE_STYLES[key][1][band]
                if not weight:
                    continue
                color, dash = stroke_ink(key, props, palette)
                rank = style.LINE_STYLES[key][3]
                ticks = style.RAIL_TICK_EVERY if key == "rail" else 0
                if water is not None and key in style.WATERWAY_KEYS:
                    if hide is None:
                        hide = open_water(water)
                    masked = hide
                else:
                    masked = None
                label = _maps_labels._name(props, lang)
                owner = None
                if label:
                    owner = by_name.get((key, label))
                    if owner is None:
                        owner = by_name[(key, label)] = len(feats)
                        feats.append((key, label))
                casts = roads if key in style.SHADOW_CASTING else None
                for part in feat["geometry"]:
                    if label:
                        part_owner = owner
                    else:
                        part_owner = len(feats)
                        feats.append((key, ""))
                    pts = [project(x, y) for x, y in part]
                    if key in style.SHADOWED:
                        deferred.append(
                            (pts, color, rank, weight, dash, part_owner))
                        continue
                    stroke_polyline(
                        layer, pts, color, rank, weight, dash, ticks,
                        part_owner, masked, casts)
    if deferred:
        shadow = road_shadow(roads, style.path_shadow_dots(bbox, dh))
        for pts, color, rank, weight, dash, part_owner in deferred:
            stroke_polyline(layer, pts, color, rank, weight, dash, 0,
                            part_owner, shadow)
    return feats


def water_lines(view, bbox, graph_w, height_cells, band, color, water=None):
    """The tiles' waterways as their own braille layer.

    A river narrower than a dot has no polygon at any zoom — it is a
    linestring or it is nothing, which is why a lake mask on its own
    still leaves a valley looking dry.  The band gates are terrain's own
    (style.TERRAIN_WATERWAY_WEIGHTS), not street's; ferries are not
    water and stay behind either way.

    The converse holds too, which is what `water` is for: where the mask
    beside this layer already paints water wide enough to read, the
    centreline through it is a seam and is suppressed.  Terrain passes
    its own inland mask, so the rule always answers for the water this
    mode actually draws.
    """
    layer = DotLayer(bbox, graph_w, height_cells)
    hide = open_water(water) if water is not None else None
    dw, dh = graph_w * 2, height_cells * 4
    for (z, tx, ty), decoded in view:
        src = decoded.get("waterway")
        if src is None:
            continue
        extent = src.get("extent") or _DEFAULT_EXTENT
        project = _projector(z, tx, ty, extent, bbox, dw, dh)
        for feat in src["features"]:
            if feat["type"] != 2:      # linestrings only
                continue
            key = style.waterway_style(feat["tags"])
            if key is None:
                continue
            weights = style.TERRAIN_WATERWAY_WEIGHTS.get(key)
            if weights is None or not weights[band]:
                continue      # a class terrain does not draw (e.g. ferry)
            weight = weights[band]
            rank = style.LINE_STYLES[key][3]
            for part in feat["geometry"]:
                stroke_polyline(layer, [project(x, y) for x, y in part],
                                color, rank, weight, hide=hide)
    return layer


def build_water_view(bbox, graph_w, height_cells, tiles, band, color):
    """(inland water dot mask, waterway layer) — terrain mode's half.

    The pure half, exactly as build_street_view is: tiles in, geometry
    out, no network.  One decode feeds both, because a view that has
    already paid for the tiles should get the rivers with the lakes.
    """
    view = decode_view(tiles)
    water = inland_water_mask(view, bbox, graph_w, height_cells)
    return (water,
            water_lines(view, bbox, graph_w, height_cells, band, color,
                        water))


# A coast dot sits on the *land* side of the boundary (_edge_dots only
# ever strokes land), so the water it goes round is a neighbour, never
# the cell itself.  Ties are broken by this order, which is the reading
# order of the neighbourhood — deterministic, and the same answer at
# every pan position.
_SHORE_LOOK = ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
               (-1, -1), (1, -1), (-1, 1), (1, 1))


def water_owners(coast, wet, waters, feats, graph_w, height_cells):
    """(coast owner grid, per-cell shore owner for water cells).

    The coastline is one mask and many things.  Drawn, it is the
    boundary of the whole water mask; read, each stretch of it is the
    rim of *this* lake, and a reader pointing at the edge of Graham Lake
    means Graham Lake and not every shore in the county.  So the mask is
    split by the connected components of the water it goes round — the
    same components the labels named — and each becomes its own feature.

    Both grids point at the same features, which is what lets the middle
    of a lake and its rim answer identically: the fill has no ink of its
    own, so a water cell is filed against the shore that encloses it.

    A component is not always one body, though, and on a coast it
    almost never is: Casco Bay, Back Cove, the harbour and the Fore
    River are one connected sheet of salt water, and filing all of it
    under one name told a reader pointing at the harbour that they were
    looking at Back Cove.  So the unit is the *named claim* — what
    `water_claims` decided each cell is called — and a region is split
    into as many features as it has names on it.  A body the tile never
    named still gets its own feature, one region at a time: "water" is
    all it can say, but it can at least say it about one pond instead of
    about every pond on screen.
    """
    index, regions = _maps_labels.water_regions(wet)
    if not regions:
        return None, None
    owner_of, shore = {}, [[None] * graph_w for _ in range(height_cells)]
    for row, line in enumerate(index):
        for col, region in enumerate(line):
            if region < 0:
                continue
            body = (region, waters.get((col, row), ""))
            idx = owner_of.get(body)
            if idx is None:
                idx = owner_of[body] = len(feats)
                feats.append(("coast", body[1]))
            shore[row][col] = idx

    coast_owners = [[0] * graph_w for _ in range(height_cells)]
    for cy, mrow in enumerate(coast):
        for cx, m in enumerate(mrow):
            if not m:
                continue
            for dx, dy in _SHORE_LOOK:
                c, r = cx + dx, cy + dy
                if 0 <= c < graph_w and 0 <= r < height_cells \
                        and shore[r][c] is not None:
                    coast_owners[cy][cx] = shore[r][c]
                    break
    return coast_owners, shore


def build_street_view(bbox, graph_w, height_cells, tiles, band, lang="en",
                      reserved=()):
    """(fills, layer, overlays) for one view — the pure half, no network.

    `tiles` maps (z, x, y) to raw MVT bytes, or to None for a tile that
    could not be read; a missing tile simply contributes nothing.
    `reserved` are cells the caller has already spoken for (the marker
    and the crosshair), which labels must route around.

    The layer comes back carrying `.hover`, the index that answers what
    is under a pointer.  It is built here rather than on demand because
    it is a property of the view, and the view is what gets cached: a
    pointer crossing a static map must cost a lookup, not a rebuild.
    """
    palette = style.palette()
    view = decode_view(tiles)
    grid, water = class_grid(view, bbox, graph_w, height_cells, band)
    fills = fill_colors(grid, graph_w, height_cells, palette)

    # Labels run before the raster, against the same water mask, because
    # naming the water is what tells the shore which shore it is.
    wet = water_cells(water, graph_w, height_cells)
    marks, texts, waters = {}, {}, {}
    overlays = _maps_labels.label_overlays(
        view, bbox, graph_w, height_cells, band, palette, lang, reserved,
        wet, marks, texts, waters)

    layer = DotLayer(bbox, graph_w, height_cells)
    land = [bytearray(1 - v for v in row) for row in water]
    coast = _edge_dots(land, water, graph_w, height_cells)
    ink = palette.get("coast", style._PALETTE_16_DEFAULT)
    feats = [("coast", "")]
    coast_owners, shore = water_owners(coast, wet, waters, feats,
                                       graph_w, height_cells)
    layer.or_mask(coast, ink, style.LINE_STYLES["coast"][3], owner=0,
                  owners=coast_owners)
    draw_lines(layer, view, bbox, graph_w, height_cells, band, palette,
               lang, feats, water)
    layer.hover = _maps_hover.HoverIndex(
        layer.owner, feats,
        _maps_hover.road_names(view, bbox, graph_w, height_cells, band,
                               lang),
        marks, fill_cells(grid, graph_w, height_cells), texts, shore)
    return fills, layer, overlays
