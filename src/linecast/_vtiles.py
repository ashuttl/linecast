"""Vector street tiles — transport and disk cache for maps.

Fetches OpenMapTiles-schema MVT tiles from OpenFreeMap, the keyless
public instance (openfreemap.org: "no limits on the number of map views
or requests"; donation-funded, so this module caches aggressively and
sends Accept-Encoding: gzip to spare their bandwidth).

The tile URL template is discovered through the TileJSON document
rather than hardcoded: the planet is rebuilt weekly under a new dated
path segment, and requests to a stale or mistyped path return HTTP 200
with zero bytes — indistinguishable from genuinely empty ocean tiles.
A zero-byte body IS the documented "empty tile" response, so it is
cached and rendered as nothing; the TileJSON itself is re-read after a
day, which is how a stale template heals.

Versioned tile URLs are immutable (10-year max-age upstream), so cached
tiles never expire.

When OpenFreeMap doesn't answer and no usable cache is on disk, the
OpenStreetMap US Tileservice stands in: the same OpenMapTiles schema,
also keyless, rebuilt daily. Anonymous use there is rate-limited and
their policy asks for a "Tiles by OSM US" credit, so it is asked only
as the second source and the attribution line names it while it serves.

Set LINECAST_VECTOR_TILES_URL to point at a self-hosted TileJSON; an
override is the user's chosen source and gets no fallback.
"""

import math
import os
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from linecast._cache import (read_cache, read_stale, write_bytes_atomic,
                             write_cache)
from linecast._http import MAX_BODY_BYTES, fetch_bytes, fetch_json, gunzip_limited
from linecast._maps_tile_cache import note_tile_use
from linecast._paths import cache_dir
from linecast._radar_tiles import _lonlat_to_world
from linecast._runtime import debug_log, log_failure

DEFAULT_TILEJSON_URL = "https://tiles.openfreemap.org/planet"
FALLBACK_TILEJSON_URL = "https://tiles.openstreetmap.us/vector/openmaptiles.json"

ATTRIBUTION = "© OpenMapTiles © OpenStreetMap"

# What the attribution line names for each source; None for an override,
# whose operator is the user.
_CREDITS = {DEFAULT_TILEJSON_URL: "OpenFreeMap",
            FALLBACK_TILEJSON_URL: "Tiles by OSM US"}

_TILEJSON_TTL = 86400  # the planet rebuilds weekly; a day of staleness is fine
_MAX_ZOOM_FALLBACK = 14

_active_url: str | None = None  # the source whose TileJSON last answered


def tilejson_url() -> str:
    return os.environ.get("LINECAST_VECTOR_TILES_URL", DEFAULT_TILEJSON_URL)


def _sources() -> list[tuple[str, str]]:
    """(url, cache file name) in asking order. An override is the user's
    chosen source, so it stands alone; the default gets the fallback."""
    override = os.environ.get("LINECAST_VECTOR_TILES_URL")
    if override:
        return [(override, "tilejson.json")]
    return [(DEFAULT_TILEJSON_URL, "tilejson.json"),
            (FALLBACK_TILEJSON_URL, "tilejson_fallback.json")]


def source_credit() -> str | None:
    """Who the attribution line names for the tiles now being served."""
    return _CREDITS.get(_active_url or tilejson_url())


def attribution_long() -> str:
    """The street register's full credit, naming whichever source is
    serving — OpenFreeMap, or OSM US when the fallback stepped in; a
    self-hosted override names nobody."""
    credit = source_credit()
    base = "© OpenMapTiles © OpenStreetMap contributors"
    return f"{credit} {base}" if credit else base


def _served(data, url):
    global _active_url
    _active_url = url
    return data


