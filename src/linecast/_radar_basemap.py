"""Braille geography layer for the radar view.

Coastlines and borders are drawn in braille at 2x4-dot-per-cell resolution;
the sea is a solid block-colour fill at half-block (sub-pixel) resolution so
the weather radar can blend over it at full resolution.  This module loads
the vendored Natural Earth data, rasterises a land/sea mask, and produces
per-cell braille dot masks + colours, a sub-pixel sea mask, and city label
overlays for a given geographic window.

Data: Natural Earth (public domain, 1:50m), simplified globally by
prototype/build_basemap_data.py → data/basemap.json.gz.  Per view we clip to
the visible bounding box so a whole-world dataset stays cheap to rasterise.
"""

import gzip
import json
import math
import os
import unicodedata

from linecast._theme import is_light_theme, lerp_rgb, theme_bg

# braille dot bit for (col, row) within a 2x4 cell — matches _braille.py
_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

# geography palette (dim, so radar reads on top)
COAST = (120, 150, 178)
BORDER = (108, 110, 130)
CITY = (225, 225, 235)
CITY_LABEL = (155, 160, 175)

# The sea is a solid block-colour fill (not a braille stipple), so the radar
# echo keeps its full half-block resolution over water and glyphs drawn on
# top don't have to knock a hole in a stipple to stay legible.  Derived from
# the terminal theme so it reads as water on dark and light backgrounds.
if is_light_theme(theme_bg):
    SEA_FILL = lerp_rgb(theme_bg, (120, 155, 205), 0.35)
else:
    SEA_FILL = lerp_rgb(theme_bg, (70, 100, 150), 0.42)

_DATA = None


