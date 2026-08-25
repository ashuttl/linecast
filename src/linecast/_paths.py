"""Where linecast keeps its files: one cache root and one config root.

Both are decided here and nowhere else, at call time from the
environment, so a test, a wrapper script, or a user with an unusual
home can move them without any module having frozen a copy at import.
Nothing here creates a directory; the writers do that when they have
something to keep.

The cache root, in order of precedence:

  LINECAST_CACHE_DIR       used as given, no "linecast" appended
  $XDG_CACHE_HOME/linecast when XDG_CACHE_HOME is an absolute path
  ~/Library/Caches/linecast on macOS, unless that directory is absent
                           and the older ~/.cache/linecast is present,
                           in which case the older one stays in use
  ~/.cache/linecast        everywhere else

The config root follows the same shape with LINECAST_CONFIG_DIR and
XDG_CONFIG_HOME, and lives under ~/.config on every platform: that is
where command-line tools keep their settings, macOS included.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path


def _override(env, name):
    """An explicit LINECAST_*_DIR, expanded, or None when unset or blank."""
    value = env.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _xdg(env, name):
    """An XDG base directory, or None when unset, blank, or relative.

    The XDG spec says a relative value is invalid and should be ignored.
    """
    value = env.get(name, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _is_dir(path):
    # os.path.isdir never raises; Path.is_dir can on an unreadable parent
    return os.path.isdir(path)


def cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """The directory every cache file lives under."""
    env = os.environ if environ is None else environ
    override = _override(env, "LINECAST_CACHE_DIR")
    if override is not None:
        return override
    xdg = _xdg(env, "XDG_CACHE_HOME")
    if xdg is not None:
        return xdg / "linecast"
    home = Path.home()
    legacy = home / ".cache" / "linecast"
    if sys.platform == "darwin":
        native = home / "Library" / "Caches" / "linecast"
        if not _is_dir(native) and _is_dir(legacy):
            return legacy
        return native
    return legacy


def config_root(environ: Mapping[str, str] | None = None) -> Path:
    """The directory config.json lives in."""
    env = os.environ if environ is None else environ
    override = _override(env, "LINECAST_CONFIG_DIR")
    if override is not None:
        return override
    xdg = _xdg(env, "XDG_CONFIG_HOME")
    if xdg is not None:
        return xdg / "linecast"
    return Path.home() / ".config" / "linecast"


def cache_dir(*parts: str) -> Path:
    """A path under the cache root: cache_dir("maps", "tile.png")."""
    return cache_root().joinpath(*parts)
