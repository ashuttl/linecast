"""TideCheck global tide data source (optional).

Provides station discovery and tide prediction fetchers for TideCheck's
global API (6,470+ stations, 176 countries).  Activated only when the user
sets the LINECAST_TIDECHECK_KEY environment variable.  Without the key this
module is completely inert — no network calls, no errors, no noise.

API docs: https://tidecheck.com/developers
Auth:     X-API-Key header
Free tier: 50 requests/day (no credit card required)
"""

import os
from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json, fetch_json_cached

CACHE_DIR = CACHE_ROOT / "tides"
TIDECHECK_BASE = "https://tidecheck.com/api"
M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600

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

    # The /stations/nearest endpoint returns a station object (or a wrapper
    # containing one).  Handle both shapes defensively.
    station = data.get("station", data) if isinstance(data, dict) else None
    if not station:
        return None, None

    station_id = str(station.get("id", ""))
    station_name = station.get("name", "")
    if not station_id:
        return None, None

    result = {"id": station_id, "name": station_name, "lat": lat, "lng": lng}
    write_cache(cache_file, result)
    return station_id, station_name


def search_stations_tidecheck(query):
    """Search TideCheck stations by name substring.

    Returns a list of dicts with 'id' and 'name' keys, or [].
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

    # Normalize: API may return a list directly or wrap in {"stations": [...]}
    stations = data if isinstance(data, list) else data.get("stations", [])
    results = []
    for s in stations:
        sid = str(s.get("id", ""))
        name = s.get("name", "")
        if sid:
            results.append({"id": sid, "name": name})
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

    # TideCheck embeds station info in the tides response; fetch a 1-day
    # prediction to extract metadata while also priming the prediction cache.
    url = f"{TIDECHECK_BASE}/station/{station_id}/tides?days=1&datum=MLLW"
    data = fetch_json_cached(
        cache_file, 0, url,
        headers=_headers(),
        timeout=10, fallback=None,
    )
    if not data:
        return None

    if data.get("source") == "tidecheck":
        return data

    station = data.get("station", {})
    tz_code = station.get("timezone", "")
    tz_offset = _tz_offset_hours(tz_code)

    meta = {
        "id": str(station.get("id", station_id)),
        "name": station.get("name", ""),
        "state": "",
        "lat": station.get("lat") or station.get("latitude"),
        "lng": station.get("lng") or station.get("longitude"),
        "timezone_abbr": _iana_to_abbr(tz_code),
        "timezonecorr": tz_offset,
        "timeZoneCode": tz_code,
        "observedst": tz_code not in ("UTC", "GMT", ""),
        "source": "tidecheck",
    }
    write_cache(cache_file, meta)
    return meta


def _tz_offset_hours(tz_code):
    """Get current UTC offset in hours for an IANA timezone."""
    if not tz_code:
        return 0
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz_code))
        return now.utcoffset().total_seconds() / 3600
    except Exception:
        return 0


_IANA_ABBR = {
    "Europe/London": "GMT", "Europe/Paris": "CET", "Europe/Berlin": "CET",
    "Europe/Rome": "CET", "Europe/Madrid": "CET", "Europe/Amsterdam": "CET",
    "Europe/Brussels": "CET", "Europe/Vienna": "CET",
    "Europe/Athens": "EET", "Europe/Helsinki": "EET",
    "Europe/Istanbul": "TRT", "Europe/Moscow": "MSK",
    "Asia/Tokyo": "JST", "Asia/Shanghai": "CST", "Asia/Hong_Kong": "HKT",
    "Asia/Seoul": "KST", "Asia/Kolkata": "IST", "Asia/Bangkok": "ICT",
    "Asia/Singapore": "SGT", "Asia/Dubai": "GST",
    "Australia/Sydney": "AEST", "Australia/Perth": "AWST",
    "Australia/Adelaide": "ACST", "Australia/Brisbane": "AEST",
    "Pacific/Auckland": "NZST", "Pacific/Fiji": "FJT",
    "Pacific/Honolulu": "HST", "Pacific/Guam": "ChST",
    "America/New_York": "EST", "America/Chicago": "CST",
    "America/Denver": "MST", "America/Los_Angeles": "PST",
    "America/Anchorage": "AKST", "America/Phoenix": "MST",
    "America/Toronto": "EST", "America/Vancouver": "PST",
    "America/Halifax": "AST", "America/St_Johns": "NST",
    "America/Sao_Paulo": "BRT", "America/Argentina/Buenos_Aires": "ART",
    "America/Mexico_City": "CST", "America/Lima": "PET",
    "America/Bogota": "COT", "America/Santiago": "CLT",
    "Africa/Cairo": "EET", "Africa/Lagos": "WAT",
    "Africa/Johannesburg": "SAST", "Africa/Nairobi": "EAT",
}


def _iana_to_abbr(tz_code):
    """Map IANA timezone to common abbreviation for display."""
    return _IANA_ABBR.get(tz_code, "UTC")


# ---------------------------------------------------------------------------
# UTC <-> local helpers
# ---------------------------------------------------------------------------
def _parse_iso_utc(s):
    """Parse an ISO 8601 UTC timestamp to a timezone-aware UTC datetime."""
    s = s.rstrip("Z")
    if "." in s:
        s = s[:s.index(".")]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _to_local(dt_utc, station_tz):
    """Convert a UTC datetime to station local time."""
    if station_tz is not None:
        return dt_utc.astimezone(station_tz)
    return dt_utc


def _parse_cached_dt(iso_str, station_tz):
    """Parse an ISO datetime string from cache back to aware datetime."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None and station_tz is not None:
        dt = dt.replace(tzinfo=station_tz)
    return dt


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
    """Fetch TideCheck interval predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples, matching the format
    expected by the rendering pipeline.
    """
    if not is_available():
        return []

    # Calculate how many days we need
    days_needed = max(1, (end_date - start_date).days + 1)
    # TideCheck supports up to 30 days; clamp to that
    fetch_days = min(30, days_needed + 2)  # +2 for timezone overlap

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"tc_pred_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"], station_tz), r["v"]) for r in cached]

    data = _fetch_tides_raw(station_id, days=fetch_days)
    if not data:
        return []

    # Extract the time series (minute-by-minute water levels)
    # TideCheck returns this in a "heights" or "timeSeries" array
    time_series = (
        data.get("heights")
        or data.get("timeSeries")
        or data.get("waterLevels")
        or []
    )

    if not time_series:
        # Fall back to synthesizing a curve from extremes if no time series
        return _synthesize_from_extremes(data, start_date, end_date, station_tz)

    # Filter to requested date range and convert
    range_start = datetime(start_date.year, start_date.month, start_date.day,
                           tzinfo=timezone.utc) - timedelta(hours=14)
    range_end = datetime(end_date.year, end_date.month, end_date.day,
                         tzinfo=timezone.utc) + timedelta(hours=38)

    rows = []
    points = []
    for entry in time_series:
        try:
            dt_utc = _parse_iso_utc(entry.get("time", entry.get("t", "")))
            # Height may be in metres; TideCheck with datum=MLLW returns feet
            # for US stations but metres for international.  Detect and convert.
            height = float(entry.get("height", entry.get("v", entry.get("value", 0))))
            # If heights look metric (TideCheck int'l stations report in metres)
            # the datum=MLLW parameter should return feet for NOAA-sourced
            # stations, but international ones may still be in metres.
            # We'll handle this via a heuristic in _maybe_convert_height.
        except (KeyError, ValueError, TypeError):
            continue

        if not (range_start <= dt_utc <= range_end):
            continue

        dt_local = _to_local(dt_utc, station_tz)
        height_ft = _maybe_convert_height(height, data)
        rows.append({"dt": dt_local.isoformat(), "v": height_ft})
        points.append((dt_local, height_ft))

    if rows:
        write_cache(cache_file, rows)
    return points


