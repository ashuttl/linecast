#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, comparative weather line, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts are sourced from NWS (US) and Environment Canada (CA).

Usage: weather [--live] [--location LAT,LNG] [--search CITY] [--emoji]
"""

import json, os, sys, time as _time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from linecast._graphics import (
    fg, bg, RESET, BOLD, interp_stops, visible_len, get_terminal_size,
    live_loop,
)
from linecast._cache import (
    CACHE_ROOT, read_cache, read_stale, write_cache, location_cache_key,
)
from linecast._location import get_location

CACHE_DIR = CACHE_ROOT / "weather"
USER_AGENT = "linecast/1.0"

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

def _use_emoji():
    """Check if emoji mode is requested (--emoji flag or LINECAST_ICONS=emoji)."""
    return "--emoji" in sys.argv or os.environ.get("LINECAST_ICONS", "").lower() == "emoji"

WMO_ICONS = _WMO_ICONS_EMOJI if _use_emoji() else _WMO_ICONS_NERD
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
# Argument parsing
# ---------------------------------------------------------------------------
def _parse_arg(flag):
    """Return the value after --flag, or None if not present."""
    for i, a in enumerate(sys.argv[1:], 1):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(f"{flag}="):
            return a.split("=", 1)[1]
    return None


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
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
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
def fetch_forecast(lat, lng):
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h."""
    cache_file = CACHE_DIR / f"forecast_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, 3600)
    if cached:
        return cached

    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lng}"
            "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
            "wind_speed_10m,wind_gusts_10m,weather_code"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,weather_code,wind_speed_10m_max,wind_gusts_10m_max"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
            "&timezone=auto&forecast_days=7&past_days=1"
            "&current=temperature_2m,apparent_temperature,weather_code,"
            "wind_speed_10m,wind_gusts_10m"
        )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
    except Exception:
        stale = read_stale(cache_file)
        if stale:
            return stale
        return None

    write_cache(cache_file, data)
    return data


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
    cached = read_cache(cache_file, 900)
    if cached is not None:
        return cached

    try:
        url = f"https://api.weather.gov/alerts/active?point={lat},{lng}"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/geo+json",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
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
    except Exception:
        stale = read_stale(cache_file)
        if stale is not None:
            return stale
        return []


