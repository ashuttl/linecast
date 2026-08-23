"""The vendored climate-family grid terrain colour climbs by.

One global raster, 0.1° and 67 KB, baked from the Beck et al. (2023)
Köppen-Geiger classification by scripts/build_climate_grid.py: each
cell holds the hypsometric ramp family of the ground there — 0 humid,
1 semiarid, 2 arid, 3 polar.  Shipping it in the wheel instead of
tiling it is the point: climate is smooth, static and tiny, so the
first frame of the globe is already right, offline included.

Ocean cells were flood-filled from the nearest land at bake time, so
sampling never misses — a shoreline sub-pixel straddling the surf gets
its coast's family, not a default.
"""

from pathlib import Path

HUMID, SEMIARID, ARID, POLAR = range(4)

# CC-BY credit for the source classification, kept terse so the
# footer's widest rung still fits an 80-column terminal
ATTRIBUTION = "Köppen © Beck et al."

_grid = None      # (w, h, bytes) once loaded; a failed load stays None
_tried = False


def _load():
    """The (w, h, rows) grid, or None if the data file is unreadable."""
    global _grid, _tried
    if _grid is not None or _tried:
        return _grid
    _tried = True
    try:
        from linecast._png import decode_rgba
        data = (Path(__file__).parent / "data" / "climate.png").read_bytes()
        w, h, rgba = decode_rgba(data)
        # grayscale decodes to RGBA; the family index is the R channel
        _grid = (w, h, bytes(rgba[::4]))
    except Exception:
        _grid = None
    return _grid


def available():
    """Whether the vendored grid loaded (drives the footer credit)."""
    return _load() is not None


def family(lat, lon):
    """The ramp family of the ground at lat/lon (HUMID when unknown)."""
    g = _load()
    if g is None:
        return HUMID
    w, h, cells = g
    ix = int((lon + 180.0) / 360.0 * w) % w
    iy = min(h - 1, max(0, int((90.0 - lat) / 180.0 * h)))
    return cells[iy * w + ix]


def grid_for_bbox(bbox, w, h):
    """Per-sub-pixel family rows for a flat equirectangular view.

    Row 0 is the view's north edge, matching the elevation grid.
    Returns None when the data file is missing, and every consumer
    treats that as "all humid" — the single-ramp world this replaces.
    """
    g = _load()
    if g is None:
        return None
    gw, gh, cells = g
    minlon, minlat, maxlon, maxlat = bbox
    rows = []
    for y in range(h):
        lat = maxlat - (maxlat - minlat) * (y + 0.5) / h
        iy = min(gh - 1, max(0, int((90.0 - lat) / 180.0 * gh)))
        base = iy * gw
        row = bytearray(w)
        for x in range(w):
            lon = minlon + (maxlon - minlon) * (x + 0.5) / w
            row[x] = cells[base + int((lon + 180.0) / 360.0 * gw) % gw]
        rows.append(row)
    return rows


def grid_for_lls(lls):
    """Per-sub-pixel family rows for the globe's lat/lon geometry.

    `lls` is the globe's grid of (lat, lon) or None-off-the-disk
    entries; unknown stays 0, which the shader never reads (there is
    no elevation off the disk either).
    """
    if lls is None:
        return None
    g = _load()
    if g is None:
        return None
    gw, gh, cells = g
    rows = []
    for ll_row in lls:
        row = bytearray(len(ll_row))
        for x, ll in enumerate(ll_row):
            if ll is None:
                continue
            lat, lon = ll
            iy = min(gh - 1, max(0, int((90.0 - lat) / 180.0 * gh)))
            row[x] = cells[iy * gw + int((lon + 180.0) / 360.0 * gw) % gw]
        rows.append(row)
    return rows
