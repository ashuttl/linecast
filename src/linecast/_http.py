"""Shared HTTP + JSON fetch helpers.

Every request goes through fetch_bytes, which keeps one open connection
per (scheme, host, port) per thread and reuses it for the next request
to the same server.  A tile pyramid or a run of Open-Meteo calls then
pays the TCP + TLS handshake once instead of once per request; a server
that hangs up on an idle socket costs one reconnect.  Threads each keep
their own connections (a threading.local), so worker pools never share
a socket.

The User-Agent is attached here by default, so callers only pass the
headers that are specific to them.
"""

import json
import os
import threading
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from linecast._cache import is_fresh, read_cache, read_stale, write_bytes_atomic, write_cache
from linecast._runtime import debug_enabled, debug_log, log_failure, redact_url

if TYPE_CHECKING:
    import http.client
    from collections.abc import Callable
    from email.message import Message

_REDIRECTS = (301, 302, 303, 307, 308)
_MAX_REDIRECTS = 5

# Hard ceilings on how much of a response body we will hold.  Real
# payloads run a few hundred KB at most; anything bigger is a broken or
# hostile server, and refusing it keeps memory — and everything
# downstream of our stdout — bounded.
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024

_CHUNK = 64 * 1024

_local = threading.local()


def read_limited(resp: "http.client.HTTPResponse", limit: int) -> bytes:
    """Stream a response body, refusing to keep more than limit bytes.

    An honest oversized response is refused from its Content-Length
    before a byte is read; a lying or chunked one is cut off as soon as
    the stream crosses the limit.
    """
    declared = getattr(resp, "length", None)
    if declared is not None and declared > limit:
        raise ValueError(f"response of {declared} bytes exceeds cap of {limit}")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"response body exceeds cap of {limit} bytes")
        chunks.append(chunk)


def gunzip_limited(data: bytes, limit: int) -> bytes:
    """Decompress a gzip body, refusing to expand past limit bytes."""
    import zlib
    d = zlib.decompressobj(31)
    out = d.decompress(data, limit)
    if d.unconsumed_tail:
        raise ValueError(f"decompressed body exceeds cap of {limit} bytes")
    return out


class HTTPError(OSError):
    """A response that was not 2xx.  Mirrors the attributes callers read
    off urllib.error.HTTPError: code, reason, headers, url."""

    url: str
    code: int
    reason: str
    headers: "Message | None"
    body: bytes

    def __init__(self, url: str, code: int, reason: str,
                 headers: "Message | None" = None, body: bytes = b"") -> None:
        super().__init__(f"HTTP Error {code}: {reason}")
        self.url = url
        self.code = code
        self.reason = reason
        self.headers = headers
        self.body = body


def _proxied():
    """True when the environment asks for a proxy (http_proxy and kin);
    those requests take urllib's proxy-aware path instead of ours."""
    for name, value in os.environ.items():
        low = name.lower()
        if value and low.endswith("_proxy") and low != "no_proxy":
            return True
    return False


def _fetch_bytes_urllib(url, headers, timeout, limit):
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return read_limited(resp, limit)


def _connection(key, timeout):
    """The calling thread's connection for (scheme, host, port), opened
    lazily by http.client on the first request; the timeout is refreshed
    on the socket so each request honours its own."""
    import http.client
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    conn = conns.get(key)
    if conn is None:
        scheme, host, port = key
        cls = (http.client.HTTPSConnection if scheme == "https"
               else http.client.HTTPConnection)
        conn = conns[key] = cls(host, port, timeout=timeout)
    else:
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
    return conn


def _drop(key):
    conns = getattr(_local, "conns", None)
    conn = conns.pop(key, None) if conns else None
    if conn is not None:
        conn.close()


def _stale_connection_errors():
    import http.client
    import ssl
    return (http.client.RemoteDisconnected, http.client.CannotSendRequest,
            http.client.ResponseNotReady, ConnectionResetError,
            ConnectionAbortedError, BrokenPipeError, ssl.SSLEOFError)


def _request(url, headers, timeout, limit):
    """One GET on the thread's connection for url's host.

    Returns (status, reason, headers, body).  A reused connection the
    server has already closed fails with a disconnect on the first byte;
    that is dropped and the request retried once on a fresh socket.  A
    brand-new connection that fails is not retried.
    """
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme {scheme or '(none)'!r} "
                         f"for host {parts.hostname or '(none)'!r}")
    key = (scheme, parts.hostname, parts.port)
    selector = parts.path or "/"
    if parts.query:
        selector += "?" + parts.query
    for attempt in (0, 1):
        conn = _connection(key, timeout)
        reused = conn.sock is not None
        try:
            conn.request("GET", selector, headers=headers)
            resp = conn.getresponse()
            body = read_limited(resp, limit)
        except _stale_connection_errors() as exc:
            _drop(key)
            if reused and attempt == 0:
                debug_log(f"reconnecting to {parts.hostname}: {exc}")
                continue
            raise
        except BaseException:
            _drop(key)  # state unknown after an interrupted exchange
            raise
        return resp.status, resp.reason, resp.headers, body


