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

import functools
import math
from datetime import datetime
from typing import NamedTuple

from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast._i18n import fmt_percent, sentence_24h, setting, table_for
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import get_terminal_size
from linecast._timefmt import fmt_time_dt
from linecast._runtime import install_banner
from linecast.weather.i18n import fmt_wind, felt_index, wmo_label, _s, _wmo_icons
from linecast._i18n import FULL_DAY_NAMES
from linecast.weather.alerts import alerts_notice, build_alert_modal, render_alerts_mapped
from linecast.weather.daily import (
    fmt_precip_amount, fmt_snow_amount, mostly_snow, render_daily_mapped,
)
from linecast.weather.hourly import (
    _precip_bar_full, _prepare_hourly_window, _present, label_rows, render_hourly,
)
from linecast.weather.header import render_header
from linecast.weather.narrative import narrative_lines
from linecast.weather.style import (
    ALERT_AMBER, CLOUD_RGB, DIM, MUTED, TEXT, TOOLTIP_BG_RGB, TOOLTIP_DIM_RGB, TOOLTIP_TEXT_RGB,
    _colored_temp, _precip_rgb, _precip_type, notable_moisture,
)
from linecast.weather.alert_feeds import alert_source
from linecast.weather.credits import observed_credit
from linecast.weather.forecast import _at, local_now, forecast_date, FORECAST_SOURCE
from linecast.weather.cover import _PRECIP_CODES, sky_condition
from linecast.terminal.glyphs import arrow_toward

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


def data_credits(country_code="", lang="en", observed=None, runtime=None, tz_name=""):
    """The data credits, longest first: where and when the current sky
    was seen, where a station's report was used, then the sources by
    name, the forecast's first and the alerts' where a service supplies
    them. Short of room, the station gives its code for its name, then
    goes, then the alerts go; the forecast's name stays, and last of all
    stands alone. The help panel carries each in full."""
    metric = bool(getattr(runtime, "metric", False))
    use_24h = sentence_24h(runtime) if runtime else not setting(lang, "sentence_12h")
    names = " & ".join(part for part in (FORECAST_SOURCE, alert_source(country_code, lang))
                       if part)
    seen = [observed_credit(observed, lang, metric, use_24h, tz_name, named=named)
            for named in (True, False)]
    rungs = [[seen[0], names], [seen[1], names], [names], [FORECAST_SOURCE]]
    credits = []
    for rung in rungs:
        credit = " · ".join(part for part in rung if part)
        if credit not in credits:
            credits.append(credit)
    return tuple(credits)


def credit_row(cols, lang, country_code="", observed=None, runtime=None, tz_name=""):
    """The live view's last row: the data credit at the left, in ink
    fainter than the prose above it, and the help hint at the right.
    The longest credit that leaves the whole hint its room wins; a
    window too narrow for any shows the hint alone."""
    from linecast.terminal import help as _help
    from linecast.terminal.textwidth import visible_len
    hint = _help.hint(lang)
    for credit in data_credits(country_code, lang, observed, runtime, tz_name):
        if visible_len(credit) + 2 + visible_len(hint) <= cols:
            return _help.footer(f"{DIM}{credit}{RESET}", cols, lang)
    return _help.footer("", cols, lang)


