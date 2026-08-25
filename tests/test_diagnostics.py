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

import importlib


def _mod(name):
    # tests/test_oneline.py re-imports linecast mid-session, so a module
    # bound at collection time can be a stale copy: look it up per test
    return importlib.import_module(f"linecast.{name}")


@pytest.fixture
def debug(monkeypatch):
    monkeypatch.setattr(_mod("_runtime"), "_DEBUG", True)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(_mod("_runtime"), "_DEBUG", False)


def log_failure(*args, **kwargs):
    return _mod("_runtime").log_failure(*args, **kwargs)


def redact_url(url):
    return _mod("_http").redact_url(url)


def fetch_json_cached(*args, **kwargs):
    return _mod("_http").fetch_json_cached(*args, **kwargs)


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

    def test_a_url_urlsplit_refuses_names_no_host_and_does_not_raise(self, debug, capsys):
        # an unbalanced IPv6 bracket makes urlsplit raise; this runs
        # inside except handlers in the tile pools and must not
        log_failure("http", "fetch", OSError("x"), url="http://user:pw@[bad/x?k=v",
                    fallback="none")
        assert _lines(capsys) == ["[linecast] http: fetch failed -- OSError: x; none"]

    def test_no_url_no_parenthesis(self, debug, capsys):
        log_failure("worker", "scene load", KeyError("time"), fallback="view stays empty")
        assert _lines(capsys) == [
            "[linecast] worker: scene load failed -- KeyError: 'time'; view stays empty"]

    def test_trace_follows_the_line_with_the_traceback(self, debug, capsys):
        try:
            raise KeyError("time")
        except KeyError as exc:
            log_failure("worker", "scene load", exc, fallback="view stays empty", trace=True)
        lines = _lines(capsys)
        assert lines[0] == (
            "[linecast] worker: scene load failed -- KeyError: 'time'; view stays empty")
        assert lines[1] == "Traceback (most recent call last):"
        assert lines[-1] == "KeyError: 'time'"
        # an exception that was never raised has no traceback to show
        log_failure("worker", "scene load", KeyError("time"), trace=True)
        assert len(_lines(capsys)) == 1

    def test_trace_prints_nothing_when_debug_is_off(self, quiet, capsys):
        try:
            raise KeyError("time")
        except KeyError as exc:
            log_failure("worker", "scene load", exc, trace=True)
        assert capsys.readouterr() == ("", "")

    def test_the_message_is_its_first_line_cut_at_120(self, debug, capsys):
        long = "x" * 300
        log_failure("png", "decode", ValueError(f"{long}\nsecond line with https://h/?k=v"))
        line, = _lines(capsys)
        assert "x" * 120 in line
        assert "x" * 121 not in line
        assert "second line" not in line
        assert "k=v" not in line

    def test_a_url_in_the_exception_message_is_redacted(self, debug, capsys):
        private = "https://alice:secret@example.test/private?token=abc"
        log_failure("http", "fetch", OSError(f"request failed for {private}"),
                    fallback="none")
        line, = _lines(capsys)
        assert "https://example.test/private?..." in line
        for leak in ("alice", "secret", "token=abc"):
            assert leak not in line

    def test_a_url_in_a_traceback_is_redacted(self, debug, capsys):
        private = "https://alice:secret@example.test/private?token=abc"
        try:
            raise OSError(f"request failed for {private}")
        except OSError as exc:
            log_failure("worker", "scene load", exc, trace=True)
        trace = capsys.readouterr().err
        assert "https://example.test/private?..." in trace
        for leak in ("alice", "secret", "token=abc"):
            assert leak not in trace

    def test_an_empty_message_leaves_just_the_type(self, debug, capsys):
        log_failure("http", "fetch", OSError(), url="h.example", fallback="none")
        assert _lines(capsys) == ["[linecast] http: fetch failed (h.example) -- OSError; none"]

    def test_the_unsupported_scheme_error_names_no_url(self):
        fetch_bytes = _mod("_http").fetch_bytes
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
        ("http://user:pw@[bad/x?k=v", "(unparseable URL)"),  # urlsplit refuses it
        ("//[bad", "(unparseable URL)"),
    ])
    def test_cases(self, url, shown):
        assert redact_url(url) == shown

    def test_the_fetch_line_is_redacted(self, debug, capsys):
        with pytest.raises(OSError):
            _mod("_http").fetch_bytes("https://api.example/v1?lat=43.68&lng=-70.37")
        err = capsys.readouterr().err
        assert "[linecast] fetch https://api.example/v1?..." in err
        assert "43.68" not in err


