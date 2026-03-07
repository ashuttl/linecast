"""Header and narrative weather text sections."""

from datetime import datetime, timedelta

from linecast._graphics import RESET, visible_len
from linecast._runtime import WeatherRuntime
from linecast._weather_i18n import DAY_NAMES, WMO_NAMES, WMO_NAMES_I18N, _PRECIP_DESCS_I18N, _s, _wmo_icons
from linecast._weather_style import MUTED, TEXT, WIND_COLOR, _colored_temp


def render_header(data, width, location_name="", runtime=None):
    """Current conditions header line."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    current = data.get("current", {})
    temp = current.get("temperature_2m", 0)
    feels = current.get("apparent_temperature", 0)
    wmo = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    gusts = current.get("wind_gusts_10m", 0)

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    name = WMO_NAMES_I18N.get(runtime.lang, {}).get(wmo) or WMO_NAMES.get(wmo, "")

    left = (
        f" {TEXT}{icon} {name}  "
        f"{_colored_temp(temp, runtime, runtime.temp_unit)}"
        f"  {MUTED}{_s('feels', runtime)} {_colored_temp(feels, runtime, runtime.temp_unit)}"
    )

    right_parts = []
    if wind > (15 if runtime.metric else 10) or gusts > (30 if runtime.metric else 20):
        parts = [f"{_s('wind', runtime)} {wind:.0f}{runtime.wind_unit}"]
        if gusts > (30 if runtime.metric else 20):
            parts.append(f"{_s('gusts', runtime)} {gusts:.0f}{runtime.wind_unit}")
        right_parts.append(f"{WIND_COLOR}{'  '.join(parts)}")
    if location_name:
        right_parts.append(f"{MUTED}{location_name}")

    right = f"  {MUTED}\u00b7  ".join(right_parts) if right_parts else ""

    if right:
        pad = width - visible_len(left) - visible_len(right) - 2
        return f"{left}{' ' * max(1, pad)}{right} {RESET}"
    return f"{left}{RESET}"


# ---------------------------------------------------------------------------
# Comparative weather line
# ---------------------------------------------------------------------------
def _comparative_line(daily, now, runtime=None):
    """Natural language comparing today vs yesterday/tomorrow."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    hi_temps = daily.get("temperature_2m_max", [])

    # With past_days=1: index 0=yesterday, 1=today, 2=tomorrow
    if len(hi_temps) < 3:
        return ""

    if now.hour < 14:
        diff = hi_temps[1] - hi_temps[0]
        ref_day = _s("yesterday", runtime)
        subject = _s("today_subj", runtime)
    else:
        diff = hi_temps[2] - hi_temps[1]
        ref_day = _s("today_ref", runtime)
        subject = _s("tomorrow_subj", runtime)

    abs_diff = abs(diff)
    # Thresholds in degrees (smaller for Celsius since 1°C ≈ 1.8°F)
    t_same, t_bit, t_much = (2, 4, 8) if runtime.metric else (3, 8, 15)
    if abs_diff < t_same:
        key = "same_temp"
    elif abs_diff < t_bit:
        key = "bit_warmer" if diff > 0 else "bit_cooler"
    elif abs_diff < t_much:
        key = "warmer" if diff > 0 else "cooler"
    else:
        key = "much_warmer" if diff > 0 else "much_cooler"

    comparison = _s(key, runtime, ref_day=ref_day, subject=subject.lower())
    sentence = _s("will_be", runtime, subject=subject, comparison=comparison)
    return f" {MUTED}{sentence}{RESET}"


# ---------------------------------------------------------------------------
# Precipitation forecast line
# ---------------------------------------------------------------------------
_PRECIP_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}

_PRECIP_DESCS = {
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms", 99: "thunderstorms",
}


