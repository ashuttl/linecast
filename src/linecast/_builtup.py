"""Built-up surface tiles for terrain's urban tint (GHSL-derived).

An optional raster companion to the street-density proxy: grayscale XYZ
tiles where pixel value 0-255 is the fraction of the cell that is
built, generated from the JRC Global Human Settlement Layer by
scripts/build_builtup_tiles.py.  Measured settlement instead of
inferred — it knows the town whose streets nobody has mapped, and it
is immune to the zoom-dependent street thinning that makes the proxy
wobble.

Enabled by LINECAST_BUILTUP_URL (an XYZ base; file:// works for a
local tile directory).  A missing tile means "nothing built here" by
construction, so misses are cached as empty files and read as zero —
the sparse tileset is the compression.
"""

import os

from linecast._cache import CACHE_ROOT, write_bytes_atomic
from linecast._http import fetch_bytes
from linecast._png import DecodeMemo, decode_rgba
from linecast._radar_tiles import _pick_zoom, reproject_xyz
from linecast._runtime import debug_log

MAX_ZOOM = 9  # the published pyramid's floor: ~300 m per pixel, plenty for a tint

# CC-BY credit for the built-up layer, kept terse so the footer's
# widest rung still fits an 80-column terminal
ATTRIBUTION = "GHSL © EC JRC"

# The published tileset (the linecast-tiles R2 bucket); the
# environment variable always wins — point it elsewhere or set it
# empty to turn the layer off.
DEFAULT_URL = "https://pub-18689fea99e6428ebbc5e51b36dc6d91.r2.dev"

# decoded tiles, as _elevation keeps them: a pan decodes only what is new
_decoded = DecodeMemo(cap=16)


def enabled():
    return bool(os.environ.get("LINECAST_BUILTUP_URL", DEFAULT_URL))


def _tile_url(z, x, y):
    base = os.environ.get("LINECAST_BUILTUP_URL", DEFAULT_URL).rstrip("/")
    return f"{base}/{z}/{x}/{y}.png"


def _fetch_tile(z, x, y, timeout=15):
    """Tile PNG bytes, disk-cached; a cached miss reads as None.

    Real tiles cache forever (the pyramid is content-stable), but empty
    misses expire after a month: a 404 usually means "nothing built
    here", yet it is also what a still-uploading or updated tileset
    says, and that kind of wrong answer shouldn't be permanent.
    """
    import time
    cdir = CACHE_ROOT / "maps"
    cpath = cdir / f"builtup_{z}_{x}_{y}.png"
    if cpath.exists():
        data = cpath.read_bytes()
        if data:
            return data
        if time.time() - cpath.stat().st_mtime < 30 * 86400:
            return None  # zero bytes = cached "nothing built here"
    try:
        data = fetch_bytes(_tile_url(z, x, y), timeout=timeout)
    except Exception as exc:
        miss = getattr(exc, "code", None) == 404 or isinstance(
            exc, FileNotFoundError) or "No such file" in str(exc)
        if not miss:
            debug_log(f"builtup tile {z}/{x}/{y} failed: {exc}")
            return None
        data = b""  # absence means zero; remember it
    cdir.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(cpath, data)
    return data or None


def builtup_grid(bbox, w, h, timeout=15):
    """Built fraction 0-255 resampled to a w×h grid over `bbox`.

    Rows of ints; 0 where nothing is built or no tile answered.
    Nearest-neighbour is right here: the value is a fraction for a
    tint threshold, not a field to differentiate.
    """
    z = _pick_zoom(bbox, w, MAX_ZOOM)

    def fetch(z_, x, y):
        data = _fetch_tile(z_, x, y, timeout)
        if data is None:
            return None
        try:
            return _decoded.get((z_, x, y), data, decode_rgba)
        except Exception:
            return None

    _, _, rgba = reproject_xyz(fetch, bbox, w, h, z)
    grid = [[rgba[(row * w + col) * 4] if rgba[(row * w + col) * 4 + 3]
             else 0 for col in range(w)] for row in range(h)]
    # a light 3x3 mean before anyone thresholds it: the raw cells grade-
    # dither at settlement edges, and the smoothed field breaks into the
    # chunkier bounded regions a schematic map wants
    out = []
    for y in range(h):
        y0, y1 = max(0, y - 1), min(h - 1, y + 1) + 1
        row = []
        for x in range(w):
            x0, x1 = max(0, x - 1), min(w - 1, x + 1) + 1
            n = s = 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    s += grid[yy][xx]
                    n += 1
            row.append(s // n)
        out.append(row)
    return out
