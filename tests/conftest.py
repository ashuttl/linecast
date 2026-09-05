"""Keep the suite in a private home, with the network switched off.

Everything here applies to unittest.TestCase files and pytest-style
files alike (pytest runs autouse fixtures for both).

The environment is set at module level, before any test module is
collected, because the test modules import linecast at collection time
and tests/test_oneline.py re-imports it mid-session: an environment
variable is the one thing that survives both. The cache directory is
shared by the whole session on purpose, so the basemap marshal (about
7 MB) is built once rather than once per test; the config directory is
fresh for every test, so a saved location or units can never leak
from one test into the next.

A test that genuinely needs the network or the real home marks itself
@pytest.mark.integration; see pyproject.toml.
"""

import http.client
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

# The home this user actually has, taken before the private one is
# announced: Windows has no pwd module to ask later.
REAL_HOME = Path.home()

_SESSION = tempfile.TemporaryDirectory(prefix="linecast-tests-")
SESSION_ROOT = Path(_SESSION.name)
HOME = SESSION_ROOT / "home"
CACHE_HOME = SESSION_ROOT / "cache"
CONFIG_HOME = SESSION_ROOT / "config"
for _dir in (HOME, CACHE_HOME, CONFIG_HOME):
    _dir.mkdir()

# The session-wide values: LINECAST_CONFIG_DIR is replaced per test.
SESSION_ENV = {
    "HOME": str(HOME),
    "XDG_CACHE_HOME": str(CACHE_HOME),
    "XDG_CONFIG_HOME": str(CONFIG_HOME),
    "LINECAST_CACHE_DIR": str(CACHE_HOME / "linecast"),
    "LINECAST_CONFIG_DIR": str(CONFIG_HOME / "linecast"),
}
if sys.platform == "win32":
    # expanduser reads USERPROFILE here, never HOME.
    SESSION_ENV["USERPROFILE"] = str(HOME)
os.environ.update(SESSION_ENV)

# Every variable linecast reads that would change what a test sees.
SCRUBBED = (
    "WEATHER_UNITS", "TIDES_UNITS", "LINECAST_UNITS", "LINECAST_CLOCK",
    "WEATHER_LOCATION", "WEATHER_NO_SHADING",
    "TIDE_STATION", "LINECAST_LANG", "LINECAST_ICONS", "LINECAST_TEMP",
    # the locale decides the language when nothing else does
    "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG",
    "LINECAST_TIDECHECK_KEY", "LINECAST_RADAR_THEME", "LINECAST_RADAR_LAYERS",
    "LINECAST_RADAR_LAYER", "LINECAST_THEME_WATCH", "LINECAST_THEME_POLL",
    "LINECAST_THEME_TIMEOUT_MS", "LINECAST_LIBREWXR_URL",
    "LINECAST_ELEVATION_URL", "LINECAST_BUILTUP_URL",
    "LINECAST_VECTOR_TILES_URL", "LINECAST_SUNSHINE_YEAR_PALETTE",
    "LINECAST_COLOR", "NO_COLOR", "CLICOLOR",
    "CLICOLOR_FORCE", "COLUMNS", "LINES",
    # icon-set detection: a dev running tests inside WezTerm or kitty
    # must see the same "plain" default CI sees
    "TERM_PROGRAM", "KITTY_WINDOW_ID",
)
for _name in SCRUBBED:
    os.environ.pop(_name, None)


def _proxy_names():
    """Every *_proxy variable, whatever its case: _http._proxied() sends
    every fetch down urllib's path when one is set, which changes what
    a failed fetch raises. A test that wants a proxy sets one itself."""
    return [name for name in os.environ if name.lower().endswith("_proxy")]


for _name in _proxy_names():
    del os.environ[_name]

# LINECAST_THEME is scrubbed here and not per test because _theme reads
# it once, at import. Unset, with no terminal to probe, _theme settles
# on the fallback palette with theme_legacy_mode False: the mode the
# stored snapshots were rendered in and the one tests/test_theme_reload.py
# needs. A value inherited from the shell (off, classic) would fix the
# other palette for the whole session.
os.environ.pop("LINECAST_THEME", None)


@pytest.fixture(autouse=True)
def _private_home(monkeypatch, tmp_path):
    """Re-assert the private home for every test.

    Some tests clear os.environ wholesale; with HOME gone, Path.home()
    would fall back to the passwd entry, which is the real home. Patching
    Path.home closes that door too.
    """
    for name, value in SESSION_ENV.items():
        monkeypatch.setenv(name, value)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("LINECAST_CONFIG_DIR", str(config_dir))
    for name in (*SCRUBBED, *_proxy_names()):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: HOME))


# ---------------------------------------------------------------------------
# Directories this process may not write or search
# ---------------------------------------------------------------------------
def _restrict(path, mode, access, what):
    if sys.platform == "win32":
        pytest.skip("directory modes do not deny access on Windows")
    if os.geteuid() == 0:
        pytest.skip("root is not refused by directory modes")
    path.chmod(mode)
    if os.access(path, access):
        path.chmod(0o755)
        pytest.skip(f"chmod does not deny {what} on this filesystem")


def readonly(path):
    """Make `path` read-only, or skip when this process would not notice
    (root, or a filesystem that ignores directory modes). The caller
    puts the mode back so tmp_path can be cleaned up."""
    _restrict(path, 0o555, os.W_OK, "writes")


def unsearchable(path):
    """Take every permission off `path`, so a stat of anything below it
    is refused, or skip when this process would not notice."""
    _restrict(path, 0o000, os.X_OK, "searches")


def _blocked(*args, **kwargs):
    raise OSError("network blocked by tests/conftest.py; "
                  "mark the test @pytest.mark.integration to allow it")


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Refuse every outbound connection unless the test is marked."""
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _blocked)
