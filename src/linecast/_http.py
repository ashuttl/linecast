"""Shared HTTP + JSON fetch helpers."""

import json
import urllib.request

from linecast._cache import read_cache, read_stale, write_cache
from linecast._runtime import debug_log


def fetch_json(url, headers=None, timeout=10):
    """Fetch and decode a JSON payload from url."""
    debug_log(f"fetch {url}")
    req = urllib.request.Request(url, headers=headers or {})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def fetch_json_cached(cache_file, max_age, url, headers=None, timeout=10, fallback=None):
    """Fetch JSON with fresh cache first, stale cache fallback, then fallback value."""
    cached = read_cache(cache_file, max_age)
    if cached is not None:
        debug_log(f"cache hit: {cache_file.name}")
        return cached

    try:
        data = fetch_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        debug_log(f"fetch failed: {url} \u2014 {exc}")
        stale = read_stale(cache_file)
        if stale is not None:
            debug_log(f"using stale cache: {cache_file.name}")
            return stale
        return fallback

    write_cache(cache_file, data)
    return data
