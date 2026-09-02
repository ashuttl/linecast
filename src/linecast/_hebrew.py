"""The Hebrew calendar, by the fixed arithmetic in use since the fourth century.

The Hebrew calendar is lunisolar: months follow the moon, so the
15th falls at the full moon and Rosh Chodesh at the new, and a
thirteenth month, Adar I, is added seven times in nineteen years to
keep Pesach in spring. Nothing in it has depended on observation
since Hillel II fixed the rules: the year begins at the molad of
Tishrei, the mean conjunction counted in parts of 1/1080 of an hour
from the calendar's epoch, moved by up to two days by the four
postponement rules (the dehiyyot), which keep Yom Kippur off Friday
and Sunday and Hoshana Rabbah off Saturday. The year's length, 353
to 385 days, then decides whether Cheshvan and Kislev run 29 or 30
days. This module is Dershowitz and Reingold's *Calendrical
Calculations* restated in Python; Hebcal is the check, and the tests
pin every month of 5780 through 5790 against it.

Months are numbered the traditional way, Nisan first: Tishrei, the
new year, is the seventh month, Adar the twelfth, and in a leap year
Adar I is the twelfth and Adar II the thirteenth. Dates are proleptic
Gregorian, in the reader's own day.

The Hebrew day begins at sunset. The panel turns the date with the
reader's own sunset (_hijri.after_sunset, shared with the Islamic
calendar, which keeps the same evening); the month grid and the
holiday dates keep civil days, the way printed calendars do. The
holidays are the diaspora observance — a second day of Rosh Hashanah,
Sukkot, Shavuot, and Pesach's first and last days, and Simchat Torah
the day after Shemini Atzeret — since that is what a reader outside
Israel keeps.
"""

from datetime import date, timedelta
from functools import lru_cache

# 1 Tishrei 1 AM, Monday 7 October 3761 BCE (Julian), as a Python
# ordinal (Rata Die), and the mean lunation in parts of 1/25920 day.
_EPOCH = -1373427
_MONTH_PARTS = 29 * 25920 + 13753        # 29d 12h 793p
_NISAN, _TISHREI, _KISLEV, _SHEVAT, _ADAR, _ADAR_II = 1, 7, 9, 11, 12, 13
_MEAN_YEAR_DAYS = 35975351 / 98496       # 235 lunations over 19 years

# The holidays the panel counts down to, in calendar order from
# Tishrei: key → (month, day, days). "adar" is the month Purim falls
# in, Adar II when the year has two. Tisha B'Av is postponed a day
# when the 9th of Av is a Saturday.
HOLIDAYS = (
    ("rosh_hashanah", 7, 1, 2),
    ("yom_kippur", 7, 10, 1),
    ("sukkot", 7, 15, 7),
    ("shemini_atzeret", 7, 22, 1),
    ("simchat_torah", 7, 23, 1),
    ("hanukkah", 9, 25, 8),
    ("tu_bishvat", 11, 15, 1),
    ("purim", "adar", 14, 1),
    ("pesach", 1, 15, 8),
    ("shavuot", 3, 6, 2),
    ("tisha_bav", 5, 9, 1),
)


def is_leap_year(year):
    """Whether *year* has thirteen months (seven of every nineteen)."""
    return (7 * year + 1) % 19 < 7


def _months_before(year):
    """Lunations from the epoch to the molad of Tishrei *year*."""
    return (235 * year - 234) // 19


@lru_cache(maxsize=1024)
def _elapsed_days(year):
    """Days from the epoch to 1 Tishrei *year*, before the length rules.

    The molad of Tishrei, with the postponements that act on it alone:
    to the next day when the molad falls at noon or later, and off
    Sunday, Wednesday, and Friday.
    """
    months = _months_before(year)
    parts = 12084 + 13753 * months
    day = 29 * months + parts // 25920
    if (3 * (day + 1)) % 7 < 3:
        day += 1
    return day


