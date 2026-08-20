#!/usr/bin/env python3
"""Tides — terminal visualization of tide predictions.

Renders a multi-line graphical display of the tide curve with an
ocean-themed color palette. Shows water level as a braille line graph
with height-colored curve, high/low labels, and current position indicator.

Uses Unicode braille characters with ANSI color for smooth line rendering
(true color when available). Station is auto-detected from IP geolocation
or overridden with TIDE_STATION env var.

Data sources: NOAA (US), CHS/IWLS (Canada), QLD Open Data (Queensland,
Australia), TideCheck (global, optional), and Open-Meteo's global tide
model (keyless fallback for any coastline), selected automatically based
on geolocation. Use --station with a station ID or name to override, and
--nearby to list the closest stations.
For extra station coverage set LINECAST_TIDECHECK_KEY (free at tidecheck.com).

Usage: tides [--print] [--oneline] [--json] [--location PLACE] [--station ID | NAME] [--search QUERY] [--nearby] [--metric] [--lang LANG] [--classic-colors]
"""

import math
import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta

from linecast._braille import build_braille_curve
from linecast._graphics import (
    bg, fg, RESET,
    visible_len, fmt_time_dt,
    get_terminal_size, live_loop,
)
from linecast._theme import (
    best_contrast,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    surface_bg,
    theme_ansi,
    theme_bg,
    theme_fg,
)
from linecast._geo import haversine_nm
from linecast._location import resolve_location
from linecast._runtime import TidesRuntime, install_banner, tides_parser
from linecast._spinner import Spinner
from linecast._marine import fetch_marine, parse_marine_current, format_marine_line
from linecast._tides_i18n import _moon_name, _ts
from linecast._tides_chs import (
    find_nearest_station_chs, fetch_station_metadata_chs,
    fetch_tides_range_chs, fetch_hilo_range_chs, fetch_y_range_chs,
    _fetch_all_stations_chs,
)
from linecast._tides_qld import (
    find_nearest_station_qld, fetch_station_metadata_qld,
    fetch_tides_range_qld, fetch_hilo_range_qld, fetch_y_range_qld,
    _fetch_all_stations_qld,
)
from linecast._tides_tidecheck import (
    is_available as _tidecheck_available,
    find_nearest_station_tidecheck,
    fetch_station_metadata_tidecheck,
    fetch_tides_range_tidecheck,
    fetch_hilo_range_tidecheck,
    fetch_y_range_tidecheck,
    search_stations_tidecheck,
)
from linecast._tides_openmeteo import (
    find_nearest_openmeteo,
    is_openmeteo_station_id as _is_openmeteo_station_id,
    fetch_station_metadata_openmeteo,
    fetch_tides_range_openmeteo,
    fetch_hilo_range_openmeteo,
    fetch_y_range_openmeteo,
)
from linecast._tides_noaa import (
    CACHE_DIR as _NOAA_CACHE_DIR,
    NEAREST_STATION_CACHE_MAX_AGE as _NOAA_NEAREST_STATION_CACHE_MAX_AGE,
    day_to_dt as _day_to_dt,
    fetch_all_stations_noaa as _fetch_all_stations,
    fetch_hilo,
    fetch_hilo_range,
    fetch_station_metadata_noaa as _fetch_station_metadata,
    fetch_tides,
    fetch_tides_range,
    fetch_y_range,
    find_nearest_station,
    synthesize_tides_from_hilo,
)
from linecast._tides_render import (
    build_now_tooltip as _build_now_tooltip,
    build_tide_hover_tooltip as _build_tide_hover_tooltip,
    compute_daylight_window as _compute_daylight_window,
    compute_moon_labels as _compute_moon_labels,
    compute_time_markers as _compute_time_markers,
    interp_height as _interp_height,
    prepare_tide_window as _prepare_tide_window,
    render_day_label_line as _render_day_label_line,
    render_tide_ticks as _render_tide_ticks,
)
from linecast.sunshine import moon_phase

CACHE_DIR = _NOAA_CACHE_DIR
NEAREST_STATION_CACHE_MAX_AGE = _NOAA_NEAREST_STATION_CACHE_MAX_AGE

