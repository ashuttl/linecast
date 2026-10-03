"""The tide chart's parts, which tides/view.py lays out: the window of
predictions a frame shows and the height at any moment in it, the
daylight shading, the midnight dividers and the day names, the moon's
rises and sets, the hour ticks, and the now and hover chips."""

from datetime import timedelta, timezone

from linecast.terminal.chart import tick_canvas, tick_interval
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.textwidth import cells as text_cells, visible_len
from linecast._timefmt import fmt_hour, fmt_time_dt
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast._log import log_failure
from linecast._i18n import FULL_DAY_NAMES
from linecast.astro.ephemeris import _moon_events_for_local_date
from linecast.sunshine.solar import daylight_factor as solar_daylight_factor
from linecast.moon.phase import moon_phase
from linecast._i18n import fmt_decimal, table_for

from linecast.tides.palette import (
    DIM, MOON_RISE_RGB, MOON_SET_RGB, MUTED_RGB, TIP_BG_RGB, TIP_TEXT_RGB,
)

_theme.track_imports(globals(), "linecast.tides.palette")


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
    except (KeyError, TypeError, ValueError) as exc:
        log_failure("tides", "daylight window", exc, fallback="no night shading")
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
        # The clock the column is read on: summer time where the station
        # keeps it, which the metadata's standard offset does not know.
        offset = col_dt.utcoffset()
        tz_h = tz_offset_h if offset is None else offset.total_seconds() / 3600
        col_daylight.append(_solar_daylight_at(hour, doy, lat, lng, tz_h))
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
            day_names = table_for(FULL_DAY_NAMES, lang)
            midnight_day_names[x] = day_names[dt.weekday()]
        dt += timedelta(days=1)

    return midnight_cols, midnight_day_names


