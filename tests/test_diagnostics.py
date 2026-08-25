"""What --debug tells you and what it never tells you.

log_failure is the one line every absorbed failure goes through; it
names the provider, the operation, the host and the fallback, and
nothing else -- no path, no query string, no userinfo, no header.  With
--debug off it prints nothing at all.  redact_url is what the fetch
lines show instead of the URL.  The network is off (tests/conftest.py),
so any real fetch here fails at the socket, which is the failure the
sweep is meant to report.
"""

import json
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _config, _runtime
from linecast._http import fetch_json_cached, redact_url
from linecast._runtime import RuntimeConfig, log_failure


@pytest.fixture
def debug(monkeypatch):
    monkeypatch.setattr(_runtime, "_DEBUG", True)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(_runtime, "_DEBUG", False)


def _lines(capsys):
    return capsys.readouterr().err.splitlines()


class TestLogFailure:
    def test_the_house_line(self, debug, capsys):
        log_failure("tides/noaa", "y-range fetch", OSError("timed out"),
                    url="https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?x=1",
                    fallback="auto-scaled axis")
        assert _lines(capsys) == [
            "[linecast] tides/noaa: y-range fetch failed (api.tidesandcurrents.noaa.gov)"
            " -- OSError: timed out; auto-scaled axis"]

    def test_nothing_when_debug_is_off(self, quiet, capsys):
        log_failure("cache", "read of x.json", ValueError("bad"), url="https://h/x?q=1",
                    fallback="miss")
        assert capsys.readouterr() == ("", "")

    def test_only_the_host_of_the_url(self, debug, capsys):
        log_failure("http", "fetch", OSError("refused"),
                    url="https://user:secret@tiles.example.net:8443/a/b/c.png?key=abc#frag")
        line, = _lines(capsys)
        assert "(tiles.example.net)" in line
        for leak in ("user", "secret", "/a/b", "key=abc", "frag", "8443"):
            assert leak not in line

    def test_a_bare_host_or_a_file_name_stands_in_for_the_url(self, debug, capsys):
        log_failure("maps/clouds", "polar cap fetch", OSError("x"), url="api.open-meteo.com")
        log_failure("cache", "read", OSError("x"), url="forecast_abc.json")
        a, b = _lines(capsys)
        assert "(api.open-meteo.com)" in a
        assert "(forecast_abc.json)" in b

    def test_no_url_no_parenthesis(self, debug, capsys):
        log_failure("worker", "scene load", KeyError("time"), fallback="view stays empty")
        assert _lines(capsys) == [
            "[linecast] worker: scene load failed -- KeyError: 'time'; view stays empty"]

    def test_the_message_is_its_first_line_cut_at_120(self, debug, capsys):
        long = "x" * 300
        log_failure("png", "decode", ValueError(f"{long}\nsecond line with https://h/?k=v"))
        line, = _lines(capsys)
        assert "x" * 120 in line
        assert "x" * 121 not in line
        assert "second line" not in line
        assert "k=v" not in line

    def test_an_empty_message_leaves_just_the_type(self, debug, capsys):
        log_failure("http", "fetch", OSError(), url="h.example", fallback="none")
        assert _lines(capsys) == ["[linecast] http: fetch failed (h.example) -- OSError; none"]

    def test_the_unsupported_scheme_error_names_no_url(self):
        from linecast._http import fetch_bytes
        with pytest.raises(ValueError) as info:
            fetch_bytes("ftp://user:pw@host.example/secret/path?k=v")
        assert "host.example" in str(info.value)
        for leak in ("secret", "pw", "k=v"):
            assert leak not in str(info.value)


