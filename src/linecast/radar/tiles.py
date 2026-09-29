"""Radar tiles from providers speaking the RainViewer v2 protocol.

LibreWXR and RainViewer both publish a weather-maps.json index (host +
past/nowcast frame lists) and serve standard XYZ (Web-Mercator) tiles at
{host}{path}/{size}/{z}/{x}/{y}/{color}/{options}.png.  Our basemap is
equirectangular (EPSG:4326), so we fetch the Web-Mercator tiles covering the
view and hand them to _xyz.reproject_xyz, which stitches them into a canvas
and resamples per output pixel back to lat/lon — the basemap and radar stay
aligned and everything downstream (build_radar_buffer / compose) is
unchanged.

Providers differ only in the constants captured by a Provider instance:
index URL, colour scheme, zoom ceiling, and cache directory.
"""

import json
import os
from collections.abc import Callable
from typing import Any

from linecast._cache import is_fresh, write_bytes_atomic
from linecast._http import fetch_bytes, fetch_bytes_cached
from linecast._paths import cache_dir
from linecast._png import decode_rgba
from linecast._log import log_failure
from linecast._xyz import TILE_SIZE, pick_zoom, reproject_xyz

_INDEX_TTL = 120     # seconds to trust a cached index before refetching
_NOWCAST_TTL = 600   # forecast tiles are re-predicted; treat older as stale
_RETRY_TIMEOUT = 5   # second attempt at a tile the first one did not get


class IncompleteFrame(Exception):
    """A stitch that lost tiles to the network.

    Raised rather than returned, because the canvas it would otherwise
    hand back is indistinguishable from a real one: a tile that never
    arrived leaves a hole shaped exactly like fair weather, and a frame
    memoised with one shows that hole for the rest of the session.  Both
    providers answer a region with nothing in it with a small opaque PNG
    and never a 404, so a tile that does not arrive is a failure, not an
    empty sky.
    """

    missed: int
    total: int

    def __init__(self, missed: int, total: int) -> None:
        super().__init__(f"{missed} of {total} tiles did not arrive")
        self.missed = missed
        self.total = total


LIBREWXR_DEFAULT_URL = "https://api.librewxr.net"
# The grayscale scheme: gray = dBZ + 32 (+128 for snow).  Fetched unsmoothed
# it is reflectivity data we can colour ourselves (see palettes).
RAW_COLOR = 0


class Provider:
    """One RainViewer-v2-protocol tile service."""
    __slots__ = ("name", "index_url", "color", "options", "max_zoom", "tag")

    name: str
    index_url: str
    color: int
    options: str
    max_zoom: int
    tag: str

    def __init__(self, name: str, index_url: str, color: int, options: str,
                 max_zoom: int) -> None:
        self.name = name            # cache subdir under radar/
        self.index_url = index_url
        self.color = color          # colour scheme id baked into tile pixels
        self.options = options      # {smooth}_{snow}
        self.max_zoom = max_zoom
        # the provider's name in the debug log (see _log.log_failure)
        self.tag = _TAGS.get(name.split("-", 1)[0], "radar/" + name)


_TAGS = {"rv": "radar/rainviewer", "lwxr": "radar/librewxr"}


def rainviewer_provider(smooth: bool = True) -> Provider:
    # Free/personal tier: Universal Blue only (the colour id in the URL is
    # ignored), max zoom 7.  Unsmoothed tiles keep the published table's
    # exact colours, which is what lets ub decode them.
    return Provider("rv", "https://api.rainviewer.com/public/weather-maps.json",
                    color=2, options=f"{int(smooth)}_1", max_zoom=7)


def librewxr_provider(color: int, smooth: bool = True) -> Provider:
    # Base URL overridable so a self-hosted instance can be pointed at; the
    # tile host still comes from the index response's "host" field.
    base = os.environ.get("LINECAST_LIBREWXR_URL", LIBREWXR_DEFAULT_URL)
    return Provider("lwxr", base.rstrip("/") + "/public/weather-maps.json",
                    color=color, options=f"{int(smooth)}_1", max_zoom=12)


def satellite_provider(provider: Provider) -> Provider:
    # Satellite tiles ride the same index and URL shape as radar but are
    # only rendered in one scheme (grayscale VIS-over-LW, alpha = cloud
    # opacity), and the source mosaic is ~8 km so deep zooms add nothing.
    return Provider(provider.name + "-sat", provider.index_url,
                    color=0, options="0_0", max_zoom=6)


def _cache_dir(provider):
    return cache_dir("radar", provider.name)


# Frame tiles are keyed by their timestamped frame path and never requested
# again once the animation window moves past them, so without a sweep the
# cache only grows (a long-running radar adds megabytes per day).
_PRUNE_MAX_AGE = 86400


def prune_tile_cache(max_age: float = _PRUNE_MAX_AGE) -> None:
    """Delete cached radar/satellite tiles older than *max_age* seconds.

    Runs at radar startup. Only sweeps the timestamp-keyed radar tree;
    immutable caches (terrain, vector tiles) are someone else's and eternal.
    """
    root = cache_dir("radar")
    try:
        if not root.is_dir():
            return
        for entry in root.iterdir():
            # Tile sources keep a directory each; the IEM frames sit as
            # files at the root, and age the same way.
            if entry.is_dir():
                tiles = entry.glob("*.png")
            elif entry.suffix == ".png":
                tiles = [entry]
            else:
                continue
            for tile in tiles:
                try:
                    # A tile stamped in the future never ages past the
                    # cutoff; it is as wrong as an old one, so it goes too.
                    if not is_fresh(tile.stat().st_mtime, max_age):
                        tile.unlink()
                except OSError:
                    pass  # a concurrent radar may have pruned it first
    except OSError as exc:
        log_failure("cache", f"prune of {root.name}", exc, fallback="skipped")


