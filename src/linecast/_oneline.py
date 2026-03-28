"""Compact single-line renderers for tmux status bars, polybar, and prompts.

Each function returns a plain string (with optional ANSI color) suitable for
embedding in a status bar.  The ``--oneline`` flag in each subcommand triggers
these renderers instead of the full terminal UI.
"""

from linecast._graphics import fg, RESET
from linecast._framebuffer import fmt_time, fmt_time_dt


# ---------------------------------------------------------------------------
# Weather oneline
# ---------------------------------------------------------------------------

def weather_oneline(data, location_name, runtime):
    """Return a compact weather summary line.

    Example: ``Portland 58°F Partly Cloudy Wind 8mph 💧32%``
    """
    from linecast._weather_i18n import WMO_NAMES, WMO_NAMES_I18N, _wmo_icons
    from linecast._weather_style import _colored_temp, TEXT, MUTED, WIND_COLOR

    if not data:
        return "No weather data"

    current = data.get("current", {})
    temp = current.get("temperature_2m", 0)
    wmo = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    humidity = current.get("relative_humidity_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    desc = WMO_NAMES_I18N.get(runtime.lang, {}).get(wmo) or WMO_NAMES.get(wmo, "")

    deg = runtime.temp_unit
    parts = []

    if location_name:
        # Use short location: first component only (e.g. "Portland" from "Portland, ME")
        short_name = location_name.split(",")[0].strip()
        parts.append(f"{TEXT}{short_name}")

    parts.append(f"{_colored_temp(temp, runtime, deg)}")
    parts.append(f"{TEXT}{icon} {desc}")

    if wind > 0:
        from linecast._weather_i18n import _s
        parts.append(f"{WIND_COLOR}{_s('wind', runtime)} {wind:.0f}{runtime.wind_unit}")

    if humidity is not None:
        parts.append(f"{MUTED}\U0001f4a7{humidity:.0f}%")

    return " ".join(parts) + RESET


# ---------------------------------------------------------------------------
# Sunshine oneline
# ---------------------------------------------------------------------------

def sunshine_oneline(lat, lng, doy, now_hour, runtime):
    """Return a compact solar summary line.

    Example: ``sunrise 5:42a sunset 7:38p 12h34m +2m waning_crescent_icon``
    """
    from linecast.sunshine import solar_times, moon_phase
    from datetime import datetime

    sunrise, sunset = solar_times(lat, lng, doy)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

    # Yesterday's day length for delta
    y_rise, y_set = solar_times(lat, lng, doy - 1)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "\u2212"
    d_abs = abs(delta_sec)
    d_m = int(d_abs) // 60
    d_s = int(d_abs) % 60

    # Moon phase
    now_dt = datetime.now()
    _idx, _name, moon_icon = moon_phase(now_dt, runtime)

    # Format sunrise/sunset times compactly
    use_24h = runtime.use_24h
    if use_24h:
        def _fmt(h):
            hh = int(h) % 24
            mm = int((h % 1) * 60)
            return f"{hh:02d}:{mm:02d}"
    else:
        def _fmt(h):
            hh = int(h) % 24
            mm = int((h % 1) * 60)
            if hh == 0:
                return f"12:{mm:02d}a"
            if hh == 12:
                return f"12:{mm:02d}p"
            if hh < 12:
                return f"{hh}:{mm:02d}a"
            return f"{hh - 12}:{mm:02d}p"

    delta_str = f"{d_sign}{d_m}m{d_s}s" if d_s else f"{d_sign}{d_m}m"

    from linecast.sunshine import INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB, INFO_DIM_RGB
    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)
    dim = fg(*INFO_DIM_RGB)

    line = (
        f"{amber}\u2191{text}{_fmt(sunrise)} "
        f"{purple}\u2193{text}{_fmt(sunset)} "
        f"{text}{dl_h}h{dl_m:02d}m "
        f"{dim}{delta_str} "
        f"{text}{moon_icon}"
    )
    return line + RESET


# ---------------------------------------------------------------------------
# Tides oneline
# ---------------------------------------------------------------------------

def tides_oneline(station_name, hilo_data, now_local, runtime):
    """Return a compact tide summary line.

    Example: ``Casco Bay ▲High 2:14p 9.2ft ▼Low 8:47p 1.1ft``

    *hilo_data* is a list of ``(datetime, height_ft, type_str)`` tuples where
    ``type_str`` is ``"H"`` or ``"L"``.
    """
    from linecast._graphics import fg, RESET
    from linecast._theme import theme_fg, ensure_contrast, theme_bg

    text_rgb = ensure_contrast(theme_fg, theme_bg, minimum=4.5)
    TEXT = fg(*text_rgb)

    parts = []

    if station_name:
        short = station_name.split(",")[0].strip()
        parts.append(f"{TEXT}{short}")

    if not hilo_data:
        parts.append(f"{TEXT}No tide data")
        return " ".join(parts) + RESET

    # Find the next two tide events (from now onward), falling back to the
    # last two if we're past all events.
    upcoming = [(dt, h, t) for dt, h, t in hilo_data if dt >= now_local]
    if len(upcoming) >= 2:
        events = upcoming[:2]
    elif len(upcoming) == 1:
        # One upcoming + the most recent past event
        past = [(dt, h, t) for dt, h, t in hilo_data if dt < now_local]
        if past:
            events = [past[-1], upcoming[0]]
        else:
            events = upcoming[:1]
    else:
        # All past — show the last two
        events = hilo_data[-2:]

    use_24h = runtime.use_24h

    for dt, height_ft, typ in events:
        h_display = runtime.convert_height(height_ft)
        is_high = typ == "H"
        arrow = "\u25b2" if is_high else "\u25bc"
        label = "High" if is_high else "Low"
        time_str = fmt_time_dt(dt, use_24h=use_24h)
        parts.append(f"{TEXT}{arrow}{label} {time_str} {h_display:.1f}{runtime.height_unit}")

    return " ".join(parts) + RESET
