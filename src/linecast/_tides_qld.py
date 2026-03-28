"""Queensland (Australia) tide data source.

Uses the Queensland Government Open Data Portal (CKAN API) for tidal stations
along the Queensland coast.  All QLD data is in AEST (UTC+10) and metres;
this module converts to feet for compatibility with the NOAA-based rendering
pipeline.
"""

from datetime import datetime, timezone, timedelta
import json
import urllib.parse

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json, fetch_json_cached

CACHE_DIR = CACHE_ROOT / "tides"
QLD_BASE = "https://www.data.qld.gov.au/api/3/action/datastore_search"
QLD_RESOURCE_ID = "1311fc19-1e60-444f-b5cf-24687f1c15a7"
M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600
# Queensland does not observe DST; AEST is always UTC+10.
AEST = timezone(timedelta(hours=10))


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def _fetch_all_stations_qld():
    """Fetch the distinct QLD tidal station list (cached 30 days).

    The CKAN datastore_search SQL endpoint lets us pull distinct Site +
    coordinates in one request.
    """
    cache_file = CACHE_DIR / "qld_all_stations.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached is not None:
        return cached

    # Fetch a small sample per station to discover names + coordinates.
    # The API doesn't support SELECT DISTINCT, so we fetch a large batch
    # sorted by Site and deduplicate client-side.
    url = (
        f"{QLD_BASE}?resource_id={QLD_RESOURCE_ID}"
        f"&limit=5000&fields=Site,Latitude,Longitude"
        f"&sort=Site%20asc"
    )
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception:
        stale = read_stale(cache_file)
        return stale if stale else []

    if not data or not isinstance(data, dict):
        return []

    result = data.get("result", {})
    records = result.get("records", [])
    if not records:
        return []

    # Deduplicate by site name, keep first occurrence (has coords).
    seen = set()
    stations = []
    for rec in records:
        name = rec.get("Site", "")
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            lat = float(rec["Latitude"])
            lng = float(rec["Longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        stations.append({"name": name, "lat": lat, "lng": lng})

    write_cache(cache_file, stations)
    return stations


def find_nearest_station_qld(lat, lng):
    """Find closest QLD tide station by haversine distance.

    Returns (station_name, station_name) or (None, None).  Cached 1 hour.
    Note: QLD stations are identified by name, not numeric ID.
    """
    cache_file = CACHE_DIR / f"qld_station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    try:
        stations = _fetch_all_stations_qld()
    except Exception:
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    if not stations:
        return None, None

    best_name, best_dist = None, float("inf")
    best_lat, best_lng = None, None
    for s in stations:
        try:
            slat = float(s["lat"])
            slng = float(s["lng"])
        except (KeyError, ValueError, TypeError):
            continue
        d = haversine_nm(lat, lng, slat, slng)
        if d < best_dist:
            best_dist = d
            best_name = s["name"]
            best_lat = slat
            best_lng = slng

    if best_dist > 100:  # > 100 nautical miles
        return None, None

    # Use station name as the ID (QLD stations have no numeric ID).
    result = {"id": best_name, "name": best_name, "lat": best_lat, "lng": best_lng}
    write_cache(cache_file, result)
    return best_name, best_name


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_qld(station_name):
    """Build QLD station metadata, normalized to match NOAA/CHS shape.

    Returns dict with: id, name, state, lat, lng, timezone_abbr,
    timezonecorr, timeZoneCode, observedst, source.
    """
    safe_name = station_name.replace(" ", "_").replace("/", "_")
    cache_file = CACHE_DIR / f"qld_meta_{safe_name}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "qld":
        return cached

    # Look up coordinates from the station list.
    stations = _fetch_all_stations_qld()
    lat, lng = None, None
    for s in stations:
        if s.get("name") == station_name:
            lat = s.get("lat")
            lng = s.get("lng")
            break

    meta = {
        "id": station_name,
        "name": station_name,
        "state": "QLD",
        "lat": lat,
        "lng": lng,
        "timezone_abbr": "AEST",
        "timezonecorr": 10,
        "timeZoneCode": "Australia/Brisbane",
        "observedst": False,
        "source": "qld",
    }
    write_cache(cache_file, meta)
    return meta


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def _parse_qld_dt(s):
    """Parse QLD datetime string to AEST-aware datetime.

    The CKAN API returns datetimes like '2026-03-27T10:00:00' in AEST.
    """
    s = s.rstrip("Z")
    if "." in s:
        s = s[:s.index(".")]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=AEST)
    return dt


def _parse_cached_dt(iso_str):
    """Parse an ISO datetime string from cache back to AEST-aware datetime."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=AEST)
    return dt


def _aest_range_for_dates(start_date, end_date):
    """Convert date range to AEST datetime strings for filtering."""
    local_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=AEST)
    local_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=AEST) + timedelta(days=1)
    return (local_start.strftime("%Y-%m-%dT%H:%M:%S"),
            local_end.strftime("%Y-%m-%dT%H:%M:%S"))


# ---------------------------------------------------------------------------
# High/low labeling
# ---------------------------------------------------------------------------
def _label_hilo(values):
    """Infer H/L labels from a sequence of extrema (dt, height_ft) tuples.

    QLD data does not label highs vs lows; this compares adjacent
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


def _find_extrema(points):
    """Find local extrema (peaks and troughs) from prediction points.

    Returns list of (dt, height_ft) tuples at turning points.
    """
    if len(points) < 3:
        return list(points)

    extrema = []
    for i in range(1, len(points) - 1):
        dt_prev, h_prev = points[i - 1]
        dt_curr, h_curr = points[i]
        dt_next, h_next = points[i + 1]
        if (h_curr > h_prev and h_curr >= h_next) or (h_curr < h_prev and h_curr <= h_next):
            extrema.append((dt_curr, h_curr))

    return extrema


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def _build_ckan_url(station_name, start_str, end_str, limit=5000):
    """Build a CKAN datastore_search URL with filters."""
    filters = json.dumps({"Site": station_name})
    params = urllib.parse.urlencode({
        "resource_id": QLD_RESOURCE_ID,
        "filters": filters,
        "sort": "DateTime asc",
        "limit": str(limit),
        "fields": "DateTime,Prediction,Water Level",
    })
    # Add date range filter via q parameter if available,
    # but CKAN datastore_search doesn't support range queries in filters.
    # We'll filter client-side after fetching.
    return f"{QLD_BASE}?{params}"


def _fetch_pred_chunk(station_name, start_date, end_date):
    """Fetch a chunk of QLD predictions.

    Returns list of (datetime_aest, height_ft) tuples.
    """
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    safe_name = station_name.replace(" ", "_").replace("/", "_")
    cache_file = CACHE_DIR / f"qld_pred_{safe_name}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"]), r["v"]) for r in cached]

    url = _build_ckan_url(station_name, start_str, end_str)
    data = fetch_json_cached(
        cache_file, 0, url,
        headers={"User-Agent": USER_AGENT},
        timeout=20, fallback=None,
    )
    if not data or not isinstance(data, dict):
        return []

    result = data.get("result", {})
    records = result.get("records", [])
    if not records:
        return []

    # Parse and filter to date range.
    aest_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=AEST)
    aest_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=AEST) + timedelta(days=1)

    rows = []
    points = []
    for rec in records:
        try:
            dt_str = rec.get("DateTime", "")
            if not dt_str:
                continue
            dt_local = _parse_qld_dt(dt_str)

            # Use Prediction field; fall back to Water Level (observed).
            height_m = rec.get("Prediction")
            if height_m is None or height_m == "":
                height_m = rec.get("Water Level")
            if height_m is None or height_m == "":
                continue
            height_m = float(height_m)
            height_ft = height_m * M_TO_FT

            if dt_local < aest_start or dt_local >= aest_end:
                continue

            rows.append({"dt": dt_local.isoformat(), "v": height_ft})
            points.append((dt_local, height_ft))
        except (KeyError, ValueError, TypeError):
            continue

    write_cache(cache_file, rows)
    return points