def _build_hover_tooltip(data, mouse_col, mouse_row, hourly_start, hourly_end, cols, rows,
                         runtime, offset_minutes=0, now=None):
    """Build a tooltip overlay for mouse hover on the hourly chart.

    Returns cursor-positioned escape sequences to draw the tooltip, or "".
    mouse_col/mouse_row are 1-based terminal coordinates.
    hourly_start/hourly_end are 0-based line indices in the output.
    `now` is the local time where the forecast is for, local_now's by
    default.
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
    if now is None:
        now = local_now(data)
    window = _prepare_hourly_window(hourly, now, graph_w, offset_minutes=offset_minutes)
    if window is None:
        return ""

    # Map graph column to nearest hour index (use int() to match midnight divider formula)
    n = len(window["temps"])
    total_hours = window["total_hours"]
    idx = int(graph_col / max(1, graph_w - 1) * total_hours + 0.5)
    idx = max(0, min(n - 1, idx))

    dt = _at(window["dts"], idx)
    temp = window["temps"][idx]
    apparent = _at(window.get("apparent_temps"), idx)
    code = _at(window["codes"], idx, 0)
    wind = _at(window["winds"], idx, 0)
    wind_dir = _at(window["wind_dirs"], idx, 0)
    humidity = _at(window.get("humidity"), idx)
    dew = _at(window.get("dew_points"), idx)
    amount = _at(window.get("precip_amount"), idx, 0)
    snow = _at(window.get("snowfall"), idx, 0)
    prob = _at(window.get("precip"), idx, 0)
    cloud = _at(window.get("cloud"), idx)

    TBG = bg(*TOOLTIP_BG_RGB)
    TFG = fg(*TOOLTIP_TEXT_RGB)

    lines = []

    # Time
    if dt:
        time_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
        lines.append(f"{TBG}{TFG} {time_str} ")

    # Temperature + feels like
    deg = "°"
    temp_line = f"{TBG} {_colored_temp(temp, runtime, deg)}"
    index = felt_index(window, runtime, idx)
    if index:
        key, value = index
        temp_line += f" {TFG}{_s(key, runtime)} {_colored_temp(value, runtime)}"
    elif index is False and apparent is not None and abs(apparent - temp) >= 3:
        temp_line += f" {TFG}{_s('feels', runtime)} {_colored_temp(apparent, runtime, deg)}"
    temp_line += " "
    lines.append(temp_line)

    # Weather description
    condition = sky_condition(code, cloud)
    wmo_name = wmo_label(condition, runtime.lang)
    if wmo_name:
        lines.append(f"{TBG}{_conditions_ink(condition, TFG)} {wmo_name} ")

    # Humidity / dew point (when notable)
    moisture = notable_moisture(humidity, dew, runtime, deg)
    if moisture:
        key, shown = moisture
        lines.append(f"{TBG}{TFG} {_s(key, runtime)} {shown} ")

    # Precipitation: the hour's amount, and its chance in the very shade
    # the bar below is drawn in, so the chip teaches what the fade means.
    precip_parts = []
    if amount and amount > 0:
        # A snowy hour's amount is its snow, as the daily rows give a
        # snowy day's: "0.8″" of snow, not the 0.12″ of water it melts to
        shown = (fmt_snow_amount(snow, runtime)
                 if _precip_type(code) == "Snow" and mostly_snow(snow, amount, runtime)
                 else fmt_precip_amount(amount, runtime))
        precip_parts.append(f"{fg(*_precip_rgb(code))}{shown}{TFG}")
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
        arrow = arrow_toward(wind_dir + 180)
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
    """The precipitation type as a word mid-sentence: "rain", not "Rain".
    The words are the past day's total's, "snow", "rain", "mixed
    precipitation", in the case that sentence's "of" asks for, which is
    the case the chance's "of" asks for too (Czech "deště", Greek
    "μεικτών κατακρημνισμάτων").  The row's own label is a heading, and
    abbreviated in some languages ("Bland.")."""
    kind = _precip_type(code)
    return _s({"Snow": "snow", "Rain": "rain", "Mix": "mixed_precip"}[kind], runtime)


def _build_daily_tooltip(data, mouse_col, mouse_row, daily_start, daily_spans, cols, rows,
                         runtime, now=None):
    """A chip for the part of a daily row under the pointer.

    Each part of the row answers for itself: the day's name and icon give
    the day and its weather, the bar the high and low and when they come,
    the odds and the amount together the day's total, its chance, the
    hours with rain and the heaviest of them, the wind its speed and
    gusts.  Returns
    cursor-positioned escapes, or "" when the pointer is elsewhere.
    mouse_col/mouse_row are 1-based terminal coordinates; daily_start is
    the 0-based line index of the first daily row.  `now` is the local
    time where the forecast is for, local_now's by default.
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
        return _at(daily.get(key), i, default)

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
        return fmt_time_dt(dt, use_24h=runtime.use_24h)

    TBG = bg(*TOOLTIP_BG_RGB)
    TFG = fg(*TOOLTIP_TEXT_RGB)
    deg = "°"
    code = day_value("weather_code", 0) or 0

    # Every chip opens with the day it speaks for, in dim type.
    now_local = local_now(data) if now is None else now
    if date == now_local.date().isoformat():
        name = _s("today", runtime)
    else:
        try:
            names = table_for(FULL_DAY_NAMES, runtime.lang)
            name = names[datetime.fromisoformat(date).weekday()]
        except (TypeError, ValueError):
            name = str(date)
    lines = [f"{TBG}{fg(*TOOLTIP_DIM_RGB)} {name} "]

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
        snow = day_value("snowfall_sum", 0) or 0
        prob = day_value("precipitation_probability_max", 0) or 0
        ink = fg(*_precip_rgb(code))
        # Full color here, unlike the hourly chip: the fade explains the
        # bar it sits under, and the daily rows have no such bar.  A snowy
        # day's amount is its snow, as the row gives it.
        shown = (fmt_snow_amount(snow, runtime)
                 if _precip_type(code) == "Snow" and mostly_snow(snow, total, runtime)
                 else fmt_precip_amount(total, runtime))
        amount = f"{ink}{shown}{TFG}" if total > 0 else ""
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
        # Through the day from one end to the other, with no more than an
        # hour's lull, as the forecast in words has it: showers in the
        # small hours and again at night are not a day of rain.
        all_day = (wet and wet[0][0] <= hours[0] + 1 and wet[-1][0] >= hours[-1] - 1
                   and all(b - a <= 2 for (a, _), (b, _) in zip(wet, wet[1:])))
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
    now_local = local_now(data)
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
                  time=fmt_time_dt(failed_at, sentence_24h(runtime)))
    else:
        text = _s("forecast_stale", runtime, day=day)
    hint = _s("retry_key" if live else "retry_run", runtime)
    return f"{ALERT_AMBER}{text} {hint}{RESET}"


