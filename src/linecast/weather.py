#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, a line or two of prose, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts sourced from NWS (US), Environment Canada (CA), Bright Sky/DWD (DE),
MET Norway (NO), Met \u00c9ireann (IE), JMA (Japan), CMA (China),
MetService (NZ), and MeteoAlarm (34 European countries).

Languages: en, fr, es, de, it, pt, nl, pl, no, sv, is, da, fi, id, ja, ko, zh, th

Usage: weather [--print] [--oneline] [--json] [--location LAT,LNG | PLACE] [--search CITY]
               [--icons SET] [--emoji] [--metric] [--imperial] [--12h] [--24h]
               [--celsius] [--fahrenheit]
               [--no-shading] [--lang fr] [--classic-colors]
"""

import math
import sys
import threading
import time as _t
from datetime import datetime

from linecast import _live, _theme
from linecast._graphics import bg, fg, get_terminal_size
from linecast._location import country_for_defaults, resolve_location
from linecast._runtime import (
    WeatherRuntime, install_banner, log_failure, set_current, weather_parser,
)
from linecast._weather_i18n import (
    FULL_DAY_NAMES,
    WMO_NAMES,
    WMO_NAMES_I18N,
    _s,
    _wmo_icons,
    has_string,
)
from linecast._weather_hourly import _precip_bar_full
from linecast._weather_render import (
    ALERT_AMBER,
    CLOUD_RGB,
    DIM,
    MUTED,
    RESET,
    TEXT,
    TOOLTIP_BG_RGB,
    TOOLTIP_TEXT_RGB,
    WIND_ARROWS,
    _colored_temp,
    _PRECIP_CODES,
    _fmt_time,
    _precip_rgb,
    _precip_type,
    _prepare_hourly_window,
    build_alert_modal,
    fmt_precip_amount,
    narrative_lines,
    render_alerts_mapped,
    render_daily_mapped,
    render_header,
    render_hourly,
)
from linecast._weather_historical import fetch_historical
from linecast._weather_sources import (
    _local_now_for_data,
    _reverse_geocode,
    _search_locations,
    alert_attribution,
    apply_india_aqi,
    fetch_aqi,
    fetch_alerts,
    fetch_forecast,
    forecast_attribution,
    forecast_date,
    forecast_is_todays,
)

# What the dashboard keeps when the window is too short for all of it:
# the graph is the view -- its day line, its ticks and two rows of braille
# -- and three days is still a forecast.
MIN_HOURLY_ROWS = 4
MIN_DAILY_ROWS = 3
MIN_CURVE_ROWS_WITH_CLOUD = 4  # the cloud strip appears only above this
CURVE_ROWS_COMFORTABLE = 6     # below this the spacing rows give way
MAX_PRECIP_ROWS = 3            # the precipitation bar at its tallest


def data_credits(country_code="", lang="en"):
    """The data credits, longest first: the forecast's with the alerts'
    when a service supplies them, then the forecast's alone."""
    forecast = forecast_attribution(lang)
    alerts = alert_attribution(country_code, lang)
    return (f"{forecast} · {alerts}", forecast) if alerts else (forecast,)


def credit_row(cols, lang, country_code=""):
    """The live view's last row: the data credit at the left, in ink
    fainter than the prose above it, and the help hint at the right.
    The longest credit that leaves the whole hint its room wins; a
    window too narrow for any shows the hint alone."""
    from linecast import _help
    from linecast._graphics import visible_len
    hint = _help.hint(lang)
    for credit in data_credits(country_code, lang):
        if visible_len(credit) + 2 + visible_len(hint) <= cols:
            return _help.footer(f"{DIM}{credit}{RESET}", cols, lang)
    return _help.footer("", cols, lang)


