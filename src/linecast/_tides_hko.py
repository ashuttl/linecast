"""Hong Kong Observatory (HKO) tide data source.

Uses the HKO Open Data API (data.weather.gov.hk) for tidal predictions:
  HHOT — Hourly heights of astronomical tides  (full series, per year)
  HLT  — Times and heights of high/low tides   (extrema, per year)

Both endpoints require a station code and a year:
  https://data.weather.gov.hk/weatherAPI/opendata/opendata.php
    ?dataType=HHOT&station=CCH&year=2026&rformat=json

All HKO data is in HKT (UTC+8) and metres; heights are converted to feet
for compatibility with the NOAA-based rendering pipeline.

Station table: 12 active stations from HHOT dataset.
Excluded stations (decommissioned, data is computer-simulated per HKO):
  CMW — Chi Ma Wan, closed 1997
  LOP — Lok On Pai, closed 1999
"""

from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import (
    CACHE_ROOT,
    location_cache_key,
    read_cache,
    read_stale,
    write_cache,
)
from linecast._geo import haversine_nm
from linecast._http import fetch_json

CACHE_DIR = CACHE_ROOT / "tides"
M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600
# Hong Kong does not observe DST; HKT is always UTC+8.
HKT = timezone(timedelta(hours=8))

_HKO_PRED_BASE = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php"

# ---------------------------------------------------------------------------
# Station table — coordinates and names from HHOT_HHOT_converted_2.csv
# (authoritative HKO geodatastore source, EPSG:4326).
# Decommissioned stations excluded (CMW closed 1997, LOP closed 1999).
# ---------------------------------------------------------------------------
_STATIONS = [
    {"id": "CCH", "name": "Cheung Chau", "lat": 22.214167, "lng": 114.023056},
    {"id": "CLK", "name": "Chek Lap Kok (E)", "lat": 22.320556, "lng": 113.945278},
    {"id": "KCT", "name": "Kwai Chung", "lat": 22.323611, "lng": 114.122778},
    {"id": "KLW", "name": "Ko Lau Wan", "lat": 22.458611, "lng": 114.360833},
    {"id": "MWC", "name": "Ma Wan", "lat": 22.363889, "lng": 114.071389},
    {"id": "PT1", "name": "Po Toi", "lat": 22.163300, "lng": 114.253100},
    {"id": "QUB", "name": "Quarry Bay", "lat": 22.291111, "lng": 114.213333},
    {"id": "SPW", "name": "Shek Pik", "lat": 22.220278, "lng": 113.894444},
    {"id": "TAO", "name": "Tai O", "lat": 22.255000, "lng": 113.865556},
    {"id": "TBT", "name": "Tsim Bei Tsui", "lat": 22.487222, "lng": 114.014167},
    {"id": "TMW", "name": "Tai Miu Wan", "lat": 22.269722, "lng": 114.288611},
    {"id": "TPK", "name": "Tai Po Kau", "lat": 22.442500, "lng": 114.183889},
    {"id": "WAG", "name": "Waglan Island", "lat": 22.183056, "lng": 114.302778},
]

# Backwards-compatibility: map old hotide real-time codes → prediction codes.
# Used when a user specifies --station with a hotide code (ct8, chc, etc.).
_HOTIDE_TO_HKO = {
    "chc": "CCH",
    "ct8": "KCT",
    "klw": "KLW",
    "mwc": "MWC",
    # skt has no prediction data and is intentionally absent
}