def tilejson() -> dict[str, Any] | None:
    """The TileJSON dict, or None when no source is reachable or cached.

    Each source in turn: fresh cache, then the network. Only when every
    source has failed do the stale caches answer, again in source order —
    yesterday's OpenFreeMap template usually still serves, and beats
    switching sources over a blip."""
    sources = _sources()
    for i, (url, name) in enumerate(sources):
        cache_file = cache_dir("maps", name)
        data = read_cache(cache_file, _TILEJSON_TTL)
        if data is not None:
            debug_log(f"cache hit: {name}")
            return _served(data, url)
        try:
            data = fetch_json(url, timeout=10)
        except Exception as exc:
            log_failure("maps/vtiles", "tilejson fetch", exc, url=url,
                        fallback=(sources[i + 1][0] if i + 1 < len(sources)
                                  else "stale cache"))
            continue
        write_cache(cache_file, data)
        return _served(data, url)
    for url, name in sources:
        stale = read_stale(cache_dir("maps", name))
        if stale is not None:
            return _served(stale, url)
    return None


def tile_info() -> tuple[str, str, int] | None:
    """(url_template, version_segment, maxzoom) or None.

    The version segment (e.g. "20260802_080001_pt") namespaces the disk
    cache; when the template carries no recognizable segment the host
    (plus the TileJSON's build date, when it has one) stands in, so
    distinct sources still cache separately.
    """
    tj = tilejson()
    if not tj:
        return None
    tiles = tj.get("tiles") or []
    if not tiles:
        return None
    template = tiles[0]
    version = next((seg for seg in template.split("/")
                    if len(seg) >= 15 and seg[:8].isdigit() and "_" in seg),
                   None)
    if version is None:
        # No dated segment (OSM US, a self-hosted source): namespace by
        # host so distinct sources never mix tiles, and by the build date
        # planetiler stamps so a daily-rebuilt source refreshes with its
        # TileJSON instead of serving the first-cached tile forever.
        import urllib.parse
        version = urllib.parse.urlsplit(template).hostname or "default"
        stamp = str(tj.get("timestamp", ""))[:10].replace("-", "")
        if len(stamp) == 8 and stamp.isdigit():
            version = f"{version}_{stamp}"
    try:
        maxzoom = int(tj.get("maxzoom", _MAX_ZOOM_FALLBACK))
    except (TypeError, ValueError):
        maxzoom = _MAX_ZOOM_FALLBACK
    return template, version, maxzoom


def tiles_for_bbox(bbox: tuple[float, float, float, float], z: int) -> list[tuple[int, int, int]]:
    """[(z, x, y), ...] covering the bbox; x wraps at the antimeridian,
    y clamps at the mercator poles."""
    minlon, minlat, maxlon, maxlat = bbox
    n = 1 << z
    x0, y0 = _lonlat_to_world(minlon, maxlat)  # top-left
    x1, y1 = _lonlat_to_world(maxlon, minlat)  # bottom-right
    tx0 = int(x0 * n)
    # right edge by ceiling so a bbox past the antimeridian (world x > 1)
    # reaches the wrapped tiles instead of clamping at n - 1
    tx1 = math.ceil(x1 * n) - 1
    ty0 = max(0, int(y0 * n))
    ty1 = min(int(y1 * n), n - 1)
    return [(z, tx % n, ty)
            for ty in range(ty0, ty1 + 1)
            for tx in range(tx0, tx1 + 1)]


def projector(z: int, tx: int, ty: int, extent: int, bbox: tuple[float, float, float, float],
              dw: float, dh: float) -> Callable[[float, float], tuple[float, float]]:
    """Tile-local (x, y) -> dot-space (x, y) for one tile in one view.

    Tile coordinates are web mercator; the view is linear in lon/lat
    (bbox_for already put the aspect correction in the bbox, which is
    what makes a braille dot ground-square).  Going through lon/lat
    rather than staying in mercator keeps street mode registered with
    the elevation grid and the Natural Earth basemap to the dot.
    """
    n = float(1 << z)
    minlon, minlat, maxlon, maxlat = bbox
    lon_span = (maxlon - minlon) or 1e-12
    lat_span = (maxlat - minlat) or 1e-12
    # x depends only on px and y only on py, and both are integers on
    # a grid of a few thousand — so each axis is computed once per
    # value and looked up after.  A terrain view projects ~300k
    # vertices through a few dozen of these; the tables are what turn
    # most of them into two dict reads.
    cols: dict[float, float] = {}
    rows: dict[float, float] = {}

    def project(px, py):
        x = cols.get(px)
        if x is None:
            lon = (tx + px / extent) / n * 360.0 - 180.0
            # a view spanning the antimeridian holds wrapped tiles,
            # whose longitudes come back on the far side of the world
            if lon < minlon - 180.0:
                lon += 360.0
            elif lon > maxlon + 180.0:
                lon -= 360.0
            x = cols[px] = (lon - minlon) / lon_span * dw
        y = rows.get(py)
        if y is None:
            wy = (ty + py / extent) / n
            lat = math.degrees(math.atan(math.sinh(
                math.pi * (1.0 - 2.0 * wy))))
            y = rows[py] = (maxlat - lat) / lat_span * dh
        return (x, y)

    return project