def _build_hover_tooltip(data, mouse_col, mouse_row, hourly_start, hourly_end, cols, rows,
                         runtime, offset_minutes=0):
    """Build a tooltip overlay for mouse hover on the hourly chart.

    Returns cursor-positioned escape sequences to draw the tooltip, or "".
    mouse_col/mouse_row are 1-based terminal coordinates.
    hourly_start/hourly_end are 0-based line indices in the output.
    """
    # Check if mouse is over the hourly section (convert 1-based row to 0-based)
    line_idx = mouse_row - 1
    if not (hourly_start <= line_idx < hourly_end):
        return ""

    graph_w = max(10, cols)
    graph_col = mouse_col - 1  # 1-based terminal col → 0-based graph col
    if graph_col < 0 or graph_col >= graph_w:
        return ""

    hourly = data.get("hourly", {})
    now = _local_now_for_data(data)
    window = _prepare_hourly_window(hourly, now, graph_w, runtime,
                                    offset_minutes=offset_minutes)
    if window is None:
        return ""

    # Map graph column to nearest hour index (use int() to match midnight divider formula)
    n = len(window["temps"])
    total_hours = window["total_hours"]
    idx = int(graph_col / max(1, graph_w - 1) * total_hours + 0.5)
    idx = max(0, min(n - 1, idx))

    dt = window["dts"][idx] if idx < len(window["dts"]) else None
    temp = window["temps"][idx]
    apparent = (window["apparent_temps"][idx]
                if idx < len(window.get("apparent_temps", [])) else None)
    code = window["codes"][idx] if idx < len(window["codes"]) else 0
    wind = window["winds"][idx] if idx < len(window["winds"]) else 0
    wind_dir = window["wind_dirs"][idx] if idx < len(window["wind_dirs"]) else 0
    humidity = window["humidity"][idx] if idx < len(window.get("humidity", [])) else None
    dew = window["dew_points"][idx] if idx < len(window.get("dew_points", [])) else None
    amount = window["precip_amount"][idx] if idx < len(window.get("precip_amount", [])) else 0
    prob = window["precip"][idx] if idx < len(window.get("precip", [])) else 0
    cloud = window["cloud"][idx] if idx < len(window.get("cloud", [])) else None

    TBG = bg(*TOOLTIP_BG_RGB)
    TFG = fg(*TOOLTIP_TEXT_RGB)

    lines = []

    # Time
    if dt:
        time_str = _fmt_time(dt, use_24h=runtime.use_24h)
        lines.append(f"{TBG}{TFG} {time_str} ")

    # Temperature + feels like
    deg = "\u00b0"
    temp_line = f"{TBG} {_colored_temp(temp, runtime, deg)}"
    if apparent is not None and abs(apparent - temp) >= 3:
        temp_line += f" {TFG}{_s('feels', runtime)} {_colored_temp(apparent, runtime, deg)}"
    temp_line += " "
    lines.append(temp_line)

    # Weather description
    wmo_name = WMO_NAMES_I18N.get(runtime.lang, {}).get(code) or WMO_NAMES.get(code, "")
    if wmo_name:
        lines.append(f"{TBG}{_conditions_ink(code, TFG)} {wmo_name} ")

    # Humidity / dew point (when notable)
    if humidity is not None and dew is not None:
        dew_f = dew * 9 / 5 + 32 if runtime.celsius else dew
        if dew_f >= 60:
            lines.append(f"{TBG}{TFG} {_s('dew_pt', runtime)} {_colored_temp(dew, runtime, deg)} ")
        elif humidity >= 70 or humidity <= 25:
            lines.append(f"{TBG}{TFG} {_s('humidity', runtime)} {humidity:.0f}% ")

    # Precipitation: the hour's amount, and its chance in the very shade
    # the bar below is drawn in, so the chip teaches what the fade means.
    precip_parts = []
    if amount and amount > 0:
        precip_parts.append(f"{fg(*_precip_rgb(code))}{fmt_precip_amount(amount, runtime)}{TFG}")
    # Under 20% the shaded figure is hard to read and says nothing worth
    # reading; the bar below is a ghost of one anyway.
    if prob and prob >= 20:
        precip_parts.append(_s("chance", runtime, p=f"{_precip_shade(code, prob)}{prob:.0f}%{TFG}"))
    if precip_parts:
        lines.append(f"{TBG}{TFG} {'  '.join(precip_parts)} ")

    # Cloud cover, in the shade of the strip
    if cloud is not None and cloud >= 10:
        shaded = f"{_cloud_shade(cloud)}{cloud:.0f}%{TFG}"
        lines.append(f"{TBG}{TFG} {_s('cloud', runtime, p=shaded)} ")

    # Wind (if notable)
    wind_threshold = 25 if runtime.metric else 15
    if wind > wind_threshold:
        sector = int((wind_dir + 22.5) / 45) % 8
        arrow = WIND_ARROWS[sector]
        lines.append(f"{TBG}{TFG} {arrow} {wind:.0f}{runtime.wind_unit} ")

    if not lines:
        return ""

    # Snapped hour column (1-based terminal col) — use int() to match midnight divider formula
    snap_col = int(idx / max(1, total_hours) * (graph_w - 1)) + 1

    return _live.pointer_chip(lines, snap_col, mouse_row, cols, rows, pad_bg=TBG)


