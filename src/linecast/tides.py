#!/usr/bin/env python3
"""Tides — terminal visualization of NOAA tide predictions.

Renders a multi-line graphical display of the day's tide curve with an
ocean-themed color palette. Shows water level as a smooth curve with
gradient fill, current tide position, and high/low extremes.

Uses half-block characters with 24-bit true color ANSI for smooth
rendering at 2x vertical sub-pixel resolution. Station is auto-detected
from IP geolocation or overridden with TIDE_STATION env var.

Usage: tides [--live] [--station ID] [--search QUERY]
"""

import math
import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta

from linecast._graphics import (
    fg, bg, RESET, BOLD, BG_PRIMARY,
    lerp, interp_stops, visible_len, fmt_time,
    get_terminal_size, Framebuffer, live_loop,
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
OCEAN_DEEP    = (8, 28, 54)
OCEAN_MID     = (15, 55, 90)
OCEAN_SURFACE = (22, 90, 130)
OCEAN_FOAM    = (140, 210, 225)
CURVE_COLOR   = (120, 200, 220)      # bright cyan curve line
DATUM_COLOR   = (35, 50, 75)         # MLLW reference line
NOW_LINE_COLOR = (65, 95, 140)        # vertical "now" line
MARKER_COLOR  = (180, 240, 255)      # current position glow

DIAMOND = "\u25c6"                    # ◆

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
# Rendering
# ---------------------------------------------------------------------------
def _ocean_gradient(t):
    """Color gradient for water fill. t=0 at surface (bright), t=1 at depth (dark)."""
    stops = [
        (0.0, OCEAN_FOAM),
        (0.15, OCEAN_SURFACE),
        (0.5, OCEAN_MID),
        (1.0, OCEAN_DEEP),
    ]
    return interp_stops(stops, t)


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
    graph_w = max(30, cols - 2)
    graph_h = max(6, rows - (1 if fullscreen else 6))
    total_spy = graph_h * 2

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

    curve_heights = []
    for x in range(graph_w):
        h = (x + 0.5) / graph_w * 24
        curve_heights.append(interp_height(h))

    # --- vertical scale (sized to monthly range for context) ---
    monthly = fetch_monthly_range(station_id, date)
    if monthly:
        scale_lo, scale_hi = monthly
        # Ensure today's data still fits
        scale_lo = min(scale_lo, min(curve_heights))
        scale_hi = max(scale_hi, max(curve_heights))
    else:
        scale_lo = min(curve_heights)
        scale_hi = max(curve_heights)

    scale_range_base = max(scale_hi - scale_lo, 0.5)
    padding = scale_range_base * 0.10
    scale_min = scale_lo - padding
    scale_max = scale_hi + padding
    scale_range = scale_max - scale_min

    # MLLW datum line position (height=0 in the scale)
    datum_spy = None
    if scale_min < 0 < scale_max:
        datum_frac = (scale_max - 0) / scale_range
        datum_spy = int(total_spy * datum_frac)
        datum_spy = max(0, min(total_spy - 1, datum_spy))

    def height_to_spy(height):
        """Tide height → sub-pixel row (float). 0=top (high water), total_spy-1=bottom."""
        frac = (scale_max - height) / scale_range
        return max(0.0, min(total_spy - 1.0, frac * (total_spy - 1)))

    curve_spy = [height_to_spy(h) for h in curve_heights]

    # Current position follows the scrubbed local datetime.
    now_hour = display_local.hour + display_local.minute / 60 + display_local.second / 3600
    now_x = max(0, min(graph_w - 1, int(now_hour / 24 * graph_w)))
    now_height = interp_height(now_hour)
    now_spy = height_to_spy(now_height)

    # --- build framebuffer ---
    fb = Framebuffer(graph_w, graph_h)

    # 1. MLLW datum line (if visible)
    if datum_spy is not None:
        fb.fill_hline(datum_spy, DATUM_COLOR)

    # 2. Water fill below the tide curve
    fb.draw_fill(curve_spy, total_spy, _ocean_gradient, aspect=1.8)

    # 3. Vertical "now" line
    now_spy_i = int(round(now_spy))
    for spy in range(total_spy):
        alpha = 0.45 if spy != now_spy_i else 0.0
        fb.set_pixel(now_x, spy, NOW_LINE_COLOR, alpha)

    # 4. Tide curve
    fb.draw_curve(curve_spy, CURVE_COLOR, sigma=0.8)

    # 5. Current position — radial glow on the curve
    glow_r = max(4, int(min(graph_w, total_spy) * 0.035))
    fb.draw_radial(now_x, now_spy, MARKER_COLOR, glow_r, peak_alpha=0.5)

    # Bright core
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            sx = now_x + dx
            sy = int(round(now_spy)) + dy
            if 0 <= sx < graph_w and 0 <= sy < total_spy:
                d = math.sqrt(dx * dx + (dy * 1.5) ** 2)
                fb.set_pixel(sx, sy, (255, 255, 255), max(0, 0.8 - d * 0.3))

    # --- render with diamond overlay ---
    diamond_cell_row = int(round(now_spy)) // 2
    overlays = {(now_x, diamond_cell_row): (DIAMOND, (255, 255, 255))}
    lines = fb.render(overlays)

    # --- info line ---
    tz_label = display_local.strftime("%Z") or (station_meta or {}).get("timezone_abbr", "")
    lines.append(
        _info_line(
            hilo,
            now_height,
            station_name,
            cols,
            now_hour,
            offset_minutes,
            tz_label,
            display_date=display_local.date(),
            reference_date=now_local.date(),
        )
    )

    return "\n".join(lines)


def _info_line(
    hilo,
    now_height,
    station_name,
    width,
    now_hour=None,
    offset_minutes=0,
    tz_label="",
    display_date=None,
    reference_date=None,
):
    """High/Low times · Range · Current height · Station name (truncated to fit)."""
    text = fg(200, 205, 215)
    dim = fg(70, 80, 100)
    muted = fg(100, 110, 130)
    sep = f"{muted}  \u00b7  "

    # Build parts as (visible_text, ansi_text) pairs
    parts = []
    if hilo:
        highs = [(h, v) for h, v, t in hilo if t == "H"]
        lows = [(h, v) for h, v, t in hilo if t == "L"]
        h_max = max((v for _, v, t in hilo if t == "H"), default=0)
        h_min = min((v for _, v, t in hilo if t == "L"), default=0)

        if highs:
            h, v = highs[0]
            parts.append(f"{text}High {v:.1f}ft {dim}{fmt_time(h)}")
        if lows:
            h, v = lows[0]
            parts.append(f"{text}Low {v:.1f}ft {dim}{fmt_time(h)}")

        tide_range = h_max - h_min
        parts.append(f"{text}Range {tide_range:.1f}ft")

    if offset_minutes:
        now_part = f"{text}{fmt_time(now_hour)} {now_height:.1f}ft"
        if display_date and reference_date and display_date != reference_date:
            now_part += f" {dim}{display_date.strftime('%a %b %-d')}"
    else:
        now_part = f"{text}Now {now_height:.1f}ft"
    if tz_label:
        now_part += f" {dim}{tz_label}"
    parts.append(now_part)

    # Station name — truncate to fit remaining space
    name = station_name.title() if station_name else "Unknown"
    core = sep.join(parts)
    core_w = visible_len(core) + 2  # leading/trailing spaces
    sep_w = visible_len(sep)
    avail = width - core_w - sep_w
    if avail >= len(name):
        parts.append(f"{muted}{name}")
    elif avail >= 4:
        parts.append(f"{muted}{name[:avail - 1]}\u2026")

    line = f" {sep.join(parts)} "
    return f"{RESET}{line}{RESET}"


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
