#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, comparative weather line, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts are sourced from NWS (US) and Environment Canada (CA).

Usage: weather [--live] [--location LAT,LNG] [--search CITY] [--emoji] [--celsius/--metric] [--shading]
"""

import os
import sys
from datetime import datetime, timezone, timedelta

from linecast._graphics import (
    fg, bg, RESET, BOLD, interp_stops, visible_len, get_terminal_size,
    live_loop,
)
from linecast._cache import (
    CACHE_ROOT, read_cache, write_cache, location_cache_key,
)
from linecast._http import fetch_json, fetch_json_cached
from linecast._location import get_location
from linecast._runtime import WeatherRuntime, arg_value, has_flag
from linecast import USER_AGENT

CACHE_DIR = CACHE_ROOT / "weather"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
TEMP_COLORS = [
    ( 0, (100,  60, 180)),   # frigid — deep purple
    (32, ( 70, 130, 210)),   # freezing — blue
    (45, ( 50, 170, 180)),   # cold — teal
    (55, ( 60, 180, 120)),   # cool — green
    (65, (140, 200,  70)),   # mild — yellow-green
    (72, (220, 190,  50)),   # warm — gold
    (82, (240, 150,  40)),   # hot — orange
    (95, (220,  60,  50)),   # very hot — red
]

TEXT    = fg(200, 205, 215)
DIM     = fg(70, 80, 100)
MUTED   = fg(100, 110, 130)
PRECIP      = fg(80, 140, 220)    # blue (rain) — kept for daily text
PRECIP_RAIN = fg(80, 140, 220)
PRECIP_SNOW = fg(200, 210, 225)   # light gray-white
PRECIP_MIX  = fg(160, 140, 200)   # light purple
PRECIP_STORM = fg(220, 190, 50)   # amber
ALERT_RED    = fg(220, 60, 50)
ALERT_AMBER  = fg(220, 170, 50)
ALERT_YELLOW = fg(200, 200, 80)
WIND_COLOR   = fg(140, 150, 170)

# Wind direction arrows: indexed by compass sector (N=0, NE=1, E=2, ... NW=7)
# Arrow points in the direction the wind is blowing FROM (meteorological convention)
WIND_ARROWS = "↓↙←↖↑↗→↘"  # N wind blows south, NE blows southwest, etc.

SEP = f"{MUTED} \u00b7 "

# Nerd Font WMO icons
_WMO_ICONS_NERD = {
    0: "\U000F0599", 1: "\U000F0599", 2: "\U000F0595", 3: "\U000F0590",
    45: "\U000F0591", 48: "\U000F0591",
    51: "\U000F0597", 53: "\U000F0597", 55: "\U000F0597",
    56: "\U000F0597", 57: "\U000F0597",
    61: "\U000F0596", 63: "\U000F0596", 65: "\U000F0596",
    66: "\U000F0596", 67: "\U000F0596",
    71: "\U000F0F36", 73: "\U000F0F36", 75: "\U000F0F36", 77: "\U000F0F36",
    80: "\U000F0596", 81: "\U000F0596", 82: "\U000F0596",
    85: "\U000F0F36", 86: "\U000F0F36",
    95: "\U000F0593", 96: "\U000F0593", 99: "\U000F0593",
}

# Emoji fallback WMO icons (no Nerd Font required)
_WMO_ICONS_EMOJI = {
    0: "\u2600\ufe0f",  1: "\U0001f324\ufe0f",  2: "\u26c5", 3: "\u2601\ufe0f",
    45: "\U0001f32b\ufe0f", 48: "\U0001f32b\ufe0f",
    51: "\U0001f326\ufe0f", 53: "\U0001f326\ufe0f", 55: "\U0001f326\ufe0f",
    56: "\U0001f327\ufe0f", 57: "\U0001f327\ufe0f",
    61: "\U0001f327\ufe0f", 63: "\U0001f327\ufe0f", 65: "\U0001f327\ufe0f",
    66: "\U0001f327\ufe0f", 67: "\U0001f327\ufe0f",
    71: "\U0001f328\ufe0f", 73: "\U0001f328\ufe0f", 75: "\U0001f328\ufe0f", 77: "\U0001f328\ufe0f",
    80: "\U0001f326\ufe0f", 81: "\U0001f326\ufe0f", 82: "\U0001f326\ufe0f",
    85: "\U0001f328\ufe0f", 86: "\U0001f328\ufe0f",
    95: "\u26c8\ufe0f",  96: "\u26c8\ufe0f",  99: "\u26c8\ufe0f",
}

def _wmo_icons(runtime):
    return _WMO_ICONS_EMOJI if runtime.emoji else _WMO_ICONS_NERD
WMO_NAMES = {
    0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

SPARKLINE = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"  # ▁▂▃▄▅▆▇█

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
def _location_from_timezone(tz_str):
    """Extract display name from timezone like 'America/New_York' → 'New York'."""
    if not tz_str or "/" not in tz_str:
        return ""
    return tz_str.rsplit("/", 1)[-1].replace("_", " ")


def _local_now_for_data(data):
    """Current local time in the forecast's timezone (as naive local datetime)."""
    tz_name = data.get("timezone", "")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception:
            pass
    try:
        offset_sec = int(data.get("utc_offset_seconds", 0))
        return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _reverse_geocode(lat, lng):
    """Reverse geocode coordinates to a display name via Nominatim. Cached.

    Returns (display_name, country_code) tuple.
    """
    cache_file = CACHE_DIR / "location.json"
    cached = read_cache(cache_file, 86400)  # 24h cache
    if cached and cached.get("lat") == round(lat, 4) and cached.get("lng") == round(lng, 4):
        return cached.get("name", ""), cached.get("country_code", "")

    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&zoom=10"
        )
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        addr = data.get("address", {})
        name = addr.get("city") or addr.get("town") or addr.get("village") or ""
        state = addr.get("state", "")
        country_code = addr.get("country_code", "").upper()
        if name and state:
            display = f"{name}, {state}"
        elif name:
            display = name
        else:
            display = ""
        write_cache(cache_file, {
            "lat": round(lat, 4), "lng": round(lng, 4),
            "name": display, "country_code": country_code,
        })
        return display, country_code
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_forecast(lat, lng, runtime=None):
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    unit_suffix = "_metric" if runtime.metric else ""
    cache_file = CACHE_DIR / f"forecast_{location_cache_key(lat, lng)}{unit_suffix}.json"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
        "wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,weather_code,wind_speed_10m_max,wind_gusts_10m_max,"
        "sunrise,sunset"
        f"&temperature_unit={'celsius' if runtime.metric else 'fahrenheit'}"
        f"&wind_speed_unit={'kmh' if runtime.metric else 'mph'}"
        f"&precipitation_unit={'mm' if runtime.metric else 'inch'}"
        "&timezone=auto&forecast_days=7&past_days=1"
        "&current=temperature_2m,apparent_temperature,weather_code,"
        "wind_speed_10m,wind_gusts_10m"
    )
    return fetch_json_cached(
        cache_file,
        3600,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )


