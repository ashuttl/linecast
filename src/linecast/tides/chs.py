"""CHS (Canadian Hydrographic Service) tide data source.

Uses the IWLS API at api-iwls.dfo-mpo.gc.ca for Canadian tidal stations.
All CHS data is in UTC and metres; this module converts to local time and
feet for compatibility with the NOAA-based rendering pipeline.
"""

from datetime import date, datetime, timezone, timedelta, tzinfo
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._log import log_failure, log_skipped
from linecast.tides.common import (
    M_TO_FT, cache_dir, cached_y_range, dedup_sorted, iana_to_abbr,
    label_hilo, local_day_bounds, nearest_station, parse_cached_dt,
    parse_utc_iso, station_coords, tz_offset_hours, y_range_window,
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