def _conditions_ink(code, text_fg):
    """The color to name the weather in: the precipitation type's, so a
    thunderstorm is in the bar's storm yellow and snow in its white, and
    the plain text color for anything dry."""
    return fg(*_precip_rgb(code)) if code in _PRECIP_CODES else text_fg


def _precip_shade(code, prob):
    """The precipitation bar's color for this chance: its type faded
    toward the background, as _precip_columns draws it."""
    return fg(*_theme.lerp_rgb(_theme.theme_bg, _precip_rgb(code), max(0.0, min(1.0, prob / 100))))


def _cloud_shade(cover):
    """The cloud strip's color for this cover, as _render_cloud_row draws it."""
    return fg(*_theme.lerp_rgb(_theme.theme_bg, CLOUD_RGB, max(0.0, min(1.0, cover / 100))))


def _precip_kind_lower(code, runtime):
    """The precipitation type as a word mid-sentence: "rain", not "Rain",
    where the language has the lowercase form, and the row label otherwise."""
    kind = _precip_type(code)
    return _s(kind.lower(), runtime) if has_string(kind.lower()) else _s(kind, runtime)


def _build_daily_tooltip(data, mouse_col, mouse_row, daily_start, daily_spans, cols, rows,
                         runtime):
    """A chip for the part of a daily row under the pointer.

    Each part of the row answers for itself: the day's name and icon give
    the day and its weather, the bar the high and low and when they come,
    the odds and the amount together the day's total, its chance, the
    hours with rain and the heaviest of them, the wind its speed and
    gusts.  Returns
    cursor-positioned escapes, or "" when the pointer is elsewhere.
    mouse_col/mouse_row are 1-based terminal coordinates; daily_start is
    the 0-based line index of the first daily row.
    """
    k = mouse_row - 1 - daily_start
    if not (0 <= k < len(daily_spans)):
        return ""
    span = daily_spans[k]
    col = mouse_col - 1
    field = next((name for name, (a, b) in span["cols"].items() if a <= col < b), None)
    if field is None:
        return ""

    i = span["index"]
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})

    def day_value(key, default=None):
        values = daily.get(key) or []
        return values[i] if i < len(values) else default

    date = day_value("time", "")
    hours = [j for j, t in enumerate(hourly.get("time") or []) if str(t).startswith(str(date))]

    def hour_values(key):
        values = hourly.get(key) or []
        return [(j, values[j]) for j in hours if j < len(values) and values[j] is not None]

    def when(j):
        try:
            dt = datetime.fromisoformat(hourly["time"][j])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return _fmt_time(dt, use_24h=runtime.use_24h)

    TBG = bg(*TOOLTIP_BG_RGB)
    TFG = fg(*TOOLTIP_TEXT_RGB)
    deg = "\u00b0"
    code = day_value("weather_code", 0) or 0

    # Every chip opens with the day it speaks for, in dim type.
    now_local = _local_now_for_data(data)
    if date == now_local.date().isoformat():
        name = _s("today", runtime)
    else:
        try:
            names = FULL_DAY_NAMES.get(runtime.lang, FULL_DAY_NAMES["en"])
            name = names[datetime.fromisoformat(date).weekday()]
        except (TypeError, ValueError):
            name = str(date)
    lines = [f"{TBG}{DIM} {name} "]

    if field == "day":
        wmo_name = WMO_NAMES_I18N.get(runtime.lang, {}).get(code) or WMO_NAMES.get(code, "")
        if wmo_name:
            icons = _wmo_icons(runtime)
            ink = _conditions_ink(code, TFG)
            lines.append(f"{TBG}{ink} {icons.get(code, icons[0])}{ink} {wmo_name} ")

    elif field == "bar":
        temps = hour_values("temperature_2m")
        for value, pick in ((day_value("temperature_2m_max"), max),
                            (day_value("temperature_2m_min"), min)):
            if value is None:
                continue
            line = f"{TBG} {_colored_temp(value, runtime, deg)}"
            if temps:
                j = pick(temps, key=lambda jv: jv[1])[0]
                at = when(j)
                if at:
                    line += f" {TFG}{_s('around', runtime, time=at)}"
            lines.append(f"{line} ")

    elif field == "rain":
        total = day_value("precipitation_sum", 0) or 0
        prob = day_value("precipitation_probability_max", 0) or 0
        ink = fg(*_precip_rgb(code))
        # Full color here, unlike the hourly chip: the fade explains the
        # bar it sits under, and the daily rows have no such bar.
        amount = f"{ink}{fmt_precip_amount(total, runtime)}{TFG}" if total > 0 else ""
        if prob > 0:
            odds = _s("chance_of", runtime, p=f"{ink}{prob:.0f}%{TFG}",
                      what=_precip_kind_lower(code, runtime))
            lines.append(f"{TBG}{TFG} {odds} ")
        elif amount:
            lines.append(f"{TBG}{ink} {_s(_precip_type(code), runtime)} {amount} ")
            amount = ""
        wet = [(j, v) for j, v in hour_values("precipitation") if v > 0]
        first = when(wet[0][0]) if wet else None
        last = when(wet[-1][0]) if wet else None
        all_day = wet and wet[0][0] <= hours[0] + 1 and wet[-1][0] >= hours[-1] - 1
        if amount and all_day:
            lines.append(f"{TBG}{TFG} {_s('amount_all_day', runtime, amount=amount)} ")
        elif amount and first and last and first != last:
            spell = _s("amount_between", runtime, amount=amount, a=first, b=last)
            lines.append(f"{TBG}{TFG} {spell} ")
        elif amount and first:
            lines.append(f"{TBG}{TFG} {amount} {_s('around', runtime, time=first)} ")
        elif amount:
            lines.append(f"{TBG}{TFG} {amount} ")
        if len(wet) > 1:
            at = when(max(wet, key=lambda jv: jv[1])[0])
            if at:
                lines.append(f"{TBG}{TFG} {_s('heaviest_around', runtime, time=at)} ")

    elif field == "wind":
        speed = day_value("wind_speed_10m_max")
        gust = day_value("wind_gusts_10m_max")
        if speed is not None:
            lines.append(f"{TBG}{TFG} {_s('wind', runtime)} {speed:.0f}{runtime.wind_unit} ")
        if gust is not None and speed is not None and gust > speed:
            line = f"{TBG}{TFG} {_s('gusts', runtime)} {gust:.0f}{runtime.wind_unit}"
            gusts = hour_values("wind_gusts_10m")
            if gusts:
                at = when(max(gusts, key=lambda jv: jv[1])[0])
                if at:
                    line += f" {_s('around', runtime, time=at)}"
            lines.append(f"{line} ")

    if len(lines) < 2:
        return ""
    # The chip's left edge follows the pointer along the row, as the hourly
    # chip's does across the chart.
    return _live.pointer_chip(lines, mouse_col, mouse_row, cols, rows, pad_bg=TBG)