class TestStartupLine:
    def test_debug_starts_with_where_things_live(self, quiet, capsys):
        rt = _mod("_runtime")
        rt.RuntimeConfig.from_sources(rt.weather_parser().parse_args(["--debug", "--print"]))
        first = _lines(capsys)[0]
        from linecast import __version__
        assert first.startswith(f"[linecast] linecast {__version__}, python ")
        assert str(_mod("_paths").cache_root()) in first
        assert str(_mod("_config").config_file()) in first

    def test_nothing_without_debug(self, quiet, capsys):
        rt = _mod("_runtime")
        rt.RuntimeConfig.from_sources(rt.weather_parser().parse_args(["--print"]))
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
        _reverse_geocode = _mod("_weather_sources")._reverse_geocode
        assert _reverse_geocode(12.3456, -65.4321, lang="xx") == ("", "", {})
        err = capsys.readouterr().err
        assert ("[linecast] location/geocoder: reverse geocode failed "
                "(nominatim.openstreetmap.org) -- OSError: ") in err
        assert err.rstrip().endswith("; unnamed location")
        assert "lat=" not in err

    def test_a_corrupt_settings_file_is_reported_once(self, debug, capsys):
        _config = _mod("_config")
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        assert _config.read_config() == {}
        assert _lines(capsys) == [
            "[linecast] config: read of config.json failed -- JSONDecodeError: "
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
            "; defaults used"]

    def test_a_missing_settings_file_is_not_a_failure(self, debug, capsys):
        _config = _mod("_config")
        assert not _config.config_file().exists()
        assert _config.read_config() == {}
        assert capsys.readouterr().err == ""

    def test_quiet_without_debug(self, quiet, capsys, tmp_path):
        _mod("_weather_sources")._reverse_geocode(12.3456, -65.4321, lang="xx")
        fetch_json_cached(tmp_path / "none.json", 60, "https://api.example/v1")
        assert capsys.readouterr() == ("", "")


# ---------------------------------------------------------------------------
# Workers that die under a live view
# ---------------------------------------------------------------------------
def _die_in_a_thread(name="prefetch"):
    import threading

    def boom():
        raise ZeroDivisionError("division by zero")
    t = threading.Thread(target=boom, name=name)
    t.start()
    t.join()


class TestWorkerWatch:
    def test_one_line_after_the_loop_without_debug(self, quiet, capsys):
        import threading
        before = threading.excepthook
        watch = _mod("_live").WorkerWatch()
        watch.install()
        _die_in_a_thread()
        watch.uninstall()
        assert threading.excepthook is before
        assert capsys.readouterr().err == ""   # nothing while the screen is up
        watch.report()
        assert capsys.readouterr().err == (
            "linecast: a background task failed; run with --debug for details\n")

    def test_debug_logs_at_once_and_prints_the_traceback_after(self, debug, capsys):
        watch = _mod("_live").WorkerWatch()
        watch.install()
        _die_in_a_thread("tiles-3")
        watch.uninstall()
        assert capsys.readouterr().err == (
            "[linecast] worker: tiles-3 failed -- ZeroDivisionError: division by zero"
            "; thread ended\n")
        watch.report()
        err = capsys.readouterr().err
        assert err.startswith("linecast: background task tiles-3 failed:\nTraceback")
        assert "ZeroDivisionError: division by zero" in err
        assert watch.failures[0][:3] == ("tiles-3", "ZeroDivisionError", "division by zero")

    def test_nothing_to_report_when_nothing_died(self, quiet, capsys):
        watch = _mod("_live").WorkerWatch()
        watch.install()
        watch.uninstall()
        watch.report()
        assert capsys.readouterr().err == ""


@pytest.fixture
def fake_tty(monkeypatch):
    """Enough of a terminal for live_loop to start: a pipe for stdin
    and termios calls that do nothing."""
    import os
    import termios
    import tty
    r, w = os.pipe()
    stdin = os.fdopen(r, "rb", buffering=0)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [0, 0, 0, 0, 0, 0, []])
    monkeypatch.setattr(termios, "tcsetattr", lambda *args: None)
    monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
    monkeypatch.setenv("LINECAST_THEME_POLL", "0")
    monkeypatch.setenv("LINECAST_THEME_WATCH", "")
    yield
    stdin.close()
    os.close(w)


class TestLiveLoopReportsDeadWorkers:
    def test_the_notice_lands_after_the_screen_is_restored(
            self, quiet, fake_tty, capsys, monkeypatch):
        import threading
        live = _mod("_live")
        before = threading.excepthook
        seen = []
        on_screen = []   # what stdout held at the moment the notice was written

        def render(offset_minutes=0, **frame):
            _die_in_a_thread("worker-1")
            seen.append(threading.excepthook is not before)
            raise KeyboardInterrupt   # quit, as q would

        report = live.WorkerWatch.report

        def report_and_snapshot(self, stream=None):
            on_screen.append(capsys.readouterr().out)
            return report(self, stream)
        monkeypatch.setattr(live.WorkerWatch, "report", report_and_snapshot)

        live.live_loop(render, interval=5)
        out, err = capsys.readouterr()
        assert seen == [True]                    # the hook was ours while it ran
        assert threading.excepthook is before    # and is gone now
        assert len(on_screen) == 1
        assert on_screen[0].endswith("\033[?25h\033[?1049l")  # the screen came back first
        assert out == ""                                      # and nothing after
        assert err == "linecast: a background task failed; run with --debug for details\n"

    def test_a_clean_session_says_nothing(self, quiet, fake_tty, capsys):
        live = _mod("_live")

        def render(offset_minutes=0, **frame):
            raise KeyboardInterrupt

        live.live_loop(render, interval=5)
        assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Worker failures outside the live loop
