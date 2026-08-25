"""Where the cache and the config live, and what a cache that cannot be
written costs: nothing the user can see.

Also checks that tests/conftest.py did its job: this test, like every
other, runs in a private home with no units or location saved and no
network.
"""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import readonly

from linecast import _cache, _config, _http, _location, _paths, _runtime, _weather_sources
from linecast import location, units
from linecast._paths import cache_dir, cache_root, config_root


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home of our own, so the darwin fallback rules can be exercised."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))
    return path


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


class TestCacheRoot:
    def test_override_is_used_verbatim(self, tmp_path):
        assert cache_root({"LINECAST_CACHE_DIR": str(tmp_path)}) == tmp_path

    def test_override_expands_tilde(self):
        expected = Path(os.environ["HOME"]) / "elsewhere"
        assert cache_root({"LINECAST_CACHE_DIR": "~/elsewhere"}) == expected

    def test_override_beats_xdg(self, tmp_path):
        env = {"LINECAST_CACHE_DIR": str(tmp_path / "a"),
               "XDG_CACHE_HOME": str(tmp_path / "b")}
        assert cache_root(env) == tmp_path / "a"

    def test_blank_override_counts_as_unset(self, tmp_path):
        env = {"LINECAST_CACHE_DIR": "  ", "XDG_CACHE_HOME": str(tmp_path)}
        assert cache_root(env) == tmp_path / "linecast"

    def test_xdg_gets_the_linecast_suffix(self, tmp_path):
        assert cache_root({"XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "linecast"

    def test_relative_xdg_is_ignored(self, home, linux):
        assert cache_root({"XDG_CACHE_HOME": "relative/cache"}) == home / ".cache" / "linecast"

    def test_default_is_dot_cache(self, home, linux):
        assert cache_root({}) == home / ".cache" / "linecast"

    def test_reads_the_environment_at_call_time(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path / "one"))
        assert cache_root() == tmp_path / "one"
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path / "two"))
        assert cache_root() == tmp_path / "two"


