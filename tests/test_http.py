"""Tests for the shared HTTP layer: per-host connection reuse, the
retry on a server-closed socket, redirects, and the byte cache.

No network: http.client's connection classes are replaced with a fake
that records requests and replays scripted responses.
"""

import gzip
import http.client
import subprocess
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import linecast
from linecast import _http, _runtime


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Response:
    def __init__(self, status=200, body=b"ok", headers=None, reason="OK"):
        self.status = status
        self.reason = reason
        self.headers = _Headers(headers or {})
        self._body = body

    def read(self, n=-1):
        body, self._body = self._body, b""
        return body


class _Sock:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


def _wire_response(body, headers):
    """Use the real parser: sized reads can silently accept a short body."""
    class Socket:
        def makefile(self, *args):
            return BytesIO(b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n\r\n" + body)

    response = http.client.HTTPResponse(Socket())
    response.begin()
    return response


class _FakeConn:
    """Stands in for HTTP(S)Connection.  `script` is a list of responses
    or exceptions handed out in order, shared across instances so a
    retry on a fresh connection continues the same script."""

    script = []
    instances = []

    def __init__(self, host, port=None, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.requests = []
        self.closed = False
        _FakeConn.instances.append(self)

    def request(self, method, selector, headers=None):
        self.requests.append((method, selector, dict(headers or {})))
        if self.sock is None:
            self.sock = _Sock()  # http.client connects on first use

    def getresponse(self):
        item = _FakeConn.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True
        self.sock = None


class _UrllibResponse(_Response):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_opener(monkeypatch, open_):
    """Replace urllib's opener with one whose open() is open_, and keep
    the handlers fetch_bytes asked for, so a test can check them."""
    import urllib.request
    built = []

    class _Opener:
        def __init__(self, *handlers):
            built.extend(handlers)

        def open(self, req, timeout=None):
            return open_(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "build_opener", _Opener)
    return built


@pytest.fixture
def conns(monkeypatch):
    _FakeConn.script = []
    _FakeConn.instances = []
    monkeypatch.setattr(http.client, "HTTPSConnection", _FakeConn)
    monkeypatch.setattr(http.client, "HTTPConnection", _FakeConn)
    monkeypatch.setattr(_http, "_local", threading.local())
    monkeypatch.setattr(_http, "_proxied", lambda: False)
    return _FakeConn


class TestFetchBytes:
    def test_agent_and_keep_alive_attached_by_default(self, conns):
        conns.script = [_Response(body=b"hello")]
        assert _http.fetch_bytes("https://h.example/a?b=1") == b"hello"
        (method, selector, headers), = conns.instances[0].requests
        assert method == "GET" and selector == "/a?b=1"
        assert headers["User-Agent"].startswith("linecast/")
        assert headers["Connection"] == "keep-alive"

    def test_caller_headers_win(self, conns):
        conns.script = [_Response()]
        _http.fetch_bytes("https://h.example/", headers={
            "User-Agent": "custom/1", "Accept-Encoding": "gzip"})
        headers = conns.instances[0].requests[0][2]
        assert headers["User-Agent"] == "custom/1"
        assert headers["Accept-Encoding"] == "gzip"

    def test_gzip_asked_for_by_default(self, conns):
        conns.script = [_Response()]
        _http.fetch_bytes("https://h.example/")
        headers = conns.instances[0].requests[0][2]
        assert headers["Accept-Encoding"] == "gzip"

    def test_declared_gzip_body_inflated(self, conns):
        conns.script = [_Response(body=gzip.compress(b'{"daily": 1}'),
                                  headers={"content-encoding": "gzip"})]
        assert _http.fetch_bytes("https://h.example/") == b'{"daily": 1}'

    def test_inflated_body_past_the_limit_refused(self, conns):
        conns.script = [_Response(body=gzip.compress(b"\0" * 1000),
                                  headers={"Content-Encoding": "gzip"})]
        with pytest.raises(ValueError):
            _http.fetch_bytes("https://h.example/", limit=100)

    def test_undeclared_gzip_body_left_for_the_caller(self, conns):
        # static tile hosts serve pre-gzipped bodies with no
        # Content-Encoding; _vtiles sniffs and inflates those itself
        raw = gzip.compress(b"tile")
        conns.script = [_Response(body=raw)]
        assert _http.fetch_bytes("https://h.example/") == raw

    def test_declared_gzip_over_a_plain_body_passes_through(self, conns):
        conns.script = [_Response(body=b"not gzip",
                                  headers={"Content-Encoding": "gzip"})]
        assert _http.fetch_bytes("https://h.example/") == b"not gzip"

    def test_proxied_path_inflates_too(self, monkeypatch):
        seen = {}

        def fake_open(req, timeout=None):
            seen["headers"] = {k.lower(): v for k, v in req.header_items()}
            return _UrllibResponse(body=gzip.compress(b"via proxy"),
                                   headers={"Content-Encoding": "gzip"})

        _fake_opener(monkeypatch, fake_open)
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        assert _http.fetch_bytes("https://h.example/") == b"via proxy"
        assert seen["headers"]["accept-encoding"] == "gzip"

    def test_same_host_reuses_the_connection(self, conns):
        conns.script = [_Response(), _Response(), _Response()]
        for path in ("/1", "/2", "/3"):
            _http.fetch_bytes(f"https://h.example{path}")
        assert len(conns.instances) == 1
        assert [r[1] for r in conns.instances[0].requests] == ["/1", "/2", "/3"]

    def test_hosts_and_schemes_get_their_own_connections(self, conns):
        conns.script = [_Response()] * 3
        _http.fetch_bytes("https://a.example/")
        _http.fetch_bytes("https://b.example:8443/")
        _http.fetch_bytes("http://a.example/")
        assert [(c.host, c.port) for c in conns.instances] == [
            ("a.example", None), ("b.example", 8443), ("a.example", None)]

    def test_threads_do_not_share_a_connection(self, conns):
        conns.script = [_Response()] * 2
        _http.fetch_bytes("https://h.example/")
        t = threading.Thread(target=_http.fetch_bytes, args=("https://h.example/",))
        t.start()
        t.join()
        assert len(conns.instances) == 2

    def test_timeout_refreshed_on_a_reused_socket(self, conns):
        conns.script = [_Response(), _Response()]
        _http.fetch_bytes("https://h.example/", timeout=3)
        _http.fetch_bytes("https://h.example/", timeout=15)
        conn = conns.instances[0]
        assert conn.timeout == 15
        assert conn.sock.timeouts == [15]

    def test_server_closed_idle_socket_retried_once(self, conns):
        conns.script = [_Response(body=b"first"),
                        http.client.RemoteDisconnected("gone"),
                        _Response(body=b"second")]
        assert _http.fetch_bytes("https://h.example/") == b"first"
        assert _http.fetch_bytes("https://h.example/") == b"second"
        first, second = conns.instances
        assert first.closed and len(second.requests) == 1

    def test_fresh_connection_failure_is_not_retried(self, conns):
        conns.script = [ConnectionResetError("reset")]
        with pytest.raises(ConnectionResetError):
            _http.fetch_bytes("https://h.example/")
        assert len(conns.instances) == 1
        assert conns.instances[0].closed

    def test_timeout_is_raised_and_the_connection_dropped(self, conns):
        conns.script = [TimeoutError("slow"), _Response()]
        with pytest.raises(TimeoutError):
            _http.fetch_bytes("https://h.example/")
        _http.fetch_bytes("https://h.example/")
        assert len(conns.instances) == 2  # not the poisoned one

    def test_non_2xx_raises_http_error_with_code(self, conns):
        conns.script = [_Response(404, b"nope", reason="Not Found")]
        with pytest.raises(_http.HTTPError) as info:
            _http.fetch_bytes("https://h.example/missing")
        assert info.value.code == 404
        assert isinstance(info.value, OSError)
        assert "404" in str(info.value)

    def test_redirect_is_followed(self, conns):
        conns.script = [
            _Response(302, b"", {"Location": "/moved"}, "Found"),
            _Response(301, b"", {"Location": "https://other.example/x"}),
            _Response(body=b"there"),
        ]
        assert _http.fetch_bytes("https://h.example/start") == b"there"
        assert conns.instances[0].requests[1][1] == "/moved"
        assert conns.instances[1].host == "other.example"

    def test_redirect_loop_gives_up(self, conns):
        conns.script = [_Response(302, b"", {"Location": "/again"})] * 10
        with pytest.raises(_http.HTTPError):
            _http.fetch_bytes("https://h.example/start")

    def test_file_url_reads_the_file(self, conns, tmp_path):
        target = tmp_path / "tile.png"
        target.write_bytes(b"\x89PNG")
        assert _http.fetch_bytes(target.as_uri()) == b"\x89PNG"
        with pytest.raises(FileNotFoundError):
            _http.fetch_bytes((tmp_path / "missing.png").as_uri())
        assert conns.instances == []

    def test_proxy_environment_takes_the_urllib_path(self, conns, monkeypatch):
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        seen = {}

        def fake(url, headers, timeout, limit):
            seen.update(url=url, headers=headers, timeout=timeout)
            return 200, "OK", {}, b"via proxy"

        monkeypatch.setattr(_http, "_request_urllib", fake)
        assert _http.fetch_bytes("https://h.example/", timeout=4) == b"via proxy"
        assert seen["timeout"] == 4 and "User-Agent" in seen["headers"]
        assert conns.instances == []

    def test_proxied_reads_the_environment(self, monkeypatch):
        for name in list(__import__("os").environ):
            if name.lower().endswith("_proxy"):
                monkeypatch.delenv(name)
        assert not _http._proxied()
        monkeypatch.setenv("no_proxy", "localhost")
        assert not _http._proxied()
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
        assert _http._proxied()

    def test_fetch_json_decodes(self, conns):
        conns.script = [_Response(body=b'{"a": [1, 2]}')]
        assert _http.fetch_json("https://h.example/j") == {"a": [1, 2]}


class TestRedirectCredentials:
    """Issue #121: credentials stay on the origin they were sent to."""

    @staticmethod
    def _run(monkeypatch, url, responses, headers, proxied=False):
        sent = []

        def request(url, headers, timeout, limit):
            sent.append((url, dict(headers)))
            status, location = responses[len(sent) - 1]
            return status, "Found", _Headers(
                {"Location": location} if location else {}), b""

        monkeypatch.setattr(_http, "_proxied", lambda: proxied)
        monkeypatch.setattr(_http, "_request", request)
        _http.fetch_bytes(url, headers=headers)
        return sent

    @staticmethod
    def _keys(headers):
        return {k.lower() for k in headers}

    @pytest.mark.parametrize("target", [
        "https://different.example/tides",       # host
        "https://tides.example:8443/tides",      # port
        "https://TIDES.example.evil/tides",      # a longer host
    ])
    @pytest.mark.parametrize("name", ["X-API-Key", "x-api-key",
                                      "Authorization", "authorization"])
    def test_cross_origin_redirect_drops_the_credential(self, monkeypatch,
                                                        target, name):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(302, target), (200, None)],
                         {name: "secret", "Accept": "application/json"})
        assert sent[1][0] == target
        assert name.lower() not in self._keys(sent[1][1])
        assert sent[1][1]["Accept"] == "application/json"
        assert sent[1][1]["User-Agent"].startswith("linecast/")
        assert sent[1][1]["Accept-Encoding"] == "gzip"

    def test_cross_scheme_upgrade_drops_the_credential(self, monkeypatch):
        sent = self._run(monkeypatch, "http://tides.example/v1",
                         [(301, "https://tides.example/v1"), (200, None)],
                         {"X-API-Key": "secret"})
        assert "x-api-key" not in self._keys(sent[1][1])

    def test_every_credential_header_is_dropped(self, monkeypatch):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(302, "https://other.example/"), (200, None)],
                         {"Authorization": "a", "Proxy-Authorization": "b",
                          "COOKIE": "c", "X-Api-Key": "d"})
        assert not self._keys(sent[1][1]) & _http._SENSITIVE_HEADERS

    def test_dropped_credentials_do_not_come_back(self, monkeypatch):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(302, "https://other.example/"),
                          (302, "https://tides.example/v2"), (200, None)],
                         {"X-API-Key": "secret"})
        assert sent[2][0] == "https://tides.example/v2"
        assert "x-api-key" not in self._keys(sent[2][1])

    @pytest.mark.parametrize("name", ["X-API-Key", "authorization"])
    def test_keyed_https_to_http_downgrade_raises(self, monkeypatch, name):
        with pytest.raises(_http.HTTPError) as info:
            self._run(monkeypatch, "https://tides.example/v1",
                      [(302, "http://tides.example/v1"), (200, None)],
                      {name: "secret"})
        assert info.value.code == 302
        assert "HTTPS to HTTP" in str(info.value)

    def test_unkeyed_https_to_http_downgrade_is_followed(self, monkeypatch):
        sent = self._run(monkeypatch, "https://tiles.example/1.png",
                         [(302, "http://tiles.example/1.png"), (200, None)],
                         {"Accept": "image/png"})
        assert sent[1] == ("http://tiles.example/1.png", sent[0][1])

    def test_downgrade_after_the_key_was_dropped_is_followed(self, monkeypatch):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(302, "https://cdn.example/v1"),
                          (302, "http://cdn.example/v1"), (200, None)],
                         {"X-API-Key": "secret"})
        assert sent[2][0] == "http://cdn.example/v1"

    @pytest.mark.parametrize("target", [
        "https://tides.example/v2",
        "https://TIDES.Example:443/v2",   # default port, other case
        "/v2",                            # relative
        "v2",
        "?page=2",
    ])
    def test_same_origin_redirect_keeps_the_credential(self, monkeypatch,
                                                       target):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(307, target), (200, None)],
                         {"X-API-Key": "secret"})
        assert sent[1][1]["X-API-Key"] == "secret"

    def test_protocol_relative_location_is_another_origin(self, monkeypatch):
        sent = self._run(monkeypatch, "https://tides.example/v1",
                         [(302, "//other.example/v1"), (200, None)],
                         {"X-API-Key": "secret"})
        assert sent[1][0] == "https://other.example/v1"
        assert "x-api-key" not in self._keys(sent[1][1])

    def test_proxied_path_drops_the_key_across_origins(self, monkeypatch):
        import urllib.error
        seen = []

        def fake_open(req, timeout=None):
            seen.append((req.full_url, {k.lower(): v
                                        for k, v in req.header_items()}))
            if len(seen) == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 302, "Found",
                    _Headers({"Location": "https://different.example/tides"}),
                    BytesIO(b""))
            return _UrllibResponse(body=b"{}")

        built = _fake_opener(monkeypatch, fake_open)
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        assert _http.fetch_bytes("https://original.example/tides",
                                 headers={"X-API-Key": "k"}) == b"{}"
        assert seen[0][1]["x-api-key"] == "k"
        assert seen[1][0] == "https://different.example/tides"
        assert "x-api-key" not in seen[1][1]
        assert "user-agent" in seen[1][1]
        # urllib must not follow redirects itself behind our back
        import urllib.request
        assert built and all(
            issubclass(h, urllib.request.HTTPRedirectHandler) for h in built)
        assert built[0]().redirect_request(None, None, 302, "Found", {},
                                           "https://x.example/") is None

    def test_proxied_path_refuses_a_keyed_downgrade(self, monkeypatch):
        import urllib.error

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 301, "Moved",
                _Headers({"Location": "http://original.example/tides"}),
                BytesIO(b""))

        _fake_opener(monkeypatch, fake_open)
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        with pytest.raises(_http.HTTPError):
            _http.fetch_bytes("https://original.example/tides",
                              headers={"Authorization": "Bearer k"})

    def test_proxied_path_refuses_a_file_redirect(self, monkeypatch):
        import urllib.error

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 302, "Found",
                _Headers({"Location": "file:///etc/passwd"}), BytesIO(b""))

        _fake_opener(monkeypatch, fake_open)
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        with pytest.raises(ValueError):
            _http.fetch_bytes("https://original.example/tides")

    def test_proxied_non_2xx_is_our_http_error(self, monkeypatch):
        import urllib.error

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found",
                                         _Headers(), BytesIO(b"nope"))

        _fake_opener(monkeypatch, fake_open)
        monkeypatch.setattr(_http, "_proxied", lambda: True)
        with pytest.raises(_http.HTTPError) as info:
            _http.fetch_bytes("https://h.example/missing")
        assert info.value.code == 404 and info.value.body == b"nope"


