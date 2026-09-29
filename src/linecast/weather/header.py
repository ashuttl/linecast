"""The header: the conditions now, in a line across the top of the
dashboard, and the place at its right."""

from linecast.terminal.color import RESET
from linecast.terminal.textwidth import visible_len
from linecast.terminal import theme as _theme
from linecast._i18n import lang_of
from linecast._runtime import WeatherRuntime, current_runtime
from linecast._log import log_failure
from linecast.weather.cover import sky_condition
from linecast.weather.i18n import fmt_wind, felt_index, wmo_label, _s, _wmo_icons
from linecast.weather import style as _style
from linecast.weather.style import (MUTED, TEXT, WIND_COLOR, _aqhi_color, _aqi_color,
                                     _colored_temp, _india_aqi_color)
from linecast.weather.forecast import local_now


def location_control(name, width, runtime):
    from linecast.terminal.textwidth import fit
    from linecast.weather.locations_i18n import ls
    return fit(name or ls('locations', runtime.lang), max(0, min(width - 6, width // 2))) + ' ▼'


def location_chip(label):
    """The place as a chip, like the tides station pill: half blocks
    round the ends of a lifted surface, the name in the full text color."""
    edge, surface, ink = _style.CHIP
    if not surface:  # no color: half blocks alone would read as stray marks
        return f"{TEXT}{label}"
    return f"{edge}\u2590{surface}{ink} {label} {RESET}{edge}\u258c"


def render_header(data, width, location_name="", runtime=None, aqi_data=None, historical=None,
                  location_menu=False, now=None):
    """Current conditions header line."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    # A key can be present and null when the model has no value for
    # the hour; a null reading is left off the line, not printed as 0.
    current = data.get("current") or {}
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    wmo = sky_condition(current.get("weather_code") or 0, current.get("cloud_cover"))
    wind = current.get("wind_speed_10m") or 0
    gusts = current.get("wind_gusts_10m") or 0
    humidity = current.get("relative_humidity_2m")
    dew_point = current.get("dew_point_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    name = wmo_label(wmo, runtime.lang)

    deg = runtime.temp_unit
    left_core = f"{TEXT}{icon} {name}"
    if temp is not None:
        left_core += f" {_colored_temp(temp, runtime, deg)}"
    # In Canada the humidex or the wind chill, as Environment Canada
    # reports them, and nothing on a day that has neither.  They are
    # indices, so they go without the degree sign: "humidex 34".
    left_feels = ""
    index = felt_index(current, runtime)
    if index:
        key, value = index
        left_feels = f" {MUTED}{_s(key, runtime)} {_colored_temp(value, runtime)}"
    elif index is False and feels is not None:
        left_feels = f" {MUTED}{_s('feels', runtime)} {_colored_temp(feels, runtime, deg)}"

    # Historical comparison — subtle annotation after feels-like
    left_hist = ""
    if historical is not None:
        try:
            from linecast.weather.historical import format_historical_comparison
            daily = data.get("daily") or {}
            hi_temps = daily.get("temperature_2m_max") or []
            lo_temps = daily.get("temperature_2m_min") or []
            # A cached forecast's second entry may no longer be today.
            today = (now if now is not None else local_now(data)).date().isoformat()
            index = next((i for i, day in enumerate(daily.get("time") or [])
                          if day == today), -1)
            if (0 <= index < min(len(hi_temps), len(lo_temps))
                    and hi_temps[index] is not None and lo_temps[index] is not None):
                hist_text = format_historical_comparison(
                    hi_temps[index], historical, runtime,
                )
                if hist_text:
                    left_hist = f" {MUTED}({hist_text})"
        except Exception as exc:
            log_failure("weather/climate", "historical comparison", exc,
                        fallback="annotation omitted")

    # Humidity/dew point — show when notable
    left_humidity = ""
    moisture = _style.notable_moisture(humidity, dew_point, runtime, deg)
    if moisture:
        key, shown = moisture
        left_humidity = f"  {MUTED}{_s(key, runtime)} {shown}"

    # AQI — show when data available. India reads its own CPCB scale
    # and Canada its AQHI, attached upstream (apply_national_index); the
    # number, its colors, and the category word follow that scale
    # there. The category ("Very Poor", "Moderate risk") is how the
    # bulletins print the index, and it is what tells a reader which
    # scale the number is on.
    aqi_value = None
    india_scale = False
    aqhi = None
    if aqi_data and isinstance(aqi_data, dict):
        aqi_current = aqi_data.get("current", {})
        india_value = aqi_current.get("india_aqi")
        aqhi = aqi_current.get("aqhi")
        if india_value is not None:
            aqi_value = india_value
            india_scale = True
        else:
            aqi_value = aqi_current.get("us_aqi")

    # The number alone (left_aqi_bare) is the next thing tried when the
    # category word costs the line its fit.
    left_aqi = left_aqi_bare = ""
    if aqhi is not None:
        from linecast.weather.air import aqhi_category, fmt_aqhi
        left_aqi_bare = f"  {MUTED}{_s('aqhi', runtime)} {_aqhi_color(aqhi)}{fmt_aqhi(aqhi)}"
        left_aqi = f"{left_aqi_bare} {aqhi_category(aqhi, lang_of(runtime))}"
    elif aqi_value is not None:
        if india_scale:
            from linecast.weather.air import india_aqi_category
            color = _india_aqi_color(aqi_value)
            category = india_aqi_category(aqi_value)
            left_aqi_bare = f"  {MUTED}{_s('aqi', runtime)} {color}{aqi_value:.0f}"
            left_aqi = f"{left_aqi_bare} {category}"
        else:
            left_aqi = left_aqi_bare = (f"  {MUTED}{_s('aqi', runtime)} "
                                        f"{_aqi_color(aqi_value)}{aqi_value:.0f}")

    # Right side: wind info + location (progressively droppable)
    wind_part = ""
    if runtime.wind_kmh(wind) > 15 or runtime.wind_kmh(gusts) > 30:
        parts = [f"{_s('wind', runtime)} {fmt_wind(wind, runtime)}"]
        if runtime.wind_kmh(gusts) > 30:
            parts.append(f"{_s('gusts', runtime)} {fmt_wind(gusts, runtime)}")
        wind_part = f"{WIND_COLOR}{'  '.join(parts)}"
    loc_part = ""
    if location_menu:
        loc_part = location_chip(location_control(location_name, width, runtime))
    elif location_name:
        from linecast.terminal.textwidth import fit
        loc_part = location_chip(fit(location_name, max(0, min(width - 4, width // 2))))

    # The first rung that fits is the line.  The left side gives up the
    # humidity, the air quality's category word, then its number, then
    # the historical comparison; past that, the location, the feels-like
    # and the wind take turns.  A rung the same as the one above it (no
    # category word to drop) fails again.
    feels = left_core + left_feels
    rungs = [
        (feels + left_hist + left_humidity + left_aqi, (wind_part, loc_part)),
        (feels + left_hist + left_aqi, (wind_part, loc_part)),
        (feels + left_hist + left_aqi_bare, (wind_part, loc_part)),
        (feels + left_hist, (wind_part, loc_part)),
        (feels, (wind_part, loc_part)),
    ]
    if location_menu:
        # The live location is a control: keep it even when conditions are long.
        rungs += [(feels, (loc_part,)), (left_core, (loc_part,))]
    else:
        rungs += [(feels, (wind_part,)),
                  (left_core, (wind_part, loc_part)),
                  (left_core, (wind_part,)),
                  (left_core, (loc_part,))]
    for left, right in rungs:
        result = _assemble(left, right, width)
        if result:
            return result

    if location_menu:
        from linecast.terminal.textwidth import fit
        room = max(0, width - visible_len(loc_part) - 1)
        core = f"{icon} {name}" + (f" {round(temp)}{deg}" if temp is not None else "")
        plain = fit(core, room)
        return f"{TEXT}{plain}{' ' * max(0, width - visible_len(plain) - visible_len(loc_part))}" \
               f"{loc_part}{RESET}"

    # Last resort: the conditions alone
    return f"{left_core}{RESET}"


def _assemble(left, right, width):
    """`left`, and the `right` parts at the far end of `width` with at
    least two cells between, or None when they do not fit.  With nothing
    at the right, `left` alone, however long."""
    right = "  ".join(part for part in right if part)
    if not right:
        return f"{left}{RESET}"
    pad = width - visible_len(left) - visible_len(right)
    if pad >= 2:  # the two halves keep the gap the parts within them do
        return f"{left}{' ' * pad}{right}{RESET}"
    return None


_theme.track_imports(globals(), "linecast.weather.style")
