"""Radar tiles from providers speaking the RainViewer v2 protocol.

LibreWXR and RainViewer both publish a weather-maps.json index (host +
past/nowcast frame lists) and serve standard XYZ (Web-Mercator) tiles at
{host}{path}/{size}/{z}/{x}/{y}/{color}/{options}.png.  Our basemap is
equirectangular (EPSG:4326), so we fetch the Web-Mercator tiles covering the
view, stitch them into a canvas, and resample per output pixel back to
lat/lon — the basemap and radar stay aligned and everything downstream
(build_radar_buffer / compose) is unchanged.

Providers differ only in the constants captured by a Provider instance:
index URL, colour scheme, zoom ceiling, and cache directory.
"""

import atexit
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from linecast._cache import CACHE_ROOT, write_bytes_atomic
from linecast._http import fetch_bytes, fetch_bytes_cached
from linecast._png import decode_rgba
from linecast._runtime import debug_log

_TILE_SIZE = 256
_TILE_WORKERS = 12   # tile fetches in flight across the whole process
_INDEX_TTL = 120     # seconds to trust a cached index before refetching
_NOWCAST_TTL = 600   # forecast tiles are re-predicted; treat older as stale

LIBREWXR_DEFAULT_URL = "https://api.librewxr.net"
# The grayscale scheme: gray = dBZ + 32 (+128 for snow).  Fetched unsmoothed
# it is reflectivity data we can colour ourselves (see _radar_palettes).
RAW_COLOR = 0


class Provider:
    """One RainViewer-v2-protocol tile service."""
    __slots__ = ("name", "index_url", "color", "options", "max_zoom")

    def __init__(self, name, index_url, color, options, max_zoom):
        self.name = name            # cache subdir under radar/
        self.index_url = index_url
        self.color = color          # colour scheme id baked into tile pixels
        self.options = options      # {smooth}_{snow}
        self.max_zoom = max_zoom


def rainviewer_provider():
    # Free/personal tier: Universal Blue only, max zoom 7.
    return Provider("rv", "https://api.rainviewer.com/public/weather-maps.json",
                    color=2, options="1_1", max_zoom=7)


def librewxr_provider(color, smooth=True):
    # Base URL overridable so a self-hosted instance can be pointed at; the
    # tile host still comes from the index response's "host" field.
    base = os.environ.get("LINECAST_LIBREWXR_URL", LIBREWXR_DEFAULT_URL)
    return Provider("lwxr", base.rstrip("/") + "/public/weather-maps.json",
                    color=color, options=f"{int(smooth)}_1", max_zoom=12)


def satellite_provider(provider):
    # Satellite tiles ride the same index and URL shape as radar but are
    # only rendered in one scheme (grayscale VIS-over-LW, alpha = cloud
    # opacity), and the source mosaic is ~8 km so deep zooms add nothing.
    return Provider(provider.name + "-sat", provider.index_url,
                    color=0, options="0_0", max_zoom=6)


def _cache_dir(provider):
    return CACHE_ROOT / "radar" / provider.name


# Frame tiles are keyed by their timestamped frame path and never requested
# again once the animation window moves past them, so without a sweep the
# cache only grows (a long-running radar adds megabytes per day).
_PRUNE_MAX_AGE = 86400


def prune_tile_cache(max_age=_PRUNE_MAX_AGE):
    """Delete cached radar/satellite tiles older than *max_age* seconds.

    Runs at radar startup. Only sweeps the timestamp-keyed radar tree;
    immutable caches (terrain, vector tiles) are someone else's and eternal.
    """
    root = CACHE_ROOT / "radar"
    if not root.is_dir():
        return
    cutoff = time.time() - max_age
    for provider_dir in root.iterdir():
        if not provider_dir.is_dir():
            continue
        for tile in provider_dir.glob("*.png"):
            try:
                if tile.stat().st_mtime < cutoff:
                    tile.unlink()
            except OSError:
                pass  # a concurrent radar may have pruned it first


def fetch_index(provider, timeout=15):
    """Return the parsed weather-maps.json (host + past/nowcast frame lists).

    Cached on disk for _INDEX_TTL seconds; falls back to stale cache on error.
    """
    cdir = _cache_dir(provider)
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / "weather-maps.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < _INDEX_TTL:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    try:
        data = fetch_bytes(provider.index_url, timeout=timeout)
        write_bytes_atomic(path, data)
        return json.loads(data)
    except Exception as exc:
        debug_log(f"{provider.name} index failed: {exc}")
        if path.exists():
            return json.loads(path.read_text())
        raise


def _lonlat_to_world(lon, lat):
    """Lon/lat → normalised Web-Mercator world coords, each in [0, 1]."""
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    s = min(max(s, -0.9999), 0.9999)
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def _pick_zoom(bbox, w, max_zoom):
    """Highest zoom (<= max_zoom) whose tile pixels roughly match output width."""
    minlon, _minlat, maxlon, _maxlat = bbox
    span = (maxlon - minlon) / 360.0  # world-x fraction spanned by the view
    if span <= 0:
        return max_zoom
    z = math.log2(max(1e-9, w / (_TILE_SIZE * span)))
    return max(0, min(max_zoom, round(z)))


def _tile_url(provider, host, path, z, x, y):
    return (f"{host}{path}/{_TILE_SIZE}/{z}/{x}/{y}/"
            f"{provider.color}/{provider.options}.png")


