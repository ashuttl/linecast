"""TideCheck global tide data source (optional).

Provides station discovery and tide prediction fetchers for TideCheck's
global API (6,470+ stations, 176 countries).  Activated only when the user
gives a key, in the LINECAST_TIDECHECK_KEY environment variable or under
`tidecheck_key` in config.json.  Without the key this module is
completely inert — no network calls, no errors, no noise.

The API publishes the high and low waters and the height every fifteen
minutes (heights in meters, times in UTC alongside a localTime with
offset), both in the one response.  The curve is the fifteen-minute
series; a response without one has its curve synthesized from the highs
and lows, with the cosine model subordinate NOAA stations use.  Discovery
endpoints (/stations/nearest, /stations/search) return bare JSON arrays
sorted by relevance/distance.

API docs: https://tidecheck.com/developers
Auth:     X-API-Key header
Free tier: 50 requests/day (no credit card required).  linecast counts
          what it sends and stops at the cap, serving cached copies
          until the day turns, unless LINECAST_TIDECHECK_PAID says a
          paid plan is in force.
"""

import os
import re
from datetime import date, datetime, timezone, tzinfo
from typing import Any

from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._config import saved_tidecheck_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._log import log_failure, log_skipped
from linecast.tides.common import (
    M_TO_FT, NEAREST_STATION_CACHE_MAX_AGE, cache_dir, cached_y_range,
    iana_to_abbr, parse_cached_dt, parse_utc_iso, tz_offset_hours,
    y_range_window,
)

TIDECHECK_BASE = "https://tidecheck.com/api"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------
def _api_key():
    """Return the TideCheck API key, or None: LINECAST_TIDECHECK_KEY,
    then the key saved in config.json."""
    return (os.environ.get("LINECAST_TIDECHECK_KEY", "").strip()
            or saved_tidecheck_key())


def is_available() -> bool:
    """Return True when the user has configured a TideCheck API key."""
    return _api_key() is not None


def _headers():
    """The API-key header; the User-Agent is attached by _http."""
    key = _api_key()
    if not key:
        return {}
    return {"X-API-Key": key}


# ---------------------------------------------------------------------------
# Request budget
# ---------------------------------------------------------------------------
FREE_TIER_LIMIT = 50


class BudgetExhausted(Exception):
    """Raised in place of a request the free tier has no room for.

    Every caller already absorbs a failed fetch, so this needs no
    handling of its own: the cached copy stands in where there is one,
    and the station falls to the next provider where there is not.
    """


def _tally_file(day: date | None = None) -> Any:
    day = day or datetime.now(timezone.utc).date()
    return cache_dir() / f"tc_requests_{day.isoformat()}.json"


def requests_today() -> int:
    """How many requests linecast has sent TideCheck today (UTC), from
    this machine.  The API does not say how many are left, so this is
    the honest lower bound: another machine on the same key adds to
    the real total."""
    data = read_stale(_tally_file())
    try:
        return int(data.get("count", 0)) if data else 0
    except (TypeError, ValueError, AttributeError):
        return 0


def _count_request() -> None:
    path = _tally_file()
    write_cache(path, {"count": requests_today() + 1})


def paid_tier() -> bool:
    """LINECAST_TIDECHECK_PAID=1 says the 50-a-day cap does not apply."""
    return os.environ.get("LINECAST_TIDECHECK_PAID", "").strip().lower() in (
        "1", "true", "yes")


def _fetch(url, timeout=10):
    """fetch_json with the API key, counted against today's budget.

    The request the tally says would be the 51st of the day is not sent:
    the server would refuse it, and a cached copy is a better answer
    than a wasted round trip.  The 50th is sent, and counted.  A cache
    hit never reaches here, so it never counts.
    """
    if not paid_tier() and requests_today() >= FREE_TIER_LIMIT:
        raise BudgetExhausted(
            f"all {FREE_TIER_LIMIT} free-tier requests used today (UTC)")
    _count_request()
    return fetch_json(url, headers=_headers(), timeout=timeout)


