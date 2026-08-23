"""Queensland (Australia) tide data source.

Uses the Queensland Government Open Data Portal (CKAN API) for tidal stations
along the Queensland coast.  All QLD data is in AEST (UTC+10) and metres;
this module converts to feet for compatibility with the NOAA-based rendering
pipeline.
"""

from datetime import timezone, timedelta
import json
import urllib.parse

from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._http import fetch_json, fetch_json_cached
from linecast._tides_common import (
    CACHE_DIR, M_TO_FT, cached_y_range, dedup_sorted, label_hilo,
    local_day_bounds, nearest_station, parse_cached_dt, parse_iso,
    station_coords, y_range_window,
)

QLD_BASE = "https://www.data.qld.gov.au/api/3/action/datastore_search"
QLD_RESOURCE_ID = "1311fc19-1e60-444f-b5cf-24687f1c15a7"
# Queensland does not observe DST; AEST is always UTC+10.
AEST = timezone(timedelta(hours=10))


def _safe_name(station_name):
    """A station name as a cache file name component."""
    return station_name.replace(" ", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def fetch_all_stations_qld():
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
        data = fetch_json(url, timeout=15)
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
    QLD stations are identified by name, not numeric ID.
    """
    return nearest_station(
        CACHE_DIR / f"qld_station_{location_cache_key(lat, lng)}.json", lat, lng,
        fetch_all_stations_qld, station_coords,
        lambda s: (s["name"], s["name"]),
    )


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_qld(station_name):
    """Build QLD station metadata, normalized to match NOAA/CHS shape.

    Returns dict with: id, name, state, lat, lng, timezone_abbr,
    timezonecorr, timeZoneCode, observedst, source.
    """
    cache_file = CACHE_DIR / f"qld_meta_{_safe_name(station_name)}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "qld":
        return cached

    # Look up coordinates from the station list.
    stations = fetch_all_stations_qld()
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
    dt = parse_iso(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=AEST)
    return dt


# ---------------------------------------------------------------------------
# High/low detection
# ---------------------------------------------------------------------------
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
def _build_ckan_url(station_name, limit=5000):
    """Build a CKAN datastore_search URL for one station's records.

    datastore_search cannot filter on a date range, so the caller trims
    the records to its dates after fetching.
    """
    filters = json.dumps({"Site": station_name})
    params = urllib.parse.urlencode({
        "resource_id": QLD_RESOURCE_ID,
        "filters": filters,
        "sort": "DateTime asc",
        "limit": str(limit),
        "fields": "DateTime,Prediction,Water Level",
    })
    return f"{QLD_BASE}?{params}"


def _fetch_pred_chunk(station_name, start_date, end_date):
    """Fetch a chunk of QLD predictions.

    Returns list of (datetime_aest, height_ft) tuples.
    """
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"qld_pred_{_safe_name(station_name)}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(parse_cached_dt(r["dt"], AEST), r["v"]) for r in cached]

    url = _build_ckan_url(station_name)
    data = fetch_json_cached(
        cache_file, 0, url,
        timeout=20, fallback=None,
    )
    if not data or not isinstance(data, dict):
        return []

    result = data.get("result", {})
    records = result.get("records", [])
    if not records:
        return []

    # Parse and filter to date range.
    aest_start, aest_end = local_day_bounds(start_date, end_date, AEST)

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
    return dedup_sorted(points)


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

    return label_hilo(extrema)


def fetch_y_range_qld(station_name, center_date, station_tz=None):
    """Compute y-axis range from available QLD prediction data.  Cached 7 days.

    QLD only provides ~7 days of data, so the range comes from the three
    days either side of the date rather than the month-long window the
    other providers use; the cache key is still month-anchored (see
    y_range_window) so consecutive days share one file.
    """
    _, _, key = y_range_window(center_date)
    start = center_date - timedelta(days=3)
    end = center_date + timedelta(days=3)

    def heights():
        hilo = fetch_hilo_range_qld(station_name, start, end, station_tz)
        if hilo:
            return [h for _, h, _ in hilo]
        # Fall back to prediction data directly.
        return [h for _, h in fetch_tides_range_qld(station_name, start, end, station_tz)]

    return cached_y_range(
        CACHE_DIR / f"qld_yrange_{_safe_name(station_name)}_{key}.json", heights)
