"""Elevation data from the AWS Open Data Terrain Tiles (Mapzen terrarium).

Free, keyless XYZ tiles encoding elevation in RGB:

    meters = (R * 256 + G + B / 256) - 32768

Land comes from SRTM/GMTED and friends; bathymetry from ETOPO1, which is
only composited in at the lower zooms — deep zooms over open ocean read as
0 m.  Tiles are immutable, so the disk cache never expires.

https://registry.opendata.aws/terrain-tiles/
"""

import os

from linecast._paths import cache_dir
from linecast._http import fetch_bytes_cached
from linecast._maps_tile_cache import note_tile_use
from linecast._png import DecodeMemo, decode_rgba
from linecast._radar_tiles import _lonlat_to_world, _pick_zoom, stitch_xyz
from linecast._runtime import log_failure

DEFAULT_URL = "https://s3.amazonaws.com/elevation-tiles-prod"
# SRTM's ~30 m native grid runs out around z13; beyond it the tiles are
# upsampled and add nothing.
MAX_ZOOM = 13
# ETOPO1 bathymetry drops out of the composite above this zoom; views
# tight enough to pick z11+ merge their sea back in from here.
BATHY_ZOOM = 10

ATTRIBUTION = "Terrain: Mapzen/AWS (SRTM, GMTED, ETOPO1)"

# decoded tiles, so a pan re-decodes only the column it uncovered: a
# view is at most a 4x3 stitch, and sixteen 256 KB decodes is 4 MB
_decoded = DecodeMemo(cap=16)


def tile_url(z, x, y):
    """URL for one tile, honouring LINECAST_ELEVATION_URL.

    The override is a bucket root by default; one carrying {z} is a full
    template, which is how a keyed host with its own path shape (Nextzen,
    say) can stand in — no public keyless mirror of these tiles exists
    to be a built-in second source (issue #34).
    """
    base = os.environ.get("LINECAST_ELEVATION_URL", DEFAULT_URL)
    if "{z}" in base:
        return (base.replace("{z}", str(z))
                .replace("{x}", str(x)).replace("{y}", str(y)))
    return f"{base.rstrip('/')}/terrarium/{z}/{x}/{y}.png"


def _fetch_tile(z, x, y, timeout=15):
    """One terrarium tile as PNG bytes, disk-cached forever (immutable)."""
    cpath = cache_dir("maps", f"terrarium_{z}_{x}_{y}.png")
    data = fetch_bytes_cached(cpath, None, tile_url(z, x, y), timeout=timeout)
    note_tile_use(cpath)  # so the sweep sees a tile still in use
    return data


def _decoded_tile(z, x, y, timeout):
    """One tile as (w, h, rgba), or None when unreadable."""
    data = _fetch_tile(z, x, y, timeout)
    if data is None:
        return None
    try:
        return _decoded.get((z, x, y), data, decode_rgba)
    except Exception as exc:
        log_failure("maps/elevation", f"tile {z}/{x}/{y} decode", exc,
                    fallback="tile left empty")
        return None


def decode_meters(r: int, g: int, b: int) -> float:
    return (r * 256 + g + b / 256.0) - 32768.0