def budget_line() -> str | None:
    """One line on where today's requests stand, or None without a key:

        TideCheck: 12 of 50 free-tier requests used today (UTC)
    """
    if not is_available():
        return None
    used = requests_today()
    if paid_tier():
        return f"TideCheck: {used} requests sent today (UTC)"
    if used >= FREE_TIER_LIMIT:
        return (f"TideCheck: all {FREE_TIER_LIMIT} free-tier requests used today"
                " (UTC); cached results only until it resets")
    return f"TideCheck: {used} of {FREE_TIER_LIMIT} free-tier requests used today (UTC)"


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def find_nearest_station_tidecheck(lat: float, lng: float
                                   ) -> tuple[str | None, str | None]:
    """Find closest TideCheck tide station by lat/lng.

    Returns (station_id, station_name) or (None, None).  Cached for 1 hour.
    The API does the distance search server-side, so this does not share
    the station-list picker the other providers use.
    """
    if not is_available():
        return None, None

    pick = fetch_json_cached(
        cache_dir() / f"tc_station_{location_cache_key(lat, lng)}.json",
        NEAREST_STATION_CACHE_MAX_AGE, f"{TIDECHECK_BASE}/stations/nearest?lat={lat}&lng={lng}",
        fetch=_fetch, fallback=None, provider="tides/tidecheck",
        transform=lambda data: _nearest_pick(data, lat, lng))
    if not pick:
        return None, None
    return pick["id"], pick["name"]


def _nearest_pick(data, lat, lng):
    """The station /stations/nearest puts first, as the pick cached for
    the place. One too far, or none, raises: an answer without a pick is
    not kept, and the last pick for the place stands in if there is one."""
    # /stations/nearest returns a JSON array sorted by distance; keep the
    # dict shapes as fallbacks in case the API grows a wrapper.
    if isinstance(data, list):
        station = data[0] if data else None
    elif isinstance(data, dict):
        station = data.get("station", data)
    else:
        station = None
    if not station:
        raise LookupError("no station in the answer")

    # Parity with the NOAA picker's 100 nm cutoff, using the distanceKm
    # the endpoint reports — an inland user shouldn't get a random coast.
    try:
        distance = float(station.get("distanceKm", 0))
    except (TypeError, ValueError) as exc:
        distance = 0
        log_failure("tides/tidecheck", "distance check", exc,
                    fallback="station accepted unchecked")
    if distance > 185:
        raise LookupError(f"the nearest station is {distance:.0f} km away")

    station_id = str(station.get("id", ""))
    if not station_id:
        raise LookupError("the nearest station has no id")
    return {"id": station_id, "name": station.get("label") or station.get("name", ""),
            "lat": lat, "lng": lng}