def _cell_width(ch):
    """Terminal columns a single character occupies (2 for CJK/wide glyphs)."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _localized(entry, lang):
    """Resolve a city entry's display name for ``lang``, falling back to the
    default Latin name when no translation is stored."""
    if len(entry) > 4 and entry[4]:
        localized = entry[4].get(lang)
        if localized:
            return localized
    return entry[3]


def _load_data():
    global _DATA
    if _DATA is None:
        path = os.path.join(os.path.dirname(__file__), "data",
                            "basemap.json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            _DATA = json.load(fh)
    return _DATA


def nearest_city(lat, lon, lang="en"):
    """(name, dist_km, bearing_deg) of the closest known city, or None.

    bearing_deg is the direction *from the city to the point*, so a result of
    ("Boston", 23, 45) reads "23 km NE of Boston".  Works off the vendored
    Natural Earth populated-places list, so it needs no network.  ``lang``
    localizes the returned name when a translation is available.
    """
    best = None
    coslat = math.cos(math.radians(lat))
    for entry in _load_data()["cities"]:
        clon, clat = entry[0], entry[1]
        # equirectangular approximation is plenty for ranking candidates
        dx = ((lon - clon + 180.0) % 360.0 - 180.0) * coslat
        dy = lat - clat
        d2 = dx * dx + dy * dy
        if best is None or d2 < best[0]:
            best = (d2, _localized(entry, lang), clat, clon)
    if best is None:
        return None
    _, name, clat, clon = best
    from linecast._geo import haversine_nm
    dist_km = haversine_nm(clat, clon, lat, lon) * 1.852
    dlon = math.radians(lon - clon)
    y = math.sin(dlon) * math.cos(math.radians(lat))
    x = (math.cos(math.radians(clat)) * math.sin(math.radians(lat))
         - math.sin(math.radians(clat)) * math.cos(math.radians(lat))
         * math.cos(dlon))
    bearing = math.degrees(math.atan2(y, x)) % 360.0
    return name, dist_km, bearing


def marine_region(lat, lon):
    """Name of the most specific vendored water body containing the point.

    The vendored list is sorted smallest-area-first at build time, so the
    first containing feature is the most specific ("Gulf of Maine" wins over
    "North Atlantic Ocean").  Even-odd ray casting across all of a feature's
    rings (exteriors and holes alike) decides containment.  Returns None on
    land or in unnamed water.
    """
    for name, _area, rings in _load_data().get("marine", ()):
        inside = False
        for ring in rings:
            for i in range(len(ring) - 1):
                (x0, y0), (x1, y1) = ring[i], ring[i + 1]
                if (y0 <= lat < y1) or (y1 <= lat < y0):
                    if lon < x0 + (lat - y0) / (y1 - y0) * (x1 - x0):
                        inside = not inside
        if inside:
            return name
    return None


def _project(lon, lat, bbox, w, h):
    minlon, minlat, maxlon, maxlat = bbox
    x = (lon - minlon) / (maxlon - minlon) * w
    y = (maxlat - lat) / (maxlat - minlat) * h
    return x, y


def _edge_dots(is_land, is_water, gw, hc):
    """Braille masks stroking the land/water boundary of dot masks.

    Both masks are (hc*4) x (gw*2) truthy/falsy grids at exactly braille
    dot resolution (2x4 per cell).  A dot is set only where
    ``is_land[dy][dx]`` and a 4-neighbour has ``is_water`` — so the
    stroke and the colour boundary can never disagree, at any zoom, from
    any data source, and *unknown* samples (in neither mask) are never
    stroked from either side.
    """
    dh, dw = hc * 4, gw * 2
    dots = [[0] * gw for _ in range(hc)]
    for dy in range(dh):
        land = is_land[dy]
        here = is_water[dy]
        up = is_water[dy - 1] if dy > 0 else None
        down = is_water[dy + 1] if dy < dh - 1 else None
        for dx in range(dw):
            if not land[dx]:
                continue
            if ((dx > 0 and here[dx - 1])
                    or (dx < dw - 1 and here[dx + 1])
                    or (up is not None and up[dx])
                    or (down is not None and down[dx])):
                dots[dy // 4][dx // 2] |= _BITS[dx % 2][dy % 4]
    return dots


class DotLayer:
    """A braille dot grid (2x4 dots per cell) with per-cell colour.

    The drawing primitives shared by the geography basemap and any other
    braille-stroke layer (e.g. warning polygon outlines).

    A cell holds exactly one ink, so who owns it is decided by `rank`:
    the highest rank drawn into a cell keeps its colour, and equal ranks
    fall back to last-writer-wins.  Radar draws in priority order and
    passes no rank at all, which is exactly the old behaviour; street
    mode walks features in arbitrary per-tile order and leans on the
    rank instead, so tile arrival order can never change the picture.
    """

    def __init__(self, bbox, graph_w, height_cells):
        self.bbox = bbox
        self.graph_w = graph_w
        self.height_cells = height_cells
        self.dw = graph_w * 2      # dot columns
        self.dh = height_cells * 4  # dot rows
        # per-cell braille state
        self.dots = [[0] * graph_w for _ in range(height_cells)]
        self.color = [[None] * graph_w for _ in range(height_cells)]
        self.rank = [[-1] * graph_w for _ in range(height_cells)]
        self.ribbon = set()        # (cx, cy) cells claimed by w3 strokes

    # -- rasterisation helpers ------------------------------------------------
    def _set_dot(self, dx, dy, color, rank=0):
        if dx < 0 or dx >= self.dw or dy < 0 or dy >= self.dh:
            return
        cx, cy = dx // 2, dy // 4
        self.dots[cy][cx] |= _BITS[dx % 2][dy % 4]
        if rank >= self.rank[cy][cx]:   # ties: last writer wins, as before
            self.rank[cy][cx] = rank
            self.color[cy][cx] = color

    def or_mask(self, mask, color, rank=0):
        """Admit a cell-indexed dot bitmask (e.g. _edge_dots output).

        The mask's dots OR into the grid; the cells it touches follow the
        same rank contest as a stroke, so an edge mask and a line layer
        can share one DotLayer without either having to be drawn last.
        """
        for cy, mrow in enumerate(mask):
            row = self.dots[cy]
            for cx, m in enumerate(mrow):
                if m:
                    row[cx] |= m
                    if rank >= self.rank[cy][cx]:
                        self.rank[cy][cx] = rank
                        self.color[cy][cx] = color

    def _dot_line(self, x0, y0, x1, y1, color, rank=0):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self._set_dot(x0, y0, color, rank)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _in_view(self, points):
        """True if a feature's lon/lat bbox overlaps the view (cheap cull)."""
        minlon, minlat, maxlon, maxlat = self.bbox
        lo_lon = lo_lat = float("inf")
        hi_lon = hi_lat = float("-inf")
        for lon, lat in points:
            if lon < lo_lon:
                lo_lon = lon
            if lon > hi_lon:
                hi_lon = lon
            if lat < lo_lat:
                lo_lat = lat
            if lat > hi_lat:
                hi_lat = lat
        return not (hi_lon < minlon or lo_lon > maxlon
                    or hi_lat < minlat or lo_lat > maxlat)

    def _draw_lines(self, lines, color, width=1, rank=0):
        offsets = ((0, 0),) if width <= 1 else ((0, 0), (1, 0), (0, 1))
        for coords in lines:
            if not self._in_view(coords):
                continue
            prev = None
            for lon, lat in coords:
                p = _project(lon, lat, self.bbox, self.dw, self.dh)
                if prev is not None:
                    for ox, oy in offsets:
                        self._dot_line(prev[0] + ox, prev[1] + oy,
                                       p[0] + ox, p[1] + oy, color, rank)
                prev = p