def fetch_index(provider: Provider, timeout: float = 15) -> dict[str, Any]:
    """Return the parsed weather-maps.json (host + past/nowcast frame lists).

    Cached on disk for _INDEX_TTL seconds; falls back to stale cache on error.
    """
    path = _cache_dir(provider) / "weather-maps.json"
    try:
        if path.exists() and is_fresh(path.stat().st_mtime, _INDEX_TTL):
            return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        log_failure("cache", f"read of {path.name}", exc, fallback="refetching")
    try:
        data = fetch_bytes(provider.index_url, timeout=timeout)
        index = json.loads(data)
    except Exception as exc:
        stale = _stale_index(path)
        log_failure(provider.tag, "index fetch", exc, url=provider.index_url,
                    fallback="stale index" if stale is not None else "raised")
        if stale is not None:
            return stale
        raise
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, data)
    except OSError as exc:
        log_failure("cache", f"write of {path.name}", exc, fallback="not cached")
    return index


def _stale_index(path):
    """The last index we managed to keep, whatever its age, or None."""
    try:
        if path.exists():
            return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        log_failure("cache", f"stale read of {path.name}", exc, fallback="no index")
    return None


def _tile_url(provider, host, path, z, x, y):
    return (f"{host}{path}/{TILE_SIZE}/{z}/{x}/{y}/"
            f"{provider.color}/{provider.options}.png")


def _tile_cache_path(provider, path, z, x, y):
    frame_id = path.strip("/").replace("/", "_")
    return (_cache_dir(provider) / f"{frame_id}_{z}_{x}_{y}_c{provider.color}"
            f"_{provider.options}.png")


def _fetch_tile(provider, host, path, z, x, y, timeout=15, mutable=False):
    """One tile as PNG bytes, disk-cached per colour scheme.

    Past-frame tiles are immutable by frame path; nowcast tiles (mutable=True)
    are re-predicted between index refreshes, so a cached copy older than
    _NOWCAST_TTL is refetched (stale bytes still serve as a network fallback).
    """
    cpath = _tile_cache_path(provider, path, z, x, y)
    url = _tile_url(provider, host, path, z, x, y)
    return fetch_bytes_cached(cpath, _NOWCAST_TTL if mutable else None, url,
                              timeout=timeout)


def _discard_tile(provider, path, z, x, y):
    """Drop a cached tile whose bytes would not decode.

    A past frame's tiles never expire, so bytes that arrived torn would
    otherwise refuse that frame for as long as the cache keeps them.
    """
    try:
        _tile_cache_path(provider, path, z, x, y).unlink(missing_ok=True)
    except OSError as exc:
        log_failure("cache", "discard of a torn tile", exc, fallback="kept")


def reproject(provider: Provider, host: str, path: str, bbox: tuple[float, float, float, float],
              w: int, h: int, timeout: float = 15, mutable: bool = False,
              smooth: bool = False,
              transform: Callable[[bytearray], Any] | None = None,
              ) -> tuple[int, int, bytearray]:
    """Fetch the tiles covering `bbox` and resample to a `w`×`h` EPSG:4326 RGBA.

    Returns (w, h, bytearray) — same shape decode_rgba yields, so it drops
    straight into build_radar_buffer.  `smooth` asks for the bilinear pass
    meant for raw grayscale (reflectivity) tiles; `transform` rewrites each
    decoded tile in place first (see ub), so the disk cache keeps
    the bytes as served.

    A tile that does not arrive is asked for once more before the frame is
    given up on, and a frame still short of tiles raises IncompleteFrame
    rather than returning a canvas with holes in it.
    """
    z = pick_zoom(bbox, w, provider.max_zoom)
    # list.append is atomic, and the pool fetches these concurrently
    wanted: list[tuple[int, int, int]] = []
    missed: list[tuple[int, int, int]] = []

    def fetch(z_, x, y):
        wanted.append((z_, x, y))
        data = _fetch_tile(provider, host, path, z_, x, y, timeout,
                           mutable=mutable)
        if data is None:
            # A tile the server was slow to render is often still being
            # rendered when our timeout fires: the request that timed out
            # is what set it going, and a second one collects it in a few
            # hundred milliseconds.  The retry runs in this pool thread,
            # so it goes alongside the other tiles rather than after them,
            # and it waits _RETRY_TIMEOUT rather than the full timeout —
            # a tile that is not ready by now was never coming.
            data = _fetch_tile(provider, host, path, z_, x, y,
                               _RETRY_TIMEOUT, mutable=mutable)
        if data is not None:
            try:
                tile = decode_rgba(data)
            except Exception as exc:
                _discard_tile(provider, path, z_, x, y)
                log_failure(provider.tag, f"tile {z_}/{x}/{y} decode", exc,
                            fallback="frame refused, tile dropped")
            else:
                if transform is not None:
                    transform(tile[2])
                return tile
        missed.append((z_, x, y))
        return None

    result = reproject_xyz(fetch, bbox, w, h, z, smooth=smooth)
    if missed:
        raise IncompleteFrame(len(missed), len(wanted))
    return result