def forecast_notice(data, runtime, live=False, fetching=False, failed_at=None):
    """One line saying the forecast on screen is from an earlier day and
    how to get a newer one, or None while it is today's.

    A forecast on screen from another day means every fetch since has
    failed and the cache stood in (see forecast_is_todays).  The line
    names the day, says a fetch is under way while one is, and after a
    failed one says when it failed, so a retry visibly did something.
    """
    made = forecast_date(data)
    if made is None:
        return None
    now_local = _local_now_for_data(data)
    if made == now_local.date():
        return None
    if fetching:
        return f"{MUTED}{_s('forecast_fetching', runtime)}{RESET}"
    days_ago = (now_local.date() - made).days
    if 1 <= days_ago <= 6:
        names = FULL_DAY_NAMES.get(runtime.lang, FULL_DAY_NAMES["en"])
        day = names[made.weekday()]
    else:
        day = made.isoformat()
    if failed_at is not None:
        text = _s("forecast_stale_at", runtime, day=day,
                  time=_fmt_time(failed_at, runtime.use_24h))
    else:
        text = _s("forecast_stale", runtime, day=day)
    hint = _s("retry_key" if live else "retry_run", runtime)
    return f"{ALERT_AMBER}{text} {hint}{RESET}"


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0, mouse_pos=None,
                     active_alert=None, modal_scroll=0, aqi_data=None, historical=None,
                     notice=None, country_code=""):
    """Build the complete weather dashboard from preloaded data.

    `notice` is a line for under the header -- forecast_notice's, when
    the forecast is not today's. `country_code` names the alerts' source
    in the live view's credit row."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}", {}

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)
    tz_name = data.get("timezone", "")

    # Pre-render fixed-height sections to budget graph rows accurately
    alert_lines, alert_spans = (
        render_alerts_mapped(alerts, width=cols, runtime=runtime, tz_name=tz_name)
        if alerts else ([], []))
    narrative = narrative_lines(data, now_local, cols, runtime)
    daily_lines_rendered, daily_spans = render_daily_mapped(data, cols, runtime, now=now_local)

    hint = install_banner()

    hourly = data.get("hourly", {})

    # Check full dataset for optional rows so layout stays stable while scrolling
    wind_threshold = 25 if runtime.metric else 15
    all_winds = hourly.get("wind_speed_10m", [])
    has_wind_row = bool(all_winds) and max(all_winds) > wind_threshold
    all_uv = hourly.get("uv_index", [])
    has_uv_row = bool(all_uv) and max(all_uv) >= 6
    has_precip_graph = (bool(hourly.get("precipitation"))
                        and max(hourly.get("precipitation", [0])) > 0)
    has_cloud_data = bool(hourly.get("cloud_cover"))

    # Count non-hourly lines precisely
    non_hourly = 1  # header
    if notice:
        non_hourly += 1
    non_hourly += len(narrative)
    non_hourly += len(daily_lines_rendered)
    if alert_lines:
        non_hourly += 1 + len(alert_lines)  # blank + alerts
    if hint:
        non_hourly += 1
    live = getattr(runtime, 'live', False)
    if live:
        non_hourly += 1  # the credit and help row

    # The shortest the hourly section will render: the day line, the ticks,
    # two rows of braille, and whichever of the wind, UV and precipitation
    # rows the data calls for.
    hourly_floor = MIN_HOURLY_ROWS
    if has_wind_row:
        hourly_floor += 1
    if has_uv_row:
        hourly_floor += 1
    if has_precip_graph:
        hourly_floor += 1

    # The spacing rows -- under the header, and between the prose and the
    # daily rows -- are the first to go: they stay only while the curve
    # would still have a comfortable height with them in.  A third, above
    # the credit row, is a luxury of a window with room to spare.
    comfortable = hourly_floor - 2 + CURVE_ROWS_COMFORTABLE
    spacing = min(2, max(0, rows - non_hourly - comfortable))
    blank_before_daily = spacing >= 1   # keeps two blocks of text apart
    blank_after_header = spacing >= 2
    non_hourly += spacing
    blank_before_credit = live and rows - non_hourly - 1 >= comfortable
    if blank_before_credit:
        non_hourly += 1

    # A window too short even for the floor would push the header off the
    # top of the screen, so give something up: the prose first, then the
    # days furthest out.
    short = hourly_floor - (rows - non_hourly)
    if short > 0 and narrative:
        dropped = min(short, len(narrative))
        narrative = narrative[:len(narrative) - dropped]
        non_hourly -= dropped
        short -= dropped
    if short > 0 and len(daily_lines_rendered) > MIN_DAILY_ROWS:
        dropped = min(short, len(daily_lines_rendered) - MIN_DAILY_ROWS)
        daily_lines_rendered = daily_lines_rendered[:-dropped]
        daily_spans = daily_spans[:-dropped]
        non_hourly -= dropped

    # All remaining rows go to hourly section
    # hourly contains: today_line(1) + tick(1) + braille(N) + wind(0-1) + uv(0-1) + precip(0-P)
    hourly_budget = max(hourly_floor, rows - non_hourly)
    graph_budget = hourly_budget - 2  # today_line + tick_labels
    if has_wind_row:
        graph_budget -= 1
    if has_uv_row:
        graph_budget -= 1

    if has_precip_graph:
        # The bar fills at a fixed hourly amount, so a forecast whose wettest
        # hour comes nowhere near it would leave most of a tall bar empty.
        # The bar takes only the rows its peak can reach, one per third of
        # the scale, and the temperature curve has the rest.
        peak = max(hourly["precipitation"]) / _precip_bar_full(data, runtime)
        reach = max(1, math.ceil(peak * MAX_PRECIP_ROWS))
        n_precip_braille = min(MAX_PRECIP_ROWS, max(1, graph_budget // 6), reach)
        remaining_for_temp = graph_budget - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = graph_budget

    # The cloud strip is the first thing to go in a short window: it takes
    # its row from the temperature curve only once the curve has more rows
    # than it needs to read well.
    has_cloud_row = has_cloud_data and remaining_for_temp >= MIN_CURVE_ROWS_WITH_CLOUD + 1
    if has_cloud_row:
        remaining_for_temp -= 1

    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime, aqi_data=aqi_data,
                               historical=historical))
    if notice:
        lines.append(notice)
    if blank_after_header:
        lines.append("")

    # Hourly — first pass without hover to establish line boundaries
    hourly_start = len(lines)
    hourly_lines = render_hourly(
        data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
        now=now_local, runtime=runtime, offset_minutes=offset_minutes,
        show_cloud=has_cloud_row, historical=historical
    )

    # Adjust if hourly used more/fewer lines than budgeted (wind appeared,
    # or precip didn't render for the visible window)
    if len(hourly_lines) != hourly_budget and n_braille > 2:
        adjusted = max(2, n_braille - (len(hourly_lines) - hourly_budget))
        if adjusted != n_braille:
            n_braille = adjusted
            hourly_lines = render_hourly(
                data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
                now=now_local, runtime=runtime, offset_minutes=offset_minutes,
                show_cloud=has_cloud_row, historical=historical
            )

    hourly_end = hourly_start + len(hourly_lines)

    # Compute hover column only if mouse is within hourly section
    hover_graph_col = None
    if mouse_pos:
        mouse_row_idx = mouse_pos[1] - 1  # 1-based → 0-based
        if hourly_start <= mouse_row_idx < hourly_end:
            graph_w = max(10, cols)
            mouse_col_raw = mouse_pos[0] - 1  # 1-based terminal col → 0-based graph col
            if 0 <= mouse_col_raw < graph_w:
                window = _prepare_hourly_window(hourly, now_local, graph_w, runtime,
                                                offset_minutes=offset_minutes)
                if window:
                    n = len(window["temps"])
                    total_hours = window["total_hours"]
                    idx = int(mouse_col_raw / max(1, graph_w - 1) * total_hours + 0.5)
                    idx = max(0, min(n - 1, idx))
                    hover_graph_col = int(idx / max(1, total_hours) * (graph_w - 1))

    # Re-render hourly with hover indicator if needed
    if hover_graph_col is not None:
        hourly_lines = render_hourly(
            data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
            now=now_local, runtime=runtime, hover_col=hover_graph_col,
            offset_minutes=offset_minutes, show_cloud=has_cloud_row, historical=historical
        )

    lines.extend(hourly_lines)

    # Feels-like, comparative, and precipitation prose
    lines.extend(narrative)

    if blank_before_daily:
        lines.append("")

    # Daily
    daily_start = len(lines)
    lines.extend(daily_lines_rendered)

    # Alerts — badges to a line, wrapping where they run out of room
    alert_row_map = {}  # 0-based line index → [(first col, last col, alert index)]
    if alerts:
        lines.append("")
        alert_start = len(lines)
        lines.extend(alert_lines)
        for i, line_spans in enumerate(alert_spans):
            alert_row_map[alert_start + i] = line_spans

    if hint:
        lines.append(hint)
    if live:
        if blank_before_credit:
            lines.append("")
        lines.append(credit_row(cols, runtime.lang, country_code))

    # Shorter still than the trimming above could reach: cut the bottom
    # rather than let the terminal scroll the header away.
    if len(lines) > rows:
        lines = lines[:rows]
        alert_row_map = {row: spans for row, spans in alert_row_map.items()
                         if row < rows}

    output = "\n".join(lines)

    overlay = ""
    if active_alert is not None and 0 <= active_alert < len(alerts):
        overlay, _max_scroll = build_alert_modal(
            alerts[active_alert], cols, rows, runtime=runtime, scroll=modal_scroll, tz_name=tz_name,
        )
    elif mouse_pos:
        mouse_col, mouse_row = mouse_pos
        overlay = _build_hover_tooltip(
            data, mouse_col, mouse_row,
            hourly_start, hourly_end,
            cols, rows, runtime,
            offset_minutes=offset_minutes,
        ) or _build_daily_tooltip(
            data, mouse_col, mouse_row, daily_start, daily_spans, cols, rows, runtime,
        )
    output = _live.overlay(output, overlay)

    return output, alert_row_map


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
class WeatherApp(_live.LiveApp):
    """The live weather view: the fetched data, refreshed every interval.

    Keep data in memory between renders: render_fn fires on every input
    event (hover motion, scroll), and re-reading disk caches — or worse,
    blocking on a network fetch when a TTL expires — on each mouse move
    makes the tooltip lag. Refresh at most once per interval, and off
    the render thread: the view keeps painting what it has while a
    worker fetches, so a slow network never freezes hover or scroll.
    """

    interval = 300
    scroll_step = 60
    mouse = True

    help_view = 'weather'

    def __init__(self, data, alerts, aqi, lat, lng, runtime,
                 location_name="", historical=None, country=""):
        self.data = data
        self.alerts = alerts
        self.aqi = aqi
        self.fetched = _t.monotonic()
        self.lat = lat
        self.lng = lng
        self.runtime = runtime
        self.location_name = location_name
        self.historical = historical
        self.country = country
        self._worker = None
        self.attempted = None   # local time the last refresh finished

    def _refresh(self):
        """Fetch fresh data and swap it in, off the render thread.

        `fetched` moves whatever the outcome — before the worker dies,
        so render never sees a dead worker with a stale stamp — and a
        dead network is asked once per interval, not once per repaint.
        """
        try:
            data = fetch_forecast(self.lat, self.lng, self.runtime)
            alerts = fetch_alerts(self.lat, self.lng, self.country,
                                  lang=self.runtime.lang)
            aqi = fetch_aqi(self.lat, self.lng)
            apply_india_aqi(aqi, self.country)
            if data:
                self.data = data
            self.alerts = alerts
            self.aqi = aqi
        except Exception as exc:
            log_failure("weather", "live refresh", exc,
                        fallback="view stays stale")
        finally:
            self.fetched = _t.monotonic()
            # When the notice says a fetch failed.  Cleared by a current
            # forecast, so that at midnight, when it stops being current,
            # the line does not report a fetch that succeeded as failed.
            self.attempted = (None if forecast_is_todays(self.data)
                              else _local_now_for_data(self.data))
        _live.nudge()

    def _refreshing(self):
        return bool(self._worker and self._worker.is_alive())

    def _start_refresh(self):
        if not self._refreshing():
            self._worker = threading.Thread(target=self._refresh, daemon=True)
            self._worker.start()

    def on_action(self, key):
        """`r` asks for a newer forecast now rather than at the next
        interval -- the retry the stale-forecast line offers."""
        if key == "r":
            self._start_refresh()
            return True
        return False

    def render(self, offset_minutes=0, mouse_pos=None, active_alert=None,
               modal_scroll=0):
        if _t.monotonic() - self.fetched >= 300:
            self._start_refresh()
        notice = forecast_notice(self.data, self.runtime, live=True,
                                 fetching=self._refreshing(),
                                 failed_at=self.attempted)
        return render_from_data(
            self.data,
            self.alerts,
            self.runtime,
            location_name=self.location_name,
            offset_minutes=offset_minutes,
            mouse_pos=mouse_pos,
            active_alert=active_alert,
            modal_scroll=modal_scroll,
            aqi_data=self.aqi,
            historical=self.historical,  # cached — doesn't need re-fetch
            notice=notice,
            country_code=self.country,
        )

    def help_panel(self):
        from linecast._help import HelpPanel, entries
        return HelpPanel('weather', self.runtime.lang, content=lambda cols, rows:
                         entries('weather', self.runtime.lang,
                                 credits=(forecast_attribution(self.runtime.lang),
                                          alert_attribution(self.country, self.runtime.lang))))

    def on_open(self, idx):
        if 0 <= idx < len(self.alerts):
            url = self.alerts[idx].get("url", "")
            if url:
                import webbrowser
                webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = weather_parser().parse_args()
    runtime = WeatherRuntime.from_sources(args)
    set_current(runtime)

    # --search: geocode cities and exit
    if args.search:
        _search_locations(args.search, lang=runtime.lang)
        return

    # country_code is "" for an override; the reverse geocode fills it in
    lat, lng, country_code, geo_label = resolve_location(
        args.location, lang=runtime.lang, return_label=True)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    # With no override the resolved location is the user's own, so the
    # units default can follow its country -- re-resolve the runtime,
    # which a cold cache made countryless, before anything is fetched.
    own = country_for_defaults(args.location, country_code, lat, lng)
    if own:
        runtime = WeatherRuntime.from_sources(args, country=own)
        set_current(runtime)

    # Fetch data in parallel for faster startup
    from concurrent.futures import ThreadPoolExecutor
    import threading

    done = threading.Event()
    result = {}

    def _fetch():
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                fut_geocode = pool.submit(_reverse_geocode, lat, lng)
                fut_forecast = pool.submit(fetch_forecast, lat, lng, runtime)
                fut_aqi = pool.submit(fetch_aqi, lat, lng)

                def _hist():
                    try:
                        from datetime import date
                        return fetch_historical(
                            lat, lng, date.today(),
                            celsius=runtime.celsius, metric=runtime.metric,
                        )
                    except Exception as exc:
                        log_failure("weather/climate", "historical averages", exc,
                                    url="archive-api.open-meteo.com",
                                    fallback="no comparison")
                        return None
                fut_hist = pool.submit(_hist)

                # Alerts depend on geocode for country_code
                name, cc, addr = fut_geocode.result()
                fut_alerts = pool.submit(
                    fetch_alerts, lat, lng, cc or country_code,
                    lang=runtime.lang, address=addr,
                )

                result["name"] = name
                result["country_code"] = cc or country_code
                result["data"] = fut_forecast.result()
                result["alerts"] = fut_alerts.result()
                result["aqi"] = fut_aqi.result()
                result["historical"] = fut_hist.result()

            # A place the reverse geocoder cannot name keeps the name the
            # user typed; failing that, the coordinates, as radar and maps
            # show them — never the timezone city, which can be a continent
            # away (issue #50).
            if not result["name"]:
                result["name"] = geo_label or f"{lat:.2f}, {lng:.2f}"
        except Exception as exc:
            # Whatever landed in `result` is shown; a forecast that did
            # not is the "Could not fetch weather data" exit below.
            log_failure("worker", "weather fetch", exc, fallback="the data in hand",
                        trace=True)
        finally:
            # Release the spinner no matter what escapes above — the main
            # thread must never wait forever on a fetch that died.
            done.set()

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()

    # Animated spinner while waiting (suppressed for --json: stdout must
    # carry nothing but the payload). The ceiling is a backstop well above
    # the individual fetch timeouts: if the thread somehow wedges, give up
    # and fall through to the no-data exit rather than spin forever.
    _FETCH_CEILING = 60
    if runtime.json_mode:
        done.wait(_FETCH_CEILING)
    else:
        from linecast._spinner import Spinner
        with Spinner():
            done.wait(_FETCH_CEILING)

    t.join(1)
    location_name = result.get("name", "")
    final_country = result.get("country_code", "")
    data = result.get("data")
    alerts = result.get("alerts", [])
    aqi_data = result.get("aqi")
    apply_india_aqi(aqi_data, final_country)
    historical = result.get("historical")

    if data is None:
        print("Could not fetch weather data.", file=sys.stderr)
        sys.exit(1)

    if runtime.json_mode:
        import json
        from linecast._weather_json import build_payload
        payload = build_payload(
            data, location_name, final_country, runtime,
            alerts=alerts, aqi_data=aqi_data, historical=historical,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast._oneline import weather_oneline
        print(weather_oneline(data, location_name, runtime))
        return

    if runtime.live:
        WeatherApp(
            data, alerts, aqi_data, lat, lng, runtime,
            location_name=location_name, historical=historical,
            country=final_country,
        ).run()
    else:
        from linecast._textwidth import calibrate_from_terminal
        calibrate_from_terminal()
        output, _alert_map = render_from_data(
            data,
            alerts,
            runtime,
            location_name=location_name,
            aqi_data=aqi_data,
            historical=historical,
            notice=forecast_notice(data, runtime),
        )
        _live.print_frame(output)


if __name__ == "__main__":
    main()