# ---------------------------------------------------------------------------
# Ocean palette
# ---------------------------------------------------------------------------
CURVE_COLOR = ensure_contrast(best_contrast((theme_ansi[6], theme_ansi[14], theme_fg), minimum=2.0), theme_bg, minimum=2.0)
NOW_LINE_COLOR = ensure_contrast(
    lerp_rgb(best_contrast((theme_ansi[4], theme_ansi[12]), minimum=2.0), theme_bg, 0.30),
    theme_bg,
    minimum=1.8,
)
HOVER_COLOR = ensure_contrast(surface_bg(0.40), theme_bg, minimum=1.5)
DIM_RGB = ensure_contrast(neutral_tone(0.32), theme_bg, minimum=2.0)
MUTED_RGB = ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.4)
TEXT_RGB = ensure_contrast(theme_fg, theme_bg, minimum=4.5)
PILL_BG_RGB = surface_bg(0.08)
PILL_FG_RGB = ensure_contrast(neutral_tone(0.72), PILL_BG_RGB, minimum=3.0)
NOW_PILL_RGB = ensure_contrast(best_contrast((theme_ansi[6], theme_ansi[14]), minimum=2.0), theme_bg, minimum=2.0)
NOW_PILL_TEXT_RGB = best_contrast(((12, 20, 30), theme_bg, theme_fg), background=NOW_PILL_RGB, minimum=4.5)
DIM = fg(*DIM_RGB)
NIGHT_DIM = 0.6 if not is_light_theme() else 0.78

# Nerd Font icons
WAVE_ICON = "\U000F0F85"            # 󰾅

LIVE_WINDOW_HOURS = 24
LIVE_NOW_RATIO = 0.25  # Keep "now" ~25% from the left in live mode.

# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
def _is_chs_station_id(station_id):
    """Check if a station ID is a CHS MongoDB ObjectId (24-char hex)."""
    return (len(station_id) == 24 and
            all(c in '0123456789abcdef' for c in station_id.lower()))


def _is_subordinate_noaa(station_id):
    """True when the NOAA station list marks this station type "S".

    Subordinate stations only publish high/low predictions — asking for the
    6-minute series is a guaranteed error, so callers skip straight to
    synthesis. Unknown stations read as reference (try the real series).
    """
    for s in (_fetch_all_stations() or []):
        if str(s.get("id", "")) == str(station_id):
            return s.get("type") == "S"
    return False


def _noaa_tides_range_with_fallback(station_id, start_date, end_date, station_tz):
    """NOAA 6-minute range; subordinate stations get a synthesized curve.

    The extra day of hi/lo on each side keeps the cosine segments anchored
    right up to the window edges.
    """
    if not _is_subordinate_noaa(station_id):
        preds = fetch_tides_range(station_id, start_date, end_date, station_tz)
        if preds:
            return preds
    hilo = fetch_hilo_range(station_id, start_date - timedelta(days=1),
                            end_date + timedelta(days=1), station_tz)
    return synthesize_tides_from_hilo(hilo)


def _is_qld_lat_lng(lat, lng):
    """Check if coordinates are roughly within Queensland, Australia.

    Queensland spans approximately:
    - Latitude: -10 (Cape York) to -29 (southern border)
    - Longitude: 138 (western border) to 154 (eastern coast)
    """
    return -30 <= lat <= -9 and 137 <= lng <= 155


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


def _live_window_start(now_local, offset_minutes, hours_shown=LIVE_WINDOW_HOURS, now_ratio=LIVE_NOW_RATIO):
    """Start datetime for the live view window.

    Keeps "now" at a fixed fraction of the viewport so the default view
    favors upcoming tide changes while preserving a short recent history.
    """
    past_hours = hours_shown * now_ratio
    return now_local - timedelta(hours=past_hours) + timedelta(minutes=offset_minutes)


# Full names for the state/territory abbreviations NOAA stations carry, so
# queries like "portland maine" match "PORTLAND, ME".
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}


