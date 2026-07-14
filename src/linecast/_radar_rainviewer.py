"""Global radar frames from the RainViewer public API.

RainViewer aggregates 1200+ radars across 150+ countries into standard XYZ
(Web-Mercator) tiles.  Our basemap is equirectangular (EPSG:4326), so we fetch
the Web-Mercator tiles covering the view, stitch them into a canvas, and
resample per output pixel back to lat/lon — the basemap and radar stay aligned
and everything downstream (build_radar_buffer / compose) is unchanged.

Free/personal tier: no API key, Universal Blue colour scheme only, max zoom 7.
Attribution: "Weather data by RainViewer" (rainviewer.com).
"""

import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT
from linecast._png import decode_rgba
from linecast._runtime import debug_log

_INDEX_URL = "https://api.rainviewer.com/public/weather-maps.json"
_RV_CACHE = CACHE_ROOT / "radar" / "rv"
_TILE_SIZE = 256
_COLOR = 2          # Universal Blue — the only scheme on the free tier
_OPTIONS = "1_1"    # {smooth}_{snow}: smoothed, snow shown separately
_MAX_ZOOM = 7       # free-tier ceiling
_INDEX_TTL = 120    # seconds to trust a cached index before refetching


def fetch_index(timeout=15):
    """Return the parsed weather-maps.json (host + past/nowcast frame lists).

    Cached on disk for _INDEX_TTL seconds; falls back to stale cache on error.
    """
    _RV_CACHE.mkdir(parents=True, exist_ok=True)
    path = _RV_CACHE / "weather-maps.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < _INDEX_TTL:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    try:
        req = urllib.request.Request(_INDEX_URL, headers={"User-Agent": USER_AGENT})
        data = urllib.request.urlopen(req, timeout=timeout).read()
        path.write_bytes(data)
        return json.loads(data)
    except Exception as exc:
        debug_log(f"rainviewer index failed: {exc}")
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


def _pick_zoom(bbox, w):
    """Highest zoom (<= _MAX_ZOOM) whose tile pixels roughly match output width."""
    minlon, _minlat, maxlon, _maxlat = bbox
    span = (maxlon - minlon) / 360.0  # world-x fraction spanned by the view
    if span <= 0:
        return _MAX_ZOOM
    z = math.log2(max(1e-9, w / (_TILE_SIZE * span)))
    return max(0, min(_MAX_ZOOM, round(z)))


def _tile_url(host, path, z, x, y):
    return f"{host}{path}/{_TILE_SIZE}/{z}/{x}/{y}/{_COLOR}/{_OPTIONS}.png"


def _fetch_tile(host, path, z, x, y, timeout=15):
    """One tile as PNG bytes (disk-cached; tiles are immutable by frame path)."""
    frame_id = path.strip("/").replace("/", "_")
    cpath = _RV_CACHE / f"{frame_id}_{z}_{x}_{y}.png"
    if cpath.exists():
        return cpath.read_bytes()
    url = _tile_url(host, path, z, x, y)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as exc:
        debug_log(f"rainviewer tile {z}/{x}/{y} failed: {exc}")
        return None
    _RV_CACHE.mkdir(parents=True, exist_ok=True)
    cpath.write_bytes(data)
    return data


def reproject(host, path, bbox, w, h, timeout=15):
    """Fetch the tiles covering `bbox` and resample to a `w`×`h` EPSG:4326 RGBA.

    Returns (w, h, bytearray) — same shape decode_rgba yields, so it drops
    straight into build_radar_buffer.
    """
    minlon, minlat, maxlon, maxlat = bbox
    z = _pick_zoom(bbox, w)
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
        data = _fetch_tile(host, path, z, tx % n, ty, timeout)
        if data is None:
            return coord, None
        try:
            return coord, decode_rgba(data)
        except Exception:
            return coord, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        tiles = list(pool.map(load, coords))

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

    org_x, org_y = tx0 * _TILE_SIZE, ty0 * _TILE_SIZE

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
