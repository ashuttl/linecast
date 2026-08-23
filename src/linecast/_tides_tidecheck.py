"""TideCheck global tide data source (optional).

Provides station discovery and tide prediction fetchers for TideCheck's
global API (6,470+ stations, 176 countries).  Activated only when the user
sets the LINECAST_TIDECHECK_KEY environment variable.  Without the key this
module is completely inert — no network calls, no errors, no noise.

The API publishes high/low extremes only (heights in meters, times in
UTC alongside a localTime with offset); the smooth curve is synthesized
with the same cosine model subordinate NOAA stations use.  Discovery
endpoints (/stations/nearest, /stations/search) return bare JSON arrays
sorted by relevance/distance.

API docs: https://tidecheck.com/developers
Auth:     X-API-Key header
Free tier: 50 requests/day (no credit card required)
"""

import os

from linecast import USER_AGENT
from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._http import fetch_json, fetch_json_cached
from linecast._tides_common import (
    CACHE_DIR, M_TO_FT, NEAREST_STATION_CACHE_MAX_AGE, cached_y_range,
    iana_to_abbr, parse_cached_dt, parse_utc_iso, tz_offset_hours,
    y_range_window,
)

TIDECHECK_BASE = "https://tidecheck.com/api"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------
def _api_key():
    """Return the TideCheck API key from the environment, or None."""
    return os.environ.get("LINECAST_TIDECHECK_KEY", "").strip() or None


def is_available():
    """Return True when the user has configured a TideCheck API key."""
    return _api_key() is not None


def _headers():
    """Standard request headers including the API key."""
    key = _api_key()
    if not key:
        return {}
    return {
        "User-Agent": USER_AGENT,
        "X-API-Key": key,
    }


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def find_nearest_station_tidecheck(lat, lng):
    """Find closest TideCheck tide station by lat/lng.

    Returns (station_id, station_name) or (None, None).  Cached for 1 hour.
    The API does the distance search server-side, so this does not share
    the station-list picker the other providers use.
    """
    if not is_available():
        return None, None

    cache_file = CACHE_DIR / f"tc_station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    url = f"{TIDECHECK_BASE}/stations/nearest?lat={lat}&lng={lng}"
    try:
        data = fetch_json(url, headers=_headers(), timeout=10)
    except Exception:
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    if not data:
        return None, None

    # /stations/nearest returns a JSON array sorted by distance; keep the
    # dict shapes as fallbacks in case the API grows a wrapper.
    if isinstance(data, list):
        station = data[0] if data else None
    elif isinstance(data, dict):
        station = data.get("station", data)
    else:
        station = None
    if not station:
        return None, None

    # Parity with the NOAA picker's 100 nm cutoff, using the distanceKm
    # the endpoint reports — an inland user shouldn't get a random coast.
    try:
        if float(station.get("distanceKm", 0)) > 185:
            return None, None
    except (TypeError, ValueError):
        pass

    station_id = str(station.get("id", ""))
    station_name = station.get("label") or station.get("name", "")
    if not station_id:
        return None, None

    result = {"id": station_id, "name": station_name, "lat": lat, "lng": lng}
    write_cache(cache_file, result)
    return station_id, station_name


def search_stations_tidecheck(query):
    """Search TideCheck stations by name substring.

    Returns a list of dicts with 'id', 'name', 'lat', and 'lng' keys, or [].
    The name is the API's label ("Cascais, Lisbon, Portugal") when present,
    and the coordinates let the caller sort by distance like any other
    provider's stations.
    """
    if not is_available():
        return []

    import urllib.parse
    encoded = urllib.parse.quote(query)
    cache_file = CACHE_DIR / f"tc_search_{encoded[:40]}.json"
    url = f"{TIDECHECK_BASE}/stations/search?q={encoded}"

    data = fetch_json_cached(
        cache_file, 86400, url,
        headers=_headers(),
        timeout=10, fallback=None,
    )
    if not data:
        return []

    # The API returns a bare list; keep the wrapped shape as a fallback
    stations = data if isinstance(data, list) else data.get("stations", [])
    results = []
    for s in stations:
        sid = str(s.get("id", ""))
        if sid:
            results.append({
                "id": sid,
                "name": s.get("label") or s.get("name", ""),
                "lat": s.get("lat"), "lng": s.get("lng"),
            })
    return results


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_tidecheck(station_id):
    """Fetch TideCheck station metadata, normalized to match NOAA shape.

    Returns dict with: id, name, lat, lng, timezone_abbr, timezonecorr,
    timeZoneCode, observedst, source.
    """
    if not is_available():
        return None

    cache_file = CACHE_DIR / f"tc_meta_{station_id}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "tidecheck":
        return cached

    # TideCheck embeds station info (lat/lng/timezone/country) in the tides
    # response; reuse the 30-day fetch the y-range needs so metadata never
    # costs a request of its own (the free tier allows 50/day).
    data = _fetch_tides_raw(station_id, days=30)
    if not data:
        return None

    station = data.get("station", {})
    tz_code = station.get("timezone", "")

    meta = {
        "id": str(station.get("id", station_id)),
        "name": station.get("name", ""),
        # The header pill renders "name, state" — the country reads best
        "state": station.get("country", ""),
        "lat": station.get("lat") or station.get("latitude"),
        "lng": station.get("lng") or station.get("longitude"),
        "timezone_abbr": iana_to_abbr(tz_code),
        "timezonecorr": tz_offset_hours(tz_code),
        "timeZoneCode": tz_code,
        "observedst": tz_code not in ("UTC", "GMT", ""),
        "source": "tidecheck",
    }
    write_cache(cache_file, meta)
    return meta


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def _fetch_tides_raw(station_id, days=7):
    """Fetch raw TideCheck tides response (cached 24 hours).

    Returns the full JSON dict or None.  Aggressively cached because the
    free tier allows only 50 requests/day.
    """
    if not is_available():
        return None

    cache_file = CACHE_DIR / f"tc_raw_{station_id}_{days}d.json"
    url = f"{TIDECHECK_BASE}/station/{station_id}/tides?days={days}&datum=MLLW"
    return fetch_json_cached(
        cache_file, 86400, url,
        headers=_headers(),
        timeout=15, fallback=None,
    )


