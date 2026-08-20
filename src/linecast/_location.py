"""IP geolocation with caching and country detection."""

import os
import sys

from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, write_cache
from linecast._config import saved_location
from linecast._http import fetch_json, fetch_json_cached
from linecast._runtime import debug_log
from linecast import USER_AGENT

_CACHE_FILE = CACHE_ROOT / "location.json"
_MAX_AGE = 3600  # 1 hour; implicit IP geolocation should refresh as users move.


def get_location():
    """Get (lat, lng, country_code) from cache or IP geolocation.

    Returns (lat, lng, country_code) on success, (None, None, None) on failure.
    country_code is ISO 3166-1 alpha-2 (e.g., "US", "CA", "GB").

    A location saved via `linecast location set` takes precedence over IP
    geolocation. (--location flags and WEATHER_LOCATION are handled by
    callers before reaching here, so overall precedence is flag > env >
    saved > IP.)
    """
    saved = saved_location()
    if saved is not None:
        return saved["lat"], saved["lng"], saved.get("country", "")

    cached = read_cache(_CACHE_FILE, _MAX_AGE)
    if cached is not None:
        try:
            return cached["lat"], cached["lng"], cached.get("country", "")
        except KeyError:
            pass

    try:
        data = fetch_json(
            "https://ipinfo.io/json",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=3,
        )
        parts = data.get("loc", "").split(",")
        if len(parts) == 2:
            lat, lng = float(parts[0]), float(parts[1])
            country = data.get("country", "")
            write_cache(_CACHE_FILE, {"lat": lat, "lng": lng, "country": country})
            return lat, lng, country
    except Exception as exc:
        debug_log(f"geolocation failed: {exc}")

    return None, None, None


def resolve_location(cli_location=None, lang="en", need_country=False):
    """Resolve the working location for a command.

    Precedence: --location flag (*cli_location*) > WEATHER_LOCATION env >
    saved location > IP geolocation. Returns (lat, lng, country_code), or
    (None, None, None) when no location can be determined. An explicit
    override that can't be geocoded exits with an error message instead.

    country_code is "" for overrides unless *need_country* is set, in which
    case it is filled in via the (cached) reverse geocoder.
    """
    override = (cli_location or os.environ.get("WEATHER_LOCATION", "")).strip()
    if not override:
        return get_location()

    country = ""
    try:
        parts = override.split(",")
        lat, lng = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        from linecast._weather_sources import geocode_first
        hit = geocode_first(override, lang=lang)
        if hit is None:
            print(f'No locations matching "{override}".', file=sys.stderr)
            sys.exit(1)
        lat, lng, _label = hit
    if need_country:
        from linecast._weather_sources import _reverse_geocode
        _name, country, _addr = _reverse_geocode(lat, lng)
    return lat, lng, country


def location_is_pinned(cli_location=None):
    """True when the location comes from a flag, env var, or saved setting.

    A pinned location may be anywhere on Earth; an unpinned (IP-derived)
    one is where the machine is, so machine-local time already matches it.
    """
    return bool(cli_location
                or os.environ.get("WEATHER_LOCATION", "").strip()
                or saved_location() is not None)


def location_tzinfo(lat, lng):
    """tzinfo for a location, via a cached Open-Meteo timezone lookup.

    Falls back to the machine's local timezone when the lookup fails
    (offline with a cold cache) or the zone database lacks the name.
    Cached for 30 days per location.
    """
    from datetime import datetime
    machine_tz = datetime.now().astimezone().tzinfo
    if lat is None or lng is None:
        return machine_tz

    cache_file = CACHE_ROOT / f"timezone_{location_cache_key(lat, lng)}.json"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}&timezone=auto"
    )
    data = fetch_json_cached(
        cache_file,
        30 * 86400,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=5,
        fallback=None,
    )
    tz_name = (data or {}).get("timezone")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception as exc:
            debug_log(f"timezone lookup failed for {tz_name}: {exc}")
    return machine_tz
