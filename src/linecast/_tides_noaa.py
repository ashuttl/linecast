"""NOAA tide data source.

Provides station discovery, station metadata, and tide prediction fetchers
for NOAA's CO-OPS APIs.
"""

import math
from datetime import datetime, timedelta

from linecast import USER_AGENT
from linecast._cache import location_cache_key, read_cache, write_cache
from linecast._http import fetch_json, fetch_json_cached
from linecast._tides_common import (
    CACHE_DIR, cached_y_range, month_after, month_start, nearest_station,
    station_coords, y_range_window,
)

PREDICTION_CACHE_MAX_AGE = 86400


def _reference_station_coords(station):
    """Coordinates of a reference station; None for a subordinate one.

    Subordinate stations (type "S") only publish high/low predictions;
    the 6-minute series this chart needs comes back as an error. Only
    reference stations (type "R") are eligible for auto-pick.
    """
    if station.get("type", "R") != "R":
        return None
    return station_coords(station)


def find_nearest_station(lat, lng):
    """Find the closest NOAA reference station by distance.

    Returns (station_id, station_name) or (None, None). Cached for 1 hour.
    The full station list is cached for 30 days (with stale fallback), so
    this works offline and never re-downloads per location.
    """
    return nearest_station(
        CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json", lat, lng,
        fetch_all_stations_noaa, _reference_station_coords,
        lambda s: (str(s.get("id", "")), s.get("name", "")),
    )


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


def _row_dt(time_str, station_tz):
    """Turn NOAA's "YYYY-MM-DD HH:MM" into a datetime, aware if a tz is given."""
    try:
        dt = datetime(int(time_str[0:4]), int(time_str[5:7]), int(time_str[8:10]),
                      int(time_str[11:13]), int(time_str[14:16]))
    except (TypeError, ValueError):
        return None
    if station_tz is not None:
        dt = dt.replace(tzinfo=station_tz)
    return dt


def _row_hour(time_str):
    """Decimal hour of day from a NOAA "YYYY-MM-DD HH:MM" timestamp."""
    return int(time_str[11:13]) + int(time_str[14:16]) / 60


def _build_tide_row(prediction):
    """Cache row for one sample: ["YYYY-MM-DD HH:MM", height_ft]."""
    time_str = prediction.get("t", "")
    if _row_dt(time_str, None) is None:
        return None
    try:
        return [time_str, float(prediction.get("v", 0))]
    except (TypeError, ValueError):
        return None


def _build_hilo_row(prediction):
    """Cache row for one extreme: ["YYYY-MM-DD HH:MM", height_ft, "H"/"L"]."""
    row = _build_tide_row(prediction)
    if row is None:
        return None
    row.append(prediction.get("type", ""))
    return row


def _fetch_prediction_rows(cache_file, url, row_builder):
    """Fetch a NOAA prediction payload and return its cache rows."""
    data = _fetch_payload(cache_file, PREDICTION_CACHE_MAX_AGE, url, fallback=None)
    if not data:
        return None
    if isinstance(data, list):
        return data

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
    return rows


def _months_covering(start_date, end_date):
    """First-of-month dates for every calendar month the range touches."""
    first = month_start(start_date)
    months = []
    while first <= end_date:
        months.append(first)
        first = month_after(first)
    return months


def fetch_month(station_id, first, interval):
    """Fetch one calendar month of predictions, cached per station and month.

    NOAA serves at most 31 days of 6-minute predictions per request, so a
    calendar month is the largest chunk that always fits. Chunking on the
    calendar rather than on the caller's window means every window in the
    same month reads the same file: a day's view, the live view's two
    weeks, and the expansion when the user scrolls all share it, and the
    file stays valid from one day to the next.
    """
    kind = "hilo" if interval == "hilo" else "pred"
    cache_file = CACHE_DIR / f"{kind}_{station_id}_{first:%Y%m}.json"
    last = month_after(first) - timedelta(days=1)
    url = _prediction_url(station_id, first.strftime("%Y%m%d"),
                          last.strftime("%Y%m%d"), interval)
    builder = _build_hilo_row if kind == "hilo" else _build_tide_row
    return _fetch_prediction_rows(cache_file, url, builder)