def _fetch_tile(provider, host, path, z, x, y, timeout=15, mutable=False):
    """One tile as PNG bytes, disk-cached per colour scheme.

    Past-frame tiles are immutable by frame path; nowcast tiles (mutable=True)
    are re-predicted between index refreshes, so a cached copy older than
    _NOWCAST_TTL is refetched (stale bytes still serve as a network fallback).
    """
    frame_id = path.strip("/").replace("/", "_")
    cpath = (_cache_dir(provider) / f"{frame_id}_{z}_{x}_{y}_c{provider.color}"
             f"_{provider.options}.png")
    url = _tile_url(provider, host, path, z, x, y)
    return fetch_bytes_cached(cpath, _NOWCAST_TTL if mutable else None, url,
                              timeout=timeout)


def reproject(provider, host, path, bbox, w, h, timeout=15, mutable=False,
              smooth=False):
    """Fetch the tiles covering `bbox` and resample to a `w`×`h` EPSG:4326 RGBA.

    Returns (w, h, bytearray) — same shape decode_rgba yields, so it drops
    straight into build_radar_buffer.  `smooth` asks for the bilinear pass
    meant for raw grayscale (reflectivity) tiles.
    """
    z = _pick_zoom(bbox, w, provider.max_zoom)

    def fetch(z_, x, y):
        data = _fetch_tile(provider, host, path, z_, x, y, timeout,
                           mutable=mutable)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception:
            return None

    return reproject_xyz(fetch, bbox, w, h, z, smooth=smooth)


_tile_pool = None
_tile_pool_lock = threading.Lock()


def _shared_pool():
    """One pool for every tile fetch in the process.

    Several frames can be stitched at once (the radar prefetch runs a few
    in parallel); giving each its own pool meant two dozen connections
    racing for the same bandwidth, so the frame on screen arrived late.
    """
    global _tile_pool
    with _tile_pool_lock:
        if _tile_pool is None:
            _tile_pool = ThreadPoolExecutor(max_workers=_TILE_WORKERS,
                                            thread_name_prefix="tiles")
        return _tile_pool


def _cancel_pool():
    """Drop every tile fetch not yet started.  Runs at interpreter exit.

    The pool's threads are joined on the way out, and each would work
    through the queue before it saw the sentinel: quitting mid-animation
    could mean waiting on a few frames' worth of tiles.  Cancelling the
    queue leaves only the fetches already in flight.  A fetch that lands
    on the cancelled pool afterwards fails, which its caller treats like
    any other missed tile.  Registered with threading's exit hooks, which
    run before the join; atexit's run after it.
    """
    with _tile_pool_lock:
        if _tile_pool is not None:
            _tile_pool.shutdown(wait=False, cancel_futures=True)


getattr(threading, "_register_atexit", atexit.register)(_cancel_pool)


def stitch_xyz(fetch_tile, bbox, z):
    """Stitch the XYZ tiles covering `bbox` at zoom `z` into one canvas.

    `fetch_tile(z, x, y)` returns a decoded `(tw, th, rgba)` tile or None
    (x arrives already wrapped to [0, 2^z)).  Returns (canvas RGBA,
    canvas_w, canvas_h, org_x, org_y, world): the canvas stays transparent
    where tiles are missing, `org_*` is its world-pixel origin and `world`
    the world size in pixels at this zoom.
    """
    minlon, minlat, maxlon, maxlat = bbox
    n = 1 << z
    world = _TILE_SIZE * n

    # world-pixel corners of the view (NW = top-left, SE = bottom-right)
    x0f, y0f = _lonlat_to_world(minlon, maxlat)
    x1f, y1f = _lonlat_to_world(maxlon, minlat)
    tx0, tx1 = math.floor(x0f * n), math.floor(x1f * n)
    ty0, ty1 = math.floor(y0f * n), math.floor(y1f * n)
    ty0, ty1 = max(0, ty0), min(n - 1, ty1)

    ncx, ncy = tx1 - tx0 + 1, ty1 - ty0 + 1
    canvas_w, canvas_h = ncx * _TILE_SIZE, ncy * _TILE_SIZE
    canvas = bytearray(canvas_w * canvas_h * 4)  # zero-filled = transparent

    coords = [(tx, ty) for ty in range(ty0, ty1 + 1)
              for tx in range(tx0, tx1 + 1)]

    def load(coord):
        tx, ty = coord
        return coord, fetch_tile(z, tx % n, ty)

    tiles = list(_shared_pool().map(load, coords))

    for (tx, ty), dec in tiles:
        if dec is None:
            continue
        tw, th, trgba = dec
        ox, oy = (tx - tx0) * _TILE_SIZE, (ty - ty0) * _TILE_SIZE
        stride = min(tw, _TILE_SIZE) * 4
        for row in range(min(th, _TILE_SIZE)):
            src = (row * tw) * 4
            dst = ((oy + row) * canvas_w + ox) * 4
            canvas[dst:dst + stride] = trgba[src:src + stride]

    return canvas, canvas_w, canvas_h, tx0 * _TILE_SIZE, ty0 * _TILE_SIZE, world


def reproject_xyz(fetch_tile, bbox, w, h, z, smooth=False):
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
        wx, _ = _lonlat_to_world(lon, minlat)
        col_cx.append(int(wx * world) - org_x)

    out = bytearray(w * h * 4)
    for oy in range(h):
        lat = maxlat - (oy + 0.5) / h * (maxlat - minlat)
        _, wy = _lonlat_to_world(minlon, lat)
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
        wx, _ = _lonlat_to_world(lon, minlat)
        fx = wx * world - org_x - 0.5
        x0 = int(fx // 1)
        col.append((min(max(x0, 0), canvas_w - 1),
                    min(max(x0 + 1, 0), canvas_w - 1), fx - x0))

    alpha = canvas[3::4]
    out = bytearray(w * h * 4)
    for oy in range(h):
        lat = maxlat - (oy + 0.5) / h * (maxlat - minlat)
        _, wy = _lonlat_to_world(minlon, lat)
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