def _year_start_offset(year):
    """The two postponements that keep a year from running 356 or 382 days."""
    this = _elapsed_days(year)
    if _elapsed_days(year + 1) - this == 356:
        return 2
    if this - _elapsed_days(year - 1) == 382:
        return 1
    return 0


@lru_cache(maxsize=1024)
def _new_year(year):
    """The ordinal of 1 Tishrei *year*."""
    return _EPOCH + _elapsed_days(year) + _year_start_offset(year)


def days_in_year(year):
    return _new_year(year + 1) - _new_year(year)


def days_in_month(year, month):
    """How many days *month* of *year* runs, 29 or 30."""
    if month in (2, 4, 6, 10, 13):
        return 29
    if month == _ADAR and not is_leap_year(year):
        return 29
    length = days_in_year(year)
    if month == 8 and length not in (355, 385):       # Cheshvan
        return 29
    if month == _KISLEV and length in (353, 383):
        return 29
    return 30


def _last_month(year):
    return _ADAR_II if is_leap_year(year) else _ADAR


def _months_of_year(year):
    """The months of *year* in the order they fall, Tishrei first."""
    return list(range(_TISHREI, _last_month(year) + 1)) + list(range(1, _TISHREI))


def _ordinal(year, month, day):
    """The ordinal of a Hebrew date."""
    days = _new_year(year) + day - 1
    for m in _months_of_year(year):
        if m == month:
            break
        days += days_in_month(year, m)
    return days


def month_start(year, month):
    """The civil date of the first of *month* *year*."""
    return date.fromordinal(_ordinal(year, month, 1))


@lru_cache(maxsize=512)
def hebrew_date(local_date):
    """(year, month, day) of the Hebrew date whose daylight is *local_date*."""
    ordinal = local_date.toordinal()
    year = int((ordinal - _EPOCH) // _MEAN_YEAR_DAYS)
    while _new_year(year + 1) <= ordinal:
        year += 1
    for month in _months_of_year(year):
        start = _ordinal(year, month, 1)
        if ordinal < start + days_in_month(year, month):
            return year, month, ordinal - start + 1
    raise AssertionError("a day outside every month of its year")


def next_month_start(local_date):
    """(civil date, (year, month)) of the Hebrew month after *local_date*'s."""
    year, month, _day = hebrew_date(local_date)
    months = _months_of_year(year)
    i = months.index(month) + 1
    if i == len(months):
        year, month = year + 1, _TISHREI
    else:
        month = months[i]
    return month_start(year, month), (year, month)


def rosh_chodesh(local_date):
    """(year, month) of the month whose Rosh Chodesh *local_date* is, or None.

    A month's first day, and the thirtieth of the month before when it
    has one. Tishrei has none: its first day is Rosh Hashanah.
    """
    year, month, day = hebrew_date(local_date)
    if day == 1 and month != _TISHREI:
        return year, month
    if day == 30:
        return next_month_start(local_date)[1]
    return None


@lru_cache(maxsize=64)
def _holidays_of_year(year):
    """[(first civil date, last civil date, key)] of *year*, in order."""
    out = []
    for key, month, day, days in HOLIDAYS:
        if month == "adar":
            month = _last_month(year)
        first = date.fromordinal(_ordinal(year, month, day))
        if key == "tisha_bav" and first.weekday() == 5:
            first += timedelta(days=1)
        out.append((first, first + timedelta(days=days - 1), key))
    return out


def holiday_key(local_date):
    """The holiday *local_date* falls within, or None."""
    year = hebrew_date(local_date)[0]
    for first, last, key in _holidays_of_year(year):
        if first <= local_date <= last:
            return key
    return None


def next_holiday(local_date):
    """(first civil date, key) of the holiday at or after *local_date*.

    A holiday in progress counts: on the third day of Sukkot the
    answer is Sukkot, with the day it began.
    """
    year = hebrew_date(local_date)[0]
    for y in (year, year + 1):
        for first, last, key in _holidays_of_year(y):
            if local_date <= last:
                return first, key
    raise AssertionError("no holiday within two years")