def _rows_in_range(station_id, start_date, end_date, interval):
    """Cache rows for every month the range touches, trimmed to the range."""
    lo, hi = start_date.isoformat(), end_date.isoformat()
    rows = []
    for first in _months_covering(start_date, end_date):
        for row in fetch_month(station_id, first, interval) or []:
            if lo <= row[0][:10] <= hi:
                rows.append(row)
    return rows


def fetch_tides(station_id, date):
    """6-minute predictions for one date as [(hour_of_day, height_ft)]."""
    rows = fetch_month(station_id, month_start(date), "6")
    if rows is None:
        return None
    day = date.isoformat()
    return [(_row_hour(t), v) for t, v in rows if t[:10] == day]


def fetch_hilo(station_id, date):
    """High/low extremes for one date as [(hour_of_day, height_ft, "H"/"L")]."""
    rows = fetch_month(station_id, month_start(date), "hilo")
    if rows is None:
        return None
    day = date.isoformat()
    return [(_row_hour(t), v, typ) for t, v, typ in rows if t[:10] == day]


_stations_memo = None


def fetch_all_stations_noaa():
    """Fetch the full NOAA tide-prediction station list (cached 30 days).

    Parsing the 1.5 MB list costs about 10 ms and one run consults it
    several times (picking the station, the subordinate check before each
    fetch, the same check in render), so the parsed list is kept for the
    life of the process.
    """
    global _stations_memo
    if _stations_memo is not None:
        return _stations_memo
    cache_file = CACHE_DIR / "all_stations.json"
    url = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
    data = _fetch_payload(cache_file, 30 * 86400, url, fallback=[])
    if isinstance(data, list):
        stations = data
    else:
        stations = data.get("stations", [])
        write_cache(cache_file, stations)
    if stations:
        _stations_memo = stations
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
    """6-minute predictions across a date range as sorted [(datetime, height_ft)]."""
    points = []
    for time_str, height in _rows_in_range(station_id, start_date, end_date, "6"):
        dt = _row_dt(time_str, station_tz)
        if dt is not None:
            points.append((dt, height))
    points.sort(key=lambda point: point[0])
    return points


def fetch_hilo_range(station_id, start_date, end_date, station_tz):
    """High/low extremes across a date range as sorted [(datetime, height_ft, type)]."""
    points = []
    for time_str, height, typ in _rows_in_range(station_id, start_date, end_date, "hilo"):
        dt = _row_dt(time_str, station_tz)
        if dt is not None:
            points.append((dt, height, typ))
    points.sort(key=lambda point: point[0])
    return points


def is_subordinate_station(station_id):
    """True when the station list marks this station type "S".

    Subordinate stations only publish high/low predictions — asking for the
    6-minute series is a guaranteed error, so callers skip straight to
    synthesis. Unknown stations read as reference (try the real series).
    """
    for s in (fetch_all_stations_noaa() or []):
        if str(s.get("id", "")) == str(station_id):
            return s.get("type") == "S"
    return False


def fetch_tides_range_with_fallback(station_id, start_date, end_date, station_tz):
    """6-minute range; subordinate stations get a synthesized curve.

    The extra day of hi/lo on each side keeps the cosine segments anchored
    right up to the window edges.
    """
    if not is_subordinate_station(station_id):
        preds = fetch_tides_range(station_id, start_date, end_date, station_tz)
        if preds:
            return preds
    hilo = fetch_hilo_range(station_id, start_date - timedelta(days=1),
                            end_date + timedelta(days=1), station_tz)
    return synthesize_tides_from_hilo(hilo)


def fetch_y_range(station_id, center_date):
    """Compute the y-axis range from hilo data around the date. Cached 7 days.

    The window and cache key are month-anchored (see y_range_window) so
    consecutive days share one request and one file.
    """
    start, end, key = y_range_window(center_date)

    def heights():
        url = _prediction_url(station_id, start.strftime("%Y%m%d"),
                              end.strftime("%Y%m%d"), "hilo")
        try:
            data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        except Exception:
            return None
        found = []
        for prediction in (data.get("predictions", []) if data else []):
            try:
                found.append(float(prediction["v"]))
            except (KeyError, ValueError):
                pass
        return found

    return cached_y_range(CACHE_DIR / f"yrange_{station_id}_{key}.json", heights)