def fetch_bytes(url: str, headers: dict[str, str] | None = None,
                timeout: float = 10, limit: int = MAX_BODY_BYTES) -> bytes:
    """GET url and return the body bytes, refusing more than limit of them.

    Raises HTTPError for a non-2xx status, OSError (timeouts, refused
    connections, TLS failures) on transport trouble, and ValueError for
    a body past the limit.  file:// URLs read the local file, as they
    did under urllib.
    """
    if debug_enabled():
        debug_log(f"fetch {redact_url(url)}")
    from linecast import user_agent
    hdrs = {"User-Agent": user_agent(), "Connection": "keep-alive"}
    if headers:
        hdrs.update(headers)
    if url.startswith("file:"):
        # url2pathname unquotes and turns /C:/x into C:\x on Windows.
        from urllib.request import url2pathname
        path = url2pathname(urllib.parse.urlsplit(url).path)
        with open(path, "rb") as fh:
            return fh.read()
    if _proxied():
        return _fetch_bytes_urllib(url, hdrs, timeout, limit)
    for _ in range(_MAX_REDIRECTS + 1):
        status, reason, resp_headers, body = _request(url, hdrs, timeout, limit)
        if 200 <= status < 300:
            return body
        target = resp_headers.get("Location") if status in _REDIRECTS else None
        if not target:
            raise HTTPError(url, status, reason, resp_headers, body)
        url = urllib.parse.urljoin(url, target)
        if debug_enabled():
            debug_log(f"redirect -> {redact_url(url)}")
    raise HTTPError(url, status, "too many redirects", resp_headers, body)


def fetch_json(url: str, headers: dict[str, str] | None = None,
               timeout: float = 10, limit: int = MAX_JSON_BYTES) -> Any:
    """Fetch and decode a JSON payload from url."""
    return json.loads(fetch_bytes(url, headers=headers, timeout=timeout,
                                  limit=limit))


def fetch_json_cached(cache_file: Path, max_age: float, url: str,
                      headers: dict[str, str] | None = None, timeout: float = 10,
                      fallback: Any = None,
                      fetch: "Callable[..., Any] | None" = None,
                      fresh: "Callable[[Any], bool] | None" = None) -> Any:
    """Fetch JSON with fresh cache first, stale cache fallback, then fallback value.

    `fetch` replaces fetch_json for the network step (called as
    fetch(url, timeout=...)), for a provider that counts or signs its
    own requests; only a cache miss reaches it.

    `fresh` is a second test a cached copy must pass, on its content
    rather than its age -- a forecast whose "today" has gone by is stale
    however young the file.  A copy that fails it is refetched, and
    still stands in when the refetch fails.
    """
    cached = read_cache(cache_file, max_age)
    if cached is not None and (fresh is None or fresh(cached)):
        debug_log(f"cache hit: {cache_file.name}")
        return cached

    try:
        if fetch is not None:
            data = fetch(url, timeout=timeout)
        else:
            data = fetch_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        stale = read_stale(cache_file)
        log_failure("http", "fetch", exc, url=url,
                    fallback=(f"stale cache {cache_file.name}"
                              if stale is not None else "fallback value"))
        return stale if stale is not None else fallback

    write_cache(cache_file, data)
    return data


def fetch_bytes_cached(cache_file: Path, max_age: float | None, url: str,
                       headers: dict[str, str] | None = None,
                       timeout: float = 10) -> bytes | None:
    """Fetch bytes with fresh cache first, stale cache fallback, else None.

    max_age None means the cached copy never expires (immutable tiles).
    """
    try:
        if cache_file.exists() and (
                max_age is None
                or is_fresh(cache_file.stat().st_mtime, max_age)):
            return cache_file.read_bytes()
    except OSError as exc:
        log_failure("cache", f"read of {cache_file.name}", exc,
                    fallback="refetching")

    try:
        data = fetch_bytes(url, headers=headers, timeout=timeout)
    except Exception as exc:
        stale = None
        try:
            if cache_file.exists():
                stale = cache_file.read_bytes()
        except OSError as stale_exc:
            log_failure("cache", f"stale read of {cache_file.name}", stale_exc,
                        fallback="no data")
        log_failure("http", "fetch", exc, url=url,
                    fallback=(f"stale cache {cache_file.name}"
                              if stale is not None else "none"))
        return stale

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(cache_file, data)
    except OSError as exc:
        log_failure("cache", f"write of {cache_file.name}", exc,
                    fallback="not cached")
    return data
