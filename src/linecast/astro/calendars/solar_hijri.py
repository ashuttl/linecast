"""The Solar Hijri calendar, Iran's civil calendar, from the equinox.

The months are fixed: Farvardin to Shahrivar have 31 days, Mehr to
Bahman 30, and Esfand 29, or 30 when the next year begins a day
later. Nothing else is arithmetic. The year begins with the March
equinox, the moment of تحویل سال, as Iran's law of 11 Farvardin 1304
(31 March 1925) set down, and the Calendar Center of the University
of Tehran's Institute of Geophysics decides the day each year by one
rule: the true (apparent) noon and the equinox are computed for the
official meridian, 52.5° E, and if the equinox falls before that noon
its day is 1 Farvardin; at noon or after, 1 Farvardin is the next day.
So the year begins at the midnight nearest the equinox, in Iran
Standard Time (UTC+3:30, the mean time of 52.5° E; daylight saving
never entered into it).

The noon is the Sun's transit, not 12:00 on the clock. In March the
equation of time puts it near 12:07:30 IRST, and the distinction can
decide a year: the 1930 equinox, near 08:30 UTC, fell within seconds of
12:00 IRST and seven and a half minutes before the transit.
The Persian Wikipedia's article on the calendar (گاه‌شماری هجری
خورشیدی) and the Calendar Center's own descriptions state the true
noon at the official meridian. Borkowski's "The Persian calendar for
3000 years" (Earth, Moon, and Planets 74, 1996) used 12:00 Tehran mean
time (51.42° E) instead, and Heydari-Malayeri's "A concise review of
the Iranian calendar" (2004) says only "noon"; neither changes a year
from 1925 to 2123, and they first part in 2124 (1503 SH), whose
equinox falls two minutes before true noon at 52.5° E and half a
minute after mean noon at Tehran.

The equinox is astro.seasons.season_event_utc, Meeus's series less ΔT (the
IERS values to 2025, the Morrison–Stephenson parabola beyond). Against the
Calendar Center's published instants for 1396–1405 SH it is within
half a minute. The closest year to the line between 1925 and 2123 is
2091 (1470 SH), whose equinox falls four minutes after true noon;
1930 (1309 SH), seven and a half minutes before, is the closest in
the past. Nowruz falls on Borkowski's day in every year 1300–1502
SH, so the leap years 1300–1501 are his, and they are the 33-year
cycle's (the year's remainder mod 33 is 1, 5, 9, 13, 17, 22, 26, or
30), which the equinox happens to follow over those two centuries.
Birashk's 2820-year arithmetic does not: it makes 1404, 1437, and
1470 leap years instead of 1403, 1436, and 1469, so its Nowruz falls
a day early in 2025, 2058, and 2091. This module follows the equinox, as Iran does.

Mehregan is kept on 10 Mehr, where Iran's official calendar prints
it: the old festival was the 16th of Mehr in a calendar of 30-day
months, and the six 31-day months since have moved that day to the
10th. Chaharshanbe Suri is the eve of the year's last Wednesday, so
its date here is the Tuesday, whose evening it is.
"""

from datetime import timedelta, timezone
from functools import lru_cache

from linecast.astro.ephemeris import sun_transit_utc
from linecast.astro.seasons import MARCH_EQUINOX, season_event_utc

# Iran Standard Time, the mean time of the 52.5° E meridian.
IRST = timezone(timedelta(hours=3, minutes=30))
_MERIDIAN_DEG = 52.5
_GREGORIAN_OFFSET = 621        # 1 Farvardin of SH year y falls in March of y + 621

MONTH_NAMES_FA = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
MONTH_NAMES_EN = (
    "Farvardin", "Ordibehesht", "Khordad", "Tir", "Mordad", "Shahrivar",
    "Mehr", "Aban", "Azar", "Dey", "Bahman", "Esfand",
)

