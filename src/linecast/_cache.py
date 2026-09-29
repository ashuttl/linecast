"""Shared cache helpers for linecast."""

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from linecast._log import log_failure


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write to a sibling temp file, then publish with os.replace.

    Readers (and the four commands running side by side in the hero shot)
    never observe a torn file, and a prefetch thread dying at interpreter
    exit can't leave a truncated payload behind to be served forever.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    # 0600: cache files can hold the user's chosen coordinates, so they
    # belong to the user alone even under a permissive umask.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


# How far into the future a file's mtime may sit and still count as
# just written: a coarse filesystem clock, not a clock that was later
# set back.
_FUTURE_SLACK = 60


def is_fresh(mtime: float, max_age: float) -> bool:
    """Whether a file written at `mtime` is within `max_age` seconds old.

    A modification time in the future means the clock was wrong when
    the file was written, or is wrong now; either way its age says
    nothing, and a file that never ages would be served forever
    (issue #68).  Such a file counts as expired.
    """
    age = time.time() - mtime
    return -_FUTURE_SLACK <= age < max_age


def read_cache(path: Path, max_age: float) -> Any:
    """Read JSON cache file if it exists and isn't too old. Returns data or None.

    A file that cannot be read or parsed counts as absent: the caller
    fetches fresh, which is what a cache is for.
    """
    try:
        if not path.exists():
            return None
        if not is_fresh(path.stat().st_mtime, max_age):
            return None
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        log_failure("cache", f"read of {path.name}", exc, fallback="treated as miss")
        return None


def read_stale(path: Path) -> Any:
    """Read cache regardless of age (for fallback when network is down)."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        log_failure("cache", f"stale read of {path.name}", exc, fallback="no stale copy")
        return None


def write_cache(path: Path, data: Any) -> None:
    """Write JSON cache file (atomically: concurrent commands share these).

    Best effort: a cache directory that cannot be written costs the next
    run a refetch, and must never cost this run its answer.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, json.dumps(data).encode())
    except OSError as exc:
        log_failure("cache", f"write of {path.name}", exc, fallback="not cached")


def location_cache_key(lat: float, lng: float) -> str:
    """Short hash for lat/lng to namespace cache files by location."""
    key = f"{lat:.4f},{lng:.4f}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# The daily sweep
# ---------------------------------------------------------------------------
# What the sweep deletes, as (folder under the cache root, file pattern,
# days).  A cached file is written again whenever it is used past its
# maximum age, so its age says how long since it was last used, give or
# take that maximum; each rule's days are well past both the maximum age
# and the time a stale copy is still worth showing offline.  What does
# not change -- a place's name and time zone, the tide stations near it
# and what they are, an answer to a search -- goes only after a year
# unused.  The ten years of climate a place is compared with are kept
# whatever their age, and go when the span they cover is out of date
# (_rolled_over).  Maps and radar prune their own tiles, the alert
# services their CAP files, and the developer's prose/ fixtures are
# never touched.
_YEAR = 365
_SWEEP = (
    ("", "timezone_*.json", _YEAR),
    ("weather", "forecast_*.json", 14),
    ("weather", "aqi_*.json", 7),
    ("weather", "aqhi_*.json", 7),
    ("weather", "metar_*.json", 7),
    ("weather", "alerts_*", 7),
    ("weather", "place_*.json", _YEAR),
    # the reverse geocoder's names before they were kept per place
    ("weather", "location.json", 0),
    ("weather", "location_*.json", 0),
    ("marine", "marine_*.json", 7),
    ("radar", "field_*.json", 7),
    ("maps/search", "*.json", _YEAR),
    ("tides", "pred_*.json", 90),
    ("tides", "hilo_*.json", 90),
    ("tides", "chs_pred_*.json", 90),
    ("tides", "chs_hilo_*.json", 90),
    ("tides", "qld_pred_*.json", 90),
    ("tides", "tc_hilo_*.json", 90),
    ("tides", "hko_hhot_*.json", _YEAR),
    ("tides", "hko_hlt_*.json", _YEAR),
    ("tides", "*yrange_*.json", 30),
    ("tides", "om_raw_*.json", 30),
    ("tides", "tc_raw_*.json", 30),
    ("tides", "tc_requests_*.json", 3),
    ("tides", "*station_*.json", _YEAR),
    ("tides", "*_meta_*.json", _YEAR),
    ("tides", "tc_search_*.json", _YEAR),
)
# Files a write left behind when it was cut short (write_bytes_atomic)
_LEFTOVERS = ("", "weather", "tides", "marine", "radar", "maps")
_SWEEP_EVERY = 86400
# The climate files, by the last year they cover, and how far back that
# may be while a view still asks for them: this year's comparison is the
# ten years to last year, and the year view is this year so far.
_ROLLED_OVER = ((re.compile(r"hist_[0-9a-f]+_\d{4}-(\d{4})_"), 1),
                (re.compile(r"year_[0-9a-f]+_(\d{4})_"), 0))


def _rolled_over(name, this_year):
    """Whether a climate file covers years the views no longer ask for.
    Last year's are kept as well, for a place where the new year has not
    come yet when it has in UTC."""
    for pattern, back in _ROLLED_OVER:
        m = pattern.match(name)
        if m:
            return int(m.group(1)) < this_year - back - 1
    return False


def sweep(now=None):
    """Delete the cached files no view will read again, at most once a
    day.  Returns how many went, or None when it is not yet time."""
    from linecast._paths import cache_root
    root = cache_root()
    now = time.time() if now is None else now
    stamp = root / "swept"
    try:
        if now - stamp.stat().st_mtime < _SWEEP_EVERY:
            return None
    except FileNotFoundError:
        pass
    except OSError as exc:
        log_failure("cache", "sweep stamp", exc, fallback="not swept")
        return None
    try:
        root.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        os.utime(stamp, (now, now))
    except OSError as exc:
        log_failure("cache", "sweep stamp", exc, fallback="not swept")
        return None
    this_year = time.gmtime(now).tm_year
    gone = 0

    def drop(path, days):
        nonlocal gone
        try:
            if now - path.stat().st_mtime > days * 86400:
                path.unlink()
                gone += 1
        except OSError:
            pass   # gone already, or not ours to delete

    try:
        for folder, pattern, days in _SWEEP:
            for path in (root / folder).glob(pattern):
                drop(path, days)
        for path in (root / "weather").glob("*.json"):
            if _rolled_over(path.name, this_year):
                drop(path, 0)
        for folder in _LEFTOVERS:
            for path in (root / folder).glob("*.tmp"):
                drop(path, 1)
    except OSError as exc:
        log_failure("cache", "sweep", exc, fallback="left in place")
    return gone