class TestFetchBytesCached:
    @pytest.mark.parametrize("stale", [None, b"previous complete tile"])
    def test_incomplete_gzip_never_replaces_the_cache(self, conns, tmp_path, stale):
        path = tmp_path / "t.png"
        if stale is not None:
            path.write_bytes(stale)
            __import__("os").utime(path, (0, 0))
        # The HTTP transfer is complete, but the gzip trailer is missing.
        body = gzip.compress(b"new tile")[:-8]
        headers = (f"Content-Length: {len(body)}\r\n"
                   "Content-Encoding: gzip").encode()
        conns.script = [_wire_response(body, headers)]

        assert _http.fetch_bytes_cached(path, 60, "https://h.example/") == stale
        if stale is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == stale
        assert conns.instances[0].closed

    @pytest.mark.parametrize("stale", [None, b"previous complete tile"])
    def test_truncated_response_never_replaces_the_cache(self, conns, tmp_path, stale):
        path = tmp_path / "t.png"
        if stale is not None:
            path.write_bytes(stale)
            __import__("os").utime(path, (0, 0))
        conns.script = [_wire_response(b"short", b"Content-Length: 10")]

        assert _http.fetch_bytes_cached(path, 60, "https://h.example/") == stale
        if stale is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == stale
        assert conns.instances[0].closed

    def test_fresh_cache_skips_the_network(self, conns, tmp_path):
        path = tmp_path / "t.png"
        path.write_bytes(b"cached")
        assert _http.fetch_bytes_cached(path, 60, "https://h.example/") == b"cached"
        assert conns.instances == []

    def test_expired_cache_is_refetched_and_rewritten(self, conns, tmp_path):
        path = tmp_path / "t.png"
        path.write_bytes(b"old")
        __import__("os").utime(path, (time.time() - 120, time.time() - 120))
        conns.script = [_Response(body=b"new")]
        assert _http.fetch_bytes_cached(path, 60, "https://h.example/") == b"new"
        assert path.read_bytes() == b"new"

    def test_none_max_age_never_expires(self, conns, tmp_path):
        path = tmp_path / "t.png"
        path.write_bytes(b"forever")
        __import__("os").utime(path, (0, 0))
        assert _http.fetch_bytes_cached(path, None, "https://h.example/") == b"forever"
        assert conns.instances == []

    def test_miss_fetches_and_creates_parent_dirs(self, conns, tmp_path):
        path = tmp_path / "deep" / "er" / "t.png"
        conns.script = [_Response(body=b"tile")]
        assert _http.fetch_bytes_cached(path, None, "https://h.example/") == b"tile"
        assert path.read_bytes() == b"tile"

    def test_failure_falls_back_to_stale_bytes(self, conns, tmp_path):
        path = tmp_path / "t.png"
        path.write_bytes(b"stale")
        __import__("os").utime(path, (0, 0))
        conns.script = [OSError("down")]
        assert _http.fetch_bytes_cached(path, 60, "https://h.example/") == b"stale"

    def test_failure_with_no_cache_is_none(self, conns, tmp_path):
        conns.script = [_Response(500, b"", reason="Server Error")]
        assert _http.fetch_bytes_cached(tmp_path / "t.png", 60,
                                        "https://h.example/") is None
        assert not (tmp_path / "t.png").exists()