_STATION_BY_ID = {s["id"]: s for s in _STATIONS}


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
    """Return HKO station metadata normalised to the shared shape.

    Accepts both prediction codes (CCH) and legacy hotide codes (chc).
    """
    # Remap legacy hotide codes transparently
    hko_id = _HOTIDE_TO_HKO.get(station_id, station_id).upper()
    s = _STATION_BY_ID.get(hko_id)
    if s is None:
        return None
    return {
        "id": hko_id,
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


# ---------------------------------------------------------------------------
# Internal: prediction API helpers
# ---------------------------------------------------------------------------
def _resolve_id(station_id):
    """Normalise station_id: hotide codes → HKO prediction codes."""
    return _HOTIDE_TO_HKO.get(station_id, station_id).upper()


def _pred_url(data_type, hko_code, year):
    return (
        f"{_HKO_PRED_BASE}"
        f"?dataType={data_type}&station={hko_code}&year={year}&rformat=json"
    )


def _fetch_year_raw(data_type, station_id, year):
    """Fetch one year of HHOT or HLT data.

    Past years cached 30 days (predictions never change); current year 24 h.
    Returns the raw 'data' list from the API, or [] on failure.
    """
    hko_code = _resolve_id(station_id)
    if hko_code not in _STATION_BY_ID:
        return []

    cache_file = CACHE_DIR / f"hko_{data_type.lower()}_{hko_code}_{year}.json"
    now_year = datetime.now(HKT).year
    max_age = 30 * 86400 if year < now_year else 86400

    cached = read_cache(cache_file, max_age)
    if cached is not None:
        return cached

    url = _pred_url(data_type, hko_code, year)
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    except Exception:
        stale = read_stale(cache_file)
        return stale if stale is not None else []

    if not data or not isinstance(data, dict):
        return []

    rows = data.get("data", [])
    if rows:
        write_cache(cache_file, rows)
    return rows


def _parse_cached_dt(iso_str):
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt


# ---------------------------------------------------------------------------
# HHOT — hourly heights series
# ---------------------------------------------------------------------------
def _hhot_rows_to_points(rows, year):
    """Parse HHOT raw rows into (datetime_hkt, height_ft) tuples.

    Each row: [MM, DD, h_at_01, h_at_02, ..., h_at_24]
    Hour columns are labelled '01'–'24' (HKT local time, 1-based).
    """
    points = []
    for row in rows:
        try:
            month = int(row[0])
            day = int(row[1])
        except (IndexError, ValueError, TypeError):
            continue
        for hour_idx in range(24):
            col = hour_idx + 2  # columns 2..25 → hours 01..24
            val = row[col] if col < len(row) else ""
            if val == "" or val is None:
                continue
            try:
                height_ft = float(val) * M_TO_FT
            except (ValueError, TypeError):
                continue
            # hour label is 1-based: col index 2 = 01:00 HKT
            hour = hour_idx + 1
            if hour == 24:
                # 24:00 = midnight of the following day
                try:
                    dt = datetime(year, month, day, 0, 0, tzinfo=HKT) + timedelta(
                        days=1
                    )
                except ValueError:
                    continue
            else:
                try:
                    dt = datetime(year, month, day, hour, 0, tzinfo=HKT)
                except ValueError:
                    continue
            points.append((dt, height_ft))
    return points


def _fetch_hhot_year(station_id, year):
    """Return list of (datetime_hkt, height_ft) for a full year via HHOT."""
    hko_code = _resolve_id(station_id)
    cache_file = CACHE_DIR / f"hko_hhot_pts_{hko_code}_{year}.json"
    now_year = datetime.now(HKT).year
    max_age = 30 * 86400 if year < now_year else 86400

    cached = read_cache(cache_file, max_age)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"]), r["v"]) for r in cached]

    rows = _fetch_year_raw("HHOT", station_id, year)
    if not rows:
        return []

    points = _hhot_rows_to_points(rows, year)
    cache_rows = [{"dt": dt.isoformat(), "v": v} for dt, v in points]
    if cache_rows:
        write_cache(cache_file, cache_rows)
    return points


# ---------------------------------------------------------------------------
# HLT — high/low extrema
# ---------------------------------------------------------------------------
def _label_hilo(values):
    """Assign H/L by comparing each point against its neighbours."""
    if not values:
        return []
    if len(values) == 1:
        return [(values[0][0], values[0][1], "H")]
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


def _hlt_rows_to_hilo(rows, year):
    """Parse HLT raw rows into (datetime_hkt, height_ft, 'H'|'L') tuples.

    Each row: [Month, Date, Time1, Height1, Time2, Height2, Time3, Height3, Time4, Height4]
    Up to 4 events per day; empty string signals fewer events that day.
    H/L labels are derived by comparison with adjacent events.
    """
    raw = []
    for row in rows:
        try:
            month = int(row[0])
            day = int(row[1])
        except (IndexError, ValueError, TypeError):
            continue
        for slot in range(4):
            t_col = 2 + slot * 2
            h_col = 3 + slot * 2
            t_str = row[t_col] if t_col < len(row) else ""
            h_str = row[h_col] if h_col < len(row) else ""
            if not t_str:
                break
            try:
                hhmm = t_str.zfill(4)
                hour = int(hhmm[:2])
                minute = int(hhmm[2:])
                height_ft = float(h_str) * M_TO_FT
            except (ValueError, TypeError):
                continue
            try:
                dt = datetime(year, month, day, hour, minute, tzinfo=HKT)
            except ValueError:
                continue
            raw.append((dt, height_ft))

    raw.sort(key=lambda p: p[0])
    return _label_hilo(raw)


def _fetch_hlt_year(station_id, year):
    """Return list of (datetime_hkt, height_ft, 'H'|'L') for a full year via HLT."""
    hko_code = _resolve_id(station_id)
    cache_file = CACHE_DIR / f"hko_hlt_pts_{hko_code}_{year}.json"
    now_year = datetime.now(HKT).year
    max_age = 30 * 86400 if year < now_year else 86400

    cached = read_cache(cache_file, max_age)
    if cached is not None:
        return [(_parse_cached_dt(r["dt"]), r["v"], r["t"]) for r in cached]

    rows = _fetch_year_raw("HLT", station_id, year)
    if not rows:
        return []

    hilo = _hlt_rows_to_hilo(rows, year)
    cache_rows = [{"dt": dt.isoformat(), "v": v, "t": t} for dt, v, t in hilo]
    if cache_rows:
        write_cache(cache_file, cache_rows)
    return hilo


# ---------------------------------------------------------------------------
# Public range fetchers
# ---------------------------------------------------------------------------
def _years_for_range(start_date, end_date):
    return list(range(start_date.year, end_date.year + 1))


def fetch_tides_range_hko(station_id, start_date, end_date, station_tz=None):
    """Fetch HKO hourly predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    station_tz is accepted for API compatibility but HKO is always HKT.
    """
    window_start = datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=HKT
    )
    window_end = datetime(
        end_date.year, end_date.month, end_date.day, tzinfo=HKT
    ) + timedelta(days=1)

    points = []
    for year in _years_for_range(start_date, end_date):
        for dt, h in _fetch_hhot_year(station_id, year):
            if window_start <= dt < window_end:
                points.append((dt, h))

    points.sort(key=lambda p: p[0])
    return points


def fetch_hilo_range_hko(station_id, start_date, end_date, station_tz=None):
    """Fetch HKO high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, 'H'|'L') tuples.
    """
    window_start = datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=HKT
    )
    window_end = datetime(
        end_date.year, end_date.month, end_date.day, tzinfo=HKT
    ) + timedelta(days=1)

    hilo = []
    for year in _years_for_range(start_date, end_date):
        for dt, h, t in _fetch_hlt_year(station_id, year):
            if window_start <= dt < window_end:
                hilo.append((dt, h, t))

    hilo.sort(key=lambda p: p[0])
    return hilo


def fetch_y_range_hko(station_id, center_date, station_tz=None):
    """Y-axis range from ±30 days of HLT data.  Cached 7 days."""
    start = center_date - timedelta(days=30)
    end = center_date + timedelta(days=30)
    hko_code = _resolve_id(station_id)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"hko_yrange_{hko_code}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    hilo = fetch_hilo_range_hko(station_id, start, end, station_tz)
    heights = [h for _, h, _ in hilo]
    if not heights:
        preds = fetch_tides_range_hko(station_id, start, end, station_tz)
        heights = [h for _, h in preds]
    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
