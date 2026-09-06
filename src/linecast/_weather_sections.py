"""Header and narrative weather text sections."""

import math
from datetime import datetime, timedelta

from linecast import _theme
from linecast._graphics import RESET, visible_len
from linecast._runtime import WeatherRuntime, current_runtime, log_failure, log_skipped
from linecast._weather_i18n import (
    DAY_NAMES, WMO_NAMES, WMO_NAMES_I18N, _PRECIP_DESCS_I18N, _s, _wmo_icons,
)
from linecast._weather_style import (MUTED, TEXT, WIND_COLOR, _aqi_color,
                                     _colored_temp, _india_aqi_color)


def render_header(data, width, location_name="", runtime=None, aqi_data=None, historical=None):
    """Current conditions header line."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    current = data.get("current", {})
    temp = current.get("temperature_2m", 0)
    feels = current.get("apparent_temperature", 0)
    wmo = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    gusts = current.get("wind_gusts_10m", 0)
    humidity = current.get("relative_humidity_2m")
    dew_point = current.get("dew_point_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    name = WMO_NAMES_I18N.get(runtime.lang, {}).get(wmo) or WMO_NAMES.get(wmo, "")

    deg = runtime.temp_unit
    left_core = f" {TEXT}{icon} {name}  {_colored_temp(temp, runtime, deg)}"
    left_feels = f"  {MUTED}{_s('feels', runtime)} {_colored_temp(feels, runtime, deg)}"

    # Historical comparison — subtle annotation after feels-like
    left_hist = ""
    if historical is not None:
        try:
            from linecast._weather_historical import format_historical_comparison
            daily = data.get("daily", {})
            hi_temps = daily.get("temperature_2m_max", [])
            lo_temps = daily.get("temperature_2m_min", [])
            # Index 1 = today (with past_days=1)
            if len(hi_temps) > 1 and len(lo_temps) > 1:
                hist_text = format_historical_comparison(
                    hi_temps[1], lo_temps[1], historical, runtime,
                )
                if hist_text:
                    left_hist = f"  {MUTED}({hist_text})"
        except Exception as exc:
            log_failure("weather/climate", "historical comparison", exc,
                        fallback="annotation omitted")

    # Humidity/dew point — show when notable
    left_humidity = ""
    if humidity is not None and dew_point is not None:
        # Show dew point when it's uncomfortably high (>= 60°F / 15°C)
        dew_f = dew_point * 9 / 5 + 32 if runtime.celsius else dew_point
        if dew_f >= 60:
            left_humidity = (f"  {MUTED}{_s('dew_pt', runtime)} "
                             f"{_colored_temp(dew_point, runtime, deg)}")
        elif humidity >= 70 or humidity <= 25:
            left_humidity = f"  {MUTED}{_s('humidity', runtime)} {humidity:.0f}%"

    # AQI — show when data available. India reads its own CPCB scale,
    # attached upstream (apply_india_aqi); the number, its colors, and
    # the category word follow that scale there. The category ("Very
    # Poor") is how CPCB bulletins print the index, and it is what tells
    # a reader which of the two scales the number is on.
    aqi_value = None
    india_scale = False
    if aqi_data and isinstance(aqi_data, dict):
        aqi_current = aqi_data.get("current", {})
        india_value = aqi_current.get("india_aqi")
        if india_value is not None:
            aqi_value = india_value
            india_scale = True
        else:
            aqi_value = aqi_current.get("us_aqi")

    left_aqi = ""
    if aqi_value is not None:
        if india_scale:
            from linecast._weather_sources import india_aqi_category
            color = _india_aqi_color(aqi_value)
            category = india_aqi_category(aqi_value)
            left_aqi = (f"  {MUTED}{_s('aqi', runtime)} "
                        f"{color}{aqi_value:.0f} {category}")
        else:
            left_aqi = (f"  {MUTED}{_s('aqi', runtime)} "
                        f"{_aqi_color(aqi_value)}{aqi_value:.0f}")

    # Right side: wind info + location (progressively droppable)
    wind_part = ""
    if wind > (15 if runtime.metric else 10) or gusts > (30 if runtime.metric else 20):
        parts = [f"{_s('wind', runtime)} {wind:.0f}{runtime.wind_unit}"]
        if gusts > (30 if runtime.metric else 20):
            parts.append(f"{_s('gusts', runtime)} {gusts:.0f}{runtime.wind_unit}")
        wind_part = f"{WIND_COLOR}{'  '.join(parts)}"
    loc_part = f"{MUTED}{location_name}" if location_name else ""

    def _join_right(*parts):
        filled = [p for p in parts if p]
        return "  ".join(filled) if filled else ""

    def _assemble(left, right):
        if not right:
            return f"{left}{RESET}"
        pad = width - visible_len(left) - visible_len(right) - 1
        if pad >= 1:
            return f"{left}{' ' * pad}{right}{RESET}"
        return None  # doesn't fit

    left = left_core + left_feels + left_hist + left_humidity + left_aqi

    # Try full header
    right = _join_right(wind_part, loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop humidity
    left = left_core + left_feels + left_hist + left_aqi
    right = _join_right(wind_part, loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop AQI
    left = left_core + left_feels + left_hist
    right = _join_right(wind_part, loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop historical comparison
    left = left_core + left_feels
    right = _join_right(wind_part, loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop location
    right = _join_right(wind_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop feels-like
    left = left_core
    right = _join_right(wind_part, loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Drop feels-like + location
    right = _join_right(wind_part)
    result = _assemble(left, right)
    if result:
        return result

    # Minimal: just conditions + temp, location on right
    right = _join_right(loc_part)
    result = _assemble(left, right)
    if result:
        return result

    # Last resort: left only
    return f"{left}{RESET}"


# ---------------------------------------------------------------------------
# The prose lines under the graph
# ---------------------------------------------------------------------------
def _muted(sentence):
    """A sentence as a dashboard line, or nothing when there is no sentence."""
    return f" {MUTED}{sentence}{RESET}" if sentence else ""


def narrative_lines(data, now, width, runtime=None):
    """The prose under the graph, packed into as few lines as it fits on.

    A sentence per line leaves most of a wide terminal empty and takes
    rows the graph wants on a narrow one, so sentences share a line while
    there is room and only spill onto another when there is not."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})
    sentences = [s for s in (
        feels_sentence(data.get("current", {}), daily, now, runtime),
        comparative_sentence(daily, now, runtime),
        precipitation_sentence(hourly, now, runtime),
        past_precip_sentence(hourly, now, runtime),
    ) if s]
    if not sentences:
        return []

    # Read as prose, so the sentences are punctuated as prose: a full stop
    # between two sharing a line and at the end of every one.  Which mark
    # that is, and whether a space follows it, is the language's business.
    join = _s("sentence_join", runtime)
    end = _s("sentence_end", runtime)

    budget = max(1, width - 1)  # the line's leading space
    rows = [sentences[0]]
    for sentence in sentences[1:]:
        joined = rows[-1] + join + sentence
        if visible_len(joined + end) <= budget:
            rows[-1] = joined
        else:
            rows.append(sentence)
    return [_muted(row + end) for row in rows]