class TestFetchJsonCached:
    def test_a_fresh_copy_that_passes_the_test_is_served(self, conns, tmp_path):
        path = tmp_path / "f.json"
        path.write_text('{"day": "today"}')
        got = _http.fetch_json_cached(path, 60, "https://h.example/",
                                      fresh=lambda d: d["day"] == "today")
        assert got == {"day": "today"}
        assert conns.instances == []

    def test_a_fresh_copy_that_fails_the_test_is_refetched(self, conns, tmp_path):
        path = tmp_path / "f.json"
        path.write_text('{"day": "tuesday"}')
        conns.script = [_Response(body=b'{"day": "today"}')]
        got = _http.fetch_json_cached(path, 60, "https://h.example/",
                                      fresh=lambda d: d["day"] == "today")
        assert got == {"day": "today"}
        assert path.read_text() == '{"day": "today"}'

    def test_a_copy_that_fails_the_test_still_stands_in_for_a_dead_network(
            self, conns, tmp_path):
        path = tmp_path / "f.json"
        path.write_text('{"day": "tuesday"}')
        conns.script = [OSError("down")]
        got = _http.fetch_json_cached(path, 60, "https://h.example/",
                                      fresh=lambda d: d["day"] == "today")
        assert got == {"day": "tuesday"}

    def test_without_a_test_age_alone_decides(self, conns, tmp_path):
        path = tmp_path / "f.json"
        path.write_text('{"day": "tuesday"}')
        assert _http.fetch_json_cached(path, 60, "https://h.example/") == {"day": "tuesday"}
        assert conns.instances == []


