"""CHS (Canadian Hydrographic Service) tide data source.

Uses the IWLS API at api-iwls.dfo-mpo.gc.ca for Canadian tidal stations.
All CHS data is in UTC and metres; this module converts to local time and
feet for compatibility with the NOAA-based rendering pipeline.
"""

import math
import threading
import time
from collections import deque
from datetime import date, datetime, timezone, timedelta, tzinfo
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._log import debug_log, log_failure, log_skipped
from linecast.tides.common import (
    M_TO_FT, cache_dir, cached_y_range, dedup_sorted, iana_to_abbr,
    label_hilo, local_day_bounds, month_after, nearest_station,
    parse_cached_dt, parse_utc_iso, station_coords, tz_offset_hours,
    y_range_window,
)

CHS_BASE = "https://api-iwls.dfo-mpo.gc.ca/api/v1"


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def is_chs_station_id(station_id: str) -> bool:
    """True when a station ID is a CHS MongoDB ObjectId (24-char hex)."""
    return (len(station_id) == 24 and
            all(c in '0123456789abcdef' for c in station_id.lower()))


def fetch_all_stations_chs() -> list[dict[str, Any]]:
    """Fetch the full CHS tidal station list (cached 30 days)."""
    stations = fetch_json_cached(
        cache_dir() / "chs_all_stations.json", 30 * 86400,
        f"{CHS_BASE}/stations?time-series-code=wlp-hilo",
        timeout=15, fallback=[], provider="tides/chs", transform=_station_list,
    )
    # A file from before the list was checked on the way in can hold
    # some other answer CHS gave.
    return stations if isinstance(stations, list) else []


def _station_list(data):
    """The station list, which CHS sends as a bare list. Anything else,
    or an empty one, is not the list, and raising keeps it out of the
    cache, where it would say "no station anywhere" for a month."""
    if not data or not isinstance(data, list):
        raise ValueError("no stations in the answer")
    return data


def _operating_station_coords(station):
    """Coordinates of an operating station with a tide curve; None for a
    closed one, or one that predicts only the current: the list asked
    for tide stations brings Second Narrows, in Vancouver's harbour,
    which has no water levels to draw."""
    if not station.get("operating", True):
        return None
    series = station.get("timeSeries")
    if series is not None and not any(s.get("code") == "wlp" for s in series):
        return None
    return station_coords(station, "latitude", "longitude")


def find_nearest_station_chs(lat: float, lng: float) -> tuple[str | None, str | None]:
    """Find closest CHS tide station by haversine distance.

    Returns (station_id, station_name) or (None, None). Cached 1 hour.
    """
    return nearest_station(
        cache_dir() / f"chs_station_{location_cache_key(lat, lng)}.json", lat, lng,
        fetch_all_stations_chs, _operating_station_coords,
        lambda s: (str(s.get("id", "")), s.get("officialName", "")),
        tag="tides/chs",
    )


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_chs(station_id: str) -> dict[str, Any] | None:
    """Fetch CHS station metadata, normalized to match NOAA shape.

    Returns dict with: id, name, state, lat, lng, timezone_abbr,
    timezonecorr, timeZoneCode, observedst, source.
    """
    meta = fetch_json_cached(
        cache_dir() / f"chs_meta_{station_id}.json", 30 * 86400,
        f"{CHS_BASE}/stations/{station_id}/metadata",
        timeout=10, fallback=None, provider="tides/chs",
        transform=lambda data: _station_meta(data, station_id),
    )
    # A file from before the metadata was parsed on the way in can hold
    # CHS's own answer.
    if not meta or "timezone_abbr" not in meta:
        return None
    return meta


def _station_meta(data, station_id):
    """CHS's metadata for a station, in the shape NOAA's has."""
    if not data:
        raise ValueError(f"no metadata for station {station_id}")
    tz_code = data.get("timeZoneCode", "")
    return {
        "id": str(data.get("id", station_id)),
        "name": data.get("officialName", ""),
        "state": data.get("provinceCode", ""),
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        "timezone_abbr": iana_to_abbr(tz_code),
        "timezonecorr": tz_offset_hours(tz_code),
        "timeZoneCode": tz_code,
        "observedst": tz_code not in ("UTC", "GMT", ""),
        "source": "chs",
    }


