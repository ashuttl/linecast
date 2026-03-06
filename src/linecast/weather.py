#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, comparative weather line, and weather alerts.
Temperature-driven color palette, Nerd Font icons, clean column alignment.

Alerts are sourced from NWS (US) and Environment Canada (CA).

Usage: weather [--live] [--location LAT,LNG] [--search CITY] [--emoji] [--celsius/--metric] [--shading] [--lang fr]
"""

import os
import sys

from linecast._graphics import get_terminal_size, live_loop
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
    render_alerts,
    render_daily,
    render_header,
    render_hourly,
)
from linecast._weather_sources import (
    CACHE_DIR,
    _eccc_severity,
    _fetch_alerts_eccc,
    _fetch_alerts_nws,
    _local_now_for_data,
    _location_from_timezone,
    _reverse_geocode,
    _search_locations,
    fetch_alerts,
    fetch_forecast,
)


def render_from_data(data, alerts, runtime, location_name="", offset_minutes=0):
    """Build the complete weather dashboard from preloaded data."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}"

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)

    # Pre-render alerts to get their exact line count for budgeting
    alert_lines = []
    if alerts:
        # Use a generous budget for the initial render; we'll re-render later
        # if needed once we know the actual remaining space
        alert_lines = render_alerts(alerts, width=cols, remaining_rows=max(4, rows // 3), runtime=runtime)

    # Count fixed-height sections to budget remaining rows for graphs
    # Header(1) + blank(1) + hourly_header(1) + tick_labels(1) + wind_row(1)
    # + comp_line(1) + precip_text(1) + past_precip(1) + blank(1)
    # + daily(7) = ~16 fixed lines, plus alerts
    alert_lines_count = (len(alert_lines) + 1) if alert_lines else 0  # +1 for blank separator
    fixed_lines = 16 + alert_lines_count
    available = max(0, rows - fixed_lines)

    # Distribute available rows between temperature graph and precip graph
    # Precip gets up to 3 braille rows, temp gets the rest
    hourly = data.get("hourly", {})
    has_precip_graph = bool(hourly.get("precipitation_probability")) and max(hourly.get("precipitation_probability", [0])) > 5
    if has_precip_graph:
        n_precip_braille = min(3, max(1, available // 6))
        remaining_for_temp = available - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = available

    # Temperature graph: minimum 2 braille rows, grows to fill available space
    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime))
    lines.append("")

    # Hourly
    lines.extend(
        render_hourly(
            data,
            cols,
            n_braille_rows=n_braille,
            n_precip_rows=n_precip_braille,
            now=now_local,
            runtime=runtime,
        )
    )

    # Comparative line
    comp = _comparative_line(data.get("daily", {}), now_local, runtime)
    if comp:
        lines.append(comp)

    # Precipitation forecast
    precip = _precipitation_line(data.get("hourly", {}), now_local, runtime)
    if precip:
        lines.append(precip)

    # Past 24h precipitation
    past_precip = _past_precip_line(data.get("hourly", {}), now_local, runtime)
    if past_precip:
        lines.append(past_precip)

    lines.append("")

    # Daily
    lines.extend(render_daily(data, cols, runtime))

    # Alerts (re-render with exact remaining space if needed)
    if alerts:
        lines.append("")
        remaining = max(4, rows - len(lines) - 1)
        if remaining != max(4, rows // 3):
            alert_lines = render_alerts(alerts, width=cols, remaining_rows=remaining, runtime=runtime)
        lines.extend(alert_lines)

    return "\n".join(lines)


def render(lat, lng, location_name="", country_code="", offset_minutes=0, runtime=None, data=None, alerts=None):
    """Build the complete weather dashboard."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    if data is None:
        data = fetch_forecast(lat, lng, runtime)
    if alerts is None:
        alerts = fetch_alerts(lat, lng, country_code, lang=runtime.lang)
    return render_from_data(data, alerts, runtime, location_name=location_name, offset_minutes=offset_minutes)


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
        name, cc = _reverse_geocode(lat, lng)
        result["name"] = name
        result["country_code"] = cc or country_code
        result["data"] = fetch_forecast(lat, lng, runtime)
        result["alerts"] = fetch_alerts(lat, lng, result["country_code"], lang=runtime.lang)
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
        live_loop(
            lambda offset_minutes=0: render(
                lat,
                lng,
                location_name,
                final_country,
                offset_minutes=offset_minutes,
                runtime=runtime,
            ),
            interval=300,
        )
    else:
        print(
            render(
                lat,
                lng,
                location_name,
                final_country,
                runtime=runtime,
                data=data,
                alerts=alerts,
            )
        )


if __name__ == "__main__":
    main()
