#!/usr/bin/env python3
"""Tides — terminal visualization of tide predictions.

Renders a multi-line graphical display of the tide curve with an
ocean-themed color palette. Shows water level as a braille line graph
with height-colored curve, high/low labels, and current position indicator.

Uses Unicode braille characters with ANSI color for smooth line rendering
(true color when available). Station is auto-detected from IP geolocation
or overridden with TIDE_STATION env var.

Data sources: NOAA (US) and CHS/IWLS (Canada), selected automatically
based on geolocation. Use --station with a station ID to override.

Usage: tides [--live] [--station ID] [--search QUERY] [--metric] [--lang LANG]
"""

import math
import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta

from linecast._braille import build_braille_curve
from linecast._graphics import (
    bg, fg, RESET,
    visible_len, fmt_hour, fmt_time_dt,
    get_terminal_size, live_loop,
)
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._http import fetch_json, fetch_json_cached
from linecast._location import get_location
from linecast._runtime import TidesRuntime, arg_value, has_flag
from linecast._tides_i18n import FULL_DAY_NAMES, _ts
from linecast._tides_chs import (
    find_nearest_station_chs, fetch_station_metadata_chs,
    fetch_tides_range_chs, fetch_hilo_range_chs, fetch_y_range_chs,
    _fetch_all_stations_chs,
)
from linecast import USER_AGENT

CACHE_DIR = CACHE_ROOT / "tides"
NEAREST_STATION_CACHE_MAX_AGE = 3600

# ---------------------------------------------------------------------------
# Ocean palette
# ---------------------------------------------------------------------------
CURVE_COLOR = (120, 200, 220)       # teal curve line
NOW_LINE_COLOR = (65, 95, 140)      # "now" indicator
HOVER_COLOR = (80, 90, 120)         # hover indicator
DIM = fg(70, 80, 100)
NIGHT_DIM = 0.6                     # brightness floor for nighttime

# Nerd Font icons
WAVE_ICON = "\U000F0F85"            # 󰾅

# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
def _is_chs_station_id(station_id):
    """Check if a station ID is a CHS MongoDB ObjectId (24-char hex)."""
    return (len(station_id) == 24 and
            all(c in '0123456789abcdef' for c in station_id.lower()))


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in nautical miles between two points."""
    R_nm = 3440.065  # Earth radius in nautical miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R_nm * 2 * math.asin(math.sqrt(a))


def find_nearest_station(lat, lng):
    """Find closest NOAA tide station by haversine distance.

    Returns (station_id, station_name) or (None, None).
    Cached per location for 1 hour.
    """
    cache_file = CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    try:
        url = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    except Exception:
        # Try stale cache
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    best_id, best_name, best_dist = None, None, float("inf")
    for s in data.get("stations", []):
        try:
            slat = float(s["lat"])
            slng = float(s["lng"])
        except (KeyError, ValueError):
            continue
        d = _haversine(lat, lng, slat, slng)
        if d < best_dist:
            best_dist = d
            best_id = str(s.get("id", ""))
            best_name = s.get("name", "")

    if best_dist > 100:  # > 100 nautical miles
        return None, None

    result = {"id": best_id, "name": best_name, "lat": lat, "lng": lng}
    write_cache(cache_file, result)
    return best_id, best_name


def _fetch_station_metadata(station_id):
    """Fetch station metadata needed for timezone handling. Cached 30 days."""
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
    s = stations[0]
    details = s.get("details", {})
    meta = {
        "id": str(s.get("id", station_id)),
        "name": s.get("name", ""),
        "state": s.get("state", ""),
        "lat": s.get("lat"),
        "lng": s.get("lng"),
        "timezone_abbr": str(s.get("timezone", "")).upper(),
        "timezonecorr": s.get("timezonecorr", details.get("timezone")),
        "observedst": bool(s.get("observedst", False)),
    }
    write_cache(cache_file, meta)
    return meta


def _station_tzinfo(meta):
    """Resolve a station timezone to tzinfo using metadata and safe fallbacks."""
    if not meta:
        return None

    # CHS stations provide IANA timezone directly
    tz_code = meta.get("timeZoneCode")
    if tz_code:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_code)
        except Exception:
            pass

    tz_abbr = str(meta.get("timezone_abbr", "")).upper()
    state = str(meta.get("state", "")).upper()
    observedst = bool(meta.get("observedst", False))

    zone_name = None
    if tz_abbr in ("UTC", "GMT", "Z"):
        return timezone.utc
    elif tz_abbr in ("EST", "EDT"):
        zone_name = "America/Puerto_Rico" if state in ("PR", "VI") else "America/New_York"
    elif tz_abbr in ("CST", "CDT"):
        zone_name = "America/Chicago"
    elif tz_abbr in ("MST", "MDT"):
        if not observedst or state == "AZ":
            zone_name = "America/Phoenix"
        else:
            zone_name = "America/Denver"
    elif tz_abbr in ("PST", "PDT"):
        zone_name = "America/Los_Angeles"
    elif tz_abbr in ("AKST", "AKDT"):
        zone_name = "America/Anchorage"
    elif tz_abbr in ("HST", "HDT"):
        zone_name = "Pacific/Honolulu"
    elif tz_abbr in ("AST", "ADT"):
        zone_name = "America/Halifax" if observedst else "America/Puerto_Rico"
    elif tz_abbr == "CHST":
        zone_name = "Pacific/Guam"
    elif tz_abbr == "SST":
        zone_name = "Pacific/Pago_Pago"

    if zone_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(zone_name)
        except Exception:
            pass

    # Fallback: fixed offset from metadata (less precise around DST boundaries)
    try:
        return timezone(timedelta(hours=float(meta.get("timezonecorr"))))
    except Exception:
        return None


def _station_now(meta):
    """Current datetime in station local time when possible."""
    tz = _station_tzinfo(meta)
    if tz is not None:
        return datetime.now(tz)
    return datetime.now()


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


def _parse_prediction_hour(t_str):
    try:
        parts = t_str.split(" ")
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
        return None

    rows = []
    for prediction in predictions:
        row = row_builder(prediction)
        if row is not None:
            rows.append(row)
    write_cache(cache_file, rows)
    return [tuple_builder(row) for row in rows]


def fetch_tides(station_id, date):
    """Fetch 6-minute interval tide predictions for a date.

    Returns list of (hour_decimal, height_ft) tuples. Cached 24h.
    """
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
    """Fetch high/low extremes for a date.

    Returns list of (hour_decimal, height_ft, "H"/"L") tuples. Cached 24h.
    """
    date_str = date.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"hilo_{station_id}_{date_str}.json"
    url = _prediction_url(station_id, date_str, date_str, "hilo")
    return _fetch_prediction_rows(
        cache_file,
        url,
        row_builder=_build_hilo_row,
        tuple_builder=lambda row: (row["h"], row["v"], row["t"]),
    )


def _fetch_all_stations():
    """Fetch the full NOAA tide-prediction station list (cached 30 days)."""
    cache_file = CACHE_DIR / "all_stations.json"
    url = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
    data = _fetch_payload(cache_file, 30 * 86400, url, fallback=[])
    if isinstance(data, list):
        return data
    stations = data.get("stations", [])
    write_cache(cache_file, stations)
    return stations


def _search_stations(query):
    """Search NOAA and CHS stations by name substring. Prints matches and exits."""
    q = query.lower()

    # NOAA
    noaa_stations = _fetch_all_stations()
    noaa_matches = [s for s in (noaa_stations or []) if q in s.get("name", "").lower()]
    noaa_matches.sort(key=lambda s: s.get("name", ""))

    # CHS (Canada)
    chs_stations = _fetch_all_stations_chs()
    chs_matches = [s for s in (chs_stations or [])
                   if q in s.get("officialName", "").lower()]
    chs_matches.sort(key=lambda s: s.get("officialName", ""))

    if not noaa_matches and not chs_matches:
        print(f"No stations matching \"{query}\".")
        sys.exit(0)

    for s in noaa_matches[:20]:
        sid = s.get("id", "")
        name = s.get("name", "")
        state = s.get("state", "")
        label = f"{name}, {state}" if state else name
        print(f"  {sid}  {label}")

    if noaa_matches and chs_matches:
        print()

    for s in chs_matches[:20]:
        sid = s.get("id", "")
        name = s.get("officialName", "")
        print(f"  {sid}  {name}")

    total = len(noaa_matches) + len(chs_matches)
    shown = min(len(noaa_matches), 20) + min(len(chs_matches), 20)
    if total > shown:
        print(f"  ... and {total - shown} more")


# ---------------------------------------------------------------------------
# Multi-day fetch & stitch
# ---------------------------------------------------------------------------
def _day_to_dt(hour_decimal, date, station_tz):
    """Convert a day-relative decimal hour to an aware datetime."""
    h = int(hour_decimal)
    m = int(round((hour_decimal - h) * 60))
    if h >= 24:
        date = date + timedelta(days=1)
        h -= 24
    try:
        dt = datetime(date.year, date.month, date.day, h, m)
    except ValueError:
        return None
    if station_tz is not None:
        dt = dt.replace(tzinfo=station_tz)
    return dt


def fetch_tides_range(station_id, start_date, end_date, station_tz):
    """Fetch and stitch tide predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    """
    points = []
    d = start_date
    while d <= end_date:
        day_data = fetch_tides(station_id, d)
        if day_data:
            for hour, height in day_data:
                dt = _day_to_dt(hour, d, station_tz)
                if dt is not None:
                    points.append((dt, height))
        d += timedelta(days=1)
    # De-duplicate by datetime (day boundaries may overlap at 00:00)
    seen = set()
    unique = []
    for dt, h in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, h))
    unique.sort(key=lambda p: p[0])
    return unique


def fetch_hilo_range(station_id, start_date, end_date, station_tz):
    """Fetch and stitch hi/lo extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    """
    points = []
    d = start_date
    while d <= end_date:
        day_data = fetch_hilo(station_id, d)
        if day_data:
            for hour, height, typ in day_data:
                dt = _day_to_dt(hour, d, station_tz)
                if dt is not None:
                    points.append((dt, height, typ))
        d += timedelta(days=1)
    points.sort(key=lambda p: p[0])
    return points


def fetch_y_range(station_id, center_date):
    """Compute y-axis range from ±30 days of hilo data. Single API call, cached 7 days."""
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
    for p in predictions:
        try:
            heights.append(float(p["v"]))
        except (KeyError, ValueError):
            pass

    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------
def _interp_height(target_dt, predictions):
    """Linearly interpolate tide height at a given datetime."""
    if not predictions:
        return 0.0
    if target_dt <= predictions[0][0]:
        return predictions[0][1]
    if target_dt >= predictions[-1][0]:
        return predictions[-1][1]
    for i in range(len(predictions) - 1):
        if predictions[i][0] <= target_dt <= predictions[i + 1][0]:
            span = (predictions[i + 1][0] - predictions[i][0]).total_seconds()
            if span == 0:
                return predictions[i][1]
            frac = (target_dt - predictions[i][0]).total_seconds() / span
            return predictions[i][1] + (predictions[i + 1][1] - predictions[i][1]) * frac
    return predictions[-1][1]


def _prepare_tide_window(predictions, hilo, start_dt, hours_shown=24):
    """Slice prediction data to a visible window starting at start_dt.

    Returns dict with: predictions (filtered), hilo (filtered),
    start, end, total_hours.
    """
    end_dt = start_dt + timedelta(hours=hours_shown)
    margin = timedelta(minutes=10)
    win_preds = [(dt, h) for dt, h in predictions
                 if start_dt - margin <= dt <= end_dt + margin]
    win_hilo = [(dt, h, t) for dt, h, t in hilo
                if start_dt <= dt <= end_dt]
    return {
        "predictions": win_preds,
        "hilo": win_hilo,
        "start": start_dt,
        "end": end_dt,
        "total_hours": hours_shown,
    }


# ---------------------------------------------------------------------------
# Daylight computation (datetime-window aware)
# ---------------------------------------------------------------------------
def _solar_daylight_at(hour, doy, lat, lng, tz_offset_h):
    """Compute daylight factor (0.0–1.0) at a local clock hour on a given day."""
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    lat_rad = math.radians(lat)
    decl_rad = math.radians(decl)

    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    if cos_ha <= -1:
        return 1.0  # midnight sun
    if cos_ha >= 1:
        return 0.0  # polar night

    ha = math.degrees(math.acos(cos_ha))

    solar_noon = 12.0
    if lng is not None:
        tz_meridian = tz_offset_h * 15
        solar_noon += (tz_meridian - lng) / 15

    sunrise = solar_noon - ha / 15
    sunset = solar_noon + ha / 15
    transition = 40 / 60  # 40 minutes

    if hour < sunrise - transition or hour > sunset + transition:
        return 0.0
    if sunrise + transition <= hour <= sunset - transition:
        return 1.0
    if hour < sunrise + transition:
        return (hour - sunrise + transition) / (2 * transition)
    return (sunset + transition - hour) / (2 * transition)


def _compute_daylight_window(graph_w, window_start, total_hours, station_meta):
    """Compute per-column daylight factor for a datetime window."""
    if not station_meta:
        return [1.0] * graph_w

    try:
        lat = float(station_meta["lat"])
        tz_offset_h = float(station_meta["timezonecorr"])
    except (KeyError, TypeError, ValueError):
        return [1.0] * graph_w

    try:
        lng = float(station_meta["lng"])
    except (KeyError, TypeError, ValueError):
        lng = None

    col_daylight = []
    for x in range(graph_w):
        frac = (x + 0.5) / graph_w
        col_dt = window_start + timedelta(hours=frac * total_hours)
        doy = col_dt.timetuple().tm_yday
        hour = col_dt.hour + col_dt.minute / 60
        col_daylight.append(_solar_daylight_at(hour, doy, lat, lng, tz_offset_h))
    return col_daylight


# ---------------------------------------------------------------------------
# Time markers (day divisions)
# ---------------------------------------------------------------------------
def _compute_time_markers(window_start, total_hours, graph_w, runtime):
    """Compute midnight column positions and day labels for the window."""
    lang = runtime.lang if runtime else "en"
    midnight_cols = set()
    midnight_day_names = {}

    # Find first midnight at or after window_start
    first_midnight = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if first_midnight <= window_start:
        first_midnight += timedelta(days=1)

    dt = first_midnight
    window_secs = total_hours * 3600
    while dt < window_start + timedelta(hours=total_hours):
        offset_secs = (dt - window_start).total_seconds()
        x = int(offset_secs / window_secs * (graph_w - 1))
        if 0 < x < graph_w - 1:
            midnight_cols.add(x)
            day_names = FULL_DAY_NAMES.get(lang, FULL_DAY_NAMES["en"])
            midnight_day_names[x] = day_names[dt.weekday()]
        dt += timedelta(days=1)

    return midnight_cols, midnight_day_names


# ---------------------------------------------------------------------------
# Overlays (hi/lo labels)
# ---------------------------------------------------------------------------
def _hilo_to_extrema(window, graph_w, runtime):
    """Convert window hilo data to extrema positions for labeling."""
    hilo = window["hilo"]
    if not hilo:
        return []
    start = window["start"]
    secs = window["total_hours"] * 3600
    extrema = []
    for dt, height, typ in hilo:
        frac = (dt - start).total_seconds() / secs
        x = max(0, min(graph_w - 1, int(frac * (graph_w - 1))))
        h_display = runtime.convert_height(height)
        extrema.append((x, height, h_display, typ == "H", dt))
    return extrema


def _compute_tide_overlays(extrema, col_heights, n_rows, graph_w, runtime,
                           value_range=None, braille_rows=None):
    """Map tide extrema to overlay labels on specific braille rows."""
    if not extrema or n_rows < 1:
        return {}

    if value_range is not None:
        h_min, h_max = value_range
    else:
        h_min, h_max = min(col_heights), max(col_heights)
    pad = max(0.3, (h_max - h_min) * 0.15)
    h_min -= pad
    h_max += pad
    total_dots = n_rows * 4
    overlays = {}
    occupied_by_row = {}
    dim_color = (70, 80, 100)

    def _row_clear(row, cols):
        """Check if all columns in a braille row are empty (no dots)."""
        if braille_rows is None or row < 0 or row >= n_rows:
            return True
        return all(braille_rows[row][c][0] == '\u2800' for c in cols if 0 <= c < graph_w)

    for x, height_ft, height_display, is_peak, dt in extrema:
        if h_max == h_min:
            curve_row = n_rows // 2
        else:
            y = (total_dots - 1) * (1 - (height_ft - h_min) / (h_max - h_min))
            curve_row = max(0, min(n_rows - 1, int(round(y)) // 4))

        label_row = max(0, curve_row - 1) if is_peak else min(n_rows - 1, curve_row + 1)

        label = f"{height_display:.1f}{runtime.height_unit}"
        start = max(0, min(graph_w - len(label), x - len(label) // 2))

        if label_row not in occupied_by_row:
            occupied_by_row[label_row] = set()
        label_cols = set(range(start, start + len(label)))
        if label_cols & occupied_by_row[label_row]:
            continue
        occupied_by_row[label_row] |= label_cols

        overlays.setdefault(label_row, []).append((start, label, CURVE_COLOR, False))

        # Time label: scan outward from curve to find a clear row
        time_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
        time_start = max(0, min(graph_w - len(time_str), x - len(time_str) // 2))
        time_cols_set = set(range(time_start, time_start + len(time_str)))

        # Search direction: away from curve (up for peaks, down for lows)
        direction = -1 if is_peak else 1
        placed = False
        for offset in range(1, 5):
            candidate = label_row + offset * direction
            if candidate < 0 or candidate >= n_rows:
                break
            if candidate not in occupied_by_row:
                occupied_by_row[candidate] = set()
            if (time_cols_set & occupied_by_row[candidate]):
                continue
            if not _row_clear(candidate, time_cols_set):
                continue
            occupied_by_row[candidate] |= time_cols_set
            overlays.setdefault(candidate, []).append(
                (time_start, time_str, dim_color, True))
            placed = True
            break

        # Fallback: try the other direction
        if not placed:
            for offset in range(1, 5):
                candidate = label_row - offset * direction
                if candidate < 0 or candidate >= n_rows:
                    break
                if candidate not in occupied_by_row:
                    occupied_by_row[candidate] = set()
                if (time_cols_set & occupied_by_row[candidate]):
                    continue
                if not _row_clear(candidate, time_cols_set):
                    continue
                occupied_by_row[candidate] |= time_cols_set
                overlays.setdefault(candidate, []).append(
                    (time_start, time_str, dim_color, True))
                break

    return overlays


def _compute_y_axis_labels(n_rows, graph_w, value_range, pad_frac, runtime):
    """Compute y-axis height labels as background overlays (right-aligned)."""
    if value_range is None or n_rows < 4:
        return {}

    h_min, h_max = value_range
    pad = max(0.3, (h_max - h_min) * pad_frac)
    h_min -= pad
    h_max += pad
    h_range = h_max - h_min
    if h_range <= 0:
        return {}

    total_dots = n_rows * 4
    # Use raw range (before padding) for step calculation
    disp_range = abs(runtime.convert_height(value_range[1]) - runtime.convert_height(value_range[0]))

    step = 1 if disp_range <= 4 else 2 if disp_range <= 10 else 5
    dim_color = (70, 80, 100)  # match x-axis tick color (DIM)
    overlays = {}

    disp_min = runtime.convert_height(h_min)
    disp_max = runtime.convert_height(h_max)
    tick_disp = math.ceil(disp_min / step) * step
    while tick_disp <= disp_max:
        tick_ft = tick_disp / 0.3048 if runtime.metric else tick_disp
        y = (total_dots - 1) * (1 - (tick_ft - h_min) / h_range)
        row = int(round(y)) // 4
        if 1 <= row < n_rows - 1:  # skip top/bottom edge rows
            label = f"{tick_disp:.0f}{runtime.height_unit}"
            start = graph_w - len(label)
            overlays.setdefault(row, []).append((start, label, dim_color, True))
        tick_disp += step

    return overlays


# ---------------------------------------------------------------------------
# Braille rendering
# ---------------------------------------------------------------------------
def _render_tide_braille_rows(braille_rows, col_daylight, midnight_cols,
                               now_col=None, hover_col=None, overlays=None):
    """Render braille tide rows with daylight dimming, indicators, and overlays.

    Overlay priority: foreground overlays > braille dots > indicators > background overlays.
    """
    if overlays is None:
        overlays = {}

    now_fg = fg(*NOW_LINE_COLOR)
    hover_fg = fg(*HOVER_COLOR)
    cr, cg, cb = CURVE_COLOR
    lines = []
    for row_idx, row in enumerate(braille_rows):
        # Split overlays into foreground (always render) and background (behind curve)
        fg_chars = {}
        bg_chars = {}
        for entry in overlays.get(row_idx, []):
            start_col, label, color = entry[0], entry[1], entry[2]
            behind = entry[3] if len(entry) > 3 else False
            for j, c in enumerate(label):
                col = start_col + j
                if 0 <= col < len(row):
                    if behind:
                        bg_chars.setdefault(col, (c, color))
                    else:
                        fg_chars[col] = (c, color)

        line = " "
        for ci, (ch, _height) in enumerate(row):
            if ci in fg_chars:
                oc, oc_color = fg_chars[ci]
                line += f"{fg(*oc_color)}{oc}"
            elif ch != '\u2800':
                dl = col_daylight[ci] if ci < len(col_daylight) else 1.0
                brightness = NIGHT_DIM + (1.0 - NIGHT_DIM) * dl
                line += f"{fg(int(cr * brightness), int(cg * brightness), int(cb * brightness))}{ch}"
            elif hover_col is not None and ci == hover_col:
                line += f"{hover_fg}\u2502"
            elif now_col is not None and ci == now_col:
                line += f"{now_fg}\u2502"
            elif ci in midnight_cols:
                line += f"{DIM}\u2502"
            elif ci in bg_chars:
                oc, oc_color = bg_chars[ci]
                line += f"{fg(*oc_color)}{oc}"
            else:
                line += " "
        lines.append(f"{line}{RESET}")
    return lines


# ---------------------------------------------------------------------------
# Tick labels
# ---------------------------------------------------------------------------
def _render_tide_ticks(window_start, total_hours, graph_w, runtime,
                        now_col=None, hover_col=None):
    """Render time axis labels under the chart."""
    use_24h = runtime.use_24h
    if graph_w < 40:
        interval = 6
    elif graph_w < 80:
        interval = 4
    elif graph_w < 140:
        interval = 3
    else:
        interval = 2

    label_items = []
    for h_off in range(0, int(total_hours) + 1, interval):
        dt = window_start + timedelta(hours=h_off)
        x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
        label_items.append((x, fmt_hour(dt.hour, use_24h), dt.hour == 0))

    canvas = [" "] * graph_w
    last_end = 0
    for x, label, is_midnight in label_items:
        tick = "\u2502" if is_midnight else "\u2575"
        tick_label = f"{tick}{label}"
        if x < last_end or x + len(tick_label) > graph_w:
            continue
        for j, c in enumerate(tick_label):
            if x + j < graph_w:
                canvas[x + j] = c
        last_end = x + len(tick_label) + 1

    if hover_col is not None and 0 <= hover_col < graph_w and canvas[hover_col] == " ":
        canvas[hover_col] = "\u2502"
    elif now_col is not None and 0 <= now_col < graph_w and canvas[now_col] == " ":
        canvas[now_col] = "\u2502"

    return f" {DIM}{''.join(canvas)}{RESET}"


# ---------------------------------------------------------------------------
# Header line (day names at midnight boundaries)
# ---------------------------------------------------------------------------
def _render_header_line(cols, station_name, runtime, offset_minutes=0):
    """Render the top line with pill-styled station name and scroll hint."""
    name = station_name.title() if station_name else ""

    # Station name pill (left)
    if name:
        pbg = bg(28, 36, 52)
        pfg = fg(160, 170, 190)
        pedge = fg(28, 36, 52)
        pill = f"{pedge}\u2590{pbg}{pfg} {name} {RESET}{pedge}\u258c{RESET}"
        pill_w = len(name) + 4  # ▐ + space + name + space + ▌
    else:
        pill = ""
        pill_w = 0

    # "Space to return" hint (right, only when scrolled)
    if offset_minutes:
        hint_text = _ts("space_to_now", runtime)
        hint = f"{DIM}{hint_text}{RESET}"
        padding = max(1, cols - 1 - pill_w - len(hint_text))
        return f"{pill}{' ' * padding}{hint}"
    return pill


def _render_day_label_line(midnight_day_names, graph_w):
    """Render day name labels on their own row, aligned with chart columns."""
    muted = fg(100, 110, 130)
    canvas = [" "] * graph_w
    for col, day_name in sorted(midnight_day_names.items()):
        pos = col + 1  # +1 for chart left margin
        for j, c in enumerate(day_name):
            if 0 <= pos + j < graph_w:
                canvas[pos + j] = c
    return f" {muted}{''.join(canvas)}{RESET}"


# ---------------------------------------------------------------------------
# Hover tooltip
# ---------------------------------------------------------------------------
def _build_tide_hover_tooltip(window, graph_col, mouse_row, chart_start, chart_end,
                               cols, rows, graph_w, runtime):
    """Build cursor-positioned tooltip overlay for mouse hover on the chart."""
    line_idx = mouse_row - 1  # 1-based -> 0-based
    if not (chart_start <= line_idx < chart_end):
        return ""
    if graph_col < 0 or graph_col >= graph_w:
        return ""

    predictions = window["predictions"]
    if not predictions:
        return ""

    total_hours = window["total_hours"]
    start_dt = window["start"]

    # Map graph column to datetime
    t_frac = graph_col / max(1, graph_w - 1)
    target_dt = start_dt + timedelta(hours=t_frac * total_hours)
    height = _interp_height(target_dt, predictions)

    TBG = bg(0, 0, 0)
    TFG = fg(200, 205, 215)

    time_str = fmt_time_dt(target_dt, use_24h=runtime.use_24h)
    h_display = runtime.convert_height(height)

    tip_lines = [
        f"{TBG}{TFG} {time_str} ",
        f"{TBG}{TFG} {h_display:.1f}{runtime.height_unit} ",
    ]

    # Pad all lines to the same visible width
    max_w = max(visible_len(line) for line in tip_lines)
    padded = []
    for line in tip_lines:
        pad = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad}{RESET}")

    # Position tooltip near snap column
    snap_col = graph_col + 2  # 0-based graph -> 1-based terminal (1 char margin)
    tooltip_col = snap_col
    tooltip_row = mouse_row
    tooltip_w = max_w
    tooltip_h = len(padded)
    if tooltip_col + tooltip_w - 1 > cols:
        tooltip_col = max(1, cols - tooltip_w + 1)
    if tooltip_row + tooltip_h - 1 > rows:
        tooltip_row = max(1, rows - tooltip_h + 1)

    result = ""
    for i, line in enumerate(padded):
        result += f"\033[{tooltip_row + i};{tooltip_col}H{line}"
    return result


# ---------------------------------------------------------------------------
# "Now" label
# ---------------------------------------------------------------------------
def _build_now_label(window, now_col, now_local, chart_start, n_braille_rows,
                     cols, rows, graph_w, runtime, value_range=None):
    """Build a tooltip-like label attached to the 'now' line."""
    if now_col is None:
        return ""

    predictions = window["predictions"]
    if not predictions:
        return ""

    now_height = _interp_height(now_local, predictions)
    h_display = runtime.convert_height(now_height)
    time_str = fmt_time_dt(now_local, use_24h=runtime.use_24h)

    TBG = bg(0, 0, 0)
    TFG = fg(200, 205, 215)

    tip_lines = [
        f"{TBG}{TFG} {time_str} ",
        f"{TBG}{TFG} {h_display:.1f}{runtime.height_unit} ",
    ]

    max_w = max(visible_len(line) for line in tip_lines)
    padded = []
    for line in tip_lines:
        pad_n = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad_n}{RESET}")

    # Map now_height to a braille row for positioning
    if value_range is not None:
        h_min, h_max = value_range
    else:
        h_min, h_max = now_height - 1, now_height + 1
    pad_v = max(0.3, (h_max - h_min) * 0.15)
    h_min -= pad_v
    h_max += pad_v
    total_dots = n_braille_rows * 4
    if h_max > h_min:
        y = (total_dots - 1) * (1 - (now_height - h_min) / (h_max - h_min))
        curve_row = max(0, min(n_braille_rows - 1, int(round(y)) // 4))
    else:
        curve_row = n_braille_rows // 2

    # Terminal positioning (1-indexed for ANSI)
    snap_col = now_col + 2  # graph col -> terminal col
    tooltip_h = len(padded)

    # Place tooltip at top or bottom of graph, opposite the curve
    if curve_row < n_braille_rows // 2:
        # Curve is in upper half -> place tooltip at bottom
        tooltip_row = chart_start + n_braille_rows - tooltip_h + 1
    else:
        # Curve is in lower half -> place tooltip at top
        tooltip_row = chart_start + 1

    tooltip_col = snap_col + 1  # just right of the now line

    # Flip to left side if near right edge
    if tooltip_col + max_w > cols:
        tooltip_col = max(1, snap_col - max_w)
    if tooltip_row + tooltip_h > rows:
        tooltip_row = max(1, rows - tooltip_h + 1)

    result = ""
    for i, line in enumerate(padded):
        result += f"\033[{tooltip_row + i};{tooltip_col}H{line}"
    return result


# ---------------------------------------------------------------------------
# Info line
# ---------------------------------------------------------------------------
def _info_line(window, now_height, now_dt, width, offset_minutes, rising, runtime):
    """Iconic pill-shaped tide info bar."""
    text = fg(200, 205, 215)
    dim = fg(70, 80, 100)
    sep = "  "

    pill_rgb = (22, 28, 42)
    now_rgb = (100, 170, 190)
    now_text = fg(12, 20, 30)

    arrow = "\u2197" if rising else "\u2198"
    icon_hi = "\U000F0799"   # 󰞙
    icon_lo = "\U000F0796"   # 󰞖

    h_display = runtime.convert_height(now_height)
    unit = runtime.height_unit

    # --- Current stat ---
    if offset_minutes:
        time_str = fmt_time_dt(now_dt, use_24h=runtime.use_24h)
        now_content = f"{now_text}{arrow} {time_str} {h_display:.1f}{unit}"
    else:
        now_content = f"{now_text}{arrow} {h_display:.1f}{unit}"

    # --- High/low/range parts ---
    rest_parts = []
    hilo = window["hilo"]
    if hilo:
        highs = [(dt, v) for dt, v, t in hilo if t == "H"]
        lows = [(dt, v) for dt, v, t in hilo if t == "L"]
        h_max = max((v for _, v, t in hilo if t == "H"), default=0)
        h_min = min((v for _, v, t in hilo if t == "L"), default=0)

        if highs:
            dt, v = highs[0]
            v_d = runtime.convert_height(v)
            t_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
            rest_parts.append(f"{text}{icon_hi}{v_d:.1f}{unit} {dim}{t_str}")
        if lows:
            dt, v = lows[0]
            v_d = runtime.convert_height(v)
            t_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
            rest_parts.append(f"{text}{icon_lo}{v_d:.1f}{unit} {dim}{t_str}")

        tide_range = runtime.convert_height(h_max - h_min)
        rest_parts.append(f"{text}\u0394{tide_range:.1f}{unit}")

    # --- "Space to return" hint ---
    if offset_minutes:
        hint = _ts("space_to_now", runtime)
        rest_parts.append(f"{dim}{hint}")

    # --- Assemble pill ---
    now_fg = fg(*now_rgb)
    now_bg = bg(*now_rgb)
    pill_fg_esc = fg(*pill_rgb)
    pill_bg_esc = bg(*pill_rgb)

    if rest_parts:
        rest_content = sep.join(rest_parts)
        line = (
            f"{now_fg}\u2590"
            f"{now_bg} {now_content} "
            f"{now_fg}{pill_bg_esc}\u258c"
            f" {rest_content} "
            f"{RESET}{pill_fg_esc}\u258c{RESET}"
        )
    else:
        line = (
            f"{now_fg}\u2590"
            f"{now_bg} {now_content} "
            f"{RESET}{now_fg}\u258c{RESET}"
        )

    pill_w = visible_len(line)
    pad = max(0, width - pill_w)
    return f"{' ' * (pad // 2)}{line}"


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
def render(station_id, station_name, station_meta=None, runtime=None,
           fullscreen=False, offset_minutes=0, mouse_pos=None,
           predictions=None, hilo=None, y_range=None):
    """Build the complete multi-line tide display.

    When predictions/hilo are provided (live mode), renders a sliding 24h
    window with hover and scroll support.  Otherwise fetches the current
    day's data for a static view.

    y_range: optional (min_ft, max_ft) to fix the y-axis scale (e.g. from
             30-day hilo data) so the curve doesn't rescale as you scroll.
    """
    if runtime is None:
        runtime = TidesRuntime.from_sources()

    now_local = _station_now(station_meta)
    station_tz = _station_tzinfo(station_meta)
    cols, rows = get_terminal_size()
    graph_w = max(30, cols - 2)

    # --- build the window ---
    if predictions is not None:
        # Live mode: sliding window from center_dt forward
        center_dt = now_local + timedelta(minutes=offset_minutes)
        window = _prepare_tide_window(
            predictions, hilo or [], center_dt, hours_shown=24,
        )
    else:
        # Static mode: show current calendar day
        date = now_local.date()
        day_preds = fetch_tides(station_id, date)
        if not day_preds:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)
        day_hilo = fetch_hilo(station_id, date) or []
        preds_dt = []
        for hour, height in day_preds:
            dt = _day_to_dt(hour, date, station_tz)
            if dt is not None:
                preds_dt.append((dt, height))
        hilo_dt = []
        for hour, height, typ in day_hilo:
            dt = _day_to_dt(hour, date, station_tz)
            if dt is not None:
                hilo_dt.append((dt, height, typ))
        day_start = datetime(date.year, date.month, date.day)
        if station_tz is not None:
            day_start = day_start.replace(tzinfo=station_tz)
        window = _prepare_tide_window(preds_dt, hilo_dt, day_start, hours_shown=24)

    w_start = window["start"]
    w_total = window["total_hours"]
    w_preds = window["predictions"]
    w_secs = w_total * 3600

    # --- dimensions (header + day_labels + braille + ticks) ---
    n_braille_rows = max(2, rows - (3 if fullscreen else 7))

    # --- interpolate predictions to graph columns ---
    col_heights = []
    for x in range(graph_w):
        frac = (x + 0.5) / graph_w
        dt = w_start + timedelta(hours=frac * w_total)
        col_heights.append(_interp_height(dt, w_preds))

    # --- now position ---
    now_offset = (now_local - w_start).total_seconds()
    if 0 <= now_offset <= w_secs:
        now_col = max(0, min(graph_w - 1, int(now_offset / w_secs * (graph_w - 1))))
    else:
        now_col = None

    # --- day divisions ---
    midnight_cols, midnight_day_names = _compute_time_markers(w_start, w_total, graph_w, runtime)

    # --- hover ---
    hover_graph_col = None
    chart_start = 2  # line index where braille starts (after header + day labels)
    chart_end = chart_start + n_braille_rows
    if mouse_pos:
        mcol, mrow = mouse_pos
        mrow_idx = mrow - 1  # 1-based -> 0-based
        if chart_start <= mrow_idx < chart_end:
            gc = mcol - 2  # 1-based terminal col -> 0-based graph col
            if 0 <= gc < graph_w:
                hover_graph_col = gc

    # --- build braille curve ---
    braille_rows = build_braille_curve(
        col_heights, graph_w, n_braille_rows, pad_frac=0.15, value_range=y_range,
    )

    # --- extrema labels + y-axis labels ---
    extrema = _hilo_to_extrema(window, graph_w, runtime)
    overlays = _compute_tide_overlays(
        extrema, col_heights, n_braille_rows, graph_w, runtime,
        value_range=y_range, braille_rows=braille_rows,
    )
    y_axis = _compute_y_axis_labels(n_braille_rows, graph_w, y_range, 0.15, runtime)
    for row, entries in y_axis.items():
        overlays.setdefault(row, []).extend(entries)

    # --- daylight dimming ---
    col_daylight = _compute_daylight_window(graph_w, w_start, w_total, station_meta)

    # --- assemble output ---
    lines = []

    # Header with pill-styled station name and scroll hint
    lines.append(_render_header_line(
        cols, station_name, runtime, offset_minutes=offset_minutes,
    ))

    # Day labels on their own row
    lines.append(_render_day_label_line(midnight_day_names, graph_w))

    # Braille chart
    lines.extend(_render_tide_braille_rows(
        braille_rows, col_daylight, midnight_cols,
        now_col=now_col, hover_col=hover_graph_col, overlays=overlays,
    ))

    # Tick labels
    lines.append(_render_tide_ticks(
        w_start, w_total, graph_w, runtime,
        now_col=now_col, hover_col=hover_graph_col,
    ))

    output = "\n".join(lines)

    # --- cursor-positioned overlays ---
    overlay_parts = []

    # "Now" label (suppressed when hovering)
    if now_col is not None and hover_graph_col is None:
        now_label = _build_now_label(
            window, now_col, now_local, chart_start, n_braille_rows,
            cols, rows, graph_w, runtime, value_range=y_range,
        )
        if now_label:
            overlay_parts.append(now_label)

    # Hover tooltip
    if mouse_pos and hover_graph_col is not None:
        tooltip = _build_tide_hover_tooltip(
            window, hover_graph_col, mouse_pos[1],
            chart_start, chart_end, cols, rows, graph_w, runtime,
        )
        if tooltip:
            overlay_parts.append(tooltip)

    if overlay_parts:
        output += "\x00" + "".join(overlay_parts)

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    runtime = TidesRuntime.from_sources()

    if has_flag("--help") or has_flag("-h"):
        print(__doc__.strip())
        return
    if has_flag("--version"):
        from linecast import __version__
        print(f"tides (linecast {__version__})")
        return

    # --search: find stations by name and exit
    search_q = arg_value("--search")
    if search_q:
        _search_stations(search_q)
        return

    # Station: --station flag > TIDE_STATION env var > geolocation
    station_arg = arg_value("--station")
    override = station_arg or os.environ.get("TIDE_STATION", "").strip()

    use_chs = False
    if override:
        if _is_chs_station_id(override):
            use_chs = True
            station_id = override
            station_name = f"Station {override[:8]}"
        else:
            station_id = override
            station_name = f"Station {override}"
            for s in (_fetch_all_stations() or []):
                if str(s.get("id", "")) == override:
                    name = s.get("name", "")
                    state = s.get("state", "")
                    station_name = f"{name}, {state}" if state else name
                    break
    else:
        lat, lng, country_code = get_location()
        if lat is None:
            print("Could not determine location for tide station lookup.", file=sys.stderr)
            sys.exit(1)

        if country_code == "CA":
            use_chs = True
            station_id, station_name = find_nearest_station_chs(lat, lng)
        else:
            station_id, station_name = find_nearest_station(lat, lng)

        if station_id is None:
            source = "CHS" if use_chs else "NOAA"
            print(
                f"No {source} tide station within 100nm. "
                "Set TIDE_STATION=<id> to specify one manually.",
                file=sys.stderr,
            )
            sys.exit(1)

    if use_chs:
        station_meta = fetch_station_metadata_chs(station_id)
    else:
        station_meta = _fetch_station_metadata(station_id)
    if station_meta:
        meta_name = station_meta.get("name", "")
        meta_state = station_meta.get("state", "")
        if meta_name:
            station_name = f"{meta_name}, {meta_state}" if meta_state else meta_name

    station_tz = _station_tzinfo(station_meta)
    now_local = _station_now(station_meta)
    today = now_local.date()

    # Fixed y-axis range from ±30 days of hilo data
    if use_chs:
        y_range = fetch_y_range_chs(station_id, today, station_tz)
    else:
        y_range = fetch_y_range(station_id, today)

    # Provider-specific range fetch functions
    _fetch_tides_range = fetch_tides_range_chs if use_chs else fetch_tides_range
    _fetch_hilo_range = fetch_hilo_range_chs if use_chs else fetch_hilo_range

    if runtime.live:
        # Pre-fetch ~7 days in each direction
        fetch_start = today - timedelta(days=7)
        fetch_end = today + timedelta(days=7)

        all_predictions = _fetch_tides_range(station_id, fetch_start, fetch_end, station_tz)
        all_hilo = _fetch_hilo_range(station_id, fetch_start, fetch_end, station_tz)
        fetched_range = [fetch_start, fetch_end]

        if not all_predictions:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)

        def _maybe_expand(offset_minutes):
            """Expand fetched range if user has scrolled near the edge."""
            nonlocal all_predictions, all_hilo
            center = now_local + timedelta(minutes=offset_minutes)
            center_date = center.date()

            need_expand = False
            new_start, new_end = fetched_range[0], fetched_range[1]

            if center_date - timedelta(days=2) < fetched_range[0]:
                new_start = center_date - timedelta(days=7)
                need_expand = True
            if center_date + timedelta(days=2) > fetched_range[1]:
                new_end = center_date + timedelta(days=7)
                need_expand = True

            if need_expand:
                all_predictions = _fetch_tides_range(station_id, new_start, new_end, station_tz)
                all_hilo = _fetch_hilo_range(station_id, new_start, new_end, station_tz)
                fetched_range[0] = new_start
                fetched_range[1] = new_end

        def _render(offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
            _maybe_expand(offset_minutes)
            return render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                fullscreen=True,
                offset_minutes=offset_minutes,
                mouse_pos=mouse_pos,
                predictions=all_predictions,
                hilo=all_hilo,
                y_range=y_range,
            ), {}

        live_loop(_render, interval=60, mouse=True, scroll_step=5)
    else:
        if use_chs:
            preds = fetch_tides_range_chs(
                station_id, today - timedelta(days=1),
                today + timedelta(days=1), station_tz)
            hilo_data = fetch_hilo_range_chs(
                station_id, today - timedelta(days=1),
                today + timedelta(days=1), station_tz)
            if not preds:
                print(f"Could not fetch tide data for station {station_id}.",
                      file=sys.stderr)
                sys.exit(1)
            print(render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                predictions=preds,
                hilo=hilo_data,
                y_range=y_range,
            ))
        else:
            print(render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                y_range=y_range,
            ))


if __name__ == "__main__":
    main()
