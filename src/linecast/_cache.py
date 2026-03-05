"""Shared cache helpers for linecast."""

import hashlib, json, time
from pathlib import Path

CACHE_ROOT = Path.home() / ".cache" / "linecast"


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
    """Write JSON cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def location_cache_key(lat, lng):
    """Short hash for lat/lng to namespace cache files by location."""
    key = f"{lat:.4f},{lng:.4f}"
    return hashlib.md5(key.encode()).hexdigest()[:8]
