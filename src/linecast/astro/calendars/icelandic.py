"""The old Icelandic calendar, the misseristal, as the almanac keeps it.

The year is two misseri, summer and winter, made of whole weeks: 52
of them, 364 days, or 53 in a year that takes a leap week, the
sumarauki. Summer begins on a Thursday, the first day of summer
(sumardagurinn fyrsti), and winter on a Saturday, the first day of
winter (fyrsti vetrardagur). Since Iceland changed to the Gregorian
calendar in 1700 the first day of summer has been the first Thursday
after 18 April, so 19 to 25 April, and the rest of the year is
counted from it. Summer runs 26 weeks and two days, winter 25 weeks
and five, so the first day of winter is always 180 days before the
next first day of summer. The leap week goes in whenever the next
first day of summer would otherwise come before 19 April.

Dates were given by the week, never by month and day: "the Tuesday
of the fifth week of winter". The almanac counts each misseri's weeks
from its first day, summer's from Thursday and winter's from
Saturday. Summer's last two days, the veturnætur, stand outside the
count, and winter's 26th week has only five days.

The months, thirty days each, were little used, but the almanac marks
where each begins: Harpa, Skerpla, Sólmánuður, Heyannir, Tvímánuður,
and Haustmánuður in summer; Gormánuður, Ýlir, Mörsugur, Þorri, Góa,
and Einmánuður in winter. Between Sólmánuður and Heyannir come the
four aukanætur, and after them the sumarauki in a year that has one.
The printed almanacs put the sumarauki at the end of summer instead
until 1928, which moved Heyannir, Tvímánuður, and Haustmánuður a week
earlier in those years; this module follows them there. Winter began
on a Friday from the sixteenth century until the almanac restored
Saturday in 1837, which is before any date linecast shows.

A year with the leap week that begins on 20 April, followed by a
Gregorian leap year, puts midsummer and the months after it a day
later than they fall in any other year, until the next leap day. This
is the rímspillir, "the calendar spoiler": 1995, 2023, 2051, once in
28 years, or 40 across a century year that is not a leap year.

The glossary of the University of Iceland's almanac (Almanak Háskóla
Íslands) gives each month's rule and range of dates, and the named
days in NAMED_DAYS. Svante Janson's "The Icelandic calendar" (2010)
gives the arithmetic this module follows, and the tests check it
against his table of every year's month starts.
"""

from datetime import date, timedelta
from functools import lru_cache

SUMMER, WINTER = "summer", "winter"

# The almanac moved the sumarauki back after the aukanætur in 1929.
_LAST_YEAR_LEAP_WEEK_LAST = 1928

# The days the almanac names, by where they fall: key → (misseri,
# days from its first day, days it lasts). A summer offset below zero
# counts back from the first day of winter. The first days of Heyannir,
# Þorri, and Góa are named days too: miðsumar, bóndadagur (also
# midwinter's day), and konudagur. The þrælar are the last days of
# Þorri and Góa; the fardagar, the old moving days, open the seventh
# week of summer; the sumarmál close the winter.
NAMED_DAYS = (
    ("sumardagurinn_fyrsti", SUMMER, 0, 1),
    ("fardagar", SUMMER, 42, 4),
    ("midsumar", SUMMER, "heyannir", 1),
    ("veturnaetur", SUMMER, -2, 2),
    ("fyrsti_vetrardagur", WINTER, 0, 1),
    ("bondadagur", WINTER, 90, 1),
    ("thorrathraell", WINTER, 119, 1),
    ("konudagur", WINTER, 120, 1),
    ("gouthraell", WINTER, 149, 1),
    ("sumarmal", WINTER, 175, 5),
)


def first_day_of_summer(year):
    """Sumardagurinn fyrsti: the first Thursday after 18 April."""
    earliest = date(year, 4, 19)
    return earliest + timedelta(days=(3 - earliest.weekday()) % 7)


def first_day_of_winter(year):
    """Fyrsti vetrardagur of the Icelandic year beginning in *year*:
    the Saturday 180 days before the next first day of summer."""
    return first_day_of_summer(year + 1) - timedelta(days=180)


