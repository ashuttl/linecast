"""Shared rendering helpers for tides chart layout."""

from datetime import timedelta

from linecast._graphics import RESET, bg, fg, fmt_hour, fmt_time_dt, visible_len
from linecast._tides_i18n import FULL_DAY_NAMES
from linecast.sunshine import daylight_factor as solar_daylight_factor

DIM = fg(70, 80, 100)


def interp_height(target_dt, predictions):
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


def prepare_tide_window(predictions, hilo, start_dt, hours_shown=24):
    """Slice prediction data to a visible window starting at start_dt."""
    end_dt = start_dt + timedelta(hours=hours_shown)
    margin = timedelta(minutes=10)
    win_preds = [(dt, h) for dt, h in predictions if start_dt - margin <= dt <= end_dt + margin]
    win_hilo = [(dt, h, t) for dt, h, t in hilo if start_dt <= dt <= end_dt]
    return {
        "predictions": win_preds,
        "hilo": win_hilo,
        "start": start_dt,
        "end": end_dt,
        "total_hours": hours_shown,
    }


def _solar_daylight_at(hour, doy, lat, lng, tz_offset_h):
    """Compute daylight factor (0.0-1.0) at a local clock hour on a given day."""
    return solar_daylight_factor(hour, doy, lat, lng, tz_offset_h)


def compute_daylight_window(graph_w, window_start, total_hours, station_meta):
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


def compute_time_markers(window_start, total_hours, graph_w, runtime):
    """Compute midnight column positions and day labels for the window."""
    lang = runtime.lang if runtime else "en"
    midnight_cols = set()
    midnight_day_names = {}

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


def render_tide_ticks(window_start, total_hours, graph_w, runtime, now_col=None, hover_col=None):
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

    window_secs = total_hours * 3600
    label_items = []
    if window_secs > 0:
        interval_secs = interval * 3600
        elapsed_secs = (
            window_start.hour * 3600
            + window_start.minute * 60
            + window_start.second
            + window_start.microsecond / 1_000_000
        )
        first_offset_secs = (interval_secs - (elapsed_secs % interval_secs)) % interval_secs
        tick_dt = window_start + timedelta(seconds=first_offset_secs)
        window_end = window_start + timedelta(hours=total_hours)

        while tick_dt <= window_end:
            offset_secs = (tick_dt - window_start).total_seconds()
            x = int(offset_secs / window_secs * (graph_w - 1))
            if 0 <= x < graph_w:
                label_items.append(
                    (x, fmt_hour(tick_dt.hour, use_24h), tick_dt.hour == 0 and tick_dt.minute == 0)
                )
            tick_dt += timedelta(seconds=interval_secs)

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


def render_day_label_line(midnight_day_names, graph_w):
    """Render day name labels on their own row, aligned with chart columns."""
    muted = fg(100, 110, 130)
    canvas = [" "] * graph_w
    for col, day_name in sorted(midnight_day_names.items()):
        pos = col + 1
        for j, c in enumerate(day_name):
            if 0 <= pos + j < graph_w:
                canvas[pos + j] = c
    return f" {muted}{''.join(canvas)}{RESET}"


def build_tide_hover_tooltip(window, graph_col, mouse_row, chart_start, chart_end, cols, rows, graph_w, runtime):
    """Build cursor-positioned tooltip overlay for mouse hover on the chart."""
    line_idx = mouse_row - 1
    if not (chart_start <= line_idx < chart_end):
        return ""
    if graph_col < 0 or graph_col >= graph_w:
        return ""

    predictions = window["predictions"]
    if not predictions:
        return ""

    total_hours = window["total_hours"]
    start_dt = window["start"]

    t_frac = graph_col / max(1, graph_w - 1)
    target_dt = start_dt + timedelta(hours=t_frac * total_hours)
    height = interp_height(target_dt, predictions)

    tip_bg = bg(0, 0, 0)
    tip_fg = fg(200, 205, 215)

    time_str = fmt_time_dt(target_dt, use_24h=runtime.use_24h)
    h_display = runtime.convert_height(height)

    tip_lines = [
        f"{tip_bg}{tip_fg} {time_str} ",
        f"{tip_bg}{tip_fg} {h_display:.1f}{runtime.height_unit} ",
    ]

    max_w = max(visible_len(line) for line in tip_lines)
    padded = []
    for line in tip_lines:
        pad = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad}{RESET}")

    snap_col = graph_col + 2
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