def search_stations_tidecheck(query: str) -> list[dict[str, Any]]:
    """Search TideCheck stations by name substring.

    Returns a list of dicts with 'id', 'name', 'lat', and 'lng' keys, or [].
    The name is the API's label ("Cascais, Lisbon, Portugal") when present,
    and the coordinates let the caller sort by distance like any other
    provider's stations.
    """
    if not is_available():
        return []

    import urllib.parse
    encoded = urllib.parse.quote(query)
    cache_file = cache_dir() / f"tc_search_{encoded[:40]}.json"
    url = f"{TIDECHECK_BASE}/stations/search?q={encoded}"

    data = fetch_json_cached(cache_file, 86400, url, fetch=_fetch, fallback=None,
                             provider="tides/tidecheck")
    if not data:
        return []

    # The API returns a bare list; keep the wrapped shape as a fallback
    stations = data if isinstance(data, list) else (data.get("stations") or [])
    results = []
    for s in stations:
        sid = str(s.get("id", ""))
        if sid:
            results.append({
                "id": sid,
                "name": s.get("label") or s.get("name", ""),
                "lat": s.get("lat"), "lng": s.get("lng"),
            })
    return results


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_tidecheck(station_id: str) -> dict[str, Any] | None:
    """Fetch TideCheck station metadata, normalized to match NOAA shape.

    Returns dict with: id, name, lat, lng, timezone_abbr, timezonecorr,
    timeZoneCode, observedst, source.
    """
    if not is_available():
        return None

    cache_file = cache_dir() / f"tc_meta_{station_id}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "tidecheck":
        return cached

    # TideCheck embeds station info (lat/lng/timezone/country) in the tides
    # response; reuse the 30-day fetch the y-range needs so metadata never
    # costs a request of its own (the free tier allows 50/day).
    data = _fetch_tides_raw(station_id, days=30)
    if not data:
        return None

    station = data.get("station") or {}
    tz_code = station.get("timezone", "")

    meta = {
        "id": str(station.get("id", station_id)),
        "name": station.get("name", ""),
        # The header pill renders "name, state" — the country reads best
        "state": station.get("country", ""),
        "lat": station.get("lat") or station.get("latitude"),
        "lng": station.get("lng") or station.get("longitude"),
        "timezone_abbr": iana_to_abbr(tz_code),
        "timezonecorr": tz_offset_hours(tz_code),
        "timeZoneCode": tz_code,
        "observedst": tz_code not in ("UTC", "GMT", ""),
        "source": "tidecheck",
    }
    write_cache(cache_file, meta)
    return meta


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def is_tidecheck_station_id(text: str) -> bool:
    """True for a TideCheck station slug: a model prefix and a place name
    joined by hyphens, all lowercase ("fes2022-lisbon").

    A plain word or a place with spaces is a search, not an ID.
    """
    return re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", text) is not None


def _fetch_tides_raw(station_id, days=7):
    """Fetch raw TideCheck tides response (cached 24 hours).

    Returns the full JSON dict or None.  Aggressively cached because the
    free tier allows only 50 requests/day.
    """
    if not is_available():
        return None

    cache_file = cache_dir() / f"tc_raw_{station_id}_{days}d.json"
    url = f"{TIDECHECK_BASE}/station/{station_id}/tides?days={days}&datum=MLLW"
    return fetch_json_cached(cache_file, 86400, url, fetch=_fetch, timeout=15,
                             fallback=None, provider="tides/tidecheck")


def fetch_tides_range_tidecheck(
    station_id: str, start_date: date, end_date: date, station_tz: tzinfo | None,
) -> list[tuple[datetime, float]]:
    """Fetch TideCheck predictions across a date range as a curve.

    The curve is the API's fifteen-minute series, which comes in the
    response the highs and lows are read from, so it costs no request
    of its own.  The series is whole where the list of highs and lows
    is not: on a sea with hardly a tide the API names few of either,
    days apart, and a curve drawn between them has holes.  A response
    with no series falls back to that curve, synthesized with the
    cosine half-cycle model subordinate NOAA stations use.  Returns
    sorted (datetime, height_ft) tuples.
    """
    if not is_available():
        return []
    data = _fetch_tides_raw(station_id, days=_fetch_days(start_date, end_date))
    series = _series_points(data, station_tz)
    if series:
        return series
    from linecast.tides.noaa import synthesize_tides_from_hilo
    labeled = fetch_hilo_range_tidecheck(station_id, start_date, end_date,
                                         station_tz)
    return synthesize_tides_from_hilo(labeled)


def _fetch_days(start_date, end_date):
    """The days to ask for to cover the range: two to spare, and no more
    than the 30 the API serves."""
    return min(30, max(1, (end_date - start_date).days + 1) + 2)


