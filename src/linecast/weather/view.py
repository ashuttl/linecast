#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, a line or two of prose, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts sourced from NWS (US), Environment Canada (CA), Bright Sky/DWD (DE),
MET Norway (NO), Met Éireann (IE), JMA (Japan), CMA (China),
MetService (NZ), and MeteoAlarm (34 European countries).

Languages: see `linecast language` for the full list.

Usage: weather [--print] [--oneline] [--json] [--location LAT,LNG | PLACE] [--search CITY]
               [--icons SET] [--emoji] [--metric] [--imperial] [--12h] [--24h]
               [--celsius] [--fahrenheit]
               [--temp-range auto|climate|forecast|world]
               [--no-shading] [--lang fr] [--classic-colors]
"""

import math
import sys
import threading
import time as _t
from datetime import datetime

from linecast import _live, _theme
from linecast._i18n import GEOCODER_UNTRANSLATED, fmt_percent, sentence_24h, table_for
from linecast._graphics import bg, fg, get_terminal_size, visible_len
from linecast._location import country_for_defaults, resolve_location
from linecast._runtime import (
    WeatherRuntime, install_banner, log_failure, set_current, weather_parser,
)
from linecast.weather.i18n import (
    fmt_wind,
    FULL_DAY_NAMES,
    wmo_label,
    _s,
    _wmo_icons,
    has_string,
)
from linecast.weather.hourly import _precip_bar_full, _present, label_rows
from linecast.weather.render import (
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
from linecast.weather.alerts import alerts_notice
from linecast.weather.historical import fetch_historical
from linecast.weather.sources import (
    ALERTS_UNAVAILABLE,
    AlertList,
    _local_now_for_data,
    _reverse_geocode,
    _search_locations,
    alert_attribution,
    alert_source,
    apply_national_index,
    fetch_canada_aqhi,
    fetch_aqi,
    fetch_alerts,
    fetch_forecast,
    forecast_attribution,
    forecast_date,
    forecast_is_todays,
    observation_attribution,
    observation_source,
    without_country,
)
from linecast.weather.cover import sky_condition
from linecast.weather.observed import apply_observation, fetch_observation

# What the dashboard keeps when the window is too short for all of it:
# the graph is the view -- its day line, its ticks and two rows of braille
# -- and three days is still a forecast.  The rows under the curve give
# way in turn as the window shrinks: the UV labels first, then the wind
# row, then the cloud strip.  The rain bar stays.
MIN_HOURLY_ROWS = 4
MIN_DAILY_ROWS = 3
MIN_CURVE_ROWS_WITH_CLOUD = 4  # the rows under the curve take from it only above this
CURVE_ROWS_COMFORTABLE = 5     # the spacing rows stay while the curve keeps this many
MAX_PRECIP_ROWS = 3            # the precipitation bar at its tallest


def data_credits(country_code="", lang="en", observed=None):
    """The data credits, longest first. The forecast's comes first,
    then the current conditions' where a station's report was used,
    then the alerts' where a service supplies them. Short of room, the
    others give up saying what they are credited for, then the alerts
    go, then the station; the forecast's stays whole, as its licence
    asks, and last of all stands alone."""
    forecast = forecast_attribution(lang)
    alerts = alert_attribution(country_code, lang)
    station = (observed or {}).get("station", "")
    current = observation_attribution(lang, station) if observed else None
    alerts_name = alert_source(country_code, lang)
    full = [forecast, current, alerts]
    named = [forecast, observation_source(station) if observed else None, alerts_name]
    rungs = [full, named, named[:2], [forecast]]
    credits = []
    for rung in rungs:
        credit = " · ".join(part for part in rung if part)
        if credit not in credits:
            credits.append(credit)
    return tuple(credits)


def credit_row(cols, lang, country_code="", observed=None):
    """The live view's last row: the data credit at the left, in ink
    fainter than the prose above it, and the help hint at the right.
    The longest credit that leaves the whole hint its room wins; a
    window too narrow for any shows the hint alone."""
    from linecast import _help
    from linecast._graphics import visible_len
    hint = _help.hint(lang)
    for credit in data_credits(country_code, lang, observed):
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
    window = _prepare_hourly_window(hourly, now, graph_w, offset_minutes=offset_minutes)
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
    deg = "°"
    temp_line = f"{TBG} {_colored_temp(temp, runtime, deg)}"
    if apparent is not None and abs(apparent - temp) >= 3:
        temp_line += f" {TFG}{_s('feels', runtime)} {_colored_temp(apparent, runtime, deg)}"
    temp_line += " "
    lines.append(temp_line)

    # Weather description
    condition = sky_condition(code, cloud)
    wmo_name = wmo_label(condition, runtime.lang)
    if wmo_name:
        lines.append(f"{TBG}{_conditions_ink(condition, TFG)} {wmo_name} ")

    # Humidity / dew point (when notable)
    if humidity is not None and dew is not None:
        dew_f = dew * 9 / 5 + 32 if runtime.celsius else dew
        if dew_f >= 60:
            lines.append(f"{TBG}{TFG} {_s('dew_pt', runtime)} {_colored_temp(dew, runtime, deg)} ")
        elif humidity >= 70 or humidity <= 25:
            lines.append(f"{TBG}{TFG} {_s('humidity', runtime)} {fmt_percent(humidity, runtime)} ")

    # Precipitation: the hour's amount, and its chance in the very shade
    # the bar below is drawn in, so the chip teaches what the fade means.
    precip_parts = []
    if amount and amount > 0:
        precip_parts.append(f"{fg(*_precip_rgb(code))}{fmt_precip_amount(amount, runtime)}{TFG}")
    # Under 20% the shaded figure is hard to read and says nothing worth
    # reading; the bar below is a ghost of one anyway.
    if prob and prob >= 20:
        shaded = f"{_precip_shade(code, prob)}{fmt_percent(prob, runtime)}{TFG}"
        precip_parts.append(_s("chance", runtime, p=shaded))
    if precip_parts:
        lines.append(f"{TBG}{TFG} {'  '.join(precip_parts)} ")

    # Cloud cover, in the shade of the strip
    if cloud is not None and cloud >= 10:
        shaded = f"{_cloud_shade(cloud)}{fmt_percent(cloud, runtime)}{TFG}"
        lines.append(f"{TBG}{TFG} {_s('cloud', runtime, p=shaded)} ")

    # Wind (if notable)
    if runtime.wind_kmh(wind) > 25:
        sector = int((wind_dir + 22.5) / 45) % 8
        arrow = WIND_ARROWS[sector]
        lines.append(f"{TBG}{TFG} {arrow} {fmt_wind(wind, runtime)} ")

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
    if runtime.lang == "el" and kind == "Mix":
        # The row is nominative; "probability of" needs the genitive.
        return _s("mixed_precip", runtime)
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
    deg = "°"
    code = day_value("weather_code", 0) or 0

    # Every chip opens with the day it speaks for, in dim type.
    now_local = _local_now_for_data(data)
    if date == now_local.date().isoformat():
        name = _s("today", runtime)
    else:
        try:
            names = table_for(FULL_DAY_NAMES, runtime.lang)
            name = names[datetime.fromisoformat(date).weekday()]
        except (TypeError, ValueError):
            name = str(date)
    lines = [f"{TBG}{DIM} {name} "]

    if field == "day":
        condition = sky_condition(code, day_value("cloud_cover_mean"))
        wmo_name = wmo_label(condition, runtime.lang)
        if wmo_name:
            icons = _wmo_icons(runtime)
            ink = _conditions_ink(condition, TFG)
            lines.append(f"{TBG}{ink} {icons.get(condition, icons[0])}{ink} {wmo_name} ")

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
            odds = _s("chance_of", runtime, p=f"{ink}{fmt_percent(prob, runtime)}{TFG}",
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
            lines.append(f"{TBG}{TFG} {_s('wind', runtime)} {fmt_wind(speed, runtime)} ")
        if gust is not None and speed is not None and gust > speed:
            line = f"{TBG}{TFG} {_s('gusts', runtime)} {fmt_wind(gust, runtime)}"
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
        names = table_for(FULL_DAY_NAMES, runtime.lang)
        day = names[made.weekday()]
    else:
        day = made.isoformat()
    if failed_at is not None:
        text = _s("forecast_stale_at", runtime, day=day,
                  time=_fmt_time(failed_at, sentence_24h(runtime)))
    else:
        text = _s("forecast_stale", runtime, day=day)
    hint = _s("retry_key" if live else "retry_run", runtime)
    return f"{ALERT_AMBER}{text} {hint}{RESET}"


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0, mouse_pos=None,
                     active_alert=None, modal_scroll=0, aqi_data=None, historical=None,
                     notice=None, country_code="", location_menu=False):
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
    # Under the badges, or alone where they would be: a word when the
    # alert service could not be asked. Never a click target.
    alert_note = alerts_notice(alerts, cols, runtime=runtime, tz_name=tz_name)
    if alert_note:
        alert_lines = [*alert_lines, alert_note]
    narrative = narrative_lines(data, now_local, cols, runtime)
    daily_lines_rendered, daily_spans = render_daily_mapped(data, cols, runtime, now=now_local)

    hint = install_banner()

    hourly = data.get("hourly", {})

    # Check full dataset for optional rows so layout stays stable while
    # scrolling.  The series can hold nulls, so the stats are over the
    # hours that have a value.  The wind and UV rows are what the chart
    # will draw for this width: UV adds no row when its labels can share
    # the wind's.
    graph_w = max(10, cols)
    window = _prepare_hourly_window(hourly, now_local, graph_w, offset_minutes=offset_minutes)
    wind_rows, uv_rows = label_rows(window, graph_w, runtime) if window else (0, 0)
    precip_peak = max(_present(hourly.get("precipitation")), default=0)
    has_precip_graph = precip_peak > 0
    has_cloud_data = bool(_present(hourly.get("cloud_cover")))

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
    # two rows of braille, and the precipitation row when the data calls
    # for one.  The wind and UV rows and the cloud strip are not in it:
    # they have their rows only while the curve can spare them.
    hourly_floor = MIN_HOURLY_ROWS
    if has_precip_graph:
        hourly_floor += 1
    optional_rows = wind_rows + uv_rows + int(has_cloud_data)

    # The spacing rows -- under the header, and between the prose and the
    # daily rows -- are the first to go: they stay only while the curve
    # would still have a comfortable height with them in and every row
    # under it in place.  A third, above the credit row, is a luxury of a
    # window with room to spare.
    comfortable = hourly_floor - 2 + CURVE_ROWS_COMFORTABLE + optional_rows
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

    # All remaining rows go to hourly section: today_line(1) + tick(1) +
    # braille(N) + wind(0-1) + uv(0-1) + cloud(0-1) + precip(0-P)
    hourly_budget = max(hourly_floor, rows - non_hourly)
    graph_budget = hourly_budget - 2  # today_line + tick_labels

    if has_precip_graph:
        # The bar fills at a fixed hourly amount, so a forecast whose wettest
        # hour comes nowhere near it would leave most of a tall bar empty.
        # The bar takes only the rows its peak can reach, one per third of
        # the scale, and the temperature curve has the rest.
        peak = precip_peak / _precip_bar_full(data, runtime)
        reach = max(1, math.ceil(peak * MAX_PRECIP_ROWS))
        n_precip_braille = min(MAX_PRECIP_ROWS, max(1, graph_budget // 6), reach)
        remaining_for_temp = graph_budget - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = graph_budget

    # The cloud strip, the wind row and the UV row take their rows from
    # the temperature curve only while the curve keeps more rows than it
    # needs to read well, and in that order: in a window with room for
    # one of them, the strip stays.  UV labels that share the wind's row
    # cost nothing while that row is there, and go with it when it is not.
    def spare_row():
        nonlocal remaining_for_temp
        if remaining_for_temp <= MIN_CURVE_ROWS_WITH_CLOUD:
            return False
        remaining_for_temp -= 1
        return True

    has_cloud_row = has_cloud_data and spare_row()
    has_wind_row = wind_rows > 0 and spare_row()
    if wind_rows > 0 and not has_wind_row:
        show_uv = False
    elif uv_rows > 0:
        show_uv = spare_row()
    else:
        show_uv = True

    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime, aqi_data=aqi_data,
                               historical=historical, location_menu=location_menu, now=now_local))
    if notice:
        lines.append(notice)
    if blank_after_header:
        lines.append("")

    # Hourly — first pass without hover to establish line boundaries
    hourly_start = len(lines)
    hourly_lines = render_hourly(
        data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
        now=now_local, runtime=runtime, offset_minutes=offset_minutes,
        show_cloud=has_cloud_row, show_wind=has_wind_row, show_uv=show_uv,
        historical=historical,
    )

    # Adjust if hourly used more/fewer lines than budgeted, giving the
    # difference to or taking it from the curve.
    if len(hourly_lines) != hourly_budget:
        adjusted = max(2, n_braille - (len(hourly_lines) - hourly_budget))
        if adjusted != n_braille:
            n_braille = adjusted
            hourly_lines = render_hourly(
                data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
                now=now_local, runtime=runtime, offset_minutes=offset_minutes,
                show_cloud=has_cloud_row, show_wind=has_wind_row, show_uv=show_uv,
                historical=historical,
            )

    hourly_end = hourly_start + len(hourly_lines)

    # Compute hover column only if mouse is within hourly section
    hover_graph_col = None
    if mouse_pos:
        mouse_row_idx = mouse_pos[1] - 1  # 1-based → 0-based
        if hourly_start <= mouse_row_idx < hourly_end:
            mouse_col_raw = mouse_pos[0] - 1  # 1-based terminal col → 0-based graph col
            if 0 <= mouse_col_raw < graph_w:
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
            offset_minutes=offset_minutes, show_cloud=has_cloud_row,
            show_wind=has_wind_row, show_uv=show_uv, historical=historical,
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
    if alert_lines:
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
        observed = (data.get("current") or {}).get("observed")
        lines.append(credit_row(cols, runtime.lang, country_code, observed))

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
        from linecast.weather.locations import LocationPicker
        self.locations = LocationPicker(runtime.lang)
        self._update_location_picker()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._location_worker = None
        self._location_result = None
        self._loading = None
        self._location_hit = None
        self._worker = None
        self._climate_worker = None
        self.attempted = None   # local time the last refresh finished
        self._start_climate(delay=_CLIMATE_RETRY_DELAY)

    def _refresh(self, generation, lat, lng, country):
        """Refresh a snapshot of the location; discard it if the user moved."""
        data, alerts, aqi = None, self.alerts, self.aqi
        # The address the alert matching needs, in the country's own
        # language, as the feeds' area names are; cached a day per
        # location, so only a place the reader has just moved to pays
        # for the call. Without it every text-only warning in the
        # country matches.
        try:
            _name, cc, addr = _reverse_geocode(lat, lng)
        except Exception as exc:
            log_failure("weather", "live refresh address", exc,
                        fallback="alerts matched on geometry alone")
            cc, addr = "", {}
        try:
            data = apply_observation(fetch_forecast(lat, lng, self.runtime),
                                     fetch_observation(lat, lng))
            alerts = fetch_alerts(lat, lng, cc or country,
                                  lang=self.runtime.lang, address=addr)
            aqi = apply_national_index(fetch_aqi(lat, lng), country, lat, lng)
        except Exception as exc:
            log_failure("weather", "live refresh", exc, fallback="view stays stale")
        finally:
            with self._state_lock:
                if generation == self._generation:
                    if data:
                        self.data = data
                    self.alerts, self.aqi = alerts, aqi
                    self.fetched = _t.monotonic()
                    self.attempted = (None if forecast_is_todays(self.data)
                                      else _local_now_for_data(self.data))
        _live.nudge()
        # The refresh is also the climate scale's next chance: a
        # location that arrived without one keeps asking every interval.
        with self._state_lock:
            if generation == self._generation:
                self._start_climate()

    def _fetch_climate(self, generation, lat, lng, delay=0):
        """Ask the archive for the climate scale a location arrived
        without, for the day it is there, and keep the answer unless the
        user has moved on.  The graph's scale falls in on the next paint."""
        if delay:
            _t.sleep(delay)
        with self._state_lock:
            if generation != self._generation or self.historical is not None:
                return
            data = self.data

        def stale():
            return generation != self._generation

        historical = None
        try:
            historical = fetch_historical(
                lat, lng, _local_now_for_data(data).date(),
                celsius=getattr(self.runtime, "celsius", False),
                metric=getattr(self.runtime, "metric", False), stale=stale)
        except Exception as exc:
            log_failure("weather", "climate scale", exc, fallback="forecast's own range")
        if historical is None:
            return
        with self._state_lock:
            if generation != self._generation or self.historical is not None:
                return
            self.historical = historical
        _live.nudge()

    def _start_climate(self, delay=0):
        """Another try for a missing climate scale, in the background:
        a little after a location arrives without one, and at each
        refresh until it has one.  Called with the state lock held."""
        if self.historical is not None or not self.data:
            return
        worker = self._climate_worker
        if worker and worker.is_alive():
            return
        self._climate_worker = threading.Thread(
            target=self._fetch_climate,
            args=(self._generation, self.lat, self.lng, delay), daemon=True)
        self._climate_worker.start()

    def _refreshing(self):
        return bool(self._worker and self._worker.is_alive())

    def _start_refresh(self):
        if not self._refreshing() and self._loading is None:
            self._worker = threading.Thread(
                target=self._refresh,
                args=(self._generation, self.lat, self.lng, self.country), daemon=True)
            self._worker.start()

    def _choose_location(self, place):
        from linecast.weather.locations_i18n import ls
        if place is None:
            return
        if place == 'save':
            self._save_default_location()
            return
        with self._state_lock:
            self._generation += 1
            generation = self._generation
            self._location_result = None
            self._loading = place
            self._worker = None
            self.flash([ls('loading', self.runtime.lang, name=place.name)], busy=True)

        def fetch():
            try:
                result = gather(place.lat, place.lon, "", self.runtime, geo_label=place.name,
                                stale=lambda: generation != self._generation)
            except Exception as exc:
                log_failure("weather", "change location", exc, fallback="keep current location")
                result = None
            with self._state_lock:
                if generation == self._generation:
                    self._location_result = (place, result)
            _live.nudge()

        self._location_worker = threading.Thread(target=fetch, daemon=True)
        self._location_worker.start()

    def _update_location_picker(self):
        from linecast._config import saved_location
        saved = saved_location()
        self.locations.location_name = self.location_name or f"{self.lat:.2f}, {self.lng:.2f}"
        self.locations.is_default = bool(
            saved and (round(saved['lat'], 4), round(saved['lng'], 4))
            == (round(self.lat, 4), round(self.lng, 4)))
        self.locations.sel = 0

    def _save_default_location(self):
        """Persist the displayed place using the CLI's shared location setting."""
        from linecast._config import read_config, write_config
        from linecast.weather.locations_i18n import ls
        label = self.location_name or f"{self.lat:.2f}, {self.lng:.2f}"
        try:
            config = read_config()
            config['location'] = dict(lat=self.lat, lng=self.lng, label=label, country=self.country)
            write_config(config)
        except OSError as exc:
            log_failure('weather', 'save default location', exc, fallback='keep previous default')
            self.flash([ls('save_failed', self.runtime.lang)], seconds=5)
            return
        self._update_location_picker()
        self.flash([ls('saved', self.runtime.lang, name=label)])

    def _finish_location(self):
        """Commit on the UI thread, so recents and panels never change mid-input."""
        from linecast.maps.search import Result
        from linecast.weather.locations_i18n import ls
        if self._location_result is None:
            return
        place, result = self._location_result
        self._location_result = self._loading = None
        self.clear_flash()
        if not result or not result.get('data'):
            self.flash([ls('failed', self.runtime.lang, name=place.name)], seconds=5)
            return
        # Keep the departure point too, so the first trip has a way back.
        if not any(round(p.lat, 4) == round(self.lat, 4) and
                   round(p.lon, 4) == round(self.lng, 4) for p in self.locations.recent.places):
            self.locations.recent.remember(
                Result(self.location_name, '', self.lat, self.lng, 'point'))
        self.lat, self.lng = place.lat, place.lon
        self.data = result['data']
        self.alerts = result.get('alerts', [])
        self.aqi = result.get('aqi')
        self.historical = result.get('historical')
        self.country = result.get('country_code', '')
        self.location_name = result.get('name') or place.name
        self._update_location_picker()
        self.aqi = apply_national_index(self.aqi, self.country, self.lat, self.lng,
                                        canada=result.get('aqhi'))
        self.fetched, self.attempted = _t.monotonic(), None
        self.locations.recent.remember(place)
        self._start_climate(delay=_CLIMATE_RETRY_DELAY)

    def text_mode(self):
        return self.locations.search.open

    def intercept(self, action):
        if self.locations.active:
            self._choose_location(self.locations.handle(action, self.lat, self.lng))
            return True
        return False

    def on_wheel(self, direction, col, row):
        if not self.locations.active:
            return NotImplemented  # keep the forecast and alert modal's usual scrolling
        self.locations.handle('fwd' if direction > 0 else 'back', self.lat, self.lng)
        return True

    def clamp_offset(self, offset_minutes):
        with self._state_lock:
            cols, _ = get_terminal_size()
            window = _prepare_hourly_window(
                self.data.get("hourly", {}), _local_now_for_data(self.data),
                max(10, cols), offset_minutes=offset_minutes)
            return window["offset_minutes"] if window else 0

    def on_drag(self, dcol, drow, done):
        # Opt in to live_loop's press/release tracking for clicks.
        return False

    def on_click(self, col, row):
        if self.locations.active:
            self._choose_location(self.locations.click(col, row))
            return True
        if (row == 1 and self._location_hit
                and self._location_hit[0] <= col <= self._location_hit[1]):
            self.locations.start()
            return True
        return False

    def stop(self):
        self.clear_flash()
        self.locations.close()
        with self._state_lock:
            self._generation += 1

    def on_action(self, key):
        """`r` asks for a newer forecast now rather than at the next
        interval -- the retry the stale-forecast line offers."""
        if key == "l":
            self.locations.start()
            return True
        if key == "/":
            self.locations.choose('add')
            return True
        if key == "r":
            self._start_refresh()
            return True
        return False

    def render(self, offset_minutes=0, mouse_pos=None, active_alert=None,
               modal_scroll=0):
        with self._state_lock:
            self._finish_location()
            return self._render(offset_minutes, mouse_pos, active_alert, modal_scroll)

    def _render(self, offset_minutes, mouse_pos, active_alert, modal_scroll):
        if _t.monotonic() - self.fetched >= 300:
            self._start_refresh()
        notice = forecast_notice(self.data, self.runtime, live=True,
                                 fetching=self._refreshing(), failed_at=self.attempted)
        panel = self.locations.active
        output, alert_rows = render_from_data(
            self.data, self.alerts, self.runtime,
            location_name=self.location_name,
            offset_minutes=offset_minutes,
            mouse_pos=None if panel else mouse_pos,
            active_alert=None if panel else active_alert,
            modal_scroll=modal_scroll,
            aqi_data=self.aqi, historical=self.historical,
            notice=notice, country_code=self.country,
            location_menu=True,
        )
        cols, rows = get_terminal_size()
        # The live header always reserves space for its location control.
        from linecast.weather.sections import location_chip, location_control
        label = location_chip(location_control(self.location_name, cols, self.runtime))
        self._location_hit = (cols - visible_len(label) + 1, cols)
        floating = self.flash_overlay(cols, rows)
        if panel:
            floating += self.locations.overlay(cols, rows, (round(self.lat, 4), round(self.lng, 4)))
            alert_rows = {}  # a panel click must not open an alert beneath it
        if floating:
            body, _, previous = output.partition("\x00")
            output = _live.overlay(body, previous + floating)
        return output, alert_rows

    def help_panel(self):
        from linecast._help import HelpPanel, entries
        from linecast.maps.search import ATTRIBUTION
        from linecast.weather.locations_i18n import ls
        observed = ((self.data or {}).get("current") or {}).get("observed")
        return HelpPanel('weather', self.runtime.lang, content=lambda cols, rows:
                         [('l', ls('locations', self.runtime.lang)),
                          ('/', ls('add', self.runtime.lang))] +
                         entries('weather', self.runtime.lang,
                                 credits=(forecast_attribution(self.runtime.lang),
                                          observation_attribution(self.runtime.lang,
                                                                  observed["station"])
                                          if observed else None,
                                          alert_attribution(self.country, self.runtime.lang),
                                          ATTRIBUTION)))

    def on_open(self, idx):
        if 0 <= idx < len(self.alerts):
            url = self.alerts[idx].get("url", "")
            if url:
                import webbrowser
                webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
