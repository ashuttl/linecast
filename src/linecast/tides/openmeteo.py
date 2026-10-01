"""Open-Meteo tide model data source (keyless global fallback).

Serves hourly `sea_level_height_msl` from Open-Meteo's marine API — a
model-based tide curve available on nearly any coastline worldwide, with
no API key.  Used when no station provider (NOAA, CHS, QLD, TideCheck)
has a station near the current location.

Unlike the station providers there are no stations here: the "station"
is the user's coordinates, encoded as `om:<lat>,<lng>`.  The marine API
defaults to cell_selection=sea, so slightly-inland coordinates snap to
the nearest wet grid cell automatically; a series of all-null heights
means the model genuinely has no coverage (far inland).

Heights are metres relative to mean sea level; converted to feet for the
rendering pipeline.

The model forecasts about ten days, but it keeps its past hours back to
the start of 2023, and a tide is the same sum of cosines every year. So
one request brings last year's hourly heights, the tide machine
(tides/harmonic.py) fits a tide's constants to them, and the predictions
come from those, for any date, every six minutes: one request a year
for each place, with the constants kept on disk. Extrapolating a year
adds nothing to the model's own error; at Portland, Maine the fit's
2026 is as close to NOAA's tables as the model's own hours are, about
half an hour early and a twentieth short on the range, which is the
model's grid cell sitting out in the bay, not the method.

What the fit leaves out is the weather: surge, wind setup, the seasons'
swell of the sea. The model's own heights, tide and weather together,
are the year view's pen, marked as modeled rather than measured; at
Portland their daily departures from the tide track the gauge's with a
correlation of 0.95, though inside bays they run short of the gauge's
peaks.

Where last year cannot be had, the hourly window is served as it comes,
with the highs and lows found by a parabola through each turn.
"""

import threading
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from linecast._cache import location_cache_key, read_cache, write_cache
from linecast._http import fetch_json_cached
from linecast._log import log_failure, log_skipped
from linecast.tides import harmonic
from linecast.tides.common import (
    M_TO_FT, cache_dir, cached_y_range, computed_hilo, computed_range, computed_y_range,
    local_day_bounds,
)

# One standard fetch window serves every caller (range, hilo, y-range,
# metadata) from a single cached payload.  The marine API caps forecasts
# at 8 days; 31 past days give the y-range a real spring/neap spread.
PAST_DAYS = 31
FORECAST_DAYS = 8
RAW_CACHE_MAX_AGE = 3 * 3600

# The constituents fitted to a year of the model's hours: all that a
# year separates, down to the quarter-diurnal overtides. M8 is left to
# the gauges; the model's grid is too coarse to make one.
FIT_NAMES = (
    "SA", "SSA", "MM", "MSF", "MF",
    "2Q1", "Q1", "RHO1", "O1", "M1", "P1", "K1", "J1", "OO1",
    "2N2", "MU2", "N2", "NU2", "M2", "LAMBDA2", "L2", "S2", "K2", "2SM2",
    "2MK3", "M3", "MK3", "MN4", "M4", "MS4", "S4", "M6", "2MS6",
)
# A fit wants most of the year: 300 days of hours.
FIT_MIN_HOURS = 300 * 24


# ---------------------------------------------------------------------------
# Pseudo-station IDs
# ---------------------------------------------------------------------------
def make_station_id(lat: float, lng: float) -> str:
    """Encode coordinates as an Open-Meteo pseudo-station ID."""
    return f"om:{float(lat):.4f},{float(lng):.4f}"


def is_openmeteo_station_id(station_id: str) -> bool:
    return str(station_id).startswith("om:")


def parse_station_id(station_id: str) -> tuple[float, float] | None:
    """Decode an `om:lat,lng` pseudo-station ID to (lat, lng) or None."""
    try:
        lat_str, lng_str = str(station_id)[3:].split(",")
        return float(lat_str), float(lng_str)
    except (ValueError, IndexError) as exc:
        log_failure("tides/open-meteo", "parse of station id", exc,
                    fallback="no station")
        return None


# ---------------------------------------------------------------------------
# Raw fetch
# ---------------------------------------------------------------------------
def _fetch_raw(lat, lng):
    """Fetch the standard tide-model window for a location.  Cached 3h."""
    cache_file = cache_dir() / f"om_raw_{location_cache_key(lat, lng)}.json"
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=sea_level_height_msl"
        f"&timezone=auto&past_days={PAST_DAYS}&forecast_days={FORECAST_DAYS}"
    )
    return fetch_json_cached(
        cache_file, RAW_CACHE_MAX_AGE, url,
        timeout=15, fallback=None,
    )


