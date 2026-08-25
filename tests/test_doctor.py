"""linecast doctor: the report, its JSON form, and what it never shows.

The provider probes are stubbed -- the suite has no network -- and the
cache and settings paths are the private ones tests/conftest.py set.
"""

import importlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from conftest import readonly, unsearchable


def _doctor():
    # tests/test_oneline.py re-imports linecast mid-session; look the
    # module up per test rather than binding it at collection
    return importlib.import_module("linecast.doctor")


def _run(*args, monkeypatch):
    """(exit code, stdout, stderr) of `linecast doctor *args`."""
    cli = importlib.import_module("linecast.__main__")
    monkeypatch.setattr(sys, "argv", ["linecast", "doctor", *args])
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main()
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


SECTIONS = ("linecast", "paths", "terminal", "preferences", "environment", "providers")


@pytest.fixture
def no_probes(monkeypatch):
    """Every probe answers without a socket: the Open-Meteo hosts are
    up, everything else has timed out.  Returns the (name, url) list."""
    doctor = _doctor()

    def probe(url, timeout=doctor.PROBE_TIMEOUT):
        if "open-meteo" in url:
            return True, "ok (HTTP 404)"
        return False, "timed out"
    monkeypatch.setattr(doctor, "probe", probe)
    return doctor.providers()


class TestOffline:
    def test_every_section_is_there_and_nothing_is_probed(self, monkeypatch):
        doctor = _doctor()
        monkeypatch.setattr(doctor, "probe", lambda *a, **k: pytest.fail("probed"))
        code, out, err = _run("--offline", monkeypatch=monkeypatch)
        assert (code, err) == (0, "")
        for section in SECTIONS:
            assert f"\n{section}\n" in "\n" + out
        assert "skipped (--offline)" in out
        from linecast import __version__
        assert f"  version   {__version__}" in out
        assert "  cache     " in out and "writable" in out
        assert "settings  " in out and "not created yet" in out

    def test_saved_settings_are_described(self, monkeypatch):
        from linecast import _config
        _config.write_config({"units": "metric",
                              "location": {"lat": 43.68, "lng": -70.37,
                                           "label": "Westbrook, Maine", "country": "US"}})
        _, out, _ = _run("--offline", monkeypatch=monkeypatch)
        assert "(exists; location, units)" in out
        assert "  units     metric (config)" in out
        assert "  location  (set) (config)" in out
        assert "Westbrook" not in out and "43.6800" not in out

    def test_env_overrides_name_their_source(self, monkeypatch):
        monkeypatch.setenv("WEATHER_UNITS", "metric")
        monkeypatch.setenv("TIDES_UNITS", "imperial")
        monkeypatch.setenv("WEATHER_LOCATION", "1.5,2.5")
        monkeypatch.setenv("LINECAST_LANG", "fr")
        _, out, _ = _run("--offline", monkeypatch=monkeypatch)
        assert "  units     metric (WEATHER_UNITS); tides imperial (TIDES_UNITS)" in out
        assert "  location  (set) (WEATHER_LOCATION)" in out
        assert "  language  fr (LINECAST_LANG)" in out
        assert "24-hour (fr)" in out
        assert "  WEATHER_LOCATION=(set)" in out
        assert "1.5,2.5" not in out

    def test_location_is_masked_in_text_and_json_reports(self, monkeypatch):
        private = "My Home, 43.6770,-70.3712"
        monkeypatch.setenv("WEATHER_LOCATION", private)
        _, text, _ = _run("--offline", monkeypatch=monkeypatch)
        _, as_json, _ = _run("--offline", "--json", monkeypatch=monkeypatch)
        for report in (text, as_json):
            assert private not in report
            assert "43.6770" not in report
            assert "WEATHER_LOCATION" in report


