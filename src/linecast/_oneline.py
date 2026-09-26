"""Compact single-line renderers for tmux status bars, polybar, and prompts.

Each function returns a plain string (with optional ANSI color) suitable for
embedding in a status bar.  The ``--oneline`` flag in each subcommand triggers
these renderers instead of the full terminal UI.
"""

from linecast.weather.i18n import fmt_wind
from linecast._i18n import fmt_decimal, fmt_duration_parts, fmt_percent, has_duration_words, lang_of
from linecast._graphics import fg, RESET
from linecast._framebuffer import fmt_time, fmt_time_dt


def emit(line, stream=None):
    """Print a one-line summary: in display order on a terminal, in
    logical order for a status bar, which orders it itself."""
    import sys
    from linecast._bidi import for_stream
    stream = sys.stdout if stream is None else stream
    print(for_stream(line, stream), file=stream)


# ---------------------------------------------------------------------------
# Weather oneline
# ---------------------------------------------------------------------------

def weather_oneline(data, location_name, runtime):
    """Return a compact weather summary line.

    Example: ``Portland 58°F Partly cloudy Wind 8mph 💧32%``
    """
    from linecast.weather.cover import sky_condition
    from linecast.weather.i18n import _wmo_icons, wmo_label
    from linecast.weather.style import _colored_temp, TEXT, MUTED, WIND_COLOR

    if not data:
        return "No weather data"

    # A key present and null is a reading the model has no value for;
    # the line leaves it out rather than print it as 0
    current = data.get("current") or {}
    temp = current.get("temperature_2m")
    wmo = sky_condition(current.get("weather_code") or 0, current.get("cloud_cover"))
    wind = current.get("wind_speed_10m") or 0
    humidity = current.get("relative_humidity_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    desc = wmo_label(wmo, runtime.lang)

    deg = runtime.temp_unit
    parts = []

    if location_name:
        # Use short location: first component only (e.g. "Portland" from "Portland, ME")
        short_name = location_name.split(",")[0].strip()
        parts.append(f"{TEXT}{short_name}")

    if temp is not None:
        parts.append(f"{_colored_temp(temp, runtime, deg)}")
    parts.append(f"{TEXT}{icon} {desc}")

    if wind > 0:
        from linecast.weather.i18n import _s
        parts.append(f"{WIND_COLOR}{_s('wind', runtime)} {fmt_wind(wind, runtime)}")

    if humidity is not None:
        parts.append(f"{MUTED}\U0001f4a7{fmt_percent(humidity, runtime)}")

    return " ".join(parts) + RESET


# ---------------------------------------------------------------------------
# Sunshine oneline
# ---------------------------------------------------------------------------

def sunshine_oneline(lat, lng, doy, now_hour, runtime, tz_offset_h=None,
                     hours=None, now=None):
    """Return a compact solar summary line.

    Example: ``sunrise 5:42a sunset 7:38p 12h34m +2m waning_crescent_icon``

    With *hours*, the day read in a tradition's hours, the reading of
    *now* follows: ``4:20 · 1h=57m`` for the halachic hours, ``Dhuhr ·
    Asr in 41m`` for the prayer times.
    """
    from linecast.sunshine.solar import solar_times
    from linecast.moon.phase import moon_phase
    from datetime import datetime

    sunrise, sunset = solar_times(lat, lng, doy, tz_offset_h)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

    # Yesterday's day length for delta
    y_rise, y_set = solar_times(lat, lng, doy - 1, tz_offset_h)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "−"
    d_abs = abs(delta_sec)
    d_m = int(d_abs) // 60
    d_s = int(d_abs) % 60

    # Moon phase
    now_dt = datetime.now()
    _idx, _name, moon_icon = moon_phase(now_dt, runtime)

    # Format sunrise/sunset times compactly
    def _fmt(h):
        return fmt_time(h, use_24h=runtime.use_24h)

    if not has_duration_words(lang_of(runtime)):
        delta_str = f"{d_sign}{d_m}m{d_s}s" if d_s else f"{d_sign}{d_m}m"
    else:
        parts = [("m", d_m), ("s", d_s)] if d_s else [("m", d_m)]
        delta_str = fmt_duration_parts(lang_of(runtime), *parts, sign=d_sign)

    from linecast.sunshine.palette import (
        INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB, INFO_DIM_RGB,
    )
    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)
    dim = fg(*INFO_DIM_RGB)

    line = (
        f"{amber}↑{text}{_fmt(sunrise)} "
        f"{purple}↓{text}{_fmt(sunset)} "
        f"{text}{dl_h}h{dl_m:02d}m "
        f"{dim}{delta_str} "
        f"{text}{moon_icon}"
    )
    if hours is not None and now is not None:
        from linecast.sunshine.hours import corner_reading
        tail = corner_reading(hours, now, runtime).replace(" = ", "=")
        if tail:
            line += f" {text}{tail}"
    return line + RESET


