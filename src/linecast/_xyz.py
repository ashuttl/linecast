"""Slippy-map arithmetic and plumbing that radar and maps share.

Both commands draw an equirectangular window (`bbox_for`) and fill it
from XYZ tiles in Web-Mercator: radar and satellite frames, terrain,
the built-up raster, the cloud mosaic, and the street register's vector
tiles.  This module holds what they have in common: the tile size, the
projection into the tile world (`lonlat_to_world`), the zoom whose
tiles match a view (`pick_zoom`), the stitch of a view's tiles into one
canvas (`stitch_xyz`) and its resample back to the window
(`reproject_xyz`), and the process's thread pools for fetching tiles
(`shared_pool`).  What a tile is and where it comes from is the
caller's: each hands the stitch a fetcher.
"""

import atexit
import math
import threading
from collections.abc import Callable
# imported before the exit hook below is registered, so the hook runs
# ahead of the pool threads' join (threading runs exit hooks newest first)
from concurrent.futures import ThreadPoolExecutor

from linecast.terminal.framebuffer import cell_aspect

TILE_SIZE = 256
_TILE_WORKERS = 12   # tile fetches in flight across the whole process


def bbox_for(lat, lon, zoom, graph_w, height_cells):
    """Geographic window so map sub-cells render ~square on screen.

    `zoom` is the degrees of latitude shown top-to-bottom.  The width
    follows from the screen's true shape: graph_w cells across against
    height_cells cells down, each as tall as the terminal's font makes
    it, so ground that is square stays square whatever the font.
    """
    spy_h = height_cells * 2
    half_lat = zoom / 2
    minlat, maxlat = lat - half_lat, lat + half_lat
    # A sub-pixel's height in cell widths (1.0 on a 2:1 cell).
    aspect = cell_aspect() / 2.0
    lon_span = zoom * (graph_w / (spy_h * aspect)) / math.cos(math.radians(lat))
    return (lon - lon_span / 2, minlat, lon + lon_span / 2, maxlat)


def lonlat_to_world(lon, lat):
    """Lon/lat → normalised Web-Mercator world coords, each in [0, 1]."""
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    s = min(max(s, -0.9999), 0.9999)
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def pick_zoom(bbox, w, max_zoom):
    """Highest zoom (<= max_zoom) whose tile pixels roughly match output width."""
    minlon, _minlat, maxlon, _maxlat = bbox
    span = (maxlon - minlon) / 360.0  # world-x fraction spanned by the view
    if span <= 0:
        return max_zoom
    z = math.log2(max(1e-9, w / (TILE_SIZE * span)))
    return max(0, min(max_zoom, round(z)))


# The process's tile pools by name; None marks one closed for good.
_pools: dict[str, ThreadPoolExecutor | None] = {}
_pool_lock = threading.Lock()
_exiting = False     # every pool is closed, including any not yet made


def shared_pool(name: str, workers: int) -> ThreadPoolExecutor | None:
    """The process's one pool called `name`, or None once it is closed.

    The first call makes it, with `workers` threads named after it.
    Several frames can be stitched at once (the radar prefetch runs a
    few in parallel); giving each its own pool meant two dozen
    connections racing for the same bandwidth, so the frame on screen
    arrived late.  A caller that wants its work kept apart from another
    kind — the map's view from its guesses — asks for a pool by a name
    of its own.
    """
    with _pool_lock:
        if name not in _pools:
            if _exiting:
                return None
            _pools[name] = ThreadPoolExecutor(max_workers=workers,
                                              thread_name_prefix=name)
        return _pools[name]


def close_pools(*names: str) -> None:
    """Drop the queued work of the named pools, or of every pool, and
    make no more of them.  With no names it runs at interpreter exit.

    Pool threads are not daemons, and the interpreter joins them on the
    way out; each would work through its queue before it saw the
    sentinel, so quitting mid-animation, or with a queue of guessed
    tiles, would be a wait at the door.  Cancelling the queues leaves
    only the fetches already in flight.  Registered with threading's
    exit hooks, which run before the join; atexit's run after it.
    """
    global _exiting
    with _pool_lock:
        if not names:
            _exiting = True
            names = tuple(_pools)
        closing = [_pools.get(name) for name in names]
        _pools.update(dict.fromkeys(names))
    for pool in closing:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


