"""Persistent user settings (config.json under the config root)."""

import json
import sys
from pathlib import Path
from typing import Any

from linecast._paths import config_root
from linecast._runtime import log_failure


def config_file() -> Path:
    return config_root() / "config.json"


def read_config() -> dict[str, Any]:
    """Return the parsed config dict, or {} if missing or corrupt."""
    try:
        return json.loads(config_file().read_bytes())
    except FileNotFoundError:
        return {}  # nothing saved yet: the usual case
    except (OSError, json.JSONDecodeError) as exc:
        log_failure("config", "read of config.json", exc, fallback="defaults used")
        return {}


def write_config(data: dict[str, Any]) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    from linecast._cache import write_bytes_atomic
    write_bytes_atomic(path, (json.dumps(data, indent=2) + "\n").encode())


def save_config(data: dict[str, Any]) -> None:
    """write_config for the settings commands.

    A config directory that cannot be written is a fact about the
    machine, not a bug, so the command ends with one line naming the
    file and the reason rather than a traceback.
    """
    try:
        write_config(data)
    except OSError as exc:
        sys.exit(f"Could not save settings to {config_file()}: {exc.strerror or exc}")


def saved_units() -> str | None:
    """Return 'metric' or 'imperial' saved via `linecast units`, or None."""
    units = read_config().get("units")
    if isinstance(units, str) and units.strip().lower() in ("metric", "imperial"):
        return units.strip().lower()
    return None


def saved_clock() -> str | None:
    """Return '12' or '24' saved via `linecast clock`, or None."""
    clock = read_config().get("clock")
    if str(clock).strip() in ("12", "24"):
        return str(clock).strip()
    return None


def saved_icons() -> str | None:
    """Return 'nerd', 'emoji' or 'plain' saved via `linecast icons`, or None."""
    icons = read_config().get("icons")
    if isinstance(icons, str) and icons.strip().lower() in ("nerd", "emoji", "plain"):
        return icons.strip().lower()
    return None


CALENDAR_CHOICES = ("chinese", "japanese", "korean", "thai", "hawaiian",
                    "samoan", "chamorro", "refaluwasch", "islamic", "almanac",
                    "none")


def saved_calendar() -> str | None:
    """Return the calendar saved via `linecast calendar`, or None.

    A calendar name — 'chinese', 'japanese', 'korean', 'thai',
    'hawaiian', 'samoan', 'chamorro', 'refaluwasch', 'islamic', or
    'almanac' —
    pins that calendar in every language; 'none' turns the calendar
    lines off even where the language would show them.
    """
    cal = read_config().get("calendar")
    if isinstance(cal, str) and cal.strip().lower() in CALENDAR_CHOICES:
        return cal.strip().lower()
    return None


def saved_location() -> dict[str, Any] | None:
    """Return the location saved via `linecast location set`, or None.

    Shape: {"lat": float, "lng": float, "label": str, "country": str}.
    Resolved to coordinates at set time, so reading it never hits the network.
    """
    loc = read_config().get("location")
    if isinstance(loc, dict) and "lat" in loc and "lng" in loc:
        return loc
    return None