class TestVersion:
    def test_user_agent_is_cached(self):
        first = linecast.user_agent()
        assert first.startswith("linecast/")
        assert linecast.user_agent() is first
        assert linecast.USER_AGENT == first

    def test_version_action_prints_and_exits(self, capsys):
        parser = _runtime._base_parser("weather", "test")
        with pytest.raises(SystemExit) as info:
            parser.parse_args(["--version"])
        assert info.value.code == 0
        out = capsys.readouterr().out
        assert out.startswith("weather (linecast ")
        assert linecast.__version__ in out

    def test_help_does_not_import_metadata_or_urllib(self):
        # every command builds a parser; none of them should pay for the
        # version lookup or urllib.request unless a request is made
        for code in ("import linecast.weather.view, linecast._runtime; "
                     "linecast._runtime.weather_parser()",
                     "import linecast.radar.view",
                     "import linecast.maps.view",
                     "import linecast.sunshine.view",
                     "import linecast.moon.view",
                     "import linecast.tides.view"):
            out = subprocess.run(
                [sys.executable, "-X", "importtime", "-c", code],
                capture_output=True, text=True, cwd=_src).stderr
            assert "importlib.metadata" not in out, code
            assert "urllib.request" not in out, code


class TestBodyCap:
    """The streamed size limit: nothing past the cap is kept."""

    @pytest.mark.parametrize("size", [0, 5, _http._CHUNK + 5])
    def test_truncated_content_length_is_refused(self, size):
        body = b"x" * size
        response = _wire_response(body, f"Content-Length: {size + 10}".encode())
        with pytest.raises(http.client.IncompleteRead) as info:
            _http.read_limited(response, size + 100)
        assert info.value.partial == body
        assert info.value.expected == 10

    @pytest.mark.parametrize("body, headers, expected", [
        (b"", b"Content-Length: 0", b""),
        (b"complete", b"Content-Length: 8", b"complete"),
        (b"complete", b"Connection: close", b"complete"),
        (b"8\r\ncomplete\r\n0\r\n\r\n", b"Transfer-Encoding: chunked", b"complete"),
    ])
    def test_complete_wire_response_is_accepted(self, body, headers, expected):
        assert _http.read_limited(_wire_response(body, headers), 100) == expected

    def test_oversized_body_is_refused(self, conns):
        conns.script = [_Response(body=b"x" * 300)]
        with pytest.raises(ValueError):
            _http.fetch_bytes("https://h.example/", limit=100)

    def test_oversized_content_length_refused_before_reading(self, conns):
        class Loud(_Response):
            length = 10_000

            def read(self, n=-1):
                raise AssertionError("read despite oversized Content-Length")

        conns.script = [Loud(body=b"x")]
        with pytest.raises(ValueError):
            _http.fetch_bytes("https://h.example/", limit=100)

    def test_body_at_the_limit_is_allowed(self, conns):
        conns.script = [_Response(body=b"x" * 100)]
        assert _http.fetch_bytes("https://h.example/", limit=100) == b"x" * 100

    def test_gunzip_bomb_is_refused(self):
        bomb = gzip.compress(b"\0" * 10_000_000)
        with pytest.raises(ValueError):
            _http.gunzip_limited(bomb, 1_000_000)
        assert _http.gunzip_limited(gzip.compress(b"streets"), 100) == b"streets"


