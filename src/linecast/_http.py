"""Shared HTTP + JSON fetch helpers."""

import json
import urllib.request

from linecast._cache import read_cache, read_stale, write_cache
from linecast._runtime import debug_log

# Hard ceilings on how much of a response body we will hold.  Real
# payloads run a few hundred KB at most; anything bigger is a broken or
# hostile server, and refusing it keeps memory — and everything
# downstream of our stdout — bounded.
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_TILE_BYTES = 16 * 1024 * 1024

_CHUNK = 64 * 1024


def read_limited(resp, limit):
    """Stream a response body, refusing to keep more than limit bytes.

    An honest oversized response is refused from its Content-Length
    before a byte is read; a lying or chunked one is cut off as soon as
    the stream crosses the limit.
    """
    declared = getattr(resp, "length", None)
    if declared is not None and declared > limit:
        raise ValueError(f"response of {declared} bytes exceeds cap of {limit}")
    chunks = []
    total = 0
    while True:
        chunk = resp.read(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"response body exceeds cap of {limit} bytes")
        chunks.append(chunk)


def gunzip_limited(data, limit):
    """Decompress a gzip body, refusing to expand past limit bytes."""
    import zlib
    d = zlib.decompressobj(31)
    out = d.decompress(data, limit)
    if d.unconsumed_tail:
        raise ValueError(f"decompressed body exceeds cap of {limit} bytes")
    return out


def fetch_json(url, headers=None, timeout=10, limit=MAX_JSON_BYTES):
    """Fetch and decode a JSON payload from url."""
    debug_log(f"fetch {url}")
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(read_limited(resp, limit))


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