# ---------------------------------------------------------------------------
# Alerts — multi-provider router
# ---------------------------------------------------------------------------
def fetch_alerts(lat, lng, country_code=""):
    """Fetch active weather alerts from the appropriate provider.

    Routes to NWS (US), Environment Canada (CA), or returns [] for unsupported regions.
    """
    if country_code == "US":
        return _fetch_alerts_nws(lat, lng)
    elif country_code == "CA":
        return _fetch_alerts_eccc(lat, lng)
    else:
        return []


def _fetch_alerts_nws(lat, lng):
    """Fetch active NWS alerts (US). Cached 15min."""
    cache_file = CACHE_DIR / f"alerts_{location_cache_key(lat, lng)}.json"
    url = f"https://api.weather.gov/alerts/active?point={lat},{lng}"
    data = fetch_json_cached(
        cache_file,
        900,
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
        timeout=10,
        fallback=[],
    )
    if isinstance(data, list):
        return data

    features = data.get("features", [])
    alerts = []
    for f in features:
        p = f.get("properties", {})
        alerts.append({
            "event": p.get("event", ""),
            "headline": p.get("headline", ""),
            "description": p.get("description", ""),
            "effective": p.get("effective", ""),
            "expires": p.get("expires", ""),
            "severity": p.get("severity", ""),
        })
    write_cache(cache_file, alerts)
    return alerts


def _fetch_alerts_eccc(lat, lng):
    """Fetch active Environment Canada alerts (CA). Cached 15min.

    Uses the OGC API at api.weather.gc.ca with bbox query.
    """
    cache_file = CACHE_DIR / f"alerts_ca_{location_cache_key(lat, lng)}.json"
    # bbox: lng-0.5, lat-0.5, lng+0.5, lat+0.5 (~50km radius)
    bbox = f"{lng - 0.5},{lat - 0.5},{lng + 0.5},{lat + 0.5}"
    url = (
        f"https://api.weather.gc.ca/collections/weather-alerts/items"
        f"?f=json&bbox={bbox}&lang=en&limit=20"
    )
    data = fetch_json_cached(
        cache_file,
        900,
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=10,
        fallback=[],
    )
    if isinstance(data, list):
        return data

    features = data.get("features", [])
    alerts = []
    seen_events = set()  # deduplicate by event name
    for f in features:
        p = f.get("properties", {})
        # ECCC field names: alert_name_en, alert_text_en, etc.
        event = p.get("alert_name_en", "").title() or p.get("alert_short_name_en", "")
        severity = _eccc_severity(p)
        desc = p.get("alert_text_en") or p.get("alert_text_fr") or ""
        effective = p.get("validity_datetime") or p.get("publication_datetime") or ""
        expires = p.get("expiration_datetime") or ""

        if not event:
            continue

        # Deduplicate — ECCC returns one feature per affected zone
        dedup_key = (event, severity)
        if dedup_key in seen_events:
            continue
        seen_events.add(dedup_key)

        alerts.append({
            "event": event,
            "headline": event,
            "description": desc,
            "effective": effective,
            "expires": expires,
            "severity": severity,
        })
    write_cache(cache_file, alerts)
    return alerts


def _eccc_severity(props):
    """Map Environment Canada alert properties to standard severity string."""
    # ECCC uses alert_type: "warning" > "watch" > "advisory" > "statement"
    alert_type = (props.get("alert_type") or "").lower()
    if alert_type == "warning":
        return "Severe"
    if alert_type == "watch":
        return "Moderate"
    if alert_type in ("advisory", "statement", "ending"):
        return "Minor"
    return "Minor"


# ---------------------------------------------------------------------------
# Search (geocoding via Open-Meteo)
# ---------------------------------------------------------------------------
def _search_locations(query):
    """Search cities using Open-Meteo geocoding API and print results."""
    import urllib.parse
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=10&language=en"
    )
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    except Exception as e:
        print(f"Search failed: {e}", file=sys.stderr)
        sys.exit(1)

    results = data.get("results", [])
    if not results:
        print(f'No locations matching "{query}".')
        return

    for r in results:
        name = r.get("name", "")
        admin1 = r.get("admin1", "")
        country = r.get("country", "")
        lat = r.get("latitude", 0)
        lng = r.get("longitude", 0)
        label = name
        if admin1:
            label += f", {admin1}"
        if country:
            label += f", {country}"
        print(f"  {lat:.4f},{lng:.4f}  {label}")

    print(f"\nUsage: weather --location LAT,LNG")
    print(f"   or: export WEATHER_LOCATION=LAT,LNG")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _temp_color(temp, runtime):
    temp_f = temp * 9 / 5 + 32 if runtime.metric else temp
    return interp_stops(TEMP_COLORS, temp_f)


def _colored_temp(temp, runtime, suffix=""):
    r, g, b = _temp_color(temp, runtime)
    return f"{fg(r, g, b)}{temp:.0f}{suffix}"


def _precip_type(wmo_code):
    """Infer precipitation type from WMO weather code."""
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if wmo_code in (56, 57, 66, 67):
        return "Mix"
    return "Rain"


def _precip_color(wmo_code):
    """ANSI color for precipitation type based on WMO code."""
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return PRECIP_SNOW
    if wmo_code in (56, 57, 66, 67):
        return PRECIP_MIX
    if wmo_code in (95, 96, 99):
        return PRECIP_STORM
    return PRECIP_RAIN


def _fmt_hour(h):
    """Format hour as compact label: 6a, 12p, etc."""
    h = h % 24
    if h == 0:
        return "12a"
    if h == 12:
        return "12p"
    if h < 12:
        return f"{h}a"
    return f"{h - 12}p"