def _fetch_alerts_eccc(lat, lng):
    """Fetch active Environment Canada alerts (CA). Cached 15min.

    Uses the OGC API at api.weather.gc.ca with bbox query.
    """
    cache_file = CACHE_DIR / f"alerts_ca_{location_cache_key(lat, lng)}.json"
    cached = read_cache(cache_file, 900)
    if cached is not None:
        return cached

    try:
        # bbox: lng-0.5, lat-0.5, lng+0.5, lat+0.5 (~50km radius)
        bbox = f"{lng - 0.5},{lat - 0.5},{lng + 0.5},{lat + 0.5}"
        url = (
            f"https://api.weather.gc.ca/collections/weather-alerts/items"
            f"?f=json&bbox={bbox}&lang=en&limit=20"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
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
    except Exception:
        stale = read_stale(cache_file)
        if stale is not None:
            return stale
        return []


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
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
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
def _temp_color(temp_f):
    return interp_stops(TEMP_COLORS, temp_f)


def _colored_temp(temp_f, suffix=""):
    r, g, b = _temp_color(temp_f)
    return f"{fg(r, g, b)}{temp_f:.0f}{suffix}"


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


# ---------------------------------------------------------------------------
# Comparative weather line
# ---------------------------------------------------------------------------
def _comparative_line(daily, now):
    """Natural language comparing today vs yesterday/tomorrow."""
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
    if abs_diff < 3:
        comparison = f"about the same as {ref_day}"
    elif abs_diff < 8:
        word = "warmer" if diff > 0 else "cooler"
        comparison = f"a bit {word} than {ref_day}"
    elif abs_diff < 15:
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


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_header(data, width, location_name=""):
    """Current conditions header line."""
    current = data.get("current", {})
    temp = current.get("temperature_2m", 0)
    feels = current.get("apparent_temperature", 0)
    wmo = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    gusts = current.get("wind_gusts_10m", 0)

    icon = WMO_ICONS.get(wmo, WMO_ICONS[0])
    name = WMO_NAMES.get(wmo, "")

    left = f" {TEXT}{icon} {name}  {_colored_temp(temp, '°F')}  {MUTED}feels {_colored_temp(feels, '°F')}"

    right_parts = []
    if wind > 10 or gusts > 20:
        parts = [f"Wind {wind:.0f}mph"]
        if gusts > 20:
            parts.append(f"gusts {gusts:.0f}mph")
        right_parts.append(f"{WIND_COLOR}{'  '.join(parts)}")
    if location_name:
        right_parts.append(f"{MUTED}{location_name}")

    right = f"  {MUTED}\u00b7  ".join(right_parts) if right_parts else ""

    if right:
        pad = width - visible_len(left) - visible_len(right) - 2
        return f"{left}{' ' * max(1, pad)}{right} {RESET}"
    return f"{left}{RESET}"


def render_hourly(data, width, n_braille_rows=2, now=None):
    """Hourly forecast: braille temperature curve + precipitation sparkline."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip_prob = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])

    if not times or not temps:
        return []

    if now is None:
        now = _local_now_for_data(data)

    # Parse all hourly timestamps
    parsed = []
    for i, t in enumerate(times):
        try:
            parsed.append((i, datetime.fromisoformat(t)))
        except Exception:
            continue

    # Find start: current hour (rounded down)
    current_hour_dt = now.replace(minute=0, second=0, microsecond=0)
    start_idx = 0
    for i, dt in parsed:
        if dt >= current_hour_dt:
            start_idx = i
            break

    # Responsive time window: wider terminal → more hours (24–48h)
    graph_w = max(10, width - 2)
    hours_shown = max(24, min(48, graph_w // 2))

    end_time = current_hour_dt + timedelta(hours=hours_shown)
    end_idx = start_idx
    for i, dt in parsed:
        if i >= start_idx and dt <= end_time:
            end_idx = i

    window_temps = temps[start_idx:end_idx + 1]
    window_precip = precip_prob[start_idx:end_idx + 1] if precip_prob else []
    window_codes = weather_codes[start_idx:end_idx + 1] if weather_codes else []
    window_dts = [dt for i, dt in parsed if start_idx <= i <= end_idx]

    if len(window_temps) < 2:
        return []

    # Chart range (actual visible min/max, not daily)
    chart_lo = min(window_temps)
    chart_hi = max(window_temps)

    # Timeline parameters (needed for midnight markers and tick labels)
    total_hours = 24
    if window_dts and len(window_dts) > 1:
        total_secs = (window_dts[-1] - window_dts[0]).total_seconds()
        total_hours = total_secs / 3600 if total_secs > 0 else 24

    # Midnight column positions for vertical markers
    midnight_cols = set()
    if window_dts:
        for h_off in range(int(total_hours) + 1):
            dt = window_dts[0] + timedelta(hours=h_off)
            if dt.hour == 0:
                x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
                if 0 < x < graph_w - 1:
                    midnight_cols.add(x)

    # Per-column temperatures for peak/valley labels
    col_temps = []
    for x in range(graph_w):
        t = x / max(1, graph_w - 1) * max(0, len(window_temps) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(window_temps) - 1)
        frac = t - lo_i
        col_temps.append(window_temps[lo_i] + (window_temps[hi_i] - window_temps[lo_i]) * frac)

    # Detect peaks and valleys for annotation
    extrema = []  # (x, temp, is_peak)
    if len(col_temps) >= 5:
        min_gap = max(8, graph_w // 15)
        for i in range(2, len(col_temps) - 2):
            local = col_temps[max(0, i - 3):i + 4]
            is_peak = col_temps[i] >= max(local) and (
                col_temps[i] > col_temps[i - 1] or col_temps[i] > col_temps[i + 1])
            is_valley = col_temps[i] <= min(local) and (
                col_temps[i] < col_temps[i - 1] or col_temps[i] < col_temps[i + 1])
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

        # Ensure global min and max are always annotated
        global_max_x = max(range(len(col_temps)), key=lambda i: col_temps[i])
        global_min_x = min(range(len(col_temps)), key=lambda i: col_temps[i])
        for gx, is_peak in [(global_max_x, True), (global_min_x, False)]:
            if not any(abs(gx - ex) < min_gap and p == is_peak for ex, _, p in extrema):
                extrema.append((gx, col_temps[gx], is_peak))

    lines = []

    # Compute day names at midnight boundaries for the header line
    midnight_day_names = {}  # col -> day name (e.g. "Friday")
    if window_dts:
        for h_off in range(int(total_hours) + 1):
            dt = window_dts[0] + timedelta(hours=h_off)
            if dt.hour == 0:
                x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
                if 0 < x < graph_w - 1:
                    midnight_day_names[x] = dt.strftime("%A")

    # "Today" label with chart temperature range
    today_left = f" {TEXT}Today"
    today_right = f"{_colored_temp(chart_lo, '°')} {TEXT}\u2192 {_colored_temp(chart_hi, '°F')}"
    # Insert day names at midnight column positions
    if midnight_day_names:
        # Build padded label area between "Today" and the temp range
        label_start = visible_len(today_left)
        right_len = visible_len(today_right) + 2
        avail = width - right_len
        mid_section = [" "] * max(0, avail - label_start)
        for col, name in sorted(midnight_day_names.items()):
            pos = col + 1 - label_start  # +1 for leading margin
            if pos >= 0 and pos + len(name) <= len(mid_section):
                for j, c in enumerate(name):
                    mid_section[pos + j] = c
        mid_str = "".join(mid_section)
        pad = width - visible_len(today_left) - visible_len(mid_str) - visible_len(today_right) - 2
        lines.append(f"{today_left}{TEXT}{mid_str}{' ' * max(0, pad)}{today_right} {RESET}")
    else:
        pad = width - visible_len(today_left) - visible_len(today_right) - 2
        lines.append(f"{today_left}{' ' * max(1, pad)}{today_right} {RESET}")

    # Peak annotations (above braille curve)
    peaks = sorted([(x, t) for x, t, p in extrema if p])
    if peaks:
        segments, cursor = [], 0
        for x, temp in peaks:
            label = f"{temp:.0f}\u00b0"
            pos = max(cursor, x + 1 - len(label) // 2)
            if pos + len(label) > graph_w + 1:
                continue
            if pos > cursor:
                segments.append((" " * (pos - cursor), None))
            segments.append((label, temp))
            cursor = pos + len(label)
        if segments:
            line = ""
            for text, temp in segments:
                if temp is not None:
                    r, g, b = _temp_color(temp)
                    line += f"{fg(r, g, b)}{text}"
                else:
                    line += text
            lines.append(f"{line}{RESET}")

    # Braille temperature curve with midnight markers
    braille_rows = _build_braille_curve(window_temps, graph_w, n_braille_rows)
    for row in braille_rows:
        line = " "
        for ci, (ch, temp) in enumerate(row):
            if ci in midnight_cols and ch == '\u2800':
                # Empty cell on midnight col: show dim separator line
                line += f"{DIM}\u2502"
            else:
                r, g, b = _temp_color(temp)
                line += f"{fg(r, g, b)}{ch}"
        lines.append(f"{line}{RESET}")

    # Valley annotations (below braille curve)
    valleys = sorted([(x, t) for x, t, p in extrema if not p])
    if valleys:
        segments, cursor = [], 0
        for x, temp in valleys:
            label = f"{temp:.0f}\u00b0"
            pos = max(cursor, x + 1 - len(label) // 2)
            if pos + len(label) > graph_w + 1:
                continue
            if pos > cursor:
                segments.append((" " * (pos - cursor), None))
            segments.append((label, temp))
            cursor = pos + len(label)
        if segments:
            line = ""
            for text, temp in segments:
                if temp is not None:
                    r, g, b = _temp_color(temp)
                    line += f"{fg(r, g, b)}{text}"
                else:
                    line += text
            lines.append(f"{line}{RESET}")

    # Tick marks + hour labels
    if window_dts:
        # Adaptive label interval based on available width
        if graph_w < 40:
            interval = 6
        elif graph_w < 80:
            interval = 4
        elif graph_w < 140:
            interval = 3
        else:
            interval = 2

        # Build label list as (x, text, is_midnight)
        label_items = []
        for h_off in range(0, int(total_hours) + 1, interval):
            x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
            dt = window_dts[0] + timedelta(hours=h_off)
            label_items.append((x, _fmt_hour(dt.hour), dt.hour == 0))

        # Render with tick marks — │ for midnight, ╵ otherwise
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

        lines.append(f" {DIM}{''.join(canvas)}{RESET}")

    # Precipitation sparkline with type-based colors
    if window_precip and max(window_precip, default=0) > 5:
        precip_chars = []
        for x in range(graph_w):
            t = x / max(1, graph_w - 1) * max(0, len(window_precip) - 1)
            lo_i = int(t)
            hi_i = min(lo_i + 1, len(window_precip) - 1)
            frac = t - lo_i
            p = window_precip[lo_i] + (window_precip[hi_i] - window_precip[lo_i]) * frac

            if p > 5:
                # Determine WMO code at this position for color
                code_t = x / max(1, graph_w - 1) * max(0, len(window_codes) - 1)
                code_i = max(0, min(len(window_codes) - 1, int(round(code_t))))
                wmo = window_codes[code_i] if window_codes else 0
                color = _precip_color(wmo)
                idx = max(0, min(7, int(p / 100 * 7.99)))
                precip_chars.append(f"{color}{SPARKLINE[idx]}")
            else:
                precip_chars.append(" ")
        lines.append(f" {''.join(precip_chars)}{RESET}")

    return lines


def render_daily(data, width):
    """Daily forecast with temperature range bars."""
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

    # Bar width: adaptive based on terminal width
    bar_w = max(10, min(30, width - 35))

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
        icon = WMO_ICONS.get(wmo, WMO_ICONS[0])
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

        lo_r, lo_g, lo_b = _temp_color(lo)
        hi_r, hi_g, hi_b = _temp_color(hi)

        cells = []
        for bx in range(bar_w):
            if lo_pos <= bx <= hi_pos:
                t_frac = (bx - lo_pos) / max(1, hi_pos - lo_pos)
                temp_at = lo + (hi - lo) * t_frac
                r, g, b = _temp_color(temp_at)
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

        # Build the line
        line = f"  {TEXT}{day_name}  {icon}  {bar}"

        # Precipitation (only when meaningful) — colored by type
        if precip >= 0.05 or prob > 25:
            ptype = _precip_type(wmo)
            pcolor = _precip_color(wmo)
            if precip >= 0.05:
                line += f"  {pcolor}{ptype} {precip:.1f}in"
            if prob > 25:
                line += f"  {pcolor}{prob:.0f}%"

        # Wind (only when gusty)
        if wind > 15:
            line += f"  {WIND_COLOR}Wind {wind:.0f}mph"

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
    cols, _ = get_terminal_size()
    width = cols
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


def render(lat, lng, location_name="", country_code="", offset_minutes=0):
    """Build the complete weather dashboard."""
    data = fetch_forecast(lat, lng)
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}"

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)

    # Adaptive braille chart height based on terminal height
    if rows >= 40:
        n_braille = 4
    elif rows >= 25:
        n_braille = 3
    else:
        n_braille = 2

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name))
    lines.append("")

    # Hourly
    lines.extend(render_hourly(data, cols, n_braille, now=now_local))

    # Comparative line
    comp = _comparative_line(data.get("daily", {}), now_local)
    if comp:
        lines.append(comp)

    # Precipitation forecast
    precip = _precipitation_line(data.get("hourly", {}), now_local)
    if precip:
        lines.append(precip)

    lines.append("")

    # Daily
    lines.extend(render_daily(data, cols))

    # Alerts
    alerts = fetch_alerts(lat, lng, country_code)
    if alerts:
        lines.append("")
        remaining = max(4, rows - len(lines) - 1)
        lines.extend(render_alerts(alerts, remaining_rows=remaining))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__.strip())
        return
    if "--version" in sys.argv:
        from linecast import __version__
        print(f"weather (linecast {__version__})")
        return

    # --search: geocode cities and exit
    search_q = _parse_arg("--search")
    if search_q:
        _search_locations(search_q)
        return

    # Location: --location flag > WEATHER_LOCATION env > geolocation
    loc_arg = _parse_arg("--location")
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
        result["data"] = fetch_forecast(lat, lng)
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

    if "--live" in sys.argv:
        live_loop(lambda offset_minutes=0: render(lat, lng, location_name, final_country, offset_minutes=offset_minutes), interval=300)
    else:
        print(render(lat, lng, location_name, final_country))


if __name__ == "__main__":
    main()