def _series(data, station_tz):
    """Parse a raw payload to a sorted [(aware_local_dt, height_ft)] list."""
    if not data or not isinstance(data, dict):
        return []
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    heights = hourly.get("sea_level_height_msl") or []
    # Open-Meteo stamps the whole response in the zone's offset at the
    # moment of the request, so the hours past a clock change carry the
    # wrong one: each is read as the instant it names, then put on the
    # station's clock.
    offset = data.get("utc_offset_seconds")
    stamped = None if offset is None else timezone(timedelta(seconds=int(offset)))
    points = []
    dropped = 0
    bad = None
    for t, h in zip(times, heights):
        if h is None:
            continue  # no model coverage for that hour: routine, not a failure
        try:
            dt = datetime.fromisoformat(t)
        except ValueError as exc:
            dropped += 1
            bad = exc
            continue
        if station_tz is not None:
            dt = (dt.replace(tzinfo=station_tz) if stamped is None
                  else dt.replace(tzinfo=stamped).astimezone(station_tz))
        points.append((dt, float(h) * M_TO_FT))
    log_skipped("tides/open-meteo", "marine hours", dropped, len(times), bad)
    points.sort(key=lambda p: p[0])
    return points


# ---------------------------------------------------------------------------
# A year of the model, and the tide fitted to it
# ---------------------------------------------------------------------------
def _fetch_year(lat, lng, year, today):
    """The model's hourly heights for a calendar year, through yesterday
    when it is this year. A finished year never changes and is kept for
    a year; this year's latest days are revised as the model runs, so
    they are kept for three hours. A copy made while the year was
    running stops short of its end, and is not taken for the finished
    year once the year has turned."""
    last = min(date(year, 12, 31), today - timedelta(days=1))
    if last < date(year, 1, 1):
        return None
    finished = last == date(year, 12, 31)
    cache_file = cache_dir() / f"om_year_{location_cache_key(lat, lng)}_{year}.json"
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=sea_level_height_msl&timezone=auto"
        f"&start_date={year}-01-01&end_date={last.isoformat()}"
    )
    def reaches_the_end(cached):
        hours = (cached.get("hourly") or {}).get("time") if isinstance(cached, dict) else None
        return bool(hours) and str(hours[-1])[:10] >= last.isoformat()

    return fetch_json_cached(cache_file, 366 * 86400 if finished else RAW_CACHE_MAX_AGE,
                             url, timeout=20, fallback=None, provider="tides/open-meteo",
                             fresh=reaches_the_end if finished else None)


def _instants(data):
    """[(UTC datetime, height in metres)] from a payload: each stamp read
    in the one offset Open-Meteo gives the whole response (see _series)."""
    if not data or not isinstance(data, dict):
        return []
    hourly = data.get("hourly") or {}
    offset = timedelta(seconds=int(data.get("utc_offset_seconds") or 0))
    out = []
    for t, h in zip(hourly.get("time") or [], hourly.get("sea_level_height_msl") or []):
        if h is None:
            continue
        try:
            out.append((datetime.fromisoformat(t).replace(tzinfo=timezone.utc) - offset, float(h)))
        except (TypeError, ValueError):
            continue
    return out


_tides = {}
_tides_lock = threading.Lock()
# How long a place whose year could not be had waits before asking again.
_RETRY_AFTER = 300


def _tide(lat, lng):
    """The tide fitted to last year's model hours here, or None.

    Fitted once a year for each place and kept on disk; a second caller
    while the first is fitting waits for its answer rather than fitting
    again, since the day view asks for the curve, the turns and the axis
    all at once.
    """
    year = date.today().year - 1
    key = (location_cache_key(lat, lng), year)
    with _tides_lock:
        known = _tides.get(key)
        if known is not None and (known[0] is not None or time.monotonic() < known[1]):
            return known[0]
        cache_file = cache_dir() / f"om_fit_{key[0]}_{year}.json"
        cached = read_cache(cache_file, 400 * 86400)
        tide = None
        if cached:
            try:
                tide = harmonic.Tide([tuple(c) for c in cached["constants"]], z0=cached["z0"])
            except (KeyError, TypeError, ValueError) as exc:
                log_failure("tides/open-meteo", "read of fitted tide", exc, fallback="fit again")
        if tide is None:
            samples = _instants(_fetch_year(lat, lng, year, date.today()))
            if len(samples) >= FIT_MIN_HOURS:
                tide = harmonic.fit(samples, FIT_NAMES)
            if tide is not None:
                write_cache(cache_file, {"z0": tide.z0, "constants": tide.constants()})
        _tides[key] = (tide, time.monotonic() + _RETRY_AFTER)
        return tide


def _payload(lat, lng):
    """A response to read the model's cell and the place's zone from:
    last year's, which is kept a year, or else the forecast window's."""
    data = _fetch_year(lat, lng, date.today().year - 1, date.today())
    return data if _instants(data) else _fetch_raw(lat, lng)