# ---------------------------------------------------------------------------
def _run_main(module, argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as info:
        module.main()
    return info.value.code


class TestWeatherFetchThread:
    @pytest.fixture
    def stubs(self, monkeypatch):
        weather = _mod("weather")
        monkeypatch.setattr(weather, "_reverse_geocode", lambda lat, lng: ("Here", "US", {}))
        monkeypatch.setattr(weather, "fetch_aqi", lambda lat, lng: None)
        monkeypatch.setattr(weather, "fetch_historical", lambda *a, **kw: None)
        monkeypatch.setattr(weather, "fetch_alerts", lambda *a, **kw: [])

        def broken(lat, lng, runtime):
            raise RuntimeError("boom")
        monkeypatch.setattr(weather, "fetch_forecast", broken)
        return weather

    def test_degrades_to_the_no_data_exit(self, quiet, stubs, monkeypatch, capsys):
        code = _run_main(stubs, ["weather", "--print", "--location", "43.68,-70.37"],
                         monkeypatch)
        out, err = capsys.readouterr()
        assert code == 1
        assert err == "Could not fetch weather data.\n"
        assert "Traceback" not in out + err

    def test_debug_names_the_failure_and_shows_the_traceback(
            self, quiet, stubs, monkeypatch, capsys):
        _run_main(stubs, ["weather", "--print", "--debug", "--location", "43.68,-70.37"],
                  monkeypatch)
        err = capsys.readouterr().err
        line = ("[linecast] worker: weather fetch failed -- RuntimeError: boom; "
                "the data in hand\n")
        assert line in err
        after = err.split(line, 1)[1]
        assert after.startswith("Traceback (most recent call last):\n")
        assert "RuntimeError: boom\n" in after
        assert err.endswith("Could not fetch weather data.\n")


class TestTidesPool:
    def test_settled_returns_none_with_one_line_and_the_traceback(self, debug, capsys):
        from concurrent.futures import Future
        tides = _mod("tides")
        future = Future()
        try:
            raise KeyError("v")
        except KeyError as exc:
            future.set_exception(exc)
        assert tides._settled(future, "tides/noaa", "y-range", "auto-scaled axis") is None
        lines = _lines(capsys)
        assert lines[0] == (
            "[linecast] tides/noaa: y-range failed -- KeyError: 'v'; auto-scaled axis")
        assert lines[1] == "Traceback (most recent call last):"
        done = Future()
        done.set_result((1.0, 2.0))
        assert tides._settled(done, "tides/noaa", "y-range", "auto-scaled axis") == (1.0, 2.0)
        assert capsys.readouterr().err == ""

    def test_provider_tags(self):
        tides = _mod("tides")
        assert tides._provider_tag(tides.NOAA) == "tides/noaa"
        assert tides._provider_tag(tides.CHS) == "tides/chs"
        assert tides._provider_tag(tides.OPENMETEO) == "tides/open-meteo"

    def test_a_provider_that_raises_does_not_take_the_command_down(
            self, quiet, monkeypatch, capsys):
        tides = _mod("tides")
        monkeypatch.setattr(tides.NOAA, "station_metadata", lambda station_id: None)

        def broken(*args):
            raise KeyError("predictions")
        monkeypatch.setattr(tides.NOAA, "y_range", broken)
        monkeypatch.setattr(tides.NOAA, "tides_range", lambda *args: [])
        code = _run_main(tides, ["tides", "--print", "--station", "8418150"], monkeypatch)
        out, err = capsys.readouterr()
        assert code == 1
        assert err == "Could not fetch tide data for station 8418150.\n"
        assert "Traceback" not in out + err

    def test_debug_names_the_provider_request_and_shows_the_traceback(
            self, quiet, monkeypatch, capsys):
        tides = _mod("tides")
        monkeypatch.setattr(tides.NOAA, "station_metadata", lambda station_id: None)

        def broken(*args):
            raise KeyError("predictions")
        monkeypatch.setattr(tides.NOAA, "y_range", broken)
        monkeypatch.setattr(tides.NOAA, "tides_range", lambda *args: [])
        _run_main(tides, ["tides", "--print", "--debug", "--station", "8418150"],
                  monkeypatch)
        err = capsys.readouterr().err
        line = ("[linecast] tides/noaa: y-range failed -- KeyError: 'predictions'; "
                "auto-scaled axis\n")
        assert line in err
        # the other pool threads log their own fetch lines meanwhile, so
        # the traceback is looked for after the line, not right after it
        after = err.split(line, 1)[1]
        assert "Traceback (most recent call last):\n" in after
        assert "KeyError: 'predictions'\n" in after
        assert "in broken\n" in after   # the frame that raised, which the line cannot name