def _parse_alert_time(iso_str):
    """Parse ISO time string to a short display string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%a %-I%p").replace("AM", "am").replace("PM", "pm")
    except Exception:
        return ""


def _severity_color(severity):
    if severity in ("Extreme", "Severe"):
        return ALERT_RED
    if severity == "Moderate":
        return ALERT_AMBER
    return ALERT_YELLOW


def _severity_rgb(severity):
    if severity in ("Extreme", "Severe"):
        return (220, 60, 50)
    if severity == "Moderate":
        return (220, 170, 50)
    return (200, 200, 80)


def _daylight_factor(col_dt, sun_events):
    """Return a brightness factor (0.0–1.0) for a given datetime.

    1.0 = full daylight, 0.0 = full night.
    Transitions smoothly over ~40 minutes at dawn/dusk.
    sun_events is a list of (sunrise_dt, sunset_dt) tuples for each day.
    """
    TRANSITION_MINS = 40
    best = 0.0
    for rise, sset in sun_events:
        if rise is None or sset is None:
            continue
        # Minutes relative to sunrise/sunset
        mins_from_rise = (col_dt - rise).total_seconds() / 60
        mins_from_set = (col_dt - sset).total_seconds() / 60

        if mins_from_rise >= TRANSITION_MINS and mins_from_set <= -TRANSITION_MINS:
            # Full day
            return 1.0
        elif mins_from_rise < 0 and mins_from_set > 0:
            # Full night (before sunrise, after sunset)
            pass
        else:
            # In transition zone
            dawn_f = max(0.0, min(1.0, mins_from_rise / TRANSITION_MINS))
            dusk_f = max(0.0, min(1.0, -mins_from_set / TRANSITION_MINS))
            f = min(dawn_f, dusk_f)
            best = max(best, f)
    return best


def _parse_sun_events(daily):
    """Parse sunrise/sunset ISO strings from daily data into datetime pairs."""
    events = []
    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])
    for i in range(max(len(sunrises), len(sunsets))):
        rise = sunset = None
        try:
            if i < len(sunrises) and sunrises[i]:
                rise = datetime.fromisoformat(sunrises[i])
        except Exception:
            pass
        try:
            if i < len(sunsets) and sunsets[i]:
                sunset = datetime.fromisoformat(sunsets[i])
        except Exception:
            pass
        events.append((rise, sunset))
    return events


# ---------------------------------------------------------------------------
# Braille temperature curve (multi-row, smooth line)
# ---------------------------------------------------------------------------
def _build_braille_curve(temps, graph_w, n_rows=2):
    """Build an n_rows-high braille line graph from temperature data.

    Returns a list of n_rows rows, each a list of (char, avg_temp) tuples.
    Together the rows form a (n_rows*4)-dot-high graph spanning graph_w chars.
    Uses proper column assignment for thin diagonal lines instead of thick bands.
    """
    n = 2 * graph_w  # samples: 2 per braille char (left col, right col)
    total_dots = n_rows * 4

    # Interpolate temps to n evenly spaced samples
    samples = []
    for i in range(n):
        t = i / max(1, n - 1) * max(0, len(temps) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(temps) - 1)
        frac = t - lo_i
        samples.append(temps[lo_i] + (temps[hi_i] - temps[lo_i]) * frac)

    s_min, s_max = min(samples), max(samples)

    # Map to float y: 0=top(max temp), total_dots-1=bottom(min temp)
    if s_max == s_min:
        ys = [total_dots / 2] * n
    else:
        s_range = s_max - s_min
        ys = [(total_dots - 1) * (1 - (s - s_min) / s_range) for s in samples]

    # Round to integer dot positions
    ys_i = [max(0, min(total_dots - 1, int(round(y)))) for y in ys]

    # Braille dot bit positions: BITS[col][row] for 2×4 grid within each char
    BITS = [[0x01, 0x02, 0x04, 0x40],   # col 0, rows 0–3
            [0x08, 0x10, 0x20, 0x80]]    # col 1, rows 0–3

    # Bit storage per (braille_row, char_col)
    rows_bits = [[0] * graph_w for _ in range(n_rows)]

    def _set_dot(ci, y, col):
        """Set a single braille dot at char index ci, dot row y, column col."""
        if ci < 0 or ci >= graph_w or y < 0 or y >= total_dots:
            return
        row_idx = y // 4
        local_y = y % 4
        rows_bits[row_idx][ci] |= BITS[col][local_y]

    for i in range(graph_w):
        left_y = ys_i[2 * i]
        right_y = ys_i[2 * i + 1]

        # Place endpoint dots
        _set_dot(i, left_y, 0)
        _set_dot(i, right_y, 1)

        # Connect left→right: assign intermediate dots to correct column
        if left_y != right_y:
            y_lo, y_hi = min(left_y, right_y), max(left_y, right_y)
            for y in range(y_lo, y_hi + 1):
                x_frac = (y - left_y) / (right_y - left_y)
                col = 0 if abs(x_frac) < 0.5 else 1
                _set_dot(i, y, col)

        # Cross-char continuity: bridge from previous char's right col
        if i > 0:
            prev_y = ys_i[2 * i - 1]
            if prev_y != left_y:
                y_lo, y_hi = min(prev_y, left_y), max(prev_y, left_y)
                for y in range(y_lo, y_hi + 1):
                    _set_dot(i, y, 0)

    # Convert to (char, avg_temp) tuples per row
    result = []
    for r in range(n_rows):
        row = []
        for ci in range(graph_w):
            avg_temp = (samples[2 * ci] + samples[2 * ci + 1]) / 2
            row.append((chr(0x2800 + rows_bits[r][ci]), avg_temp))
        result.append(row)

    return result


def _build_precip_blocks(precip_probs, weather_codes, graph_w, n_rows=1):
    """Build multi-row block bar graph for precipitation probability.

    Returns a list of rendered line strings (n_rows lines).
    Bars grow upward from the bottom using partial block characters (▁▂▃▄▅▆▇█),
    giving 8 levels of vertical resolution per character row.
    """
    total_eighths = n_rows * 8  # total vertical resolution units

    # Interpolate precip probability to 1 sample per column
    col_probs = []
    col_codes = []
    for x in range(graph_w):
        t = x / max(1, graph_w - 1) * max(0, len(precip_probs) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(precip_probs) - 1)
        frac = t - lo_i
        col_probs.append(precip_probs[lo_i] + (precip_probs[hi_i] - precip_probs[lo_i]) * frac)

        code_t = x / max(1, graph_w - 1) * max(0, len(weather_codes) - 1)
        code_i = max(0, min(len(weather_codes) - 1, int(round(code_t))))
        col_codes.append(weather_codes[code_i] if weather_codes else 0)

    # Build rows top-down (row 0 = top, row n_rows-1 = bottom)
    result = []
    for r in range(n_rows):
        line = " "
        row_bottom = (n_rows - 1 - r) * 8  # eighths at bottom of this row
        row_top = row_bottom + 8             # eighths at top of this row
        for x in range(graph_w):
            p = col_probs[x]
            if p <= 5:
                line += " "
                continue
            # Bar height in eighths (0 to total_eighths)
            bar_h = max(1, int(p / 100 * total_eighths + 0.5))
            if bar_h <= row_bottom:
                # Bar doesn't reach this row
                line += " "
            elif bar_h >= row_top:
                # Bar fills this row completely
                color = _precip_color(col_codes[x])
                line += f"{color}\u2588"
            else:
                # Bar partially fills this row
                eighths_in_row = bar_h - row_bottom  # 1-7
                color = _precip_color(col_codes[x])
                line += f"{color}{SPARKLINE[eighths_in_row - 1]}"
        result.append(f"{line}{RESET}")

    return result


# ---------------------------------------------------------------------------
# Comparative weather line
# ---------------------------------------------------------------------------
def _comparative_line(daily, now, runtime=None):
    """Natural language comparing today vs yesterday/tomorrow."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    hi_temps = daily.get("temperature_2m_max", [])

    # With past_days=1: index 0=yesterday, 1=today, 2=tomorrow
    if len(hi_temps) < 3:
        return ""

    if now.hour < 14:
        diff = hi_temps[1] - hi_temps[0]
        ref_day = "yesterday"
        subject = "Today"
    else:
        diff = hi_temps[2] - hi_temps[1]
        ref_day = "today"
        subject = "Tomorrow"

    abs_diff = abs(diff)
    # Thresholds in degrees (smaller for Celsius since 1°C ≈ 1.8°F)
    t_same, t_bit, t_much = (2, 4, 8) if runtime.metric else (3, 8, 15)
    if abs_diff < t_same:
        comparison = f"about the same as {ref_day}"
    elif abs_diff < t_bit:
        word = "warmer" if diff > 0 else "cooler"
        comparison = f"a bit {word} than {ref_day}"
    elif abs_diff < t_much:
        word = "warmer" if diff > 0 else "cooler"
        comparison = f"{word} than {ref_day}"
    else:
        word = "warmer" if diff > 0 else "cooler"
        comparison = f"much {word} than {ref_day}"

    return f" {MUTED}{subject} will be {comparison}{RESET}"