_FETCH_CEILING = 30  # shared wall-clock budget for the dashboard providers
# How long the live dashboard waits for the climate scale before showing
# the forecast without it. The archive answers in a few seconds when it
# answers; when it hangs, the view fills the scale in afterwards.
_CLIMATE_PATIENCE = 10
# The station's sky is a correction to the forecast, not worth holding
# the view for: once the forecast is in, it has this long to follow.
_OBSERVATION_PATIENCE = 2
# How long the live view waits before asking again for a climate scale
# that did not arrive with the forecast. Long enough for a request the
# dashboard stopped waiting for to finish and leave its answer in the
# cache, and to spare an archive that is refusing requests a second
# volley on its heels.
_CLIMATE_RETRY_DELAY = 20


def gather(lat, lng, country_code, runtime, geo_label="", stale=None):
    """Everything the dashboard is built from, fetched side by side.

    Returns a dict with name, country_code, data, alerts, aqi and
    historical.  Each is taken from its own fetch on its own: a
    provider that raises -- an alert feed with a null where a string
    was expected, say -- costs only its own entry, logged under --debug,
    and never the air quality or the climate scale fetched beside it.
    All providers share one deadline; completed results survive a timeout.
    `stale` says whether the caller has stopped wanting the answer; the
    archive, which queues its requests, asks it before taking its turn."""
    from concurrent.futures import Future, TimeoutError
    from datetime import date

    deadline = _t.monotonic() + _FETCH_CEILING

    def _submit(fetch, *args, **kwargs):
        future = Future()
        if _t.monotonic() >= deadline:
            future.set_exception(TimeoutError("weather fetch deadline reached"))
            return future

        def run():
            try:
                future.set_result(fetch(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

        # Executor workers are joined at interpreter exit, even when their
        # parent is a daemon. A wedged provider must not hold up Ctrl-C.
        threading.Thread(target=run, daemon=True).start()
        return future

    def _settle(future, what, fallback, patience=None):
        # With the traceback: a worker that failed is the one thing a
        # --debug transcript exists to explain.
        wait = max(0, deadline - _t.monotonic())
        why = "omitted after fetch deadline"
        if patience is not None and patience < wait:
            wait, why = patience, "left for the live view to fill in"
        try:
            return future.result(timeout=wait)
        except TimeoutError as exc:
            log_failure("worker", what, exc, fallback=why)
            return fallback
        except Exception as exc:
            log_failure("worker", what, exc, fallback="omitted", trace=True)
            return fallback

    result = {}
    fut_geocode = _submit(_reverse_geocode, lat, lng)
    fut_forecast = _submit(fetch_forecast, lat, lng, runtime)
    fut_aqi = _submit(fetch_aqi, lat, lng)
    fut_observed = _submit(fetch_observation, lat, lng)
    today = date.today()
    fut_hist = _submit(fetch_historical, lat, lng, today,
                       celsius=runtime.celsius, metric=runtime.metric, stale=stale)

    # Alerts depend on geocode for country_code
    name, cc, addr = _settle(fut_geocode, "reverse geocode", ("", "", {}))
    # That address is in the country's own language, as the alert
    # feeds' area names are. A typed place is shown by the forward
    # geocoder's label, which names what was asked for; with only
    # coordinates, or a language that label cannot be in, Nominatim
    # is asked again for the name in the user's.
    fut_name = None
    if not geo_label or runtime.lang in GEOCODER_UNTRANSLATED:
        fut_name = _submit(_reverse_geocode, lat, lng, lang=runtime.lang)
    fut_alerts = _submit(
        fetch_alerts, lat, lng, cc or country_code,
        lang=runtime.lang, address=addr,
    )
    # Canada publishes the air quality index it reports; fetched beside
    # the rest, and computed from the pollutants when it does not come.
    fut_aqhi = _submit(fetch_canada_aqhi, lat, lng) if (cc or country_code) == "CA" else None

    localized = _settle(fut_name, "place name", ("", "", {}))[0] if fut_name else ""
    result["name"] = localized or without_country(geo_label) or name
    result["country_code"] = cc or country_code
    result["data"] = apply_observation(_settle(fut_forecast, "forecast", None),
                                       _settle(fut_observed, "station observation", None,
                                               _OBSERVATION_PATIENCE))
    result["aqi"] = _settle(fut_aqi, "air quality", None)
    result["aqhi"] = _settle(fut_aqhi, "Canada's AQHI", None) if fut_aqhi else None
    # The live view can fill the climate scale in later, so it does not
    # keep the forecast waiting on a hung archive; a one-shot run has no
    # later, and waits out the deadline.
    patience = _CLIMATE_PATIENCE if getattr(runtime, "live", False) else None
    result["historical"] = _settle(fut_hist, "historical averages", None, patience)
    # The archive was asked for the machine's day, which is the
    # location's until the date line or a midnight comes between.
    # Then it is asked again for the day it is there: the download
    # covers the whole year, so the second answer comes from the
    # first's cache (issue #110).  Should that second ask miss the
    # deadline, the first answer stands: its year's extremes are the
    # same, and only the day's averages are a day off.
    if result["data"]:
        there = _local_now_for_data(result["data"]).date()
        if there != today:
            again = _settle(
                _submit(fetch_historical, lat, lng, there,
                        celsius=runtime.celsius, metric=runtime.metric, stale=stale),
                "historical averages", None, patience)
            if again is not None:
                result["historical"] = again
    # A feed that raised or ran out the deadline was not heard from.
    result["alerts"] = _settle(fut_alerts, "alerts", AlertList(status=ALERTS_UNAVAILABLE))

    # A place no geocoder can name shows its coordinates, as radar and
    # maps do — never the timezone city, which can be a continent away
    # (issue #50).
    if not result["name"]:
        result["name"] = f"{lat:.2f}, {lng:.2f}"
    return result


def main():
    try:
        _main()
    except KeyboardInterrupt:
        sys.exit(130)


def _main():
    args = weather_parser().parse_args()
    runtime = WeatherRuntime.from_sources(args)
    set_current(runtime)
    # In a right-to-left language the whole dashboard reads from the
    # right, the hourly graph included: now is at the right edge
    from linecast import _bidi
    _bidi.set_mirror(True)

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

    # JSON stdout must contain only the payload; Spinner clears its line
    # on cancellation. gather bounds all providers with one deadline.
    from contextlib import nullcontext
    from linecast._spinner import Spinner
    with nullcontext() if runtime.json_mode else Spinner():
        result = gather(lat, lng, country_code, runtime, geo_label)

    location_name = result.get("name", "")
    final_country = result.get("country_code", "")
    data = result.get("data")
    alerts = result.get("alerts", [])
    aqi_data = apply_national_index(result.get("aqi"), final_country, lat, lng,
                                    canada=result.get("aqhi"))
    historical = result.get("historical")

    if data is None:
        print("Could not fetch weather data.", file=sys.stderr)
        sys.exit(1)

    if runtime.json_mode:
        import json
        from linecast.weather.json import build_payload
        payload = build_payload(
            data, location_name, final_country, runtime,
            alerts=alerts, aqi_data=aqi_data, historical=historical,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast._oneline import emit, weather_oneline
        emit(weather_oneline(data, location_name, runtime))
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

