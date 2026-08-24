"""Hong Kong Observatory (HKO) tide data source.

Uses the HKO Open Data API for tidal stations around Hong Kong.
All HKO data is in HKT (UTC+8) and metres; this module converts to feet
for compatibility with the NOAA-based rendering pipeline.

Station list is hard-coded (small, stable, no discovery endpoint):
  https://tide1.hydro.gov.hk/hotide/OpenData/station_data.php?station=<code>
"""

from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json

CACHE_DIR = CACHE_ROOT / "tides"
M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600
# Hong Kong does not observe DST; HKT is always UTC+8.
HKT = timezone(timedelta(hours=8))

# Static station table derived from Tidedata_link_geodatastore_converted.csv
_STATIONS = [
    {"id": "ct8", "name": "Kwai Chung",  "lat": 22.323726, "lng": 114.122665},
    {"id": "mwc", "name": "Ma Wan",      "lat": 22.363950, "lng": 114.071347},
    {"id": "chc", "name": "Cheung Chau", "lat": 22.214012, "lng": 114.023014},
    {"id": "klw", "name": "Ko Lau Wan",  "lat": 22.458492, "lng": 114.360616},
    {"id": "skt", "name": "Sha Kiu Tau", "lat": 22.348293, "lng": 114.352831},
]
_HKO_BASE = "https://tide1.hydro.gov.hk/hotide/OpenData/station_data.php"


# ---------------------------------------------------------------------------
# Station discovery (static list — no network call needed)
# ---------------------------------------------------------------------------
def _fetch_all_stations_hko():
    """Return the static HKO station list (no network needed)."""
    return _STATIONS


def find_nearest_station_hko(lat, lng):
    """Find closest HKO tide station by haversine distance.

    Returns (station_id, station_name) or (None, None).  Cached 1 hour.
    Returns None when the nearest station is > 100 nm away.
    """
    cache_file = CACHE_DIR / f"hko_station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    best_id, best_name, best_dist = None, None, float("inf")
    for s in _STATIONS:
        d = haversine_nm(lat, lng, s["lat"], s["lng"])
        if d < best_dist:
            best_dist = d
            best_id = s["id"]
            best_name = s["name"]

    if best_dist > 100:
        return None, None

    result = {"id": best_id, "name": best_name}
    write_cache(cache_file, result)
    return best_id, best_name


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_hko(station_id):
    """Return HKO station metadata normalised to the shared shape."""
    for s in _STATIONS:
        if s["id"] == station_id:
            return {
                "id": station_id,
                "name": s["name"],
                "state": "HK",
                "lat": s["lat"],
                "lng": s["lng"],
                "timezone_abbr": "HKT",
                "timezonecorr": 8,
                "timeZoneCode": "Asia/Hong_Kong",
                "observedst": False,
                "source": "hko",
            }
    return None


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def _parse_hko_dt(s):
    """Parse HKO datetime string 'YYYY-MM-DD HH:MM' to HKT-aware datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=HKT)


def _parse_cached_dt(iso_str):
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def _fetch_pred_day(station_id, date):
    """Fetch one day of HKO predictions.  Returns [(datetime_hkt, height_ft)]."""
    date_str = date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"hko_pred_{station_id}_{date_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"]), r["v"]) for r in cached]

    url = f"{_HKO_BASE}?station={station_id}"
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception:
        stale = read_stale(cache_file)
        if stale:
            return [(_parse_cached_dt(r["dt"]), r["v"]) for r in stale]
        return []

    if not data or not isinstance(data, list):
        return []

    # The API always returns data for "today" from HKO's perspective; filter
    # to the requested date so range fetches stay clean.
    day_start = datetime(date.year, date.month, date.day, tzinfo=HKT)
    day_end = day_start + timedelta(days=1)

    rows = []
    points = []
    for rec in data:
        try:
            dt = _parse_hko_dt(rec["DateTime"])
            height_ft = float(rec["height"]) * M_TO_FT
        except (KeyError, ValueError, TypeError):
            continue
        if day_start <= dt < day_end:
            rows.append({"dt": dt.isoformat(), "v": height_ft})
            points.append((dt, height_ft))

    if rows:
        write_cache(cache_file, rows)
    return points


def fetch_tides_range_hko(station_id, start_date, end_date, station_tz=None):
    """Fetch HKO interval predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    station_tz is accepted for API compatibility but HKO is always HKT.

    Note: the HKO open-data endpoint returns the current day only; for
    dates in the past or future the cache may be empty and the result will
    be an empty list for those days.  The live view and static render will
    both fall through to hilo-based synthesis in that case.
    """
    points = []
    d = start_date
    while d <= end_date:
        points.extend(_fetch_pred_day(station_id, d))
        d += timedelta(days=1)

    seen = set()
    unique = []
    for dt, h in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, h))
    unique.sort(key=lambda p: p[0])
    return unique


# ---------------------------------------------------------------------------
# High/low detection (same approach as QLD)
# ---------------------------------------------------------------------------
def _find_extrema(points):
    if len(points) < 3:
        return list(points)
    extrema = []
    for i in range(1, len(points) - 1):
        _, h_prev = points[i - 1]
        dt_curr, h_curr = points[i]
        _, h_next = points[i + 1]
        if (h_curr > h_prev and h_curr >= h_next) or (h_curr < h_prev and h_curr <= h_next):
            extrema.append((dt_curr, h_curr))
    return extrema


def _label_hilo(values):
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


def fetch_hilo_range_hko(station_id, start_date, end_date, station_tz=None):
    """Derive high/low extremes from the HKO prediction series."""
    preds = fetch_tides_range_hko(station_id, start_date, end_date, station_tz)
    if not preds:
        return []
    extrema = _find_extrema(preds)
    return _label_hilo(extrema) if extrema else []


def fetch_y_range_hko(station_id, center_date, station_tz=None):
    """Y-axis range from a ±3-day window of HKO data.  Cached 7 days."""
    start = center_date - timedelta(days=3)
    end = center_date + timedelta(days=3)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"hko_yrange_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    hilo = fetch_hilo_range_hko(station_id, start, end, station_tz)
    heights = [h for _, h, _ in hilo] if hilo else []
    if not heights:
        preds = fetch_tides_range_hko(station_id, start, end, station_tz)
        heights = [h for _, h in preds]
    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