class TestSecrets:
    def test_a_key_is_shown_as_set(self, monkeypatch):
        monkeypatch.setenv("LINECAST_TIDECHECK_KEY", "abc123secret")
        monkeypatch.setenv("LINECAST_SOME_TOKEN", "tok-xyz")
        monkeypatch.setenv("https_proxy", "http://user:pw@proxy.example:3128/?x=1")
        code, out, _ = _run("--offline", monkeypatch=monkeypatch)
        assert "  LINECAST_TIDECHECK_KEY=(set)" in out
        assert "  LINECAST_SOME_TOKEN=(set)" in out
        assert "  https_proxy=http://proxy.example:3128/?..." in out
        _, as_json, _ = _run("--offline", "--json", monkeypatch=monkeypatch)
        for text in (out, as_json):
            # the userinfo as it would leak, not the bare word "user":
            # the report prints paths, and a login name can contain it
            for leak in ("abc123secret", "tok-xyz", "user:pw@", "pw@", "x=1"):
                assert leak not in text

    def test_a_url_override_loses_its_userinfo_and_query(self, no_probes, monkeypatch):
        monkeypatch.setenv("LINECAST_LIBREWXR_URL", "https://alice:pw1@wxr.example/base?token=abc")
        monkeypatch.setenv("LINECAST_ELEVATION_URL", "https://bob:pw2@dem.example/tiles/")
        monkeypatch.setenv("LINECAST_TILE_SERVER", "https://carol:pw3@t.example/x?key=k")
        code, out, err = _run(monkeypatch=monkeypatch)
        _, as_json, _ = _run("--json", monkeypatch=monkeypatch)
        assert (code, err) == (0, "")
        for text in (out, as_json):
            assert "wxr.example" in text and "dem.example" in text and "t.example" in text
            for leak in ("alice:", "pw1", "bob:", "pw2", "carol:", "pw3", "token=abc", "key=k"):
                assert leak not in text
        assert "  LINECAST_LIBREWXR_URL=https://wxr.example/base?..." in out
        assert "  LINECAST_ELEVATION_URL=https://dem.example/tiles/" in out
        assert "  LINECAST_TILE_SERVER=https://t.example/x?..." in out
        hosts = {h["name"]: h for h in json.loads(as_json)["providers"]}
        assert hosts["LibreWXR radar and clouds"]["url"] == "https://wxr.example/"
        assert hosts["AWS terrain tiles"]["url"] == "https://dem.example/tiles/terrarium/0/0/0.png"

    def test_the_probe_gets_the_url_as_configured_and_records_it_redacted(self, monkeypatch):
        doctor = _doctor()
        probed = []

        def probe(url, timeout=doctor.PROBE_TIMEOUT):
            probed.append(url)
            return True, "ok"
        monkeypatch.setattr(doctor, "probe", probe)
        record, = doctor.probe_all([("x", "https://u:p@h.example/t/0.png?k=v")])
        assert probed == ["https://u:p@h.example/t/0.png?k=v"]
        assert record == {"name": "x", "host": "h.example", "url": "https://h.example/t/0.png?...",
                          "ok": True, "status": "ok"}

    def test_an_override_urlsplit_refuses_is_probed_and_reported_as_such(self, monkeypatch):
        monkeypatch.setenv("LINECAST_LIBREWXR_URL", "https://user:pw@[bad")
        hosts = {h["name"]: h for h in _doctor().probe_all(_doctor().providers())}
        record = hosts["LibreWXR radar and clouds"]
        assert (record["host"], record["url"]) == (None, "(unparseable URL)")
        assert record["ok"] is False and record["status"].startswith("bad url (")

    def test_a_proxy_urlsplit_refuses_does_not_end_the_report(self, monkeypatch):
        monkeypatch.setenv("http_proxy", "http://user:pw@[bad")
        code, out, err = _run("--offline", monkeypatch=monkeypatch)
        assert (code, err) == (0, "")
        assert "  http_proxy=(unparseable URL)" in out
        assert "pw@" not in out

    def test_unset_variables_are_not_listed(self, monkeypatch):
        monkeypatch.delenv("LINECAST_THEME", raising=False)
        _, out, _ = _run("--offline", monkeypatch=monkeypatch)
        assert "LINECAST_TIDECHECK_KEY" not in out
        assert "LINECAST_THEME=" not in out