# ---------------------------------------------------------------------------
# Precipitation forecast line
# ---------------------------------------------------------------------------
_PRECIP_CODES = {51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99}

_PRECIP_DESCS = {
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms", 99: "thunderstorms",
}


def _precipitation_line(hourly, now):
    """Natural language description of upcoming precipitation."""
    times = hourly.get("time", [])
    precip_prob = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])

    if not times or not precip_prob or not codes:
        return ""

    current_hour = now.replace(minute=0, second=0, microsecond=0)

    # Build window: (data_index, datetime) for next 24h
    window = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
            if dt >= current_hour:
                window.append((i, dt))
        except Exception:
            continue
    window = [(i, dt) for i, dt in window if dt <= current_hour + timedelta(hours=24)]
    if len(window) < 2:
        return ""

    def is_precip(idx):
        p = precip_prob[idx] if idx < len(precip_prob) else 0
        c = codes[idx] if idx < len(codes) else 0
        return c in _PRECIP_CODES and p > 30

    def desc(idx):
        c = codes[idx] if idx < len(codes) else 0
        return _PRECIP_DESCS.get(c, "precipitation")

    def time_phrase(dt):
        delta = (dt - now).total_seconds() / 3600
        if delta < 1.5:
            return "shortly"
        if delta < 2.5:
            return "in about an hour"
        if delta < 4:
            return "in a couple hours"
        if dt.date() == now.date():
            h12 = dt.hour % 12 or 12
            suffix = "am" if dt.hour < 12 else "pm"
            return f"around {h12}{suffix}"
        if dt.date() == (now + timedelta(days=1)).date():
            if dt.hour < 12:
                return "tomorrow morning"
            if dt.hour < 17:
                return "tomorrow afternoon"
            return "tomorrow evening"
        return f"on {DAY_NAMES[dt.weekday()]}"

    first_idx = window[0][0]

    if is_precip(first_idx):
        current_desc = desc(first_idx)
        for i, dt in window[1:]:
            if not is_precip(i):
                return f" {MUTED}{current_desc.capitalize()} ending {time_phrase(dt)}{RESET}"
        return f" {MUTED}{current_desc.capitalize()} continuing through the day{RESET}"
    else:
        for i, dt in window[1:]:
            if is_precip(i):
                return f" {MUTED}{desc(i).capitalize()} likely starting {time_phrase(dt)}{RESET}"
        return ""


def _interpolate_columns(values, graph_w):
    """Linearly interpolate values to one sample per terminal column."""
    cols = []
    for x in range(graph_w):
        t = x / max(1, graph_w - 1) * max(0, len(values) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(values) - 1)
        frac = t - lo_i
        cols.append(values[lo_i] + (values[hi_i] - values[lo_i]) * frac)
    return cols


