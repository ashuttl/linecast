"""The vendored lake-depth grid terrain paints its lake beds from.

The elevation tiles report a lake as its surface: a sample over
Superior reads the hundred and eighty metres the water stands at,
which is the meadow beside it too, so the terrain register paints a
lake one flat tint from the water polygons and the bed is lost.  This
grid gives the bed back where it has been sounded.  NOAA NCEI's
surveyed grids of the Great Lakes, each referenced to its own lake's
low water datum, are reduced to a hundredth of a degree by
scripts/build_lake_depth_grid.py: a cell holds the mean depth of the
water in it, in two-metre steps, and a cell with no water holds 0.

A region is one lake or one group of them in one PNG, with its own
metres per grey level, since Erie is sixty-four metres deep and
Baikal sixteen hundred; the samplers walk the regions a point can
fall in.  Baikal's floor comes from ETOPO 2022, which carries the
GEBCO soundings of the largest lakes.  Another lake with a surveyed
grid is another entry in REGIONS and a recipe in the build script.
A sample is read bilinearly, so the cells never show and the bed
shelves to nothing at the shore the polygons draw.
"""

import math
from array import array

from linecast._paths import data_path
from linecast._log import log_failure

ATTRIBUTION = "Lake depths: NOAA NCEI"

PITCH = 0.01         # degrees per cell
# (file stem, (minlon, minlat, maxlon, maxlat), metres per grey level):
# the box each file covers, which the build script bakes to and the
# samplers read from, and the depth its 255 levels span
REGIONS = (("lake_depth_great_lakes", (-92.2, 41.0, -76.0, 49.5), 2.0),
           ("lake_depth_baikal", (103.6, 51.4, 110.0, 55.9), 7.0))

_loaded = None       # [(bbox, w, h, cells, step)] once loaded; [] if none read
_tried = False


def _load():
    """The regions' grids, or an empty list if none could be read."""
    global _loaded, _tried
    if _loaded is not None or _tried:
        return _loaded or []
    _tried = True
    out = []
    for stem, bbox, step in REGIONS:
        try:
            from linecast._png import decode_rgba
            w, h, rgba = decode_rgba(data_path(f"{stem}.png").read_bytes())
            # grayscale decodes to RGBA; the depth is the R channel
            out.append((bbox, w, h, bytes(rgba[::4]), step))
        except Exception as exc:
            log_failure("png", f"lake depth grid {stem} load", exc,
                        fallback="a flat lake tint")
    _loaded = out
    return out


def available() -> bool:
    """Whether any region's grid loaded."""
    return bool(_load())


def in_view(bbox: tuple[float, float, float, float]) -> bool:
    """Whether the view's bbox overlaps a region with depths."""
    minlon, minlat, maxlon, maxlat = bbox
    return any(minlon < r[2] and maxlon > r[0] and minlat < r[3]
               and maxlat > r[1] for r, *_rest in _load())


def _sampler(region):
    """depth_m(lat, lon) over one region: 0.0 outside it or on land."""
    (minlon, minlat, maxlon, maxlat), w, h, cells, step = region
    floor = math.floor
    scale = 1.0 / PITCH

    def depth(lat, lon):
        if not (minlon <= lon < maxlon and minlat < lat <= maxlat):
            return 0.0
        fx = (lon - minlon) * scale - 0.5
        fy = (maxlat - lat) * scale - 0.5
        x0 = min(w - 2, max(0, int(floor(fx))))
        y0 = min(h - 2, max(0, int(floor(fy))))
        tx = min(1.0, max(0.0, fx - x0))
        ty = min(1.0, max(0.0, fy - y0))
        i, j = y0 * w + x0, (y0 + 1) * w + x0
        top = cells[i] + (cells[i + 1] - cells[i]) * tx
        bot = cells[j] + (cells[j + 1] - cells[j]) * tx
        return (top + (bot - top) * ty) * step

    return depth


def grid_for_bbox(bbox: tuple[float, float, float, float], w: int, h: int
                  ) -> list[array] | None:
    """Per-sub-pixel depth rows, in metres, for a flat equirectangular
    view; row 0 is the view's north edge, as in the elevation grid.

    None when the data is missing, the view holds no region, or no
    sample in it is wet.
    """
    regions = [r for r in _load()
               if bbox[0] < r[0][2] and bbox[2] > r[0][0]
               and bbox[1] < r[0][3] and bbox[3] > r[0][1]]
    if not regions:
        return None
    minlon, minlat, maxlon, maxlat = bbox
    lons = [minlon + (maxlon - minlon) * (x + 0.5) / w for x in range(w)]
    rows = []
    any_wet = False
    for y in range(h):
        lat = maxlat - (maxlat - minlat) * (y + 0.5) / h
        row = array("f", bytes(4 * w))
        for region in regions:
            rb = region[0]
            if not (rb[1] < lat <= rb[3]):
                continue
            depth = _sampler(region)
            for x, lon in enumerate(lons):
                if rb[0] <= lon < rb[2]:
                    d = depth(lat, lon)
                    if d > 0.0:
                        row[x] = d
                        any_wet = True
        rows.append(row)
    return rows if any_wet else None


def grid_for_lls(lls: list[list[tuple[float, float] | None]] | None
                 ) -> list[array] | None:
    """Per-sub-pixel depth rows, in metres, for the globe's lat/lon
    geometry; off the disk stays 0.  None when the data is missing or
    no sample is wet.
    """
    if lls is None:
        return None
    regions = _load()
    if not regions:
        return None
    samplers = [(r[0], _sampler(r)) for r in regions]
    rows = []
    any_wet = False
    for ll_row in lls:
        row = array("f", bytes(4 * len(ll_row)))
        for x, ll in enumerate(ll_row):
            if ll is None:
                continue
            lat, lon = ll
            for (rminlon, rminlat, rmaxlon, rmaxlat), depth in samplers:
                if rminlon <= lon < rmaxlon and rminlat < lat <= rmaxlat:
                    d = depth(lat, lon)
                    if d > 0.0:
                        row[x] = d
                        any_wet = True
                    break
        rows.append(row)
    return rows if any_wet else None
