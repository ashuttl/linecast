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
import sys
from datetime import datetime, timezone, timedelta

from linecast.terminal.braille import BLANK, build_braille_curve
from linecast.terminal.color import bg, fg, RESET
from linecast.terminal.textwidth import fit, visible_len
from linecast.terminal.framebuffer import get_terminal_size
from linecast._timefmt import fmt_time_dt
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast._i18n import fmt_decimal
from linecast._runtime import TidesRuntime, current_runtime, install_banner
from linecast._log import log_failure
from linecast.tides.marine import parse_marine_current, format_marine_line
from linecast.tides.i18n import _ts
from linecast._i18n import moon_name
from linecast.tides.providers import NOAA
from linecast.tides.stations import _station_now, _station_tzinfo
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


def _live_window_hours(cols):
    """Widen in six-hour steps, aiming for four columns per hour.

    Keep at least a day on small terminals and at most three days so
    individual tides remain readable even on very wide displays.
    """
    return max(LIVE_WINDOW_HOURS, min(72, ((cols + 12) // 24) * 6))


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


# The fewest cells of a station's name a pill is worth drawing for
LEAST_PILL_NAME = 4

# How wide the pill on screen is: the cells a click opens the menu from
_pill_width = 0


def pill_width():
    return _pill_width


def _pill(name):
    """(pill, width): *name* in the station pill's colours."""
    pbg = bg(*PILL_BG_RGB)
    if name and not pbg:
        # no color: the half blocks alone would read as stray marks
        return name, visible_len(name)
    if name:
        pfg = fg(*PILL_FG_RGB)
        pedge = fg(*PILL_BG_RGB)
        # ▐ + space + name + space + ▌
        return (f"{pedge}\u2590{pbg}{pfg} {name} {RESET}{pedge}\u258c{RESET}",
                visible_len(name) + 4)
    return "", 0


def _fit_title(cols, station_name, location_menu, titles):
    """(pill name, title) for a header *cols* wide, where the title has
    the say.  *titles* are its forms, longest first, each (text, the
    cells to keep for it).  The station's name gives way before the
    title does: it drops its state or country, "Portland, ME" to
    "Portland", for the longest title that then fits; under the shortest
    it is cut short, and then left out."""
    whole = _pill_label(station_name)
    if not whole:
        return "", titles[0][0]
    mark = " \u25bc" if location_menu else ""
    edges = _pill("x")[1] - 1
    names = dict.fromkeys((whole, whole.split(",")[0].strip()))

    def room(keep):
        return cols - keep - 2 - edges - visible_len(mark)

    for text, keep in titles:
        for name in names:
            if visible_len(name) <= room(keep):
                return name + mark, text
    text, keep = titles[-1]
    if room(keep) < LEAST_PILL_NAME:
        return "", text
    return fit(list(names)[-1], room(keep)) + mark, text


def _render_header_line(cols, station_name, runtime, offset_minutes=0, location_menu=False,
                        right=None):
    """Render the top line with pill-styled station name.

    *right* replaces the Moon's phase at the right end: the month and
    year views' titles, already inked.  A list of (title, cells to keep
    for it) gives a title's forms, longest first; see _fit_title."""
    global _pill_width
    if right is not None:
        titles = [(right, visible_len(right))] if isinstance(right, str) else right
        name, right = _fit_title(cols, station_name, location_menu, titles)
        keep = dict(titles)[right]
        pill, pill_w = _pill(name)
        _pill_width = pill_w
        if offset_minutes:
            hint = f"{DIM}{_ts('space_to_now', runtime)}{RESET}   "
            if pill_w + visible_len(hint) + keep + 2 <= cols:
                right = hint + right
        padding = max(1, cols - pill_w - visible_len(right))
        return f"{pill}{' ' * padding}{right}"

    pill, pill_w = _pill(_pill_label(station_name, location_menu))
    _pill_width = pill_w

    # Moon phase (right-aligned)
    idx, _, moon_icon = moon_phase(datetime.now(timezone.utc), runtime, bg_color=_theme.theme_bg)
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

    With predictions/hilo, renders a sliding window that widens with the
    terminal in fullscreen mode, with hover and scroll support. Otherwise
    fetches the current day's data from *provider* (NOAA when not given)
    for a static view.

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
        hours_shown = _live_window_hours(cols) if fullscreen else LIVE_WINDOW_HOURS
        start_dt = _live_window_start(
            now_local,
            offset_minutes=offset_minutes,
            hours_shown=hours_shown,
        )
        window = prepare_tide_window(
            predictions, hilo or [], start_dt, hours_shown=hours_shown,
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


def main():
    # the live view draws through render, so tides.live imports this
    # module; importing it here, at the call, keeps that one-way at load
    from linecast.tides.live import main as live_main
    live_main()