class _Layout(NamedTuple):
    """How the dashboard shares out the window's rows (_budget)."""
    narrative: int              # the prose lines kept
    daily: int                  # the daily rows kept
    blank_after_header: bool    # the spacing rows kept
    blank_before_daily: bool
    blank_before_credit: bool
    hourly: int                 # the hourly section's rows in all
    braille: int                # the temperature curve's rows
    precip: int                 # the precipitation bar's rows
    cloud: bool                 # the rows under the curve that keep their row
    wind: bool
    uv: bool


def _budget(data, runtime, rows, fixed, narrative, daily, chart_labels):
    """The _Layout for a window `rows` high.  `fixed` is the rows there
    at any height (the header, the notice, the alerts, the install hint,
    the credit row), `narrative` and `daily` the prose lines and daily
    rows on offer, and `chart_labels` the (wind, UV) rows the chart's
    labels would take at this width (hourly.label_rows).

    The full dataset decides the optional rows, so the layout stays
    stable while scrolling.  The series can hold nulls, so the stats
    are over the hours that have a value."""
    hourly = data.get("hourly", {})
    wind_rows, uv_rows = chart_labels
    precip_peak = max(_present(hourly.get("precipitation")), default=0)
    has_precip_graph = precip_peak > 0
    has_cloud_data = bool(_present(hourly.get("cloud_cover")))
    live = getattr(runtime, 'live', False)
    non_hourly = fixed + narrative + daily

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
    non_hourly += spacing
    blank_before_credit = live and rows - non_hourly - 1 >= comfortable
    if blank_before_credit:
        non_hourly += 1

    # A window too short even for the floor would push the header off the
    # top of the screen, so give something up: the prose first, then the
    # days furthest out.
    short = hourly_floor - (rows - non_hourly)
    if short > 0 and narrative:
        dropped = min(short, narrative)
        narrative -= dropped
        non_hourly -= dropped
        short -= dropped
    if short > 0 and daily > MIN_DAILY_ROWS:
        dropped = min(short, daily - MIN_DAILY_ROWS)
        daily -= dropped
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

    return _Layout(narrative, daily, spacing >= 2, spacing >= 1, blank_before_credit,
                   hourly_budget, max(2, remaining_for_temp), n_precip_braille,
                   has_cloud_row, has_wind_row, show_uv)