def compute_moon_labels(window_start, total_hours, graph_w, station_meta, runtime):
    """Compute moonrise/moonset labels mapped to graph columns."""
    if total_hours <= 0 or graph_w < 3 or not station_meta:
        return {}

    try:
        lat = float(station_meta["lat"])
        lng = float(station_meta["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        log_failure("tides", "moon labels", exc, fallback="labels omitted")
        return {}

    tzinfo = window_start.tzinfo
    if tzinfo is None:
        try:
            tzinfo = timezone(timedelta(hours=float(station_meta.get("timezonecorr"))))
        except (TypeError, ValueError) as exc:
            log_failure("tides", "moon labels", exc, fallback="labels omitted")
            return {}
        local_start = window_start.replace(tzinfo=tzinfo)
    else:
        local_start = window_start.astimezone(tzinfo)

    local_end = local_start + timedelta(hours=total_hours)
    labels = {}
    use_24h = bool(getattr(runtime, "use_24h", False))

    day = local_start.date() - timedelta(days=1)
    last_day = local_end.date() + timedelta(days=1)
    while day <= last_day:
        rise_dt, set_dt = _moon_events_for_local_date(day, lat, lng, tzinfo)
        for event_dt, is_rise in ((rise_dt, True), (set_dt, False)):
            if event_dt is None:
                continue
            off_h = (event_dt - local_start).total_seconds() / 3600.0
            if 0 < off_h < total_hours:
                col = int(off_h / total_hours * (graph_w - 1))
                if 0 < col < graph_w - 1:
                    _idx, _name, phase_icon = moon_phase(
                        event_dt.astimezone(timezone.utc),
                        runtime,
                        bg_color=_theme.theme_bg,
                    )
                    arrow = "↑" if is_rise else "↓"
                    labels[col] = (
                        f"{phase_icon}{arrow}{fmt_time_dt(event_dt, use_24h=use_24h)}",
                        is_rise,
                    )
        day += timedelta(days=1)

    return labels


def render_tide_ticks(window_start, total_hours, graph_w, runtime, now_col=None, hover_col=None):
    """Render time axis labels under the chart."""
    use_24h = runtime.use_24h
    interval = tick_interval(graph_w * 24 / total_hours) if total_hours > 0 else 6

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

    return f"{DIM}{tick_canvas(label_items, graph_w, hover_col, now_col)}{RESET}"


def render_day_label_line(midnight_day_names, graph_w, moon_labels=None):
    """Render day and moon-event labels on their own row."""
    if moon_labels is None:
        moon_labels = {}

    muted = fg(*MUTED_RGB)
    rise_color = MOON_RISE_RGB
    set_color = MOON_SET_RGB
    canvas = [" "] * graph_w
    canvas_colors = [None] * graph_w

    def _draw_label(start, text, color=None, allow_overlap=False):
        laid, width = text_cells(text)
        if start < 0 or start + width > graph_w:
            return False
        if not allow_overlap and any(canvas[start + i] != " " for i in range(width)):
            return False
        for c, glyph in laid:
            canvas[start + c] = glyph
            canvas_colors[start + c] = color
        return True

    def _find_open_slot(
        preferred_start,
        text,
        prefer_forward=True,
        pad_mask=None,
        min_pad=0,
    ):
        """Find an open slot for text, preferring movement to the right."""
        width = visible_len(text)
        if width <= 0 or width > graph_w:
            return None

        lo = 0
        hi = graph_w - width
        start = max(lo, min(hi, preferred_start))

        def _open(slot):
            if not all(canvas[slot + i] == " " for i in range(width)):
                return False
            if pad_mask is None or min_pad <= 0:
                return True

            left = max(0, slot - min_pad)
            right = min(graph_w - 1, slot + width - 1 + min_pad)
            for i in range(left, right + 1):
                if slot <= i < slot + width:
                    continue
                if pad_mask[i]:
                    return False
            return True

        if _open(start):
            return start

        if prefer_forward:
            for slot in range(start + 1, hi + 1):
                if _open(slot):
                    return slot
            for slot in range(start - 1, lo - 1, -1):
                if _open(slot):
                    return slot
        else:
            for slot in range(start - 1, lo - 1, -1):
                if _open(slot):
                    return slot
            for slot in range(start + 1, hi + 1):
                if _open(slot):
                    return slot
        return None

    for col, day_name in sorted(midnight_day_names.items()):
        _draw_label(col + 1, day_name, color=None, allow_overlap=True)

    day_mask = [cell != " " for cell in canvas]

    for col, (label, is_rise) in sorted(moon_labels.items()):
        color = rise_color if is_rise else set_color
        preferred = max(0, col + 1)
        slot = _find_open_slot(
            preferred,
            label,
            prefer_forward=True,
            pad_mask=day_mask,
            min_pad=1,
        )
        if slot is not None:
            _draw_label(slot, label, color=color, allow_overlap=False)

    line = muted
    current_color = None
    for i in range(graph_w):
        color = canvas_colors[i]
        if color != current_color:
            line += muted if color is None else fg(*color)
            current_color = color
        line += canvas[i]
    if current_color is not None:
        line += muted
    return f"{line}{RESET}"


def build_now_tooltip(now_col, now_info, chart_start, cols):
    """Build cursor-positioned tooltip at the top of the now indicator line."""
    if now_col is None or now_info is None:
        return ""

    time_str, height, unit = now_info

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)

    tip_lines = [
        f"{tip_bg}{tip_fg} {time_str} ",
        f"{tip_bg}{tip_fg} {height}{unit} ",
    ]
    # At the top of the chart (a 0-based line, so +1 for the terminal's
    # row), just right of the now column (+1 for 1-based columns, +1 to
    # sit beside it).
    return _live.chip_at(tip_lines, chart_start + 1, now_col + 2, cols)


def build_tide_hover_tooltip(window, graph_col, mouse_row, chart_start, chart_end,
                             cols, rows, graph_w, runtime):
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

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)

    time_str = fmt_time_dt(target_dt, use_24h=runtime.use_24h)
    h_display = runtime.convert_height(height)

    tip_lines = [
        f"{tip_bg}{tip_fg} {time_str} ",
        f"{tip_bg}{tip_fg} {fmt_decimal(h_display, 1, runtime)}{runtime.height_unit} ",
    ]

    return _live.pointer_chip(tip_lines, graph_col + 1, mouse_row, cols, rows,
                              pad_bg=tip_bg)
