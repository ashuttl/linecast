#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, comparative weather line, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts sourced from NWS (US), Environment Canada (CA), Bright Sky/DWD (DE),
MET Norway (NO), Met \u00c9ireann (IE), JMA (Japan), and MeteoAlarm (30 European countries).

Languages: en, fr, es, de, it, pt, nl, pl, no, sv, is, da, fi, ja

Usage: weather [--live] [--location LAT,LNG] [--search CITY] [--emoji] [--metric] [--celsius] [--fahrenheit] [--shading] [--lang fr]
"""

import os
import sys

from linecast._graphics import bg, fg, get_terminal_size, live_loop, visible_len
from linecast._location import get_location
from linecast._runtime import WeatherRuntime, arg_value, has_flag
from linecast._weather_i18n import (
    _PRECIP_DESCS_I18N,
    _STRINGS,
    _WMO_ICONS_EMOJI,
    _WMO_ICONS_NERD,
    DAY_NAMES,
    FULL_DAY_NAMES,
    WMO_NAMES,
    WMO_NAMES_I18N,
    _s,
    _wmo_icons,
)
from linecast._weather_render import (
    ALERT_AMBER,
    ALERT_RED,
    ALERT_YELLOW,
    DIM,
    MUTED,
    PRECIP,
    PRECIP_MIX,
    PRECIP_RAIN,
    PRECIP_SNOW,
    PRECIP_STORM,
    RESET,
    SEP,
    SPARKLINE,
    TEMP_COLORS,
    TEXT,
    WIND_ARROWS,
    WIND_COLOR,
    _PRECIP_CODES,
    _PRECIP_DESCS,
    _build_braille_curve,
    _build_precip_blocks,
    _colored_temp,
    _comparative_line,
    _compute_daylight_columns,
    _compute_sun_labels,
    _compute_time_markers,
    _daylight_factor,
    _find_temperature_extrema,
    _fmt_hour,
    _fmt_time,
    _interpolate_columns,
    _parse_alert_time,
    _parse_sun_events,
    _past_precip_line,
    _precip_color,
    _precip_type,
    _precipitation_line,
    _prepare_hourly_window,
    _render_braille_rows,
    _render_extrema_line,
    _render_precip_rows,
    _render_single_alert,
    _render_tick_labels,
    _render_today_line,
    _render_wind_row,
    _severity_color,
    _severity_rgb,
    _temp_color,
    build_alert_modal,
    render_alerts,
    render_daily,
    render_header,
    render_hourly,
)
from linecast._weather_sources import (
    CACHE_DIR,
    _eccc_severity,
    _fetch_alerts_brightsky,
    _fetch_alerts_eccc,
    _fetch_alerts_meteireann,
    _fetch_alerts_meteoalarm,
    _fetch_alerts_metno,
    _fetch_alerts_nws,
    _local_now_for_data,
    _location_from_timezone,
    _reverse_geocode,
    _search_locations,
    fetch_alerts,
    fetch_forecast,
)


def _build_hover_tooltip(data, mouse_col, mouse_row, hourly_start, hourly_end, cols, rows, runtime):
    """Build a tooltip overlay for mouse hover on the hourly chart.

    Returns cursor-positioned escape sequences to draw the tooltip, or "".
    mouse_col/mouse_row are 1-based terminal coordinates.
    hourly_start/hourly_end are 0-based line indices in the output.
    """
    # Check if mouse is over the hourly section (convert 1-based row to 0-based)
    line_idx = mouse_row - 1
    if not (hourly_start <= line_idx < hourly_end):
        return ""

    graph_w = max(10, cols - 2)
    graph_col = mouse_col - 2  # 1-based terminal col → 0-based graph col (1 char margin)
    if graph_col < 0 or graph_col >= graph_w:
        return ""

    hourly = data.get("hourly", {})
    now = _local_now_for_data(data)
    window = _prepare_hourly_window(hourly, now, graph_w)
    if window is None:
        return ""

    # Map graph column to nearest hour index (use int() to match midnight divider formula)
    n = len(window["temps"])
    total_hours = window["total_hours"]
    idx = int(graph_col / max(1, graph_w - 1) * total_hours + 0.5)
    idx = max(0, min(n - 1, idx))

    dt = window["dts"][idx] if idx < len(window["dts"]) else None
    temp = window["temps"][idx]
    apparent = window["apparent_temps"][idx] if idx < len(window.get("apparent_temps", [])) else None
    code = window["codes"][idx] if idx < len(window["codes"]) else 0
    wind = window["winds"][idx] if idx < len(window["winds"]) else 0
    wind_dir = window["wind_dirs"][idx] if idx < len(window["wind_dirs"]) else 0

    TBG = bg(0, 0, 0)
    TFG = fg(200, 205, 215)

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
        lines.append(f"{TBG}{TFG} {wmo_name} ")

    # Wind (if notable)
    wind_threshold = 25 if runtime.metric else 15
    if wind > wind_threshold:
        sector = int((wind_dir + 22.5) / 45) % 8
        arrow = WIND_ARROWS[sector]
        lines.append(f"{TBG}{TFG} {arrow} {wind:.0f}{runtime.wind_unit} ")

    if not lines:
        return ""

    # Pad all lines to the same visible width
    max_w = max(visible_len(line) for line in lines)
    padded = []
    for line in lines:
        pad = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad}{RESET}")

    # Snapped hour column (1-based terminal col) — use int() to match midnight divider formula
    snap_col = int(idx / max(1, total_hours) * (graph_w - 1)) + 2

    # Position: top-left anchored to snapped column, pushed inward at edges
    tooltip_w = max_w
    tooltip_h = len(padded)
    tooltip_col = snap_col
    tooltip_row = mouse_row
    if tooltip_col + tooltip_w - 1 > cols:
        tooltip_col = max(1, cols - tooltip_w + 1)
    if tooltip_row + tooltip_h - 1 > rows:
        tooltip_row = max(1, rows - tooltip_h + 1)

    # Tooltip
    result = ""
    for i, line in enumerate(padded):
        result += f"\033[{tooltip_row + i};{tooltip_col}H{line}"
    return result


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
    """Build the complete weather dashboard from preloaded data."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}", {}

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)

    # Pre-render fixed-height sections to budget graph rows accurately
    alert_lines = render_alerts(alerts, width=cols, runtime=runtime) if alerts else []
    comp = _comparative_line(data.get("daily", {}), now_local, runtime)
    precip = _precipitation_line(data.get("hourly", {}), now_local, runtime)
    past_precip = _past_precip_line(data.get("hourly", {}), now_local, runtime)
    daily_lines_rendered = render_daily(data, cols, runtime)

    # Count non-hourly lines precisely
    non_hourly = 2  # header + blank
    if comp: non_hourly += 1
    if precip: non_hourly += 1
    if past_precip: non_hourly += 1
    non_hourly += 1  # blank before daily
    non_hourly += len(daily_lines_rendered)
    if alert_lines:
        non_hourly += 1 + len(alert_lines)  # blank + alerts

    # All remaining rows go to hourly section
    # hourly contains: today_line(1) + braille(N) + tick(1) + wind(0-1) + precip(0-P)
    hourly_budget = max(4, rows - non_hourly)
    graph_budget = hourly_budget - 2  # today_line + tick_labels

    hourly = data.get("hourly", {})
    has_precip_graph = bool(hourly.get("precipitation_probability")) and max(hourly.get("precipitation_probability", [0])) > 5
    if has_precip_graph:
        n_precip_braille = min(3, max(1, graph_budget // 6))
        remaining_for_temp = graph_budget - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = graph_budget

    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime))
    lines.append("")

    # Hourly — first pass without hover to establish line boundaries
    hourly_start = len(lines)
    hourly_lines = render_hourly(
        data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
        now=now_local, runtime=runtime,
    )

    # Adjust if hourly used more/fewer lines than budgeted (wind appeared,
    # or precip didn't render for the visible window)
    if len(hourly_lines) != hourly_budget and n_braille > 2:
        adjusted = max(2, n_braille - (len(hourly_lines) - hourly_budget))
        if adjusted != n_braille:
            n_braille = adjusted
            hourly_lines = render_hourly(
                data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
                now=now_local, runtime=runtime,
            )

    hourly_end = hourly_start + len(hourly_lines)

    # Compute hover column only if mouse is within hourly section
    hover_graph_col = None
    if mouse_pos:
        mouse_row_idx = mouse_pos[1] - 1  # 1-based → 0-based
        if hourly_start <= mouse_row_idx < hourly_end:
            graph_w = max(10, cols - 2)
            mouse_col_raw = mouse_pos[0] - 2  # 1-based terminal col → 0-based graph col
            if 0 <= mouse_col_raw < graph_w:
                window = _prepare_hourly_window(hourly, now_local, graph_w)
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
        )

    lines.extend(hourly_lines)

    # Comparative line
    if comp:
        lines.append(comp)

    # Precipitation forecast
    if precip:
        lines.append(precip)

    # Past 24h precipitation
    if past_precip:
        lines.append(past_precip)

    lines.append("")

    # Daily
    lines.extend(daily_lines_rendered)

    # Alerts — one line per alert
    alert_row_map = {}  # 0-based line index → alert index
    if alerts:
        lines.append("")
        alert_start = len(lines)
        lines.extend(alert_lines)
        for i in range(len(alert_lines)):
            alert_row_map[alert_start + i] = i

    output = "\n".join(lines)

    overlay = ""
    if active_alert is not None and 0 <= active_alert < len(alerts):
        overlay, _max_scroll = build_alert_modal(
            alerts[active_alert], cols, rows, runtime=runtime, scroll=modal_scroll,
        )
    elif mouse_pos:
        mouse_col, mouse_row = mouse_pos
        overlay = _build_hover_tooltip(
            data, mouse_col, mouse_row,
            hourly_start, hourly_end,
            cols, rows, runtime,
        )
    if overlay:
        output += "\x00" + overlay

    return output, alert_row_map


