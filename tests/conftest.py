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
import tempfile
from pathlib import Path

import pytest

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
os.environ.update(SESSION_ENV)

# Every variable linecast reads that would change what a test sees.
# LINECAST_THEME is not here: _theme reads it once at import, and
# tests/test_theme_reload.py needs the terminal-following mode it gets
# when the variable is unset (tests/test_render_snapshots.py pins the
# fixed palette for itself).
SCRUBBED = (
    "WEATHER_UNITS", "TIDES_UNITS", "WEATHER_LOCATION", "WEATHER_NO_SHADING",
    "TIDE_STATION", "LINECAST_LANG", "LINECAST_ICONS", "LINECAST_TEMP",
    "LINECAST_TIDECHECK_KEY", "LINECAST_RADAR_THEME", "LINECAST_RADAR_LAYERS",
    "LINECAST_RADAR_LAYER", "LINECAST_THEME_WATCH", "LINECAST_THEME_POLL",
    "LINECAST_THEME_TIMEOUT_MS", "LINECAST_LIBREWXR_URL",
    "LINECAST_ELEVATION_URL", "LINECAST_BUILTUP_URL",
    "LINECAST_VECTOR_TILES_URL", "LINECAST_COLOR", "NO_COLOR", "CLICOLOR",
    "CLICOLOR_FORCE", "COLUMNS", "LINES",
)
for _name in SCRUBBED:
    os.environ.pop(_name, None)


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
    for name in SCRUBBED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: HOME))


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
