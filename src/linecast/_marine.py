"""Open-Meteo Marine Weather API data source.

Fetches hourly wave/swell conditions for a given location.
The API is free and requires no API key, but coverage is limited
to coastal areas.
"""

from datetime import datetime, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache
from linecast._http import fetch_json_cached

CACHE_DIR = CACHE_ROOT / "marine"
MARINE_CACHE_MAX_AGE = 3600  # 1 hour


def _compass_direction(degrees):
    """Convert degrees (0-360) to a compass abbreviation."""
    if degrees is None:
        return ""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((degrees + 11.25) / 22.5) % 16
    return directions[idx]


def fetch_marine(lat, lng):
    """Fetch hourly marine forecast from Open-Meteo. Cached 1h.

    Returns the raw JSON response dict or None on failure.
    """
    cache_file = CACHE_DIR / f"marine_{location_cache_key(lat, lng)}.json"
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=wave_height,wave_period,wave_direction,"
        "wind_wave_height,swell_wave_height,swell_wave_period,"
        "swell_wave_direction"
        "&timezone=auto&forecast_days=3"
    )
    return fetch_json_cached(
        cache_file,
        MARINE_CACHE_MAX_AGE,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )


def parse_marine_current(data, target_dt=None):
    """Extract current marine conditions from an Open-Meteo marine response.

    Returns a dict with wave/swell info for the hour nearest to target_dt,
    or None if data is unavailable.

    Keys returned (any may be None if unavailable):
        wave_height     — combined wave height in meters
        wave_period     — combined wave period in seconds
        wave_direction  — combined wave direction in degrees
        swell_height    — swell wave height in meters
        swell_period    — swell wave period in seconds
        swell_direction — swell wave direction in degrees
    """
    if not data or not isinstance(data, dict):
        return None

    hourly = data.get("hourly")
    if not hourly:
        return None

    times = hourly.get("time", [])
    if not times:
        return None

    # Find the hour index closest to target_dt
    if target_dt is None:
        target_dt = datetime.now()

    # Open-Meteo returns times like "2026-03-27T14:00"
    best_idx = 0
    best_diff = None
    for i, t_str in enumerate(times):
        try:
            t = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            continue
        diff = abs((t - target_dt.replace(tzinfo=None)).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = i

    def _val(key):
        arr = hourly.get(key, [])
        if best_idx < len(arr):
            return arr[best_idx]
        return None

    wave_height = _val("wave_height")
    wave_period = _val("wave_period")
    wave_direction = _val("wave_direction")
    swell_height = _val("swell_wave_height")
    swell_period = _val("swell_wave_period")
    swell_direction = _val("swell_wave_direction")

    # If all wave fields are None, the location likely has no marine data
    if wave_height is None and swell_height is None:
        return None

    return {
        "wave_height": wave_height,
        "wave_period": wave_period,
        "wave_direction": wave_direction,
        "swell_height": swell_height,
        "swell_period": swell_period,
        "swell_direction": swell_direction,
    }


def format_marine_line(marine, runtime, width=80):
    """Format marine conditions as a compact display string.

    marine: dict from parse_marine_current()
    runtime: TidesRuntime instance (for metric/imperial, lang, emoji)
    width: available terminal width

    Returns a formatted string or "" if no useful data.
    """
    if not marine:
        return ""

    from linecast._tides_i18n import _ts

    parts = []

    # Wave info
    wh = marine.get("wave_height")
    wp = marine.get("wave_period")
    wd = marine.get("wave_direction")
    if wh is not None:
        h_str = _format_height(wh, runtime)
        segment = f"{_ts('waves', runtime)} {h_str}"
        if wp is not None:
            segment += f" @ {wp:.0f}s"
        if wd is not None:
            segment += f" {_compass_direction(wd)}"
        parts.append(segment)

    # Swell info
    sh = marine.get("swell_height")
    sp = marine.get("swell_period")
    sd = marine.get("swell_direction")
    if sh is not None and sh > 0:
        h_str = _format_height(sh, runtime)
        segment = f"{_ts('swell', runtime)} {h_str}"
        if sp is not None:
            segment += f" @ {sp:.0f}s"
        if sd is not None:
            segment += f" {_compass_direction(sd)}"
        parts.append(segment)

    if not parts:
        return ""

    return " \u2502 ".join(parts)


def _format_height(meters, runtime):
    """Format a wave height value respecting metric/imperial setting."""
    if runtime.metric:
        return f"{meters:.1f}m"
    else:
        feet = meters / 0.3048
        return f"{feet:.1f}\u2032"