class TestJson:
    def test_parses_with_the_expected_keys(self, monkeypatch):
        code, out, err = _run("--offline", "--json", monkeypatch=monkeypatch)
        assert (code, err) == (0, "")
        report = json.loads(out)
        assert list(report) == list(SECTIONS)
        assert set(report["linecast"]) == {
            "version", "python", "platform", "machine", "temporary_install"}
        assert set(report["paths"]) == {
            "settings_file", "settings_exists", "settings_keys", "cache_dir",
            "cache_exists", "cache_writable", "cache_writable_reason", "cache_files",
            "cache_bytes", "cache_count_complete", "cache_legacy_location"}
        assert set(report["terminal"]) == {
            "term", "colorterm", "color_mode", "columns", "lines", "stdout_tty",
            "icons", "theme", "clock", "lang"}
        assert set(report["preferences"]) == {
            "units", "units_source", "tides_units", "tides_units_source", "location",
            "location_source", "language", "language_source"}
        assert isinstance(report["environment"], dict)
        assert report["providers"] is None
        from linecast._paths import cache_root
        assert report["paths"]["cache_dir"] == str(cache_root())
        assert report["paths"]["cache_writable"] is True

    def test_providers_are_listed_when_probed(self, no_probes, monkeypatch):
        _, out, _ = _run("--json", monkeypatch=monkeypatch)
        hosts = json.loads(out)["providers"]
        assert [h["name"] for h in hosts] == [name for name, _ in no_probes]
        assert {h["status"] for h in hosts} == {"ok (HTTP 404)", "timed out",
                                                "not configured"}
        assert all(set(h) == {"name", "host", "url", "ok", "status"} for h in hosts)
        assert [h["ok"] for h in hosts if h["name"] == "TideCheck tides"] == [None]


class TestProviders:
    def test_each_host_reports_ok_or_the_failure(self, no_probes, monkeypatch):
        code, out, err = _run(monkeypatch=monkeypatch)
        assert (code, err) == (0, "")
        lines = out.split("\nproviders\n", 1)[1].splitlines()
        assert len(lines) == len(no_probes)
        up = [ln for ln in lines if ln.endswith("  ok (HTTP 404)")]
        down = [ln for ln in lines if ln.endswith("  timed out")]
        assert len(up) == 5 and all("open-meteo" in ln for ln in up)
        assert len(down) == len(lines) - 6   # every other host but TideCheck
        assert any("nominatim.openstreetmap.org" in ln for ln in down)

    def test_tidecheck_needs_a_key(self, no_probes, monkeypatch):
        _, out, _ = _run(monkeypatch=monkeypatch)
        assert "TideCheck tides" in out and "not configured" in out
        monkeypatch.setenv("LINECAST_TIDECHECK_KEY", "k")
        _, out, _ = _run(monkeypatch=monkeypatch)
        line = next(ln for ln in out.splitlines() if "TideCheck" in ln)
        assert "tidecheck.com" in line and "not configured" not in line

    def test_overrides_are_honoured(self, no_probes, monkeypatch):
        monkeypatch.setenv("LINECAST_LIBREWXR_URL", "https://wxr.example:8443/base")
        monkeypatch.setenv("LINECAST_VECTOR_TILES_URL", "https://tiles.example/planet.json")
        monkeypatch.setenv("LINECAST_ELEVATION_URL", "https://dem.example/tiles/")
        hosts = {h["name"]: h["url"] for h in _doctor().probe_all(_doctor().providers())}
        assert hosts["LibreWXR radar and clouds"] == "https://wxr.example:8443/"
        assert hosts["OpenFreeMap streets"] == "https://tiles.example/"
        assert hosts["AWS terrain tiles"] == "https://dem.example/tiles/terrarium/0/0/0.png"

    def test_a_hung_lookup_does_not_hold_the_report(self, monkeypatch):
        # the socket timeout never reaches getaddrinfo; the deadline does
        import threading
        import time
        doctor = _doctor()
        release = threading.Event()

        def stuck(url, timeout=doctor.PROBE_TIMEOUT):
            release.wait(5)
            return True, "ok"
        monkeypatch.setattr(doctor, "probe", stuck)
        monkeypatch.setattr(doctor, "_PROBE_GRACE", 0.1)
        started = time.monotonic()
        try:
            hosts = doctor.probe_all([("a", "https://a.example/"), ("none", None),
                                      ("b", "https://b.example/x?y=1")], timeout=0.2)
            elapsed = time.monotonic() - started
        finally:
            release.set()
        assert elapsed < 0.2 + 0.1 + 1
        assert [h["status"] for h in hosts] == ["timed out (dns)", "not configured",
                                                "timed out (dns)"]
        assert hosts[2] == {"name": "b", "host": "b.example", "url": "https://b.example/x?...",
                            "ok": False, "status": "timed out (dns)"}

    def test_probe_names_the_failure(self):
        # the socket is blocked by conftest: an OSError, not a traceback
        ok, status = _doctor().probe("https://api.example/", timeout=1)
        assert ok is False
        assert status.startswith("unreachable (")
        ok, status = _doctor().probe("ftp://api.example/", timeout=1)
        assert (ok, status[:8]) == (False, "bad url ")