# The observances the panel counts down to, (month, day) → key.
# Chaharshanbe Suri moves with the weekday and is found separately.
OBSERVANCES = {
    (1, 1): "nowruz",
    (1, 13): "sizdah_bedar",
    (4, 13): "tirgan",
    (7, 10): "mehregan",
    (9, 30): "yalda",
    (11, 10): "sadeh",
}
CHAHARSHANBE_SURI = "chaharshanbe_suri"
_WEDNESDAY = 2

@lru_cache(maxsize=None)
def nowruz_utc(sh_year):
    """The March equinox that begins *sh_year*, as an aware UTC datetime.

    This is the moment of تحویل سال the countdown runs to; it can fall
    on 1 Farvardin or on the last day of Esfand before it.
    """
    return season_event_utc(sh_year + _GREGORIAN_OFFSET, MARCH_EQUINOX)


def _true_noon_utc(day):
    """The Sun's transit over the 52.5° E meridian on *day*, in UTC."""
    return sun_transit_utc(day, _MERIDIAN_DEG, IRST)


@lru_cache(maxsize=None)
def _nowruz(sh_year):
    """The civil date of 1 Farvardin *sh_year*."""
    equinox = nowruz_utc(sh_year)
    day = equinox.astimezone(IRST).date()
    if equinox < _true_noon_utc(day):
        return day
    return day + timedelta(days=1)


def is_leap_year(year):
    """Whether Esfand *year* has 30 days, making the year 366."""
    return (_nowruz(year + 1) - _nowruz(year)).days == 366


def days_in_month(year, month):
    """How many days *month* of *year* runs."""
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    return 30 if is_leap_year(year) else 29


def _days_before(month):
    """Days in the year before the first of *month*."""
    return 31 * min(month - 1, 6) + 30 * max(month - 7, 0)


def month_start(year, month):
    """The civil date of 1 *month* *year*."""
    return _nowruz(year) + timedelta(days=_days_before(month))


def to_gregorian(year, month, day):
    """The civil date of *day* *month* *year*."""
    if not 1 <= month <= 12 or not 1 <= day <= days_in_month(year, month):
        raise ValueError(f"no such date: {year}-{month}-{day}")
    return month_start(year, month) + timedelta(days=day - 1)


def solar_hijri_date(local_date):
    """(year, month, day) of the civil date *local_date*."""
    year = local_date.year - _GREGORIAN_OFFSET
    if local_date < _nowruz(year):
        year -= 1
    elapsed = (local_date - _nowruz(year)).days
    if elapsed < 186:
        month, day = divmod(elapsed, 31)
    else:
        month, day = divmod(elapsed - 186, 30)
        month += 6
    return year, month + 1, day + 1


def next_month_start(local_date):
    """(civil date, (year, month)) of the month after *local_date*'s."""
    year, month, _day = solar_hijri_date(local_date)
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return month_start(year, month), (year, month)


def chaharshanbe_suri(year):
    """The Tuesday whose evening is the eve of *year*'s last Wednesday."""
    last_day = _nowruz(year + 1) - timedelta(days=1)
    wednesday = last_day - timedelta(days=(last_day.weekday() - _WEDNESDAY) % 7)
    return wednesday - timedelta(days=1)


def _observances_of_year(year):
    """[(civil date, key)] of *year*'s observances, in order."""
    days = [(to_gregorian(year, month, day), key)
            for (month, day), key in OBSERVANCES.items()]
    days.append((chaharshanbe_suri(year), CHAHARSHANBE_SURI))
    return sorted(days)


def observance_key(local_date):
    """The observance falling on *local_date*, or None."""
    year = solar_hijri_date(local_date)[0]
    for day, key in _observances_of_year(year):
        if day == local_date:
            return key
    return None


def next_observance(local_date):
    """(civil date, key) of the first observance at or after *local_date*."""
    year = solar_hijri_date(local_date)[0]
    for yy in (year, year + 1):
        for day, key in _observances_of_year(yy):
            if day >= local_date:
                return day, key
    raise AssertionError("no observance within two years")

