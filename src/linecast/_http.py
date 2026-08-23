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
import time
import urllib.parse

from linecast._cache import read_cache, read_stale, write_bytes_atomic, write_cache
from linecast._runtime import debug_log

_REDIRECTS = (301, 302, 303, 307, 308)
_MAX_REDIRECTS = 5

_local = threading.local()


class HTTPError(OSError):
    """A response that was not 2xx.  Mirrors the attributes callers read
    off urllib.error.HTTPError: code, reason, headers, url."""

    def __init__(self, url, code, reason, headers=None, body=b""):
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


def _fetch_bytes_urllib(url, headers, timeout):
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


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


def _request(url, headers, timeout):
    """One GET on the thread's connection for url's host.

    Returns (status, reason, headers, body).  A reused connection the
    server has already closed fails with a disconnect on the first byte;
    that is dropped and the request retried once on a fresh socket.  A
    brand-new connection that fails is not retried.
    """
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {url}")
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
            body = resp.read()
        except _stale_connection_errors() as exc:
            _drop(key)
            if reused and attempt == 0:
                debug_log(f"reconnecting to {parts.netloc}: {exc}")
                continue
            raise
        except BaseException:
            _drop(key)  # state unknown after an interrupted exchange
            raise
        return resp.status, resp.reason, resp.headers, body


def fetch_bytes(url, headers=None, timeout=10):
    """GET url and return the body bytes.

    Raises HTTPError for a non-2xx status and OSError (timeouts,
    refused connections, TLS failures) on transport trouble.  file://
    URLs read the local file, as they did under urllib.
    """
    debug_log(f"fetch {url}")
    from linecast import user_agent
    hdrs = {"User-Agent": user_agent(), "Connection": "keep-alive"}
    if headers:
        hdrs.update(headers)
    if url.startswith("file:"):
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        with open(path, "rb") as fh:
            return fh.read()
    if _proxied():
        return _fetch_bytes_urllib(url, hdrs, timeout)
    for _ in range(_MAX_REDIRECTS + 1):
        status, reason, resp_headers, body = _request(url, hdrs, timeout)
        if 200 <= status < 300:
            return body
        target = resp_headers.get("Location") if status in _REDIRECTS else None
        if not target:
            raise HTTPError(url, status, reason, resp_headers, body)
        url = urllib.parse.urljoin(url, target)
        debug_log(f"redirect -> {url}")
    raise HTTPError(url, status, "too many redirects", resp_headers, body)


def fetch_json(url, headers=None, timeout=10):
    """Fetch and decode a JSON payload from url."""
    return json.loads(fetch_bytes(url, headers=headers, timeout=timeout))


def fetch_json_cached(cache_file, max_age, url, headers=None, timeout=10, fallback=None):
    """Fetch JSON with fresh cache first, stale cache fallback, then fallback value."""
    cached = read_cache(cache_file, max_age)
    if cached is not None:
        debug_log(f"cache hit: {cache_file.name}")
        return cached

    try:
        data = fetch_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        debug_log(f"fetch failed: {url} — {exc}")
        stale = read_stale(cache_file)
        if stale is not None:
            debug_log(f"using stale cache: {cache_file.name}")
            return stale
        return fallback

    write_cache(cache_file, data)
    return data


def fetch_bytes_cached(cache_file, max_age, url, headers=None, timeout=10):
    """Fetch bytes with fresh cache first, stale cache fallback, else None.

    max_age None means the cached copy never expires (immutable tiles).
    """
    try:
        if cache_file.exists() and (
                max_age is None
                or time.time() - cache_file.stat().st_mtime < max_age):
            return cache_file.read_bytes()
    except OSError:
        pass

    try:
        data = fetch_bytes(url, headers=headers, timeout=timeout)
    except Exception as exc:
        debug_log(f"fetch failed: {url} — {exc}")
        try:
            if cache_file.exists():
                debug_log(f"using stale cache: {cache_file.name}")
                return cache_file.read_bytes()
        except OSError:
            pass
        return None

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(cache_file, data)
    except OSError as exc:
        debug_log(f"cache write failed: {cache_file.name} — {exc}")
    return data