class TestCacheDirectory:
    def test_the_writable_check_leaves_the_directory_clean(self, tmp_path):
        root = tmp_path / "cache"
        root.mkdir()
        (root / "keep.json").write_text("{}")
        assert _doctor().cache_writable(root) == (True, "")
        assert sorted(p.name for p in root.iterdir()) == ["keep.json"]

    def test_a_missing_directory_is_created_and_removed_again(self, tmp_path):
        root = tmp_path / "deeper" / "cache"
        assert _doctor().cache_writable(root) == (True, "")
        assert not root.exists()
        assert not root.parent.exists()

    def test_an_unwritable_cache_is_reported_not_fatal(self, tmp_path, monkeypatch):
        root = tmp_path / "readonly"
        root.mkdir()
        readonly(root)
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(root))
        try:
            code, out, err = _run("--offline", monkeypatch=monkeypatch)
            assert (code, err) == (0, "")
            assert (f"  cache     {root}  (exists; 0 files, 0 B; "
                    "NOT writable (Permission denied))") in out
            _, as_json, _ = _run("--offline", "--json", monkeypatch=monkeypatch)
            paths = json.loads(as_json)["paths"]
            assert paths["cache_writable"] is False
            assert paths["cache_writable_reason"] == "Permission denied"
        finally:
            root.chmod(0o755)

    def test_paths_under_an_unsearchable_parent_are_reported_not_fatal(
            self, tmp_path, monkeypatch):
        # Path.exists and Path.is_dir raise PermissionError here before
        # Python 3.14; the report must say "not writable", not die
        locked = tmp_path / "locked"
        locked.mkdir()
        unsearchable(locked)
        cache, config = locked / "cache", locked / "config"
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(cache))
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(config))
        try:
            code, out, err = _run("--offline", monkeypatch=monkeypatch)
            assert (code, err) == (0, "")
            assert (f"  cache     {cache}  (not created yet; "
                    "NOT writable (Permission denied))") in out
            assert f"  settings  {config / 'config.json'}  (not created yet)" in out
            _, as_json, _ = _run("--offline", "--json", monkeypatch=monkeypatch)
            paths = json.loads(as_json)["paths"]
            assert (paths["cache_exists"], paths["cache_writable"]) == (False, False)
            assert paths["cache_writable_reason"] == "Permission denied"
            assert paths["settings_exists"] is False
        finally:
            locked.chmod(0o755)

    def test_usage_counts_files_and_bytes(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "x.png").write_bytes(b"x" * 10)
        (tmp_path / "y.json").write_bytes(b"y" * 5)
        assert _doctor().cache_usage(tmp_path) == (2, 15, True)
        assert _doctor().cache_usage(tmp_path, limit=1) == (1, 10, False) or \
            _doctor().cache_usage(tmp_path, limit=1) == (1, 5, False)

    def test_the_macos_legacy_note(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        (home / ".cache" / "linecast").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.delenv("LINECAST_CACHE_DIR")
        monkeypatch.delenv("XDG_CACHE_HOME")
        monkeypatch.setattr(sys, "platform", "darwin")
        _, out, _ = _run("--offline", monkeypatch=monkeypatch)
        assert "the older location; ~/Library/Caches/linecast takes over" in out
        _, as_json, _ = _run("--offline", "--json", monkeypatch=monkeypatch)
        assert json.loads(as_json)["paths"]["cache_legacy_location"] is True


class TestFlags:
    def test_version_and_help(self, monkeypatch):
        from linecast import __version__
        code, out, err = _run("--version", monkeypatch=monkeypatch)
        assert (code, out, err) == (0, f"linecast doctor (linecast {__version__})\n", "")
        code, out, err = _run("--help", monkeypatch=monkeypatch)
        assert code == 0 and "--offline" in out and "--json" in out

    def test_the_dispatcher_lists_it(self, monkeypatch):
        cli = importlib.import_module("linecast.__main__")
        assert cli.COMMANDS["doctor"] == "linecast.doctor"
        assert "  linecast doctor " in cli.HELP