# ---------------------------------------------------------------------------
# Feels-like line
# Open-Meteo's apparent temperature is the Australian one, which is the air
# temperature plus a humidity term and minus a wind term:
#
#     AT = Ta + 0.33e - 0.70v - 4.00      e in hPa, v in m/s
#
# with sunshine added on top.  Checked against the API hour by hour, those
# two terms account for the reading to within a few tenths overnight, and
# what is left over rises and falls with the sun.  So the same arithmetic,
# run backwards, says how much of the gap each of the three is holding --
# no guessing from thresholds, and the answer is right by construction.
#
# A term has to be worth a degree Celsius before it is worth a sentence.
_FEELS_FLOOR_C = 1.0


def _feels_terms(temp_c, humidity, wind_ms, gap_c):
    """What humidity, wind and sunshine each contribute, in degrees Celsius."""
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    humid = 0.33 * vapour - 4.0     # zero at a dew point near 10 C
    wind = -0.70 * wind_ms
    return {"humid": humid, "wind": wind, "sun": gap_c - humid - wind}


def _is_daylight(daily, now):
    """Whether `now` falls between today's sunrise and sunset.  False when
    the day has no sunrise -- a polar winter, or a forecast that omits it."""
    from linecast._weather_hourly import _parse_sun_events
    for rise, sunset in _parse_sun_events(daily):
        if rise is not None and rise.date() == now.date():
            return sunset is not None and rise <= now <= sunset
    return False


def feels_sentence(current, daily, now, runtime=None):
    """Why the air feels warmer or cooler than the thermometer reads.

    Names whichever of humidity, wind and sunshine is holding most of the
    gap, and says nothing when the gap is small, when no one thing is
    holding a degree of it, or when the forecast is too old to carry the
    humidity the arithmetic needs.  The header already prints the number;
    this is only here to say what is behind it."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    if temp is None or feels is None or humidity is None or wind is None:
        return ""

    gap = feels - temp
    if abs(gap) < (2 if runtime.celsius else 3):
        return ""

    to_c = (lambda t: t) if runtime.celsius else (lambda t: (t - 32) * 5 / 9)
    terms = _feels_terms(
        to_c(temp), humidity,
        wind / 3.6 if runtime.metric else wind * 0.44704,
        gap if runtime.celsius else gap * 5 / 9,
    )

    # Of the terms pushing the way the reading went, the largest one.
    pushing = sorted(((abs(size), name) for name, size in terms.items()
                      if (size > 0) == (gap > 0)), reverse=True)
    if not pushing or pushing[0][0] < _FEELS_FLOOR_C:
        return ""

    holding = pushing[0][1]
    if holding == "wind":
        return _s("feels_wind", runtime)
    if holding == "humid":
        return _s("feels_humid" if gap > 0 else "feels_dry", runtime)
    # Sunshine is the leftover, so it carries whatever the formula and the
    # API disagree about.  Claim it only when it warms, and only with the
    # sun actually up.
    if gap > 0 and _is_daylight(daily, now):
        return _s("feels_sun", runtime)
    return ""


# ---------------------------------------------------------------------------
# Comparative weather line
# ---------------------------------------------------------------------------
def comparative_sentence(daily, now, runtime=None):
    """Plain-text natural language comparing today vs yesterday/tomorrow."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
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
    t_same, t_bit, t_much = (2, 4, 8) if runtime.celsius else (3, 8, 15)
    if abs_diff < t_same:
        key = "same_temp"
    elif abs_diff < t_bit:
        key = "bit_warmer" if diff > 0 else "bit_cooler"
    elif abs_diff < t_much:
        key = "warmer" if diff > 0 else "cooler"
    else:
        key = "much_warmer" if diff > 0 else "much_cooler"

    comparison = _s(key, runtime, ref_day=ref_day, subject=subject.lower())
    return _s("will_be", runtime, subject=subject, comparison=comparison)