def elevation_grid(bbox: tuple[float, float, float, float], w: int, h: int,
                   timeout: float = 15, camera=None) -> list[list[float | None]]:
    """Elevation in meters resampled to a w×h grid over `bbox`.

    Returns rows of floats; None where no tile data arrived.  Samples are
    decoded to meters at the tile pixels and interpolated bilinearly
    between them: elevation is a continuous field (the terrarium RGB
    channels are not — G wraps — which is why decoding comes first), and
    the nearest-neighbor duplication this replaced stepped the hillshade
    into visible axis-aligned combs wherever the view outresolved a tile.
    With a camera, its bounds choose the tiles and its inverse projection
    chooses each sample; bbox sampling remains available to existing callers.
    """
    # one step past the width-matched zoom: the caller's 2x supersample
    # then box-averages real detail down instead of interpolated guesses
    detail_bbox = bbox if camera is None else camera.scale_bbox
    z = min(MAX_ZOOM, _pick_zoom(detail_bbox, w, MAX_ZOOM) + 1)
    options = {} if camera is None else {"camera": camera}
    grid = _resample(bbox, w, h, z, timeout, **options)
    if z <= BATHY_ZOOM:
        return grid

    # Above z10 the composite carries no ETOPO1, and what it reports near
    # the sea is not trustworthy below the waterline: open water decodes
    # as metre-scale noise around 0 that flickers across the sea-level
    # test and chews the coast.  So above z10 the fine grid is treated as
    # authoritative *above* sea level only — wherever the z10 grid
    # confidently says sea (< -1 m) and the fine grid does not clearly
    # say dry land (>= 1 m), the z10 value wins.  Land keeps its ~30 m
    # SRTM; the sea keeps its bathymetry; below-sea-level land (a polder,
    # Death Valley) falls back to the z10 data it always rendered from.
    if not any(v is None or v < 1.0 for row in grid for v in row):
        return grid  # nothing near or below sea level: skip the fetch
    coarse = _resample(bbox, w, h, BATHY_ZOOM, timeout, **options)
    for row, crow in zip(grid, coarse):
        for x, (v, c) in enumerate(zip(row, crow)):
            if c is not None and (v is None or (c < -1.0 and v < 1.0)):
                row[x] = c
    return grid


def _resample(bbox, w, h, z, timeout, camera=None):
    """One zoom level's tiles, bilinearly sampled to a w×h meters grid."""

    def fetch(z_, x, y):
        return _decoded_tile(z_, x, y, timeout)

    coverage = bbox if camera is None else camera.bounds
    stitched = stitch_xyz(fetch, coverage, z)
    if camera is not None:
        return _resample_camera(stitched, camera.lls(w, h), coverage)
    canvas, cw, ch, org_x, org_y, world = stitched
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


def _canvas_xy(ll, center_lon, org_x, org_y, world):
    """A geographic point in a local stitch, unwrapped by the whole world.

    A dateline-crossing stitch can start east of 180° while the camera's
    inverse projection returns a negative longitude. Move the point into
    the coverage's longitude interval, never modulo the local canvas width:
    opposite edges of a regional stitch are different places.
    """
    lat, lon = ll
    lon += 360.0 * round((center_lon - lon) / 360.0)
    wx, wy = _lonlat_to_world(lon, lat)
    return wx * world - org_x, wy * world - org_y


def _resample_camera(stitched, lls, bbox):
    """Decode and bilinearly sample a local canvas through the map camera."""
    canvas, cw, ch, org_x, org_y, world = stitched
    center_lon = (bbox[0] + bbox[2]) * 0.5
    grid = []
    for ll_row in lls:
        row = []
        for ll in ll_row:
            if ll is None or cw <= 0 or ch <= 0:
                row.append(None)
                continue
            px, py = _canvas_xy(ll, center_lon, org_x, org_y, world)
            if not (0.0 <= px <= cw and 0.0 <= py <= ch):
                row.append(None)
                continue
            fx = min(max(px - 0.5, 0.0), cw - 1.0)
            fy = min(max(py - 0.5, 0.0), ch - 1.0)
            x0, y0 = int(fx), int(fy)
            x1, y1 = min(x0 + 1, cw - 1), min(y0 + 1, ch - 1)
            tx, ty = fx - x0, fy - y0
            taps = ((y0 * cw + x0) * 4, (y0 * cw + x1) * 4,
                    (y1 * cw + x0) * 4, (y1 * cw + x1) * 4)
            a, b, c, d = [decode_meters(canvas[i], canvas[i + 1], canvas[i + 2])
                          if canvas[i + 3] else None for i in taps]
            # Match the existing separable sampler's treatment of missing
            # neighbours: use the available sample without mixing in zero.
            top = b if a is None else (a if b is None else a + (b - a) * tx)
            bot = d if c is None else (c if d is None else c + (d - c) * tx)
            value = bot if top is None else (
                top if bot is None else top + (bot - top) * ty)
            row.append(value)
        grid.append(row)
    return grid
