"""CHS (Canadian Hydrographic Service) tide data source.

Uses the IWLS API at api-iwls.dfo-mpo.gc.ca for Canadian tidal stations.
All CHS data is in UTC and metres; this module converts to local time and
feet for compatibility with the NOAA-based rendering pipeline.
"""

from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json, fetch_json_cached

CACHE_DIR = CACHE_ROOT / "tides"
CHS_BASE = "https://api-iwls.dfo-mpo.gc.ca/api/v1"
M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def _fetch_all_stations_chs():
    """Fetch the full CHS tidal station list (cached 30 days)."""
    cache_file = CACHE_DIR / "chs_all_stations.json"
    url = f"{CHS_BASE}/stations?time-series-code=wlp-hilo"
    data = fetch_json_cached(
        cache_file, 30 * 86400, url,
        headers={"User-Agent": USER_AGENT},
        timeout=15, fallback=None,
    )
    if not data or not isinstance(data, list):
        return []
    return data


def find_nearest_station_chs(lat, lng):
    """Find closest CHS tide station by haversine distance.

    Returns (station_id, station_name) or (None, None). Cached 1 hour.
    """
    cache_file = CACHE_DIR / f"chs_station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    try:
        stations = _fetch_all_stations_chs()
    except Exception:
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    if not stations:
        return None, None

    best_id, best_name, best_dist = None, None, float("inf")
    for s in stations:
        try:
            slat = float(s["latitude"])
            slng = float(s["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        if not s.get("operating", True):
            continue
        d = haversine_nm(lat, lng, slat, slng)
        if d < best_dist:
            best_dist = d
            best_id = str(s.get("id", ""))
            best_name = s.get("officialName", "")

    if best_dist > 100:  # > 100 nautical miles
        return None, None

    result = {"id": best_id, "name": best_name, "lat": lat, "lng": lng}
    write_cache(cache_file, result)
    return best_id, best_name


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_chs(station_id):
    """Fetch CHS station metadata, normalized to match NOAA shape.

    Returns dict with: id, name, state, lat, lng, timezone_abbr,
    timezonecorr, timeZoneCode, observedst, source.
    """
    cache_file = CACHE_DIR / f"chs_meta_{station_id}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "chs":
        return cached

    url = f"{CHS_BASE}/stations/{station_id}/metadata"
    data = fetch_json_cached(
        cache_file, 0, url,
        headers={"User-Agent": USER_AGENT},
        timeout=10, fallback=None,
    )
    if not data:
        return None

    if data.get("source") == "chs":
        return data

    tz_code = data.get("timeZoneCode", "")
    tz_offset = _tz_offset_hours(tz_code)

    meta = {
        "id": str(data.get("id", station_id)),
        "name": data.get("officialName", ""),
        "state": data.get("provinceCode", ""),
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        "timezone_abbr": _iana_to_abbr(tz_code),
        "timezonecorr": tz_offset,
        "timeZoneCode": tz_code,
        "observedst": tz_code not in ("UTC", "GMT", ""),
        "source": "chs",
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
    "Canada/Pacific": "PST", "America/Vancouver": "PST",
    "Canada/Mountain": "MST", "America/Edmonton": "MST",
    "Canada/Central": "CST", "America/Winnipeg": "CST",
    "Canada/Eastern": "EST", "America/Toronto": "EST",
    "Canada/Atlantic": "AST", "America/Halifax": "AST",
    "Canada/Newfoundland": "NST", "America/St_Johns": "NST",
}


def _iana_to_abbr(tz_code):
    """Map IANA timezone to common abbreviation for display."""
    return _IANA_ABBR.get(tz_code, "UTC")


# ---------------------------------------------------------------------------
# UTC <-> local helpers
# ---------------------------------------------------------------------------
def _utc_range_for_dates(start_date, end_date, station_tz):
    """Convert local date range to UTC ISO strings for the CHS API."""
    local_start = datetime(start_date.year, start_date.month, start_date.day)
    local_end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    if station_tz is not None:
        local_start = local_start.replace(tzinfo=station_tz)
        local_end = local_end.replace(tzinfo=station_tz)
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = local_end.astimezone(timezone.utc)
    else:
        utc_start = local_start.replace(tzinfo=timezone.utc)
        utc_end = local_end.replace(tzinfo=timezone.utc)
    return (utc_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            utc_end.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _parse_chs_dt(s, station_tz):
    """Parse CHS UTC datetime string to timezone-aware local datetime."""
    s = s.rstrip("Z")
    if "." in s:
        s = s[:s.index(".")]
    dt_utc = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
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
# High/low labeling
# ---------------------------------------------------------------------------
def _label_hilo(values):
    """Infer H/L labels from a sequence of extrema (dt, height_ft) tuples.

    CHS wlp-hilo does not label highs vs lows; this compares adjacent
    values to determine which are peaks and which are troughs.
    """
    if not values:
        return []
    if len(values) == 1:
        return [(*values[0], "H")]

    labeled = []
    for i, (dt, height) in enumerate(values):
        if i == 0:
            is_high = height > values[1][1]
        elif i == len(values) - 1:
            is_high = height > values[-2][1]
        else:
            is_high = height > values[i - 1][1] and height > values[i + 1][1]
        labeled.append((dt, height, "H" if is_high else "L"))
    return labeled


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def fetch_tides_range_chs(station_id, start_date, end_date, station_tz):
    """Fetch CHS interval predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    CHS supports up to 31 days at FIVE_MINUTES resolution per request.
    """
    points = []
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=29), end_date)
        chunk = _fetch_pred_chunk(station_id, d, chunk_end, station_tz)
        if chunk:
            points.extend(chunk)
        d = chunk_end + timedelta(days=1)

    seen = set()
    unique = []
    for dt, h in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, h))
    unique.sort(key=lambda p: p[0])
    return unique


