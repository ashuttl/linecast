"""Elevation data from the AWS Open Data Terrain Tiles (Mapzen terrarium).

Free, keyless XYZ tiles encoding elevation in RGB:

    meters = (R * 256 + G + B / 256) - 32768

Land comes from SRTM/GMTED and friends; bathymetry from ETOPO1, which is
only composited in at the lower zooms — deep zooms over open ocean read as
0 m.  Tiles are immutable, so the disk cache never expires.

https://registry.opendata.aws/terrain-tiles/
"""

import os

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT
from linecast._png import decode_rgba
from linecast._radar_tiles import _lonlat_to_world, _pick_zoom, stitch_xyz
from linecast._runtime import debug_log

DEFAULT_URL = "https://s3.amazonaws.com/elevation-tiles-prod"
# SRTM's ~30 m native grid runs out around z13; beyond it the tiles are
# upsampled and add nothing.  ETOPO1 bathymetry drops out of the composite
# above z10, so open sea reads 0 m in views tight enough to pick z11+ —
# it renders as the shallowest bathy stop, which at a few miles across is
# truer than ETOPO1's 1-arc-minute mush ever was there.
MAX_ZOOM = 13

ATTRIBUTION = "Terrain: Mapzen/AWS (SRTM, GMTED, ETOPO1)"


def _tile_url(z, x, y):
    base = os.environ.get("LINECAST_ELEVATION_URL", DEFAULT_URL).rstrip("/")
    return f"{base}/terrarium/{z}/{x}/{y}.png"


def _fetch_tile(z, x, y, timeout=15):
    """One terrarium tile as PNG bytes, disk-cached forever (immutable)."""
    import urllib.request
    cdir = CACHE_ROOT / "maps"
    cpath = cdir / f"terrarium_{z}_{x}_{y}.png"
    if cpath.exists():
        return cpath.read_bytes()
    try:
        req = urllib.request.Request(_tile_url(z, x, y),
                                     headers={"User-Agent": USER_AGENT})
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as exc:
        debug_log(f"terrarium tile {z}/{x}/{y} failed: {exc}")
        return None
    cdir.mkdir(parents=True, exist_ok=True)
    cpath.write_bytes(data)
    return data


def decode_meters(r, g, b):
    return (r * 256 + g + b / 256.0) - 32768.0


def elevation_grid(bbox, w, h, timeout=15):
    """Elevation in meters resampled to a w×h grid over `bbox`.

    Returns rows of floats; None where no tile data arrived.  Samples are
    decoded to meters at the tile pixels and interpolated bilinearly
    between them: elevation is a continuous field (the terrarium RGB
    channels are not — G wraps — which is why decoding comes first), and
    the nearest-neighbor duplication this replaced stepped the hillshade
    into visible axis-aligned combs wherever the view outresolved a tile.
    """
    # one step past the width-matched zoom: the caller's 2x supersample
    # then box-averages real detail down instead of interpolated guesses
    z = min(MAX_ZOOM, _pick_zoom(bbox, w, MAX_ZOOM) + 1)

    def fetch(z_, x, y):
        data = _fetch_tile(z_, x, y, timeout)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception:
            return None

    canvas, cw, ch, org_x, org_y, world = stitch_xyz(fetch, bbox, z)
    minlon, minlat, maxlon, maxlat = bbox

    # x depends only on lon, y only on lat, so the resample is separable:
    # precompute each output column's canvas span, interpolate the canvas
    # rows the output needs horizontally, then blend pairs vertically.
    cols = []
    for ox in range(w):
        lon = minlon + (ox + 0.5) / w * (maxlon - minlon)
        wx, _ = _lonlat_to_world(lon, minlat)
        fx = min(max(wx * world - org_x - 0.5, 0.0), cw - 1.0)
        x0 = int(fx)
        cols.append((x0 * 4, min(x0 + 1, cw - 1) * 4, fx - x0))

    rows, need = [], set()
    for oy in range(h):
        lat = maxlat - (oy + 0.5) / h * (maxlat - minlat)
        _, wy = _lonlat_to_world(minlon, lat)
        fy = min(max(wy * world - org_y - 0.5, 0.0), ch - 1.0)
        y0 = int(fy)
        y1 = min(y0 + 1, ch - 1)
        rows.append((y0, y1, fy - y0))
        need.add(y0)
        need.add(y1)

    hrows = {}
    for cy in need:
        base = cy * cw * 4
        out = []
        for i0, i1, t in cols:
            a = b = None
            if canvas[base + i0 + 3]:  # alpha 0 = tile missing
                j = base + i0
                a = decode_meters(canvas[j], canvas[j + 1], canvas[j + 2])
            if canvas[base + i1 + 3]:
                j = base + i1
                b = decode_meters(canvas[j], canvas[j + 1], canvas[j + 2])
            if a is None:
                out.append(b)
            elif b is None:
                out.append(a)
            else:
                out.append(a + (b - a) * t)
        hrows[cy] = out

    grid = []
    for y0, y1, t in rows:
        r0, r1 = hrows[y0], hrows[y1]
        row = []
        for x in range(w):
            a, b = r0[x], r1[x]
            if a is None:
                row.append(b)
            elif b is None:
                row.append(a)
            else:
                row.append(a + (b - a) * t)
        grid.append(row)
    return grid
