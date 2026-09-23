"""The civil calendar: the one the app writes its dates in.

Gregorian everywhere, except in Persian, where the date is the Solar
Hijri one (solar_hijri.py): it is Iran's civil calendar and the one a
reader there thinks in, so the moon's panel and month grid, and the
sunshine year's axis and hover, read ۱ مهر ۱۴۰۵ rather than 23
September. The Gregorian date stays beside it in the hovers.

The choice is a setting like the others. Precedence: LINECAST_DATES >
the `dates` key in config.json (`linecast dates gregorian|solar-hijri`)
> the language. JSON output is never touched: it stays ISO Gregorian.

The helpers here write ASCII digits; the output pass (_bidi) puts them
in the reader's digits.
"""

import os
from datetime import datetime

from linecast._calendars import solar_hijri
from linecast._i18n import base_language

GREGORIAN = "gregorian"
SOLAR_HIJRI = "solar_hijri"

# The settings' spellings, as `linecast dates` and LINECAST_DATES take
# them, and the calendar each names.
DATES_CHOICES = ("gregorian", "solar-hijri")
_CHOICE_CALENDAR = {"gregorian": GREGORIAN, "solar-hijri": SOLAR_HIJRI}

# The languages whose civil calendar is not the Gregorian.
CIVIL_OF_LANG = {"fa": SOLAR_HIJRI}


def dates_choice(value):
    """A setting's value as DATES_CHOICES spells it, or None.

    Case and the separator are forgiven: solar_hijri, Solar-Hijri."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower().replace("_", "-")
    return value if value in DATES_CHOICES else None


def resolve_dates(lang, environ=None):
    """(calendar, source) for *lang*: GREGORIAN or SOLAR_HIJRI, and
    "LINECAST_DATES", "config", or "auto"."""
    env = os.environ if environ is None else environ
    choice = dates_choice(env.get("LINECAST_DATES", ""))
    if choice:
        return _CHOICE_CALENDAR[choice], "LINECAST_DATES"
    from linecast._config import saved_dates
    choice = saved_dates()
    if choice:
        return _CHOICE_CALENDAR[choice], "config"
    return CIVIL_OF_LANG.get(base_language(lang or "en"), GREGORIAN), "auto"


def civil_calendar(lang, environ=None):
    """The calendar dates are written in for *lang*: GREGORIAN or
    SOLAR_HIJRI."""
    return resolve_dates(lang, environ)[0]


def is_solar_hijri(lang):
    return civil_calendar(lang) == SOLAR_HIJRI


# ---------------------------------------------------------------------------
# Writing a Solar Hijri date
# ---------------------------------------------------------------------------
# Persian writes the months in full, day before month before year:
# ۱ مهر ۱۴۰۵. Every other language gets the customary transliterations
# (1 Mehr 1405), in the same order, which is how the Solar Hijri date
# is written in English too.

def _as_date(d):
    return d.date() if isinstance(d, datetime) else d


def solar_hijri_month_name(month, lang):
    names = (solar_hijri.MONTH_NAMES_FA if base_language(lang or "en") == "fa"
             else solar_hijri.MONTH_NAMES_EN)
    return names[month - 1]


def solar_hijri_day_month(d, lang):
    """`31 شهریور`: the day and month of the civil date *d*."""
    _year, month, day = solar_hijri.solar_hijri_date(_as_date(d))
    return f"{day} {solar_hijri_month_name(month, lang)}"


def solar_hijri_date_label(d, lang):
    """`1 مهر 1405`: the full date of the civil date *d*."""
    year, month, day = solar_hijri.solar_hijri_date(_as_date(d))
    return f"{day} {solar_hijri_month_name(month, lang)} {year}"


def solar_hijri_month_title(year, month, lang):
    """`مهر 1405`: a month and its year, as a calendar heads it."""
    return f"{solar_hijri_month_name(month, lang)} {year}"


def solar_hijri_day_of_year(d):
    """(day, days in year) of the civil date *d* in its Solar Hijri year."""
    d = _as_date(d)
    year = solar_hijri.solar_hijri_date(d)[0]
    start = solar_hijri.month_start(year, 1)
    total = 366 if solar_hijri.is_leap_year(year) else 365
    return (d - start).days + 1, total


def shift_month(year, month, n):
    """(year, month) *n* Solar Hijri months from *year*/*month*."""
    k = year * 12 + (month - 1) + n
    y, m = divmod(k, 12)
    return y, m + 1