def _fetch_pred_chunk(station_id, start_date, end_date, station_tz):
    """Fetch a single chunk of CHS predictions (max 30 days)."""
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"chs_pred_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"], station_tz), r["v"]) for r in cached]

    utc_from, utc_to = _utc_range_for_dates(start_date, end_date, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlp&from={utc_from}&to={utc_to}"
        f"&resolution=FIVE_MINUTES"
    )
    data = fetch_json_cached(
        cache_file, 0, url,
        headers={"User-Agent": USER_AGENT},
        timeout=20, fallback=None,
    )
    if not data or not isinstance(data, list):
        return []

    rows = []
    points = []
    for entry in data:
        try:
            dt_local = _parse_chs_dt(entry["eventDate"], station_tz)
            height_ft = float(entry["value"]) * M_TO_FT
            rows.append({"dt": dt_local.isoformat(), "v": height_ft})
            points.append((dt_local, height_ft))
        except (KeyError, ValueError, TypeError):
            continue

    write_cache(cache_file, rows)
    return points


def fetch_hilo_range_chs(station_id, start_date, end_date, station_tz):
    """Fetch CHS high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    CHS supports up to 366 days of hilo data per request.
    """
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"chs_hilo_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in cached]

    utc_from, utc_to = _utc_range_for_dates(start_date, end_date, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlp-hilo&from={utc_from}&to={utc_to}"
    )
    data = fetch_json_cached(
        cache_file, 0, url,
        headers={"User-Agent": USER_AGENT},
        timeout=15, fallback=None,
    )
    if not data or not isinstance(data, list):
        return []

    raw = []
    for entry in data:
        try:
            dt_local = _parse_chs_dt(entry["eventDate"], station_tz)
            height_ft = float(entry["value"]) * M_TO_FT
            raw.append((dt_local, height_ft))
        except (KeyError, ValueError, TypeError):
            continue

    labeled = _label_hilo(raw)

    cache_rows = [{"dt": dt.isoformat(), "v": v, "t": t} for dt, v, t in labeled]
    write_cache(cache_file, cache_rows)
    return labeled


def fetch_y_range_chs(station_id, center_date, station_tz):
    """Compute y-axis range from +/-30 days of CHS hilo data. Cached 7 days."""
    start = center_date - timedelta(days=30)
    end = center_date + timedelta(days=30)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"chs_yrange_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    utc_from, utc_to = _utc_range_for_dates(start, end, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlp-hilo&from={utc_from}&to={utc_to}"
    )
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception:
        return None

    if not data or not isinstance(data, list):
        return None

    heights = []
    for entry in data:
        try:
            heights.append(float(entry["value"]) * M_TO_FT)
        except (KeyError, ValueError, TypeError):
            pass

    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
