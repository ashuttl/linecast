"""Shared cache helpers for linecast."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from linecast._runtime import log_failure


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
