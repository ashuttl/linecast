"""NOAA tide data source.

Provides station discovery, station metadata, and tide prediction fetchers
for NOAA's CO-OPS APIs.
"""

import math
import threading
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._log import log_failure, log_skipped
from linecast.tides.common import (
    cache_dir, cached_y_range, month_after, month_start, nearest_station,
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


def find_nearest_station(lat: float, lng: float) -> tuple[str | None, str | None]:
    """Find the closest NOAA reference station by distance.

    Returns (station_id, station_name) or (None, None). Cached for 1 hour.
    The full station list is cached for 30 days (with stale fallback), so
    this works offline and never re-downloads per location.
    """
    return nearest_station(
        cache_dir() / f"station_{location_cache_key(lat, lng)}.json", lat, lng,
        fetch_all_stations_noaa, _reference_station_coords,
        lambda s: (str(s.get("id", "")), s.get("name", "")),
        tag="tides/noaa",
    )


def fetch_station_metadata_noaa(station_id: str) -> dict[str, Any] | None:
    """Fetch NOAA station metadata needed for timezone handling."""
    url = (
        "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
        f"stations/{station_id}.json?expand=details"
    )
    meta = fetch_json_cached(
        cache_dir() / f"station_meta_{station_id}.json", 30 * 86400, url,
        timeout=10, fallback=None, provider="tides/noaa",
        transform=lambda data: _station_meta(data, station_id),
    )
    # A file from before the metadata was parsed on the way in can hold
    # mdapi's own answer, one that named no station.
    if not meta or "timezone_abbr" not in meta:
        return None
    return _with_reference_clock(meta)


def _station_meta(data, station_id):
    """mdapi's answer for a station, as the metadata the view reads."""
    stations = data.get("stations") or []
    if not stations:
        raise LookupError(f"no station {station_id} in the answer")
    station = stations[0]
    details = station.get("details") or {}
    return {
        "id": str(station.get("id", station_id)),
        "name": station.get("name", ""),
        "state": station.get("state", ""),
        "lat": station.get("lat"),
        "lng": station.get("lng"),
        "timezone_abbr": str(station.get("timezone", "")).upper(),
        "timezonecorr": station.get("timezonecorr", details.get("timezone")),
        "observedst": bool(station.get("observedst", False)),
    }


def _with_reference_clock(meta):
    """A subordinate station's metadata, with its reference station's clock.

    mdapi names no zone for a subordinate station and says it keeps no
    summer time, but NOAA's local-time predictions for it are on its
    reference station's clock: Back Cove's are on Portland's EDT, and
    Veracruz's on Tampico's CDT.  Taken where the two keep the same
    standard offset; elsewhere the offset alone stands.
    """
    if meta.get("timezone_abbr"):
        return meta
    ref = next((str(s.get("reference_id") or "") for s in fetch_all_stations_noaa()
                if str(s.get("id", "")) == str(meta.get("id"))), "")
    ref_meta = fetch_station_metadata_noaa(ref) if ref and ref != meta.get("id") else None
    if (not ref_meta or not ref_meta.get("timezone_abbr")
            or ref_meta.get("timezonecorr") != meta.get("timezonecorr")):
        return meta
    return {**meta, "timezone_abbr": ref_meta["timezone_abbr"],
            "observedst": ref_meta.get("observedst", False)}


def _prediction_url(station_id, begin_date, end_date, interval):
    return (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?begin_date={begin_date}&end_date={end_date}"
        f"&station={station_id}&product=predictions&datum=MLLW"
        f"&units=english&time_zone=lst_ldt&interval={interval}&format=json"
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
    rows = fetch_json_cached(
        cache_file, PREDICTION_CACHE_MAX_AGE, url, timeout=10, fallback=None,
        provider="tides/noaa", transform=lambda data: _prediction_rows(data, row_builder))
    # A file from before the rows were parsed on the way in can hold
    # NOAA's own answer, left where parsing it failed.
    return rows if isinstance(rows, list) else None


def _prediction_rows(data, row_builder):
    """The cache rows for a prediction payload's samples.

    NOAA reports "no data" as an HTTP 200 JSON error payload. That is no
    answer, and raising keeps it out of the cache, where it would be
    served as fresh for the next 24 hours.
    """
    predictions = data.get("predictions") or []
    if not predictions:
        error = data.get("error") or {}
        raise ValueError(error.get("message") or "no predictions in the answer")
    rows = []
    for prediction in predictions:
        row = row_builder(prediction)
        if row is not None:
            rows.append(row)
    log_skipped("tides/noaa", "prediction rows",
                len(predictions) - len(rows), len(predictions))
    return rows


def _months_covering(start_date, end_date):
    """First-of-month dates for every calendar month the range touches."""
    first = month_start(start_date)
    months = []
    while first <= end_date:
        months.append(first)
        first = month_after(first)
    return months


# cache file name -> lock held while that month fetches
_month_locks: dict[str, threading.Lock] = {}
_month_locks_lock = threading.Lock()


def _month_lock(name):
    with _month_locks_lock:
        return _month_locks.setdefault(name, threading.Lock())


def fetch_month(station_id: str, first: date, interval: str) -> list[list[Any]] | None:
    """Fetch one calendar month of predictions, cached per station and month.

    NOAA serves at most 31 days of 6-minute predictions per request, so a
    calendar month is the largest chunk that always fits. Chunking on the
    calendar rather than on the caller's window means every window in the
    same month reads the same file: a day's view, the live view's two
    weeks, and the expansion when the user scrolls all share it, and the
    file stays valid from one day to the next.

    Two threads asking for the same month at once (a subordinate
    station's curve and its extremes both come from the hi/lo month)
    take turns: the second waits on the month's lock and then reads the
    file the first wrote, instead of making the same request itself.
    """
    kind = "hilo" if interval == "hilo" else "pred"
    cache_file = cache_dir() / f"{kind}_{station_id}_{first:%Y%m}.json"
    last = month_after(first) - timedelta(days=1)
    url = _prediction_url(station_id, first.strftime("%Y%m%d"),
                          last.strftime("%Y%m%d"), interval)
    builder = _build_hilo_row if kind == "hilo" else _build_tide_row
    with _month_lock(cache_file.name):
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


_stations_memo = None


def fetch_all_stations_noaa() -> list[dict[str, Any]]:
    """Fetch the full NOAA tide-prediction station list (cached 30 days).

    Parsing the 1.5 MB list costs about 10 ms and one run consults it
    several times (picking the station, naming a --station ID, the
    subordinate check before each fetch), so the parsed list is kept for
    the life of the process.
    """
    global _stations_memo
    if _stations_memo is not None:
        return _stations_memo
    url = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
    stations = fetch_json_cached(
        cache_dir() / "all_stations.json", 30 * 86400, url,
        timeout=10, fallback=[], provider="tides/noaa", transform=_station_list)
    # A file from before the list was parsed on the way in can hold
    # mdapi's own answer, left where parsing it failed.
    if not isinstance(stations, list):
        stations = []
    if stations:
        _stations_memo = stations
    return stations


def _station_list(data):
    """The stations in mdapi's answer. An answer with none in it is not
    the list: raising keeps it out of the cache, where it would say "no
    station anywhere" for a month."""
    stations = data.get("stations") or []
    if not stations:
        raise ValueError("no stations in the answer")
    return stations


def synthesize_tides_from_hilo(hilo_points: list[tuple[datetime, float, str]],
                               step_minutes: int = 6) -> list[tuple[datetime, float]]:
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


def fetch_tides_range(station_id: str, start_date: date, end_date: date,
                      station_tz: tzinfo | None) -> list[tuple[datetime, float]]:
    """6-minute predictions across a date range as sorted [(datetime, height_ft)]."""
    points = []
    for time_str, height in _rows_in_range(station_id, start_date, end_date, "6"):
        dt = _row_dt(time_str, station_tz)
        if dt is not None:
            points.append((dt, height))
    points.sort(key=lambda point: point[0])
    return points


def fetch_hilo_range(station_id: str, start_date: date, end_date: date,
                     station_tz: tzinfo | None) -> list[tuple[datetime, float, str]]:
    """High/low extremes across a date range as sorted [(datetime, height_ft, type)]."""
    points = []
    for time_str, height, typ in _rows_in_range(station_id, start_date, end_date, "hilo"):
        dt = _row_dt(time_str, station_tz)
        if dt is not None:
            points.append((dt, height, typ))
    points.sort(key=lambda point: point[0])
    return points


# ---------------------------------------------------------------------------
# What the gauge measured, and where the water floods
# ---------------------------------------------------------------------------
def _observed_url(station_id, product, begin, end):
    return (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?begin_date={begin:%Y%m%d}&end_date={end:%Y%m%d}"
        f"&station={station_id}&product={product}&datum=MLLW"
        f"&units=english&time_zone=lst_ldt&format=json"
    )


def _observed_rows(data):
    """["YYYY-MM-DD HH:MM", height_ft] rows of a water level answer.

    A station without a gauge answers with an error payload, kept as no
    rows so the question is not asked again until the file ages out."""
    rows = []
    for sample in data.get("data") or []:
        time_str, value = sample.get("t", ""), sample.get("v")
        if not value or _row_dt(time_str, None) is None:
            continue
        try:
            rows.append([time_str, float(value)])
        except (TypeError, ValueError):
            continue
    return rows


def fetch_observed_extremes(station_id: str, year: int,
                            today: date) -> dict[date, tuple[float, float]]:
    """{day: (lowest, highest)} of the water the gauge measured in *year*
    before *today*, in feet above MLLW; empty for a station without one.

    NOAA's verified highs and lows come a year to a request, and reach
    to about a month ago. The weeks after that come from the preliminary
    six-minute series, 31 days to a request: two or three requests in
    all, and the past years' are kept for a month.
    """
    first = date(year, 1, 1)
    last = min(date(year, 12, 31), today - timedelta(days=1))
    if last < first:
        return {}
    days = {}

    def take(rows):
        for time_str, value in rows or []:
            day = date.fromisoformat(time_str[:10])
            lo, hi = days.get(day, (value, value))
            days[day] = (min(lo, value), max(hi, value))

    past = year < today.year
    # A past year's files are good for a month, but only the copies made
    # since the year ended: one made while it ran stops where it stood.
    ended = datetime(year + 1, 1, 2, tzinfo=timezone.utc).timestamp()

    def keep(cache_file, running):
        try:
            made_after = cache_file.stat().st_mtime >= ended
        except OSError:
            made_after = True   # no copy: the age decides nothing
        return 30 * 86400 if past and made_after else running

    hl_file = cache_dir() / f"obs_hl_{station_id}_{year}.json"
    take(fetch_json_cached(
        hl_file, keep(hl_file, 86400),
        _observed_url(station_id, "high_low", first, last), timeout=15,
        fallback=None, provider="tides/noaa", transform=_observed_rows))
    # Without verified days the gauge may be new or absent: look only at
    # the last few weeks, not the whole year a month at a time.
    start = max(days) + timedelta(days=1) if days else max(first, last - timedelta(days=45))
    while start <= last:
        end = min(start + timedelta(days=30), last)
        wl_file = cache_dir() / f"obs_wl_{station_id}_{start:%Y%m%d}.json"
        take(fetch_json_cached(
            wl_file, keep(wl_file, 3 * 3600),
            _observed_url(station_id, "water_level", start, end), timeout=15,
            fallback=None, provider="tides/noaa", transform=_observed_rows))
        start = end + timedelta(days=1)
    return days


def fetch_flood_stage(station_id: str) -> float | None:
    """The station's minor flood level in feet above MLLW, or None:
    the National Weather Service's where it has set one, else NOS's.

    NOAA gives flood levels over the station's own datum, so MLLW's
    height on that datum comes off: Portland, Maine floods at 20.55 ft
    over its datum, which is 12.0 over MLLW.
    """
    base = f"https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{station_id}"
    levels = fetch_json_cached(cache_dir() / f"flood_{station_id}.json", 30 * 86400,
                               f"{base}/floodlevels.json", timeout=10, fallback=None,
                               provider="tides/noaa")
    datums = fetch_json_cached(cache_dir() / f"datums_{station_id}.json", 30 * 86400,
                               f"{base}/datums.json?units=english", timeout=10,
                               fallback=None, provider="tides/noaa")
    if not isinstance(levels, dict) or not isinstance(datums, dict):
        return None
    minor = levels.get("nws_minor") or levels.get("nos_minor")
    mllw = next((d.get("value") for d in datums.get("datums") or []
                 if d.get("name") == "MLLW"), None)
    try:
        return float(minor) - float(mllw)
    except (TypeError, ValueError):
        return None


def is_subordinate_station(station_id: str) -> bool:
    """True when the station list marks this station type "S".

    Subordinate stations only publish high/low predictions — asking for the
    6-minute series is a guaranteed error, so callers skip straight to
    synthesis. Unknown stations read as reference (try the real series).
    """
    for s in (fetch_all_stations_noaa() or []):
        if str(s.get("id", "")) == str(station_id):
            return s.get("type") == "S"
    return False


def fetch_tides_range_with_fallback(
    station_id: str, start_date: date, end_date: date, station_tz: tzinfo | None,
) -> list[tuple[datetime, float]]:
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


def fetch_y_range(station_id: str, center_date: date) -> tuple[float, float] | None:
    """Compute the y-axis range from hilo data around the date. Cached 7 days.

    The window and cache key are month-anchored (see y_range_window) so
    consecutive days share one request and one file.
    """
    start, end, key = y_range_window(center_date)

    def heights():
        url = _prediction_url(station_id, start.strftime("%Y%m%d"),
                              end.strftime("%Y%m%d"), "hilo")
        try:
            data = fetch_json(url, timeout=15)
        except Exception as exc:
            log_failure("tides/noaa", "y-range fetch", exc, url=url,
                        fallback="auto-scaled axis")
            return None
        found = []
        rows = (data.get("predictions") or []) if data else []
        bad = None
        for prediction in rows:
            try:
                found.append(float(prediction["v"]))
            except (KeyError, ValueError) as exc:
                bad = exc
        log_skipped("tides/noaa", "y-range heights", len(rows) - len(found), len(rows), bad)
        return found

    return cached_y_range(cache_dir() / f"yrange_{station_id}_{key}.json", heights)
