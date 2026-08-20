"""NOAA tide data source.

Provides station discovery, station metadata, and tide prediction fetchers
for NOAA's CO-OPS APIs.
"""

import math
from datetime import datetime, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json, fetch_json_cached

CACHE_DIR = CACHE_ROOT / "tides"
NEAREST_STATION_CACHE_MAX_AGE = 3600


def find_nearest_station(lat, lng):
    """Find closest NOAA tide station by distance.

    Returns (station_id, station_name) or (None, None). Cached for 1 hour.
    """
    cache_file = CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    # The full station list is cached for 30 days (with stale fallback),
    # so this works offline and never re-downloads per location.
    stations = fetch_all_stations_noaa()
    if not stations:
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    best_id, best_name, best_dist = None, None, float("inf")
    for station in stations:
        # Subordinate stations (type "S") only publish high/low predictions;
        # the 6-minute series this chart needs comes back as an error. Only
        # reference stations (type "R") are eligible for auto-pick.
        if station.get("type", "R") != "R":
            continue
        try:
            station_lat = float(station["lat"])
            station_lng = float(station["lng"])
        except (KeyError, ValueError):
            continue
        distance = haversine_nm(lat, lng, station_lat, station_lng)
        if distance < best_dist:
            best_dist = distance
            best_id = str(station.get("id", ""))
            best_name = station.get("name", "")

    if best_dist > 100:
        return None, None

    result = {"id": best_id, "name": best_name, "lat": lat, "lng": lng}
    write_cache(cache_file, result)
    return best_id, best_name


def fetch_station_metadata_noaa(station_id):
    """Fetch NOAA station metadata needed for timezone handling."""
    cache_file = CACHE_DIR / f"station_meta_{station_id}.json"
    url = (
        "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
        f"stations/{station_id}.json?expand=details"
    )
    data = fetch_json_cached(
        cache_file,
        30 * 86400,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )
    if not data:
        return None
    if "timezone_abbr" in data:
        return data

    stations = data.get("stations", [])
    if not stations:
        return None
    station = stations[0]
    details = station.get("details", {})
    meta = {
        "id": str(station.get("id", station_id)),
        "name": station.get("name", ""),
        "state": station.get("state", ""),
        "lat": station.get("lat"),
        "lng": station.get("lng"),
        "timezone_abbr": str(station.get("timezone", "")).upper(),
        "timezonecorr": station.get("timezonecorr", details.get("timezone")),
        "observedst": bool(station.get("observedst", False)),
    }
    write_cache(cache_file, meta)
    return meta


def _prediction_url(station_id, begin_date, end_date, interval):
    return (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?begin_date={begin_date}&end_date={end_date}"
        f"&station={station_id}&product=predictions&datum=MLLW"
        f"&units=english&time_zone=lst_ldt&interval={interval}&format=json"
    )


def _fetch_payload(cache_file, max_age, url, fallback=None):
    """Read fresh cache, otherwise fetch JSON with stale-cache fallback."""
    cached = read_cache(cache_file, max_age)
    if cached is not None:
        return cached
    return fetch_json_cached(
        cache_file,
        0,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=fallback,
    )


def _parse_prediction_hour(time_str):
    try:
        parts = time_str.split(" ")
        time_parts = parts[1].split(":")
        return int(time_parts[0]) + int(time_parts[1]) / 60
    except (IndexError, ValueError):
        return None


def _build_tide_row(prediction):
    hour = _parse_prediction_hour(prediction.get("t", ""))
    if hour is None:
        return None
    return {"h": hour, "v": float(prediction.get("v", 0))}


def _build_hilo_row(prediction):
    row = _build_tide_row(prediction)
    if row is None:
        return None
    row["t"] = prediction.get("type", "")
    return row


def _fetch_prediction_rows(cache_file, url, row_builder, tuple_builder):
    """Fetch NOAA prediction payload and return parsed tuple rows."""
    data = _fetch_payload(cache_file, 86400, url, fallback=None)
    if not data:
        return None
    if isinstance(data, list):
        return [tuple_builder(row) for row in data]

    predictions = data.get("predictions", [])
    if not predictions:
        # NOAA reports "no data" as an HTTP 200 JSON error payload, which
        # fetch_json_cached has just written to disk; drop it so the miss
        # isn't served as fresh cache for the next 24 hours.
        try:
            cache_file.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    rows = []
    for prediction in predictions:
        row = row_builder(prediction)
        if row is not None:
            rows.append(row)
    write_cache(cache_file, rows)
    return [tuple_builder(row) for row in rows]