class TestDarwin:
    def test_cache_under_library(self, home, darwin):
        assert cache_root({}) == home / "Library" / "Caches" / "linecast"

    def test_legacy_cache_stays_in_use(self, home, darwin):
        legacy = home / ".cache" / "linecast"
        legacy.mkdir(parents=True)
        assert cache_root({}) == legacy

    def test_native_wins_once_it_exists(self, home, darwin):
        (home / ".cache" / "linecast").mkdir(parents=True)
        native = home / "Library" / "Caches" / "linecast"
        native.mkdir(parents=True)
        assert cache_root({}) == native

    def test_override_and_xdg_still_win(self, home, darwin, tmp_path):
        assert cache_root({"LINECAST_CACHE_DIR": str(tmp_path)}) == tmp_path
        assert cache_root({"XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "linecast"

    def test_config_stays_under_dot_config(self, home, darwin):
        assert config_root({}) == home / ".config" / "linecast"


class TestConfigRoot:
    def test_override_is_used_verbatim(self, tmp_path):
        assert config_root({"LINECAST_CONFIG_DIR": str(tmp_path)}) == tmp_path

    def test_override_beats_xdg(self, tmp_path):
        env = {"LINECAST_CONFIG_DIR": str(tmp_path / "a"),
               "XDG_CONFIG_HOME": str(tmp_path / "b")}
        assert config_root(env) == tmp_path / "a"

    def test_xdg_gets_the_linecast_suffix(self, tmp_path):
        assert config_root({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "linecast"

    def test_relative_xdg_is_ignored(self, home, linux):
        assert config_root({"XDG_CONFIG_HOME": "rel"}) == home / ".config" / "linecast"

    def test_default_is_dot_config(self, home, linux):
        assert config_root({}) == home / ".config" / "linecast"

    def test_config_file_sits_in_the_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        assert _config.config_file() == tmp_path / "config.json"


class TestCacheDir:
    def test_joins_under_the_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
        assert cache_dir() == tmp_path
        assert cache_dir("maps", "tile.png") == tmp_path / "maps" / "tile.png"

    def test_creates_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path / "fresh"))
        cache_dir("maps", "tile.png")
        assert not (tmp_path / "fresh").exists()


# ---------------------------------------------------------------------------
# A cache that cannot be written
# ---------------------------------------------------------------------------
@pytest.fixture
def readonly_cache(tmp_path, monkeypatch):
    root = tmp_path / "ro-cache"
    root.mkdir()
    readonly(root)
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(root))
    try:
        yield root
    finally:
        root.chmod(0o755)


@pytest.fixture
def readonly_config(tmp_path, monkeypatch):
    root = tmp_path / "ro-config"
    root.mkdir()
    readonly(root)
    monkeypatch.setenv("LINECAST_CONFIG_DIR", str(root))
    try:
        yield root
    finally:
        root.chmod(0o755)


class TestUnwritableCache:
    def test_write_cache_is_a_quiet_no_op(self, readonly_cache):
        _cache.write_cache(cache_dir("weather", "x.json"), {"a": 1})  # mkdir refused
        _cache.write_cache(cache_dir("x.json"), {"a": 1})  # the write itself refused
        assert list(readonly_cache.iterdir()) == []

    def test_fetch_json_cached_still_answers(self, readonly_cache, monkeypatch):
        monkeypatch.setattr(_http, "fetch_json",
                            lambda url, headers=None, timeout=10: {"fresh": True})
        got = _http.fetch_json_cached(cache_dir("weather", "x.json"), 60, "https://x")
        assert got == {"fresh": True}

    def test_fetch_bytes_cached_still_answers(self, readonly_cache, monkeypatch):
        monkeypatch.setattr(_http, "fetch_bytes",
                            lambda url, headers=None, timeout=10: b"png")
        got = _http.fetch_bytes_cached(cache_dir("maps", "t.png"), None, "https://x")
        assert got == b"png"

    def test_ip_geolocation_still_answers(self, readonly_cache, monkeypatch):
        monkeypatch.setattr(_location, "saved_location", lambda: None)
        monkeypatch.setattr(_location, "fetch_json",
                            lambda url, headers=None, timeout=10:
                            {"loc": "43.7,-70.3", "country": "US"})
        assert _location.get_location() == (43.7, -70.3, "US")

    def test_reverse_geocode_still_answers(self, readonly_cache, monkeypatch):
        payload = {"address": {"city": "Westbrook", "state": "Maine",
                               "country_code": "us"}}
        monkeypatch.setattr(_weather_sources, "fetch_json",
                            lambda url, timeout=10: payload)
        name, country, addr = _weather_sources._reverse_geocode(43.7, -70.3)
        assert (name, country) == ("Westbrook, Maine", "US")
        assert addr == payload["address"]

    def test_nws_alerts_still_answer(self, readonly_cache, monkeypatch):
        fixture = Path(__file__).parent / "fixtures" / "nws_alerts_with_test.json"
        payload = json.loads(fixture.read_text())
        monkeypatch.setattr(_http, "fetch_json",
                            lambda url, headers=None, timeout=10: payload)
        alerts = _weather_sources._fetch_alerts_nws(40.7, -74.0)
        assert [a["event"] for a in alerts] == ["Heat Advisory"]


class TestUnreadableCache:
    def test_a_directory_where_a_file_should_be_reads_as_absent(self, tmp_path):
        (tmp_path / "x.json").mkdir()
        assert _cache.read_cache(tmp_path / "x.json", 60) is None
        assert _cache.read_stale(tmp_path / "x.json") is None

    def test_a_file_that_is_not_text_reads_as_absent(self, tmp_path):
        path = tmp_path / "x.json"
        path.write_bytes(b"\xff\xfe\x00 not json")
        assert _cache.read_cache(path, 60) is None
        assert _cache.read_stale(path) is None

    def test_an_unreadable_file_reads_as_absent(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root is not refused by file modes")
        path = tmp_path / "x.json"
        path.write_text(json.dumps({"a": 1}))
        path.chmod(0)
        if os.access(path, os.R_OK):
            path.chmod(0o644)
            pytest.skip("chmod does not deny reads on this filesystem")
        try:
            assert _cache.read_cache(path, 60) is None
            assert _cache.read_stale(path) is None
        finally:
            path.chmod(0o644)


class TestUnwritableConfig:
    def test_units_command_ends_with_one_line(self, readonly_config):
        with pytest.raises(SystemExit) as exc:
            units._cmd_set("metric")
        assert str(exc.value.code).startswith("Could not save settings to ")
        assert "\n" not in str(exc.value.code)

    def test_location_command_ends_with_one_line(self, readonly_config, monkeypatch):
        monkeypatch.setattr(_weather_sources, "_reverse_geocode",
                            lambda lat, lng: ("Westbrook", "US", {}))
        with pytest.raises(SystemExit) as exc:
            location._cmd_set("43.7,-70.3")
        assert str(exc.value.code).startswith("Could not save settings to ")

    def test_the_installed_command_prints_no_traceback(self, readonly_config):
        proc = subprocess.run(
            [sys.executable, "-m", "linecast.units", "metric"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 1
        assert "Traceback" not in proc.stderr
        assert proc.stderr.strip().startswith("Could not save settings to ")
        assert len(proc.stderr.strip().splitlines()) == 1


# ---------------------------------------------------------------------------
# conftest.py did its job
# ---------------------------------------------------------------------------
class TestPrivateHome:
    def test_nothing_is_saved(self):
        assert _runtime.units_pref() is None
        assert _config.saved_units() is None
        assert _config.saved_location() is None

    def test_nothing_leaks_from_the_shell(self):
        for name in ("WEATHER_UNITS", "LINECAST_TEMP", "LINECAST_LANG", "NO_COLOR"):
            assert name not in os.environ

    def test_home_is_private(self):
        import pwd
        real = Path(pwd.getpwuid(os.getuid()).pw_dir)
        assert Path.home() != real
        assert real not in Path.home().parents
        assert real not in _paths.cache_root().parents
        assert real not in _paths.config_root().parents

    def test_home_survives_a_cleared_environment(self, monkeypatch):
        import pwd
        private = Path.home()
        for name in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                     "LINECAST_CACHE_DIR", "LINECAST_CONFIG_DIR"):
            monkeypatch.delenv(name, raising=False)
        assert Path.home() == private
        assert Path(pwd.getpwuid(os.getuid()).pw_dir) not in _paths.cache_root().parents

    def test_network_is_blocked(self):
        with pytest.raises(OSError, match="network blocked"):
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        with pytest.raises(OSError, match="network blocked"):
            _http.fetch_bytes("https://example.invalid/", timeout=1)
