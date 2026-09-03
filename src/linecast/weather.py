#!/usr/bin/env python3
"""Weather — terminal weather dashboard.

Renders a text-based dashboard with current conditions, braille temperature
curve, daily range bars, comparative weather line, and weather alerts.
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

import sys
import threading
import time as _t

from linecast import _live
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
)
from linecast._weather_render import (
    ALERT_AMBER,
    MUTED,
    RESET,
    TEXT,
    TOOLTIP_BG_RGB,
    TOOLTIP_TEXT_RGB,
    WIND_ARROWS,
    _colored_temp,
    _comparative_line,
    _fmt_time,
    _past_precip_line,
    _precipitation_line,
    _prepare_hourly_window,
    build_alert_modal,
    render_alerts,
    render_daily,
    render_header,
    render_hourly,
)
from linecast._weather_historical import fetch_historical
from linecast._weather_sources import (
    _local_now_for_data,
    _reverse_geocode,
    _search_locations,
    apply_india_aqi,
    fetch_aqi,
    fetch_alerts,
    fetch_forecast,
    forecast_date,
)


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

    graph_w = max(10, cols - 2)
    graph_col = mouse_col - 2  # 1-based terminal col → 0-based graph col (1 char margin)
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
        lines.append(f"{TBG}{TFG} {wmo_name} ")

    # Humidity / dew point (when notable)
    if humidity is not None and dew is not None:
        dew_f = dew * 9 / 5 + 32 if runtime.celsius else dew
        if dew_f >= 60:
            lines.append(f"{TBG}{TFG} {_s('dew_pt', runtime)} {_colored_temp(dew, runtime, deg)} ")
        elif humidity >= 70 or humidity <= 25:
            lines.append(f"{TBG}{TFG} {_s('humidity', runtime)} {humidity:.0f}% ")

    # Wind (if notable)
    wind_threshold = 25 if runtime.metric else 15
    if wind > wind_threshold:
        sector = int((wind_dir + 22.5) / 45) % 8
        arrow = WIND_ARROWS[sector]
        lines.append(f"{TBG}{TFG} {arrow} {wind:.0f}{runtime.wind_unit} ")

    if not lines:
        return ""

    # Snapped hour column (1-based terminal col) — use int() to match midnight divider formula
    snap_col = int(idx / max(1, total_hours) * (graph_w - 1)) + 2

    return _live.pointer_chip(lines, snap_col, mouse_row, cols, rows, pad_bg=TBG)


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
                     notice=None):
    """Build the complete weather dashboard from preloaded data.

    `notice` is a line for under the header -- forecast_notice's, when
    the forecast is not today's."""
    if not data:
        return f"{TEXT}Could not fetch weather data.{RESET}", {}

    cols, rows = get_terminal_size()
    now_local = _local_now_for_data(data)
    tz_name = data.get("timezone", "")

    # Pre-render fixed-height sections to budget graph rows accurately
    alert_lines = (render_alerts(alerts, width=cols, runtime=runtime, tz_name=tz_name)
                   if alerts else [])
    comp = _comparative_line(data.get("daily", {}), now_local, runtime)
    precip = _precipitation_line(data.get("hourly", {}), now_local, runtime)
    past_precip = _past_precip_line(data.get("hourly", {}), now_local, runtime)
    daily_lines_rendered = render_daily(data, cols, runtime, now=now_local)

    # Count non-hourly lines precisely
    non_hourly = 2  # header + blank
    if notice:
        non_hourly += 1
    if comp:
        non_hourly += 1
    if precip:
        non_hourly += 1
    if past_precip:
        non_hourly += 1
    non_hourly += 1  # blank before daily
    non_hourly += len(daily_lines_rendered)
    if alert_lines:
        non_hourly += 1 + len(alert_lines)  # blank + alerts

    # All remaining rows go to hourly section
    # hourly contains: today_line(1) + tick(1) + braille(N) + wind(0-1) + uv(0-1) + precip(0-P)
    hourly_budget = max(4, rows - non_hourly)
    graph_budget = hourly_budget - 2  # today_line + tick_labels

    hourly = data.get("hourly", {})

    # Check full dataset for optional rows so layout stays stable while scrolling
    wind_threshold = 25 if runtime.metric else 15
    all_winds = hourly.get("wind_speed_10m", [])
    has_wind_row = bool(all_winds) and max(all_winds) > wind_threshold
    all_uv = hourly.get("uv_index", [])
    has_uv_row = bool(all_uv) and max(all_uv) >= 6
    if has_wind_row:
        graph_budget -= 1
    if has_uv_row:
        graph_budget -= 1

    has_precip_graph = (bool(hourly.get("precipitation_probability"))
                        and max(hourly.get("precipitation_probability", [0])) > 5)
    if has_precip_graph:
        n_precip_braille = min(3, max(1, graph_budget // 6))
        remaining_for_temp = graph_budget - n_precip_braille
    else:
        n_precip_braille = 0
        remaining_for_temp = graph_budget

    n_braille = max(2, remaining_for_temp)

    lines = []

    # Header
    lines.append(render_header(data, cols, location_name, runtime=runtime, aqi_data=aqi_data,
                               historical=historical))
    if notice:
        lines.append(notice)
    lines.append("")

    # Hourly — first pass without hover to establish line boundaries
    hourly_start = len(lines)
    hourly_lines = render_hourly(
        data, cols, n_braille_rows=n_braille, n_precip_rows=n_precip_braille,
        now=now_local, runtime=runtime, offset_minutes=offset_minutes,
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
                window = _prepare_hourly_window(hourly, now_local, graph_w,
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
            offset_minutes=offset_minutes,
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

    hint = install_banner()
    if hint:
        lines.append(hint)

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
            self.attempted = _local_now_for_data(self.data)
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
        )

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
        print(output)


if __name__ == "__main__":
    main()
