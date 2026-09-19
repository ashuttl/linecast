"""Header and narrative weather text sections."""

import math
from datetime import datetime, timedelta

from linecast import _theme
from linecast._i18n import fmt_percent, sentence_24h
from linecast._graphics import RESET, visible_len
from linecast._runtime import WeatherRuntime, current_runtime, log_failure, log_skipped
from linecast._textwidth import wrap_display_width
from linecast._weather_i18n import (
    fmt_wind, _precip_s,
    DAY_NAMES, ON_DAY_FORMS, WMO_NAMES, WMO_NAMES_I18N, _PRECIP_DESCS_I18N, _s, _wmo_icons,
)
from linecast._weather_style import (MUTED, TEXT, WIND_COLOR, _aqi_color,
                                     _colored_temp, _india_aqi_color)
from linecast._weather_sources import _local_now_for_data


def location_control(name, width, runtime):
    from linecast._help import fit
    from linecast._weather_locations_i18n import ls
    return fit(name or ls('locations', runtime.lang), max(0, min(width - 2, width // 2))) + ' ▼'


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
    wmo = current.get("weather_code") or 0
    wind = current.get("wind_speed_10m") or 0
    gusts = current.get("wind_gusts_10m") or 0
    humidity = current.get("relative_humidity_2m")
    dew_point = current.get("dew_point_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    name = WMO_NAMES_I18N.get(runtime.lang, {}).get(wmo) or WMO_NAMES.get(wmo, "")

    deg = runtime.temp_unit
    left_core = f"{TEXT}{icon} {name}"
    if temp is not None:
        left_core += f"  {_colored_temp(temp, runtime, deg)}"
    left_feels = ""
    if feels is not None:
        left_feels = f"  {MUTED}{_s('feels', runtime)} {_colored_temp(feels, runtime, deg)}"

    # Historical comparison — subtle annotation after feels-like
    left_hist = ""
    if historical is not None:
        try:
            from linecast._weather_historical import format_historical_comparison
            daily = data.get("daily") or {}
            hi_temps = daily.get("temperature_2m_max") or []
            lo_temps = daily.get("temperature_2m_min") or []
            # A cached forecast's second entry may no longer be today.
            today = (now if now is not None else _local_now_for_data(data)).date().isoformat()
            index = next((i for i, day in enumerate(daily.get("time") or [])
                          if day == today), -1)
            if (0 <= index < min(len(hi_temps), len(lo_temps))
                    and hi_temps[index] is not None and lo_temps[index] is not None):
                hist_text = format_historical_comparison(
                    hi_temps[index], lo_temps[index], historical, runtime,
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
            left_humidity = f"  {MUTED}{_s('humidity', runtime)} {fmt_percent(humidity, runtime)}"

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
        parts = [f"{_s('wind', runtime)} {fmt_wind(wind, runtime)}"]
        if gusts > (30 if runtime.metric else 20):
            parts.append(f"{_s('gusts', runtime)} {fmt_wind(gusts, runtime)}")
        wind_part = f"{WIND_COLOR}{'  '.join(parts)}"
    loc_part = f"{MUTED}{location_name}" if location_name else ""
    if location_menu:
        loc_part = f"{MUTED}{location_control(location_name, width, runtime)}"

    def _join_right(*parts):
        filled = [p for p in parts if p]
        return "  ".join(filled) if filled else ""

    def _assemble(left, right):
        if not right:
            return f"{left}{RESET}"
        pad = width - visible_len(left) - visible_len(right)
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

    if location_menu:
        # The live location is a control: keep it even when conditions are long.
        for compact in (left_core + left_feels, left_core):
            result = _assemble(compact, loc_part)
            if result:
                return result
        from linecast._help import fit
        label = location_control(location_name, width, runtime)
        room = max(0, width - visible_len(label) - 1)
        core = f"{icon} {name}" + (f"  {temp:.0f}{deg}" if temp is not None else "")
        plain = fit(core, room)
        return f"{TEXT}{plain}{' ' * max(0, width - visible_len(plain) - visible_len(label))}" \
               f"{MUTED}{label}{RESET}"

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
def _prose(sentence):
    """A sentence as a dashboard line, in the full text color like the day
    names and the conditions at the top, or nothing when there is no
    sentence."""
    return f"{TEXT}{sentence}{RESET}" if sentence else ""


def narrative_lines(data, now, width, runtime=None):
    """The prose under the graph, wrapped as one continuous paragraph."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})
    feels = feels_sentence(data.get("current", {}), daily, now, runtime)
    comparison = comparative_sentence(daily, now, runtime)
    # Through the morning the comparison is about today, so it opens the
    # paragraph and the feels-like sentence explains it.  From mid-afternoon
    # it looks ahead to tomorrow, and a look ahead follows the present tense.
    if now.hour < _COMPARISON_TURNS_TO_TOMORROW:
        opening = (comparison, feels)
    else:
        opening = (feels, comparison)
    sentences = [s for s in (
        *opening,
        precipitation_sentence(hourly, now, runtime),
        past_precip_sentence(hourly, now, runtime),
    ) if s]
    if not sentences:
        return []

    # Read as prose, so the sentences are punctuated as prose: a full stop
    # between sentences and at the end of the paragraph.  Which mark
    # that is, and whether a space follows it, is the language's business.
    join = _s("sentence_join", runtime)
    end = _s("sentence_end", runtime)

    budget = max(1, width)
    rows = wrap_display_width(join.join(sentences) + end, budget)
    # Give a lone final word some company when it fits, without adding a
    # row or leaving another lone word behind.  Languages without spaces
    # keep the display-width wrapper's natural breaks.
    if len(rows) > 1 and len(rows[-1].split()) == 1:
        before, space, word = rows[-2].rpartition(" ")
        last = word + " " + rows[-1]
        if space and len(before.split()) > 1 and visible_len(last) <= budget:
            rows[-2:] = [before, last]
    return [_prose(line) for line in rows]


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

    # A gap has to be one a person would notice before it is worth a
    # sentence: six degrees Fahrenheit, or three Celsius.
    gap = feels - temp
    if abs(gap) < (3 if runtime.celsius else 6):
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
# The hour the comparison stops looking back at yesterday and starts looking
# ahead to tomorrow.  Most of today's high is in by then.
_COMPARISON_TURNS_TO_TOMORROW = 14


def comparative_sentence(daily, now, runtime=None):
    """Plain-text natural language comparing today vs yesterday/tomorrow."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    hi_temps = daily.get("temperature_2m_max", [])

    # Resolve the dates in cached forecasts too: index 1 only means
    # today on the day of the fetch. Undated series use past_days=1.
    if daily.get("time") is not None:
        by_date = dict(zip(daily["time"], hi_temps))
        hi_temps = [by_date.get((now.date() + timedelta(days=offset)).isoformat())
                    for offset in (-1, 0, 1)]
    if len(hi_temps) < 3:
        return ""

    if now.hour < _COMPARISON_TURNS_TO_TOMORROW:
        a, b = hi_temps[0], hi_temps[1]
        ref_day = _s("yesterday", runtime)
        subject = _s("today_subj", runtime)
    else:
        a, b = hi_temps[1], hi_temps[2]
        ref_day = _s("today_ref", runtime)
        subject = _s("tomorrow_subj", runtime)
    # Either day's high can be null; there is then nothing to compare.
    if a is None or b is None:
        return ""
    diff = b - a

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
    """ANSI-colored comparative sentence for the dashboard."""
    return _prose(comparative_sentence(daily, now, runtime))


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

# How hard each precipitation code falls, one step at a time, so a run
# of rain can say when it turns heavy without calling a let-up a turn.
_PRECIP_RANK = {
    51: 1, 53: 2, 55: 3, 56: 2, 57: 3,
    61: 2, 63: 3, 65: 4, 66: 3, 67: 4,
    71: 2, 73: 3, 75: 4, 77: 1,
    80: 2, 81: 3, 82: 4, 85: 3, 86: 4,
    95: 4, 96: 5, 99: 5,
}


def _peak_hour(run, amounts, codes):
    """The hour in a run of precipitation worth naming on its own, or None.

    The peak is the hour with the most forecast, the tallest column of
    the bar under the chart; with no amounts it is the hour of the
    heaviest code.  It is named only when its code is a step up from
    the current hour's, so "rain becoming light rain" is never said,
    and a run that keeps its name says nothing more.
    """
    def amount(idx):
        return (amounts[idx] if idx < len(amounts) else 0) or 0

    def rank(idx):
        return _PRECIP_RANK.get(codes[idx] if idx < len(codes) else 0, 0)

    first = run[0][0]
    later = run[1:]
    if not later:
        return None
    if any(amount(i) for i, _ in run):
        i, dt = max(later, key=lambda h: amount(h[0]))
        if amount(i) <= amount(first):
            return None
    else:
        i, dt = max(later, key=lambda h: rank(h[0]))
    if rank(i) <= rank(first):
        return None
    return i, dt


def precipitation_sentence(hourly, now, runtime=None):
    """Plain-text description of upcoming precipitation."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    lang = runtime.lang
    times = hourly.get("time", [])
    precip_prob = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])
    amounts = hourly.get("precipitation") or []

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
        # A null probability or code is an hour that says nothing
        p = (precip_prob[idx] if idx < len(precip_prob) else 0) or 0
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
                      time=fmt_hour_phrase(dt.hour, sentence_24h(runtime), lang))
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
        form = ON_DAY_FORMS.get(lang, {}).get(dt.weekday())
        if form:
            return form.format(day=day_names[dt.weekday()])
        return _s("on_day", runtime, day=day_names[dt.weekday()])

    def run_from(n):
        """The wet hours from window[n] on, and the first dry hour after them."""
        run = [window[n]]
        for i, dt in window[n + 1:]:
            if not is_precip(i):
                return run, dt
            run.append((i, dt))
        return run, None

    def sentence(key, run, **words):
        """The template for `key`, or its "becoming" form when the run
        has an hour heavier than its first worth naming."""
        peak = _peak_hour(run, amounts, codes)
        if peak:
            key += "_becoming"
            words.update(peak=desc(peak[0]), peak_time=time_phrase(peak[1]))
        return _precip_s(key, codes[run[0][0]], runtime, **words)

    first_idx = window[0][0]

    if is_precip(first_idx):
        run, end = run_from(0)
        if end:
            return sentence("ending", run, desc=_ucfirst(desc(first_idx)),
                            time=time_phrase(end))
        return sentence("continuing", run, desc=_ucfirst(desc(first_idx)))

    for n, (i, dt) in enumerate(window[1:], 1):
        if is_precip(i):
            run, _ = run_from(n)
            return sentence("starting", run, desc=_ucfirst(desc(i)), time=time_phrase(dt))
    return ""


def _precipitation_line(hourly, now, runtime=None):
    """ANSI-colored precipitation sentence for the dashboard."""
    return _prose(precipitation_sentence(hourly, now, runtime))


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
        # A null hour holds no measurable precipitation
        p = (precip[i] if i < len(precip) else 0) or 0
        s = (snowfall[i] if i < len(snowfall) else 0) or 0
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
            amt = f"{total_snow_cm:.1f}{metric_sep}{_s('unit_cm', runtime)}"
        else:
            inches = total_snow_cm / 2.54
            unit = _s("precip_inch", runtime)
            amt = f"{inches:.1f}{unit}" if inches >= 1 else f"{inches:.2f}{unit}"
        ptype = _s("snow", runtime)
    elif mix_hours >= rain_hours:
        if runtime.metric:
            amt = f"{total_precip:.1f}{metric_sep}{_s('unit_mm', runtime)}"
        else:
            amt = f"{total_precip:.2f}{_s('precip_inch', runtime)}"
        ptype = _s("mixed_precip", runtime)
    else:
        if runtime.metric:
            amt = f"{total_precip:.1f}{metric_sep}{_s('unit_mm', runtime)}"
        else:
            amt = f"{total_precip:.2f}{_s('precip_inch', runtime)}"
        ptype = _s("rain", runtime)

    return _s("past_precip", runtime, amt=amt, ptype=ptype)


def _past_precip_line(hourly, now, runtime):
    """ANSI-colored past-precipitation sentence for the dashboard."""
    return _prose(past_precip_sentence(hourly, now, runtime))

_theme.track_imports(globals(), "linecast._weather_style")
