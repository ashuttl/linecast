"""IP geolocation with caching and country detection."""

import json, time, urllib.request
from pathlib import Path

from linecast._cache import CACHE_ROOT

_CACHE_FILE = CACHE_ROOT / "location.json"
_MAX_AGE = 7 * 86400  # 7 days


def get_location():
    """Get (lat, lng, country_code) from cache or IP geolocation.

    Returns (lat, lng, country_code) on success, (None, None, None) on failure.
    country_code is ISO 3166-1 alpha-2 (e.g., "US", "CA", "GB").
    """
    if _CACHE_FILE.exists():
        age = time.time() - _CACHE_FILE.stat().st_mtime
        if age < _MAX_AGE:
            try:
                d = json.loads(_CACHE_FILE.read_text())
                return d["lat"], d["lng"], d.get("country", "")
            except (json.JSONDecodeError, KeyError):
                pass

    try:
        req = urllib.request.Request(
            "https://ipinfo.io/json",
            headers={"Accept": "application/json", "User-Agent": "linecast/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=3)
        d = json.loads(resp.read())
        parts = d.get("loc", "").split(",")
        if len(parts) == 2:
            lat, lng = float(parts[0]), float(parts[1])
            country = d.get("country", "")
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(json.dumps({
                "lat": lat, "lng": lng, "country": country,
            }))
            return lat, lng, country
    except Exception:
        pass

    return None, None, None