def has_sumarauki(year):
    """Whether the Icelandic year beginning in *year* takes the leap week."""
    return (first_day_of_summer(year + 1) - first_day_of_summer(year)).days == 371


def icelandic_year(local_date):
    """The Gregorian year in which *local_date*'s Icelandic year began."""
    year = local_date.year
    return year if local_date >= first_day_of_summer(year) else year - 1


@lru_cache(maxsize=64)
def month_starts(year):
    """((key, first day), ...) of the Icelandic year beginning in *year*.

    The months in order, with the aukanætur and, in a year that has
    it, the sumarauki among them where the almanac of the day put it.
    """
    summer = first_day_of_summer(year)
    winter = first_day_of_winter(year)

    def after(start, days):
        return start + timedelta(days=days)

    starts = [("harpa", summer), ("skerpla", after(summer, 30)),
              ("solmanudur", after(summer, 60)),
              ("aukanaetur", after(summer, 90))]
    late = [("heyannir", after(winter, -90)),
            ("tvimanudur", after(winter, -60)),
            ("haustmanudur", after(winter, -30))]
    if has_sumarauki(year):
        if year <= _LAST_YEAR_LEAP_WEEK_LAST:
            late = [(key, after(start, -7)) for key, start in late]
            late.append(("sumarauki", after(winter, -7)))
        else:
            starts.append(("sumarauki", after(summer, 94)))
    starts += late
    starts += [(key, after(winter, 30 * i)) for i, key in enumerate(
        ("gormanudur", "ylir", "morsugur", "thorri", "goa", "einmanudur"))]
    return tuple(starts)


def month_key(local_date):
    """The month (or the aukanætur, or the sumarauki) *local_date* is in."""
    current = None
    for key, start in month_starts(icelandic_year(local_date)):
        if start > local_date:
            break
        current = key
    return current


def next_month_start(local_date):
    """(first day, key) of the month after *local_date*'s."""
    year = icelandic_year(local_date)
    for key, start in (*month_starts(year), *month_starts(year + 1)):
        if start > local_date:
            return start, key
    raise AssertionError("no month start within two years")


def icelandic_week(local_date):
    """(misseri, week) of *local_date*: SUMMER or WINTER, and the week
    counted from the misseri's first day, 1 to 27 in summer and 1 to 26
    in winter. The week is None on the veturnætur, summer's last two
    days, which stand outside the count."""
    year = icelandic_year(local_date)
    winter = first_day_of_winter(year)
    if local_date >= winter:
        return WINTER, (local_date - winter).days // 7 + 1
    if local_date >= winter - timedelta(days=2):
        return SUMMER, None
    return SUMMER, (local_date - first_day_of_summer(year)).days // 7 + 1


@lru_cache(maxsize=64)
def _named_days_of_year(year):
    """[(first day, last day, key)] of the Icelandic year beginning in
    *year*, in order."""
    summer = first_day_of_summer(year)
    winter = first_day_of_winter(year)
    starts = dict(month_starts(year))
    out = []
    for key, misseri, offset, days in NAMED_DAYS:
        if isinstance(offset, str):
            first = starts[offset]
        elif misseri == SUMMER:
            first = (winter if offset < 0 else summer) + timedelta(days=offset)
        else:
            first = winter + timedelta(days=offset)
        out.append((first, first + timedelta(days=days - 1), key))
    return out


def named_day_key(local_date):
    """The named day *local_date* falls within, or None."""
    for first, last, key in _named_days_of_year(icelandic_year(local_date)):
        if first <= local_date <= last:
            return key
    return None


def next_named_day(local_date):
    """(first day, key) of the named day at or after *local_date*.

    A named day in progress counts: on the second day of the
    veturnætur the answer is the veturnætur, with the day they began.
    """
    year = icelandic_year(local_date)
    for y in (year, year + 1):
        for first, last, key in _named_days_of_year(y):
            if local_date <= last:
                return first, key
    raise AssertionError("no named day within two years")