def fetch_modeled_extremes_openmeteo(station_id: str, year: int,
                                     today: date) -> dict[date, tuple[float, float]]:
    """{day: (lowest, highest)} of the model's own heights in *year*
    before *today*, tide and weather together, in feet: the year view's
    pen, which the view marks as modeled."""
    coords = parse_station_id(station_id)
    if coords is None:
        return {}
    data = _fetch_year(*coords, year, today)
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(data.get("timezone")) if data and data.get("timezone") else timezone.utc
    except Exception as exc:
        log_failure("tides/open-meteo", "zone of the year", exc, fallback="UTC days")
        zone = timezone.utc
    days = {}
    for t, h in _instants(data):
        day = t.astimezone(zone).date()
        if day.year != year or day >= today:
            continue
        lo, hi = days.get(day, (h, h))
        days[day] = (min(lo, h), max(hi, h))
    return {d: (lo * M_TO_FT, hi * M_TO_FT) for d, (lo, hi) in days.items()}


# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------
def find_nearest_openmeteo(lat: float | None, lng: float | None
                           ) -> tuple[str | None, None]:
    """Return (pseudo_station_id, None) when the tide model covers this
    location, or (None, None) when it doesn't (far inland / fetch failure).

    The display name is left to the caller, which knows the location label.
    """
    if lat is None or lng is None:
        return None, None
    if not _instants(_payload(lat, lng)):
        return None, None
    return make_station_id(lat, lng), None


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_openmeteo(station_id: str) -> dict[str, Any] | None:
    """Build NOAA-shaped metadata from the model response for this location."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    data = _payload(*coords)
    if not data or not isinstance(data, dict):
        return None
    try:
        tz_corr = float(data.get("utc_offset_seconds", 0)) / 3600
    except (TypeError, ValueError):
        tz_corr = 0
    return {
        "id": station_id,
        "name": "",
        "state": "",
        "lat": data.get("latitude", coords[0]),
        "lng": data.get("longitude", coords[1]),
        "timezone_abbr": "",
        "timezonecorr": tz_corr,
        "timeZoneCode": data.get("timezone", ""),
        "observedst": False,
        "source": "openmeteo",
    }


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------
def fetch_tides_range_openmeteo(
    station_id: str, start_date: date, end_date: date, station_tz: tzinfo | None,
) -> list[tuple[datetime, float]]:
    """Heights across a date range as [(dt, height_ft)]: six-minute ones
    from the fitted tide, or without one the model's own hours, whose
    window is fixed (31 days back, 8 days ahead); dates outside it are
    simply absent from the result.
    """
    coords = parse_station_id(station_id)
    if coords is None:
        return []
    tide = _tide(*coords)
    if tide is not None:
        return computed_range(tide, start_date, end_date, station_tz)
    points = _series(_fetch_raw(*coords), station_tz)
    lo, hi = local_day_bounds(start_date, end_date, station_tz)
    return [(dt, h) for dt, h in points if lo <= dt <= hi]


def _extrema(points):
    """Find high/low events in an hourly series with parabolic refinement.

    Fits a parabola through each local extremum and its neighbours to
    recover sub-hour timing and peak height from hourly samples.
    """
    out = []
    for i in range(1, len(points) - 1):
        (t0, a), (t1, b), (t2, c) = points[i - 1], points[i], points[i + 1]
        if b >= a and b > c:
            typ = "H"
        elif b <= a and b < c:
            typ = "L"
        else:
            continue
        denom = a - 2 * b + c
        offset = 0.5 * (a - c) / denom if denom else 0.0
        offset = max(-1.0, min(1.0, offset))
        zone = t1.tzinfo
        if zone is not None:
            # Measured on the instants: the hours either side of a clock
            # change are an hour apart, not the two or none the wall
            # clock counts.
            t0, t1, t2 = (t.astimezone(timezone.utc) for t in (t0, t1, t2))
        step = ((t2 - t0) / 2)
        dt = t1 + step * offset
        if zone is not None:
            dt = dt.astimezone(zone)
        height = b - 0.25 * (a - c) * offset
        out.append((dt, height, typ))
    return out


def fetch_hilo_range_openmeteo(
    station_id: str, start_date: date, end_date: date, station_tz: tzinfo | None,
) -> list[tuple[datetime, float, str]]:
    """High/low events across a date range as [(dt, height_ft, "H"|"L")]."""
    coords = parse_station_id(station_id)
    if coords is None:
        return []
    tide = _tide(*coords)
    if tide is not None:
        return computed_hilo(tide, start_date, end_date, station_tz)
    points = _series(_fetch_raw(*coords), station_tz)
    lo, hi = local_day_bounds(start_date, end_date, station_tz)
    return [(dt, h, t) for dt, h, t in _extrema(points) if lo <= dt <= hi]


def fetch_y_range_openmeteo(station_id: str, center_date: date,
                            station_tz: tzinfo | None) -> tuple[float, float] | None:
    """Y-axis range: the fitted tide's over the months around the date,
    or without one the fetched window's (it spans spring and neap)."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    tide = _tide(*coords)
    if tide is not None:
        return computed_y_range(tide, center_date, station_tz)
    return cached_y_range(
        cache_dir() / f"om_yrange_{location_cache_key(*coords)}.json",
        lambda: [h for _, h in _series(_fetch_raw(*coords), station_tz)],
    )
