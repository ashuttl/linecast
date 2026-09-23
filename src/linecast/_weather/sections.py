"""Header and narrative weather text sections."""

import contextvars
import functools
import math
from datetime import datetime, timedelta

from linecast import _theme
from linecast._i18n import (
    base_language, fallbacks, fmt_decimal, fmt_percent, has_text, lang_of, sentence_24h,
    table_for,
)
from linecast._graphics import RESET, visible_len
from linecast._runtime import WeatherRuntime, current_runtime, log_failure, log_skipped
from linecast._textwidth import wrap_display_width
from linecast._weather.cover import sky_condition
from linecast._weather.i18n import (
    fmt_wind, _precip_s,
    DAY_NAMES, FULL_DAY_NAMES, ON_DAY_FORMS, ON_FULL_DAY_FORMS, wmo_label,
    _PRECIP_DESCS_I18N, _PRECIP_PARTITIVES_I18N, _STRINGS, _s, _wmo_icons,
)
from linecast._weather import style as _weather_style
from linecast._weather.style import (MUTED, TEXT, WIND_COLOR, _aqhi_color, _aqi_color,
                                     _colored_temp, _india_aqi_color)
from linecast._weather.sources import _local_now_for_data


def location_control(name, width, runtime):
    from linecast._help import fit
    from linecast._weather.locations_i18n import ls
    return fit(name or ls('locations', runtime.lang), max(0, min(width - 6, width // 2))) + ' ▼'


def location_chip(label):
    """The place as a chip, like the tides station pill: half blocks
    round the ends of a lifted surface, the name in the full text color."""
    edge, surface, ink = _weather_style.CHIP
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
    left_feels = ""
    if feels is not None:
        left_feels = f" {MUTED}{_s('feels', runtime)} {_colored_temp(feels, runtime, deg)}"

    # Historical comparison — subtle annotation after feels-like
    left_hist = ""
    if historical is not None:
        try:
            from linecast._weather.historical import format_historical_comparison
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
                    left_hist = f" {MUTED}({hist_text})"
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
        from linecast._weather.sources import aqhi_category, fmt_aqhi
        left_aqi_bare = f"  {MUTED}{_s('aqhi', runtime)} {_aqhi_color(aqhi)}{fmt_aqhi(aqhi)}"
        left_aqi = f"{left_aqi_bare} {aqhi_category(aqhi, lang_of(runtime))}"
    elif aqi_value is not None:
        if india_scale:
            from linecast._weather.sources import india_aqi_category
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
        from linecast._help import fit
        loc_part = location_chip(fit(location_name, max(0, min(width - 4, width // 2))))

    def _join_right(*parts):
        filled = [p for p in parts if p]
        return "  ".join(filled) if filled else ""

    def _assemble(left, right):
        if not right:
            return f"{left}{RESET}"
        pad = width - visible_len(left) - visible_len(right)
        if pad >= 2:  # the two halves keep the gap the parts within them do
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

    # Drop the air quality category word, keeping the number
    if left_aqi_bare != left_aqi:
        left = left_core + left_feels + left_hist + left_aqi_bare
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
        room = max(0, width - visible_len(loc_part) - 1)
        core = f"{icon} {name}" + (f" {temp:.0f}{deg}" if temp is not None else "")
        plain = fit(core, room)
        return f"{TEXT}{plain}{' ' * max(0, width - visible_len(plain) - visible_len(loc_part))}" \
               f"{loc_part}{RESET}"

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


def _has(key, runtime):
    """Whether the display language carries `key` in its own words.

    A sentence the language has not been given yet is left unsaid rather
    than said in English: the paragraph is prose, and a line of another
    language in it would read as a mistake.  The English table is the
    reference, so English has everything."""
    return has_text(_STRINGS, key, lang_of(runtime))


def _degrees(n, runtime, signed=False):
    """A number of degrees as the prose writes it: "8°", "8度", "8 grader",
    "3 stupně".  A difference is unsigned; a temperature keeps its sign.

    Languages whose word for degree changes with the number carry the
    forms as variants of "degrees": "_one" for one, "_few" for the
    Slavic two to four, "_many" for Romanian's twenty and up, and
    "_diff" (with its own "_one") for a difference, which Icelandic puts
    in the dative."""
    value = round(n) if signed else round(abs(n))
    digits = f"{value}".replace("-", "−")
    if not _has("degrees", runtime):
        return digits + "°"
    base = "degrees_diff" if not signed and _has("degrees_diff", runtime) else "degrees"
    key = base + _number_form(abs(value), runtime, base)
    return _s(key, runtime, n=digits)


def _number_form(count, runtime, base):
    """The variant suffix a count takes in the display language, among
    the variants the language has for `base`."""
    lang = runtime.lang
    if lang == "is":
        # Icelandic: one for every number ending in 1 but 11
        if count % 10 == 1 and count % 100 != 11 and _has(base + "_one", runtime):
            return "_one"
        return ""
    if lang in ("ru", "uk", "pl"):
        # Slavic: one for 1, 21, 31 (not 11; and in Polish only 1); few
        # for 2 to 4, 22 to 24 (not 12 to 14), where the base has a few
        one = count % 10 == 1 and count % 100 != 11 and (lang != "pl" or count == 1)
        if one and _has(base + "_one", runtime):
            return "_one"
        if (count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14)
                and _has(base + "_few", runtime)):
            return "_few"
        return ""
    if count == 1 and _has(base + "_one", runtime):
        return "_one"
    if 2 <= count <= 4 and _has(base + "_few", runtime):
        return "_few"
    if count >= 20 and _has(base + "_many", runtime):
        return "_many"
    return ""


def _prose_sep(runtime):
    """The space between a number and its unit in a sentence: the
    language's "metric_unit_sep_prose" where running text spaces a unit
    that the compact figures elsewhere do not ("12 mm of rain", but
    "12mm" under the chart), and its "metric_unit_sep" otherwise."""
    if _has("metric_unit_sep_prose", runtime):
        return _s("metric_unit_sep_prose", runtime)
    return _s("metric_unit_sep", runtime)


def _prose_inches(n, runtime):
    """A number of inches as a sentence writes it: "3 inches" where the
    language spells the unit out, "3″" where it keeps the mark."""
    if _has("precip_inch_prose", runtime):
        return _s("precip_inch_prose", runtime, n=n)
    return f"{n}{_s('precip_inch', runtime)}"


# How many sentences the paragraph will carry, and which.  Each candidate
# sentence comes with a salience, for choosing, and a time, for reading.
#
# Salience is what a person would be sure to mention: thunder, a freeze,
# a gale, snow on the ground by morning, then rain and when, then the sky
# and the felt temperature, then how today compares, then what fell
# yesterday.  The comparison is what most people open the app for --
# will it be like today out there, or not -- so it is never dropped
# lightly, "about the same" included.
#
# The sentences then read in the order of the things they describe: now,
# later today, tonight, tomorrow, the week.  What fell in the last day
# is a footnote at the end.  The feels-like sentence is about this hour,
# so it goes ahead of the comparison about today: after "Today's high",
# "the humidity is making it feel warmer" reads as though it were about
# the high.  The comparison about tomorrow takes tomorrow's place.
_MAX_SENTENCES = 4


def narrative_lines(data, now, width, runtime=None, trace=None):
    """The prose under the graph, wrapped as one continuous paragraph.

    `trace`, a list, collects every candidate sentence as a dict of its
    salience, hours from now, text, and whether it was chosen: how
    `linecast prose` shows why a paragraph says what it says."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})
    current = data.get("current", {})

    # Each candidate is a sentence builder rather than a sentence, so a
    # sentence can be told what the one before it established: a
    # paragraph says "tomorrow" once and then carries it.
    candidates = []    # (salience, hours from now, anchor, build, rank, leaves)

    def hours(dt):
        return (dt - now).total_seconds() / 3600

    def add(salience, at, anchor, build, leaves=None):
        # `leaves` is the last time the sentence names, the frame the
        # next sentence can inherit; by default the anchor itself
        text = build(None)
        if text:
            candidates.append((salience, at, anchor, build, len(candidates),
                               leaves or anchor))
            if trace is not None:
                trace.append({"salience": salience, "at": at, "text": _ucfirst(text),
                              "chosen": False})

    precip = _precip_parts(hourly, now, runtime, daily, current=current)
    kind = precip["kind"]
    anchor = precip["run"][0][1] if kind == "starting" else now
    at = hours(anchor) if kind == "starting" else -1.0
    gusts, gale, gust_at, gust_speed = _gusts(hourly, now, runtime, daily=daily)
    if (gusts and precip["sentence"] and kind != "ending" and _has("with_gusts", runtime)
            and _period_phrase(gust_at, now, runtime) == _period_phrase(anchor, now, runtime)):
        # Wind in the same part of the day rides on the rain's sentence
        add(max(precip["salience"], 5 if gale else 3), at, anchor,
            lambda after: _s(
                "with_gusts", runtime, speed=gust_speed,
                sentence=_precip_parts(hourly, now, runtime, daily, after,
                                       current)["sentence"]),
            leaves=precip["last_named"])
    else:
        add(precip["salience"], at, anchor,
            lambda after: _precip_parts(hourly, now, runtime, daily, after,
                                        current)["sentence"],
            leaves=precip["last_named"])
        if gusts:
            add(5 if gale else 3, hours(gust_at), gust_at,
                lambda after: _gusts(hourly, now, runtime, after, daily)[0])
    if precip["next"]:
        add(3, hours(precip["next"][1]), precip["next"][1],
            lambda after: more_later_sentence(precip, now, runtime, after))
    snow, heavy = _snow_sentence(precip, hourly, now, runtime)
    add(5 if heavy else 4, at + 0.01, anchor, lambda after: snow)

    comparison, big = _comparison(daily, now, runtime)
    feels, feels_cause = _feels(current, daily, now, runtime)
    ahead, ahead_at, ahead_cause = _feels_ahead(hourly, now, runtime, current=current)
    if ahead and ahead_cause == feels_cause:
        # One sentence about the felt temperature: the one that looks ahead
        feels = ""
    add(3, 0.0, now, lambda after: feels)
    if now.hour < _COMPARISON_TURNS_TO_TOMORROW:
        add(big, 0.01, now, lambda after: comparison)
    else:
        noon_tomorrow = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0,
                                                          microsecond=0)
        add(big, hours(noon_tomorrow), noon_tomorrow,
            lambda after: _comparison(daily, now, runtime, after is not None)[0])

    fog, fog_at, fog_end = _fog(hourly, current, now, runtime, daily=daily)
    if fog:
        add(4, hours(fog_at), fog_at,
            lambda after: _fog(hourly, current, now, runtime, after, daily)[0],
            leaves=fog_end)
    sky, sky_at = _sky(hourly, daily, now, runtime, kind, precip["end"])
    # Fog is the sky.  Once the fog sentence has spoken, a sentence about
    # the cloud would say the same change over again -- the fog closing
    # in, or lifting -- in words that read as though it were something else.
    if sky and not fog:
        add(3, hours(sky_at), sky_at,
            lambda after: _sky(hourly, daily, now, runtime, kind, precip["end"], after)[0])
    freeze, freeze_at = _freeze(hourly, current, now, runtime)
    if freeze:
        add(4, hours(freeze_at), freeze_at,
            lambda after: _freeze(hourly, current, now, runtime, after)[0])
    if ahead:
        add(4, hours(ahead_at), ahead_at,
            lambda after: _feels_ahead(hourly, now, runtime, after, current)[0])
    if not kind:
        week, week_at = _next_rain(daily, now, runtime, hourly)
        if week:
            add(2, hours(week_at), week_at,
                lambda after: _next_rain(daily, now, runtime, hourly, after)[0])
    add(2, float("inf"), None, lambda after: past_precip_sentence(hourly, now, runtime))

    if not candidates:
        return []

    chosen = sorted(candidates, key=lambda c: (-c[0], c[1], c[4]))[:_MAX_SENTENCES]
    chosen.sort(key=lambda c: (c[1], c[4]))
    if trace is not None:
        for _, _, _, _, rank, _ in chosen:
            trace[rank]["chosen"] = True

    # A sentence about the same later day as the one before it inherits
    # that day: "Gusts to 40 km/h tomorrow morning.  It will be 3° cooler
    # than today."  Today needs no such care; its phrases do not name it.
    sentences = []
    previous = None
    said = set()
    for _, _, anchor, build, _, leaves in chosen:
        after = None
        if (previous is not None and anchor is not None
                and anchor.date() == previous.date() and _names_the_day(previous, now)):
            after = previous
        said = _said_in(functools.partial(build, after), said, sentences)
        previous = leaves if leaves is not None else previous

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


def _said_in(build, before, sentences):
    """Build a sentence onto `sentences`, knowing which parts of today the
    one before it named; return the parts this one names."""
    now_said = set()
    token = _SAID.set((before, now_said))
    try:
        sentences.append(_ucfirst(build()))
    finally:
        _SAID.reset(token)
    return now_said


# ---------------------------------------------------------------------------
# Naming an hour
# ---------------------------------------------------------------------------
def _hours_ahead(hourly, now, span=24):
    """(index, datetime) for each hour from this one to `span` hours on."""
    times = hourly.get("time", [])
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    window = []
    dropped = 0
    bad = None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError) as exc:
            dropped += 1
            bad = exc
            continue
        if current_hour <= dt <= current_hour + timedelta(hours=span):
            window.append((i, dt))
    log_skipped("weather/open-meteo", "hourly times", dropped, len(times), bad)
    return window


def _names_the_day(dt, now):
    """Whether the phrase for `dt` says which day it is: "tomorrow
    afternoon" does, "in about an hour", "overnight" and "tonight" do
    not, even when the hour they name falls after midnight."""
    if (dt - now).total_seconds() < 4 * 3600 or dt.date() == now.date():
        return False
    if dt.date() == (now + timedelta(days=1)).date():
        return dt.hour >= 5
    return True


# Where one part of tomorrow ends and the next begins: the small hours
# before the morning proper, then morning, afternoon, evening.  The
# small hours and the morning are one morning for saying "later in" it.
_DAY_PARTS = (8, 12, 17)
_LATER_IN = ("morning", "morning", "afternoon", "evening")


def _day_part(hour):
    """Which part of the day an hour falls in, as an index into the
    parts the phrases for tomorrow name."""
    return sum(hour >= edge for edge in _DAY_PARTS)


def _time_phrase(dt, now, runtime, after=None, same_sentence=False):
    """When something happens, as a person would say it: "shortly", "around
    3pm", "tomorrow afternoon".  With `after`, the hour named just before
    -- in this sentence when `same_sentence`, otherwise in the one before
    it -- a second "tomorrow" is left out: "starting tomorrow afternoon,
    becoming rain in the evening"."""
    lang = runtime.lang
    delta = (dt - now).total_seconds() / 3600
    if delta < 1.5:
        return _s("shortly", runtime)
    if delta < 2.5:
        return _s("in_about_an_hour", runtime)
    if delta < 4:
        return _s("in_a_couple_hours", runtime)
    if dt.date() == now.date():
        if dt.hour == 12 and _has("around_noon", runtime):
            return _s("around_noon", runtime)
        from linecast._framebuffer import fmt_hour_phrase
        return _s("around", runtime,
                  time=fmt_hour_phrase(dt.hour, sentence_24h(runtime), lang))
    tomorrow = (now + timedelta(days=1)).date()
    if dt.date() == tomorrow:
        if dt.hour < 5:
            # Read before dawn, the hours after midnight tomorrow belong
            # to the night this evening leads into, the one the rest of
            # the paragraph is already calling tonight.  A forecast
            # issued at four says "tonight"; "tomorrow night" would be
            # the night after, a day late.
            if now.hour < 5 and _has("tonight", runtime):
                return _part_of_day("tonight", runtime)
            return _part_of_day("overnight", runtime)
        said_tomorrow = (after is not None and after.date() == tomorrow
                         and _names_the_day(after, now))
        if dt.hour < 8:
            key = "early_tomorrow_morning"
        elif dt.hour < 12:
            key = "tomorrow_morning"
        elif dt.hour < 17:
            key = "tomorrow_afternoon"
        else:
            key = "tomorrow_evening"
        again = "then_" + key.replace("tomorrow_", "")
        if said_tomorrow:
            # A second hour in the part of the day this sentence has
            # already named is later in it, not that part over again: "a
            # chance of drizzle tomorrow morning, becoming showers later
            # in the morning".  What one sentence hands the next is the
            # day and not an hour to be later than -- the comparison
            # names no hour at all -- so between sentences only the turn
            # out of the small hours reads that way.  A language without
            # the words for the turn names the part again rather than
            # the day twice.
            here, there = _day_part(dt.hour), _day_part(after.hour)
            later = "then_later_" + _LATER_IN[here]
            if (_LATER_IN[there] == _LATER_IN[here] and (there < here or same_sentence)
                    and _has(later, runtime)):
                again = later
            if _has(again, runtime):
                key = again
        return _s(key, runtime)
    day_names = table_for(DAY_NAMES, lang)
    forms = ON_DAY_FORMS.get(lang, ON_DAY_FORMS.get(base_language(lang), {}))
    form = forms.get(dt.weekday())
    if form:
        return form.format(day=day_names[dt.weekday()])
    return _s("on_day", runtime, day=day_names[dt.weekday()])


def _names_an_hour(dt, now):
    """Whether _time_phrase names `dt` as a moment -- "soon", "in a
    couple hours", "around 3pm" -- rather than a part of a day."""
    return (dt - now).total_seconds() < 4 * 3600 or dt.date() == now.date()


# The parts of today the paragraph has named, while it is being written:
# (those the sentence before named, those this one has).  A sentence about
# the same part of today as the one before it says so in the language's
# own word, "then", rather than naming it again: "Below freezing tonight,
# down to −2°.  Light snow likely then."  Tomorrow is carried the same way
# by `after`; today's parts need this instead, because "tonight" names no
# day for `after` to compare.
_SAID = contextvars.ContextVar("parts_of_today_said", default=None)


def _part_of_day(key, runtime, form=None):
    """The phrase for a part of today, `key`, in `form` (a declined form
    of it) where given: or the language's "same_time" word when the
    sentence before named the same part.  The word is said once in a
    sentence.  A second phrase for the same part in one sentence is the
    language's "same_part_later", "light snow likely then, turning heavy
    later", where it has one, and names the part again where it does
    not."""
    said = _SAID.get()
    if said is not None:
        before, now_said = said
        if key in now_said and _has("same_part_later", runtime):
            # Named already in this sentence: later in the same part
            return _s("same_part_later", runtime)
        now_said.add(key)
        if (key in before and _SAME_SAID not in now_said
                and _has("same_time", runtime)):
            now_said.add(_SAME_SAID)
            return _s("same_time", runtime)
    return _s(form or key, runtime)


# Marks a sentence that has already said its "same_time" word
_SAME_SAID = object()


def _period_phrase(dt, now, runtime, by=False, after=None):
    """The part of the day an hour falls in: "this afternoon", "tonight",
    "tomorrow morning".  For things that are not on the hour -- a gusty
    afternoon, a freezing night.  With `by`, a deadline rather than a
    time, so the small hours become "tomorrow morning": the snow that
    stops at three is on the ground by then.  Falls back to the hour
    where the language has no words for the parts of today."""
    if not _has("this_afternoon", runtime):
        return _time_phrase(dt, now, runtime, after=after)

    def phrase(key):
        # "By" a time takes its own form where the language declines it
        if by and _has(key + "_by", runtime):
            return _part_of_day(key, runtime, key + "_by")
        return _part_of_day(key, runtime)

    if dt.date() == now.date():
        if dt.hour < 12:
            return phrase("this_morning")
        if dt.hour < 17:
            return phrase("this_afternoon")
        if dt.hour < 21:
            return phrase("this_evening")
        return phrase("tonight")
    if by and dt.date() == (now + timedelta(days=1)).date():
        if dt.hour < 12:
            return phrase("tomorrow_morning")
        if dt.hour < 17:
            return phrase("tomorrow_afternoon")
        return phrase("tomorrow_evening")
    return _time_phrase(dt, now, runtime, after=after)


def _is_night(daily, now):
    """Whether `now` is after dark: past sunset with the evening under
    way, or before four in the morning.  Without sun events, the hours
    from eight to four."""
    from linecast._weather.hourly import _parse_sun_events
    for rise, sunset in _parse_sun_events(daily):
        if rise is not None and rise.date() == now.date():
            if sunset is None:
                break
            return (now > sunset and now.hour >= 12) or (now < rise and now.hour < 4)
    return now.hour >= 20 or now.hour < 4


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
# The humidity term is zero at a dew point near 10 C, so cold air always
# reads as dry to the formula whatever its relative humidity: Longyearbyen
# at 91% is not "dry air".  The term is only named as dryness when the
# air is dry in the sense a person means.
_FEELS_DRY_RH = 40


def _feels_terms(temp_c, humidity, wind_ms, gap_c):
    """What humidity, wind and sunshine each contribute, in degrees Celsius."""
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    humid = 0.33 * vapour - 4.0     # zero at a dew point near 10 C
    wind = -0.70 * wind_ms
    return {"humid": humid, "wind": wind, "sun": gap_c - humid - wind}


def _is_daylight(daily, now):
    """Whether `now` falls between today's sunrise and sunset.  False when
    the day has no sunrise -- a polar winter, or a forecast that omits it."""
    from linecast._weather.hourly import _parse_sun_events
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
    return _feels(current, daily, now, runtime)[0]


# Below this the air is cold, and a wind makes it feel colder rather
# than cooler.
_FEELS_COLD_C = 10


def _feels(current, daily, now, runtime):
    """The feels-like sentence and the cause it names."""
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    if temp is None or feels is None or humidity is None or wind is None:
        return "", None

    # A gap has to be one a person would notice before it is worth a
    # sentence: six degrees Fahrenheit, or three Celsius.
    gap = feels - temp
    if abs(gap) < (3 if runtime.celsius else 6):
        return "", None

    to_c = (lambda t: t) if runtime.celsius else (lambda t: (t - 32) * 5 / 9)
    terms = _feels_terms(
        to_c(temp), humidity,
        runtime.wind_kmh(wind) / 3.6,
        gap if runtime.celsius else gap * 5 / 9,
    )

    if gap < 0 and humidity >= _FEELS_DRY_RH:
        del terms["humid"]

    # Of the terms pushing the way the reading went, the largest one.
    pushing = sorted(((abs(size), name) for name, size in terms.items()
                      if (size > 0) == (gap > 0)), reverse=True)
    if not pushing or pushing[0][0] < _FEELS_FLOOR_C:
        return "", None

    holding = pushing[0][1]

    def said(key):
        # Air that is cold already feels colder, not cooler, where the
        # language tells the two apart
        if to_c(temp) < _FEELS_COLD_C and _has(key + "_cold", runtime):
            key += "_cold"
        return _s(key, runtime)

    if holding == "wind":
        return said("feels_wind"), "wind"
    if holding == "humid":
        return (_s("feels_humid", runtime) if gap > 0 else said("feels_dry")), "humid"
    # Sunshine is the leftover, so it carries whatever the formula and the
    # API disagree about.  Claim it only when it warms, and only with the
    # sun actually up.
    if gap > 0 and _is_daylight(daily, now):
        return _s("feels_sun", runtime), "sun"
    return "", None


# The felt temperature ahead is worth a sentence when it is extreme and
# not what this place is used to: heat a person should plan around, or a
# wind chill they should dress for.  What the place is used to is read
# off the rest of the forecast week; a gap between felt and thermometer
# that every day has is the climate, not news.  Past the danger marks it
# is said regardless.
#
# And it has to be news against the hour the reader is in.  Promising 34°
# when the header already says it feels 34° says nothing, and costs the
# present-tense sentence that would have said why, so the hour ahead has
# to be a couple of degrees past the one at hand before it is named.
_FEELS_AHEAD_HOT_C = 33
_FEELS_AHEAD_COLD_C = -15
_FEELS_AHEAD_DANGER_HOT_C = 40
_FEELS_AHEAD_DANGER_COLD_C = -25
_FEELS_AHEAD_UNUSUAL_C = 2.0
_FEELS_AHEAD_BEYOND_NOW_C = 2.0


def feels_ahead_sentence(hourly, now, runtime=None, daily=None, current=None):
    """"High humidity will make it feel as high as 36° this afternoon":
    the felt temperature at the hottest or coldest hour of the day
    ahead, when it is extreme, the air temperature does not say so on
    its own, and it is a couple of degrees past what it feels like now,
    with what is behind it when one thing is.  The current hour is the
    feels-like sentence's; this looks past it."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _feels_ahead(hourly, now, runtime, current=current)[0]


def _feels_ahead(hourly, now, runtime, after=None, current=None):
    """The feels-ahead sentence, the hour it is about, and its cause."""
    nothing = ("", None, None)
    if not _has("feels_ahead_hot", runtime):
        return nothing
    temps = hourly.get("temperature_2m") or []
    feels = hourly.get("apparent_temperature") or []
    humidity = hourly.get("relative_humidity_2m") or []
    wind = hourly.get("wind_speed_10m") or []
    later = [(i, dt) for i, dt in _hours_ahead(hourly, now)
             if (dt - now).total_seconds() >= 1.5 * 3600
             and i < len(temps) and i < len(feels)
             and temps[i] is not None and feels[i] is not None]
    if not later:
        return nothing
    to_c = (lambda t: t) if runtime.celsius else (lambda t: (t - 32) * 5 / 9)
    gap_c = 3.0

    i, dt = max(later, key=lambda h: feels[h[0]])
    hot = (to_c(feels[i]) >= _FEELS_AHEAD_HOT_C
           and to_c(feels[i]) - to_c(temps[i]) >= gap_c)
    if not hot:
        i, dt = min(later, key=lambda h: feels[h[0]])
        if not (to_c(feels[i]) <= _FEELS_AHEAD_COLD_C
                and to_c(temps[i]) - to_c(feels[i]) >= gap_c):
            return nothing
    gap = to_c(feels[i]) - to_c(temps[i])

    # Is it anything the reader does not already have?  A sentence about
    # an extreme is for planning, and there is nothing to plan for in a
    # temperature it feels like right now.
    felt_now = (current or {}).get("apparent_temperature")
    if felt_now is not None:
        beyond = to_c(feels[i]) - to_c(felt_now)
        if (beyond if hot else -beyond) < _FEELS_AHEAD_BEYOND_NOW_C:
            return nothing

    # Is this what the place is used to?  The same gap on the other days
    # of the forecast says yes, unless the reading is dangerous anyway.
    danger = (to_c(feels[i]) >= _FEELS_AHEAD_DANGER_HOT_C if hot
              else to_c(feels[i]) <= _FEELS_AHEAD_DANGER_COLD_C)
    if not danger:
        pick = max if hot else min
        by_day = {}
        for k, t in enumerate(hourly.get("time") or []):
            if k >= len(temps) or k >= len(feels) or temps[k] is None or feels[k] is None:
                continue
            day = t[:10]
            gap_k = to_c(feels[k]) - to_c(temps[k])
            by_day[day] = pick(by_day.get(day, gap_k), gap_k)
        others = [g for day, g in by_day.items() if day != dt.date().isoformat()]
        if others:
            others.sort()
            usual = others[len(others) // 2]
            if abs(gap - usual) < _FEELS_AHEAD_UNUSUAL_C:
                return nothing

    cause = None
    if i < len(humidity) and i < len(wind) and humidity[i] is not None and wind[i] is not None:
        terms = _feels_terms(to_c(temps[i]), humidity[i],
                             runtime.wind_kmh(wind[i]) / 3.6, gap)
        pushing = sorted(((abs(size), name) for name, size in terms.items()
                          if (size > 0) == (gap > 0)), reverse=True)
        if pushing and pushing[0][0] >= _FEELS_FLOOR_C:
            cause = pushing[0][1]
    key = "feels_ahead_hot" if hot else "feels_ahead_cold"
    if hot and cause in ("humid", "sun"):
        key += "_" + cause
    elif not hot and cause == "wind":
        key += "_wind"
    else:
        cause = None
    return (_ucfirst(_s(key, runtime, temp=_degrees(feels[i], runtime, signed=True),
                        time=_period_phrase(dt, now, runtime, after=after))), dt, cause)


# ---------------------------------------------------------------------------
# Comparative weather line
# ---------------------------------------------------------------------------
# The hour the comparison stops looking back at yesterday and starts looking
# ahead to tomorrow.  Most of today's high is in by then.
_COMPARISON_TURNS_TO_TOMORROW = 14


def _comparison(daily, now, runtime, inherited=False):
    """The comparative sentence and its salience: nothing to say, about the
    same, a few degrees, or a real change.  With `inherited`, the sentence
    before this one has already said "tomorrow", and the language's
    "will_be_then" form carries it: "It will be 3° cooler than today"."""
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
        return "", 0

    if now.hour < _COMPARISON_TURNS_TO_TOMORROW:
        a, b = hi_temps[0], hi_temps[1]
        ref_key, subject = "yesterday", _s("today_subj", runtime)
    else:
        a, b = hi_temps[1], hi_temps[2]
        ref_key, subject = "today_ref", _s("tomorrow_subj", runtime)
    ref_day = _s(ref_key, runtime)
    # The reference day with "and", "with", for a language whose word
    # for it depends on the day: Korean 어제와, 오늘과
    ref_day_with = _s(ref_key + "_with", runtime) if _has(ref_key + "_with", runtime) else ref_day
    # Either day's high can be null; there is then nothing to compare.
    if a is None or b is None:
        return "", 0
    diff = b - a

    abs_diff = abs(diff)
    # Thresholds in degrees (smaller for Celsius since 1°C ≈ 1.8°F)
    t_same, t_bit, t_much = (2, 4, 8) if runtime.celsius else (3, 8, 15)
    if abs_diff < t_same:
        key, salience = "same_temp", 2
    elif abs_diff < t_bit:
        key, salience = ("bit_warmer" if diff > 0 else "bit_cooler"), 2
    elif abs_diff < t_much:
        key, salience = ("warmer" if diff > 0 else "cooler"), 2
    else:
        key, salience = ("much_warmer" if diff > 0 else "much_cooler"), 3

    # The number stands in for "a bit" and "much" where the language has
    # the form for it; the others keep their words.
    if key != "same_temp" and _has("warmer_by", runtime) and _has("degrees", runtime):
        key = "warmer_by" if diff > 0 else "cooler_by"
    form = "will_be"
    if inherited and _has("will_be_then", runtime):
        form = "will_be_then"
        if _has(key + "_then", runtime):
            # French keeps the subject inside the comparison; the
            # inherited form has one without it
            key += "_then"
    comparison = _s(key, runtime, ref_day=ref_day, ref_day_with=ref_day_with,
                    subject=subject.lower(), diff=_degrees(diff, runtime))
    return _s(form, runtime, subject=subject, comparison=comparison), salience


def comparative_sentence(daily, now, runtime=None):
    """Plain-text natural language comparing today vs yesterday/tomorrow."""
    return _comparison(daily, now, runtime)[0]


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

# What kind of thing is falling.  A turn from one kind to another is
# always worth a word -- drizzle to rain, rain to snow, showers to
# thunder.  Within a kind, only a turn to heavy is: nobody says "light
# drizzle becoming drizzle" out loud.
_PRECIP_KIND = {
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    80: "rain", 81: "rain", 82: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
    95: "thunder", 96: "thunder", 99: "thunder",
}
_HEAVY_RANK = 4
_SNOW_CODES = {71, 73, 75, 77, 85, 86}
_FREEZING_CODES = {56, 57, 66, 67}

# Open-Meteo's hourly probability, and the hedge it earns: a chance below
# sixty, likely below eighty, and no hedge at all from eighty up.
_PRECIP_CHANCE_BELOW = 60
_PRECIP_LIKELY_BELOW = 80


@functools.lru_cache(maxsize=None)
def _precip_descs(lang):
    """The precipitation nouns by WMO code in `lang`: English under the
    language's own, and a regional variant's few under its base's."""
    descs = dict(_PRECIP_DESCS)
    for code in reversed(fallbacks(lang)):
        descs.update(_PRECIP_DESCS_I18N.get(code, {}))
    return descs


@functools.lru_cache(maxsize=None)
def _precip_partitives(lang):
    """The precipitation nouns with their article, by WMO code, where the
    language has them: a regional variant's under its base's."""
    forms = {}
    for code in reversed(fallbacks(lang)):
        forms.update(_PRECIP_PARTITIVES_I18N.get(code, {}))
    return forms


def _peak_hour(run, amounts, codes, desc=None, open_ended=False):
    """The hour in a run of precipitation worth naming on its own, or None.

    The peak is the hour with the most forecast, the tallest column of
    the bar under the chart; with no amounts it is the hour of the
    heaviest code.  It is named only when it is a turn a person would
    mention: to another kind of precipitation, or to heavy.  A run that
    keeps its name says nothing more, and neither does one whose turn
    the language has no separate word for.  The hour returned is the
    first at which the run reads as the peak does.

    A turn can be hiding behind the peak: the thunder at eight after a
    wetter hour of plain rain at seven.  When the peak is not a turn,
    the run's first hour of thunder, snow or ice is named instead --
    weather a person would change their plans for, rather than the same
    water in another size, which the peak already speaks for.
    """
    def amount(idx):
        return (amounts[idx] if idx < len(amounts) else 0) or 0

    def rank(idx):
        return _PRECIP_RANK.get(codes[idx] if idx < len(codes) else 0, 0)

    def code(idx):
        return codes[idx] if idx < len(codes) else 0

    def kind(idx):
        return _PRECIP_KIND.get(code(idx))

    first = run[0][0]
    later = run[1:]
    if not later:
        return None

    def worth_naming(idx):
        """Whether an hour is a turn a person would mention: to another
        kind of precipitation, or to heavy, and one the language has a
        separate word for."""
        if rank(idx) <= rank(first):
            return False
        if kind(idx) == kind(first) and rank(idx) < _HEAVY_RANK:
            return False
        return desc is None or desc(idx) != desc(first)

    def another_thing(idx):
        """Thunder, snow or ice where the run began as something else.
        Drizzle after showers is the same water in another size, and a
        let-up rather than a turn, whatever its rank."""
        if code(idx) in _FREEZING_CODES and code(first) not in _FREEZING_CODES:
            return True
        return kind(idx) in ("snow", "thunder") and kind(idx) != kind(first)

    peak = None
    if any(amount(i) for i, _ in run):
        i, dt = max(later, key=lambda h: amount(h[0]))
        if amount(i) > amount(first):
            peak = (i, dt)
    else:
        peak = max(later, key=lambda h: rank(h[0]))
    if peak is None or not worth_naming(peak[0]):
        # The wettest hour of the run is no turn, but one can be hiding
        # behind it: an hour of thunder carries less water than the hour
        # of rain before it and is still what a person would be told.
        peak = next(((j, when) for j, when in later
                     if another_thing(j) and worth_naming(j)), None)
        if peak is None:
            return None
    i, dt = peak
    # The peak says what it turns into; the turn is when the run first
    # reaches that.  Drizzle now with rain from two and the most of it
    # after midnight becomes rain in a couple of hours, not overnight.
    for n, (j, when) in enumerate(run):
        if (desc(j) == desc(i)) if desc is not None else (code(j) == code(i)):
            # A turn needs two hours of the new weather to be worth its
            # own clause, unless the run is cut off by the end of the
            # day's window rather than by dry weather
            if not open_ended and n > len(run) - 2:
                return None
            return j, when
    return i, dt


def _precip_parts(hourly, now, runtime, daily=None, after=None, current=None):
    """The precipitation sentence for the next 24 hours, and what it was
    built from, for the sentences that follow it: the run of wet hours,
    when it ends, the next run after that, and the hour window."""
    parts = {"sentence": "", "kind": "", "run": [], "end": None, "next": None,
             "window": [], "salience": 0, "desc": None, "codes": [], "last_named": None}
    lang = runtime.lang
    precip_prob = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])
    amounts = hourly.get("precipitation") or []
    parts["codes"] = codes

    if not hourly.get("time") or not precip_prob or not codes:
        return parts

    window = _hours_ahead(hourly, now)
    if len(window) < 2:
        return parts
    parts["window"] = window

    def prob(idx):
        # A null probability or code is an hour that says nothing
        return (precip_prob[idx] if idx < len(precip_prob) else 0) or 0

    # The header prints what is falling now, so the prose cannot say it
    # has not started: when the current conditions are wet, the hour we
    # are in is wet too, whatever its own odds.  Hong Kong's drizzle at
    # exactly thirty percent is drizzle.
    current_wet = (current or {}).get("weather_code") in _PRECIP_CODES
    first_idx = window[0][0]

    def is_precip(idx):
        c = codes[idx] if idx < len(codes) else 0
        if c not in _PRECIP_CODES:
            return False
        return prob(idx) > 30 or (idx == first_idx and current_wet)

    def desc(idx):
        c = codes[idx] if idx < len(codes) else 0
        descs = _precip_descs(lang)
        return descs.get(c, _PRECIP_DESCS.get(c, "precipitation"))

    parts["desc"] = desc

    def run_from(n):
        """The wet hours from window[n] on, and the first dry hour after
        them.  A single dry hour with rain on both sides is a lull, not an
        ending, and stays in the run."""
        run = [window[n]]
        k = n + 1
        while k < len(window):
            i, dt = window[k]
            if not is_precip(i):
                if k + 1 < len(window) and is_precip(window[k + 1][0]):
                    run.append((i, dt))
                    k += 1
                    continue
                return run, k
            run.append((i, dt))
            k += 1
        return run, None

    def salience(run):
        heavy = any(_PRECIP_RANK.get(codes[i], 0) >= _HEAVY_RANK
                    or codes[i] in _FREEZING_CODES for i, _ in run if i < len(codes))
        return 5 if heavy else 4

    def sentence(key, run, end=None, start=None, open_ended=False, **words):
        """The template for `key`, or its "becoming" form when the run
        has an hour heavier than its first worth naming.  The hours are
        phrased in the order the sentence says them, so "tomorrow" is
        said once: the start, then the turn; or the turn, then the end.
        The last hour named is left in parts["last_named"] for the
        sentence that follows."""
        peak = _peak_hour(run, amounts, codes, desc, open_ended)
        # The hour whose noun the sentence opens with, for agreement
        noun = run[0][0]
        if peak and (peak[1] - now).total_seconds() < 1.5 * 3600:
            # A turn that is all but here is what is falling: "showers
            # ending in a couple hours", not "drizzle becoming showers
            # shortly"
            words["desc"] = desc(peak[0])
            noun = peak[0]
            peak = None
        if peak and start is not None and (peak[1] - start).total_seconds() <= 2 * 3600:
            # An hour of drizzle at the edge of a storm is the storm:
            # "thunderstorms starting around noon", not "drizzle at
            # eleven becoming thunderstorms at noon"
            words["desc"] = desc(peak[0])
            noun = peak[0]
            start = peak[1]
            peak = None
        if start is not None:
            words["time"] = _time_phrase(start, now, runtime, after=after)
        if peak:
            # Rain that turns heavy is the same rain, harder: a language
            # that says so in its own way ("雨が強まり", not "雨が強い雨と
            # なり") carries a "_heavier" form of the template, and the
            # "_becoming" form is kept for a turn to another kind
            # Rain that freezes is not the rain turned heavy, whatever
            # its rank: it is another thing, and says so
            same_kind = (_PRECIP_KIND.get(codes[peak[0]])
                         == _PRECIP_KIND.get(codes[run[0][0]])
                         and (codes[peak[0]] in _FREEZING_CODES)
                         == (codes[run[0][0]] in _FREEZING_CODES))
            if same_kind and _has(key + "_heavier", runtime):
                key += "_heavier"
            else:
                key += "_becoming"
            peak_code = codes[peak[0]] if peak[0] < len(codes) else 0
            words.update(peak=desc(peak[0]),
                         peak_art=_precip_partitives(lang).get(peak_code, desc(peak[0])),
                         peak_time=_time_phrase(peak[1], now, runtime, after=start,
                                                same_sentence=True))
        if end is not None:
            words["time"] = _time_phrase(end, now, runtime, after=peak[1] if peak else None,
                                         same_sentence=True)
        parts["last_named"] = end or (peak[1] if peak else None) or start
        return _ucfirst(_precip_s(key, codes[noun] if noun < len(codes) else 0, runtime,
                                  **words))

    if is_precip(first_idx):
        run, end_n = run_from(0)
        parts["run"] = run
        parts["salience"] = salience(run)
        if end_n is not None:
            end = window[end_n][1]
            parts["kind"] = "ending"
            parts["end"] = end
            for i, dt in window[end_n + 1:]:
                if is_precip(i):
                    parts["next"] = (i, dt)
                    break
            parts["sentence"] = sentence("ending", run, end=end, desc=desc(first_idx))
        else:
            parts["kind"] = "continuing"
            key = "continuing"
            if _is_night(daily or {}, now) and _has("continuing_night", runtime):
                key = "continuing_night"
            parts["sentence"] = sentence(key, run, desc=desc(first_idx), open_ended=True)
        return parts

    # Only rain worth planning for leads.  A single forty-percent hour
    # before lunch is not what a person wants to hear about a day with
    # an evening thunderstorm in it, so a run that is no more than a
    # chance leads only when nothing surer follows it inside the day.
    # The chance then goes unsaid: the paragraph has better to say.
    leading = None
    n = 1
    while n < len(window):
        i, dt = window[n]
        if not is_precip(i):
            n += 1
            continue
        run, end_n = run_from(n)
        best = max(prob(j) for j, _ in run)
        if leading is None or best >= _PRECIP_CHANCE_BELOW:
            leading = (i, dt, run, end_n, best)
        if best >= _PRECIP_CHANCE_BELOW:
            break
        n = len(window) if end_n is None else end_n
    if leading is None:
        return parts

    i, dt, run, end_n, best = leading
    parts["run"] = run
    parts["kind"] = "starting"
    parts["salience"] = salience(run)
    # The hedge follows the best hour of the run: how likely it is to
    # rain at all, not how sure the first drop's hour is.
    key = "starting"
    if best < _PRECIP_CHANCE_BELOW and _has("starting_chance", runtime):
        key = "starting_chance"
    elif best >= _PRECIP_LIKELY_BELOW and _has("starting_sure", runtime):
        key = "starting_sure"
    elif not _names_an_hour(dt, now) and _has("starting_span", runtime):
        # Likely in a part of the day needs no "starting": "light
        # drizzle likely in the evening".  Before an hour it does, or
        # the rain would seem to fall in that hour alone
        key = "starting_span"
    parts["sentence"] = sentence(key, run, start=dt, desc=desc(i),
                                 open_ended=end_n is None)
    return parts


def precipitation_sentence(hourly, now, runtime=None, daily=None, current=None):
    """Plain-text description of upcoming precipitation."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _precip_parts(hourly, now, runtime, daily, current=current)["sentence"]


def _precipitation_line(hourly, now, runtime=None):
    """ANSI-colored precipitation sentence for the dashboard."""
    return _prose(precipitation_sentence(hourly, now, runtime))


def more_later_sentence(parts, now, runtime, after=None):
    """"More rain this evening": a second run of precipitation after the
    first one ends, when there is one within the day and a real break
    before it."""
    if parts["kind"] != "ending" or not parts["next"] or not _has("more_later", runtime):
        return ""
    i, dt = parts["next"]
    if (dt - parts["end"]).total_seconds() < 3 * 3600:
        return ""
    codes = parts["codes"]
    return _ucfirst(_precip_s("more_later", codes[i] if i < len(codes) else 0, runtime,
                              desc=parts["desc"](i),
                              time=_time_phrase(dt, now, runtime, after=after)))


def snow_total_sentence(hourly, now, runtime=None, daily=None, current=None):
    """Plain-text snow accumulation over the coming run of snow."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    parts = _precip_parts(hourly, now, runtime, daily, current=current)
    return _snow_sentence(parts, hourly, now, runtime)[0]


def _snow_sentence(parts, hourly, now, runtime):
    run = parts["run"]
    if not run or not _has("snow_total", runtime):
        return "", False
    codes = hourly.get("weather_code", [])
    snowfall = hourly.get("snowfall") or []
    snow_hours = sum(1 for i, _ in run if i < len(codes) and codes[i] in _SNOW_CODES)
    if snow_hours * 2 < len(run):
        return "", False
    total_cm = sum((snowfall[i] if i < len(snowfall) else 0) or 0 for i, _ in run)
    if total_cm < 1:
        return "", False
    if runtime.metric:
        # "About" and a decimal do not go together; whole centimetres
        amt = f"{total_cm:.0f}{_prose_sep(runtime)}{_s('unit_cm', runtime)}"
    else:
        inches = total_cm / 2.54
        n = f"{inches:.0f}" if inches >= 2 else fmt_decimal(inches, 1, runtime)
        amt = _prose_inches(n, runtime)
    end = parts["end"] or run[-1][1]
    return (_ucfirst(_s("snow_total", runtime, amt=amt,
                        time=_period_phrase(end, now, runtime, by=True))),
            total_cm >= 10)


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
        # Each hour's figure is what fell in the hour before its stamp,
        # so the last day is the 24 stamps after the start, up to this hour
        if dt <= past_start or dt > current_hour:
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

    # A tenth of an inch, 2.5 mm, before it is worth a sentence: less
    # than that is a damp pavement, and nobody reports it.  Snow from a
    # centimetre.
    if total_precip < (2.5 if runtime.metric else 0.1) and total_snow_cm < 1:
        return ""

    # Determine dominant type and format amount
    metric_sep = _prose_sep(runtime)
    if snow_hours >= rain_hours and snow_hours >= mix_hours:
        # Show snow accumulation (Open-Meteo snowfall is in cm)
        if runtime.metric:
            amt = f"{fmt_decimal(total_snow_cm, 1, runtime)}{metric_sep}{_s('unit_cm', runtime)}"
        else:
            inches = total_snow_cm / 2.54
            amt = _prose_inches(fmt_decimal(inches, 1 if inches >= 1 else 2, runtime), runtime)
        ptype = _s("snow", runtime)
    elif mix_hours >= rain_hours:
        if runtime.metric:
            amt = f"{fmt_decimal(total_precip, 1, runtime)}{metric_sep}{_s('unit_mm', runtime)}"
        else:
            amt = _prose_inches(fmt_decimal(total_precip, 2, runtime), runtime)
        ptype = _s("mixed_precip", runtime)
    else:
        if runtime.metric:
            amt = f"{fmt_decimal(total_precip, 1, runtime)}{metric_sep}{_s('unit_mm', runtime)}"
        else:
            amt = _prose_inches(fmt_decimal(total_precip, 2, runtime), runtime)
        ptype = _s("rain", runtime)

    return _s("past_precip", runtime, amt=amt, ptype=ptype)


def _past_precip_line(hourly, now, runtime):
    """ANSI-colored past-precipitation sentence for the dashboard."""
    return _prose(past_precip_sentence(hourly, now, runtime))


# ---------------------------------------------------------------------------
# The week ahead: when it next rains
# ---------------------------------------------------------------------------
def next_rain_sentence(daily, now, runtime=None, hourly=None):
    """The next rain in the week, when nothing falls in the next day and
    the rain is worth mentioning: "Rain likely on Friday".  A chance of
    drizzle in six days is not; the further off, the surer and the wetter
    it has to be.  Dry spells go unremarked."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _next_rain(daily, now, runtime, hourly)[0]


# What a day has to hold to be the next rain worth a sentence, by how
# far off it is: (days from now, least chance, least amount in mm).
_NEXT_RAIN_WORTH = ((2, 60, 2.0), (7, 70, 5.0))


def _next_rain(daily, now, runtime, hourly=None, after=None):
    """The next-rain sentence and the day it is about."""
    if not _has("rain_next", runtime):
        return "", None
    times = daily.get("time") or []
    sums = daily.get("precipitation_sum") or []
    probs = daily.get("precipitation_probability_max") or []
    codes = daily.get("weather_code") or []
    if not times or not sums:
        return "", None
    mm = 1.0 if runtime.metric else 25.4
    by_date = {}
    for k, t in enumerate(times):
        amount = ((sums[k] if k < len(sums) else 0) or 0) * mm
        p = (probs[k] if k < len(probs) else 0) or 0
        by_date[t] = (amount, p, codes[k] if k < len(codes) else 0)
    for offset in range(1, 8):
        day = now.date() + timedelta(days=offset)
        row = by_date.get(day.isoformat())
        if row is None:
            break
        amount, p, code = row
        within, chance, least = next(w for w in _NEXT_RAIN_WORTH if offset <= w[0])
        if p < chance or amount < least:
            continue
        at = datetime.combine(day, now.time().replace(hour=12, minute=0, second=0,
                                                       microsecond=0))
        near = _next_rain_near(hourly or {}, now, day, runtime, far=offset > 2, after=after)
        if near:
            return near, at
        if hourly and near == "":
            # The hours know the day and found nothing worth saying
            continue
        # Without the hours, the day's own code says what falls.  A wet
        # tomorrow has no time of day to give it then, and no language
        # has a bare "tomorrow" to say instead, so it goes unsaid.
        if offset == 1:
            return "", None
        lang = runtime.lang
        desc = _precip_descs(lang).get(code)
        when = _on_full_day(day, runtime)
        if not desc:
            code, desc = 63, _precip_descs(lang).get(63, "rain")
        key = ("rain_next_chance" if p < _PRECIP_CHANCE_BELOW
               else "rain_next_likely" if p < _PRECIP_LIKELY_BELOW else "rain_next")
        return _ucfirst(_precip_s(key, code, runtime, desc=desc, time=when)), at
    return "", None


def _on_full_day(day, runtime):
    """"on Friday", with the day's full name, declined where the language
    declines it."""
    lang = runtime.lang
    name = table_for(FULL_DAY_NAMES, lang)[day.weekday()]
    forms = ON_FULL_DAY_FORMS.get(lang, ON_FULL_DAY_FORMS.get(base_language(lang), {}))
    form = forms.get(day.weekday())
    if form:
        return form.format(day=name)
    return _s("on_full_day", runtime, day=name)


def _next_rain_near(hourly, now, day, runtime, far=False, after=None):
    """"Light rain likely on Monday": `day`'s rain in the hourly series,
    starting at its first wet hour, named by the hour that holds most of
    it and hedged by the wettest hour's odds.  Nothing without the
    hours, nothing that is only a chance, and nothing for drizzle on a
    day that is far off."""
    times = hourly.get("time") or []
    codes = hourly.get("weather_code") or []
    probs = hourly.get("precipitation_probability") or []
    amounts = hourly.get("precipitation") or []
    wet = []
    for i, t in enumerate(times):
        if i >= len(codes) or i >= len(probs):
            break
        try:
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        if dt.date() != day:
            continue
        p = probs[i] or 0
        if codes[i] in _PRECIP_CODES and p > 30:
            wet.append((i, dt, p, (amounts[i] if i < len(amounts) else 0) or 0))
    if not wet:
        return ""
    _, dt, _, _ = wet[0]
    best = max(w[2] for w in wet)
    if best < _PRECIP_CHANCE_BELOW:
        return ""
    # A wet day that opens with a drizzly hour is not a day of drizzle.
    # The hour carrying most of the water says what falls, and the first
    # wet hour still says when; with no amounts to weigh, the heaviest
    # code stands in.
    if any(w[3] for w in wet):
        i = max(wet, key=lambda w: w[3])[0]
    else:
        i = max(wet, key=lambda w: _PRECIP_RANK.get(codes[w[0]], 0))[0]
    if far and _PRECIP_KIND.get(codes[i]) == "drizzle":
        return ""
    lang = runtime.lang
    desc = _precip_descs(lang).get(
        codes[i], _PRECIP_DESCS.get(codes[i], "rain"))
    if dt.date() == (now + timedelta(days=1)).date():
        when = _time_phrase(dt, now, runtime, after=after)
    else:
        when = _on_full_day(dt, runtime)
    key = ("rain_next_chance" if best < _PRECIP_CHANCE_BELOW
           else "rain_next_likely" if best < _PRECIP_LIKELY_BELOW else "rain_next")
    return _ucfirst(_precip_s(key, codes[i], runtime, desc=desc, time=when))


# ---------------------------------------------------------------------------
# The sky: clearing and clouding over
# ---------------------------------------------------------------------------
# Cloud cover, averaged over three hours, above which the sky is cloudy and
# below which it is clear.  Between the two nothing is claimed.
_SKY_CLOUDY = 65
_SKY_CLEAR = 35


def sky_sentence(hourly, daily, now, runtime=None, precip_kind="", precip_end=None):
    """"Clearing around 2pm", "Clouding over tomorrow morning": the first
    lasting change in the sky over the next day, when the sky is plainly
    one thing now and plainly the other later.

    Lasting means the old sky does not come back within the day: a clear
    hour or two before the marine layer rolls in again is not clearing.
    The hour named is the hour the change arrives, after dark as much as
    in the daylight: someone reading at seven in the evening, hoping to
    see stars, is owed the hour the cloud comes in and not the first
    hour of the morning that shows it.  Because the old sky has to stay
    away for the rest of the window, a change in the night is one that
    still holds when the sun comes up.  Rain that is starting or
    continuing already says the sky is clouding over, so nothing is said
    then; after rain that is ending, only a clearing after the end."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _sky(hourly, daily, now, runtime, precip_kind, precip_end)[0]


def _sky(hourly, daily, now, runtime, precip_kind="", precip_end=None, after=None):
    """The sky sentence and the hour it is about."""
    if not _has("sky_clearing", runtime) or precip_kind in ("starting", "continuing"):
        return "", None
    cover = hourly.get("cloud_cover") or []
    hours = [(i, dt) for i, dt in _hours_ahead(hourly, now)
             if i < len(cover) and cover[i] is not None]
    if len(hours) < 4:
        return "", None
    values = [cover[i] for i, _ in hours]

    def sky(percent):
        return ("cloudy" if percent >= _SKY_CLOUDY
                else "clear" if percent <= _SKY_CLEAR else None)

    def state(k):
        span = values[k:k + 3]
        return sky(sum(span) / len(span))

    start = state(0)
    if start is None:
        return "", None
    for k in range(1, len(hours) - 2):
        new = state(k)
        if new is None or new == start:
            continue
        # A change that holds: the old sky does not return in the hours
        # left in the day
        if any(state(m) == start for m in range(k, len(hours))):
            return "", None
        # The three-hour mean turns as soon as the change is within
        # sight of it, up to two hours before the sky itself does; the
        # hour to name is the first one whose own cover is the new sky.
        dt = next(hours[m][1] for m in range(k, min(k + 3, len(values)))
                  if sky(values[m]) == new)
        if new == "clear":
            if precip_end is not None and dt < precip_end:
                return "", None
            return _ucfirst(_s("sky_clearing", runtime,
                               time=_time_phrase(dt, now, runtime, after=after))), dt
        if precip_kind == "ending":
            return "", None
        return _ucfirst(_s("sky_clouding", runtime,
                           time=_time_phrase(dt, now, runtime, after=after))), dt
    return "", None


# ---------------------------------------------------------------------------
# Fog
# ---------------------------------------------------------------------------
# The two codes the model has for fog: fog, and the freezing fog that
# leaves rime on whatever it touches.  A person says "fog" for both and
# the prose does too; which of the two it is, the header's label says.
_FOG_CODES = (45, 48)


def fog_sentence(hourly, current, now, runtime=None, daily=None):
    """"Fog overnight, clearing tomorrow morning": when there is fog in
    the day ahead, when it closes in, and when it lifts.

    Fog is worth a sentence whatever else the weather is doing, so it is
    said alongside the rain rather than instead of it.  Fog already out
    there is said as what it does next, since the header has shown it and
    the paragraph must not read as though the air were clear.  An hour of
    it later on is a patch the model happens to have put on the hour and
    goes unsaid; a clear hour with fog on both sides is a thinning, not a
    lifting, as with rain."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _fog(hourly, current, now, runtime, daily=daily)[0]


def _fog(hourly, current, now, runtime, after=None, daily=None):
    """The fog sentence, the hour it is anchored at, and the hour it names
    as the end, when it names one."""
    nothing = ("", None, None)
    codes = hourly.get("weather_code") or []
    window = [(i, dt) for i, dt in _hours_ahead(hourly, now) if i < len(codes)]
    if len(window) < 2:
        return nothing

    def is_fog(n):
        return codes[window[n][0]] in _FOG_CODES

    def part_of_day(dt):
        """The stretch of the day an hour belongs to, by the parts the
        prose names: the night runs past midnight, so two in the morning
        and the evening before it are the one stretch."""
        if dt.hour >= 21:
            return dt.date(), "night"
        if dt.hour < 5:
            return dt.date() - timedelta(days=1), "night"
        if dt.hour < 12:
            return dt.date(), "morning"
        if dt.hour < 17:
            return dt.date(), "afternoon"
        return dt.date(), "evening"

    def run_from(n):
        """The foggy hours from window[n] on, and the first clear hour
        after them, or None when the fog outlasts the window."""
        run = [window[n]]
        k = n + 1
        while k < len(window):
            if not is_fog(k):
                if k + 1 < len(window) and is_fog(k + 1):
                    run.append(window[k])
                    k += 1
                    continue
                return run, k
            run.append(window[k])
            k += 1
        return run, None

    if is_fog(0) or (current or {}).get("weather_code") in _FOG_CODES:
        # Fog the header is already showing.  The reading on the screen
        # wins over the model's first hour where the two disagree, and
        # that hour is read as a thinning inside the fog.
        _, end_n = run_from(0)
        if end_n is not None:
            if not _has("fog_ending", runtime):
                return nothing
            end = window[end_n][1]
            return (_ucfirst(_s("fog_ending", runtime,
                                time=_time_phrase(end, now, runtime, after=after))),
                    now, end)
        # Fog with no end in the day ahead: how long it holds is all
        # there is to say, and that is the day or the night, not an hour.
        key = "fog_continuing"
        if _is_night(daily or {}, now) and _has("fog_continuing_night", runtime):
            key = "fog_continuing_night"
        if not _has(key, runtime):
            return nothing
        return _ucfirst(_s(key, runtime)), now, None

    n = 1
    while n < len(window):
        if not is_fog(n):
            n += 1
            continue
        run, end_n = run_from(n)
        if sum(1 for i, _ in run if codes[i] in _FOG_CODES) > 1:
            # Fog fills a part of the day rather than arriving at an
            # hour, so it is named the way the gusty afternoon and the
            # freezing night are: "fog tonight", not "fog at eleven".
            # The lifting is an hour, and is named as one.
            start = run[0][1]
            time = _period_phrase(start, now, runtime, after=after)
            end = window[end_n][1] if end_n is not None else None
            # The lifting is worth naming when it falls in another
            # stretch of the day than the fog came in on; inside the one
            # stretch, "fog tonight" has said it, and "fog tonight,
            # clearing overnight" would only say it again, worse.
            if (end is not None and part_of_day(end) != part_of_day(start)
                    and _has("fog_starting_ending", runtime)):
                # The end is phrased after the start, so a night that
                # runs into the morning says "tomorrow" once
                ending = _time_phrase(end, now, runtime, after=start)
                return (_ucfirst(_s("fog_starting_ending", runtime,
                                    time=time, end=ending)), start, end)
            if not _has("fog_starting", runtime):
                return nothing
            return _ucfirst(_s("fog_starting", runtime, time=time)), start, None
        # A single foggy hour is not worth a sentence; there may be fog
        # that is further on.
        if end_n is None:
            break
        n = end_n + 1
    return nothing


# ---------------------------------------------------------------------------
# Wind, and the cold
# ---------------------------------------------------------------------------
# Gusts worth a sentence, and gusts worth leading with, in km/h.  Short
# of a gale, gusts are news only when they are more than the place is
# used to, read off the rest of the forecast week the way the felt
# temperature is: Honolulu's afternoon trade wind every day is the
# climate, and the same speed after a calm week is worth a word.
_GUSTS_NOTABLE_KMH = 40
_GUSTS_GALE_KMH = 60
_GUSTS_BEYOND_USUAL_KMH = 10


def _gusts_usual(daily, day, runtime):
    """The week's typical strongest gust, in km/h, leaving out `day`:
    the middle of the other days' maxima, or None without them."""
    days = daily.get("time") or []
    maxima = daily.get("wind_gusts_10m_max") or []
    others = sorted(runtime.wind_kmh(g) for d, g in zip(days, maxima)
                    if g is not None and d != day)
    if not others:
        return None
    return others[len(others) // 2]


def _gusts(hourly, now, runtime, after=None, daily=None):
    """"Gusts to 45 mph this afternoon", whether that is a gale, the
    hour of the peak, and the speed as written."""
    nothing = ("", False, None, "")
    if not _has("gusts_to", runtime):
        return nothing
    gusts = hourly.get("wind_gusts_10m") or []
    hours = [(i, dt) for i, dt in _hours_ahead(hourly, now)
             if i < len(gusts) and gusts[i] is not None]
    if not hours:
        return nothing
    i, dt = max(hours, key=lambda h: gusts[h[0]])
    kmh = runtime.wind_kmh(gusts[i])
    if kmh < _GUSTS_NOTABLE_KMH:
        return nothing
    if kmh < _GUSTS_GALE_KMH:
        usual = _gusts_usual(daily or {}, dt.date().isoformat(), runtime)
        if usual is not None and kmh - usual < _GUSTS_BEYOND_USUAL_KMH:
            return nothing
    speed = f"{gusts[i]:.0f}{_prose_sep(runtime)}{runtime.wind_unit_label}"
    return (_ucfirst(_s("gusts_to", runtime, speed=speed,
                        time=_period_phrase(dt, now, runtime, after=after))),
            kmh >= _GUSTS_GALE_KMH, dt, speed)


def gusts_sentence(hourly, now, runtime=None, daily=None):
    """Plain-text sentence for the strongest gusts of the day ahead."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _gusts(hourly, now, runtime, daily=daily)[0]


def freeze_sentence(hourly, current, now, runtime=None):
    """"Below freezing tonight, down to 28°": when the air is above
    freezing now and will not be by morning.  Said of the night ahead
    only, through nine tomorrow morning, and not when it is freezing
    already, which the header shows."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    return _freeze(hourly, current, now, runtime)[0]


def _freeze(hourly, current, now, runtime, after=None):
    """The freeze sentence and the hour of the low."""
    if not _has("freeze_tonight", runtime):
        return "", None
    temps = hourly.get("temperature_2m") or []
    freezing = 0 if runtime.celsius else 32
    morning = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    hours = [(i, dt) for i, dt in _hours_ahead(hourly, now)
             if dt <= morning and i < len(temps) and temps[i] is not None]
    if not hours:
        return "", None
    now_temp = current.get("temperature_2m")
    if now_temp is None:
        now_temp = temps[hours[0][0]]
    if now_temp <= freezing:
        return "", None
    i, dt = min(hours, key=lambda h: temps[h[0]])
    if temps[i] > freezing:
        return "", None
    return (_ucfirst(_s("freeze_tonight", runtime, temp=_degrees(temps[i], runtime, signed=True),
                        time=_period_phrase(dt, now, runtime, after=after))), dt)


_theme.track_imports(globals(), "linecast._weather.style")
