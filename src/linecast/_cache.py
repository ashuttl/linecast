"""Shared cache helpers for linecast."""

import hashlib, json, os, threading, time
from pathlib import Path

CACHE_ROOT = Path.home() / ".cache" / "linecast"


def write_bytes_atomic(path, data):
    """Write to a sibling temp file, then publish with os.replace.

    Readers (and the four commands running side by side in the hero shot)
    never observe a torn file, and a prefetch thread dying at interpreter
    exit can't leave a truncated payload behind to be served forever.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def read_cache(path, max_age):
    """Read JSON cache file if it exists and isn't too old. Returns data or None."""
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < max_age:
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, KeyError):
                pass
    return None


def read_stale(path):
    """Read cache regardless of age (for fallback when network is down)."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def write_cache(path, data):
    """Write JSON cache file (atomically: concurrent commands share these)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(path, json.dumps(data).encode())


def location_cache_key(lat, lng):
    """Short hash for lat/lng to namespace cache files by location."""
    key = f"{lat:.4f},{lng:.4f}"
    return hashlib.md5(key.encode()).hexdigest()[:8]