# ---------------------------------------------------------------------------
# UTC <-> local helpers
# ---------------------------------------------------------------------------
def _utc_range_for_dates(start_date, end_date, station_tz):
    """Convert local date range to UTC ISO strings for the CHS API."""
    lo, hi = local_day_bounds(start_date, end_date, station_tz or timezone.utc)
    return (lo.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            hi.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def _levels(data, station_tz, what):
    """CHS's (eventDate, value) rows as (local datetime, feet).

    CHS answers with a bare list; an empty one, or anything else, is no
    answer, and raising keeps it out of the cache.
    """
    if not data or not isinstance(data, list):
        raise ValueError(f"no {what} in the answer")
    levels = []
    bad = None
    for entry in data:
        try:
            levels.append((parse_utc_iso(entry["eventDate"], station_tz),
                           float(entry["value"]) * M_TO_FT))
        except (KeyError, ValueError, TypeError) as exc:
            bad = exc
    log_skipped("tides/chs", what, len(data) - len(levels), len(data), bad)
    return levels


def _level_rows(data, station_tz):
    """The water levels as cache rows: {"dt": local ISO time, "v": feet}."""
    return [{"dt": dt.isoformat(), "v": v}
            for dt, v in _levels(data, station_tz, "water-level rows")]


def _extreme_rows(data, station_tz):
    """The extremes as cache rows, with "t" saying high or low, which
    CHS's wlp-hilo series does not."""
    return [{"dt": dt.isoformat(), "v": v, "t": t}
            for dt, v, t in label_hilo(_levels(data, station_tz, "hilo rows"))]


def fetch_tides_range_chs(station_id: str, start_date: date, end_date: date,
                          station_tz: tzinfo | None) -> list[tuple[datetime, float]]:
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
    return dedup_sorted(points)


def _fetch_pred_chunk(station_id, start_date, end_date, station_tz):
    """Fetch a single chunk of CHS predictions (max 30 days)."""
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = cache_dir() / f"chs_pred_{station_id}_{start_str}_{end_str}.json"

    utc_from, utc_to = _utc_range_for_dates(start_date, end_date, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlp&from={utc_from}&to={utc_to}"
        f"&resolution=FIVE_MINUTES"
    )
    rows = fetch_json_cached(cache_file, 86400, url, timeout=20, fallback=[],
                             provider="tides/chs",
                             transform=lambda data: _level_rows(data, station_tz))
    return [(parse_cached_dt(r["dt"], station_tz), r["v"]) for r in rows]


def fetch_hilo_range_chs(station_id: str, start_date: date, end_date: date,
                         station_tz: tzinfo | None) -> list[tuple[datetime, float, str]]:
    """Fetch CHS high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    CHS supports up to 366 days of hilo data per request.
    """
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = cache_dir() / f"chs_hilo_{station_id}_{start_str}_{end_str}.json"

    utc_from, utc_to = _utc_range_for_dates(start_date, end_date, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlp-hilo&from={utc_from}&to={utc_to}"
    )
    rows = fetch_json_cached(cache_file, 86400, url, timeout=15, fallback=[],
                             provider="tides/chs",
                             transform=lambda data: _extreme_rows(data, station_tz))
    return [(parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in rows]


def fetch_y_range_chs(station_id: str, center_date: date,
                      station_tz: tzinfo | None) -> tuple[float, float] | None:
    """Compute the y-axis range from CHS hilo data around the date. Cached 7 days.

    The window and cache key are month-anchored (see y_range_window) so
    consecutive days share one request and one file.
    """
    start, end, key = y_range_window(center_date)

    def heights():
        utc_from, utc_to = _utc_range_for_dates(start, end, station_tz)
        url = (
            f"{CHS_BASE}/stations/{station_id}/data"
            f"?time-series-code=wlp-hilo&from={utc_from}&to={utc_to}"
        )
        try:
            data = fetch_json(url, timeout=15)
        except Exception as exc:
            log_failure("tides/chs", "y-range fetch", exc, url=url,
                        fallback="auto-scaled axis")
            return None
        if not data or not isinstance(data, list):
            return None
        found = []
        bad = None
        for entry in data:
            try:
                found.append(float(entry["value"]) * M_TO_FT)
            except (KeyError, ValueError, TypeError) as exc:
                bad = exc
        log_skipped("tides/chs", "y-range heights", len(data) - len(found), len(data), bad)
        return found

    return cached_y_range(cache_dir() / f"chs_yrange_{station_id}_{key}.json", heights)


# ---------------------------------------------------------------------------
# What the gauge measured
# ---------------------------------------------------------------------------
# IWLS lets an address make three requests a second and thirty a minute.
# A year of what a gauge measured is a dozen of them, and stepping back
# to the year before is a dozen more, so these keep to two a second and
# twenty-four a minute, which leaves room for the view's other requests.
# The worker waits its turn rather than draw a year with holes where the
# server said no.
_OBS_SPACING = 0.5
_OBS_PER_MINUTE = 24
_obs_sent: deque[float] = deque()
_obs_lock = threading.Lock()
# The gauge's samples are asked for fifteen minutes apart
_STEP = 15 * 60


def _obs_turn():
    """Wait until one more observation request keeps within the limits."""
    with _obs_lock:
        while True:
            now = time.monotonic()
            while _obs_sent and now - _obs_sent[0] >= 60:
                _obs_sent.popleft()
            wait = _OBS_SPACING - (now - _obs_sent[-1]) if _obs_sent else 0
            if len(_obs_sent) >= _OBS_PER_MINUTE:
                wait = max(wait, 60 - (now - _obs_sent[0]))
            if wait <= 0:
                break
            debug_log(f"tides/chs: waiting {wait:.1f}s for the IWLS rate limit")
            time.sleep(wait)
        _obs_sent.append(now)


def _series_id(station_id, code):
    """The id of the station's *code* time series, from the station list;
    None when the station keeps no such series or is not listed."""
    for station in fetch_all_stations_chs():
        if str(station.get("id", "")) == station_id:
            for series in station.get("timeSeries") or []:
                if series.get("code") == code:
                    return str(series.get("id") or "") or None
            return None
    return None


def _station_zone(station_id):
    """The station's zone, from its metadata; UTC when it names none."""
    from zoneinfo import ZoneInfo
    tz_code = (fetch_station_metadata_chs(station_id) or {}).get("timeZoneCode")
    try:
        return ZoneInfo(tz_code) if tz_code else timezone.utc
    except (KeyError, ValueError) as exc:
        log_failure("tides/chs", f"lookup of {tz_code}", exc, fallback="UTC days")
        return timezone.utc


def _holdings(data):
    """{series id: [[first day, last day], ...]}: the UTC days each of the
    station's series holds data for, a span to each run without a gap."""
    if not isinstance(data, list):
        raise ValueError("no holdings in the answer")
    return {str(held["timeSeriesId"]): [[span["dateStart"][:10], span["dateEnd"][:10]]
                                        for span in held.get("dataHoldings") or []]
            for held in data}


def _samples(data, start, slots):
    """The water levels as metres on the fifteen-minute grid from *start*,
    None where the gauge sent nothing.  An empty list is an answer, a
    gauge silent all month, and is kept as a month of None."""
    if not isinstance(data, list):
        raise ValueError("no water levels in the answer")
    grid = [None] * slots
    kept, bad = 0, None
    for entry in data:
        try:
            at = parse_utc_iso(entry["eventDate"])
            value = float(entry["value"])
        except (KeyError, ValueError, TypeError) as exc:
            bad = exc
            continue
        kept += 1
        slot = round((at - start).total_seconds() / _STEP)
        if 0 <= slot < slots:
            grid[slot] = value
    log_skipped("tides/chs", "water levels", len(data) - kept, len(data), bad)
    return grid


def _observed_month(station_id, first, last, station_tz, settled, fetch):
    """{"to": last, "from": UTC start, "m": [metres or None, ...]}: the
    gauge's samples from the midnight opening *first* to the one closing
    *last*, both included.  A settled month is kept for 30 days; the
    month still under way for three hours, and asked again as soon as a
    day has been added to it, however young the file.

    The samples are kept rather than each day's extremes so that the
    turns of the tide either side of a month's end can be read across it.
    """
    utc_from, utc_to = _utc_range_for_dates(first, last, station_tz)
    url = (
        f"{CHS_BASE}/stations/{station_id}/data"
        f"?time-series-code=wlo&from={utc_from}&to={utc_to}"
        f"&resolution=FIFTEEN_MINUTES"
    )
    start, end = parse_utc_iso(utc_from), parse_utc_iso(utc_to)
    slots = int((end - start).total_seconds()) // _STEP + 1
    through = last.isoformat()
    return fetch_json_cached(
        cache_dir() / f"chs_obs_{station_id}_{first:%Y%m}.json",
        30 * 86400 if settled else 3 * 3600, url, timeout=15, fallback=None,
        provider="tides/chs", fetch=fetch,
        fresh=lambda cached: isinstance(cached, dict) and cached.get("to") == through,
        transform=lambda data: {"to": through, "from": utc_from,
                                "m": _samples(data, start, slots)})


def _measured_turns(turns, level, start, last):
    """{day: (lowest, highest)} in feet of the water the gauge measured at
    each day's predicted turns of the tide, through *last*.

    Each turn takes the samples nearer to it than to the turns either
    side, and reads their highest for a high water and their lowest for
    a low; a day's range is then taken from its turns as the predicted
    one is.  A day's plain highest sample will not do: where the higher
    high water falls near midnight, as it does in Vancouver in summer,
    the water at midnight is the evening's high still ebbing, and the
    day after would read five feet over a prediction it matched.
    A sample or two gone missing costs a few inches at most, even at
    Fundy's range, but three or more running are a gap the turn itself
    may be in, and the day is left out.
    """
    at = [(moment - start).total_seconds() / _STEP for moment, _h, _k in turns]
    found, missed = {}, set()
    for i, (moment, _height, kind) in enumerate(turns):
        day = moment.date()
        if day > last:
            break
        lo = (at[i - 1] + at[i]) / 2 if i else at[i] - 12
        hi = (at[i] + at[i + 1]) / 2 if i + 1 < len(turns) else at[i] + 12
        window = level[max(0, math.ceil(lo)):max(0, math.ceil(hi))]
        seen = [v for v in window if v is not None]
        gap = run = 0
        for v in window:
            run = run + 1 if v is None else 0
            gap = max(gap, run)
        if not seen or gap > 2:
            missed.add(day)
            continue
        found.setdefault(day, []).append((max(seen) if kind == "H" else min(seen)) * M_TO_FT)
    return {day: (min(v), max(v)) for day, v in found.items() if day not in missed}


def fetch_observed_extremes_chs(station_id: str, year: int,
                                today: date) -> dict[date, tuple[float, float]]:
    """{day: (lowest, highest)} of the water the gauge measured in *year*
    before *today*, in feet above chart datum as the predictions are;
    empty for a station without a gauge.

    The measured water is IWLS's official level, the wlo series, which
    comes at most 31 days to a request.  Hourly samples would come in a
    quarter of the bytes, but an hour's sample can miss the top of a
    Fundy tide by a foot, and the pen would draw that as water falling
    short of the prediction; fifteen minutes misses it by an inch or
    two.  So a year is a request a month, one after another, half a
    second apart for the rate limit.  A gauge can stop without the
    station list saying so (Halifax's stopped in November 2025), so the
    station's holdings are asked for first, and the months they say the
    gauge was silent are not.
    """
    yesterday = today - timedelta(days=1)
    first, last = date(year, 1, 1), min(date(year, 12, 31), yesterday)
    series = _series_id(station_id, "wlo") if first <= last else None
    if series is None:
        return {}
    station_tz = _station_zone(station_id)
    # The year view has just asked for the same year, so this is its cache
    turns = fetch_hilo_range_chs(station_id, first, date(year, 12, 31), station_tz)
    if not turns:
        return {}
    failed = False

    def fetch(url, timeout):
        # Once IWLS has failed to answer, the months after are read from
        # the cache, not waited on one timeout at a time.
        nonlocal failed
        if failed:
            raise ConnectionError("IWLS did not answer an earlier request")
        _obs_turn()
        try:
            return fetch_json(url, timeout=timeout)
        except Exception:
            failed = True
            raise

    holdings = fetch_json_cached(
        cache_dir() / f"chs_holdings_{station_id}.json", 86400,
        f"{CHS_BASE}/stations/{station_id}/holdings", timeout=10, fallback=None,
        provider="tides/chs", fetch=fetch, transform=_holdings)
    # Unknown holdings ask for every month
    held = holdings.get(series, []) if isinstance(holdings, dict) else None
    start, end = (parse_utc_iso(t) for t in _utc_range_for_dates(first, last, station_tz))
    level = [None] * (int((end - start).total_seconds()) // _STEP + 1)
    month = first
    while month <= last:
        month_end = min(month_after(month) - timedelta(days=1), last)
        # The holdings count UTC days; a day either side covers the zone.
        lo = (month - timedelta(days=1)).isoformat()
        hi = (month_end + timedelta(days=1)).isoformat()
        if held is None or any(a <= hi and b >= lo for a, b in held):
            found = _observed_month(station_id, month, month_end, station_tz,
                                    month_end < yesterday, fetch)
            if found:
                offset = round((parse_utc_iso(found["from"]) - start).total_seconds() / _STEP)
                for k, value in enumerate(found["m"]):
                    if value is not None and 0 <= offset + k < len(level):
                        level[offset + k] = value
        month = month_after(month)
    return _measured_turns(turns, level, start, last)
