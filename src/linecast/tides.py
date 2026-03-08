#!/usr/bin/env python3
"""Tides — terminal visualization of NOAA tide predictions.

Renders a multi-line graphical display of the day's tide curve with an
ocean-themed color palette. Shows water level as a braille line graph
with height-colored curve, high/low labels, and current position indicator.

Uses Unicode braille characters with ANSI color for smooth line rendering
(true color when available). Station is auto-detected from IP geolocation
or overridden with TIDE_STATION env var.

Usage: tides [--live] [--station ID] [--search QUERY]
"""

import math
import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta

from linecast._graphics import (
    bg, fg, RESET,
    visible_len, fmt_time,
    get_terminal_size, live_loop,
)
from linecast._cache import CACHE_ROOT, location_cache_key, read_cache, read_stale, write_cache
from linecast._http import fetch_json, fetch_json_cached
from linecast._location import get_location
from linecast._runtime import RuntimeConfig, arg_value, has_flag
from linecast import USER_AGENT

CACHE_DIR = CACHE_ROOT / "tides"
NEAREST_STATION_CACHE_MAX_AGE = 3600

# ---------------------------------------------------------------------------
# Ocean palette
# ---------------------------------------------------------------------------
CURVE_COLOR   = (120, 200, 220)      # teal curve line
NOW_LINE_COLOR = (65, 95, 140)        # "now" indicator
NIGHT_DIM     = 0.6                   # brightness floor for nighttime

# Nerd Font icons
WAVE_ICON = "\U000F0F85"             # 󰾅

# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
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


def fetch_monthly_range(station_id, date):
    """Fetch min/max tide heights over a 30-day window for y-axis scaling.

    Returns (min_height, max_height) or None. Cached 24h.
    """
    date_str = date.strftime("%Y%m%d")
    end = date + timedelta(days=30)
    end_str = end.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"range_{station_id}_{date_str}.json"
    url = _prediction_url(station_id, date_str, end_str, "hilo")
    data = _fetch_payload(cache_file, 86400, url, fallback=None)
    if not data:
        return None
    if isinstance(data, dict) and "min" in data and "max" in data:
        return data["min"], data["max"]

    predictions = data.get("predictions", [])
    if not predictions:
        return None

    heights = [float(p.get("v", 0)) for p in predictions]
    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return result["min"], result["max"]


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
    """Search NOAA stations by name substring. Prints matches and exits."""
    stations = _fetch_all_stations()
    if not stations:
        print("Could not fetch station list.", file=sys.stderr)
        sys.exit(1)

    q = query.lower()
    matches = [s for s in stations if q in s.get("name", "").lower()]

    if not matches:
        print(f"No stations matching \"{query}\".")
        sys.exit(0)

    # Sort alphabetically by name
    matches.sort(key=lambda s: s.get("name", ""))
    for s in matches[:20]:
        sid = s.get("id", "")
        name = s.get("name", "")
        state = s.get("state", "")
        label = f"{name}, {state}" if state else name
        print(f"  {sid}  {label}")

    if len(matches) > 20:
        print(f"  ... and {len(matches) - 20} more")