def _maybe_convert_height(height, api_response):
    """Convert height to feet if the API returned metres.

    TideCheck with datum=MLLW returns heights in the station's native unit.
    We detect the unit from the response metadata and convert if needed.
    """
    # Check if the API tells us the unit
    unit = ""
    if isinstance(api_response, dict):
        unit = str(api_response.get("unit", api_response.get("units", ""))).lower()
    if "meter" in unit or unit in ("m", "metres", "metric"):
        return height * M_TO_FT
    if "feet" in unit or unit in ("ft", "imperial"):
        return height
    # Default: assume MLLW in feet (US convention, which we requested)
    return height


def _synthesize_from_extremes(data, start_date, end_date, station_tz):
    """Build a smooth tide curve from high/low extremes using cosine interpolation.

    This fallback is used when the API doesn't return a minute-by-minute
    time series.  It creates a visually smooth approximation.
    """
    extremes = data.get("extremes", [])
    if not extremes:
        return []

    # Parse extremes
    parsed = []
    for ex in extremes:
        try:
            dt_utc = _parse_iso_utc(ex.get("time", ""))
            height = float(ex.get("height", 0))
            height_ft = _maybe_convert_height(height, data)
            dt_local = _to_local(dt_utc, station_tz)
            parsed.append((dt_local, height_ft))
        except (KeyError, ValueError, TypeError):
            continue

    if len(parsed) < 2:
        return list(parsed) if parsed else []

    parsed.sort(key=lambda p: p[0])

    # Generate interpolated points every 6 minutes between extremes
    import math
    points = []
    for i in range(len(parsed) - 1):
        dt1, h1 = parsed[i]
        dt2, h2 = parsed[i + 1]
        span = (dt2 - dt1).total_seconds()
        if span <= 0:
            continue

        step = 360  # 6 minutes in seconds
        t = 0
        while t <= span:
            frac = t / span
            # Cosine interpolation for natural tide shape
            weight = (1 - math.cos(frac * math.pi)) / 2
            height = h1 + (h2 - h1) * weight
            dt = dt1 + timedelta(seconds=t)
            points.append((dt, height))
            t += step

    # Deduplicate
    seen = set()
    unique = []
    for dt, h in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, h))
    unique.sort(key=lambda p: p[0])

    # Cache the synthesized points
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"tc_pred_{parsed[0][0].strftime('%s')}_{start_str}_{end_str}.json"
    rows = [{"dt": dt.isoformat(), "v": v} for dt, v in unique]
    write_cache(cache_file, rows)
    return unique


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
        return [(_parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in cached]

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
            dt_utc = _parse_iso_utc(ex.get("time", ""))
            height = float(ex.get("height", 0))
            height_ft = _maybe_convert_height(height, data)
            dt_local = _to_local(dt_utc, station_tz)
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
    """Compute y-axis range from TideCheck hilo data.  Cached 7 days."""
    start = center_date - timedelta(days=30)
    end = center_date + timedelta(days=30)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"tc_yrange_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    # Fetch a 30-day window (the maximum TideCheck supports)
    data = _fetch_tides_raw(station_id, days=30)
    if not data:
        return None

    extremes = data.get("extremes", [])
    if not extremes:
        return None

    heights = []
    for ex in extremes:
        try:
            height = float(ex.get("height", 0))
            heights.append(_maybe_convert_height(height, data))
        except (KeyError, ValueError, TypeError):
            pass

    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