class TestRedactUrl:
    @pytest.mark.parametrize("url, shown", [
        ("https://api.open-meteo.com/v1/forecast?latitude=1&longitude=2",
         "https://api.open-meteo.com/v1/forecast?..."),
        ("https://h.example/a/b#section", "https://h.example/a/b"),
        ("https://user:pw@h.example:8443/t/1/2/3.pbf?key=abc",
         "https://h.example:8443/t/1/2/3.pbf?..."),
        ("https://h.example/", "https://h.example/"),
        ("/only/a/path?q=1", "/only/a/path?..."),
        ("file:///tmp/tile.png", "file:///tmp/tile.png"),
        ("not a url at all", "not a url at all"),
        ("http://[::1]:8080/x?y=1", "http://[::1]:8080/x?..."),
    ])
    def test_cases(self, url, shown):
        assert redact_url(url) == shown

    def test_the_fetch_line_is_redacted(self, debug, capsys):
        with pytest.raises(OSError):
            from linecast._http import fetch_bytes
            fetch_bytes("https://api.example/v1?lat=43.68&lng=-70.37")
        err = capsys.readouterr().err
        assert "[linecast] fetch https://api.example/v1?..." in err
        assert "43.68" not in err


class TestStartupLine:
    def test_debug_starts_with_where_things_live(self, capsys, monkeypatch):
        monkeypatch.setattr(_runtime, "_DEBUG", False)
        ns = _runtime.weather_parser().parse_args(["--debug", "--print"])
        RuntimeConfig.from_sources(ns)
        first = _lines(capsys)[0]
        from linecast import __version__
        from linecast._paths import cache_root
        assert first.startswith(f"[linecast] linecast {__version__}, python ")
        assert str(cache_root()) in first
        assert str(_config.config_file()) in first

    def test_nothing_without_debug(self, capsys, monkeypatch):
        monkeypatch.setattr(_runtime, "_DEBUG", False)
        RuntimeConfig.from_sources(_runtime.weather_parser().parse_args(["--print"]))
        assert capsys.readouterr().err == ""


class TestTheSweep:
    """A few of the sites, as the user would hit them."""

    def test_a_cached_fetch_reports_the_host_and_the_fallback(self, debug, capsys, tmp_path):
        out = fetch_json_cached(tmp_path / "none.json", 60,
                                "https://api.example/v1?lat=43.68&lng=-70.37",
                                fallback={"empty": True})
        assert out == {"empty": True}
        err = capsys.readouterr().err
        line = next(ln for ln in err.splitlines() if "fetch failed" in ln)
        assert line.startswith("[linecast] http: fetch failed (api.example) -- ")
        assert line.endswith("; fallback value")
        assert "43.68" not in err

    def test_a_stale_copy_is_named(self, debug, capsys, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"old": 1}))
        assert fetch_json_cached(path, 0, "https://api.example/v1?x=1") == {"old": 1}
        assert "; stale cache old.json" in capsys.readouterr().err

    def test_reverse_geocode_degrades_with_one_line(self, debug, capsys):
        from linecast._weather_sources import _reverse_geocode
        assert _reverse_geocode(12.3456, -65.4321, lang="xx") == ("", "", {})
        err = capsys.readouterr().err
        assert ("[linecast] location/geocoder: reverse geocode failed "
                "(nominatim.openstreetmap.org) -- OSError: ") in err
        assert err.rstrip().endswith("; unnamed location")
        assert "lat=" not in err

    def test_a_corrupt_settings_file_is_reported_once(self, debug, capsys):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        assert _config.read_config() == {}
        assert _lines(capsys) == [
            "[linecast] config: read of config.json failed -- JSONDecodeError: "
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
            "; defaults used"]

    def test_a_missing_settings_file_is_not_a_failure(self, debug, capsys):
        assert not _config.config_file().exists()
        assert _config.read_config() == {}
        assert capsys.readouterr().err == ""

    def test_quiet_without_debug(self, quiet, capsys, tmp_path):
        from linecast._weather_sources import _reverse_geocode
        _reverse_geocode(12.3456, -65.4321, lang="xx")
        fetch_json_cached(tmp_path / "none.json", 60, "https://api.example/v1")
        assert capsys.readouterr() == ("", "")