def _hover_column(mouse_pos, hourly_start, hourly_end, graph_w, window):
    """The chart column of the hour under the pointer, where the hover
    line is drawn, or None when the pointer is not over the chart."""
    if not mouse_pos or not window:
        return None
    if not hourly_start <= mouse_pos[1] - 1 < hourly_end:   # 1-based → 0-based
        return None
    col = mouse_pos[0] - 1  # 1-based terminal col → 0-based graph col
    if not 0 <= col < graph_w:
        return None
    n = len(window["temps"])
    total_hours = window["total_hours"]
    idx = int(col / max(1, graph_w - 1) * total_hours + 0.5)
    idx = max(0, min(n - 1, idx))
    return int(idx / max(1, total_hours) * (graph_w - 1))


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0, mouse_pos=None,
                     active_alert=None, modal_scroll=0, aqi_data=None, historical=None,
                     notice=None, country_code="", location_menu=False, now=None):
    """Build the complete weather dashboard from preloaded data.

    `notice` is a line for under the header -- forecast_notice's, when
    the forecast is not today's. `country_code` names the alerts' source
    in the live view's credit row.  `now` is the local time where the
    forecast is for, local_now's by default; every part of the frame,
    the hover chips included, reads this one clock."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}", {}

    cols, rows = get_terminal_size()
    now_local = local_now(data) if now is None else now
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
    live = getattr(runtime, 'live', False)

    # The wind and UV rows are what the chart will draw for this width:
    # UV adds no row when its labels can share the wind's.
    graph_w = max(10, cols)
    window = _prepare_hourly_window(data.get("hourly", {}), now_local, graph_w,
                                    offset_minutes=offset_minutes)
    fixed = 1  # header
    if notice:
        fixed += 1
    if alert_lines:
        fixed += 1 + len(alert_lines)  # blank + alerts
    if hint:
        fixed += 1
    if live:
        fixed += 1  # the credit and help row
    layout = _budget(data, runtime, rows, fixed, len(narrative), len(daily_lines_rendered),
                     label_rows(window, graph_w, runtime) if window else (0, 0))
    narrative = narrative[:layout.narrative]
    daily_lines_rendered = daily_lines_rendered[:layout.daily]
    daily_spans = daily_spans[:layout.daily]

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime, aqi_data=aqi_data,
                               historical=historical, location_menu=location_menu, now=now_local))
    if notice:
        lines.append(notice)
    if layout.blank_after_header:
        lines.append("")

    # Hourly — first pass without hover to establish line boundaries
    hourly_start = len(lines)
    chart = functools.partial(
        render_hourly, data, cols, n_precip_rows=layout.precip, now=now_local,
        runtime=runtime, offset_minutes=offset_minutes, show_cloud=layout.cloud,
        show_wind=layout.wind, show_uv=layout.uv, historical=historical,
    )
    n_braille = layout.braille
    hourly_lines = chart(n_braille_rows=n_braille)

    # Adjust if hourly used more/fewer lines than budgeted, giving the
    # difference to or taking it from the curve.
    if len(hourly_lines) != layout.hourly:
        adjusted = max(2, n_braille - (len(hourly_lines) - layout.hourly))
        if adjusted != n_braille:
            n_braille = adjusted
            hourly_lines = chart(n_braille_rows=n_braille)

    hourly_end = hourly_start + len(hourly_lines)

    # Re-render hourly with hover indicator if needed
    hover_graph_col = _hover_column(mouse_pos, hourly_start, hourly_end, graph_w, window)
    if hover_graph_col is not None:
        hourly_lines = chart(n_braille_rows=n_braille, hover_col=hover_graph_col)

    lines.extend(hourly_lines)

    # Feels-like, comparative, and precipitation prose
    lines.extend(narrative)

    if layout.blank_before_daily:
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
        if layout.blank_before_credit:
            lines.append("")
        observed = (data.get("current") or {}).get("observed")
        lines.append(credit_row(cols, runtime.lang, country_code, observed, runtime,
                                    data.get("timezone", "")))

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
            offset_minutes=offset_minutes, now=now_local,
        ) or _build_daily_tooltip(
            data, mouse_col, mouse_row, daily_start, daily_spans, cols, rows, runtime,
            now=now_local,
        )
    output = _live.overlay(output, overlay)

    return output, alert_row_map


def main():
    # the live view draws through render_from_data, so weather.live
    # imports this module; importing it here, at the call, keeps that
    # one-way at load
    from linecast.weather.live import main as live_main
    live_main()


_theme.track_imports(globals(), "linecast.weather.style")
