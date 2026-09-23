"""Keeping the map tile cache from growing without end.

Radar sweeps by age, and rightly: its tiles are keyed by frame timestamp
and nothing asks for yesterday's. Map tiles are the opposite. Terrain,
built-up and vector tiles for a given z/x/y never change, so age says
nothing about whether a tile is still wanted -- the tiles for home are
among the oldest on disk and the last that should go. What does grow
without bound is the total, a continent at a time.

So the sweep here goes by size, in two passes, cheapest first.

A vector tile lives under the version segment of the tilejson that named
it. When the planet rebuilds, that segment changes and every tile beneath
the old one is dead weight that nothing will ask for again -- 135MB of it
in the cache that prompted this, against 33MB still in use. Dropping
those costs nothing at all, so it happens first and unconditionally.

What remains is capped, and over the cap the least recently used tiles
go first. A tile is written once and read many times, so its write time
says when it was first fetched and nothing more -- sweeping by that
would retire the city visited every morning ahead of the continent
visited once last spring, which is the wrong way round. So reading a
tile marks it (note_tile_use, below) and the sweep goes by the mark.

Empty tiles are exempt too, for the same reason from the other end: a
zero-byte file is a cached "nothing here", and dropping one frees
nothing while costing a refetch.

Only the tile pyramids are evictable. The handful of small artifacts
beside them -- the tilejson, the polar cloud mask, the search results,
the precomputed globe canvases -- are a few megabytes between them and
cost real work to rebuild, so the sweep leaves them alone.
"""

import os
import shutil
import time

from linecast._paths import cache_dir
from linecast._runtime import log_failure

# Generous for the way the tool is used -- a home region in detail and
# the odd trip elsewhere -- and small enough that the cache stays
# something a user never has to think about.
DEFAULT_CACHE_MB = 256

# Decimal, to agree with the MB doctor prints: a cache reported at 256.0
# MB against a cap the user set to 256 should not look like an overrun.
_BYTES_PER_MB = 1_000_000

_EVICTABLE_SUFFIXES = (".pbf", ".png")
_KEEP_PREFIXES = ("globe_canvas",)

# How stale a tile's mark has to be before a read rewrites it. The sweep
# wants nothing finer than a day, and a view redrawing at speed should
# not touch the disk once per tile per frame.
_MARK_AFTER = 86400


def note_tile_use(path):
    """Mark a cached tile as used just now, for the sweep to sort by.

    Called on the hit path of the tile readers. Best effort: a mark that
    cannot be written leaves the tile sorting by its fetch time, which is
    where it started.

    Empty files are left unmarked. A zero-byte tile is a cached miss
    whose mtime is its expiry, not its age, and it holds no bytes the
    sweep could want back.
    """
    try:
        stat = os.stat(path)
        now = time.time()
        if not stat.st_size or now - stat.st_mtime < _MARK_AFTER:
            return
        os.utime(path, (now, now))
    except OSError:
        pass


def cache_limit_bytes():
    """The cap in bytes, from LINECAST_MAPS_CACHE_MB or the default."""
    raw = os.environ.get("LINECAST_MAPS_CACHE_MB", "").strip()
    if raw:
        try:
            mb = float(raw)
        except ValueError:
            log_failure("cache", f"reading LINECAST_MAPS_CACHE_MB={raw!r}",
                        ValueError("not a number"),
                        fallback=f"{DEFAULT_CACHE_MB}MB")
        else:
            if mb >= 0:
                return int(mb * _BYTES_PER_MB)
    return DEFAULT_CACHE_MB * _BYTES_PER_MB


def _current_vector_version():
    """The version segment the tilejson points at now, or "".

    "" whenever the answer is not known for certain -- offline with a cold
    tilejson cache, say. Every version on disk is then one we might still
    be drawing from, so the stale pass stands down rather than deleting
    the lot and leaving the user with a blank map and no way to refill it.
    """
    try:
        from linecast._vtiles import tile_info
        info = tile_info()
        return info[1] if info else ""
    except Exception:
        return ""


def _drop_stale_vector_versions(root, keep):
    """Remove vt/<version> trees the tilejson no longer names. Bytes freed."""
    vt = root / "vt"
    if not keep or not vt.is_dir():
        return 0
    freed = 0
    for version_dir in vt.iterdir():
        if version_dir.name == keep or not version_dir.is_dir():
            continue
        size = sum(size for _, size, _ in _tile_files(version_dir))
        try:
            shutil.rmtree(version_dir, ignore_errors=True)
        except OSError:
            continue  # a concurrent maps may be part-way through the same
        freed += size
    return freed


def _tile_files(root):
    """(path, size, last used) for each evictable tile under *root*."""
    found = []
    stack = [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.name.endswith(_EVICTABLE_SUFFIXES):
                            continue
                        if entry.name.startswith(_KEEP_PREFIXES):
                            continue
                        stat = entry.stat()
                        # a cached "nothing here" frees no bytes, and
                        # dropping it only buys a refetch
                        if not stat.st_size:
                            continue
                        # atime as well: where the filesystem keeps it, it
                        # sees the reads that happened before a tile was
                        # first marked, and where it doesn't it reads as
                        # the fetch time and costs nothing.
                        used = max(stat.st_atime, stat.st_mtime)
                        found.append((entry.path, stat.st_size, used))
                    except OSError:
                        continue  # vanished under us; someone else's problem
        except OSError:
            continue
    return found


def prune_maps_cache(limit=None):
    """Sweep the map tile cache back under its size cap. Bytes freed.

    Runs at maps startup, before the session adds to the pile. Best
    effort throughout: a cache that cannot be swept costs disk, and must
    never cost the user their map.
    """
    root = cache_dir("maps")
    if limit is None:
        limit = cache_limit_bytes()
    freed = 0
    try:
        if not root.is_dir():
            return 0
        freed += _drop_stale_vector_versions(root, _current_vector_version())

        tiles = _tile_files(root)
        total = sum(size for _, size, _ in tiles)
        if total <= limit:
            return freed
        tiles.sort(key=lambda tile: tile[2])  # least recently used first
        for path, size, _ in tiles:
            if total <= limit:
                break
            try:
                os.unlink(path)
            except OSError:
                continue  # a concurrent maps got there first
            total -= size
            freed += size
    except OSError as exc:
        log_failure("cache", f"prune of {root.name}", exc, fallback="skipped")
    return freed