class Basemap(DotLayer):
    """Pre-rasterised braille geography for one (bbox, size). Reused per frame."""

    def __init__(self, bbox, graph_w, height_cells):
        super().__init__(bbox, graph_w, height_cells)
        self._build()

    def _fill_polys(self, land, poly_groups, value):
        """Scanline-fill each polygon (a list of rings) into ``land`` at dot
        resolution, writing ``value`` inside.  Even-odd across a group's rings
        means interior rings (island holes) keep the opposite value, so filling
        land with 1 and then carving lakes with 0 both respect their holes."""
        for rings in poly_groups:
            if not self._in_view([p for ring in rings for p in ring]):
                continue
            # project rings to dot space
            prings = [[_project(lon, lat, self.bbox, self.dw, self.dh)
                       for lon, lat in ring] for ring in rings]
            ys = [p[1] for ring in prings for p in ring]
            y0 = max(0, int(min(ys)))
            y1 = min(self.dh - 1, int(max(ys)) + 1)
            for y in range(y0, y1 + 1):
                yc = y + 0.5
                xs = []
                for ring in prings:
                    n = len(ring)
                    for i in range(n - 1):
                        ax, ay = ring[i]
                        bx, by = ring[i + 1]
                        if (ay <= yc < by) or (by <= yc < ay):
                            xs.append(ax + (yc - ay) / (by - ay) * (bx - ax))
                xs.sort()
                row = land[y]
                for i in range(0, len(xs) - 1, 2):
                    xa = max(0, int(xs[i] + 0.5))
                    xb = min(self.dw, int(xs[i + 1] + 0.5))
                    for x in range(xa, xb):
                        row[x] = value

    def _sea_mask(self):
        """Boolean land mask at dot resolution via scanline polygon fill.

        Lakes are carved back to water after the land fill: Natural Earth's
        land polygons have no lake holes cut out, so the Great Lakes (and every
        other inland water body) would otherwise fill solid as land."""
        land = [bytearray(self.dw) for _ in range(self.dh)]
        data = _load_data()
        self._fill_polys(land, data["land"], 1)
        self._fill_polys(land, data.get("lakes", ()), 0)
        return land

    def _build(self):
        # 1) sea as a solid fill at half-block (sub-pixel) resolution: one
        # sub-pixel spans a 2x2 block of braille dots, and is sea when at
        # least half of them fall on water.  compose() paints these
        # sub-pixels SEA_FILL and blends the radar echo over them, so the
        # weather keeps its full resolution over the ocean (the block edge
        # is coarse, but the coastline braille re-adds the crisp boundary).
        land = self._sea_mask()
        spy_h = self.height_cells * 2
        self.sea = [[False] * self.graph_w for _ in range(spy_h)]
        for spy in range(spy_h):
            srow = self.sea[spy]
            top, bot = land[spy * 2], land[spy * 2 + 1]
            for x in range(self.graph_w):
                dx = x * 2
                water = ((not top[dx]) + (not top[dx + 1])
                         + (not bot[dx]) + (not bot[dx + 1]))
                if water >= 2:
                    srow[x] = True
        # 2) coastlines, then borders on top (priority order). Coast strokes
        # are the land polygons' own outlines, so the emphasized coastline and
        # the land/sea fill boundary can never disagree.
        data = _load_data()
        coast = [ring for rings in data["land"] for ring in rings]
        # lake shorelines are coastlines too: draw them in COAST so the crisp
        # boundary is re-added over the coarse sub-pixel water fill, exactly as
        # for the ocean coast.
        coast += [ring for rings in data.get("lakes", ()) for ring in rings]
        self._draw_lines(coast, COAST)
        self._draw_lines(data["borders"], BORDER)

    # -- city labels ----------------------------------------------------------
    def city_overlays(self, max_cities=None, lang="en"):
        """{(col,row): (char, color)} for the biggest cities in view + labels.

        The label budget scales with the visible area, and biggest-first
        greedy placement skips cities too close to an already-placed one, so
        wide views show the majors and close views fill in the local towns.
        ``lang`` selects localized placenames where the vendored data has
        them, falling back to the default Latin name.

        Labels are placed one terminal *column* at a time: CJK and other
        double-width glyphs consume two columns, with the trailing column
        marked by an ``("", None)`` sentinel so the renderer emits nothing
        there (the wide glyph already covers it) and the row stays aligned.
        """
        if max_cities is None:
            max_cities = max(6, min(24, (self.graph_w * self.height_cells) // 400))
        minlon, minlat, maxlon, maxlat = self.bbox
        inview = []
        for entry in _load_data()["cities"]:
            lon, lat, pop = entry[0], entry[1], entry[2]
            if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
                inview.append((pop, _localized(entry, lang), lon, lat))
        inview.sort(key=lambda c: c[0], reverse=True)

        overlays = {}
        placed = []
        for _pop, name, lon, lat in inview:
            if len(placed) >= max_cities:
                break
            x, y = _project(lon, lat, self.bbox, self.graph_w, self.height_cells)
            col, row = int(x), int(y)
            if not (0 <= col < self.graph_w and 0 <= row < self.height_cells):
                continue
            if (col, row) in overlays:
                continue
            # keep labels breathable: skip anything crowding a placed marker
            if any(abs(col - pc) < 16 and abs(row - pr) < 3 for pc, pr in placed):
                continue
            placed.append((col, row))
            overlays[(col, row)] = ("•", CITY)  # •
            # label to the right, unless it runs off the edge or collides
            c = col + 1
            for ch in name:
                w = _cell_width(ch)
                if c + w > self.graph_w:
                    break
                if (c, row) in overlays or (w == 2 and (c + 1, row) in overlays):
                    break
                overlays[(c, row)] = (ch, CITY_LABEL)
                if w == 2:
                    overlays[(c + 1, row)] = ("", None)  # consumed by wide glyph
                c += w
        return overlays
