"""IP geolocation with caching and country detection."""

import os
import sys
from datetime import tzinfo

from linecast._cache import location_cache_key, read_cache, write_cache
from linecast._config import saved_location
from linecast._http import fetch_json, fetch_json_cached
from linecast._paths import cache_dir
from linecast._runtime import log_failure

_MAX_AGE = 3600  # 1 hour; implicit IP geolocation should refresh as users move.


def _cache_file():
    return cache_dir("location.json")


def get_location() -> tuple[float | None, float | None, str | None]:
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

    cached = read_cache(_cache_file(), _MAX_AGE)
    if cached is not None:
        try:
            return cached["lat"], cached["lng"], cached.get("country", "")
        except KeyError:
            pass

    try:
        data = fetch_json(
            "https://ipinfo.io/json",
            headers={"Accept": "application/json"},
            timeout=3,
        )
        parts = data.get("loc", "").split(",")
        if len(parts) != 2:
            return None, None, None
        lat, lng = float(parts[0]), float(parts[1])
        country = data.get("country", "")
    except Exception as exc:
        log_failure("location/ipinfo", "geolocation", exc, url="https://ipinfo.io/json",
                    fallback="no location")
        return None, None, None

    # the answer is in hand; keeping it is a separate, best-effort matter
    write_cache(_cache_file(), {"lat": lat, "lng": lng, "country": country})
    return lat, lng, country


def own_country() -> str | None:
    """The user's own country (ISO alpha-2), for units and clock defaults.

    The saved location's country, else the IP-geolocation cache -- read
    with a 30-day tolerance, since a country changes far more slowly than
    a position -- else None.  Never fetches: the defaults must resolve
    offline, and before any command has touched the network.
    """
    saved = saved_location()
    if saved is not None and saved.get("country"):
        return saved["country"]
    cached = read_cache(_cache_file(), 30 * 86400)
    if cached is not None and cached.get("country"):
        return cached["country"]
    return None


def location_overridden(cli_location: str | None = None) -> bool:
    """True when a --location flag or WEATHER_LOCATION points the view
    somewhere explicit -- a place that need not be the user's own, so
    its country must not feed the units default."""
    return bool((cli_location or os.environ.get("WEATHER_LOCATION", "")).strip())


def resolve_location(
    cli_location: str | None = None, lang: str = "en", need_country: bool = False,
    return_label: bool = False,
) -> (tuple[float | None, float | None, str | None]
      | tuple[float | None, float | None, str | None, str]):
    """Resolve the working location for a command.

    Precedence: --location flag (*cli_location*) > WEATHER_LOCATION env >
    saved location > IP geolocation. Returns (lat, lng, country_code), or
    (None, None, None) when no location can be determined. An explicit
    override that can't be geocoded exits with an error message instead.

    country_code is "" for overrides unless *need_country* is set, in which
    case it is filled in via the (cached) reverse geocoder.

    With *return_label*, a fourth element carries the geocoder's label for
    a place-name override ("" otherwise); radar and maps show it as the
    place name instead of reverse-geocoding the coordinates again.
    """
    override = (cli_location or os.environ.get("WEATHER_LOCATION", "")).strip()
    if not override:
        lat, lng, country = get_location()
        return (lat, lng, country, "") if return_label else (lat, lng, country)

    country = ""
    label = ""
    try:
        parts = override.split(",")
        lat, lng = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        from linecast._weather_sources import geocode_first
        hit = geocode_first(override, lang=lang)
        if hit is None:
            # sys.exit with a message prints it to stderr with status 1,
            # after the caller's finally blocks have run -- so a spinner
            # on the same line is cleared before the message lands.
            sys.exit(f'No locations matching "{override}".')
        lat, lng, label = hit
    if need_country:
        from linecast._weather_sources import _reverse_geocode
        _name, country, _addr = _reverse_geocode(lat, lng)
    return (lat, lng, country, label) if return_label else (lat, lng, country)


def location_is_pinned(cli_location: str | None = None) -> bool:
    """True when the location comes from a flag, env var, or saved setting.

    A pinned location may be anywhere on Earth; an unpinned (IP-derived)
    one is where the machine is, so machine-local time already matches it.
    """
    return bool(cli_location
                or os.environ.get("WEATHER_LOCATION", "").strip()
                or saved_location() is not None)


def location_tzinfo(lat: float | None, lng: float | None) -> tzinfo | None:
    """tzinfo for a location, via a cached Open-Meteo timezone lookup.

    Falls back to the machine's local timezone when the lookup fails
    (offline with a cold cache) or the zone database lacks the name.
    Cached for 30 days per location.
    """
    from datetime import datetime
    machine_tz = datetime.now().astimezone().tzinfo
    if lat is None or lng is None:
        return machine_tz

    cache_file = cache_dir(f"timezone_{location_cache_key(lat, lng)}.json")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}&timezone=auto"
    )
    data = fetch_json_cached(
        cache_file,
        30 * 86400,
        url,
        timeout=5,
        fallback=None,
    )
    tz_name = (data or {}).get("timezone")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception as exc:
            log_failure("tz", f"lookup of {tz_name}", exc, fallback="machine timezone")
    return machine_tz