# ---------------------------------------------------------------------------
# Braille rendering
# ---------------------------------------------------------------------------
def _compute_daylight(graph_w, date, station_meta):
    """Compute per-column daylight factor (0.0=night, 1.0=day) using solar math.

    Uses the station's lat/lng and timezone to approximate sunrise/sunset,
    then applies a smooth 40-minute transition at dawn and dusk.
    Falls back to uniform full brightness when coordinates are unavailable.
    """
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

    doy = date.timetuple().tm_yday

    # Solar declination (degrees)
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    lat_rad = math.radians(lat)
    decl_rad = math.radians(decl)

    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    if cos_ha <= -1:
        return [1.0] * graph_w   # midnight sun
    if cos_ha >= 1:
        return [0.0] * graph_w   # polar night

    ha = math.degrees(math.acos(cos_ha))

    # Solar noon in local clock time
    solar_noon = 12.0
    if lng is not None:
        tz_meridian = tz_offset_h * 15
        solar_noon += (tz_meridian - lng) / 15

    sunrise = solar_noon - ha / 15
    sunset = solar_noon + ha / 15
    transition = 40 / 60  # 40 minutes

    col_daylight = []
    for x in range(graph_w):
        hour = (x + 0.5) / graph_w * 24
        if hour < sunrise - transition or hour > sunset + transition:
            col_daylight.append(0.0)
        elif sunrise + transition <= hour <= sunset - transition:
            col_daylight.append(1.0)
        elif hour < sunrise + transition:
            col_daylight.append((hour - sunrise + transition) / (2 * transition))
        else:
            col_daylight.append((sunset + transition - hour) / (2 * transition))
    return col_daylight