def _find_matching_stations(query, cli_location=None):
    """Match stations across all providers by tokenized name/state search.

    Every whitespace-separated token of *query* must appear somewhere in a
    station's searchable text — name, state abbreviation, full state name,
    or country — so multi-word queries like "portland maine" work.

    Returns a list of dicts {source, id, name, dist_nm}, sorted by distance
    from the current location when one is known (alphabetically otherwise).
    TideCheck results come from a server-side search without coordinates and
    are appended last.

    An empty query matches every station, so callers can list the nearest
    stations by passing "".
    """
    tokens = [t for t in query.lower().split() if t]

    candidates = []

    for s in (_fetch_all_stations() or []):
        name = s.get("name", "")
        state = s.get("state", "")
        haystack = f"{name} {state} {US_STATE_NAMES.get(state.upper(), '')}".lower()
        if all(t in haystack for t in tokens):
            candidates.append({
                "source": "noaa", "id": str(s.get("id", "")),
                "name": f"{name}, {state}" if state else name,
                "lat": s.get("lat"), "lng": s.get("lng"),
            })

    for s in (_fetch_all_stations_chs() or []):
        name = s.get("officialName", "")
        haystack = f"{name} canada".lower()
        if all(t in haystack for t in tokens):
            candidates.append({
                "source": "chs", "id": str(s.get("id", "")), "name": name,
                "lat": s.get("latitude"), "lng": s.get("longitude"),
            })

    for s in (_fetch_all_stations_qld() or []):
        name = s.get("name", "")
        haystack = f"{name} qld queensland australia".lower()
        if all(t in haystack for t in tokens):
            # QLD stations are identified by name, not numeric ID
            candidates.append({
                "source": "qld", "id": name, "name": name,
                "lat": s.get("lat"), "lng": s.get("lng"),
            })

    # TideCheck's server-side search returns coordinates too, so its hits
    # join the pool before the distance sort like any other provider's.
    if _tidecheck_available() and tokens:
        for s in search_stations_tidecheck(query):
            candidates.append({
                "source": "tidecheck", "id": str(s.get("id", "")),
                "name": s.get("name", ""),
                "lat": s.get("lat"), "lng": s.get("lng"),
            })

    here_lat, here_lng, _country = resolve_location(cli_location)
    for c in candidates:
        try:
            c["dist_nm"] = haversine_nm(
                here_lat, here_lng, float(c.pop("lat")), float(c.pop("lng")))
        except (TypeError, ValueError):
            c.pop("lat", None)
            c.pop("lng", None)
            c["dist_nm"] = None
    if here_lat is not None:
        candidates.sort(
            key=lambda c: (c["dist_nm"] is None, c["dist_nm"] or 0.0, c["name"]))
    else:
        candidates.sort(key=lambda c: c["name"])

    return candidates


def _search_stations(query, metric=False, limit=20, cli_location=None):
    """Print stations matching *query* (all stations when empty), nearest
    first, and exit."""
    nearby = not query.strip()
    matches = _find_matching_stations(query, cli_location=cli_location)

    if not matches:
        if nearby:
            print("Could not fetch any station lists (offline?).")
        else:
            print(f"No stations matching \"{query}\". "
                  "Try `tides --nearby` to list the nearest stations.")
        sys.exit(0)

    if nearby:
        matches = [c for c in matches if c["dist_nm"] is not None] or matches
        print("Nearest tide stations:")

    source_tags = {"chs": " (Canada)", "qld": " (QLD, Australia)",
                   "tidecheck": " (TideCheck)"}
    for c in matches[:limit]:
        left = c["name"] if c["id"] == c["name"] else f"{c['id']}  {c['name']}"
        dist = ""
        if c["dist_nm"] is not None:
            if metric:
                dist = f" — {c['dist_nm'] * 1.852:.0f} km"
            else:
                dist = f" — {c['dist_nm'] * 1.15078:.0f} mi"
        print(f"  {left}{dist}{source_tags.get(c['source'], '')}")

    if len(matches) > limit:
        print(f"  ... and {len(matches) - limit} more")
    print("\nUse `tides --station <id or name>` to view one.")


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
    dim_color = DIM_RGB

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
    dim_color = DIM_RGB  # match x-axis tick color (DIM)
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
# Header line (day names at midnight boundaries)
# ---------------------------------------------------------------------------
def _render_header_line(cols, station_name, runtime, offset_minutes=0):
    """Render the top line with pill-styled station name."""
    # Title-case the city name but preserve short uppercase tokens (state/province codes)
    if station_name:
        parts = station_name.split(",")
        parts = [p.strip().title() if len(p.strip()) > 2 else p.strip().upper()
                 for p in parts]
        name = ", ".join(parts)
    else:
        name = ""

    # Station name pill (left)
    if name:
        pbg = bg(*PILL_BG_RGB)
        pfg = fg(*PILL_FG_RGB)
        pedge = fg(*PILL_BG_RGB)
        pill = f"{pedge}\u2590{pbg}{pfg} {name} {RESET}{pedge}\u258c{RESET}"
        pill_w = len(name) + 4  # ▐ + space + name + space + ▌
    else:
        pill = ""
        pill_w = 0

    # Moon phase (right-aligned)
    idx, _, moon_icon = moon_phase(datetime.now(timezone.utc), runtime)
    phase_name = _moon_name(idx, runtime)
    moon_color = fg(*MUTED_RGB)
    moon_str = f"{moon_color}{moon_icon} {DIM}{phase_name}{RESET}"
    moon_w = len(moon_icon) + 1 + len(phase_name)

    # "Space to return" hint (right, only when scrolled)
    if offset_minutes:
        hint_text = _ts("space_to_now", runtime)
        hint = f"{DIM}{hint_text}{RESET}"
        right_w = len(hint_text)
        padding = max(1, cols - 1 - pill_w - right_w)
        return f"{pill}{' ' * padding}{hint}"

    padding = max(1, cols - 1 - pill_w - moon_w)
    return f"{pill}{' ' * padding}{moon_str}"