# ---------------------------------------------------------------------------
# Moon oneline
# ---------------------------------------------------------------------------

def moon_oneline(now_local, lat, lng, runtime, calendar=None):
    """Return a compact moon summary line.

    Example: ``waxing_gibbous_icon Waxing Gibbous 84% ↓4:12a ↑9:41p``

    Rise/set are the *next* events from now — never today's already-passed
    ones — listed chronologically, so a leading ↓ means the Moon is up.

    With a traditional calendar in effect the line carries what the
    panel's headline carries: the night's name in place of the phase
    name where the calendar names nights, and the lunar date (or the
    anahulu, or the almanac's half of the month) after the events —
    ``… ↓4:12a ↑9:41p · 20 Elul 5786`` — so the line a status bar
    already shows is unchanged up to the new ending.
    """
    from linecast.moon.view import (
        calendar_headline, moon_illumination, upcoming_moon_events,
    )
    from linecast.moon.phase import moon_phase
    from linecast.sunshine.palette import INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB
    from linecast._i18n import lang_of
    from linecast._calendars.lunisolar import resolve_calendar
    from linecast.tides.i18n import _moon_name

    idx, _name, icon = moon_phase(now_local, runtime)
    name = _moon_name(idx, runtime)
    illum = moon_illumination(now_local)
    lang = lang_of(runtime)
    cal_name, aside = calendar_headline(
        resolve_calendar(calendar, lang), now_local, lat, lng, runtime, lang)
    if cal_name:
        name = cal_name

    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)

    parts = [f"{text}{icon} {name} {fmt_percent(illum * 100, runtime)}"]

    rise, sset = upcoming_moon_events(now_local, lat, lng)
    events = sorted(
        (dt, arrow) for dt, arrow in ((rise, "↑"), (sset, "↓")) if dt
    )
    for dt, arrow in events:
        color = amber if arrow == "↑" else purple
        parts.append(f"{color}{arrow}{text}{fmt_time_dt(dt, use_24h=runtime.use_24h)}")
    if aside:
        parts.append(f"{text}· {aside}")

    return " ".join(parts) + RESET


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
        height = fmt_decimal(h_display, 1, runtime)
        parts.append(f"{TEXT}{arrow}{label} {time_str} {height}{runtime.height_unit}")

    return " ".join(parts) + RESET


# ---------------------------------------------------------------------------
# Sky oneline
# ---------------------------------------------------------------------------

def sky_oneline(now_local, lat, lng, runtime):
    """Return a compact sky summary line.

    Example: ``🌖 84% W 31° · Jupiter SE 42° · Saturn S 20°``

    The Moon if it is up, then the planets up and bright enough for the
    sky as it is, brightest first, each with the way to look and how
    high; the sky's name when nothing is.
    """
    from datetime import timezone
    from linecast.sky.view import Scene, compass_point, easily_seen, TEXT_RGB, DIM_RGB
    from linecast._i18n import lang_of
    from linecast.sky.catalogue import resolve_culture
    from linecast.sky.i18n import _sk, body_name
    from linecast.sunshine.i18n import sky_phase
    from linecast.moon.phase import moon_phase

    scene = Scene(now_local.astimezone(timezone.utc), lat, lng)
    culture = resolve_culture(None, lang_of(runtime))
    text, dim = fg(*TEXT_RGB), fg(*DIM_RGB)
    parts = []
    if scene.moon_alt > 0.0:
        _idx, _name, icon = moon_phase(scene.moment_utc, runtime)
        parts.append(f"{text}{icon} {fmt_percent(scene.moon_illum * 100, runtime)} "
                     f"{compass_point(scene.moon_az, runtime, culture)} {scene.moon_alt:.0f}°")
    for key, _vec, alt, az, mag in scene.planets:
        if alt > 0.0 and easily_seen(mag, alt, scene):
            parts.append(f"{text}{body_name(key, runtime)} "
                         f"{compass_point(az, runtime, culture)} {alt:.0f}°")
    if not parts:
        parts.append(f"{dim}{sky_phase(scene.sun_alt, runtime, morning=scene.morning())}"
                     f" · {_sk('planets_none', runtime)}")
    return f"{dim} · ".join(parts) + RESET