def _build_tide_braille(col_heights, graph_w, n_rows):
    """Build an n_rows-high braille line graph from tide heights.

    Returns list of n_rows rows, each a list of (char, avg_height) tuples.
    Together the rows form a (n_rows*4)-dot-high graph spanning graph_w chars.
    """
    n = 2 * graph_w  # samples: 2 per braille char (left col, right col)
    total_dots = n_rows * 4

    # Interpolate to 2 samples per braille char
    samples = []
    for i in range(n):
        t = i / max(1, n - 1) * max(0, len(col_heights) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(col_heights) - 1)
        frac = t - lo_i
        samples.append(col_heights[lo_i] + (col_heights[hi_i] - col_heights[lo_i]) * frac)

    s_min, s_max = min(samples), max(samples)
    # Vertical padding so curve doesn't reach edges (room for labels)
    pad = max(0.3, (s_max - s_min) * 0.15)
    s_min -= pad
    s_max += pad
    if s_max == s_min:
        ys = [total_dots / 2] * n
    else:
        s_range = s_max - s_min
        ys = [(total_dots - 1) * (1 - (s - s_min) / s_range) for s in samples]

    ys_i = [max(0, min(total_dots - 1, int(round(y)))) for y in ys]

    # Braille dot bit positions: BITS[col][row] for 2x4 grid within each char
    bits = [[0x01, 0x02, 0x04, 0x40], [0x08, 0x10, 0x20, 0x80]]
    rows_bits = [[0] * graph_w for _ in range(n_rows)]

    def _set_dot(ci, y, col):
        if ci < 0 or ci >= graph_w or y < 0 or y >= total_dots:
            return
        rows_bits[y // 4][ci] |= bits[col][y % 4]

    for i in range(graph_w):
        left_y = ys_i[2 * i]
        right_y = ys_i[2 * i + 1]

        _set_dot(i, left_y, 0)
        _set_dot(i, right_y, 1)

        # Connect left->right within char
        if left_y != right_y:
            y_lo, y_hi = min(left_y, right_y), max(left_y, right_y)
            for y in range(y_lo, y_hi + 1):
                x_frac = (y - left_y) / (right_y - left_y)
                _set_dot(i, y, 0 if abs(x_frac) < 0.5 else 1)

        # Cross-char continuity: bridge from previous char's right col
        if i > 0:
            prev_y = ys_i[2 * i - 1]
            if prev_y != left_y:
                y_lo, y_hi = min(prev_y, left_y), max(prev_y, left_y)
                for y in range(y_lo, y_hi + 1):
                    _set_dot(i, y, 0)

    result = []
    for r in range(n_rows):
        row = []
        for ci in range(graph_w):
            avg_h = (samples[2 * ci] + samples[2 * ci + 1]) / 2
            row.append((chr(0x2800 + rows_bits[r][ci]), avg_h))
        result.append(row)
    return result


def _hilo_to_extrema(hilo, graph_w):
    """Convert hi/lo tide data to extrema positions for labeling."""
    if not hilo:
        return []
    return [
        (max(0, min(graph_w - 1, int(hour / 24 * graph_w))), height, typ == "H")
        for hour, height, typ in hilo
    ]


def _compute_tide_overlays(extrema, col_heights, n_rows, graph_w):
    """Map tide extrema to overlay labels on specific braille rows."""
    if not extrema or n_rows < 1:
        return {}

    h_min, h_max = min(col_heights), max(col_heights)
    # Match padding from _build_tide_braille
    pad = max(0.3, (h_max - h_min) * 0.15)
    h_min -= pad
    h_max += pad
    total_dots = n_rows * 4
    overlays = {}
    occupied_by_row = {}

    for x, height, is_peak in extrema:
        if h_max == h_min:
            curve_row = n_rows // 2
        else:
            y = (total_dots - 1) * (1 - (height - h_min) / (h_max - h_min))
            curve_row = max(0, min(n_rows - 1, int(round(y)) // 4))

        label_row = max(0, curve_row - 1) if is_peak else min(n_rows - 1, curve_row + 1)

        label = f"{height:.1f}\u2032"
        start = max(0, min(graph_w - len(label), x - len(label) // 2))

        if label_row not in occupied_by_row:
            occupied_by_row[label_row] = set()
        label_cols = set(range(start, start + len(label)))
        if label_cols & occupied_by_row[label_row]:
            continue
        occupied_by_row[label_row] |= label_cols

        overlays.setdefault(label_row, []).append((start, label, CURVE_COLOR))

    return overlays


def _render_tide_braille_rows(braille_rows, now_col, col_daylight, overlays=None):
    """Render braille tide rows with daylight dimming and now indicator."""
    if overlays is None:
        overlays = {}

    now_fg = fg(*NOW_LINE_COLOR)
    cr, cg, cb = CURVE_COLOR
    lines = []
    for row_idx, row in enumerate(braille_rows):
        overlay_chars = {}
        for start_col, label, color in overlays.get(row_idx, []):
            for j, c in enumerate(label):
                col = start_col + j
                if 0 <= col < len(row):
                    overlay_chars[col] = (c, color)

        line = " "
        for ci, (ch, _height) in enumerate(row):
            if ci in overlay_chars:
                oc, oc_color = overlay_chars[ci]
                line += f"{fg(*oc_color)}{oc}"
            elif ch == '\u2800' and ci == now_col:
                line += f"{now_fg}\u2502"
            elif ch == '\u2800':
                line += " "
            else:
                dl = col_daylight[ci] if ci < len(col_daylight) else 1.0
                brightness = NIGHT_DIM + (1.0 - NIGHT_DIM) * dl
                line += f"{fg(int(cr * brightness), int(cg * brightness), int(cb * brightness))}{ch}"
        lines.append(f"{line}{RESET}")
    return lines


def _fmt_hour_12(h):
    """Format hour (0-24) as compact 12-hour label."""
    h = h % 24
    if h == 0:
        return "12a"
    if h == 12:
        return "12p"
    if h < 12:
        return f"{h}a"
    return f"{h - 12}p"


def _render_tide_ticks(graph_w, now_hour=None):
    """Render time axis labels for 24-hour tide chart."""
    if graph_w < 40:
        interval = 6
    elif graph_w < 80:
        interval = 4
    elif graph_w < 140:
        interval = 3
    else:
        interval = 2

    canvas = [" "] * graph_w
    last_end = 0
    for h in range(0, 25, interval):
        x = int(h / 24 * (graph_w - 1)) if h < 24 else graph_w - 1
        label = _fmt_hour_12(h)
        tick = "\u2575"
        tick_label = f"{tick}{label}"
        if x < last_end or x + len(tick_label) > graph_w:
            continue
        for j, c in enumerate(tick_label):
            if x + j < graph_w:
                canvas[x + j] = c
        last_end = x + len(tick_label) + 1

    if now_hour is not None:
        now_x = max(0, min(graph_w - 1, int(now_hour / 24 * graph_w)))
        if canvas[now_x] == " ":
            canvas[now_x] = "\u2502"

    dim = fg(70, 80, 100)
    return f" {dim}{''.join(canvas)}{RESET}"


def render(station_id, station_name, station_meta=None, fullscreen=False, offset_minutes=0):
    """Build the complete multi-line tide display."""
    now_local = _station_now(station_meta)
    display_local = now_local + timedelta(minutes=offset_minutes) if offset_minutes else now_local
    date = display_local.date()

    predictions = fetch_tides(station_id, date)
    if not predictions:
        print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
        sys.exit(1)

    hilo = fetch_hilo(station_id, date)

    cols, rows = get_terminal_size()

    # --- dimensions ---
    # Reserve: station_name(1) + braille + tick(1) + info(1)
    graph_w = max(30, cols - 2)
    n_braille_rows = max(2, rows - (3 if fullscreen else 7))

    # --- interpolate predictions to graph columns ---
    hours = [p[0] for p in predictions]
    heights = [p[1] for p in predictions]

    def interp_height(hour):
        """Linearly interpolate tide height at a given hour."""
        if hour <= hours[0]:
            return heights[0]
        if hour >= hours[-1]:
            return heights[-1]
        for i in range(len(hours) - 1):
            if hours[i] <= hour <= hours[i + 1]:
                t = (hour - hours[i]) / (hours[i + 1] - hours[i])
                return heights[i] + (heights[i + 1] - heights[i]) * t
        return heights[-1]

    col_heights = []
    for x in range(graph_w):
        h = (x + 0.5) / graph_w * 24
        col_heights.append(interp_height(h))

    # Current position
    now_hour = display_local.hour + display_local.minute / 60 + display_local.second / 3600
    now_col = max(0, min(graph_w - 1, int(now_hour / 24 * graph_w)))
    now_height = interp_height(now_hour)

    # --- build braille curve ---
    braille_rows = _build_tide_braille(col_heights, graph_w, n_braille_rows)

    # --- extrema labels from hi/lo data ---
    extrema = _hilo_to_extrema(hilo, graph_w)
    overlays = _compute_tide_overlays(extrema, col_heights, n_braille_rows, graph_w)

    # --- daylight dimming ---
    col_daylight = _compute_daylight(graph_w, date, station_meta)

    # --- assemble output ---
    lines = []

    # Station name pinned to top-right
    name = station_name.title() if station_name else ""
    muted = fg(100, 110, 130)
    if name:
        lines.append(f"{muted}{' ' * max(0, cols - len(name) - 1)}{name}{RESET}")
    else:
        lines.append("")

    lines.extend(_render_tide_braille_rows(braille_rows, now_col, col_daylight, overlays))
    lines.append(_render_tide_ticks(graph_w, now_hour))

    # --- info line ---
    # Determine tide direction from local slope
    eps = 0.1  # ~6 minutes
    rising = interp_height(min(24, now_hour + eps)) > interp_height(max(0, now_hour - eps))

    lines.append(
        _info_line(
            hilo,
            now_height,
            cols,
            now_hour,
            offset_minutes,
            rising=rising,
            display_date=display_local.date(),
            reference_date=now_local.date(),
        )
    )

    return "\n".join(lines)


def _info_line(
    hilo,
    now_height,
    width,
    now_hour=None,
    offset_minutes=0,
    rising=True,
    display_date=None,
    reference_date=None,
):
    """Iconic pill-shaped tide info bar with knocked-out current stat."""
    text = fg(200, 205, 215)
    dim = fg(70, 80, 100)
    sep = "  "

    # Pill colors
    pill_rgb = (22, 28, 42)
    now_rgb = (100, 170, 190)  # teal for current stat knockout
    now_text = fg(12, 20, 30)

    # Nerd Font icons
    arrow = "\u2197" if rising else "\u2198"  # ↗ / ↘ (diagonal arrows for rising/falling)
    icon_hi = "\U000F0799"   # 󰞙
    icon_lo = "\U000F0796"   # 󰞖

    # --- Current stat (knocked out: dark text on teal) ---
    if offset_minutes:
        now_content = f"{now_text}{arrow} {fmt_time(now_hour)} {now_height:.1f}\u2032"
        if display_date and reference_date and display_date != reference_date:
            now_content += f" {fg(40, 60, 70)}{display_date.strftime('%a %b %-d')}"
    else:
        now_content = f"{now_text}{arrow} {now_height:.1f}\u2032"

    # --- High/low/range parts (light text on dark pill) ---
    rest_parts = []
    if hilo:
        highs = [(h, v) for h, v, t in hilo if t == "H"]
        lows = [(h, v) for h, v, t in hilo if t == "L"]
        h_max = max((v for _, v, t in hilo if t == "H"), default=0)
        h_min = min((v for _, v, t in hilo if t == "L"), default=0)

        if highs:
            h, v = highs[0]
            rest_parts.append(f"{text}{icon_hi}{v:.1f}\u2032 {dim}{fmt_time(h)}")
        if lows:
            h, v = lows[0]
            rest_parts.append(f"{text}{icon_lo}{v:.1f}\u2032 {dim}{fmt_time(h)}")

        tide_range = h_max - h_min
        rest_parts.append(f"{text}\u0394{tide_range:.1f}\u2032")

    # --- Assemble pill ---
    now_fg = fg(*now_rgb)
    now_bg = bg(*now_rgb)
    pill_fg_esc = fg(*pill_rgb)
    pill_bg_esc = bg(*pill_rgb)

    if rest_parts:
        rest_content = sep.join(rest_parts)
        line = (
            f"{now_fg}\u2590"                          # left edge: → teal
            f"{now_bg} {now_content} "                 # current stat on teal
            f"{now_fg}{pill_bg_esc}\u258c"             # transition: teal → pill_bg
            f" {rest_content} "                        # rest on pill_bg
            f"{RESET}{pill_fg_esc}\u258c{RESET}"       # right edge: pill_bg →
        )
    else:
        line = (
            f"{now_fg}\u2590"                          # left edge
            f"{now_bg} {now_content} "                 # current stat on teal
            f"{RESET}{now_fg}\u258c{RESET}"            # right edge
        )

    # Center the pill
    pill_w = visible_len(line)
    pad = max(0, width - pill_w)
    return f"{' ' * (pad // 2)}{line}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    runtime = RuntimeConfig.from_sources()

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

    if override:
        station_id = override
        # Try to resolve a proper name from the station list
        station_name = f"Station {override}"
        for s in (_fetch_all_stations() or []):
            if str(s.get("id", "")) == override:
                name = s.get("name", "")
                state = s.get("state", "")
                station_name = f"{name}, {state}" if state else name
                break
    else:
        lat, lng, _country = get_location()
        if lat is None:
            print("Could not determine location for tide station lookup.", file=sys.stderr)
            sys.exit(1)

        station_id, station_name = find_nearest_station(lat, lng)
        if station_id is None:
            print(
                "No NOAA tide station within 100nm. "
                "Set TIDE_STATION=<id> to specify one manually.",
                file=sys.stderr,
            )
            sys.exit(1)

    station_meta = _fetch_station_metadata(station_id)
    if station_meta:
        meta_name = station_meta.get("name", "")
        meta_state = station_meta.get("state", "")
        if meta_name:
            station_name = f"{meta_name}, {meta_state}" if meta_state else meta_name

    live = runtime.live
    _render = lambda offset_minutes=0: render(
        station_id,
        station_name,
        station_meta=station_meta,
        fullscreen=live,
        offset_minutes=offset_minutes,
    )

    if live:
        live_loop(_render)
    else:
        print(_render())


if __name__ == "__main__":
    main()
