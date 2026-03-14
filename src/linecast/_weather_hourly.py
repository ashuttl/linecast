"""Hourly weather chart rendering."""

from datetime import datetime, timedelta

from linecast._braille import build_braille_curve, interpolate
from linecast._graphics import bg, fg, fmt_hour, fmt_time_dt, RESET, visible_len
from linecast._runtime import WeatherRuntime
from linecast._weather_i18n import DAY_NAMES, FULL_DAY_NAMES, _s
from linecast._weather_sources import _local_now_for_data
from linecast._weather_style import (
    CHART_BG_DAY_RGB,
    CHART_BG_NIGHT_RGB,
    CHART_HOVER_RGB,
    DIM,
    MUTED,
    SPARKLINE,
    SUNRISE_LABEL_RGB,
    SUNSET_LABEL_RGB,
    TEXT,
    UV_COLOR,
    WIND_ARROWS,
    WIND_COLOR,
    _colored_temp,
    _precip_color,
    _temp_color,
    _uv_color,
)


def _daylight_factor(col_dt, sun_events):
    """Return a brightness factor (0.0-1.0) for a given datetime.

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
        if mins_from_rise < 0 and mins_from_set > 0:
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
def _build_precip_blocks(precip_probs, weather_codes, graph_w, n_rows=1, indicator_cols=None):
    """Build multi-row block bar graph for precipitation probability.

    Returns a list of rendered line strings (n_rows lines).
    Bars grow upward from the bottom using partial block characters (▁▂▃▄▅▆▇█),
    giving 8 levels of vertical resolution per character row.
    indicator_cols: set of 0-based graph columns to draw │ where cell is empty.
    """
    total_eighths = n_rows * 8  # total vertical resolution units

    # Interpolate precip probability to 1 sample per column
    col_probs = interpolate(precip_probs, graph_w)
    # Nearest-neighbor for discrete weather codes
    col_codes = []
    for x in range(graph_w):
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
            is_empty = p <= 5
            if not is_empty:
                bar_h = max(1, int(p / 100 * total_eighths + 0.5))
                is_empty = bar_h <= row_bottom

            if is_empty:
                if indicator_cols and x in indicator_cols:
                    line += f"{DIM}\u2502"
                else:
                    line += " "
            elif bar_h >= row_top:
                color = _precip_color(col_codes[x])
                line += f"{color}\u2588"
            else:
                eighths_in_row = bar_h - row_bottom  # 1-7
                color = _precip_color(col_codes[x])
                line += f"{color}{SPARKLINE[eighths_in_row - 1]}"
        result.append(f"{line}{RESET}")

    return result


def _interpolate_columns(values, graph_w):
    """Linearly interpolate values to one sample per terminal column."""
    return interpolate(values, graph_w)


def _prepare_hourly_window(hourly, now, graph_w, offset_minutes=0):
    """Slice hourly arrays to the visible window.

    offset_minutes shifts the window start forward (positive) or backward
    (negative) from the current hour, enabling keyboard/mouse scrolling.
    """
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip_prob = hourly.get("precipitation_probability", [])
    weather_codes = hourly.get("weather_code", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    wind_directions = hourly.get("wind_direction_10m", [])
    apparent_temps = hourly.get("apparent_temperature", [])
    humidity = hourly.get("relative_humidity_2m", [])
    dew_points = hourly.get("dew_point_2m", [])
    uv_indices = hourly.get("uv_index", [])
    if not times or not temps:
        return None

    parsed = []
    for i, t in enumerate(times):
        try:
            parsed.append((i, datetime.fromisoformat(t)))
        except Exception:
            continue

    current_hour_dt = now.replace(minute=0, second=0, microsecond=0)
    hours_shown = max(24, min(48, graph_w // 2))

    window_start_dt = current_hour_dt + timedelta(minutes=offset_minutes)

    # Clamp so the window fits within available data
    if parsed:
        first_dt = parsed[0][1]
        last_dt = parsed[-1][1]
        max_start = last_dt - timedelta(hours=hours_shown)
        if window_start_dt > max_start:
            window_start_dt = max_start
        if window_start_dt < first_dt:
            window_start_dt = first_dt

    start_idx = 0
    for i, dt in parsed:
        if dt >= window_start_dt:
            start_idx = i
            break

    end_time = window_start_dt + timedelta(hours=hours_shown)
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
    window_apparent = apparent_temps[start_idx:end_idx + 1] if apparent_temps else []
    window_humidity = humidity[start_idx:end_idx + 1] if humidity else []
    window_dew = dew_points[start_idx:end_idx + 1] if dew_points else []
    window_uv = uv_indices[start_idx:end_idx + 1] if uv_indices else []
    window_dts = [dt for i, dt in parsed if start_idx <= i <= end_idx]

    total_hours = 24
    if window_dts and len(window_dts) > 1:
        total_secs = (window_dts[-1] - window_dts[0]).total_seconds()
        total_hours = total_secs / 3600 if total_secs > 0 else 24

    # Global stats across all available data for stable layout while scrolling
    all_temp_lo = min(temps) if temps else 0
    all_temp_hi = max(temps) if temps else 0
    all_wind_max = max(wind_speeds) if wind_speeds else 0
    all_uv_max = max(uv_indices) if uv_indices else 0
    all_precip_max = max(precip_prob) if precip_prob else 0

    return {
        "temps": window_temps,
        "precip": window_precip,
        "codes": window_codes,
        "winds": window_winds,
        "wind_dirs": window_wind_dirs,
        "apparent_temps": window_apparent,
        "humidity": window_humidity,
        "dew_points": window_dew,
        "uv": window_uv,
        "dts": window_dts,
        "total_hours": total_hours,
        "all_temp_range": (all_temp_lo, all_temp_hi),
        "all_wind_max": all_wind_max,
        "all_uv_max": all_uv_max,
        "all_precip_max": all_precip_max,
    }


def _compute_time_markers(window_dts, total_hours, graph_w, runtime=None):
    """Compute notable timeline columns (midnight, noon) and day labels."""
    lang = getattr(runtime, "lang", "en") if runtime else "en"
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
                midnight_day_names[x] = FULL_DAY_NAMES.get(lang, FULL_DAY_NAMES["en"])[dt.weekday()]
            elif dt.hour == 12:
                noon_cols.add(x)
    return midnight_cols, noon_cols, midnight_day_names


def _compute_sun_labels(window_dts, sun_events, total_hours, graph_w, runtime):
    """Compute sunrise/sunset labels mapped to graph columns."""
    sun_labels = {}
    use_24h = runtime.use_24h
    sunrise_icon = "\u2600\ufe0f" if runtime.emoji else "\U000F059C"
    sunset_icon = "\U0001f305" if runtime.emoji else "\U000F059B"
    if window_dts and sun_events:
        t0 = window_dts[0]
        for rise, sset in sun_events:
            if rise:
                off_h = (rise - t0).total_seconds() / 3600
                if 0 < off_h < total_hours:
                    x = int(off_h / total_hours * (graph_w - 1))
                    if 0 < x < graph_w - 1:
                        lbl = fmt_time_dt(rise, use_24h)
                        sun_labels[x] = (f"{sunrise_icon}{lbl}", True)
            if sset:
                off_h = (sset - t0).total_seconds() / 3600
                if 0 < off_h < total_hours:
                    x = int(off_h / total_hours * (graph_w - 1))
                    if 0 < x < graph_w - 1:
                        lbl = fmt_time_dt(sset, use_24h)
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
    """Detect notable points for chart annotations: peaks, valleys, and bends.

    All candidate label points are scored and placed greedily from highest to
    lowest priority, respecting a minimum gap between labels.  This naturally
    adapts to terminal width — wider charts get more labels.

    Candidate types (unified scoring in comparable degree units):
      - Global max/min: score 100 (always placed)
      - Peaks/valleys:  score = topographic prominence (degrees)
      - Curvature bends: score = equivalent temperature displacement over the
        label-gap window, capturing elbows and plateaus
    """
    extrema = []  # (x, temp, is_peak)
    if len(col_temps) < 5:
        return extrema

    min_gap = max(8, graph_w // 15)
    prom_radius = max(15, graph_w // 10)
    n = len(col_temps)

    # All candidates: (x, temp, is_peak, score)
    scored = []

    # --- Peaks and valleys (scored by prominence in degrees) ---
    for i in range(2, n - 2):
        local = col_temps[max(0, i - 3):i + 4]
        is_peak = col_temps[i] >= max(local) and (
            col_temps[i] > col_temps[i - 1] or col_temps[i] > col_temps[i + 1]
        )
        is_valley = col_temps[i] <= min(local) and (
            col_temps[i] < col_temps[i - 1] or col_temps[i] < col_temps[i + 1]
        )
        if not is_peak and not is_valley:
            continue
        nl = col_temps[max(0, i - prom_radius):i]
        nr = col_temps[i + 1:min(n, i + prom_radius + 1)]
        if not nl or not nr:
            continue
        if is_peak:
            prom = col_temps[i] - max(min(nl), min(nr))
        else:
            prom = min(max(nl), max(nr)) - col_temps[i]
        if prom >= 1:
            scored.append((i, col_temps[i], is_peak, prom))

    # --- Global max/min (always placed first) ---
    global_max_x = max(range(n), key=lambda i: col_temps[i])
    global_min_x = min(range(n), key=lambda i: col_temps[i])
    for gx, is_peak in [(global_max_x, True), (global_min_x, False)]:
        scored.append((gx, col_temps[gx], is_peak, 100))

    # --- Curvature points: elbows and plateaus ---
    # Sagitta = how far the curve deviates from a straight chord.
    # Directly in degrees, comparable to peak/valley prominence.
    half_w = min_gap * 2
    detect_r = max(3, graph_w // 40)
    sagittas = [0.0] * n
    for i in range(detect_r, n - detect_r):
        hw = min(half_w, i, n - 1 - i)
        if hw < min_gap:
            continue
        sagittas[i] = col_temps[i] - (col_temps[i - hw] + col_temps[i + hw]) / 2

    for i in range(detect_r, n - detect_r):
        abs_sag = abs(sagittas[i])
        if abs_sag < 1:
            continue
        # Only label slope bends — skip near local temperature extrema
        local_slice = col_temps[max(0, i - min_gap):min(n, i + min_gap + 1)]
        local_hi, local_lo = max(local_slice), min(local_slice)
        band = (local_hi - local_lo) * 0.15
        if col_temps[i] > local_hi - band or col_temps[i] < local_lo + band:
            continue
        # Must be a local maximum of |sagitta|
        if any(abs(sagittas[j]) > abs_sag
               for j in range(i - detect_r, i + detect_r + 1)):
            continue
        # Concave up (sag<0, elbow) → label above; concave down (sag>0) → below
        is_peak = sagittas[i] < 0
        scored.append((i, col_temps[i], is_peak, abs_sag))

    # --- Greedily place from highest to lowest score ---
    for x, temp, is_peak, score in sorted(scored, key=lambda c: -c[3]):
        if any(abs(x - ex) < min_gap for ex, _, _ in extrema):
            continue
        # Skip if a nearby label already shows the same rounded temperature
        label_int = int(round(temp))
        if any(abs(x - ex) < min_gap * 3 and int(round(t)) == label_int
               for ex, t, _ in extrema):
            continue
        extrema.append((x, temp, is_peak))

    return extrema


def _render_today_line(width, chart_lo, chart_hi, midnight_day_names, sun_labels, runtime,
                       window_dts=None, now=None, offset_minutes=0):
    """Render the hourly section header with day and sun-event labels."""
    # Show "Today" only when the window starts on today's date;
    # otherwise show the actual day name so scrolled views make sense.
    lang = getattr(runtime, "lang", "en") if runtime else "en"
    if window_dts and now and window_dts[0].date() != now.date():
        day_name = FULL_DAY_NAMES.get(lang, FULL_DAY_NAMES["en"])[window_dts[0].weekday()]
        today_left = f" {TEXT}{day_name}"
    else:
        today_left = f" {TEXT}{_s('today', runtime)}"
    if offset_minutes:
        hint_text = _s("space_to_now", runtime)
        today_right = f"{DIM}{hint_text}"
    else:
        today_right = (
            f"{_colored_temp(chart_lo, runtime, '°')} "
            f"{TEXT}\u2192 {_colored_temp(chart_hi, runtime, runtime.temp_unit)}"
        )
    if not (midnight_day_names or sun_labels):
        pad = width - visible_len(today_left) - visible_len(today_right) - 2
        return f"{today_left}{' ' * max(1, pad)}{today_right} {RESET}"

    label_start = visible_len(today_left)

    # Drop the "today" label if it would crowd out a midnight day name
    if midnight_day_names:
        first_col = min(midnight_day_names)
        if first_col + 1 < label_start:
            today_left = " "
            label_start = 1
    right_len = visible_len(today_right) + 2
    avail = width - right_len
    mid_w = max(0, avail - label_start)

    mid_canvas = [" "] * mid_w
    mid_colors = [None] * mid_w

    for col, name in sorted(midnight_day_names.items()):
        pos = col + 1 - label_start
        name_w = visible_len(name)
        if pos >= 0 and pos + name_w <= mid_w:
            cx = pos
            for c in name:
                mid_canvas[cx] = c
                cw = visible_len(c)
                for k in range(1, cw):
                    if cx + k < mid_w:
                        mid_canvas[cx + k] = ""
                cx += cw

    for col, (lbl, is_rise) in sorted(sun_labels.items()):
        pos = max(0, col + 1 - label_start)
        lbl_w = visible_len(lbl)
        if pos + lbl_w > mid_w:
            continue
        if all(mid_canvas[pos + j] == " " for j in range(lbl_w)):
            color = SUNRISE_LABEL_RGB if is_rise else SUNSET_LABEL_RGB
            cx = pos
            for c in lbl:
                mid_canvas[cx] = c
                mid_colors[cx] = color
                cw = visible_len(c)
                for k in range(1, cw):
                    if cx + k < mid_w:
                        mid_canvas[cx + k] = ""
                        mid_colors[cx + k] = color
                cx += cw

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


def _compute_extrema_overlays(extrema, col_temps, n_rows, graph_w, runtime, value_range=None):
    """Map temperature extrema to overlay labels on specific braille rows."""
    if not extrema or n_rows < 1:
        return {}

    if value_range is not None:
        t_min, t_max = value_range
    else:
        t_min, t_max = min(col_temps), max(col_temps)
    total_dots = n_rows * 4
    overlays = {}  # row_idx -> [(start_col, label_text, (r, g, b)), ...]
    occupied_by_row = {}

    sorted_extrema = sorted(extrema, key=lambda e: -e[1] if e[2] else e[1])

    for x, temp, is_peak in sorted_extrema:
        if t_max == t_min:
            curve_row = n_rows // 2
        else:
            y = (total_dots - 1) * (1 - (temp - t_min) / (t_max - t_min))
            curve_row = max(0, min(n_rows - 1, int(round(y)) // 4))

        if is_peak:
            label_row = max(0, curve_row - 1)
        else:
            label_row = min(n_rows - 1, curve_row + 1)

        label = f"{temp:.0f}\u00b0"
        start = max(0, min(graph_w - len(label), x - len(label) // 2))

        if label_row not in occupied_by_row:
            occupied_by_row[label_row] = set()
        cols = set(range(start, start + len(label)))
        if cols & occupied_by_row[label_row]:
            continue
        occupied_by_row[label_row] |= cols

        color = _temp_color(temp, runtime)
        overlays.setdefault(label_row, []).append((start, label, color))

    return overlays


def _render_braille_rows(braille_rows, col_daylight, midnight_cols, runtime,
                         overlays=None, hover_col=None):
    """Render braille temperature rows with optional day/night shading."""
    if overlays is None:
        overlays = {}
    shading = runtime.shading
    night_dim = 0.6
    midnight_fg = DIM
    hover_fg = fg(*CHART_HOVER_RGB)
    bg_night = CHART_BG_NIGHT_RGB
    bg_day = CHART_BG_DAY_RGB

    lines = []
    for row_idx, row in enumerate(braille_rows):
        # Build overlay char map for this row
        overlay_chars = {}
        for start_col, label, color in overlays.get(row_idx, []):
            for j, c in enumerate(label):
                col = start_col + j
                if 0 <= col < len(row):
                    overlay_chars[col] = (c, color)

        line = " "
        for ci, (ch, temp) in enumerate(row):
            dl = col_daylight[ci] if ci < len(col_daylight) else 1.0

            if ci in overlay_chars:
                oc, oc_color = overlay_chars[ci]
                if shading:
                    br = int(bg_night[0] + (bg_day[0] - bg_night[0]) * dl)
                    bg_g = int(bg_night[1] + (bg_day[1] - bg_night[1]) * dl)
                    bb = int(bg_night[2] + (bg_day[2] - bg_night[2]) * dl)
                    bg_str = bg(br, bg_g, bb)
                    line += f"{bg_str}{fg(*oc_color)}{oc}{RESET}"
                else:
                    line += f"{fg(*oc_color)}{oc}"
                continue

            # Pick indicator color for empty cells (hover > midnight)
            indicator = None
            if ch == '\u2800':
                if hover_col is not None and ci == hover_col:
                    indicator = hover_fg
                elif ci in midnight_cols:
                    indicator = midnight_fg

            if shading:
                br = int(bg_night[0] + (bg_day[0] - bg_night[0]) * dl)
                bg_g = int(bg_night[1] + (bg_day[1] - bg_night[1]) * dl)
                bb = int(bg_night[2] + (bg_day[2] - bg_night[2]) * dl)
                bg_str = bg(br, bg_g, bb)

                if indicator:
                    line += f"{bg_str}{indicator}\u2502{RESET}"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    line += f"{bg_str}{fg(r, g, b)}{ch}{RESET}"
            else:
                if indicator:
                    line += f"{indicator}\u2502"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    brightness = night_dim + (1.0 - night_dim) * dl
                    line += f"{fg(int(r * brightness), int(g * brightness), int(b * brightness))}{ch}"
        lines.append(f"{line}{RESET}")
    return lines


def _render_tick_labels(window_dts, total_hours, graph_w, runtime=None, hover_col=None):
    """Render compact timeline tick labels under the chart.

    Labels are anchored to clock-aligned hours so they scroll with the data
    rather than staying at fixed screen positions.
    """
    if not window_dts:
        return None
    use_24h = runtime.use_24h if runtime else False
    if graph_w < 40:
        interval = 6
    elif graph_w < 80:
        interval = 4
    elif graph_w < 140:
        interval = 3
    else:
        interval = 2

    t0 = window_dts[0]
    # Find first clock-aligned hour that falls within the window
    first_hour = t0.replace(minute=0, second=0, microsecond=0)
    if first_hour < t0:
        first_hour += timedelta(hours=1)
    # Round up to next multiple of interval
    remainder = first_hour.hour % interval
    if remainder != 0:
        first_hour += timedelta(hours=interval - remainder)

    label_items = []
    dt = first_hour
    end_dt = t0 + timedelta(hours=total_hours)
    while dt <= end_dt:
        h_off = (dt - t0).total_seconds() / 3600
        x = int(h_off / total_hours * (graph_w - 1)) if total_hours > 0 else 0
        if 0 <= x < graph_w:
            label_items.append((x, fmt_hour(dt.hour, use_24h), dt.hour == 0))
        dt += timedelta(hours=interval)

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
    return f" {DIM}{''.join(canvas)}{RESET}"


def _render_wind_row(window_winds, window_wind_dirs, total_hours, graph_w, runtime,
                     midnight_cols=None, hover_col=None):
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
    if not any(c != " " for c in wind_canvas):
        return None

    # Build output with indicator lines in empty cells
    hover_fg = fg(*CHART_HOVER_RGB)
    midnight_fg = DIM
    parts = [" "]
    in_wind = False
    for x, ch in enumerate(wind_canvas):
        if ch != " ":
            if not in_wind:
                parts.append(WIND_COLOR)
                in_wind = True
            parts.append(ch)
        else:
            indicator = None
            if hover_col is not None and x == hover_col:
                indicator = hover_fg
            elif midnight_cols and x in midnight_cols:
                indicator = midnight_fg
            if indicator:
                if in_wind:
                    in_wind = False
                parts.append(f"{indicator}\u2502")
            else:
                if not in_wind:
                    parts.append(WIND_COLOR)
                    in_wind = True
                parts.append(" ")
    parts.append(RESET)
    return "".join(parts)


def _render_uv_row(window_uv, total_hours, graph_w, runtime,
                    midnight_cols=None, hover_col=None):
    """Render UV index labels at positions where UV is remarkable (>= 6)."""
    if not window_uv or max(window_uv, default=0) < 6:
        return None

    uv_canvas = [" "] * graph_w
    sample_interval = max(1, int(3 / total_hours * (graph_w - 1))) if total_hours > 0 else 6
    col_uv = _interpolate_columns(window_uv, graph_w)
    for x in range(0, graph_w, max(1, sample_interval)):
        uv = col_uv[x]
        if uv < 6:
            continue
        label = f"{_s('uv', runtime)}{uv:.0f}"
        start = max(0, x - len(label) // 2)
        if start + len(label) > graph_w:
            start = graph_w - len(label)
        if all(uv_canvas[start + j] == " " for j in range(len(label)) if start + j < graph_w):
            for j, ch in enumerate(label):
                if start + j < graph_w:
                    uv_canvas[start + j] = ch
    if not any(c != " " for c in uv_canvas):
        return None

    hover_fg = fg(*CHART_HOVER_RGB)
    midnight_fg = DIM
    parts = [" "]
    in_uv = False
    for x, ch in enumerate(uv_canvas):
        if ch != " ":
            if not in_uv:
                parts.append(UV_COLOR)
                in_uv = True
            parts.append(ch)
        else:
            indicator = None
            if hover_col is not None and x == hover_col:
                indicator = hover_fg
            elif midnight_cols and x in midnight_cols:
                indicator = midnight_fg
            if indicator:
                if in_uv:
                    in_uv = False
                parts.append(f"{indicator}\u2502")
            else:
                if not in_uv:
                    parts.append(UV_COLOR)
                    in_uv = True
                parts.append(" ")
    parts.append(RESET)
    return "".join(parts)


def _render_precip_rows(window_precip, window_codes, graph_w, n_precip_rows, indicator_cols=None):
    """Render precipitation probability graph rows."""
    if not window_precip or max(window_precip, default=0) <= 5:
        return []
    if n_precip_rows >= 1:
        return _build_precip_blocks(window_precip, window_codes, graph_w, n_precip_rows,
                                    indicator_cols=indicator_cols)

    precip_chars = []
    col_precip = _interpolate_columns(window_precip, graph_w)
    for x, p in enumerate(col_precip):
        if p <= 5:
            if indicator_cols and x in indicator_cols:
                precip_chars.append(f"{DIM}\u2502")
            else:
                precip_chars.append(" ")
            continue
        code_t = x / max(1, graph_w - 1) * max(0, len(window_codes) - 1)
        code_i = max(0, min(len(window_codes) - 1, int(round(code_t))))
        wmo = window_codes[code_i] if window_codes else 0
        color = _precip_color(wmo)
        idx = max(0, min(7, int(p / 100 * 7.99)))
        precip_chars.append(f"{color}{SPARKLINE[idx]}")
    return [f" {''.join(precip_chars)}{RESET}"]


def render_hourly(data, width, n_braille_rows=2, n_precip_rows=0, now=None, runtime=None, hover_col=None, offset_minutes=0):
    """Hourly forecast: braille temperature curve + precipitation graph."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    daily = data.get("daily", {})
    sun_events = _parse_sun_events(daily)
    if now is None:
        now = _local_now_for_data(data)

    graph_w = max(10, width - 2)
    window = _prepare_hourly_window(data.get("hourly", {}), now, graph_w, offset_minutes=offset_minutes)
    if window is None:
        return []

    window_temps = window["temps"]
    window_precip = window["precip"]
    window_codes = window["codes"]
    window_winds = window["winds"]
    window_wind_dirs = window["wind_dirs"]
    window_dts = window["dts"]
    total_hours = window["total_hours"]
    all_temp_range = window.get("all_temp_range")
    chart_lo = min(window_temps)
    chart_hi = max(window_temps)

    midnight_cols, _noon_cols, midnight_day_names = _compute_time_markers(
        window_dts, total_hours, graph_w, runtime
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
            window_dts=window_dts,
            now=now,
            offset_minutes=offset_minutes,
        )
    ]

    tick_line = _render_tick_labels(window_dts, total_hours, graph_w, runtime, hover_col=hover_col)
    if tick_line:
        lines.append(tick_line)

    braille_rows = build_braille_curve(window_temps, graph_w, n_braille_rows,
                                       value_range=all_temp_range)
    overlays = _compute_extrema_overlays(extrema, col_temps, n_braille_rows, graph_w, runtime,
                                          value_range=all_temp_range)
    lines.extend(_render_braille_rows(braille_rows, col_daylight, midnight_cols, runtime, overlays,
                                       hover_col=hover_col))

    window_uv = window.get("uv", [])
    wind_threshold = 25 if runtime.metric else 15
    has_global_wind = window.get("all_wind_max", 0) > wind_threshold
    has_global_uv = window.get("all_uv_max", 0) >= 6
    has_global_precip = window.get("all_precip_max", 0) > 5

    wind_line = _render_wind_row(window_winds, window_wind_dirs, total_hours, graph_w, runtime,
                                 midnight_cols=midnight_cols, hover_col=hover_col)
    uv_line = _render_uv_row(window_uv, total_hours, graph_w, runtime,
                              midnight_cols=midnight_cols, hover_col=hover_col)

    # Always reserve rows for wind/UV/precip if they appear anywhere in the
    # full dataset, so the chart height stays stable while scrolling.
    if wind_line:
        lines.append(wind_line)
    elif has_global_wind:
        lines.append("")
    if uv_line:
        lines.append(uv_line)
    elif has_global_uv:
        lines.append("")

    # Indicator columns for precip: midnight dividers + hover
    indicator_cols = set(midnight_cols)
    if hover_col is not None:
        indicator_cols.add(hover_col)
    precip_lines = _render_precip_rows(window_precip, window_codes, graph_w, n_precip_rows,
                                       indicator_cols=indicator_cols if indicator_cols else None)
    if precip_lines:
        lines.extend(precip_lines)
    elif has_global_precip and n_precip_rows >= 1:
        lines.extend([""] * n_precip_rows)
    return lines