getattr(threading, "_register_atexit", atexit.register)(close_pools)


def stitch_xyz(fetch_tile: Callable[[int, int, int], tuple[int, int, bytearray] | None],
               bbox: tuple[float, float, float, float], z: int,
               ) -> tuple[bytearray, int, int, int, int, int]:
    """Stitch the XYZ tiles covering `bbox` at zoom `z` into one canvas.

    `fetch_tile(z, x, y)` returns a decoded `(tw, th, rgba)` tile or None
    (x arrives already wrapped to [0, 2^z)).  Returns (canvas RGBA,
    canvas_w, canvas_h, org_x, org_y, world): the canvas stays transparent
    where tiles are missing, `org_*` is its world-pixel origin and `world`
    the world size in pixels at this zoom.
    """
    minlon, minlat, maxlon, maxlat = bbox
    n = 1 << z
    world = TILE_SIZE * n

    # world-pixel corners of the view (NW = top-left, SE = bottom-right)
    x0f, y0f = lonlat_to_world(minlon, maxlat)
    x1f, y1f = lonlat_to_world(maxlon, minlat)
    tx0, tx1 = math.floor(x0f * n), math.floor(x1f * n)
    ty0, ty1 = math.floor(y0f * n), math.floor(y1f * n)
    ty0, ty1 = max(0, ty0), min(n - 1, ty1)

    ncx, ncy = tx1 - tx0 + 1, ty1 - ty0 + 1
    canvas_w, canvas_h = ncx * TILE_SIZE, ncy * TILE_SIZE
    canvas = bytearray(canvas_w * canvas_h * 4)  # zero-filled = transparent

    coords = [(tx, ty) for ty in range(ty0, ty1 + 1)
              for tx in range(tx0, tx1 + 1)]

    def load(coord):
        tx, ty = coord
        return coord, fetch_tile(z, tx % n, ty)

    pool = shared_pool("tiles", _TILE_WORKERS)
    if pool is None:
        # closed at exit: a fetch now would only hold the exit up, so
        # the stitch fails and its caller gives the frame up
        raise RuntimeError("the tile pool is closed")
    tiles = list(pool.map(load, coords))

    for (tx, ty), dec in tiles:
        if dec is None:
            continue
        tw, th, trgba = dec
        ox, oy = (tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE
        stride = min(tw, TILE_SIZE) * 4
        for row in range(min(th, TILE_SIZE)):
            src = (row * tw) * 4
            dst = ((oy + row) * canvas_w + ox) * 4
            canvas[dst:dst + stride] = trgba[src:src + stride]

    return canvas, canvas_w, canvas_h, tx0 * TILE_SIZE, ty0 * TILE_SIZE, world


def reproject_xyz(fetch_tile: Callable[[int, int, int], tuple[int, int, bytearray] | None],
                  bbox: tuple[float, float, float, float], w: int, h: int, z: int,
                  smooth: bool = False) -> tuple[int, int, bytearray]:
    """Stitch the XYZ tiles covering `bbox` at zoom `z`; resample to EPSG:4326.

    The Web-Mercator stitch + equirectangular resample is service-agnostic —
    radar and satellite tiles differ only in their fetcher.  Nearest-neighbor
    resampling, which is right for server-coloured radar echoes (palette-
    coded classes that must not blend); terrain does its own bilinear pass
    over the stitched canvas instead.  Raw grayscale reflectivity tiles
    *can* blend, and `smooth=True` resamples them bilinearly (see
    _smooth_gray) so echoes keep soft edges when a tile pixel spans several
    cells.  Returns (w, h, bytearray RGBA).
    """
    minlon, minlat, maxlon, maxlat = bbox
    canvas, canvas_w, canvas_h, org_x, org_y, world = \
        stitch_xyz(fetch_tile, bbox, z)
    if smooth:
        return _smooth_gray(canvas, canvas_w, canvas_h, org_x, org_y, world,
                            bbox, w, h)

    # x depends only on lon, y only on lat — precompute the column mapping
    col_cx = []
    for ox in range(w):
        lon = minlon + (ox + 0.5) / w * (maxlon - minlon)
        wx, _ = lonlat_to_world(lon, minlat)
        col_cx.append(int(wx * world) - org_x)

    out = bytearray(w * h * 4)
    for oy in range(h):
        lat = maxlat - (oy + 0.5) / h * (maxlat - minlat)
        _, wy = lonlat_to_world(minlon, lat)
        cy = int(wy * world) - org_y
        if cy < 0 or cy >= canvas_h:
            continue
        base = cy * canvas_w
        di_row = oy * w * 4
        for ox in range(w):
            cx = col_cx[ox]
            if cx < 0 or cx >= canvas_w:
                continue
            si = (base + cx) * 4
            di = di_row + ox * 4
            out[di:di + 4] = canvas[si:si + 4]
    return w, h, out


def _smooth_gray(canvas, canvas_w, canvas_h, org_x, org_y, world, bbox, w, h):
    """Bilinear resample of a scheme-0 (gray = dBZ + 32, +128 snow) canvas.

    Reflectivity and coverage interpolate separately: alpha fades across an
    echo's edge, and the gray is the alpha-weighted mean of the covered
    neighbours so the edge keeps its own intensity instead of darkening
    toward the transparent side.  The snow bit is carried as a fraction and
    re-flagged by majority.  Output is the same encoding, so the palette
    step doesn't know the difference.

    Most of a frame is clear sky, so each output pixel first probes its four
    neighbours' alphas from one contiguous plane and skips the weighted sum
    where all four are zero.
    """
    minlon, minlat, maxlon, maxlat = bbox

    # per output column: the two canvas columns it straddles (edge-clamped)
    # and its fractional position between them
    col = []
    for ox in range(w):
        lon = minlon + (ox + 0.5) / w * (maxlon - minlon)
        wx, _ = lonlat_to_world(lon, minlat)
        fx = wx * world - org_x - 0.5
        x0 = int(fx // 1)
        col.append((min(max(x0, 0), canvas_w - 1),
                    min(max(x0 + 1, 0), canvas_w - 1), fx - x0))

    alpha = canvas[3::4]
    out = bytearray(w * h * 4)
    for oy in range(h):
        lat = maxlat - (oy + 0.5) / h * (maxlat - minlat)
        _, wy = lonlat_to_world(minlon, lat)
        fy = wy * world - org_y - 0.5
        y0 = int(fy // 1)
        ty = fy - y0
        r0 = min(max(y0, 0), canvas_h - 1) * canvas_w
        r1 = min(max(y0 + 1, 0), canvas_h - 1) * canvas_w
        di_row = oy * w * 4
        for ox in range(w):
            xa, xb, tx = col[ox]
            a00 = alpha[r0 + xa]
            a10 = alpha[r0 + xb]
            a01 = alpha[r1 + xa]
            a11 = alpha[r1 + xb]
            if not (a00 or a10 or a01 or a11):
                continue
            a_sum = g_sum = s_sum = 0.0
            for idx, a, wgt in ((r0 + xa, a00, (1 - ty) * (1 - tx)),
                                (r0 + xb, a10, (1 - ty) * tx),
                                (r1 + xa, a01, ty * (1 - tx)),
                                (r1 + xb, a11, ty * tx)):
                if not a or not wgt:
                    continue
                wgt *= a
                a_sum += wgt
                gray = canvas[idx * 4]
                if gray >= 128:
                    s_sum += wgt
                    gray -= 128
                g_sum += wgt * gray
            if a_sum <= 0:
                continue
            gray = int(g_sum / a_sum + 0.5)
            if s_sum * 2 >= a_sum:
                gray += 128
            di = di_row + ox * 4
            out[di] = out[di + 1] = out[di + 2] = gray
            out[di + 3] = int(a_sum + 0.5)
    return w, h, out
