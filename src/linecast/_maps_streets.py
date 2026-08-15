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

from linecast import _maps_style as style
from linecast._mvt import assemble_polygons, decode_tile
from linecast._radar_basemap import DotLayer, _edge_dots
from linecast._runtime import debug_log
from linecast._vtiles import fetch_tiles, tile_info, tiles_for_bbox

# Fill ids double as indices into style.FILL_ORDER, so the id order *is*
# the stacking order: water over park (a pond in a park), park over
# urban, buildings on everything.
GROUND, URBAN, PARK, WATER, BUILDING = 0, 1, 2, 3, 4

# The only layers with polygons worth painting. `landcover` is admitted
# for parks alone — no grass, wood, farmland, wetland or sand, because
# green-washing a rural view buys the reader nothing.
FILL_LAYERS = ("water", "park", "landcover", "landuse", "building")

_MAX_TILES = 16          # a view needs ~4; more means a pathological window
_DEFAULT_EXTENT = 4096
_MIN_BUILDING_DOTS = 4.0  # one sub-pixel is 2x2 dots


# ---------------------------------------------------------------------------
# Which tiles a view needs
# ---------------------------------------------------------------------------
def view_tiles(bbox, height_cells):
    """(band, z_src, [(z, x, y), ...]) for a view.

    The source zoom comes from the style model, which lands on
    OpenMapTiles' own generalisation floors, so the band table never
    asks for a class the tile does not carry.  A window wide enough to
    need more than _MAX_TILES tiles is coarsened a zoom at a time rather
    than silently truncated — and says so in the debug log.
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
def _projector(z, tx, ty, extent, bbox, dw, dh):
    """Tile-local (x, y) -> dot-space (x, y) for one tile in one view.

    Tile coordinates are web mercator; the view is linear in lon/lat
    (bbox_for already put the aspect correction in the bbox, which is
    what makes a braille dot ground-square).  Going through lon/lat
    rather than staying in mercator keeps street mode registered with
    the elevation grid and the Natural Earth basemap to the dot.
    """
    n = float(1 << z)
    minlon, minlat, maxlon, maxlat = bbox
    lon_span = (maxlon - minlon) or 1e-12
    lat_span = (maxlat - minlat) or 1e-12

    def project(px, py):
        lon = (tx + px / extent) / n * 360.0 - 180.0
        wy = (ty + py / extent) / n
        lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy))))
        # a view spanning the antimeridian holds wrapped tiles, whose
        # longitudes come back on the far side of the world
        if lon < minlon - 180.0:
            lon += 360.0
        elif lon > maxlon + 180.0:
            lon -= 360.0
        return ((lon - minlon) / lon_span * dw,
                (maxlat - lat) / lat_span * dh)

    return project


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


def class_grid(tiles, bbox, graph_w, height_cells, band):
    """(fill class grid, water mask) at dot resolution.

    Both are (hc*4) x (gw*2).  The water mask is snapshotted before
    buildings are painted, so the coastline still traces the water
    polygon where a pier or a boathouse sits on top of it.
    """
    dw, dh = graph_w * 2, height_cells * 4
    grid = [bytearray(dw) for _ in range(dh)]
    groups = {URBAN: [], PARK: [], WATER: [], BUILDING: []}
    # Tiles are walked in key order, never arrival order, so a slow tile
    # can never change the picture.
    for (z, tx, ty), data in sorted(tiles.items()):
        if not data:
            continue
        try:
            decoded = decode_tile(data)
        except ValueError as exc:
            debug_log(f"street tile {z}/{tx}/{ty} undecodable: {exc}")
            continue
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


def build_street_view(bbox, graph_w, height_cells, tiles, band):
    """(fills, layer) for one view — the pure half, no network.

    `tiles` maps (z, x, y) to raw MVT bytes, or to None for a tile that
    could not be read; a missing tile simply contributes nothing.
    """
    palette = style.palette()
    grid, water = class_grid(tiles, bbox, graph_w, height_cells, band)
    fills = fill_colors(grid, graph_w, height_cells, palette)

    layer = DotLayer(bbox, graph_w, height_cells)
    land = [bytearray(1 - v for v in row) for row in water]
    coast = _edge_dots(land, water, graph_w, height_cells)
    ink = palette.get("coast", style._PALETTE_16_DEFAULT)
    layer.or_mask(coast, ink, style.LINE_STYLES["coast"][3])
    return fills, layer