DEFAULT_EXTENT = 4096   # the MVT default, when a layer carries none


def iter_layer(
    view: Iterable[tuple[tuple[int, int, int], dict[str, Any]]],
    names: str | Sequence[str], bbox: tuple[float, float, float, float], dw: float, dh: float,
    geom: int | None = None,
) -> Iterator[tuple[str, dict[str, Any], Callable[[float, float], tuple[float, float]]]]:
    """(layer name, feature, project) for every feature of the named
    layers in a decoded view, tile by tile in the view's own order.

    `names` is one layer name or a sequence of them; `geom` keeps only
    features of that geometry type (1 point, 2 linestring, 3 polygon).
    One projector is built per tile and layer and handed out with each
    feature: it is the projector every consumer must use, so a fill,
    its stroke and its label agree to the dot.
    """
    if isinstance(names, str):
        names = (names,)
    for (z, tx, ty), decoded in view:
        for name in names:
            src = decoded.get(name)
            if src is None:
                continue
            project = projector(z, tx, ty, src.get("extent") or DEFAULT_EXTENT,
                                bbox, dw, dh)
            for feat in src["features"]:
                if geom is not None and feat["type"] != geom:
                    continue
                yield name, feat, project


def _cache_path(version, z, x, y):
    return cache_dir("maps", "vt", version, f"{z}_{x}_{y}.pbf")


def fetch_tile(z: int, x: int, y: int, timeout: float = 15) -> bytes | None:
    """Raw MVT bytes for a tile (b"" = empty tile), or None on failure.

    Disk-cached forever under the current version segment; the cache
    stores decompressed bytes so later loads skip the gunzip.
    """
    info = tile_info()
    if info is None:
        return None
    template, version, _ = info
    path = _cache_path(version, z, x, y)
    try:
        data = path.read_bytes()
    except OSError:
        pass
    else:
        note_tile_use(path)  # so the sweep sees a tile still in use
        return data
    url = (template.replace("{z}", str(z))
           .replace("{x}", str(x)).replace("{y}", str(y)))
    try:
        data = fetch_bytes(url, headers={"Accept-Encoding": "gzip"},
                           timeout=timeout)
        # sniff rather than trust Content-Encoding: static hosts serve
        # pre-gzipped bodies without declaring them
        if data[:2] == b"\x1f\x8b":
            data = gunzip_limited(data, MAX_BODY_BYTES)
    except Exception as exc:
        log_failure("maps/vtiles", f"tile {z}/{x}/{y} fetch", exc, url=url,
                    fallback="no tile")
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # atomic publish so a concurrent reader never sees a torn file
        write_bytes_atomic(path, data)
    except OSError as exc:
        log_failure("cache", f"write of {path.name}", exc, fallback="not cached")
    return data


def fetch_tiles(keys: list[tuple[int, int, int]], timeout: float = 15
                ) -> dict[tuple[int, int, int], bytes | None]:
    """{(z, x, y): bytes|None} for a batch, fetched concurrently."""
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = pool.map(lambda k: fetch_tile(*k, timeout=timeout), keys)
    return dict(zip(keys, results))
