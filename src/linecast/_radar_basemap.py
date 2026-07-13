"""Braille geography layer for the radar view.

Everything that is *geography* (sea, coastlines, borders) is drawn in braille
at 2x4-dot-per-cell resolution; the weather radar is painted over it as a
half-block colour fill by the renderer.  This module loads the vendored
Natural Earth data, rasterises a land/sea mask, and produces per-cell braille
dot masks + colours plus city label overlays for a given geographic window.

Data: Natural Earth (public domain), simplified & clipped to CONUS by
prototype/build_basemap_data.py → data/basemap_us.json.
"""

import json
import os

# braille dot bit for (col, row) within a 2x4 cell — matches _braille.py
_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

# geography palette (dim, so radar reads on top)
SEA = (52, 72, 112)
COAST = (120, 150, 178)
BORDER = (108, 110, 130)
CITY = (225, 225, 235)
CITY_LABEL = (155, 160, 175)

_DATA = None


def _load_data():
    global _DATA
    if _DATA is None:
        path = os.path.join(os.path.dirname(__file__), "data", "basemap_us.json")
        with open(path) as fh:
            _DATA = json.load(fh)
    return _DATA


def _project(lon, lat, bbox, w, h):
    minlon, minlat, maxlon, maxlat = bbox
    x = (lon - minlon) / (maxlon - minlon) * w
    y = (maxlat - lat) / (maxlat - minlat) * h
    return x, y


class Basemap:
    """Pre-rasterised braille geography for one (bbox, size). Reused per frame."""

    def __init__(self, bbox, graph_w, height_cells):
        self.bbox = bbox
        self.graph_w = graph_w
        self.height_cells = height_cells
        self.dw = graph_w * 2      # dot columns
        self.dh = height_cells * 4  # dot rows
        # per-cell braille state
        self.dots = [[0] * graph_w for _ in range(height_cells)]
        self.color = [[None] * graph_w for _ in range(height_cells)]
        self._build()

    # -- rasterisation helpers ------------------------------------------------
    def _set_dot(self, dx, dy, color):
        if dx < 0 or dx >= self.dw or dy < 0 or dy >= self.dh:
            return
        cx, cy = dx // 2, dy // 4
        self.dots[cy][cx] |= _BITS[dx % 2][dy % 4]
        self.color[cy][cx] = color  # last writer wins (drawn in priority order)

    def _dot_line(self, x0, y0, x1, y1, color):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self._set_dot(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _draw_lines(self, lines, color):
        for coords in lines:
            prev = None
            for lon, lat in coords:
                p = _project(lon, lat, self.bbox, self.dw, self.dh)
                if prev is not None:
                    self._dot_line(prev[0], prev[1], p[0], p[1], color)
                prev = p

    def _sea_mask(self):
        """Boolean land mask at dot resolution via scanline polygon fill."""
        land = [bytearray(self.dw) for _ in range(self.dh)]
        for rings in _load_data()["land"]:
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
                        row[x] = 1
        return land

    def _build(self):
        # 1) sea stipple everywhere that isn't land (checkerboard dither)
        land = self._sea_mask()
        for dy in range(self.dh):
            lrow = land[dy]
            for dx in range(self.dw):
                if not lrow[dx] and (dx + dy) % 2 == 0:
                    self._set_dot(dx, dy, SEA)
        # 2) coastlines, then borders on top (priority order)
        data = _load_data()
        self._draw_lines(data["coast"], COAST)
        self._draw_lines(data["borders"], BORDER)

    # -- city labels ----------------------------------------------------------
    def city_overlays(self, max_cities=8):
        """{(col,row): (char, color)} for the biggest cities in view + labels."""
        minlon, minlat, maxlon, maxlat = self.bbox
        inview = []
        for lon, lat, pop, name in _load_data()["cities"]:
            if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
                inview.append((pop, name, lon, lat))
        inview.sort(reverse=True)

        overlays = {}
        for _pop, name, lon, lat in inview[:max_cities]:
            x, y = _project(lon, lat, self.bbox, self.graph_w, self.height_cells)
            col, row = int(x), int(y)
            if not (0 <= col < self.graph_w and 0 <= row < self.height_cells):
                continue
            if (col, row) in overlays:
                continue
            overlays[(col, row)] = ("•", CITY)  # •
            # label to the right, unless it collides
            for j, ch in enumerate(name):
                c = col + 1 + j
                if c >= self.graph_w or (c, row) in overlays:
                    break
                overlays[(c, row)] = (ch, CITY_LABEL)
        return overlays