class TestGunzip:
    @pytest.mark.parametrize("parts", [(b"streets",), (b"str", b"eets"), (b"", b"")])
    def test_all_members_fit_at_the_exact_limit(self, parts):
        body = b"".join(gzip.compress(part) for part in parts)
        expected = b"".join(parts)
        assert _http.gunzip_limited(body, len(expected)) == expected

    @pytest.mark.parametrize("parts, limit", [
        ((b"streets",), 0),
        ((b"str", b"eets"), 6),
        ((b"streets", b"x"), 7),
    ])
    def test_limit_applies_to_the_whole_body(self, parts, limit):
        body = b"".join(gzip.compress(part) for part in parts)
        with pytest.raises(ValueError, match="exceeds cap"):
            _http.gunzip_limited(body, limit)

    @pytest.mark.parametrize("missing", [1, 8, 12])
    @pytest.mark.parametrize("prefix", [b"", gzip.compress(b"first member")],
                             ids=["first", "second"])
    def test_incomplete_member_is_refused(self, missing, prefix):
        body = prefix + gzip.compress(b"streets")[:-missing]
        with pytest.raises(ValueError):
            _http.gunzip_limited(body, 100)

    @pytest.mark.parametrize("offset", [-8, -4])
    def test_checksum_and_size_are_checked_even_at_the_limit(self, offset):
        body = bytearray(gzip.compress(b"streets"))
        body[offset] ^= 1
        with pytest.raises(ValueError):
            _http.gunzip_limited(bytes(body), 7)

    def test_negative_limit_is_refused(self):
        with pytest.raises(ValueError):
            _http.gunzip_limited(gzip.compress(b"streets"), -1)