def _series_points(data, station_tz):
    """The response's fifteen-minute heights as sorted (datetime,
    height_ft), aware in a fixed offset as the cached highs and lows
    are; [] when the response has no series."""
    rows = data.get("timeSeries") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return []
    points = []
    bad = None
    for row in rows:
        try:
            dt_local = parse_utc_iso(row["time"], station_tz)
            height_ft = _maybe_convert_height(float(row["height"]), data)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            # AttributeError: a time that is null or not a string
            bad = exc
            continue
        points.append((parse_cached_dt(dt_local.isoformat(), station_tz), height_ft))
    log_skipped("tides/tidecheck", "series", len(rows) - len(points), len(rows), bad)
    points.sort(key=lambda p: p[0])
    return points


def _maybe_convert_height(height, api_response):
    """Convert a TideCheck height to feet (the pipeline's working unit).

    The API reports heights in meters for every station (confirmed live
    and in the docs); an explicit unit field wins if one ever appears.
    """
    unit = ""
    if isinstance(api_response, dict):
        unit = str(api_response.get("unit", api_response.get("units", ""))).lower()
    if "feet" in unit or unit in ("ft", "imperial"):
        return height
    return height * M_TO_FT


def fetch_hilo_range_tidecheck(
    station_id: str, start_date: date, end_date: date, station_tz: tzinfo | None,
) -> list[tuple[datetime, float, str]]:
    """Fetch TideCheck high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    """
    if not is_available():
        return []

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = cache_dir() / f"tc_hilo_{station_id}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in cached]

    data = _fetch_tides_raw(station_id, days=_fetch_days(start_date, end_date))
    if not data or not isinstance(data, dict):
        return []

    extremes = data.get("extremes") or []
    if not extremes:
        return []

    labeled = []
    bad = None
    for ex in extremes:
        try:
            dt_local = parse_utc_iso(ex.get("time", ""), station_tz)
            height = float(ex.get("height", 0))
            height_ft = _maybe_convert_height(height, data)
            # TideCheck labels extremes as "high"/"low" (or "H"/"L")
            raw_type = str(ex.get("type", "")).upper()
            if raw_type.startswith("H"):
                typ = "H"
            elif raw_type.startswith("L"):
                typ = "L"
            else:
                typ = "H"  # default; will be corrected below
            labeled.append((dt_local, height_ft, typ))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            bad = exc
            continue
    log_skipped("tides/tidecheck", "extremes",
                len(extremes) - len(labeled), len(extremes), bad)

    labeled.sort(key=lambda p: p[0])

    cache_rows = [{"dt": dt.isoformat(), "v": v, "t": t} for dt, v, t in labeled]
    write_cache(cache_file, cache_rows)
    # Read back from the rows, as the next run will read them: aware in
    # a fixed offset, so a time past a change of clock is placed by the
    # hours that have passed, not by the wall clock.
    return [(parse_cached_dt(r["dt"], station_tz), r["v"], r["t"]) for r in cache_rows]


def fetch_y_range_tidecheck(station_id: str, center_date: date,
                            station_tz: tzinfo | None) -> tuple[float, float] | None:
    """Compute y-axis range from TideCheck hilo data.  Cached 7 days.

    TideCheck only serves the next 30 days from now, so the window is not
    ours to choose; the cache key is month-anchored (see y_range_window)
    so consecutive days share one request and one file.
    """
    _, _, key = y_range_window(center_date)

    def heights():
        # Fetch a 30-day window (the maximum TideCheck supports)
        data = _fetch_tides_raw(station_id, days=30)
        if not data:
            return None
        found = []
        extremes = data.get("extremes") or []
        bad = None
        for ex in extremes:
            try:
                height = float(ex.get("height", 0))
                found.append(_maybe_convert_height(height, data))
            except (KeyError, ValueError, TypeError) as exc:
                bad = exc
        log_skipped("tides/tidecheck", "y-range heights",
                    len(extremes) - len(found), len(extremes), bad)
        return found

    return cached_y_range(cache_dir() / f"tc_yrange_{station_id}_{key}.json", heights)