def fetch_tides_range_tidecheck(station_id, start_date, end_date, station_tz):
    """Fetch TideCheck predictions across a date range as a smooth curve.

    The API publishes high/low extremes only — no minute series — so the
    curve is synthesized with the same cosine half-cycle model subordinate
    NOAA stations use.  Synthesis is cheap; only the raw response is
    cached (24h, inside fetch_hilo_range_tidecheck's fetch).  Returns
    sorted (datetime, height_ft) tuples.
    """
    from linecast._tides_noaa import synthesize_tides_from_hilo
    labeled = fetch_hilo_range_tidecheck(station_id, start_date, end_date,
                                         station_tz)
    return synthesize_tides_from_hilo(labeled)


def _maybe_convert_height(height, api_response):
    """Convert a TideCheck height to feet (the pipeline's working unit).

    The API reports heights in meters for every station (confirmed live
    and in the docs); an explicit unit field wins if one ever appears.
    """
    unit = ""
    if isinstance(api_response, dict):
        unit = str(api_response.get("unit", api_response.get("units", ""))).lower()
    if "feet" in unit or unit in ("ft", "imperial"):
        return height
    return height * M_TO_FT


def fetch_hilo_range_tidecheck(station_id, start_date, end_date, station_tz):
    """Fetch TideCheck high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    """
    if not is_available():
        return []

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"tc_hilo_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in cached]

    days_needed = max(1, (end_date - start_date).days + 1)
    fetch_days = min(30, days_needed + 2)
    data = _fetch_tides_raw(station_id, days=fetch_days)
    if not data:
        return []

    extremes = data.get("extremes", [])
    if not extremes:
        return []

    labeled = []
    for ex in extremes:
        try:
            dt_local = parse_utc_iso(ex.get("time", ""), station_tz)
            height = float(ex.get("height", 0))
            height_ft = _maybe_convert_height(height, data)
            # TideCheck labels extremes as "high"/"low" (or "H"/"L")
            raw_type = str(ex.get("type", "")).upper()
            if raw_type.startswith("H"):
                typ = "H"
            elif raw_type.startswith("L"):
                typ = "L"
            else:
                typ = "H"  # default; will be corrected below
            labeled.append((dt_local, height_ft, typ))
        except (KeyError, ValueError, TypeError):
            continue

    labeled.sort(key=lambda p: p[0])

    cache_rows = [{"dt": dt.isoformat(), "v": v, "t": t} for dt, v, t in labeled]
    write_cache(cache_file, cache_rows)
    return labeled


def fetch_y_range_tidecheck(station_id, center_date, station_tz):
    """Compute y-axis range from TideCheck hilo data.  Cached 7 days.

    TideCheck only serves the next 30 days from now, so the window is not
    ours to choose; the cache key is month-anchored (see y_range_window)
    so consecutive days share one request and one file.
    """
    _, _, key = y_range_window(center_date)

    def heights():
        # Fetch a 30-day window (the maximum TideCheck supports)
        data = _fetch_tides_raw(station_id, days=30)
        if not data:
            return None
        found = []
        for ex in data.get("extremes", []):
            try:
                height = float(ex.get("height", 0))
                found.append(_maybe_convert_height(height, data))
            except (KeyError, ValueError, TypeError):
                pass
        return found

    return cached_y_range(CACHE_DIR / f"tc_yrange_{station_id}_{key}.json", heights)
