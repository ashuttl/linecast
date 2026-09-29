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

Usage: tides [--print] [--oneline] [--json] [--location PLACE] [--station ID | NAME]
             [--search QUERY] [--nearby] [--metric] [--lang LANG] [--classic-colors]
"""

import math
import os
import sys
import threading
import time as _t
from datetime import datetime, timezone, timedelta

from linecast.terminal.braille import BLANK, build_braille_curve
from linecast.terminal.color import bg, fg, RESET
from linecast.terminal.textwidth import visible_len
from linecast.terminal.framebuffer import get_terminal_size
from linecast._timefmt import fmt_time_dt
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast._i18n import fmt_decimal
from linecast._location import country_for_defaults, resolve_location
from linecast._plaintext import plain_text
from linecast._runtime import TidesRuntime, current_runtime, install_banner, set_current
from linecast._parsers import tides_parser
from linecast._log import log_failure
from linecast.terminal.spinner import Spinner
from linecast.tides.marine import parse_marine_current, format_marine_line
from linecast.tides.common import sweep_legacy_cache
from linecast.tides.i18n import _ts
from linecast.weather.location_menu import LocationMenu
from linecast._i18n import moon_name
from linecast.tides.providers import NOAA, PROVIDERS, TIDECHECK, provider_for_id
from linecast.tides.stations import (
    _fetch_station, _find_matching_stations, _search_stations, _station_details,
    _station_for_location, _station_now, _station_tzinfo,
)
from linecast.tides.chart import (
    build_now_tooltip,
    build_tide_hover_tooltip,
    compute_daylight_window,
    compute_moon_labels,
    compute_time_markers,
    interp_height,
    prepare_tide_window,
    render_day_label_line,
    render_tide_ticks,
)
from linecast.moon.phase import moon_phase

from linecast.tides.palette import (
    CURVE_COLOR, DIM, DIM_RGB, HOVER_COLOR, MUTED_RGB, NIGHT_DIM, NOW_LINE_COLOR,
    NOW_PILL_RGB, NOW_PILL_TEXT_RGB, PILL_BG_RGB, PILL_FG_RGB, TEXT_RGB,
)

_theme.track_imports(globals(), "linecast.tides.palette")

LIVE_WINDOW_HOURS = 24
LIVE_NOW_RATIO = 0.25  # Keep "now" ~25% from the left in live mode.


def _live_window_start(now_local, offset_minutes, hours_shown=LIVE_WINDOW_HOURS,
                       now_ratio=LIVE_NOW_RATIO):
    """Start datetime for the live view window.

    Keeps "now" at a fixed fraction of the viewport so the default view
    favors upcoming tide changes while preserving a short recent history.
    """
    past_hours = hours_shown * now_ratio
    return now_local - timedelta(hours=past_hours) + timedelta(minutes=offset_minutes)


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
        return all(braille_rows[row][c][0] == BLANK for c in cols if 0 <= c < graph_w)

    for x, height_ft, height_display, is_peak, dt in extrema:
        if h_max == h_min:
            curve_row = n_rows // 2
        else:
            y = (total_dots - 1) * (1 - (height_ft - h_min) / (h_max - h_min))
            curve_row = max(0, min(n_rows - 1, int(round(y)) // 4))

        label_row = max(0, curve_row - 1) if is_peak else min(n_rows - 1, curve_row + 1)

        label = f"{fmt_decimal(height_display, 1, runtime)}{runtime.height_unit}"
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
    disp_range = abs(runtime.convert_height(value_range[1])
                     - runtime.convert_height(value_range[0]))

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

    Overlay priority: foreground overlays > braille dots > background
    overlays > indicators.  A time label is a background overlay, and the
    now, hover, and midnight lines stop at it rather than cut through it.
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

        line = ""
        for ci, (ch, _height) in enumerate(row):
            if ci in fg_chars:
                oc, oc_color = fg_chars[ci]
                line += f"{fg(*oc_color)}{oc}"
            elif ch != BLANK:
                dl = col_daylight[ci] if ci < len(col_daylight) else 1.0
                brightness = NIGHT_DIM + (1.0 - NIGHT_DIM) * dl
                line += fg(int(cr * brightness), int(cg * brightness), int(cb * brightness))
                line += ch
            elif ci in bg_chars:
                oc, oc_color = bg_chars[ci]
                line += f"{fg(*oc_color)}{oc}"
            elif hover_col is not None and ci == hover_col:
                line += f"{hover_fg}\u2502"
            elif now_col is not None and ci == now_col:
                line += f"{now_fg}\u2502"
            elif ci in midnight_cols:
                line += f"{DIM}\u2502"
            else:
                line += " "
        lines.append(f"{line}{RESET}")
    return lines


# ---------------------------------------------------------------------------
# Header line (day names at midnight boundaries)
# ---------------------------------------------------------------------------
def _pill_label(station_name, location_menu=False):
    """The station pill's text; the live view's pill is a menu too."""
    # Title-case a station list's capitals but preserve short uppercase
    # tokens (state/province codes). A name that arrives in mixed case is
    # a geocoder's, and already written as its language writes it:
    # "préfecture d'Osaka" is not improved by "Préfecture D'Osaka".
    if station_name:
        parts = [p.strip() for p in station_name.split(",")]
        parts = [p.upper() if len(p) <= 2 else p.title() if p.isupper() else p
                 for p in parts]
        name = ", ".join(parts)
    else:
        name = ""
    return f"{name} \u25bc" if name and location_menu else name


def _render_header_line(cols, station_name, runtime, offset_minutes=0, location_menu=False):
    """Render the top line with pill-styled station name."""
    name = _pill_label(station_name, location_menu)

    # Station name pill (left)
    pbg = bg(*PILL_BG_RGB)
    if name and not pbg:
        # no color: the half blocks alone would read as stray marks
        pill, pill_w = name, visible_len(name)
    elif name:
        pfg = fg(*PILL_FG_RGB)
        pedge = fg(*PILL_BG_RGB)
        pill = f"{pedge}\u2590{pbg}{pfg} {name} {RESET}{pedge}\u258c{RESET}"
        pill_w = visible_len(name) + 4  # ▐ + space + name + space + ▌
    else:
        pill = ""
        pill_w = 0

    # Moon phase (right-aligned)
    idx, _, moon_icon = moon_phase(datetime.now(timezone.utc), runtime)
    phase_name = moon_name(idx, runtime)
    moon_color = fg(*MUTED_RGB)
    moon_str = f"{moon_color}{moon_icon} {DIM}{phase_name}{RESET}"
    moon_w = visible_len(moon_icon) + 1 + visible_len(phase_name)

    # "Space to return" hint (right, only when scrolled)
    if offset_minutes:
        hint_text = _ts("space_to_now", runtime)
        hint = f"{DIM}{hint_text}{RESET}"
        right_w = visible_len(hint_text)
        padding = max(1, cols - pill_w - right_w)
        return f"{pill}{' ' * padding}{hint}"

    padding = max(1, cols - pill_w - moon_w)
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

    arrow = "↗" if rising else "↘"
    if runtime.icons == "nerd":
        icon_hi = "\U000F0799"   # 󰞙
        icon_lo = "\U000F0796"   # 󰞖
    else:
        icon_hi = "▲"
        icon_lo = "▼"

    h_display = runtime.convert_height(now_height)
    unit = runtime.height_unit

    # --- Current stat ---
    if offset_minutes:
        time_str = fmt_time_dt(now_dt, use_24h=runtime.use_24h)
        now_content = f"{now_text}{arrow} {time_str} {fmt_decimal(h_display, 1, runtime)}{unit}"
    else:
        now_content = f"{now_text}{arrow} {fmt_decimal(h_display, 1, runtime)}{unit}"

    # --- High/low/range parts ---
    rest_parts = []
    hilo = window["hilo"]
    if hilo:
        highs = [(dt, v) for dt, v, t in hilo if t == "H"]
        lows = [(dt, v) for dt, v, t in hilo if t == "L"]

        if highs:
            dt, v = highs[0]
            v_d = runtime.convert_height(v)
            t_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
            rest_parts.append(f"{text}{icon_hi}{fmt_decimal(v_d, 1, runtime)}{unit} {dim}{t_str}")
        if lows:
            dt, v = lows[0]
            v_d = runtime.convert_height(v)
            t_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
            rest_parts.append(f"{text}{icon_lo}{fmt_decimal(v_d, 1, runtime)}{unit} {dim}{t_str}")

        # The range is the highest high less the lowest low, so it needs
        # one of each.  A diurnal station's 24 hours can hold a single
        # extreme, and measuring that against zero would print a range
        # that is really a height, or a negative one for a lone low.
        if highs and lows:
            h_max = max(v for _, v in highs)
            h_min = min(v for _, v in lows)
            tide_range = runtime.convert_height(h_max - h_min)
            rest_parts.append(f"{text}Δ{fmt_decimal(tide_range, 1, runtime)}{unit}")

    # --- "Space to return" hint ---
    if offset_minutes:
        hint = _ts("space_to_now", runtime)
        rest_parts.append(f"{dim}{hint}")

    # --- Assemble pill ---
    now_fg = fg(*now_rgb)
    now_bg = bg(*now_rgb)
    pill_fg_esc = fg(*pill_rgb)
    pill_bg_esc = bg(*pill_rgb)

    if not now_bg:
        # no color: the stats alone, without the half blocks round them
        line = sep.join([now_content, *rest_parts]) + RESET
    elif rest_parts:
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
           predictions=None, hilo=None, y_range=None, marine_data=None,
           provider=None, location_menu=False):
    """Build the complete multi-line tide display.

    When predictions/hilo are provided (live mode), renders a sliding 24h
    window with hover and scroll support.  Otherwise fetches the current
    day's data from *provider* (NOAA when not given) for a static view.

    y_range: optional (min_ft, max_ft) to fix the y-axis scale (e.g. from
             30-day hilo data) so the curve doesn't rescale as you scroll.
    marine_data: optional dict from fetch_marine() for wave/swell conditions.
    """
    if runtime is None:
        runtime = current_runtime(TidesRuntime)
    if provider is None:
        provider = NOAA

    now_local = _station_now(station_meta, predictions)
    station_tz = _station_tzinfo(station_meta)
    cols, rows = get_terminal_size()
    graph_w = max(30, cols)

    # --- build the window ---
    if predictions is not None:
        # Live mode: keep "now" near the left so most of the chart looks ahead.
        start_dt = _live_window_start(
            now_local,
            offset_minutes=offset_minutes,
            hours_shown=LIVE_WINDOW_HOURS,
        )
        window = prepare_tide_window(
            predictions, hilo or [], start_dt, hours_shown=LIVE_WINDOW_HOURS,
        )
    else:
        # Static mode: show the current calendar day
        date = (now_local + timedelta(minutes=offset_minutes)).date()
        preds_dt = provider.tides_range(station_id, date, date, station_tz)
        hilo_dt = provider.hilo_range(station_id, date, date, station_tz)
        if not preds_dt:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)
        day_start = datetime(date.year, date.month, date.day)
        if station_tz is not None:
            day_start = day_start.replace(tzinfo=station_tz)
        window = prepare_tide_window(preds_dt, hilo_dt, day_start, hours_shown=LIVE_WINDOW_HOURS)

    w_start = window["start"]
    w_total = window["total_hours"]
    w_preds = window["predictions"]
    w_secs = w_total * 3600

    # --- dimensions (header + day_labels + braille + ticks + extras) ---
    extra = 1  # the footer line: marine conditions + data source
    if install_banner():
        extra += 1
    n_braille_rows = max(2, rows - ((3 + extra) if fullscreen else 7))

    # --- interpolate predictions to graph columns ---
    col_heights = []
    for x in range(graph_w):
        frac = (x + 0.5) / graph_w
        dt = w_start + timedelta(hours=frac * w_total)
        col_heights.append(interp_height(dt, w_preds))

    # --- now position ---
    now_offset = (now_local - w_start).total_seconds()
    if 0 <= now_offset <= w_secs:
        now_col = max(0, min(graph_w - 1, int(now_offset / w_secs * (graph_w - 1))))
    else:
        now_col = None

    # --- day divisions ---
    midnight_cols, midnight_day_names = compute_time_markers(w_start, w_total, graph_w, runtime)
    moon_labels = compute_moon_labels(w_start, w_total, graph_w, station_meta, runtime)

    # --- hover ---
    hover_graph_col = None
    chart_start = 2  # line index where braille starts (after header + day labels)
    chart_end = chart_start + n_braille_rows
    if mouse_pos:
        mcol, mrow = mouse_pos
        mrow_idx = mrow - 1  # 1-based -> 0-based
        if chart_start <= mrow_idx < chart_end:
            gc = mcol - 1  # 1-based terminal col -> 0-based graph col
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
    col_daylight = compute_daylight_window(graph_w, w_start, w_total, station_meta)

    # --- now info for header ---
    now_info = None
    if now_col is not None:
        now_height = interp_height(now_local, w_preds)
        h_display = runtime.convert_height(now_height)
        time_str = fmt_time_dt(now_local, use_24h=runtime.use_24h)
        now_info = (time_str, fmt_decimal(h_display, 1, runtime), runtime.height_unit)

    # --- assemble output ---
    lines = []

    # Header with pill-styled station name
    lines.append(_render_header_line(
        cols, station_name, runtime, offset_minutes=offset_minutes,
        location_menu=location_menu,
    ))

    # Day labels on their own row
    lines.append(render_day_label_line(midnight_day_names, graph_w, moon_labels=moon_labels))

    # Braille chart
    lines.extend(_render_tide_braille_rows(
        braille_rows, col_daylight, midnight_cols,
        now_col=now_col, hover_col=hover_graph_col, overlays=overlays,
    ))

    # Tick labels
    lines.append(render_tide_ticks(
        w_start, w_total, graph_w, runtime,
        now_col=now_col, hover_col=hover_graph_col,
    ))

    # Footer: marine conditions on the left, the data source on the
    # right, one line.  Too narrow for both: marine wins.
    marine_str = ""
    from linecast.terminal import help as _help
    from linecast._i18n import lang_of
    foot_width = cols - visible_len(_help.hint(lang_of(runtime), cols)) - 2 if fullscreen else cols
    if marine_data is not None:
        try:
            marine = parse_marine_current(marine_data, now_local)
            marine_str = format_marine_line(marine, runtime, width=foot_width) or ""
        except Exception as exc:
            # Marine data is optional; never crash
            log_failure("marine/open-meteo", "marine line", exc, fallback="line omitted")
    dim = fg(*DIM_RGB)
    source = provider.footer_label(runtime)
    pad = foot_width - visible_len(marine_str) - visible_len(source)
    if marine_str and pad >= 2:
        lines.append(f"{dim}{marine_str}{' ' * pad}{source}{RESET}")
    elif marine_str:
        lines.append(f"{dim}{marine_str}{RESET}")
    else:
        lines.append(f"{dim}{source}{RESET}")
    if fullscreen:
        lines[-1] = _help.footer(lines[-1], cols, lang_of(runtime))

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
            tooltip = build_tide_hover_tooltip(
                window, hover_graph_col, mouse_pos[1],
                chart_start, chart_end, cols, rows, graph_w, runtime,
            )
            if tooltip:
                overlay_parts.append(tooltip)
        elif now_col is not None and now_info is not None:
            now_tip = build_now_tooltip(now_col, now_info, chart_start, cols)
            if now_tip:
                overlay_parts.append(now_tip)

        output = _live.overlay(output, "".join(overlay_parts))

    return output


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
class TidesApp(LocationMenu, _live.LiveApp):
    """The live tide view: a sliding window over predictions fetched a
    week to either side, widened as the user scrolls toward an edge."""

    interval = 60
    mouse = True
    # Larger step makes wheel/arrow scrubbing practical for multi-day browsing.
    scroll_step = 30

    help_view = 'tides'
    LOG_AREA = 'tides'

    def __init__(self, provider, station_id, station_name, station_meta,
                 station_tz, runtime, predictions, hilo, fetched_start,
                 fetched_end, y_range=None, marine_data=None, place=None, country=""):
        self.provider = provider
        self.station_id = station_id
        self.station_name = station_name
        self.station_meta = station_meta
        self.station_tz = station_tz
        self.runtime = runtime
        self.predictions = predictions
        self.hilo = hilo
        self.fetched_start = fetched_start
        self.fetched_end = fetched_end
        self.y_range = y_range
        self.marine_data = marine_data
        self._worker = None
        self._retry_at = 0.0   # monotonic; no expansion before this
        # The place the reader asked for, which the station is nearest
        # to: (lat, lng, label). A named station stands for itself.
        if place is None:
            meta = station_meta or {}
            place = (meta.get("lat"), meta.get("lng"), "")
        self.lat, self.lng, self.place_label = place
        self.country = country
        from linecast.weather.locations import LocationPicker
        self.locations = LocationPicker(runtime.lang, align='left')
        self._update_location_picker()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._loading = None
        self._location_result = None
        self._location_worker = None

    # --- the location menu (LocationMenu) ---------------------------------
    def _here(self):
        try:
            return float(self.lat), float(self.lng)
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _label(self):
        lat, lng = self._here()
        return self.place_label or self.station_name or f"{lat:.2f}, {lng:.2f}"

    def _load_place(self, place, stale):
        """The nearest station to *place* and its data, as main() finds
        them: None when nothing covers it, "failed" when it would not load."""
        from linecast._geocode import reverse_geocode
        try:
            country = reverse_geocode(place.lat, place.lon, lang=self.runtime.lang)[1]
        except Exception as exc:
            log_failure("tides", "place country", exc, fallback="no regional provider")
            country = ""
        provider, station_id, station_name = _station_for_location(
            place.lat, place.lon, country, label=place.name)
        if station_id is None:
            return None
        station_meta, station_name, station_tz = _station_details(
            provider, station_id, station_name)
        fetched = _fetch_station(provider, station_id, station_meta, station_tz, live=True)
        if not fetched[4]:
            return "failed"
        return dict(provider=provider, station_id=station_id, station_name=station_name,
                    station_meta=station_meta, station_tz=station_tz, country=country,
                    fetched=fetched)

    def _place_failed(self, place, result):
        if isinstance(result, dict):
            return None
        key = "no_tides" if result is None else "load_failed"
        return _ts(key, self.runtime, name=place.name)

    def _commit_place(self, place, result):
        (self.fetched_start, self.fetched_end, self.y_range, self.marine_data,
         self.predictions, self.hilo) = result["fetched"]
        self.provider = result["provider"]
        self.station_id = result["station_id"]
        self.station_name = result["station_name"]
        self.station_meta = result["station_meta"]
        self.station_tz = result["station_tz"]
        self.country = result["country"]
        self.lat, self.lng, self.place_label = place.lat, place.lon, place.name
        self._retry_at = 0.0

    def _on_place(self, col, row):
        name = _pill_label(self.station_name, location_menu=True)
        return row == 1 and bool(name) and col <= visible_len(name) + 4

    def expand_for(self, offset_minutes):
        """Widen the fetched range when the user scrolls near an edge.

        The fetch runs on a worker so a slow network never stalls the
        scroll: the view keeps painting the range it has, and the wider
        one nudges a repaint when it lands. The providers absorb network
        failures and answer empty, and an empty range is a failure, not
        a flat sea — the old range stays, and the next try waits out a
        short pause so a dead network is not asked on every repaint.
        """
        current_now = _station_now(self.station_meta, self.predictions)
        view_start = _live_window_start(
            current_now,
            offset_minutes=offset_minutes,
            hours_shown=LIVE_WINDOW_HOURS,
        )
        view_end = view_start + timedelta(hours=LIVE_WINDOW_HOURS)
        view_start_date = view_start.date()
        view_end_date = view_end.date()

        need_expand = False
        new_start, new_end = self.fetched_start, self.fetched_end

        if view_start_date - timedelta(days=2) < self.fetched_start:
            new_start = view_start_date - timedelta(days=7)
            need_expand = True
        if view_end_date + timedelta(days=2) > self.fetched_end:
            new_end = view_end_date + timedelta(days=7)
            need_expand = True

        if (not need_expand or _t.monotonic() < self._retry_at
                or (self._worker and self._worker.is_alive())):
            return

        provider, station_id, station_tz = self.provider, self.station_id, self.station_tz

        def worker():
            try:
                predictions = provider.tides_range(
                    station_id, new_start, new_end, station_tz)
                hilo = provider.hilo_range(
                    station_id, new_start, new_end, station_tz)
            except Exception as exc:
                log_failure("tides", "range expansion", exc,
                            fallback="edge stays put")
                predictions = None
            if station_id != self.station_id:
                return  # the reader has moved to another station
            if predictions:
                self.predictions = predictions
                self.hilo = hilo
                self.fetched_start = new_start
                self.fetched_end = new_end
                _live.nudge()
            else:
                self._retry_at = _t.monotonic() + 30

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def render(self, offset_minutes=0, mouse_pos=None, active_alert=None,
               modal_scroll=0):
        with self._state_lock:
            self._finish_location()
        panel = self.locations.active
        self.expand_for(offset_minutes)
        output = render(
            self.station_id,
            self.station_name,
            station_meta=self.station_meta,
            runtime=self.runtime,
            fullscreen=True,
            offset_minutes=offset_minutes,
            predictions=self.predictions,
            hilo=self.hilo,
            y_range=self.y_range,
            marine_data=self.marine_data,
            provider=self.provider,
            mouse_pos=None if panel else mouse_pos,
            location_menu=True,
        )
        cols, rows = get_terminal_size()
        floating = self.menu_overlay(cols, rows)
        output = _live.overlay(output, floating)
        return output, {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = tides_parser().parse_args()
    runtime = TidesRuntime.from_sources(args)
    set_current(runtime)
    # The tide curve is time, so in a right-to-left language the whole
    # view reads from the right, the next tide at the right edge
    from linecast.terminal import bidi as _bidi
    _bidi.set_mirror(True)
    sweep_legacy_cache()

    # --search / --nearby: list stations and exit.  A bare `--search`
    # behaves like --nearby (empty query = nearest stations).
    if args.nearby or args.search is not None:
        query = args.search or ""
        _search_stations(query, metric=runtime.metric,
                         limit=15 if not query.strip() else 20,
                         cli_location=args.location)
        return

    # Ask the terminal how wide it draws things before the spinner has
    # the screen: the probe wants stdin and stdout to itself.
    if not runtime.json_mode:
        from linecast.terminal.textwidth import calibrate_from_terminal
        calibrate_from_terminal()

    # everything from here to the first paint may block on the network
    # (station lookup, metadata, two weeks of predictions) — spin
    # (suppressed for --json: stdout must carry nothing but the payload)
    spin = Spinner()
    if not runtime.json_mode:
        spin.start()
    try:
        # Station: --station flag > TIDE_STATION env var > geolocation
        override = args.station or os.environ.get("TIDE_STATION", "").strip()
        place, country = None, ""  # what the station was found for

        if override:
            provider = provider_for_id(override)
            if provider is not None:
                station_id = override
                station_name = plain_text(provider.name_for_id(override))
            else:
                # Text query — pick the closest matching station (first match
                # when the current location is unknown)
                matches = _find_matching_stations(override,
                                                  cli_location=args.location)
                if not matches:
                    print(f'No stations matching "{override}". '
                          "Try `linecast tides --nearby` to list the nearest stations.",
                          file=sys.stderr)
                    sys.exit(1)
                best = matches[0]
                provider = PROVIDERS[best["source"]]
                station_id = best["id"]
                station_name = best["name"] or f"Station {station_id[:8]}"
            # A named station says nothing about where the user is; the
            # units default still follows their own location, as it does
            # in the branch below.
            _lat, _lng, _cc = resolve_location(args.location, lang=runtime.lang)
            own = country_for_defaults(args.location, _cc, _lat, _lng)
            if own:
                runtime = TidesRuntime.from_sources(args, country=own)
                set_current(runtime)
        else:
            # need_country: provider routing (CHS for Canada, QLD for
            # Queensland) hinges on the country of the target location.
            # return_label: the forward geocoder already named the place
            # the user asked for. Keeping it spares a reverse-geocode
            # round trip and, more to the point, keeps the header able to
            # show that "Leith" was read as the one in Tasmania.
            lat, lng, country_code, resolved_label = resolve_location(
                args.location, lang=runtime.lang, need_country=True,
                return_label=True)
            if lat is None:
                print("Could not determine location for tide station lookup.", file=sys.stderr)
                sys.exit(1)
            if resolved_label:
                from linecast._geocode import place_label
                resolved_label = place_label(lat, lng, resolved_label, runtime.lang)

            # Re-resolve the runtime a cold cache made countryless.
            own = country_for_defaults(args.location, country_code, lat, lng)
            if own:
                runtime = TidesRuntime.from_sources(args, country=own)
                set_current(runtime)

            provider, station_id, station_name = _station_for_location(
                lat, lng, country_code, label=resolved_label)
            place, country = (lat, lng, resolved_label or ""), country_code or ""

            if station_id is None and runtime.json_mode:
                # No station in range: emit the payload shape anyway, with
                # station/events/series empty-or-null, and exit cleanly.
                import json as _json
                from linecast.sunshine.json import _location_label
                from linecast.tides.json import build_payload
                payload = build_payload(
                    None, runtime, datetime.now().astimezone(), [], [],
                    location=resolved_label or _location_label(lat, lng),
                )
                print(_json.dumps(payload, ensure_ascii=False))
                return

            if station_id is None:
                hint = ("No tide station within 100nm, and the global tide "
                        "model has no coverage here (inland?).\n"
                        "  Try `linecast tides --nearby` to list the nearest stations, "
                        "or `linecast tides --station <id or name>`.")
                if not TIDECHECK.available():
                    hint += ("\n  For more station coverage, set "
                             "LINECAST_TIDECHECK_KEY (free at tidecheck.com).")
                print(hint, file=sys.stderr)
                sys.exit(1)

        station_meta, station_name, station_tz = _station_details(
            provider, station_id, station_name)
        now_local = _station_now(station_meta)
        today = now_local.date()

        if runtime.json_mode:
            import json as _json
            from linecast.tides.json import build_payload
            preds = provider.tides_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            hilo_data = provider.hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            now_local = _station_now(station_meta, preds or hilo_data)
            tz_name = (getattr(station_tz, "key", None)
                       or (now_local.tzname() if now_local.tzinfo else None))
            payload = build_payload(
                station_name, runtime, now_local, preds, hilo_data,
                station_id=station_id, source=provider.name, tz_name=tz_name,
            )
            print(_json.dumps(payload, ensure_ascii=False))
            return

        if runtime.oneline:
            from linecast.terminal.oneline import emit
            from linecast.tides.oneline import tides_oneline
            hilo_data = provider.hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=1), station_tz)
            line = tides_oneline(station_name, hilo_data or [],
                                 _station_now(station_meta, hilo_data),
                                 runtime)
            spin.stop()
            emit(line)
            return

        fetch_start, fetch_end, y_range, marine_data, preds, hilo_data = _fetch_station(
            provider, station_id, station_meta, station_tz, runtime.live)

        if not preds:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)

        if runtime.live:
            spin.stop()
            TidesApp(
                provider, station_id, station_name, station_meta,
                station_tz, runtime, preds, hilo_data, fetch_start, fetch_end,
                y_range=y_range, marine_data=marine_data, place=place, country=country,
            ).run()
        elif provider is NOAA:
            # NOAA's static view is the calendar day, which render fetches
            # itself from the month already cached above; every other
            # provider shows the same 24-hour window as the live view.
            out = render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                y_range=y_range,
                marine_data=marine_data,
                provider=provider,
            )
            spin.stop()
            _live.print_frame(out)
        else:
            out = render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                predictions=preds,
                hilo=hilo_data,
                y_range=y_range,
                marine_data=marine_data,
                provider=provider,
            )
            spin.stop()
            _live.print_frame(out)
    finally:
        spin.stop()