# ---------------------------------------------------------------------------
# Info line
# ---------------------------------------------------------------------------
def _info_line(window, now_height, now_dt, width, offset_minutes, rising, runtime):
    """Iconic pill-shaped tide info bar."""
    text = fg(*TEXT_RGB)
    dim = fg(*DIM_RGB)
    sep = "  "

    pill_rgb = PILL_BG_RGB
    now_rgb = NOW_PILL_RGB
    now_text = fg(*NOW_PILL_TEXT_RGB)

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
           predictions=None, hilo=None, y_range=None, marine_data=None):
    """Build the complete multi-line tide display.

    When predictions/hilo are provided (live mode), renders a sliding 24h
    window with hover and scroll support.  Otherwise fetches the current
    day's data for a static view.

    y_range: optional (min_ft, max_ft) to fix the y-axis scale (e.g. from
             30-day hilo data) so the curve doesn't rescale as you scroll.
    marine_data: optional dict from fetch_marine() for wave/swell conditions.
    """
    if runtime is None:
        runtime = TidesRuntime.from_sources()

    now_local = _station_now(station_meta)
    station_tz = _station_tzinfo(station_meta)
    cols, rows = get_terminal_size()
    graph_w = max(30, cols - 2)

    # --- build the window ---
    if predictions is not None:
        # Live mode: keep "now" near the left so most of the chart looks ahead.
        start_dt = _live_window_start(
            now_local,
            offset_minutes=offset_minutes,
            hours_shown=LIVE_WINDOW_HOURS,
        )
        window = _prepare_tide_window(
            predictions, hilo or [], start_dt, hours_shown=LIVE_WINDOW_HOURS,
        )
    else:
        # Static mode: show current calendar day
        date = (now_local + timedelta(minutes=offset_minutes)).date()
        subordinate = _is_subordinate_noaa(station_id)
        day_preds = None if subordinate else fetch_tides(station_id, date)
        day_hilo = fetch_hilo(station_id, date) or []
        preds_dt = []
        for hour, height in (day_preds or []):
            dt = _day_to_dt(hour, date, station_tz)
            if dt is not None:
                preds_dt.append((dt, height))
        hilo_dt = []
        for hour, height, typ in day_hilo:
            dt = _day_to_dt(hour, date, station_tz)
            if dt is not None:
                hilo_dt.append((dt, height, typ))
        if not preds_dt:
            # No 6-minute series (subordinate station): synthesize the curve
            # from hi/lo, pulling the neighbouring days' extremes so the
            # cosine segments cover the whole calendar-day window.
            extremes = list(hilo_dt)
            for day in (date - timedelta(days=1), date + timedelta(days=1)):
                for hour, height, typ in (fetch_hilo(station_id, day) or []):
                    dt = _day_to_dt(hour, day, station_tz)
                    if dt is not None:
                        extremes.append((dt, height, typ))
            preds_dt = synthesize_tides_from_hilo(extremes)
        if not preds_dt:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)
        day_start = datetime(date.year, date.month, date.day)
        if station_tz is not None:
            day_start = day_start.replace(tzinfo=station_tz)
        window = _prepare_tide_window(preds_dt, hilo_dt, day_start, hours_shown=LIVE_WINDOW_HOURS)

    w_start = window["start"]
    w_total = window["total_hours"]
    w_preds = window["predictions"]
    w_secs = w_total * 3600

    # --- dimensions (header + day_labels + braille + ticks + extras) ---
    extra = 0
    if marine_data is not None:
        extra += 1
    if install_banner():
        extra += 1
    n_braille_rows = max(2, rows - ((3 + extra) if fullscreen else 7))

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
    moon_labels = _compute_moon_labels(w_start, w_total, graph_w, station_meta, runtime)

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

    # --- now info for header ---
    now_info = None
    if now_col is not None:
        now_height = _interp_height(now_local, w_preds)
        h_display = runtime.convert_height(now_height)
        time_str = fmt_time_dt(now_local, use_24h=runtime.use_24h)
        now_info = (time_str, h_display, runtime.height_unit)

    # --- assemble output ---
    lines = []

    # Header with pill-styled station name
    lines.append(_render_header_line(
        cols, station_name, runtime, offset_minutes=offset_minutes,
    ))

    # Day labels on their own row
    lines.append(_render_day_label_line(midnight_day_names, graph_w, moon_labels=moon_labels))

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

    # Marine conditions line (optional)
    if marine_data is not None:
        try:
            marine = parse_marine_current(marine_data, now_local)
            marine_str = format_marine_line(marine, runtime, width=cols)
            if marine_str:
                wave_icon = "\U0001F30A" if runtime.emoji else WAVE_ICON
                muted = fg(*MUTED_RGB)
                dim = fg(*DIM_RGB)
                lines.append(f" {muted}{wave_icon} {dim}{marine_str}{RESET}")
        except Exception:
            pass  # Marine data is optional; never crash

    hint = install_banner()
    if hint:
        lines.append(hint)

    output = "\n".join(lines)

    # --- cursor-positioned overlays (live mode only: they ride live_loop's
    # \x00 channel and use absolute cursor addressing, neither of which
    # belongs in static/piped output) ---
    if fullscreen:
        overlay_parts = []

        # Hover tooltip (takes priority over now tooltip)
        if mouse_pos and hover_graph_col is not None:
            tooltip = _build_tide_hover_tooltip(
                window, hover_graph_col, mouse_pos[1],
                chart_start, chart_end, cols, rows, graph_w, runtime,
            )
            if tooltip:
                overlay_parts.append(tooltip)
        elif now_col is not None and now_info is not None:
            now_tip = _build_now_tooltip(now_col, now_info, chart_start, cols, graph_w)
            if now_tip:
                overlay_parts.append(now_tip)

        if overlay_parts:
            output += "\x00" + "".join(overlay_parts)

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = tides_parser().parse_args()
    runtime = TidesRuntime.from_sources(namespace=args)

    # --search / --nearby: list stations and exit.  A bare `--search`
    # behaves like --nearby (empty query = nearest stations).
    if args.nearby or args.search is not None:
        query = args.search or ""
        _search_stations(query, metric=args.metric,
                         limit=15 if not query.strip() else 20,
                         cli_location=args.location)
        return

    # everything from here to the first paint may block on the network
    # (station lookup, metadata, two weeks of predictions) — spin
    # (suppressed for --json: stdout must carry nothing but the payload)
    spin = Spinner()
    if not runtime.json_mode:
        spin.start()
    try:
        # Station: --station flag > TIDE_STATION env var > geolocation
        override = args.station or os.environ.get("TIDE_STATION", "").strip()

        source = "noaa"  # "noaa", "chs", "qld", "tidecheck", or "openmeteo"
        if override:
            if _is_openmeteo_station_id(override):
                source = "openmeteo"
                station_id = override
                station_name = "Tide model"
            elif _is_chs_station_id(override):
                source = "chs"
                station_id = override
                station_name = f"Station {override[:8]}"
            elif override.isdigit():
                station_id = override
                station_name = f"Station {override}"
                for s in (_fetch_all_stations() or []):
                    if str(s.get("id", "")) == override:
                        name = s.get("name", "")
                        state = s.get("state", "")
                        station_name = f"{name}, {state}" if state else name
                        break
            else:
                # Text query — pick the closest matching station (first match
                # when the current location is unknown)
                matches = _find_matching_stations(override,
                                                  cli_location=args.location)
                if not matches:
                    print(f'No stations matching "{override}". '
                          "Try `tides --nearby` to list the nearest stations.",
                          file=sys.stderr)
                    sys.exit(1)
                best = matches[0]
                source = best["source"]
                station_id = best["id"]
                station_name = best["name"] or f"Station {station_id[:8]}"
        else:
            # need_country: provider routing below (CHS for Canada, QLD for
            # Queensland) hinges on the country of the target location.
            lat, lng, country_code = resolve_location(
                args.location, lang=runtime.lang, need_country=True)
            if lat is None:
                print("Could not determine location for tide station lookup.", file=sys.stderr)
                sys.exit(1)

            if country_code == "CA":
                source = "chs"
                station_id, station_name = find_nearest_station_chs(lat, lng)
            elif country_code == "AU" and _is_qld_lat_lng(lat, lng):
                source = "qld"
                station_id, station_name = find_nearest_station_qld(lat, lng)
            else:
                station_id, station_name = find_nearest_station(lat, lng)

            # Border/outage fallback: a NOAA station may be in range even
            # when the regional provider found nothing (e.g. Victoria BC).
            if station_id is None and source != "noaa":
                station_id, station_name = find_nearest_station(lat, lng)
                if station_id is not None:
                    source = "noaa"

            # Fallback to TideCheck for locations outside US/Canada coverage
            if station_id is None and _tidecheck_available():
                source = "tidecheck"
                station_id, station_name = find_nearest_station_tidecheck(lat, lng)

            # Last resort: Open-Meteo's global tide model — keyless, works
            # on nearly any coastline.  Labeled with the location name since
            # there is no station.
            if station_id is None:
                station_id, _ = find_nearest_openmeteo(lat, lng)
                if station_id is not None:
                    source = "openmeteo"
                    try:
                        from linecast._sunshine_json import _location_label
                        station_name = f"{_location_label(lat, lng)} (model)"
                    except Exception:
                        station_name = "Tide model"

            if station_id is None and runtime.json_mode:
                # No station in range: emit the payload shape anyway, with
                # station/events/series empty-or-null, and exit cleanly.
                import json as _json
                from linecast._sunshine_json import _location_label
                from linecast._tides_json import build_payload
                payload = build_payload(
                    None, runtime, datetime.now().astimezone(), [], [],
                    location=_location_label(lat, lng),
                )
                print(_json.dumps(payload, ensure_ascii=False))
                return

            if station_id is None:
                hint = ("No tide station within 100nm, and the global tide "
                        "model has no coverage here (inland?).\n"
                        "  Try `tides --nearby` to list the nearest stations, "
                        "or `tides --station <id or name>`.")
                if not _tidecheck_available():
                    hint += ("\n  For more station coverage, set "
                             "LINECAST_TIDECHECK_KEY (free at tidecheck.com).")
                print(hint, file=sys.stderr)
                sys.exit(1)

        _metadata_fetchers = {
            "chs": fetch_station_metadata_chs,
            "qld": fetch_station_metadata_qld,
            "tidecheck": fetch_station_metadata_tidecheck,
            "openmeteo": fetch_station_metadata_openmeteo,
        }
        station_meta = _metadata_fetchers.get(source, _fetch_station_metadata)(station_id)
        if station_meta:
            meta_name = station_meta.get("name", "")
            meta_state = station_meta.get("state", "")
            if meta_name:
                station_name = f"{meta_name}, {meta_state}" if meta_state else meta_name

        station_tz = _station_tzinfo(station_meta)
        now_local = _station_now(station_meta)
        today = now_local.date()

        # Provider-specific range fetchers, shared by every mode below
        _range_fetchers = {
            "chs": (fetch_tides_range_chs, fetch_hilo_range_chs),
            "qld": (fetch_tides_range_qld, fetch_hilo_range_qld),
            "tidecheck": (fetch_tides_range_tidecheck,
                          fetch_hilo_range_tidecheck),
            "openmeteo": (fetch_tides_range_openmeteo,
                          fetch_hilo_range_openmeteo),
        }
        _fetch_tides_range, _fetch_hilo_range = _range_fetchers.get(
            source, (_noaa_tides_range_with_fallback, fetch_hilo_range))

        if runtime.json_mode:
            import json as _json
            from linecast._tides_json import build_payload
            preds = _fetch_tides_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            hilo_data = _fetch_hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            tz_name = (getattr(station_tz, "key", None)
                       or (now_local.tzname() if now_local.tzinfo else None))
            payload = build_payload(
                station_name, runtime, now_local, preds, hilo_data,
                station_id=station_id, source=source, tz_name=tz_name,
            )
            print(_json.dumps(payload, ensure_ascii=False))
            return

        if runtime.oneline:
            from linecast._oneline import tides_oneline
            hilo_data = _fetch_hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=1), station_tz)
            line = tides_oneline(station_name, hilo_data or [], now_local,
                                 runtime)
            spin.stop()
            print(line)
            return

        # Fixed y-axis range from historical hilo data
        _y_range_fetchers = {
            "chs": fetch_y_range_chs,
            "qld": fetch_y_range_qld,
            "tidecheck": fetch_y_range_tidecheck,
            "openmeteo": fetch_y_range_openmeteo,
        }
        if source in _y_range_fetchers:
            y_range = _y_range_fetchers[source](station_id, today, station_tz)
        else:
            y_range = fetch_y_range(station_id, today)

        # Fetch marine/wave conditions (optional, may return None)
        marine_data = None
        try:
            _marine_lat = station_meta.get("lat") if station_meta else None
            _marine_lng = station_meta.get("lng") if station_meta else None
            if _marine_lat is not None and _marine_lng is not None:
                marine_data = fetch_marine(float(_marine_lat), float(_marine_lng))
        except Exception:
            pass  # Marine data is optional; never crash the tides view

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
                current_now = _station_now(station_meta)
                view_start = _live_window_start(
                    current_now,
                    offset_minutes=offset_minutes,
                    hours_shown=LIVE_WINDOW_HOURS,
                )
                view_end = view_start + timedelta(hours=LIVE_WINDOW_HOURS)
                view_start_date = view_start.date()
                view_end_date = view_end.date()

                need_expand = False
                new_start, new_end = fetched_range[0], fetched_range[1]

                if view_start_date - timedelta(days=2) < fetched_range[0]:
                    new_start = view_start_date - timedelta(days=7)
                    need_expand = True
                if view_end_date + timedelta(days=2) > fetched_range[1]:
                    new_end = view_end_date + timedelta(days=7)
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
                    marine_data=marine_data,
                ), {}

            spin.stop()
            # Larger step makes wheel/arrow scrubbing practical for multi-day browsing.
            live_loop(_render, interval=60, mouse=True, scroll_step=30)
        else:
            if source != "noaa":
                preds = _fetch_tides_range(
                    station_id, today - timedelta(days=1),
                    today + timedelta(days=1), station_tz)
                hilo_data = _fetch_hilo_range(
                    station_id, today - timedelta(days=1),
                    today + timedelta(days=1), station_tz)
                if not preds:
                    print(f"Could not fetch tide data for station {station_id}.",
                          file=sys.stderr)
                    sys.exit(1)
                out = render(
                    station_id,
                    station_name,
                    station_meta=station_meta,
                    runtime=runtime,
                    predictions=preds,
                    hilo=hilo_data,
                    y_range=y_range,
                    marine_data=marine_data,
                )
            else:
                out = render(
                    station_id,
                    station_name,
                    station_meta=station_meta,
                    runtime=runtime,
                    y_range=y_range,
                    marine_data=marine_data,
                )
            spin.stop()
            print(out)
    finally:
        spin.stop()


if __name__ == "__main__":
    main()
