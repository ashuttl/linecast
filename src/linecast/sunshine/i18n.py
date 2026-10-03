"""Sunshine localization strings, and the clock in its corner.

Month names and month-day date order come from the moon tables; this
module holds the year view's relative-day phrases and the numeric month
labels for the languages whose month names don't abbreviate.
"""

from linecast._i18n import LocaleTable, base_language, has_text, lang_of, lookup, plural_category, setting, table_for
from linecast._timefmt import fmt_time_dt
from linecast._i18n import MONTHS

_SUNSHINE_STRINGS = LocaleTable("SUNSHINE")

# Month-axis labels where the first three letters of the MONTHS name
# won't do: CJK and Vietnamese dates are numeric, Finnish months are
# long words, and French juin and juillet share their first three
# letters.
# Everything else takes the first letters of the MONTHS name.
_AXIS_MONTHS = LocaleTable("CHART_MONTHS")


def _axis_months(lang):
    """The month names the axis abbreviates: a language's own axis set
    where it has one, else its months, read through a variant's base."""
    return (_AXIS_MONTHS.get(lang) or _AXIS_MONTHS.get(base_language(lang))
            or table_for(MONTHS, lang))


def _ss(key, runtime, **kwargs):
    """Look up a sunshine-specific localized string."""
    return lookup(_SUNSHINE_STRINGS, key, lang_of(runtime), **kwargs)


def sky_phase(elev, runtime, morning=None):
    """Name the sky for a sun elevation: day, the three twilights, night.

    Many languages name the two twilights of a day with different words
    — Polish świt and zmierzch, Indonesian fajar and senja, Swedish
    gryning and skymning — so *morning* tells them apart: True before
    solar noon, False after, None for a language-generic name. Languages
    without the split simply have no _dawn/_dusk entries and keep their
    one word either way.
    """
    if elev >= -0.833:
        key = "sky_day"
    elif elev >= -6:
        key = "sky_civil"
    elif elev >= -12:
        key = "sky_nautical"
    elif elev >= -18:
        key = "sky_astronomical"
    else:
        key = "sky_night"
    if morning is not None and key not in ("sky_day", "sky_night"):
        variant = key + ("_dawn" if morning else "_dusk")
        if has_text(_SUNSHINE_STRINGS, variant, lang_of(runtime)):
            key = variant
    return _ss(key, runtime)


def sky_event(key, runtime):
    """'solar noon', 'sunrise', 'sunset'."""
    return _ss(key, runtime)


def polar_name(state, runtime):
    """'midnight sun' or 'polar night' for a polar_state(), else "".

    On a day with no horizon crossing solar_times() returns solar noon
    for both the rise and the set. The phrase goes where those clock
    times would, there being none to give.
    """
    if state == "day":
        return _ss("midnight_sun", runtime)
    if state == "night":
        return _ss("polar_night", runtime)
    return ""


def relative_day(diff, runtime):
    """'today', 'in 3 days', '2 days ago' for a day offset from today.

    A language may carry category suffixes beside the plain keys, such
    as _two for Hebrew and Arabic or _few for Slavic languages. The
    count picks the form by the language's plural rule.
    """
    if diff == 0:
        return _ss("today", runtime)
    n = abs(diff)
    lang = lang_of(runtime)
    one, many = ("in_day", "in_days") if diff > 0 else ("day_ago", "days_ago")
    form = plural_category(lang, n)
    variant = many + "_" + form
    if has_text(_SUNSHINE_STRINGS, variant, lang):
        return _ss(variant, runtime, n=n)
    return _ss(one if form == "one" else many, runtime, n=n)


def axis_month_labels(runtime, narrow=False):
    """Twelve month labels for the year axis, ordered January..December.

    Wide labels are three-character month abbreviations (CJK: '1月');
    narrow ones are a single letter, or the month number where a letter
    would mean nothing.
    """
    lang = lang_of(runtime)
    if narrow:
        if setting(lang, "numeric_month_axis"):
            return [str(m) for m in range(1, 13)]
        names = _axis_months(lang)
        return [name[:1].upper() for name in names]
    names = _axis_months(lang)
    return [name[:3] for name in names]


def gregorian_axis_labels(runtime, narrow=False):
    """(labels, named): the twelve labels for a year axis that runs by
    the Gregorian months whatever the reader's calendar, as weather's and
    the tides' do.

    Where dates are Solar Hijri, a month's number would read as a Solar
    Hijri month -- 7 as Mehr, not July -- so the months are named, in
    full, since Persian does not abbreviate its months, and *named* says
    so: a name is not to be cut short, and a month too narrow for its
    name goes without a label rather than take a number."""
    from linecast.astro.calendars.civil import SOLAR_HIJRI, civil_calendar
    if civil_calendar(runtime.lang) == SOLAR_HIJRI:
        return table_for(MONTHS, runtime.lang), True
    return axis_month_labels(runtime, narrow=narrow), False


def clock_label(now, runtime, today=None):
    """'2:14p': the time of the shown moment on the location's own clock,
    so a pinned place reads as a world clock. The weekday is added only
    when that moment falls on a different day from the user's own --
    a place across the date line, or the day view scrubbed past
    midnight -- as 'Fri 3:14a'. `today` is the user's date, the
    machine's by default.
    """
    from linecast.sunshine import solar
    from linecast._i18n import DAY_NAMES
    if today is None:
        today = solar._local_today()
    clock = fmt_time_dt(now, runtime.use_24h)
    if now.date() == today:
        return clock
    day = table_for(DAY_NAMES, lang_of(runtime))[now.weekday()]
    return f"{day} {clock}"
