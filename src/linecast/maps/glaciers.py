"""The vendored glacier grid terrain paints its ice from.

One global raster, 0.1° and 43 KB, baked from Natural Earth's 1:10m
glaciated areas by scripts/build_glacier_grid.py: each cell holds the
share of it under ice, 0 to 255, and everything south of 60°S is ice.
It is the ice wherever the vector tiles are too coarse to draw their
own (below style.GLACIER_TILE_ZOOM) and on the globe, which has no
tiles at all — so the Gulf of Alaska's coastal icefields are drawn
from the same outlines as the Greenland ice sheet, offline included.

A sample is ice where the grid, read bilinearly at its point, is half
ice or more: the cells' edges never show, and the ice a view draws
covers the ground Natural Earth gives it.
"""

import math

from linecast._paths import data_path
from linecast._log import log_failure

_HALF = 128
_BLOCK = 10       # cells to a block: one degree

_grid = None      # (w, h, cells, blocks) once loaded; a failed load stays None
_tried = False


def _load():
    """(w, h, cells, blocks), or None if the data file is unreadable.

    `blocks` flags each degree square that has ice in it or in a
    neighbouring square, so a sample can be cleared with one lookup
    before the four the bilinear read costs — most of the planet is
    not glacier, and the globe's bake samples all of it.
    """
    global _grid, _tried
    if _grid is not None or _tried:
        return _grid
    _tried = True
    try:
        from linecast._png import decode_rgba
        w, h, rgba = decode_rgba(data_path("glaciers.png").read_bytes())
        # grayscale decodes to RGBA; the ice fraction is the R channel
        cells = bytes(rgba[::4])
        bw, bh = w // _BLOCK, h // _BLOCK
        own = bytearray(bw * bh)
        for y in range(h):
            row = cells[y * w:(y + 1) * w]
            if row.count(0) == w:
                continue
            by = y // _BLOCK
            for bx in range(bw):
                if row[bx * _BLOCK:(bx + 1) * _BLOCK].count(0) < _BLOCK:
                    own[by * bw + bx] = 1
        blocks = bytearray(bw * bh)
        for by in range(bh):
            for bx in range(bw):
                if own[by * bw + bx]:
                    for ny in range(max(0, by - 1), min(bh, by + 2)):
                        for nx in (bx - 1, bx, bx + 1):
                            blocks[ny * bw + nx % bw] = 1
        _grid = (w, h, cells, bytes(blocks))
    except Exception as exc:
        log_failure("png", "glacier grid load", exc,
                    fallback="the vector tiles' ice alone")
        _grid = None
    return _grid


def available() -> bool:
    """Whether the vendored grid loaded."""
    return _load() is not None


def _sampler(g):
    """is_ice(lat, lon) over a loaded grid."""
    w, h, cells, blocks = g
    bw = w // _BLOCK
    floor = math.floor

    def is_ice(lat, lon):
        fy = (90.0 - lat) * 10.0 - 0.5
        fx = (lon + 180.0) * 10.0 - 0.5
        y0 = min(h - 2, max(0, int(floor(fy))))
        x0 = int(floor(fx))
        if not blocks[(y0 // _BLOCK) * bw + (x0 % w) // _BLOCK]:
            return False
        ty = min(1.0, max(0.0, fy - y0))
        tx = fx - x0
        i, j = y0 * w, (y0 + 1) * w
        xa, xb = x0 % w, (x0 + 1) % w
        top = cells[i + xa] + (cells[i + xb] - cells[i + xa]) * tx
        bot = cells[j + xa] + (cells[j + xb] - cells[j + xa]) * tx
        return top + (bot - top) * ty >= _HALF

    return is_ice


def grid_for_bbox(bbox: tuple[float, float, float, float], w: int, h: int,
                  value: int) -> list[bytearray] | None:
    """Per-sub-pixel ice rows for a flat equirectangular view.

    `value` where the ground is ice and 0 elsewhere, row 0 the view's
    north edge as in the elevation grid.  None when the data file is
    missing or the view holds no ice.
    """
    g = _load()
    if g is None:
        return None
    is_ice = _sampler(g)
    minlon, minlat, maxlon, maxlat = bbox
    lons = [minlon + (maxlon - minlon) * (x + 0.5) / w for x in range(w)]
    rows = []
    any_ice = False
    for y in range(h):
        lat = maxlat - (maxlat - minlat) * (y + 0.5) / h
        row = bytearray(w)
        for x, lon in enumerate(lons):
            if is_ice(lat, lon):
                row[x] = value
                any_ice = True
        rows.append(row)
    return rows if any_ice else None


def grid_for_lls(lls: list[list[tuple[float, float] | None]] | None,
                 value: int) -> list[bytearray] | None:
    """Per-sub-pixel ice rows for the globe's lat/lon geometry.

    `lls` is the globe's grid of (lat, lon) or None-off-the-disk
    entries; off the disk stays 0.  None when the data file is missing
    or no sample is ice.
    """
    if lls is None:
        return None
    g = _load()
    if g is None:
        return None
    is_ice = _sampler(g)
    rows = []
    any_ice = False
    for ll_row in lls:
        row = bytearray(len(ll_row))
        for x, ll in enumerate(ll_row):
            if ll is not None and is_ice(ll[0], ll[1]):
                row[x] = value
                any_ice = True
        rows.append(row)
    return rows if any_ice else None
