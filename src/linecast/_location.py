"""IP geolocation with caching and country detection."""

from linecast._cache import CACHE_ROOT, read_cache, write_cache
from linecast._http import fetch_json
from linecast._runtime import debug_log
from linecast import USER_AGENT

_CACHE_FILE = CACHE_ROOT / "location.json"
_MAX_AGE = 3600  # 1 hour; implicit IP geolocation should refresh as users move.


def get_location():
    """Get (lat, lng, country_code) from cache or IP geolocation.

    Returns (lat, lng, country_code) on success, (None, None, None) on failure.
    country_code is ISO 3166-1 alpha-2 (e.g., "US", "CA", "GB").
    """
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