def _prepare_hourly_window(hourly, now, graph_w):
    """Slice hourly arrays to the upcoming visible window."""
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip_prob = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    wind_directions = hourly.get("wind_direction_10m", [])
    if not times or not temps:
        return None

    parsed = []
    for i, t in enumerate(times):
        try:
            parsed.append((i, datetime.fromisoformat(t)))
        except Exception:
            continue

    current_hour_dt = now.replace(minute=0, second=0, microsecond=0)
    start_idx = 0
    for i, dt in parsed:
        if dt >= current_hour_dt:
            start_idx = i
            break

    hours_shown = max(24, min(48, graph_w // 2))
    end_time = current_hour_dt + timedelta(hours=hours_shown)
    end_idx = start_idx
    for i, dt in parsed:
        if i >= start_idx and dt <= end_time:
            end_idx = i

    window_temps = temps[start_idx:end_idx + 1]
    if len(window_temps) < 2:
        return None

    window_precip = precip_prob[start_idx:end_idx + 1] if precip_prob else []
    window_codes = weather_codes[start_idx:end_idx + 1] if weather_codes else []
    window_winds = wind_speeds[start_idx:end_idx + 1] if wind_speeds else []
    window_wind_dirs = wind_directions[start_idx:end_idx + 1] if wind_directions else []
    window_dts = [dt for i, dt in parsed if start_idx <= i <= end_idx]

    total_hours = 24
    if window_dts and len(window_dts) > 1:
        total_secs = (window_dts[-1] - window_dts[0]).total_seconds()
        total_hours = total_secs / 3600 if total_secs > 0 else 24

    return {
        "temps": window_temps,
        "precip": window_precip,
        "codes": window_codes,
        "winds": window_winds,
        "wind_dirs": window_wind_dirs,
        "dts": window_dts,
        "total_hours": total_hours,
    }


def _compute_time_markers(window_dts, total_hours, graph_w):
    """Compute notable timeline columns (midnight, noon) and day labels."""
    midnight_cols = set()
    noon_cols = set()
    midnight_day_names = {}
    if window_dts:
        for h_off in range(int(total_hours) + 1):
            dt = window_dts[0] + timedelta(hours=h_off)
            x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
            if not (0 < x < graph_w - 1):
                continue
            if dt.hour == 0:
                midnight_cols.add(x)
                midnight_day_names[x] = dt.strftime("%A")
            elif dt.hour == 12:
                noon_cols.add(x)
    return midnight_cols, noon_cols, midnight_day_names


def _compute_sun_labels(window_dts, sun_events, total_hours, graph_w, runtime):
    """Compute sunrise/sunset labels mapped to graph columns."""
    sun_labels = {}
    sunrise_icon = "\u2600\ufe0f" if runtime.emoji else "\ue34c"
    sunset_icon = "\U0001f305" if runtime.emoji else "\ue34d"
    if window_dts and sun_events:
        t0 = window_dts[0]
        for rise, sset in sun_events:
            if rise:
                off_h = (rise - t0).total_seconds() / 3600
                if 0 < off_h < total_hours:
                    x = int(off_h / total_hours * (graph_w - 1))
                    if 0 < x < graph_w - 1:
                        lbl = rise.strftime("%-I:%M%p").lower().replace("am", "a").replace("pm", "p")
                        sun_labels[x] = (f"{sunrise_icon}{lbl}", True)
            if sset:
                off_h = (sset - t0).total_seconds() / 3600
                if 0 < off_h < total_hours:
                    x = int(off_h / total_hours * (graph_w - 1))
                    if 0 < x < graph_w - 1:
                        lbl = sset.strftime("%-I:%M%p").lower().replace("am", "a").replace("pm", "p")
                        sun_labels[x] = (f"{sunset_icon}{lbl}", False)
    return sun_labels


def _compute_daylight_columns(window_dts, sun_events, graph_w):
    """Compute per-column daylight factor for day/night tinting."""
    if window_dts and sun_events:
        col_daylight = []
        for x in range(graph_w):
            t_frac = x / max(1, graph_w - 1) * max(0, len(window_dts) - 1)
            lo_i = int(t_frac)
            hi_i = min(lo_i + 1, len(window_dts) - 1)
            frac = t_frac - lo_i
            secs = (window_dts[lo_i] + (window_dts[hi_i] - window_dts[lo_i]) * frac).timestamp()
            if window_dts[0].tzinfo:
                col_dt = datetime.fromtimestamp(secs, tz=window_dts[0].tzinfo)
            else:
                col_dt = datetime.fromtimestamp(secs)
            col_daylight.append(_daylight_factor(col_dt, sun_events))
        return col_daylight
    return [1.0] * graph_w


def _find_temperature_extrema(col_temps, graph_w):
    """Detect prominent peaks and valleys for chart annotations."""
    extrema = []  # (x, temp, is_peak)
    if len(col_temps) < 5:
        return extrema

    min_gap = max(8, graph_w // 15)
    for i in range(2, len(col_temps) - 2):
        local = col_temps[max(0, i - 3):i + 4]
        is_peak = col_temps[i] >= max(local) and (
            col_temps[i] > col_temps[i - 1] or col_temps[i] > col_temps[i + 1]
        )
        is_valley = col_temps[i] <= min(local) and (
            col_temps[i] < col_temps[i - 1] or col_temps[i] < col_temps[i + 1]
        )
        if not is_peak and not is_valley:
            continue
        neighbors_l = col_temps[max(0, i - 15):i]
        neighbors_r = col_temps[i + 1:min(len(col_temps), i + 16)]
        if not neighbors_l or not neighbors_r:
            continue
        if is_peak:
            prom = col_temps[i] - max(min(neighbors_l), min(neighbors_r))
        else:
            prom = min(max(neighbors_l), max(neighbors_r)) - col_temps[i]
        if prom < 3:
            continue
        if not any(abs(i - ex) < min_gap for ex, _, _ in extrema):
            extrema.append((i, col_temps[i], is_peak))

    global_max_x = max(range(len(col_temps)), key=lambda i: col_temps[i])
    global_min_x = min(range(len(col_temps)), key=lambda i: col_temps[i])
    for gx, is_peak in [(global_max_x, True), (global_min_x, False)]:
        if not any(abs(gx - ex) < min_gap and p == is_peak for ex, _, p in extrema):
            extrema.append((gx, col_temps[gx], is_peak))

    return extrema


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_header(data, width, location_name="", runtime=None):
    """Current conditions header line."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    current = data.get("current", {})
    temp = current.get("temperature_2m", 0)
    feels = current.get("apparent_temperature", 0)
    wmo = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    gusts = current.get("wind_gusts_10m", 0)

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    name = WMO_NAMES.get(wmo, "")

    left = (
        f" {TEXT}{icon} {name}  "
        f"{_colored_temp(temp, runtime, runtime.temp_unit)}"
        f"  {MUTED}feels {_colored_temp(feels, runtime, runtime.temp_unit)}"
    )

    right_parts = []
    if wind > (15 if runtime.metric else 10) or gusts > (30 if runtime.metric else 20):
        parts = [f"Wind {wind:.0f}{runtime.wind_unit}"]
        if gusts > (30 if runtime.metric else 20):
            parts.append(f"gusts {gusts:.0f}{runtime.wind_unit}")
        right_parts.append(f"{WIND_COLOR}{'  '.join(parts)}")
    if location_name:
        right_parts.append(f"{MUTED}{location_name}")

    right = f"  {MUTED}\u00b7  ".join(right_parts) if right_parts else ""

    if right:
        pad = width - visible_len(left) - visible_len(right) - 2
        return f"{left}{' ' * max(1, pad)}{right} {RESET}"
    return f"{left}{RESET}"


def _render_today_line(width, chart_lo, chart_hi, midnight_day_names, sun_labels, runtime):
    """Render the hourly section header with day and sun-event labels."""
    today_left = f" {TEXT}Today"
    today_right = (
        f"{_colored_temp(chart_lo, runtime, '°')} "
        f"{TEXT}\u2192 {_colored_temp(chart_hi, runtime, runtime.temp_unit)}"
    )
    if not (midnight_day_names or sun_labels):
        pad = width - visible_len(today_left) - visible_len(today_right) - 2
        return f"{today_left}{' ' * max(1, pad)}{today_right} {RESET}"

    label_start = visible_len(today_left)
    right_len = visible_len(today_right) + 2
    avail = width - right_len
    mid_w = max(0, avail - label_start)

    mid_canvas = [" "] * mid_w
    mid_colors = [None] * mid_w

    for col, name in sorted(midnight_day_names.items()):
        pos = col + 1 - label_start
        if pos >= 0 and pos + len(name) <= mid_w:
            for j, c in enumerate(name):
                mid_canvas[pos + j] = c

    for col, (lbl, is_rise) in sorted(sun_labels.items()):
        pos = max(0, col + 1 - label_start)
        if pos + len(lbl) > mid_w:
            continue
        if all(mid_canvas[pos + j] == " " for j in range(len(lbl))):
            color = (200, 160, 60) if is_rise else (200, 100, 50)
            for j, c in enumerate(lbl):
                mid_canvas[pos + j] = c
                mid_colors[pos + j] = color

    mid_str = ""
    cur_color = None
    for i in range(mid_w):
        color = mid_colors[i]
        if color != cur_color:
            if color is None:
                mid_str += f"{TEXT}"
            else:
                mid_str += f"{fg(*color)}"
            cur_color = color
        mid_str += mid_canvas[i]
    if cur_color is not None:
        mid_str += f"{TEXT}"

    pad = width - visible_len(today_left) - mid_w - visible_len(today_right) - 2
    return f"{today_left}{mid_str}{' ' * max(0, pad)}{today_right} {RESET}"


def _render_extrema_line(extrema, graph_w, runtime, is_peak):
    """Render one extrema annotation line (peaks above or valleys below)."""
    points = sorted([(x, t) for x, t, peak in extrema if peak == is_peak])
    if not points:
        return None

    segments, cursor = [], 0
    for x, temp in points:
        label = f"{temp:.0f}\u00b0"
        pos = max(cursor, x + 1 - len(label) // 2)
        if pos + len(label) > graph_w + 1:
            continue
        if pos > cursor:
            segments.append((" " * (pos - cursor), None))
        segments.append((label, temp))
        cursor = pos + len(label)
    if not segments:
        return None

    line = ""
    for text, temp in segments:
        if temp is None:
            line += text
            continue
        r, g, b = _temp_color(temp, runtime)
        line += f"{fg(r, g, b)}{text}"
    return f"{line}{RESET}"


def _render_braille_rows(braille_rows, col_daylight, midnight_cols, noon_cols, runtime):
    """Render braille temperature rows with optional day/night shading."""
    shading = runtime.shading
    night_dim = 0.6
    midnight_fg = fg(50, 30, 80)
    noon_fg = fg(100, 120, 150)
    bg_night = (12, 12, 22)
    bg_day = (18, 22, 32)

    lines = []
    for row in braille_rows:
        line = " "
        for ci, (ch, temp) in enumerate(row):
            dl = col_daylight[ci] if ci < len(col_daylight) else 1.0

            if shading:
                br = int(bg_night[0] + (bg_day[0] - bg_night[0]) * dl)
                bg_g = int(bg_night[1] + (bg_day[1] - bg_night[1]) * dl)
                bb = int(bg_night[2] + (bg_day[2] - bg_night[2]) * dl)
                bg_str = bg(br, bg_g, bb)

                if ci in midnight_cols and ch == '\u2800':
                    line += f"{bg_str}{midnight_fg}\u2502{RESET}"
                elif ci in noon_cols and ch == '\u2800':
                    line += f"{bg_str}{noon_fg}\u2502{RESET}"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    line += f"{bg_str}{fg(r, g, b)}{ch}{RESET}"
            else:
                if ci in midnight_cols and ch == '\u2800':
                    line += f"{DIM}\u2502"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    brightness = night_dim + (1.0 - night_dim) * dl
                    line += f"{fg(int(r * brightness), int(g * brightness), int(b * brightness))}{ch}"
        lines.append(f"{line}{RESET}")
    return lines


def _render_tick_labels(window_dts, total_hours, graph_w):
    """Render compact timeline tick labels under the chart."""
    if not window_dts:
        return None
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
        x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
        dt = window_dts[0] + timedelta(hours=h_off)
        label_items.append((x, _fmt_hour(dt.hour), dt.hour == 0))

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
    return f" {DIM}{''.join(canvas)}{RESET}"


def _render_wind_row(window_winds, window_wind_dirs, total_hours, graph_w, runtime):
    """Render wind arrows/speed labels at high-wind positions."""
    wind_threshold = 25 if runtime.metric else 15
    if not window_winds or max(window_winds, default=0) <= wind_threshold:
        return None

    wind_canvas = [" "] * graph_w
    sample_interval = max(1, int(3 / total_hours * (graph_w - 1))) if total_hours > 0 else 6
    for x in range(0, graph_w, max(1, sample_interval)):
        t = x / max(1, graph_w - 1) * max(0, len(window_winds) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(window_winds) - 1)
        frac = t - lo_i
        speed = window_winds[lo_i] + (window_winds[hi_i] - window_winds[lo_i]) * frac
        if speed <= wind_threshold:
            continue

        dir_i = max(0, min(len(window_wind_dirs) - 1, int(round(t)))) if window_wind_dirs else 0
        deg = window_wind_dirs[dir_i] if window_wind_dirs else 0
        sector = int((deg + 22.5) / 45) % 8
        arrow = WIND_ARROWS[sector]
        label = f"{arrow}{speed:.0f}"

        start = max(0, x - len(label) // 2)
        if start + len(label) > graph_w:
            start = graph_w - len(label)
        if all(wind_canvas[start + j] == " " for j in range(len(label)) if start + j < graph_w):
            for j, ch in enumerate(label):
                if start + j < graph_w:
                    wind_canvas[start + j] = ch
    if any(c != " " for c in wind_canvas):
        return f" {WIND_COLOR}{''.join(wind_canvas)}{RESET}"
    return None


def _render_precip_rows(window_precip, window_codes, graph_w, n_precip_rows):
    """Render precipitation probability graph rows."""
    if not window_precip or max(window_precip, default=0) <= 5:
        return []
    if n_precip_rows >= 1:
        return _build_precip_blocks(window_precip, window_codes, graph_w, n_precip_rows)

    precip_chars = []
    col_precip = _interpolate_columns(window_precip, graph_w)
    for x, p in enumerate(col_precip):
        if p <= 5:
            precip_chars.append(" ")
            continue
        code_t = x / max(1, graph_w - 1) * max(0, len(window_codes) - 1)
        code_i = max(0, min(len(window_codes) - 1, int(round(code_t))))
        wmo = window_codes[code_i] if window_codes else 0
        color = _precip_color(wmo)
        idx = max(0, min(7, int(p / 100 * 7.99)))
        precip_chars.append(f"{color}{SPARKLINE[idx]}")
    return [f" {''.join(precip_chars)}{RESET}"]


def render_hourly(data, width, n_braille_rows=2, n_precip_rows=0, now=None, runtime=None):
    """Hourly forecast: braille temperature curve + precipitation graph."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    daily = data.get("daily", {})
    sun_events = _parse_sun_events(daily)
    if now is None:
        now = _local_now_for_data(data)

    graph_w = max(10, width - 2)
    window = _prepare_hourly_window(data.get("hourly", {}), now, graph_w)
    if window is None:
        return []

    window_temps = window["temps"]
    window_precip = window["precip"]
    window_codes = window["codes"]
    window_winds = window["winds"]
    window_wind_dirs = window["wind_dirs"]
    window_dts = window["dts"]
    total_hours = window["total_hours"]
    chart_lo = min(window_temps)
    chart_hi = max(window_temps)

    midnight_cols, noon_cols, midnight_day_names = _compute_time_markers(
        window_dts, total_hours, graph_w
    )
    sun_labels = _compute_sun_labels(window_dts, sun_events, total_hours, graph_w, runtime)
    col_daylight = _compute_daylight_columns(window_dts, sun_events, graph_w)
    col_temps = _interpolate_columns(window_temps, graph_w)
    extrema = _find_temperature_extrema(col_temps, graph_w)

    lines = [
        _render_today_line(
            width,
            chart_lo,
            chart_hi,
            midnight_day_names,
            sun_labels,
            runtime,
        )
    ]

    peak_line = _render_extrema_line(extrema, graph_w, runtime, is_peak=True)
    if peak_line:
        lines.append(peak_line)

    braille_rows = _build_braille_curve(window_temps, graph_w, n_braille_rows)
    lines.extend(_render_braille_rows(braille_rows, col_daylight, midnight_cols, noon_cols, runtime))

    valley_line = _render_extrema_line(extrema, graph_w, runtime, is_peak=False)
    if valley_line:
        lines.append(valley_line)

    tick_line = _render_tick_labels(window_dts, total_hours, graph_w)
    if tick_line:
        lines.append(tick_line)

    wind_line = _render_wind_row(window_winds, window_wind_dirs, total_hours, graph_w, runtime)
    if wind_line:
        lines.append(wind_line)

    lines.extend(_render_precip_rows(window_precip, window_codes, graph_w, n_precip_rows))
    return lines


def render_daily(data, width, runtime=None):
    """Daily forecast with temperature range bars."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    daily = data.get("daily", {})
    times = daily.get("time", [])
    hi_temps = daily.get("temperature_2m_max", [])
    lo_temps = daily.get("temperature_2m_min", [])
    precip_sum = daily.get("precipitation_sum", [])
    precip_prob = daily.get("precipitation_probability_max", [])
    wmo_codes = daily.get("weather_code", [])
    wind_max = daily.get("wind_speed_10m_max", [])

    lines = []

    # With past_days=1: 0=yesterday, 1=today, 2+=forecast
    # Show today (1) through end for scale, display 2+ as forecast rows
    display_end = min(len(times), 8)
    if display_end < 3:
        return lines

    # Common temperature scale across today + all forecast days
    all_lo = [lo_temps[i] for i in range(1, display_end) if i < len(lo_temps)]
    all_hi = [hi_temps[i] for i in range(1, display_end) if i < len(hi_temps)]
    if not all_lo or not all_hi:
        return lines

    scale_min = min(all_lo)
    scale_max = max(all_hi)

    # Measure widest right-side detail columns across all days for alignment
    left_prefix_w = 10  # "  Tod  ⛅  " = day(3) + icon(1) + spacing(6)
    # Compute per-day detail fields and find max width of each column
    day_details = []  # list of (precip_str, prob_str, wind_str) per day
    max_precip_w = 0
    max_prob_w = 0
    max_wind_w = 0
    for i in range(1, display_end):
        precip_i = precip_sum[i] if i < len(precip_sum) else 0
        prob_i = precip_prob[i] if i < len(precip_prob) else 0
        wind_i = wind_max[i] if i < len(wind_max) else 0
        wmo_i = wmo_codes[i] if i < len(wmo_codes) else 0
        precip_s = ""
        if precip_i >= (1 if runtime.metric else 0.05):
            ptype = _precip_type(wmo_i)
            if runtime.metric:
                precip_s = f"{ptype} {precip_i:.0f}{runtime.precip_unit}"
            else:
                precip_s = f"{ptype} {precip_i:.1f}{runtime.precip_unit}"
        prob_s = f"{prob_i:.0f}%" if prob_i > 25 else ""
        wind_s = f"Wind {wind_i:.0f}{runtime.wind_unit}" if wind_i > (25 if runtime.metric else 15) else ""
        day_details.append((precip_s, prob_s, wind_s))
        if precip_s:
            max_precip_w = max(max_precip_w, len(precip_s))
        if prob_s:
            max_prob_w = max(max_prob_w, len(prob_s))
        if wind_s:
            max_wind_w = max(max_wind_w, len(wind_s))

    max_right_w = 0
    if max_prob_w:
        max_right_w += 2 + max_prob_w
    if max_precip_w:
        max_right_w += 2 + max_precip_w
    if max_wind_w:
        max_right_w += 2 + max_wind_w

    # Bar gets all remaining width after left prefix, right details, and padding
    bar_w = max(10, width - left_prefix_w - max_right_w - 2)

    # Ensure outside labels always fit
    max_lo_label = max(
        len(f"{lo_temps[i]:.0f}\u00b0") for i in range(1, display_end) if i < len(lo_temps)
    )
    max_hi_label = max(
        len(f"{hi_temps[i]:.0f}\u00b0") for i in range(1, display_end) if i < len(hi_temps)
    )
    inner_w = bar_w - 1 - max_lo_label - max_hi_label
    if inner_w < 1:
        inner_w = 1
    actual_range = max(scale_max - scale_min, 1)
    deg_per_char = actual_range / max(inner_w, 1)
    scale_min = scale_min - max_lo_label * deg_per_char
    scale_max = scale_max + max_hi_label * deg_per_char
    scale_range = max(scale_max - scale_min, 1)

    DARK_FG = fg(20, 20, 25)
    icons = _wmo_icons(runtime)

    for i in range(1, display_end):
        if i == 1:
            day_name = "Tod"
        else:
            try:
                dt = datetime.fromisoformat(times[i])
                day_name = DAY_NAMES[dt.weekday()]
            except Exception:
                day_name = "???"

        wmo = wmo_codes[i] if i < len(wmo_codes) else 0
        icon = icons.get(wmo, icons[0])
        hi = hi_temps[i] if i < len(hi_temps) else 0
        lo = lo_temps[i] if i < len(lo_temps) else 0
        precip = precip_sum[i] if i < len(precip_sum) else 0
        prob = precip_prob[i] if i < len(precip_prob) else 0
        wind = wind_max[i] if i < len(wind_max) else 0

        # Temperature range bar with integrated labels
        lo_pos = int((lo - scale_min) / scale_range * (bar_w - 1))
        hi_pos = int((hi - scale_min) / scale_range * (bar_w - 1))
        hi_pos = max(hi_pos, lo_pos + 1)  # at least 1 char wide

        lo_label = f"{lo:.0f}\u00b0"
        hi_label = f"{hi:.0f}\u00b0"
        lo_len = len(lo_label)
        hi_len = len(hi_label)
        filled_w = hi_pos - lo_pos + 1

        # Decide label placement: inside (knocked out) or outside
        both_inside = filled_w >= lo_len + hi_len + 2
        hi_inside = not both_inside and filled_w >= hi_len + 1
        lo_inside = both_inside

        lo_r, lo_g, lo_b = _temp_color(lo, runtime)
        hi_r, hi_g, hi_b = _temp_color(hi, runtime)

        cells = []
        for bx in range(bar_w):
            if lo_pos <= bx <= hi_pos:
                t_frac = (bx - lo_pos) / max(1, hi_pos - lo_pos)
                temp_at = lo + (hi - lo) * t_frac
                r, g, b = _temp_color(temp_at, runtime)
                rel = bx - lo_pos
                if lo_inside and rel < lo_len:
                    cells.append((lo_label[rel], f"{bg(r, g, b)}{DARK_FG}{BOLD}"))
                elif both_inside and rel >= filled_w - hi_len:
                    hi_idx = rel - (filled_w - hi_len)
                    cells.append((hi_label[hi_idx], f"{bg(r, g, b)}{DARK_FG}{BOLD}"))
                elif hi_inside and not both_inside and rel >= filled_w - hi_len:
                    hi_idx = rel - (filled_w - hi_len)
                    cells.append((hi_label[hi_idx], f"{bg(r, g, b)}{DARK_FG}{BOLD}"))
                else:
                    cells.append(("\u2588", f"{fg(r, g, b)}"))
            else:
                cells.append(("\u2500", f"{DIM}"))

        # Overlay outside labels adjacent to filled region
        if not lo_inside:
            label_start = lo_pos - lo_len
            if label_start >= 0:
                for j, ch in enumerate(lo_label):
                    cells[label_start + j] = (ch, f"{fg(lo_r, lo_g, lo_b)}")
        if not (both_inside or hi_inside):
            label_start = hi_pos + 1
            if label_start + hi_len <= bar_w:
                for j, ch in enumerate(hi_label):
                    cells[label_start + j] = (ch, f"{fg(hi_r, hi_g, hi_b)}")

        bar = "".join(f"{prefix}{ch}{RESET}" for ch, prefix in cells)

        # Build the line with aligned right-side columns
        line = f"  {TEXT}{day_name}  {icon}  {bar}"

        precip_s, prob_s, wind_s = day_details[i - 1]
        pcolor = _precip_color(wmo)
        if max_prob_w:
            line += f"  {pcolor}{prob_s:>{max_prob_w}}" if prob_s else f"  {' ' * max_prob_w}"
        if max_precip_w:
            line += f"  {pcolor}{precip_s:<{max_precip_w}}" if precip_s else f"  {' ' * max_precip_w}"
        if max_wind_w:
            line += f"  {WIND_COLOR}{wind_s:<{max_wind_w}}" if wind_s else f"  {' ' * max_wind_w}"

        lines.append(f"{line}{RESET}")

    return lines


def _render_single_alert(alert, width, max_lines=999):
    """Render one alert (pill + wrapped description), up to max_lines."""
    DARK_FG = fg(20, 20, 25)
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")
    effective = _parse_alert_time(alert.get("effective", ""))
    expires = _parse_alert_time(alert.get("expires", ""))
    timing = ""
    if effective and expires:
        timing = f" {effective} \u2013 {expires}"
    elif expires:
        timing = f" until {expires}"

    pill = f"{bg_color}{DARK_FG}{BOLD} \u26a0 {event} {RESET}"
    line1 = f" {pill} {MUTED}\u00b7{WIND_COLOR}{timing}{RESET}" if timing else f" {pill}{RESET}"
    lines = [line1]

    desc = alert.get("description", "").strip()
    if desc and max_lines > 1:
        desc = " ".join(desc.split())
        wrap_w = width - 2
        words = desc.split()
        current_line = ""
        desc_lines = 0
        max_desc = max_lines - 1  # 1 line for pill
        for word in words:
            if current_line and len(current_line) + 1 + len(word) > wrap_w:
                lines.append(f"  {MUTED}{current_line}{RESET}")
                desc_lines += 1
                if desc_lines >= max_desc:
                    break
                current_line = word
            else:
                current_line = f"{current_line} {word}" if current_line else word
        if current_line and desc_lines < max_desc:
            lines.append(f"  {MUTED}{current_line}{RESET}")

    return lines


def render_alerts(alerts, width=80, remaining_rows=None):
    """NWS/ECCC alert banners — severity-colored background pill + description."""
    if not alerts:
        return []
    n = len(alerts)

    if remaining_rows is not None:
        # Blank line between each alert, evenly distribute remaining space
        separator_lines = n - 1
        usable = max(n, remaining_rows - separator_lines)
        per_alert = usable // n
        # Distribute remainder to earlier alerts
        extras = usable - per_alert * n
    else:
        per_alert = 999
        extras = 0

    lines = []
    for idx, a in enumerate(alerts):
        if idx > 0:
            lines.append("")  # blank separator between alerts
        budget = per_alert + (1 if idx < extras else 0)
        lines.extend(_render_single_alert(a, width, max_lines=budget))

    return lines


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0):
    """Build the complete weather dashboard from preloaded data."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}"

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)

    # Estimate fixed-height sections to budget remaining rows for graphs
    # Header(1) + blank(1) + hourly_header(1) + peaks(1) + valleys(1)
    # + tick_labels(1) + wind_row(1) + comp_line(1) + precip_text(1) + blank(1)
    # + daily(7) = ~17 fixed lines, plus alerts
    alert_lines_est = 0
    if alerts:
        alert_lines_est = max(4, len(alerts) * 3)  # rough estimate

    fixed_lines = 17 + alert_lines_est
    available = max(0, rows - fixed_lines)

    # Distribute available rows between temperature graph and precip graph
    # Precip gets up to 3 braille rows, temp gets the rest
    hourly = data.get("hourly", {})
    has_precip_graph = bool(hourly.get("precipitation_probability")) and max(hourly.get("precipitation_probability", [0])) > 5
    if has_precip_graph:
        n_precip_braille = min(3, max(1, available // 6))
        remaining_for_temp = available - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = available

    # Temperature graph: minimum 2 braille rows, grows to fill available space
    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime))
    lines.append("")

    # Hourly
    lines.extend(
        render_hourly(
            data,
            cols,
            n_braille_rows=n_braille,
            n_precip_rows=n_precip_braille,
            now=now_local,
            runtime=runtime,
        )
    )

    # Comparative line
    comp = _comparative_line(data.get("daily", {}), now_local, runtime)
    if comp:
        lines.append(comp)

    # Precipitation forecast
    precip = _precipitation_line(data.get("hourly", {}), now_local)
    if precip:
        lines.append(precip)

    lines.append("")

    # Daily
    lines.extend(render_daily(data, cols, runtime))

    # Alerts
    if alerts:
        lines.append("")
        remaining = max(4, rows - len(lines) - 1)
        lines.extend(render_alerts(alerts, width=cols, remaining_rows=remaining))

    return "\n".join(lines)


def render(lat, lng, location_name="", country_code="", offset_minutes=0, runtime=None, data=None, alerts=None):
    """Build the complete weather dashboard."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    if data is None:
        data = fetch_forecast(lat, lng, runtime)
    if alerts is None:
        alerts = fetch_alerts(lat, lng, country_code)
    return render_from_data(data, alerts, runtime, location_name=location_name, offset_minutes=offset_minutes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    runtime = WeatherRuntime.from_sources()

    if has_flag("--help") or has_flag("-h"):
        print(__doc__.strip())
        return
    if has_flag("--version"):
        from linecast import __version__
        print(f"weather (linecast {__version__})")
        return

    # --search: geocode cities and exit
    search_q = arg_value("--search")
    if search_q:
        _search_locations(search_q)
        return

    # Location: --location flag > WEATHER_LOCATION env > geolocation
    loc_arg = arg_value("--location")
    override = loc_arg or os.environ.get("WEATHER_LOCATION", "").strip()

    if override:
        try:
            parts = override.split(",")
            lat, lng = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            print("Invalid location format. Use: --location LAT,LNG", file=sys.stderr)
            sys.exit(1)
        country_code = ""  # will be detected via reverse geocode
    else:
        lat, lng, country_code = get_location()
        if lat is None:
            print("Could not determine location.", file=sys.stderr)
            sys.exit(1)

    # Fetch data with spinner for perceived responsiveness
    import threading

    done = threading.Event()
    result = {}

    def _fetch():
        name, cc = _reverse_geocode(lat, lng)
        result["name"] = name
        result["country_code"] = cc or country_code
        result["data"] = fetch_forecast(lat, lng, runtime)
        result["alerts"] = fetch_alerts(lat, lng, result["country_code"])
        if not result["name"] and result["data"]:
            result["name"] = _location_from_timezone(result["data"].get("timezone", ""))
        done.set()

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()

    # Animated spinner while waiting
    if sys.stdout.isatty():
        frames = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827"  # braille spinner
        i = 0
        while not done.wait(0.08):
            sys.stdout.write(f"\r {MUTED}{frames[i % len(frames)]} Loading{RESET} ")
            sys.stdout.flush()
            i += 1
        sys.stdout.write("\r\033[K")  # clear spinner line
        sys.stdout.flush()
    else:
        done.wait()

    t.join()
    location_name = result.get("name", "")
    final_country = result.get("country_code", "")
    data = result.get("data")
    alerts = result.get("alerts", [])

    if runtime.live:
        live_loop(
            lambda offset_minutes=0: render(
                lat,
                lng,
                location_name,
                final_country,
                offset_minutes=offset_minutes,
                runtime=runtime,
            ),
            interval=300,
        )
    else:
        print(
            render(
                lat,
                lng,
                location_name,
                final_country,
                runtime=runtime,
                data=data,
                alerts=alerts,
            )
        )


if __name__ == "__main__":
    main()
