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

The almanac names six moons, the tunglheiti, each from the new moon
that lights it to the next. The jólatungl is the moon Epiphany (6
January) falls in, and the páskatungl the moon Easter falls in. The
two before the páskatungl are the þorratungl and the góutungl, the
second before the jólatungl is the vetrartungl, and the one after the
páskatungl is the sumartungl. When Easter comes late and three moons
fall between the jólatungl and the páskatungl, the first of them is
the aukatungl, the extra moon. The rest of the moons, from early
summer into autumn, and the one between the vetrartungl and the
jólatungl, go unnamed. The almanac prints each name at the true new moon, but finds
the jólatungl by the church's tables, the epacts Easter is reckoned
by, which have the moon new a day or two after it truly is: a moon
new on Epiphany itself is usually new by the tables only after it,
so it is not the jólatungl. That is how the aukatungl comes about. In
the years whose epact is 24 (2000, 2019, 2038) the tables put
Epiphany in December's moon and Easter in April's, and the true moon
new on 5 or 6 January is the aukatungl. For a time the almanac took
the vetrartungl to be the moon in the sky on All Saints' Day; this
module keeps the present rule throughout.

The glossary of the University of Iceland's almanac (Almanak Háskóla
Íslands) gives each month's rule and range of dates, the named days
in NAMED_DAYS, and the rules for the moons. Svante Janson's "The
Icelandic calendar" (2010) gives the arithmetic this module follows,
and the tests check it against his table of every year's month starts.
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from linecast.astro.ephemeris import next_moon_phase_utc

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


def _epact(year):
    """The Gregorian epact of *year*: the moon's age on 1 January by the
    church's tables, 0 to 29, from the golden number and the solar and
    lunar corrections."""
    golden = year % 19 + 1
    century = year // 100 + 1
    solar = 3 * century // 4 - 12
    lunar = (8 * century + 5) // 25 - 5
    return (11 * golden + 20 + lunar - solar) % 30


def easter(year):
    """Easter Sunday: the first Sunday after the tables' full moon on or
    after 21 March."""
    epact = _epact(year)
    # The tables' April moon has 29 days, so epacts 24 and 25 share its
    # new moon, and 25 in the later years of the cycle takes 26's.
    if epact == 24 or (epact == 25 and year % 19 > 10):
        epact += 1
    full = date(year, 3, 1) + timedelta(days=43 - epact)
    if full < date(year, 3, 21):
        full += timedelta(days=30)
    return full + timedelta(days=7 - (full.weekday() + 1) % 7)


def _tables_epiphany_moon(year):
    """The day the tables' moon that Epiphany falls in is new: January's,
    when the epact puts it on the 6th or before, otherwise December's.
    January's is exact (its 30 days take the epacts in turn, from 29 on
    the 2nd to 1 on the 30th); December's is to within a day, which is
    near enough to find the true new moon by."""
    epact = _epact(year)
    new = date(year, 1, 31 - epact) if epact else date(year, 1, 1)
    return new if new.day <= 6 else new - timedelta(days=30)


def _utc(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _next_new_moon(moment):
    # A lunation is never shorter than 29.2 days, so the search can
    # start 25 days on.
    return next_moon_phase_utc(moment + timedelta(days=25), 0.0)


def _previous_new_moon(moment):
    return next_moon_phase_utc(moment - timedelta(days=25), 0.0, backwards=True)


@lru_cache(maxsize=16)
def named_moons(year):
    """((new moon, key), ...) of the moons the almanac names around the
    Easter of *year*, in order: the vetrartungl, lit in the autumn
    before, to the sumartungl. The new moons are UTC datetimes."""
    # The true new moon comes up to three days before the tables' one.
    # Easter falls 15 to 21 days into the tables' moon, so the true new
    # moon before it is at least 12 days back, and the one after it is
    # later than Easter.
    jol = next_moon_phase_utc(_utc(_tables_epiphany_moon(year))
                              + timedelta(days=5), 0.0, backwards=True)
    paska = next_moon_phase_utc(_utc(easter(year)) - timedelta(days=12),
                                0.0, backwards=True)
    between = []
    moon = _next_new_moon(jol)
    while moon < paska - timedelta(days=1):
        between.append(moon)
        moon = _next_new_moon(moon)
    keys = ("aukatungl", "thorratungl", "goutungl")[-len(between):]
    return ((_previous_new_moon(_previous_new_moon(jol)), "vetrartungl"),
            (jol, "jolatungl"),
            *zip(between, keys),
            (paska, "paskatungl"),
            (_next_new_moon(paska), "sumartungl"))


def lit_moon_key(new_moon):
    """The name of the moon *new_moon* lights, or None; *new_moon* is an
    aware datetime of a new moon, however it was found."""
    new_moon = new_moon.astimezone(timezone.utc)
    for year in (new_moon.year, new_moon.year + 1):
        for moment, key in named_moons(year):
            if abs(moment - new_moon) < timedelta(days=1):
                return key
    return None


def moon_key(moment):
    """The name of the moon *moment* (an aware datetime) falls in, or
    None: the moon lit at the last new moon, until the next."""
    return lit_moon_key(next_moon_phase_utc(
        moment.astimezone(timezone.utc), 0.0, backwards=True))


def next_named_moon(moment):
    """(new moon, key) of the next named moon lit after *moment*, an
    aware datetime; the new moon is in UTC."""
    moment = moment.astimezone(timezone.utc)
    for year in (moment.year, moment.year + 1):
        for new_moon, key in named_moons(year):
            if new_moon > moment:
                return new_moon, key
    raise AssertionError("no named moon within a year")