def render(lat, lng, location_name="", country_code="", offset_minutes=0, runtime=None, data=None, alerts=None, mouse_pos=None, active_alert=None, modal_scroll=0):
    """Build the complete weather dashboard."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    if data is None:
        data = fetch_forecast(lat, lng, runtime)
    if alerts is None:
        alerts = fetch_alerts(lat, lng, country_code, lang=runtime.lang)
    return render_from_data(data, alerts, runtime, location_name=location_name, offset_minutes=offset_minutes, mouse_pos=mouse_pos, active_alert=active_alert, modal_scroll=modal_scroll)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    runtime = WeatherRuntime.from_sources()

    if has_flag("--help") or has_flag("-h"):
        print(__doc__.strip())
        return
    if has_flag("--version"):
        from linecast import __version__
        print(f"weather (linecast {__version__})")
        return

    # --search: geocode cities and exit
    search_q = arg_value("--search")
    if search_q:
        _search_locations(search_q, lang=runtime.lang)
        return

    # Location: --location flag > WEATHER_LOCATION env > geolocation
    loc_arg = arg_value("--location")
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
        name, cc, addr = _reverse_geocode(lat, lng)
        result["name"] = name
        result["country_code"] = cc or country_code
        result["data"] = fetch_forecast(lat, lng, runtime)
        result["alerts"] = fetch_alerts(lat, lng, result["country_code"], lang=runtime.lang, address=addr)
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
    data = result.get("data")
    alerts = result.get("alerts", [])

    if runtime.live:
        def _open_alert_url(idx):
            if 0 <= idx < len(alerts):
                url = alerts[idx].get("url", "")
                if url:
                    import webbrowser
                    webbrowser.open(url)

        live_loop(
            lambda offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0: render(
                lat,
                lng,
                location_name,
                final_country,
                offset_minutes=offset_minutes,
                runtime=runtime,
                mouse_pos=mouse_pos,
                active_alert=active_alert,
                modal_scroll=modal_scroll,
            ),
            interval=300,
            mouse=True,
            on_open=_open_alert_url,
        )
    else:
        output, _alert_map = render(
            lat,
            lng,
            location_name,
            final_country,
            runtime=runtime,
            data=data,
            alerts=alerts,
        )
        print(output)


if __name__ == "__main__":
    main()