def _precipitation_line(hourly, now, runtime=None):
    """Natural language description of upcoming precipitation."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    lang = runtime.lang
    times = hourly.get("time", [])
    precip_prob = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])

    if not times or not precip_prob or not codes:
        return ""

    current_hour = now.replace(minute=0, second=0, microsecond=0)

    # Build window: (data_index, datetime) for next 24h
    window = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
            if dt >= current_hour:
                window.append((i, dt))
        except Exception:
            continue
    window = [(i, dt) for i, dt in window if dt <= current_hour + timedelta(hours=24)]
    if len(window) < 2:
        return ""

    def is_precip(idx):
        p = precip_prob[idx] if idx < len(precip_prob) else 0
        c = codes[idx] if idx < len(codes) else 0
        return c in _PRECIP_CODES and p > 30

    def desc(idx):
        c = codes[idx] if idx < len(codes) else 0
        descs = _PRECIP_DESCS_I18N.get(lang, _PRECIP_DESCS)
        return descs.get(c, _PRECIP_DESCS.get(c, "precipitation"))

    def time_phrase(dt):
        delta = (dt - now).total_seconds() / 3600
        if delta < 1.5:
            return _s("shortly", runtime)
        if delta < 2.5:
            return _s("in_about_an_hour", runtime)
        if delta < 4:
            return _s("in_a_couple_hours", runtime)
        if dt.date() == now.date():
            if runtime.metric:
                return _s("around", runtime, time=f"{dt.hour:02d}h")
            h12 = dt.hour % 12 or 12
            suffix = "am" if dt.hour < 12 else "pm"
            return _s("around", runtime, time=f"{h12}{suffix}")
        if dt.date() == (now + timedelta(days=1)).date():
            if dt.hour < 12:
                return _s("tomorrow_morning", runtime)
            if dt.hour < 17:
                return _s("tomorrow_afternoon", runtime)
            return _s("tomorrow_evening", runtime)
        day_names = DAY_NAMES.get(lang, DAY_NAMES["en"])
        return _s("on_day", runtime, day=day_names[dt.weekday()])

    first_idx = window[0][0]

    if is_precip(first_idx):
        current_desc = desc(first_idx)
        for i, dt in window[1:]:
            if not is_precip(i):
                text = _s("ending", runtime, desc=current_desc.capitalize(), time=time_phrase(dt))
                return f" {MUTED}{text}{RESET}"
        text = _s("continuing", runtime, desc=current_desc.capitalize())
        return f" {MUTED}{text}{RESET}"

    for i, dt in window[1:]:
        if is_precip(i):
            text = _s("starting", runtime, desc=desc(i).capitalize(), time=time_phrase(dt))
            return f" {MUTED}{text}{RESET}"
    return ""


def _past_precip_line(hourly, now, runtime):
    """Natural language summary of precipitation in the last 24 hours."""
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])
    snowfall = hourly.get("snowfall", [])
    codes = hourly.get("weather_code", [])

    if not times or not precip:
        return ""

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    past_start = current_hour - timedelta(hours=24)

    total_precip = 0.0
    total_snow_cm = 0.0
    snow_hours = 0
    rain_hours = 0
    mix_hours = 0

    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if dt < past_start or dt > current_hour:
            continue
        p = precip[i] if i < len(precip) else 0
        s = snowfall[i] if i < len(snowfall) else 0
        c = codes[i] if i < len(codes) else 0
        if p > 0 or s > 0:
            total_precip += p
            total_snow_cm += s
            if c in (71, 73, 75, 77, 85, 86):
                snow_hours += 1
            elif c in (56, 57, 66, 67):
                mix_hours += 1
            else:
                rain_hours += 1

    if total_precip < (0.5 if runtime.metric else 0.01) and total_snow_cm < 0.1:
        return ""

    # Determine dominant type and format amount
    if snow_hours >= rain_hours and snow_hours >= mix_hours:
        # Show snow accumulation (Open-Meteo snowfall is in cm)
        if runtime.metric:
            amt = f"{total_snow_cm:.1f}cm"
        else:
            inches = total_snow_cm / 2.54
            amt = f"{inches:.1f}\u2033" if inches >= 1 else f"{inches:.2f}\u2033"
        ptype = _s("snow", runtime)
    elif mix_hours >= rain_hours:
        if runtime.metric:
            amt = f"{total_precip:.1f}mm"
        else:
            amt = f"{total_precip:.2f}\u2033"
        ptype = _s("mixed_precip", runtime)
    else:
        if runtime.metric:
            amt = f"{total_precip:.1f}mm"
        else:
            amt = f"{total_precip:.2f}\u2033"
        ptype = _s("rain", runtime)

    return f" {MUTED}{_s('past_precip', runtime, amt=amt, ptype=ptype)}{RESET}"