def fetch_tides_range_qld(station_name, start_date, end_date, station_tz=None):
    """Fetch QLD interval predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    The station_tz parameter is accepted for API compatibility but QLD
    stations are always AEST.
    """
    points = []
    # QLD API returns a rolling ~7-day window, so fetch in day-sized chunks
    # to allow caching and avoid hitting the 5000-record limit.
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=1), end_date)
        chunk = _fetch_pred_chunk(station_name, d, chunk_end)
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


def fetch_hilo_range_qld(station_name, start_date, end_date, station_tz=None):
    """Fetch QLD high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    Derived from prediction data by finding local extrema.
    """
    # Get the full prediction series first.
    preds = fetch_tides_range_qld(station_name, start_date, end_date, station_tz)
    if not preds:
        return []

    # Find turning points.
    extrema = _find_extrema(preds)
    if not extrema:
        return []

    return _label_hilo(extrema)


def fetch_y_range_qld(station_name, center_date, station_tz=None):
    """Compute y-axis range from available QLD prediction data.  Cached 7 days.

    QLD only provides ~7 days of data, so we use whatever is available
    rather than the +-30 day window NOAA/CHS use.
    """
    safe_name = station_name.replace(" ", "_").replace("/", "_")
    start = center_date - timedelta(days=3)
    end = center_date + timedelta(days=3)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"qld_yrange_{safe_name}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    hilo = fetch_hilo_range_qld(station_name, start, end, station_tz)
    if not hilo:
        # Fall back to prediction data directly.
        preds = fetch_tides_range_qld(station_name, start, end, station_tz)
        if not preds:
            return None
        heights = [h for _, h in preds]
    else:
        heights = [h for _, h, _ in hilo]

    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