def _comparative_line(daily, now, runtime=None):
    """ANSI-muted comparative sentence for the dashboard."""
    return _muted(comparative_sentence(daily, now, runtime))


# ---------------------------------------------------------------------------
# Precipitation forecast line
# ---------------------------------------------------------------------------
def _ucfirst(s):
    """Uppercase first character without lowering the rest (preserves German noun caps)."""
    return s[:1].upper() + s[1:] if s else s


_PRECIP_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86,
                 95, 96, 99}

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


def precipitation_sentence(hourly, now, runtime=None):
    """Plain-text description of upcoming precipitation."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    lang = runtime.lang
    times = hourly.get("time", [])
    precip_prob = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])

    if not times or not precip_prob or not codes:
        return ""

    current_hour = now.replace(minute=0, second=0, microsecond=0)

    # Build window: (data_index, datetime) for next 24h
    window = []
    dropped = 0
    bad = None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
            if dt >= current_hour:
                window.append((i, dt))
        except (TypeError, ValueError) as exc:
            dropped += 1
            bad = exc
            continue
    log_skipped("weather/open-meteo", "hourly times", dropped, len(times), bad)
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
            from linecast._framebuffer import fmt_hour_phrase
            return _s("around", runtime,
                      time=fmt_hour_phrase(dt.hour, runtime.use_24h, lang))
        if dt.date() == (now + timedelta(days=1)).date():
            if dt.hour < 5:
                return _s("overnight", runtime)
            if dt.hour < 8:
                return _s("early_tomorrow_morning", runtime)
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
                return _s("ending", runtime, desc=_ucfirst(current_desc),
                          time=time_phrase(dt))
        return _s("continuing", runtime, desc=_ucfirst(current_desc))

    for i, dt in window[1:]:
        if is_precip(i):
            return _s("starting", runtime, desc=_ucfirst(desc(i)), time=time_phrase(dt))
    return ""


def _precipitation_line(hourly, now, runtime=None):
    """ANSI-muted precipitation sentence for the dashboard."""
    return _muted(precipitation_sentence(hourly, now, runtime))


def past_precip_sentence(hourly, now, runtime):
    """Plain-text summary of precipitation in the last 24 hours."""
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

    dropped = 0
    bad = None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError) as exc:
            dropped += 1
            bad = exc
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
    log_skipped("weather/open-meteo", "hourly times", dropped, len(times), bad)

    # 0.25 mm is 0.01", the line between a trace and a measurable
    # amount, so the same rain qualifies in either unit
    if total_precip < (0.25 if runtime.metric else 0.01) and total_snow_cm < 0.1:
        return ""

    # Determine dominant type and format amount
    metric_sep = _s("metric_unit_sep", runtime)
    if snow_hours >= rain_hours and snow_hours >= mix_hours:
        # Show snow accumulation (Open-Meteo snowfall is in cm)
        if runtime.metric:
            amt = f"{total_snow_cm:.1f}{metric_sep}cm"
        else:
            inches = total_snow_cm / 2.54
            unit = _s("precip_inch", runtime)
            amt = f"{inches:.1f}{unit}" if inches >= 1 else f"{inches:.2f}{unit}"
        ptype = _s("snow", runtime)
    elif mix_hours >= rain_hours:
        if runtime.metric:
            amt = f"{total_precip:.1f}{metric_sep}mm"
        else:
            amt = f"{total_precip:.2f}{_s('precip_inch', runtime)}"
        ptype = _s("mixed_precip", runtime)
    else:
        if runtime.metric:
            amt = f"{total_precip:.1f}{metric_sep}mm"
        else:
            amt = f"{total_precip:.2f}{_s('precip_inch', runtime)}"
        ptype = _s("rain", runtime)

    return _s("past_precip", runtime, amt=amt, ptype=ptype)


def _past_precip_line(hourly, now, runtime):
    """ANSI-muted past-precipitation sentence for the dashboard."""
    return _muted(past_precip_sentence(hourly, now, runtime))

_theme.track_imports(globals(), "linecast._weather_style")
