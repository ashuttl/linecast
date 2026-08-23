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
rendering pipeline.  High/low events are derived locally from the hourly
series with parabolic refinement for sub-hour timing.
"""

from datetime import datetime

from linecast import USER_AGENT
from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._tides_common import CACHE_DIR, M_TO_FT, cached_y_range, local_day_bounds

# One standard fetch window serves every caller (range, hilo, y-range,
# metadata) from a single cached payload.  The marine API caps forecasts
# at 8 days; 31 past days give the y-range a real spring/neap spread.
PAST_DAYS = 31
FORECAST_DAYS = 8
RAW_CACHE_MAX_AGE = 3 * 3600


# ---------------------------------------------------------------------------
# Pseudo-station IDs
# ---------------------------------------------------------------------------
def make_station_id(lat, lng):
    """Encode coordinates as an Open-Meteo pseudo-station ID."""
    return f"om:{float(lat):.4f},{float(lng):.4f}"


def is_openmeteo_station_id(station_id):
    return str(station_id).startswith("om:")


def parse_station_id(station_id):
    """Decode an `om:lat,lng` pseudo-station ID to (lat, lng) or None."""
    try:
        lat_str, lng_str = str(station_id)[3:].split(",")
        return float(lat_str), float(lng_str)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Raw fetch
# ---------------------------------------------------------------------------
def _fetch_raw(lat, lng):
    """Fetch the standard tide-model window for a location.  Cached 3h."""
    cache_file = CACHE_DIR / f"om_raw_{location_cache_key(lat, lng)}.json"
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=sea_level_height_msl"
        f"&timezone=auto&past_days={PAST_DAYS}&forecast_days={FORECAST_DAYS}"
    )
    return fetch_json_cached(
        cache_file, RAW_CACHE_MAX_AGE, url,
        headers={"User-Agent": USER_AGENT},
        timeout=15, fallback=None,
    )


def _series(data, station_tz):
    """Parse a raw payload to a sorted [(aware_local_dt, height_ft)] list."""
    if not data or not isinstance(data, dict):
        return []
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    heights = hourly.get("sea_level_height_msl", [])
    points = []
    for t, h in zip(times, heights):
        if h is None:
            continue
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            continue
        if station_tz is not None:
            dt = dt.replace(tzinfo=station_tz)
        points.append((dt, float(h) * M_TO_FT))
    points.sort(key=lambda p: p[0])
    return points


# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------
def find_nearest_openmeteo(lat, lng):
    """Return (pseudo_station_id, None) when the tide model covers this
    location, or (None, None) when it doesn't (far inland / fetch failure).

    The display name is left to the caller, which knows the location label.
    """
    if lat is None or lng is None:
        return None, None
    data = _fetch_raw(lat, lng)
    if not _series(data, None):
        return None, None
    return make_station_id(lat, lng), None


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_openmeteo(station_id):
    """Build NOAA-shaped metadata from the model response for this location."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    data = _fetch_raw(*coords)
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
def fetch_tides_range_openmeteo(station_id, start_date, end_date, station_tz):
    """Hourly model heights across a date range as [(dt, height_ft)].

    The model window is fixed (31 days back, 8 days ahead); dates outside
    it are simply absent from the result.
    """
    coords = parse_station_id(station_id)
    if coords is None:
        return []
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
        step = ((t2 - t0) / 2)
        dt = t1 + step * offset
        height = b - 0.25 * (a - c) * offset
        out.append((dt, height, typ))
    return out


def fetch_hilo_range_openmeteo(station_id, start_date, end_date, station_tz):
    """High/low events across a date range as [(dt, height_ft, "H"|"L")]."""
    coords = parse_station_id(station_id)
    if coords is None:
        return []
    points = _series(_fetch_raw(*coords), station_tz)
    lo, hi = local_day_bounds(start_date, end_date, station_tz)
    return [(dt, h, t) for dt, h, t in _extrema(points) if lo <= dt <= hi]


def fetch_y_range_openmeteo(station_id, center_date, station_tz):
    """Y-axis range from the full fetched window (spans spring/neap)."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    return cached_y_range(
        CACHE_DIR / f"om_yrange_{location_cache_key(*coords)}.json",
        lambda: [h for _, h in _series(_fetch_raw(*coords), station_tz)],
    )