def fetch_tides(station_id, date):
    """Fetch 6-minute interval tide predictions for a date."""
    date_str = date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"pred_{station_id}_{date_str}.json"
    url = _prediction_url(station_id, date_str, date_str, "6")
    return _fetch_prediction_rows(
        cache_file,
        url,
        row_builder=_build_tide_row,
        tuple_builder=lambda row: (row["h"], row["v"]),
    )


def fetch_hilo(station_id, date):
    """Fetch high/low extremes for a date."""
    date_str = date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"hilo_{station_id}_{date_str}.json"
    url = _prediction_url(station_id, date_str, date_str, "hilo")
    return _fetch_prediction_rows(
        cache_file,
        url,
        row_builder=_build_hilo_row,
        tuple_builder=lambda row: (row["h"], row["v"], row["t"]),
    )


def fetch_all_stations_noaa():
    """Fetch the full NOAA tide-prediction station list (cached 30 days)."""
    cache_file = CACHE_DIR / "all_stations.json"
    url = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
    data = _fetch_payload(cache_file, 30 * 86400, url, fallback=[])
    if isinstance(data, list):
        return data
    stations = data.get("stations", [])
    write_cache(cache_file, stations)
    return stations


def day_to_dt(hour_decimal, date, station_tz):
    """Convert a day-relative decimal hour to an aware datetime."""
    hour = int(hour_decimal)
    minute = int(round((hour_decimal - hour) * 60))
    if hour >= 24:
        date = date + timedelta(days=1)
        hour -= 24
    try:
        dt = datetime(date.year, date.month, date.day, hour, minute)
    except ValueError:
        return None
    if station_tz is not None:
        dt = dt.replace(tzinfo=station_tz)
    return dt


def synthesize_tides_from_hilo(hilo_points, step_minutes=6):
    """Approximate a tide curve from hi/lo extremes by cosine interpolation.

    Subordinate NOAA stations only publish high/low predictions. Between two
    extremes the water level closely follows half a cosine cycle (the model
    behind the sailor's rule of twelfths), which is also how those stations'
    published offsets are meant to be used. Takes [(datetime, height, type)]
    and returns [(datetime, height)] sampled every *step_minutes*.
    """
    pts = sorted(hilo_points, key=lambda p: p[0])
    if len(pts) < 2:
        return []
    out = []
    step = timedelta(minutes=step_minutes)
    for (t1, h1, _), (t2, h2, _) in zip(pts, pts[1:]):
        span = (t2 - t1).total_seconds()
        # Skip duplicates and gaps too wide to be adjacent extremes
        # (a semidiurnal half-cycle is ~6h12m; diurnal ~12h25m).
        if span <= 0 or span > 16 * 3600:
            continue
        t = t1
        while t < t2:
            frac = (t - t1).total_seconds() / span
            height = h1 + (h2 - h1) * (1 - math.cos(math.pi * frac)) / 2
            out.append((t, height))
            t += step
    if out:
        out.append(pts[-1][:2])
    return out


def fetch_tides_range(station_id, start_date, end_date, station_tz):
    """Fetch and stitch tide predictions across a date range."""
    points = []
    day = start_date
    while day <= end_date:
        day_data = fetch_tides(station_id, day)
        if day_data:
            for hour, height in day_data:
                dt = day_to_dt(hour, day, station_tz)
                if dt is not None:
                    points.append((dt, height))
        day += timedelta(days=1)

    seen = set()
    unique = []
    for dt, height in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, height))
    unique.sort(key=lambda point: point[0])
    return unique


def fetch_hilo_range(station_id, start_date, end_date, station_tz):
    """Fetch and stitch hi/lo extremes across a date range."""
    points = []
    day = start_date
    while day <= end_date:
        day_data = fetch_hilo(station_id, day)
        if day_data:
            for hour, height, typ in day_data:
                dt = day_to_dt(hour, day, station_tz)
                if dt is not None:
                    points.append((dt, height, typ))
        day += timedelta(days=1)
    points.sort(key=lambda point: point[0])
    return points


def fetch_y_range(station_id, center_date):
    """Compute y-axis range from +/-30 days of hilo data."""
    start = (center_date - timedelta(days=30)).strftime("%Y%m%d")
    end = (center_date + timedelta(days=30)).strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"yrange_{station_id}_{start}_{end}.json"

    cached = read_cache(cache_file, 7 * 86400)
    if cached is not None:
        return (cached["min"], cached["max"])

    url = _prediction_url(station_id, start, end, "hilo")
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception:
        return None

    predictions = data.get("predictions", []) if data else []
    if not predictions:
        return None

    heights = []
    for prediction in predictions:
        try:
            heights.append(float(prediction["v"]))
        except (KeyError, ValueError):
            pass

    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])
