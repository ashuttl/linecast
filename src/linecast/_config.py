"""Persistent user settings (~/.config/linecast/config.json)."""

import json
import os
from pathlib import Path


def config_file():
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "linecast" / "config.json"


def read_config():
    """Return the parsed config dict, or {} if missing or corrupt."""
    try:
        return json.loads(config_file().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_config(data):
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    from linecast._cache import write_bytes_atomic
    write_bytes_atomic(path, (json.dumps(data, indent=2) + "\n").encode())


def saved_units():
    """Return 'metric' or 'imperial' saved via `linecast units`, or None."""
    units = read_config().get("units")
    if isinstance(units, str) and units.strip().lower() in ("metric", "imperial"):
        return units.strip().lower()
    return None


def saved_location():
    """Return the location saved via `linecast location set`, or None.

    Shape: {"lat": float, "lng": float, "label": str, "country": str}.
    Resolved to coordinates at set time, so reading it never hits the network.
    """
    loc = read_config().get("location")
    if isinstance(loc, dict) and "lat" in loc and "lng" in loc:
        return loc
    return None
