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
from linecast._radar_tiles import _pick_zoom, reproject_xyz
from linecast._runtime import debug_log

DEFAULT_URL = "https://s3.amazonaws.com/elevation-tiles-prod"
# bathymetry (ETOPO1) drops out of the composite above this zoom; terrain
# detail beyond it is finer than any terminal can show anyway
MAX_ZOOM = 10

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

    Returns rows of floats; None where no tile data arrived.  Nearest-
    neighbor resampling preserves exact terrarium RGB values, so decoding
    after reprojection is lossless.
    """
    # one step past the width-matched zoom: hillshade differentiates the
    # grid, so duplicated nearest-neighbor columns read as visible steps
    z = min(MAX_ZOOM, _pick_zoom(bbox, w, MAX_ZOOM) + 1)

    def fetch(z_, x, y):
        data = _fetch_tile(z_, x, y, timeout)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception:
            return None

    _, _, rgba = reproject_xyz(fetch, bbox, w, h, z)
    grid = []
    for row in range(h):
        base = row * w * 4
        out = []
        for col in range(w):
            i = base + col * 4
            if rgba[i + 3] == 0:  # tile missing: canvas stayed transparent
                out.append(None)
            else:
                out.append(decode_meters(rgba[i], rgba[i + 1], rgba[i + 2]))
        grid.append(out)
    return grid
